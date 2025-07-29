import asyncio
import os
import json
import yaml
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from neo4j import AsyncGraphDatabase, AsyncTransaction
from neo4j.exceptions import CypherSyntaxError, Neo4jError
from openai import AsyncOpenAI
from pydantic import BaseModel

from xai_sdk import AsyncClient
from xai_sdk.chat import SearchParameters, system, user, tool_result, tool
from xai_sdk.search import rss_source, x_source

# Load schema used in system prompt
with open("knowledge_graph/schema.md", "r") as f:
    SCHEMA = f.read()

# Model names
EMBEDDING_MODEL = "text-embedding-3-large"
LLM_MODEL = "grok-4"

# File used to persist the timestamp of the last batch run
LAST_RUN_FILE = "last_run_timestamp.txt"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _load_last_run() -> Optional[datetime]:
    """Return the timestamp of the previous batch run if available."""
    if not os.path.exists(LAST_RUN_FILE):
        return None
    try:
        with open(LAST_RUN_FILE, "r") as f:
            ts = f.read().strip()
        if not ts:
            return None
        return datetime.fromisoformat(ts)
    except Exception as exc:  # pragma: no cover - best effort logging
        logger.error(f"Failed to read {LAST_RUN_FILE}: {exc}")
        return None


def _save_last_run(dt: datetime) -> None:
    """Persist the provided timestamp for the next batch run."""
    try:
        with open(LAST_RUN_FILE, "w") as f:
            f.write(dt.isoformat())
    except Exception as exc:  # pragma: no cover - best effort logging
        logger.error(f"Failed to write {LAST_RUN_FILE}: {exc}")


def _build_search_params(source: Optional[Dict[str, Any]] = None) -> Optional[SearchParameters]:
    """Create SearchParameters from a source config dict."""
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


async def execute_cypher_query(tx: AsyncTransaction, query: str) -> list:
    """Execute a Cypher query and return the results without embeddings."""

    def filter_embedding(obj):
        if isinstance(obj, dict):
            return {k: filter_embedding(v) for k, v in obj.items() if k != "embedding"}
        if isinstance(obj, list):
            return [filter_embedding(item) for item in obj]
        return obj

    try:
        result = await tx.run(query)
        records = await result.data()
        return [filter_embedding(record) for record in records]
    except Neo4jError as e:
        logger.error(f"Neo4j error executing query: {e}")
        raise RuntimeError(f"Error executing query: {e}")
    except Exception as e:
        logger.error(f"Unexpected error executing query: {e}")
        raise RuntimeError(f"Unexpected error executing query: {e}")


async def merge_node(tx: AsyncTransaction, node_type: str, name: str, description: str) -> str:
    query = f"""
    MERGE (n:`{node_type}` {{name: $name}})
    SET n.description = $description
    RETURN elementId(n) AS node_id
    """
    result = await tx.run(query, name=name, description=description)
    record = await result.single()
    if record is None:
        raise RuntimeError("Failed to merge node")
    return record["node_id"]


