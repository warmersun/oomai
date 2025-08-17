import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import yaml
from collections import namedtuple
import re
from lark import Lark, ParseError
# drivers
from neo4j import AsyncGraphDatabase
from openai import AsyncOpenAI
from groq import AsyncGroq
from xai_sdk import AsyncClient
from xai_sdk.chat import SearchParameters, system, user, tool, tool_result
from xai_sdk.search import rss_source, x_source
from neo4j.time import Date, DateTime
# tools
from function_tools import (
    core_execute_cypher_query,
    core_create_node,
    core_create_edge,
    core_find_node,
    GraphOpsCtx,
)

class Neo4jDateEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (Date, DateTime)):
            return o.iso_format()  # Convert Neo4j Date/DateTime to ISO 8601 string
        return super().default(o)

with open("knowledge_graph/schema.md", "r") as f:
    schema = f.read()

embedding_model = "text-embedding-3-large"
llm_model = "grok-3-mini"

LAST_RUN_FILE = "last_run_timestamp.txt"


def _load_last_run() -> Optional[datetime]:
    if not os.path.exists(LAST_RUN_FILE):
        return None
    try:
        with open(LAST_RUN_FILE, "r") as f:
            ts = f.read().strip()
        if not ts:
            return None
        return datetime.fromisoformat(ts)
    except Exception as exc:
        logging.error(f"Failed to read {LAST_RUN_FILE}: {exc}")
        return None


def _save_last_run(dt: datetime) -> None:
    try:
        with open(LAST_RUN_FILE, "w") as f:
            f.write(dt.isoformat())
    except Exception as exc:
        logging.error(f"Failed to write {LAST_RUN_FILE}: {exc}")


def _build_search_params(source: Optional[Dict[str, Any]] = None) -> Optional[SearchParameters]:
    if not source:
        return None

    last_run = _load_last_run()
    params: Dict[str, Any] = {"mode": "on"}
    if last_run is not None:
        params["from_date"] = last_run

    if source.get("source_type") == "RSS" and "url" in source:
        return SearchParameters(
            **params,
            sources=[rss_source([source["url"]])],
        )
    if source.get("source_type") == "X" and "handles" in source:
        return SearchParameters(
            **params,
            sources=[x_source(included_x_handles=source["handles"])],
        )
    return None


cypher_query_tool = tool(
    name="cypher_query",
    description=(
        """
        Executes the provided Cypher query against the Neo4j database and returns the results.
        """
    ),
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string", "description": "The Cypher query to execute."}},
        "required": ["query"],
    },
)

create_node_tool = tool(
    name="create_node",
    description="""
    Creates or updates a node in the Neo4j knowledge graph, ensuring no duplicates by checking for similar nodes based on their descriptions.
    If a similar node exists, it updates the node with a merged description. If not, it creates a new node.
    Returns the node's elementId (a unique string identifier).
    Use this tool to add or update nodes like technologies, capabilities, or parties in the graph.
    Provide the node type, a short name, and a detailed description.
    """,
    parameters={
        "type": "object",
        "properties": {
            "node_type": {"type": "string", "description": "The type of node (e.g., 'EmTech', 'Capability', 'Party')."},
            "name": {"type": "string", "description": "A short, unique name for the node."},
            "description": {"type": "string", "description": "A detailed description of the node."},
        },
        "required": ["node_type", "name", "description"],
    },
)

create_edge_tool = tool(
    name="create_edge",
    description="""
    Creates or merges a directed relationship (edge) between two existing nodes in the Neo4j knowledge graph.
    If the relationship doesn't exist, it creates it; if it does, it matches the existing one.
    Use this tool to connect nodes, such as linking an emerging technology to a capability it enables.
    Provide the source and target node elementIds, the relationship type, and optional properties for the edge.
    Returns the relationship object.
    """,
    parameters={
        "type": "object",
        "properties": {
            "source_id": {"type": "string", "description": "The elementId of the source node."},
            "target_id": {"type": "string", "description": "The elementId of the target node."},
            "relationship_type": {"type": "string", "description": "The type of relationship (e.g., 'ENABLES', 'USES', 'RELATES_TO')."},
            "properties": {"type": "object", "description": "Optional additional properties for the relationship (e.g., {'explanation': 'details'})."},
        },
        "required": ["source_id", "target_id", "relationship_type"],
    },
)

