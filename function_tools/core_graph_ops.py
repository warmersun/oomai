from neo4j import AsyncTransaction
from neo4j.exceptions import ClientError, CypherSyntaxError
import json
from typing import List, Dict, Optional, Union
from pydantic import BaseModel

from neo4j.time import Date, DateTime
from dataclasses import dataclass
from typing import Literal
from asyncio import Lock
import logging
import asyncio
from neo4j.exceptions import ServiceUnavailable


class KVPair(BaseModel):
    key: str
    value: Union[str, int, float, bool]

class Neo4jDateEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Date):
            return o.to_native().isoformat()          # e.g. "2025-07-30"
        if isinstance(o, DateTime):
            return o.to_native().date().isoformat()   # e.g. "2025-07-30"
        return super().default(o)

EMBEDDING_MODEL = "text-embedding-3-large"

@dataclass
class GraphOpsCtx:
    tx: AsyncTransaction
    lock: Lock

async def run_transaction(tx: AsyncTransaction, query, params=None, max_retries=3):
    # If params is None, default to empty dict for safety
    if params is None:
        params = {}

    for attempt in range(max_retries):
        try:
            result = await tx.run(query, params)
            return await result.data()
        except ServiceUnavailable as e:
            logging.warning(f"💥 ServiceUnavailable error: {e}. Retrying ({attempt + 1}/{max_retries})...")
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)  # Exponential backoff

# Core logic functions, independent of Chainlit

async def core_execute_cypher_query(ctx: GraphOpsCtx, query: str) -> List[dict]:
    """
    Executes the provided Cypher query against the Neo4j database and returns the results.
    Robust error handling is implemented to catch exceptions from invalid queries or empty result sets.

    Returns:
        list: A list of dictionaries representing the records from the database query.

    Raises:
        RuntimeError: If there is an error executing the Cypher query.
    """

    logging.info(f"[CYPHER_QUERY]:\n{query}")

    from neo4j.time import Date, DateTime

    def filter_embedding(obj):
        """
        Recursively removes the 'embedding' key and converts Neo4j Date/DateTime to strings.
        """
        if isinstance(obj, dict):
            return {k: filter_embedding(v) for k, v in obj.items() if k != 'embedding'}
        elif isinstance(obj, list):
            return [filter_embedding(item) for item in obj]
        elif isinstance(obj, Date):
            return obj.iso_format()  # Convert Neo4j Date to ISO 8601 string (e.g., "2025-07-28")
        elif isinstance(obj, DateTime):
            return obj.iso_format()  # Convert Neo4j DateTime to ISO 8601 string (e.g., "2025-07-28T10:55:00+00:00")
        return obj

    try:
        async with ctx.lock:
            records = await run_transaction(ctx.tx, query)
            # Convert the results to a list of dictionaries
            if not records:
                return []

            # Apply recursive filtering to each record
            filtered_records = [filter_embedding(record) for record in records]
            return filtered_records

    except CypherSyntaxError as e:
        # Handle Cypher syntax errors
        logging.error(f"Cypher syntax error: {e}. The transaction will be rolled back.")
        return [{"error": f"Try again! Cypher syntax error: {e.message}"}]

    except ClientError as e:
        # Handle client errors (e.g., invalid parameters)
        logging.error(f"Client error: {e}.")
        if e.is_retriable:
            return [{"error": f"Try again! Client error: {e.message}"}]
        else:
            raise RuntimeError(f"Client error: {e.message}")

    except Exception as e:
        # Catch any other unexpected errors
        logging.error(f"Error executing Cypher query: {e}. The transaction will be rolled back.")
        raise RuntimeError(f"Error executing Cypher query: {e}. The transaction will be rolled back.")

async def core_create_node(ctx: GraphOpsCtx, node_type: str, name: str, description: str, groq_client=None, openai_client=None) -> str:
    logging.info(f"[CREATE_NODE] TYPE: {node_type}\nNAME: {name}\n DESCRIPTION: {description}")

    if node_type in ["Convergence", "Capability", "Milestone", "Trend", "Idea", "LTC", "LAC"]:
        if groq_client is None or openai_client is None:
            raise ValueError("groq_client and openai_client are required for smart_upsert node types")
        return await core_smart_upsert(ctx, node_type, name, description, groq_client, openai_client)
    elif node_type == "EmTech":
        return "Do not create new EmTech type nodes. EmTechs are reference data, use existing ones."
    else:
        return await core_merge_node(ctx, node_type, name, description)

class CompareResult(BaseModel):
    different: bool
    name: Optional[str] = None
    description: Optional[str] = None