async def smart_upsert(
    tx: AsyncTransaction,
    node_type: str,
    name: str,
    description: str,
    *,
    xai_client: AsyncClient,
    openai_client: AsyncOpenAI,
) -> str:
    index_name = f"{node_type.lower()}_description_embeddings"

    class CompareResult(BaseModel):
        different: bool
        name: Optional[str] = None
        description: Optional[str] = None

    emb_response = await openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=description,
    )
    new_embedding = emb_response.data[0].embedding

    similar_query = """
    CALL db.index.vector.queryNodes($index_name, 100, $vector)
    YIELD node, score
    WHERE score >= 0.8
    RETURN elementId(node) AS node_id, node.name AS name, node.description AS description, score
    ORDER BY score DESC
    LIMIT 10
    """
    similar_result = await tx.run(similar_query, index_name=index_name, vector=new_embedding)
    similar_nodes: List[Dict[str, Union[str, float]]] = await similar_result.data()

    found_same_id = None
    updated_name = name
    updated_description = description
    for sim in similar_nodes:
        old_name = sim["name"]
        old_desc = sim["description"]
        logger.info("Checking similarity with node %s (score: %.2f)", sim["node_id"], sim["score"])
        compare_prompt = (
            "Determine whether the following two nodes represent the same concept. "
            "If they are the same, provide a short improved name and a merged description. "
            "Respond in JSON matching this schema: {different: bool, name?: string, description?: string}."
        )
        chat = xai_client.chat.create(model=LLM_MODEL, temperature=0.0)
        chat.append(system(compare_prompt))
        chat.append(
            user(
                f"Node A name: {old_name}\nNode A description: {old_desc}\n\n"
                f"Node B name: {name}\nNode B description: {description}"
            )
        )
        try:
            _, result = await chat.parse(CompareResult)
        except Exception as e:  # pragma: no cover - best effort logging
            logger.warning(f"Failed to parse LLM response: {e}")
            continue
        if not result.different:
            found_same_id = sim["node_id"]
            updated_name = result.name or old_name
            updated_description = result.description or description
            break

    if found_same_id:
        logger.info("Found semantically equivalent node with id: %s", found_same_id)
        logger.info("Updated name: %s", updated_name)
        logger.info("Updated description: %s", updated_description)
        updated_emb_response = await openai_client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=updated_description,
        )
        updated_embedding = updated_emb_response.data[0].embedding
        update_query = """
        MATCH (n)
        WHERE elementId(n) = $node_id
        SET n.name = $name, n.description = $description, n.embedding = $embedding
        RETURN elementId(n) AS id
        """
        update_result = await tx.run(
            update_query,
            node_id=found_same_id,
            name=updated_name,
            description=updated_description,
            embedding=updated_embedding,
        )
        update_record = await update_result.single()
        if update_record is None:
            raise RuntimeError(f"Failed to update node with elementId: {found_same_id}")
        return update_record["id"]

    logger.info("No semantically equivalent node found, creating a new node.")
    create_query = f"""
    CREATE (n:`{node_type}` {{name: $name, description: $description, embedding: $embedding}})
    RETURN elementId(n) AS id
    """
    create_result = await tx.run(create_query, name=name, description=description, embedding=new_embedding)
    create_record = await create_result.single()
    if create_record is None:
        raise RuntimeError("Failed to create new node")
    return create_record["id"]


async def create_node(
    tx: AsyncTransaction,
    node_type: str,
    name: str,
    description: str,
    *,
    xai_client: AsyncClient,
    openai_client: AsyncOpenAI,
) -> str:
    if node_type in ["Convergence", "Capability", "Milestone", "Trend", "Idea", "LTC", "LAC"]:
        return await smart_upsert(
            tx,
            node_type,
            name,
            description,
            xai_client=xai_client,
            openai_client=openai_client,
        )
    if node_type == "EmTech":
        return "Do not create new EmTech type nodes. EmTechs are reference data, use existing ones."
    return await merge_node(tx, node_type, name, description)


async def create_edge(
    tx: AsyncTransaction,
    source_id: str,
    target_id: str,
    relationship_type: str,
    properties: Optional[Dict[str, Any]] = None,
) -> Any:
    if properties is None:
        properties = {}
    prop_keys = ", ".join(f"{key}: ${key}" for key in properties)
    prop_str = f"{{{prop_keys}}}" if prop_keys else ""
    query = (
        "MATCH (source) WHERE elementId(source) = $source_id "
        "MATCH (target) WHERE elementId(target) = $target_id "
        f"MERGE (source)-[r:{relationship_type} {prop_str}]->(target) "
        "RETURN r"
    )
    params = {"source_id": source_id, "target_id": target_id}
    params.update(properties)
    result = await tx.run(query, **params)
    record = await result.single()
    return record.data() if record else None


