import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

import yaml
from neo4j import AsyncGraphDatabase, AsyncTransaction
from neo4j.exceptions import CypherSyntaxError, Neo4jError
from openai import AsyncOpenAI
from pydantic import BaseModel
from xai_sdk import AsyncClient
from xai_sdk.chat import SearchParameters, system, user, tool, tool_result
from xai_sdk.search import rss_source, x_source


with open("knowledge_graph/schema.md", "r") as f:
    schema = f.read()

embedding_model = "text-embedding-3-large"
llm_model = "grok-4"

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
        params["from_date"] = last_run.isoformat()

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
    def filter_embedding(obj):
        if isinstance(obj, dict):
            return {k: filter_embedding(v) for k, v in obj.items() if k != "embedding"}
        if isinstance(obj, list):
            return [filter_embedding(item) for item in obj]
        return obj

    try:
        result = await tx.run(query)
        records = await result.data()
        if not records:
            logging.warning("Query executed successfully but returned no results.")
            return []
        return [filter_embedding(record) for record in records]
    except Neo4jError as e:
        logging.error(f"Neo4j error executing query: {e}")
        raise RuntimeError(f"Error executing query: {e}")
    except Exception as e:
        logging.error(f"Unexpected error executing query: {e}")
        raise RuntimeError(f"Unexpected error executing query: {e}")


cypher_query_tool = tool(
    name="cypher_query",
    description=(
        "Executes the provided Cypher query against the Neo4j database and returns the results."
    ),
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string", "description": "The Cypher query to execute."}},
        "required": ["query"],
    },
)


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


async def smart_upsert(tx: AsyncTransaction, node_type: str, name: str, description: str, openai_client: AsyncOpenAI, xai_client: AsyncClient) -> str:
    index_name = f"{node_type.lower()}_description_embeddings"

    class CompareResult(BaseModel):
        different: bool
        name: Optional[str] = None
        description: Optional[str] = None

    emb_response = await openai_client.embeddings.create(model=embedding_model, input=description)
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

        compare_prompt = (
            "Determine whether the following two nodes represent the same concept. "
            "If they are the same, provide a short improved name and a merged description. "
            "Respond in JSON matching this schema: {different: bool, name?: string, description?: string}."
        )

        chat = xai_client.chat.create(model=llm_model, temperature=0.0)
        chat.append(system(compare_prompt))
        chat.append(user(f"Node A name: {old_name}\nNode A description: {old_desc}\n\nNode B name: {name}\nNode B description: {description}"))

        try:
            _, result = await chat.parse(CompareResult)
        except Exception as e:
            logging.warning(f"Failed to parse LLM response: {e}")
            continue

        if not result.different:
            found_same_id = sim["node_id"]
            updated_name = result.name or old_name
            updated_description = result.description or description
            break

    if found_same_id:
        logging.info(f"Found semantically equivalent node with id: {found_same_id}")
        logging.info(f"Updated name: {updated_name}")
        logging.info(f"Updated description: {updated_description}")

        updated_emb_response = await openai_client.embeddings.create(model=embedding_model, input=updated_description)
        updated_embedding = updated_emb_response.data[0].embedding

        update_query = """
        MATCH (n)
        WHERE elementId(n) = $node_id
        SET n.name = $name, n.description = $description, n.embedding = $embedding
        RETURN elementId(n) AS id
        """
        update_result = await tx.run(update_query, node_id=found_same_id, name=updated_name, description=updated_description, embedding=updated_embedding)
        update_record = await update_result.single()
        if update_record is None:
            raise RuntimeError(f"Failed to update node with elementId: {found_same_id}")
        return update_record["id"]

    logging.info("No semantically equivalent node found, creating a new node.")
    create_query = f"""
    CREATE (n:`{node_type}` {{name: $name, description: $description, embedding: $embedding}})
    RETURN elementId(n) AS id
    """
    create_result = await tx.run(create_query, name=name, description=description, embedding=new_embedding)
    create_record = await create_result.single()
    if create_record is None:
        raise RuntimeError("Failed to create new node")
    return create_record["id"]


async def create_node(tx: AsyncTransaction, node_type: str, name: str, description: str, openai_client: AsyncOpenAI, xai_client: AsyncClient) -> str:
    if node_type in ["Convergence", "Capability", "Milestone", "Trend", "Idea", "LTC", "LAC"]:
        return await smart_upsert(tx, node_type, name, description, openai_client, xai_client)
    if node_type == "EmTech":
        return "Do not create new EmTech type nodes. EmTechs are reference data, use existing ones."
    return await merge_node(tx, node_type, name, description)