async def core_smart_upsert(ctx: GraphOpsCtx, node_type: str, name: str, description: str, groq_client, openai_client) -> str:
    """
    Performs a smart UPSERT for a node in Neo4j.
    - Queries for similar nodes based on description embedding similarity >= 0.8 (top 100 candidates, filtered).
    - Uses the Grok4 LLM with structured outputs to determine if any candidate
      is semantically the same based on name and description.
    - If the same, the LLM also returns an improved name and a merged
      description which are then used to update the node.
    - If no match is found, creates a new node.
    - Returns the node's name.
    """
    index_name = f"{node_type.lower()}_description_embeddings"

    try:
        # Generate embedding for the new description
        emb_response = await openai_client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=description
        )
        new_embedding = emb_response.data[0].embedding

        # Query for similar nodes
        similar_query = """
        CALL db.index.vector.queryNodes($index_name, 100, $vector)
        YIELD node, score
        WHERE score >= 0.8
        RETURN node.name AS name, node.description AS description, score
        ORDER BY score DESC
        LIMIT 10
        """
        async with ctx.lock:
            similar_nodes = await run_transaction(ctx.tx, similar_query, {"index_name": index_name, "vector": new_embedding})

        found_same_name = None
        updated_name = name
        updated_description = description
        for sim in similar_nodes:
            old_name = sim['name']
            old_desc = sim['description']

            compare_prompt = (
                "Determine whether the following two nodes represent the same concept by carefully comparing their names and descriptions. "
                "Reason step by step: First, analyze similarities in meaning. Second, decide if they are semantically identical. "
                "If they are the same, provide an improved short name (combining the best aspects) and a merged description (concise, comprehensive, avoiding redundancy). "
                "If different, just indicate they are different. "
                "Always output only a JSON object with keys: different (boolean), and optionally name (string) and description (string) if not different."
            )

            completion = await groq_client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=[
                    {
                        "role": "system",
                        "content": compare_prompt,
                    },
                    {
                        "role": "user",
                        "content": f"Node A name: {old_name}\nNode A description: {old_desc}\n\n"
                                   f"Node B name: {name}\nNode B description: {description}"
                    },                    
                ],
                stream=False,
                reasoning_effort="low",
                # reasoning_format="hidden",
                temperature=0.2,
                response_format = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "compare_result",
                        "description": "Result of comparing two nodes.",
                        "schema": CompareResult.model_json_schema(),
                    }
                },
            )

            try:
                result = CompareResult.model_validate_json(completion.choices[0].message.content)

                if not result.different:
                    found_same_name = sim['name']
                    updated_name = result.name or old_name
                    updated_description = result.description or description
                    break

            except Exception as e:
                logging.error(f"Failed to parse LLM response: {e}")
                logging.error(f"LLM response: {completion.choices[0].message.content}")


        if found_same_name:
            logging.info(
                f"[CREATE_NODE] Found semantically equivalent node to: {name}; "
                f"updating the node with name: {updated_name}" 
                f"and description: {updated_description}"
            )

            # Generate new embedding for the updated description
            updated_emb_response = await openai_client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=updated_description
            )
            updated_embedding = updated_emb_response.data[0].embedding

            async with ctx.lock:
                # Update the existing node with new name, description and embedding
                update_query = """
                MATCH (n)
                WHERE n.name = $node_name
                SET n.name = $name, n.description = $description, n.embedding = $embedding
                RETURN n.name AS name
                """
                update_record_list = await run_transaction(ctx.tx, update_query, {"node_name": found_same_name, "name": updated_name, "description": updated_description, "embedding": updated_embedding})
                update_record = update_record_list[0] if update_record_list else None
                if update_record is None:
                    raise RuntimeError(f"Failed to update node with name: {found_same_name}")
                return update_record['name']
        else:
            logging.info(
                "[CREATE_NODE] "
                f"No semantically equivalent node found, creating a new node;"
                f"Type: {node_type} Name: {name} Description: {description}"
            )
            async with ctx.lock:
                # Create a new node
                create_query = f"""-
                CREATE (n:`{node_type}` {{name: $name, description: $description, embedding: $embedding}})
                RETURN n.name AS name
                """
                create_record_list = await run_transaction(ctx.tx, create_query, {"name": name, "description": description, "embedding": new_embedding})
                create_record = create_record_list[0] if create_record_list else None
                if create_record is None:
                    raise RuntimeError("Failed to create new node")
                return create_record['name']
    except Exception as e:
        logging.error(f"Error in smart_upsert: {str(e)}")
        raise