find_node_tool = tool(
    name="find_node",
    description="""
    Finds nodes in knowledge graph that are similar to a given query text.
    Uses vector similarity search based on node descriptions.
    Returns a list of nodes with their names, descriptions, and similarity scores.
    """,
    parameters={
        "type": "object",
        "properties": {
            "query_text": {"type": "string", "description": "The text to search for similar nodes."},
            "node_type": {"type": "string", "description": "The type of node to search for.", "enum": ["Convergence", "Capability", "Milestone", "Trend", "Idea", "LTC", "LAC"]},
            "top_k": {"type": "integer", "description": "The number of top results to return (default is 5).", "default": 5},
        },
        "required": ["query_text", "node_type"],
    },
)


async def run_chat(
    prompt: str,
    *, 
    search_parameters: Optional[SearchParameters], 
    xai_client: AsyncClient, 
    neo4jdriver, 
    openai_client: AsyncOpenAI, 
    groq_client: AsyncGroq, 
    parser: Lark
) -> str:
    chat_kwargs = dict(
        model=llm_model,
        messages=[
            system(
                f"""
                You are a thorough analyst that builds a knowledge graph.
                You search on X and RSS feeds for the latest news and articles about emerging technologies, products, services, capabilities, milestones, trends, ideas, use cases, and applications.

                - When provided with a story, an article or document, decompose its content into nodes and relationships for the knowledge graph, using `create_node` and `create_edge`.
                - Use `execute_cypher_query` and `find_node` tools to check what is already in the knowledge graph so you can connect the newly added nodes to existing ones.
                - The `create_node` tool merges similar semantic descriptions to handle duplicates.
                - Ensure every product or service (PTC) is connected to relevant Capabilities and Milestones.
                - Where categorization is missing (e.g. in articles or news), create or identify and link abstract entities (LAC, LTC).
                - Never use the `execute_cypher_query` to batch create nodes and edges. Only use `create_node` and `create_edge` for this purpose.

                # Context

                - The schema for the knowledge graph is:
                  {schema}
                - All graph operations occur within a single Neo4j transaction; this ensures you may utilize the `elementId()` function for node identification. This is not an `elementId` property, but a function call, such as: `MATCH (n:EmTech {{name: 'computing'}}) RETURN elementId(n) AS elementId`.
                - Write Cypher queries with explicit node labels and relationship types for clarity.
                - Limit the number of results for each query.

                # Output Format

                - You carry out the instructions and provide a summary of the actions taken and the results obtained. 
                - There is no user interaction. You do not ask for confirmation or additional information.
                - You are used within a script, so you have one shot to get it right.

                # Stop Conditions

                - Consider the task complete when you have captured all relevant information into the knowledge graph.
            """
            )
        ],
        tools=[cypher_query_tool, create_node_tool, create_edge_tool, find_node_tool],
    )
    if search_parameters is not None:
        chat_kwargs["search_parameters"] = search_parameters

    chat = xai_client.chat.create(**chat_kwargs)
    chat.append(user(prompt))

    max_retries = 3
    cypher_retries = 0
    edge_retries = 0

    while True:
        response = await chat.sample()
        chat.append(response)

        if not response.tool_calls:
            break

        tool_executed = False
        async with neo4jdriver.session() as session:
            tx = await session.begin_transaction()
            lock = asyncio.Lock()
            ctx = GraphOpsCtx(tx, lock)
            tool_name = "unknown"
            Property = namedtuple('Property', ['key', 'value'])
            id_pattern = re.compile(r'^\d+:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}:\d+$', re.IGNORECASE)
            try:
                for tool_call in response.tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = json.loads(tool_call.function.arguments)
                    if tool_name == "cypher_query":
                        if cypher_retries >= max_retries:
                            logging.error("Max retries for Cypher query reached")
                            chat.append(tool_result(json.dumps({"error": "Max retries for Cypher query reached"})))
                            continue
                        query = tool_args["query"]
                        try:
                            parser.parse(query)
                        except ParseError as e:
                            cypher_retries += 1
                            logging.warning(f"Cypher query validation failed:\n---\n{query}\n---\nRetrying...")
                            chat.append(tool_result(json.dumps({"error": f"Cypher query validation failed: {str(e)}. Please correct and try again."})))
                            continue
                        results = await core_execute_cypher_query(
                            ctx, 
                            query
                        )
                        logging.info(f"[CYPHER_QUERY] results: {results}")
                        chat.append(tool_result(json.dumps(results, cls=Neo4jDateEncoder)))
                        tool_executed = True
                    elif tool_name == "create_node":
                        result = await core_create_node(
                            ctx, 
                            tool_args["node_type"], 
                            tool_args["name"], 
                            tool_args["description"], 
                            groq_client,
                            openai_client,
                        )
                        logging.info(f"[CREATE_NODE] result: {result}")
                        chat.append(tool_result(json.dumps(result, cls=Neo4jDateEncoder)))
                        tool_executed = True
                    elif tool_name == "create_edge":
                        if edge_retries >= max_retries:
                            logging.error("Max retries for create_edge reached")
                            chat.append(tool_result(json.dumps({"error": "Max retries for create_edge reached"})))
                            continue
                        source_id = tool_args["source_id"]
                        target_id = tool_args["target_id"]
                        if not id_pattern.match(source_id) or not id_pattern.match(target_id):
                            edge_retries += 1
                            logging.warning(f"Invalid element ID format for source_id '{source_id}' or target_id '{target_id}'. Retrying...")
                            chat.append(tool_result(json.dumps({"error": f"Invalid element ID format for source_id '{source_id}' or target_id '{target_id}'. Please provide valid element IDs from previous queries or creations."})))
                            continue
                        properties = tool_args.get("properties", {})
                        properties_list = [Property(k, v) for k, v in properties.items()]
                        result = await core_create_edge(
                            ctx,
                            source_id,
                            target_id,
                            tool_args["relationship_type"],
                            properties_list,
                        )
                        logging.info(f"[CREATE_EDGE] result: {result}")
                        chat.append(tool_result(json.dumps(result, cls=Neo4jDateEncoder)))
                        tool_executed = True
                    elif tool_name == "find_node":
                        results = await core_find_node(
                            ctx,
                            tool_args["query_text"],
                            tool_args["node_type"],
                            tool_args.get("top_k", 5),
                            openai_client,
                        )
                        logging.info(f"[FIND_NODE] results length: {len(results)}")
                        chat.append(tool_result(json.dumps(results, cls=Neo4jDateEncoder)))
                        tool_executed = True
                if tool_executed:
                    logging.info("Tool executed, committing the Neo4j transaction.")
                    await tx.commit()
                else:
                    logging.error("No tool executed, rolling back the Neo4j transaction.")
                    await tx.rollback()
            except Exception as e:
                logging.error(f"Error executing tool {tool_name}: {e}")
                chat.append(tool_result(json.dumps({"error": str(e)})))
                if tx is not None:
                    logging.error("Rolling back the Neo4j transaction.")
                    await tx.rollback()
            finally:
                if tx is not None:
                    await tx.close()

    logging.info(f"Final response: {response.content}")
    logging.info(f"Finish reason: {response.finish_reason}")
    logging.info(f"Reasoning tokens: {response.usage.reasoning_tokens}")
    logging.info(f"Total tokens: {response.usage.total_tokens}")

    return response.content
async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    neo4jdriver = AsyncGraphDatabase.driver(os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]))
    await neo4jdriver.verify_connectivity()

    xai_client = AsyncClient(api_key=os.getenv("XAI_API_KEY"), timeout=3600)
    openai_client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

    with open('knowledge_graph/cypher.cfg', 'r') as f:
        grammar = f.read()
    parser = Lark(grammar, start='start', parser='earley')

    with open("knowledge_graph/batch_sources.yaml", "r") as f:
        config = yaml.safe_load(f)

    for source in config.get("sources", []):
        params = _build_search_params(source)
        prompt = source.get("prompt", "")
        logging.info(f"Processing {source.get('name')} with params {params}")
        result = await run_chat(prompt, search_parameters=params, xai_client=xai_client, neo4jdriver=neo4jdriver, openai_client=openai_client, groq_client=groq_client, parser=parser)
        logging.info(f"Processed {source.get('name')}: {result}")

    _save_last_run(datetime.now(timezone.utc))
    await neo4jdriver.close()


if __name__ == "__main__":
    asyncio.run(main())