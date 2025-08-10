import chainlit as cl
import os
from xai_sdk import AsyncClient
from xai_sdk.chat import SearchParameters, system, user, tool, tool_result
from groq import AsyncGroq
from neo4j import AsyncGraphDatabase, AsyncTransaction
from neo4j.exceptions import CypherSyntaxError, Neo4jError
from chainlit.logger import logger
import json
from openai import AsyncOpenAI
from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel

from neo4j.time import Date, DateTime
from function_tools import (
    web_search_brave_tool,
    web_search_brave,
)
import re
from elevenlabs.types import VoiceSettings
from elevenlabs.client import ElevenLabs
from agents import FunctionTool, RunContextWrapper, function_tool
from dataclasses import dataclass


class Neo4jDateEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Date):
            return o.to_native().isoformat()          # e.g. "2025-07-30"
        if isinstance(o, DateTime):
            return o.to_native().date().isoformat()   # e.g. "2025-07-30"
        return super().default(o)

embedding_model = "text-embedding-3-large"

@dataclass
class GraphOpsCtx:
    tx: AsyncTransaction

@function_tool
async def execute_cypher_query(wrapper: RunContextWrapper[GraphOpsCtx], query: str) -> list:
    """
    Executes the provided Cypher query against the Neo4j database and returns the results.
    Robust error handling is implemented to catch exceptions from invalid queries or empty result sets.

    Returns:
        list: A list of dictionaries representing the records from the database query.

    Raises:
        RuntimeError: If there is an error executing the Cypher query.
    """

    async with cl.Step(name="Execute Cypher Query", type="tool") as step:
        step.show_input = True
        step.input = {"query": query}

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
            result = await wrapper.context.tx.run(query)
            # Convert the results to a list of dictionaries
            records = await result.data()
            if not records:
                return []

            # Apply recursive filtering to each record
            filtered_records = [filter_embedding(record) for record in records]
            step.output = filtered_records
            return filtered_records

        except Neo4jError as e:
            # Catch errors thrown by the Neo4j driver specifically
            logger.error(f"Neo4j error executing query: {e}")
            raise RuntimeError(f"Error executing query: {e}")
        except Exception as e:
            # Catch any other unexpected errors
            logger.error(f"Unexpected error executing query: {e}")
            raise RuntimeError(f"Unexpected error executing query: {e}")


@function_tool
async def create_node(wrapper: RunContextWrapper[GraphOpsCtx], node_type: str, name: str, description: str) -> str:
    async with cl.Step(name="Create Node", type="tool") as step:
        step.show_input = True
        step.input = {"node_type": node_type, "name": name, "description": description}

        if node_type in ["Convergence", "Capability", "Milestone", "Trend", "Idea", "LTC", "LAC"]:
            return await smart_upsert(wrapper.context.tx, node_type, name, description)
        elif node_type == "EmTech":
            return "Do not create new EmTech type nodes. EmTechs are reference data, use existing ones."
        else:
            return await merge_node(wrapper.context.tx, node_type, name, description)