create_node_tool = tool(
    name="create_node",
    description="Creates or updates a node in the knowledge graph, avoiding duplicates.",
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


async def create_edge(tx: AsyncTransaction, source_id: str, target_id: str, relationship_type: str, properties: Optional[Dict[str, Any]] = None) -> Any:
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
    if record:
        return record.data()
    return None


create_edge_tool = tool(
    name="create_edge",
    description="Creates or merges a relationship between two nodes in Neo4j.",
    parameters={
        "type": "object",
        "properties": {
            "source_id": {"type": "string", "description": "The elementId of the source node."},
            "target_id": {"type": "string", "description": "The elementId of the target node."},
            "relationship_type": {"type": "string", "description": "The type of relationship."},
            "properties": {"type": "object", "description": "Optional additional properties.", "additionalProperties": True},
        },
        "required": ["source_id", "target_id", "relationship_type"],
    },
)


async def find_node(tx: AsyncTransaction, query_text: str, node_type: str, openai_client: AsyncOpenAI, top_k: int = 5) -> list:
    emb_response = await openai_client.embeddings.create(model=embedding_model, input=query_text)
    query_embedding = emb_response.data[0].embedding

    cypher_query = """
    CALL db.index.vector.queryNodes($index_name, $top_k, $embedding)
    YIELD node, score
    RETURN {name: node.name, description: node.description} AS node, score
    ORDER BY score DESC
    """
    result = await tx.run(cypher_query, index_name=f"{node_type.lower()}_description_embeddings", top_k=top_k, embedding=query_embedding)
    records = []
    async for record in result:
        records.append(record.data())
    return records


find_node_tool = tool(
    name="find_node",
    description="Finds nodes similar to a given text using vector search.",
    parameters={
        "type": "object",
        "properties": {
            "query_text": {"type": "string", "description": "The text to search for similar nodes."},
            "node_type": {"type": "string", "description": "The type of node to search for.", "enum": ["Convergence", "Capability", "Milestone", "Trend", "Idea"]},
            "top_k": {"type": "integer", "description": "The number of top results to return (default is 5).", "default": 5},
        },
        "required": ["query_text", "node_type"],
    },
)


async def run_chat(prompt: str, *, search_parameters: Optional[SearchParameters], xai_client: AsyncClient, neo4jdriver, openai_client: AsyncOpenAI) -> str:
    chat_kwargs = dict(
        model=llm_model,
        messages=[
            system(
                f"""
            You are a helpful assistant that can build a knowledge graph and then use it to answer questions.

            The knowledge graph has the following schema:
            {schema}

             When you are given an article to process you break it down to nodes in the knowledge graph and connect them wih edges to capture relationships. You can use the `create_node` and `create_edge` tools. You can also use the `cypher_query` and `find_node` tools to look for nodes. The `create_node` tool is smart and will avoid duplicates by merging their descriptions if similar semantics already exist.

            ---

            Note: there is no elementId property. Use the elementId function to get the elementId of a node or edge. e.g.
            MATCH (n:EmTech {{name: 'computing'}}) RETURN elementId(n) AS elementId
            """
            )
        ],
        tools=[cypher_query_tool, create_node_tool, create_edge_tool, find_node_tool],
    )
    if search_parameters is not None:
        chat_kwargs["search_parameters"] = search_parameters

    chat = xai_client.chat.create(**chat_kwargs)
    chat.append(user(prompt))

    stream_gen = chat.stream()
    response = None
    async for streamed_response, _ in stream_gen:
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
                                result = await create_node(tx, tool_args["node_type"], tool_args["name"], tool_args["description"], openai_client, xai_client)
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
                                    openai_client,
                                    tool_args.get("top_k", 5),
                                )
                                chat.append(tool_result(json.dumps(results)))
                        except CypherSyntaxError as cypher_syntax_error:
                            logging.error(f"Error executing tool {tool_name}. Cypher syntax error: {cypher_syntax_error}")
                            chat.append(tool_result(json.dumps({"Cypher syntax error": str(cypher_syntax_error)})))
                    await tx.commit()
                except Exception as e:
                    logging.error(f"Error executing tool {tool_name}: {e}")
                    chat.append(tool_result(json.dumps({"error": str(e)})))
                    if tx is not None:
                        await tx.cancel()
                finally:
                    if tx is not None:
                        await tx.close()

            stream_gen = chat.stream()
            response = None
            async for streamed_response, _ in stream_gen:
                response = streamed_response
            if response is None:
                raise RuntimeError("No response from xAI client")
            chat.append(response)

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

    with open("knowledge_graph/sources.yaml", "r") as f:
        config = yaml.safe_load(f)

    for source in config.get("sources", []):
        params = _build_search_params(source)
        prompt = source.get("prompt", "")
        logging.info(f"Processing {source.get('name')}")
        result = await run_chat(prompt, search_parameters=params, xai_client=xai_client, neo4jdriver=neo4jdriver, openai_client=openai_client)
        logging.info(f"Processed {source.get('name')}: {result}")

    _save_last_run(datetime.now(timezone.utc))
    await neo4jdriver.close()


if __name__ == "__main__":
    asyncio.run(main())