async def find_node(
    tx: AsyncTransaction,
    query_text: str,
    node_type: str,
    top_k: int = 5,
    *,
    openai_client: AsyncOpenAI,
) -> list:
    emb_response = await openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=query_text,
    )
    query_embedding = emb_response.data[0].embedding
    cypher_query = """
    CALL db.index.vector.queryNodes($index_name, $top_k, $embedding)
    YIELD node, score
    RETURN {name: node.name, description: node.description} AS node, score
    ORDER BY score DESC
    """
    result = await tx.run(
        cypher_query,
        index_name=f"{node_type.lower()}_description_embeddings",
        top_k=top_k,
        embedding=query_embedding,
    )
    records = []
    async for record in result:
        records.append(record.data())
    return records


CYTHER_QUERY_TOOL = tool(
    name="cypher_query",
    description="Executes the provided Cypher query against the Neo4j database and returns the results.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The Cypher query to execute."},
        },
        "required": ["query"],
    },
)

CREATE_NODE_TOOL = tool(
    name="create_node",
    description="Creates or updates a node in the knowledge graph and returns its elementId.",
    parameters={
        "type": "object",
        "properties": {
            "node_type": {"type": "string"},
            "name": {"type": "string"},
            "description": {"type": "string"},
        },
        "required": ["node_type", "name", "description"],
    },
)

CREATE_EDGE_TOOL = tool(
    name="create_edge",
    description="Create or merge a relationship between two nodes.",
    parameters={
        "type": "object",
        "properties": {
            "source_id": {"type": "string"},
            "target_id": {"type": "string"},
            "relationship_type": {"type": "string"},
            "properties": {"type": "object", "additionalProperties": True},
        },
        "required": ["source_id", "target_id", "relationship_type"],
    },
)

FIND_NODE_TOOL = tool(
    name="find_node",
    description="Find nodes similar to the provided query text.",
    parameters={
        "type": "object",
        "properties": {
            "query_text": {"type": "string"},
            "node_type": {"type": "string", "enum": ["Convergence", "Capability", "Milestone", "Trend", "Idea"]},
            "top_k": {"type": "integer", "default": 5},
        },
        "required": ["query_text", "node_type"],
    },
)