async def smart_upsert(tx: AsyncTransaction, node_type: str, name: str, description: str) -> str:
    """
    Performs a smart UPSERT for a node in Neo4j.
    - Queries for similar nodes based on description embedding similarity >= 0.8 (top 100 candidates, filtered).
    - Uses the Grok4 LLM with structured outputs to determine if any candidate
      is semantically the same based on name and description.
    - If the same, the LLM also returns an improved name and a merged
      description which are then used to update the node.
    - If no match is found, creates a new node.
    - Returns the node's elementId.
    """
    groq_client = cl.user_session.get("groq_client")
    if groq_client is None:
        raise ValueError("No Groq client found in user session")
    openai_client = cl.user_session.get("openai_client")
    if openai_client is None:
        raise ValueError("No OpenAI client found in user session")

    index_name = f"{node_type.lower()}_description_embeddings"

    class CompareResult(BaseModel):
        different: bool
        name: Optional[str] = None
        description: Optional[str] = None

    try:
        # Generate embedding for the new description
        emb_response = await openai_client.embeddings.create(
            model=embedding_model,
            input=description
        )
        new_embedding = emb_response.data[0].embedding

        # Query for similar nodes
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
            old_name = sim['name']
            old_desc = sim['description']

            compare_prompt = (
                "Determine whether the following two nodes represent the same concept. "
                "If they are the same, provide a short improved name and a merged description. "
                "Respond in JSON matching this schema: {different: bool, name?: string, description?: string}."
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
                temperature=0.01,
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
                    found_same_id = sim['node_id']
                    updated_name = result.name or old_name
                    updated_description = result.description or description
                    break

            except Exception as e:
                logger.warning(f"Failed to parse LLM response: {e}")
                logger.warning(f"LLM response: {completion.choices[0].message.content}")


        if found_same_id:
            logger.warning(
                f"Found semantically equivalent node to: {name}; "
                f"updating the node with name: {updated_name} and description: {updated_description}"
            )

            # Generate new embedding for the updated description
            updated_emb_response = await openai_client.embeddings.create(
                model=embedding_model,
                input=updated_description
            )
            updated_embedding = updated_emb_response.data[0].embedding

            # Update the existing node with new name, description and embedding
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
            return update_record['id']
        else:
            logger.warning(
                f"No semantically equivalent node found, creating a new node. "
                f"Type: {node_type} Name: {name} Description: {description}"
            )
            # Create a new node
            create_query = f"""
            CREATE (n:`{node_type}` {{name: $name, description: $description, embedding: $embedding}})
            RETURN elementId(n) AS id
            """
            create_result = await tx.run(create_query, name=name, description=description, embedding=new_embedding)
            create_record = await create_result.single()
            if create_record is None:
                raise RuntimeError("Failed to create new node")
            return create_record['id']
    except Exception as e:
        logger.error(f"Error in smart_upsert: {str(e)}")
        raise

async def merge_node(tx: AsyncTransaction, node_type: str, name: str, description: str) -> str:
    """
    Performs a simple MERGE operation to create or match a node in Neo4j with the given type, name, and description.
    If a node with the same name and type exists, it updates the description; otherwise, it creates a new node.
    Returns the Neo4j elementId of the matched or created node as a string.

    Args:
        node_type (str): The type/label of the node (e.g., 'EmTech', 'Capability', 'Party').
        name (str): A short, unique name for the node (e.g., 'AI', 'OpenAI').
        description (str): A detailed description of the node.

    Returns:
        str: The elementId of the matched or created node.

    Raises:
        RuntimeError: If the Neo4j driver is not found or the query fails.
    """

    try:
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
    except Exception as e:
        logger.error(f"Error in merge_node: {str(e)}")
        raise RuntimeError(f"Failed to merge node: {str(e)}")

@function_tool
async def create_edge(
    wrapper: RunContextWrapper[GraphOpsCtx],
    source_id: str,
    target_id: str,
    relationship_type: str,
    properties: Optional[Dict[str, Any]] = None,
) -> Any:
    """
    Creates a directed edge (relationship) between two existing nodes in Neo4j.
    Takes source node elementId, target node elementId, relationship type, and optional properties for the edge.
    Assumes nodes exist and elementIds are valid.
    Returns the created relationship.
    """
    async with cl.Step(name="Create Edge", type="tool") as step:
        step.show_input = True
        step.input = {
            "source_id": source_id,
            "target_id": target_id,
            "relationship_type": relationship_type,
            "properties": properties,
        }

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
        result = await wrapper.context.tx.run(query, **params)
        record =  await result.single()
        if record:
            return record.data()
        return None

@function_tool
async def find_node(wrapper: RunContextWrapper[GraphOpsCtx], query_text: str, node_type: str, top_k: int = 5) -> list:
    """
    Finds nodes in knowledge graph that are similar to a given query text.
    Uses vector similarity search based on node descriptions.
    Returns a list of nodes with their names, descriptions, and similarity scores.
    """
    async with cl.Step(name="Find Node", type="tool") as step:
        step.show_input = True
        step.input = {"query_text": query_text, "node_type": node_type, "top_k": top_k}

        openai_client = cl.user_session.get("openai_client")
        assert openai_client is not None, "No OpenAI client found in user session"

        # calculate embedding for the query text
        emb_response = await openai_client.embeddings.create(
            model=embedding_model,
            input=query_text
        )
        query_embedding = emb_response.data[0].embedding

        async def vector_search(tx):
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
            result = await tx.run(cypher_query, index_name=f"{node_type.lower()}_description_embeddings", top_k=top_k, embedding=query_embedding)
            records = []
            async for record in result:
                records.append(record.data())
            return records

        # execute the query
        results = await vector_search(wrapper.context.tx)
        step.output = results
        return results