async def core_merge_node(ctx: GraphOpsCtx, node_type: str, name: str, description: str) -> str:
    """
    Performs a simple MERGE operation to create or match a node in Neo4j with the given type, name, and description.
    If a node with the same name and type exists, it updates the description; otherwise, it creates a new node.
    Returns the name of the matched or created node as a string.

    Args:
        node_type (str): The type/label of the node (e.g., 'EmTech', 'Capability', 'Party').
        name (str): A short, unique name for the node (e.g., 'AI', 'OpenAI').
        description (str): A detailed description of the node.

    Returns:
        str: The name of the matched or created node.

    Raises:
        RuntimeError: If the Neo4j driver is not found or the query fails.
    """

    try:
        async with ctx.lock:
            query = f"""
            MERGE (n:`{node_type}` {{name: $name}})
            SET n.description = $description
            RETURN n.name AS node_name
            """
            record_list = await run_transaction(ctx.tx, query, {"name": name, "description": description})
            record = record_list[0] if record_list else None
            if record is None:
                raise RuntimeError("Failed to merge node")
            logging.info(f"[CREATE_NODE] merged: type: {node_type}\nname: {name}\n description: {description}")
            return record["node_name"]
    except Exception as e:
        logging.error(f"Error in merge_node: {str(e)}")
        raise RuntimeError(f"Failed to merge node: {str(e)}")

async def core_create_edge(
    ctx: GraphOpsCtx,
    source_name: str,
    target_name: str,
    relationship_type: str,
    properties: Optional[List[KVPair]] = None,
) -> dict:
    """
    Creates a directed edge (relationship) between two existing nodes in Neo4j.
    Takes source node name, target node name, relationship type, and optional properties.
    Returns the created relationship as a dict.
    """

    logging.info(f"[CREATE_EDGE]\nSOURCE: {source_name}\n->\nTARGET:{target_name}\nWITH TYPE:{relationship_type} AND PROPERTIES: {properties}")

    # rebuild a strict dict for Cypher params
    props_dict = {p.key: p.value for p in (properties or [])}

    prop_keys = ", ".join(f"{key}: ${key}" for key in props_dict)
    prop_str = f"{{{prop_keys}}}" if prop_keys else ""

    query = (
        "MATCH (source) WHERE source.name = $source_name "
        "MATCH (target) WHERE target.name = $target_name "
        f"MERGE (source)-[r:{relationship_type} {prop_str}]->(target) "
        "RETURN r"
    )
    params = {"source_name": source_name, "target_name": target_name, **props_dict}

    async with ctx.lock:
        record_list = await run_transaction(ctx.tx, query, params)
        record = record_list[0] if record_list else None
        if record is None:
            raise RuntimeError("Failed to create edge")
        logging.info(f"Created edge: {source_name} -> {target_name} with type: {relationship_type} and properties: {properties}")
        return record

async def core_find_node(
    ctx: GraphOpsCtx,
    query_text: str,
    node_type: Literal[
        "Convergence", "Capability", "Milestone", "Trend", "Idea", "LTC", "LAC"
    ],
    top_k: int = 5,
    openai_client=None
) -> list:
    """
    Finds nodes in knowledge graph that are similar to a given query text.
    Uses vector similarity search based on node descriptions.
    Returns a list of nodes with their names, descriptions, and similarity scores.
    Allowed node_type values: Convergence, Capability, Milestone, Trend, Idea, LTC, LAC
    """

    logging.info(f"[FIND_NODE] SIMILAR TO:\n{query_text}\nOF TYPE:\n{node_type}")

    if openai_client is None:
        raise ValueError("openai_client is required for find_node")

    # calculate embedding for the query text
    emb_response = await openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=query_text
    )
    query_embedding = emb_response.data[0].embedding

    async def vector_search(ctx: GraphOpsCtx):
        cypher_query = """
        CALL db.index.vector.queryNodes($index_name, $top_k, $embedding)
        YIELD node, score
        RETURN
            CASE
                WHEN node:Milestone
                THEN node { .name, .description, .milestone_reached_date }
                ELSE node { .name, .description }
            END AS node,
            score
        ORDER BY score DESC
        """
        records = await run_transaction(ctx.tx, cypher_query, {"index_name": f"{node_type.lower()}_description_embeddings", "top_k": top_k, "embedding": query_embedding})
        return records

    # execute the query
    async with ctx.lock:
        results = await vector_search(ctx)
        logging.info(f"Found {len(results)} nodes similar to {query_text}")
        return results