async def run_chat_batch(
    prompt: str,
    *,
    neo4jdriver,
    xai_client: AsyncClient,
    openai_client: AsyncOpenAI,
    search_parameters: Optional[SearchParameters] = None,
    stream: bool = False,
) -> str:
    chat_kwargs = dict(
        model=LLM_MODEL,
        messages=[
            system(
                f"""
            You are a helpful assistant that can build a knowledge graph and then use it to answer questions.

            The knowledge graph has the following schema:
            {SCHEMA}

            You work in two possible modes:

            1. You can answer questions based on the knowledge graph. You can only use the `cypher_query` and `find_node` tools.
            You help the user to traverse the graph and find related nodes or edges but always talk in a simple, natural tone. The user does not need to know anything about the graph schema. Don't mention nodes, edges, node and edge types to the user. Just use what responses you receive from the knowledge graph and make it interesting and fun.
            Occasionally you may discover that a connection is missing. In that case, you can use the `create_edge` tool to add it.

            2. When you are given an article to process you break it down to nodes in the knowledge graph and connect them with edges to capture relationships. You can use the `create_node` and `create_edge` tools. You can also use the `cypher_query` and `find_node` tools to look for nodes. The `create_node` tool is smart and will avoid duplicates by merging their descriptions if similar semantics already exist.

            ---

            Note: there is no elementId property. Use the elementId function to get the elementId of a node or edge. e.g.
            MATCH (n:EmTech {{name: 'computing'}}) RETURN elementId(n) AS elementId
            """
            )
        ],
        tools=[CYTHER_QUERY_TOOL, CREATE_NODE_TOOL, CREATE_EDGE_TOOL, FIND_NODE_TOOL],
    )
    if search_parameters is not None:
        chat_kwargs["search_parameters"] = search_parameters
    chat = xai_client.chat.create(**chat_kwargs)
    chat.append(user(prompt))

    stream_gen = chat.stream()
    response = None
    async for streamed_response, chunk in stream_gen:
        if chunk.content and stream:
            print(chunk.content, end="", flush=True)
        response = streamed_response

    if response is None:
        raise RuntimeError("No response from xAI client")
    chat.append(response)

    while not response.content:
        if response.tool_calls:
            async with neo4jdriver.session() as session:
                tx = await session.begin_transaction()
                tool_name = "unknown"
                try:
                    for tool_call in response.tool_calls:
                        tool_name = tool_call.function.name
                        tool_args = json.loads(tool_call.function.arguments)
                        try:
                            if tool_name == "cypher_query":
                                results = await execute_cypher_query(tx, tool_args["query"])
                                chat.append(tool_result(json.dumps(results)))
                            elif tool_name == "create_node":
                                result = await create_node(
                                    tx,
                                    tool_args["node_type"],
                                    tool_args["name"],
                                    tool_args["description"],
                                    xai_client=xai_client,
                                    openai_client=openai_client,
                                )
                                chat.append(tool_result(json.dumps({"elementId": result})))
                            elif tool_name == "create_edge":
                                result = await create_edge(
                                    tx,
                                    tool_args["source_id"],
                                    tool_args["target_id"],
                                    tool_args["relationship_type"],
                                    tool_args.get("properties", {}),
                                )
                                chat.append(tool_result(json.dumps(result)))
                            elif tool_name == "find_node":
                                results = await find_node(
                                    tx,
                                    tool_args["query_text"],
                                    tool_args["node_type"],
                                    tool_args.get("top_k", 5),
                                    openai_client=openai_client,
                                )
                                chat.append(tool_result(json.dumps(results)))
                        except CypherSyntaxError as cypher_syntax_error:
                            logger.error(
                                f"Error executing tool {tool_name}. Cypher syntax error: {cypher_syntax_error}"
                            )
                            chat.append(tool_result(json.dumps({"Cypher syntax error": str(cypher_syntax_error)})))
                    await tx.commit()
                except Exception as e:
                    logger.error(f"Error executing tool {tool_name}: {e}")
                    chat.append(tool_result(json.dumps({"error": str(e)})))
                    await tx.cancel()
                finally:
                    await tx.close()

            stream_gen = chat.stream()
            response = None
            async for streamed_response, chunk in stream_gen:
                if chunk.content and stream:
                    print(chunk.content, end="", flush=True)
                response = streamed_response
            if response is None:
                raise RuntimeError("No response from xAI client")
            chat.append(response)

    if stream:
        print()
    logger.info("Final response: %s", response.content)
    logger.info("Finish reason: %s", response.finish_reason)
    logger.info("Reasoning tokens: %s", response.usage.reasoning_tokens)
    logger.info("Total tokens: %s", response.usage.total_tokens)

    return response.content


async def run_daily_batch() -> None:
    neo4jdriver = AsyncGraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
    )
    await neo4jdriver.verify_connectivity()

    xai_client = AsyncClient(api_key=os.getenv("XAI_API_KEY"), timeout=3600)
    openai_client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])

    with open("knowledge_graph/sources.yaml", "r") as f:
        config = yaml.safe_load(f)

    for source in config.get("sources", []):
        params = _build_search_params(source)
        logger.info("Processing %s", source.get("name"))
        result = await run_chat_batch(
            source.get("prompt", ""),
            neo4jdriver=neo4jdriver,
            xai_client=xai_client,
            openai_client=openai_client,
            search_parameters=params,
            stream=False,
        )
        logger.info("Processed %s: %s", source.get("name"), result)

    _save_last_run(datetime.now(timezone.utc))
    await neo4jdriver.close()


if __name__ == "__main__":
    asyncio.run(run_daily_batch())
