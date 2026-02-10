from neo4j import AsyncDriver, AsyncTransaction
from neo4j.exceptions import ClientError, CypherSyntaxError
import json
from typing import List, Dict, Optional, Union, Tuple, Any
from pydantic import BaseModel

from neo4j.time import Date, DateTime
from dataclasses import dataclass
from typing import Literal
from asyncio import Lock
import logging
from neo4j.exceptions import ServiceUnavailable
from lark import Lark, ParseError, UnexpectedCharacters, UnexpectedToken

# Load the Cypher grammar
with open("knowledge_graph/cypher.cfg", "r") as f:
    CYPHER_GRAMMAR = f.read()


def validate_cypher_query(query: str) -> Tuple[bool, Optional[str]]:
    """
    Validates a Cypher query using the context-free grammar.
    
    Args:
        query: The Cypher query string to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        # Create Lark parser with the grammar
        parser = Lark(CYPHER_GRAMMAR, start='start', parser='earley')

        # Parse the query - this will raise an exception if invalid
        parser.parse(query.strip())

        return True, None  # Valid query

    except ParseError as e:
        return False, f"Parse error: {str(e)}"
    except UnexpectedCharacters as e:
        return False, f"Unexpected characters at position {e.pos_in_stream}: {str(e)}"
    except UnexpectedToken as e:
        return False, f"Unexpected token '{e.token}' at position {e.pos_in_stream}: {str(e)}"
    except Exception as e:
        return False, f"Validation error: {str(e)}"


class Neo4jDateEncoder(json.JSONEncoder):

    def default(self, o):
        if isinstance(o, Date):
            return o.to_native().isoformat()  # e.g. "2025-07-30"
        if isinstance(o, DateTime):
            return o.to_native().date().isoformat()  # e.g. "2025-07-30"
        return super().default(o)


EMBEDDING_MODEL = "text-embedding-3-large"


@dataclass
class GraphOpsCtx:
    neo4jdriver: AsyncDriver
    lock: Lock
    node_name_mapping: Dict[
        str, str] = None  # Maps old node names to actual node names

    def __post_init__(self):
        if self.node_name_mapping is None:
            self.node_name_mapping = {}


async def run_transaction(tx: AsyncTransaction, query, params=None):
    # If params is None, default to empty dict for safety
    if params is None:
        params = {}

    result = await tx.run(query, params)
    return await result.data()


# Core logic functions, independent of Chainlit


async def core_execute_cypher_query(ctx: GraphOpsCtx,
                                    query: str) -> List[dict]:
    """
    Executes the provided Cypher query against the Neo4j database and returns the results.
    Robust error handling is implemented to catch exceptions from invalid queries or empty result sets.

    Returns:
        list: A list of dictionaries representing the records from the database query.

    Raises:
        RuntimeError: If there is an error executing the Cypher query.
    """

    def filter_embedding(obj):
        """
        Recursively removes the 'embedding' key and converts Neo4j Date/DateTime to strings.
        """
        if isinstance(obj, dict):
            return {
                k: filter_embedding(v)
                for k, v in obj.items() if k != 'embedding'
            }
        elif isinstance(obj, list):
            return [filter_embedding(item) for item in obj]
        elif isinstance(obj, Date):
            return obj.iso_format(
            )  # Convert Neo4j Date to ISO 8601 string (e.g., "2025-07-28")
        elif isinstance(obj, DateTime):
            return obj.iso_format(
            )  # Convert Neo4j DateTime to ISO 8601 string (e.g., "2025-07-28T10:55:00+00:00")
        return obj

    logging.info(f"[CYPHER_QUERY]:\n{query}")

    # Validate the query before execution
    is_valid, validation_error = validate_cypher_query(query)
    if not is_valid:
        logging.error(
            f"validate_cypher_query caught and reported an Invalid Cypher query: {validation_error}"
        )
        raise RuntimeError(f"Invalid Cypher query: {validation_error}")

    async with ctx.neo4jdriver.session() as session:

        async def read_work(tx: AsyncTransaction):
            result = await tx.run(query)
            records = await result.data()
            if not records:
                return []
            filtered_records = [filter_embedding(record) for record in records]
            return filtered_records

        async with ctx.lock:
            try:
                return await session.execute_read(read_work)
            except (ClientError, CypherSyntaxError, ServiceUnavailable) as e:
                raise RuntimeError(f"Error executing Cypher query: {str(e)}")


async def core_create_node(ctx: GraphOpsCtx,
                           node_type: str,
                           name: str,
                           description: str,
                           groq_client=None,
                           openai_embedding_client=None) -> str:
    logging.info(
        f"[CREATE_NODE] TYPE: {node_type}\nNAME: {name}\n DESCRIPTION: {description}"
    )

    if node_type in [
            "Convergence", "Capability", "Milestone", "Trend", "Idea", "Bet", "LTC",
            "LAC"
    ]:
        if groq_client is None or openai_embedding_client is None:
            raise ValueError(
                "groq_client and openai_embedding_client are required for smart_upsert node types"
            )
        return await core_smart_upsert(ctx, node_type, name, description,
                                       groq_client, openai_embedding_client)
    elif node_type == "EmTech":
        return "Do not create new EmTech type nodes. EmTechs are reference data, use existing ones."
    else:
        return await core_merge_node(ctx, node_type, name, description)


class CompareResult(BaseModel):
    different: bool
    name: Optional[str] = None
    description: Optional[str] = None


async def core_smart_upsert(ctx: GraphOpsCtx, node_type: str, name: str,
                            description: str, groq_client,
                            openai_embedding_client) -> str:
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
        emb_response = await openai_embedding_client.embeddings.create(
            model=EMBEDDING_MODEL, input=description)
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
        params = {"index_name": index_name, "vector": new_embedding}

        async with ctx.neo4jdriver.session() as session:

            async def read_similar(tx: AsyncTransaction):
                result = await tx.run(similar_query, params)
                return await result.data()

            async with ctx.lock:
                similar_nodes = await session.execute_read(read_similar)

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
                            "role":
                            "user",
                            "content":
                            f"Node A name: {old_name}\nNode A description: {old_desc}\n\n"
                            f"Node B name: {name}\nNode B description: {description}"
                        },
                    ],
                    stream=False,
                    reasoning_effort="low",
                    # reasoning_format="hidden",
                    temperature=0.2,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": "compare_result",
                            "description": "Result of comparing two nodes.",
                            "schema": CompareResult.model_json_schema(),
                        }
                    },
                )

                try:
                    result = CompareResult.model_validate_json(
                        completion.choices[0].message.content)

                    if not result.different:
                        found_same_name = old_name
                        updated_name = result.name or old_name
                        updated_description = result.description or description
                        break

                except Exception as e:
                    logging.error(f"Failed to parse LLM response: {e}")
                    logging.error(
                        f"LLM response: {completion.choices[0].message.content}"
                    )

            if found_same_name:
                logging.info(
                    f"[CREATE_NODE] Found semantically equivalent node to: {name}; "
                    f"updating the node with name: {updated_name} "
                    f"and description: {updated_description}")

                # Generate new embedding for the updated description
                updated_emb_response = await openai_embedding_client.embeddings.create(
                    model=EMBEDDING_MODEL, input=updated_description)
                updated_embedding = updated_emb_response.data[0].embedding

                # Update the existing node with new name, description and embedding
                update_query = f"""
                MATCH (n:`{node_type}` {{name: $node_name}})
                SET n.name = $name, n.description = $description, n.embedding = $embedding
                RETURN n.name AS name
                """
                update_params = {
                    "node_name": found_same_name,
                    "name": updated_name,
                    "description": updated_description,
                    "embedding": updated_embedding
                }

                async def write_update(tx: AsyncTransaction):
                    result = await tx.run(update_query, update_params)
                    records = await result.data()
                    if not records:
                        raise RuntimeError(
                            f"Failed to update node with name: {found_same_name}"
                        )
                    return records[0]['name']

                async with ctx.lock:
                    actual_name = await session.execute_write(write_update)
                    # Store the mapping from original name to actual name
                    ctx.node_name_mapping[name] = actual_name
                    return actual_name

            else:
                logging.info(
                    "[CREATE_NODE] "
                    f"No semantically equivalent node found, creating a new node;"
                    f"Type: {node_type} Name: {name} Description: {description}"
                )
                # Create a new node
                create_query = f"""
                CREATE (n:`{node_type}` {{name: $name, description: $description, embedding: $embedding}})
                RETURN n.name AS name
                """
                create_params = {
                    "name": name,
                    "description": description,
                    "embedding": new_embedding
                }

                async def write_create(tx: AsyncTransaction):
                    result = await tx.run(create_query, create_params)
                    records = await result.data()
                    if not records:
                        raise RuntimeError("Failed to create new node")
                    return records[0]['name']
                async with ctx.lock:
                    actual_name = await session.execute_write(write_create)
                    # Store the mapping from original name to actual name (in case of future updates)
                    ctx.node_name_mapping[name] = actual_name
                    return actual_name
    except Exception as e:
        logging.error(f"Error in smart_upsert: {str(e)}")
        raise


async def core_merge_node(ctx: GraphOpsCtx, node_type: str, name: str,
                          description: str) -> str:
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

    query = f"""
    MERGE (n:`{node_type}` {{name: $name}})
    SET n.description = $description
    RETURN n.name AS node_name
    """

    async with ctx.neo4jdriver.session() as session:

        async def write_work(tx: AsyncTransaction):
            result = await tx.run(query, {
                "name": name,
                "description": description
            })
            records = await result.data()
            if not records:
                raise RuntimeError("Failed to merge node")
            return records[0]["node_name"]

        async with ctx.lock:
            try:
                node_name = await session.execute_write(write_work)
                logging.info(
                    f"[CREATE_NODE] merged: type: {node_type}\nname: {name}\n description: {description}"
                )
                # Store the mapping from original name to actual name
                ctx.node_name_mapping[name] = node_name
                return node_name
            except Exception as e:
                logging.error(f"Error in merge_node: {str(e)}")
                raise RuntimeError(f"Failed to merge node: {str(e)}")


async def core_create_edge(
    ctx: GraphOpsCtx,
    source_name: str,
    target_name: str,
    relationship_type: str,
    properties: Optional[Dict[str, Union[str, int, float, bool]]] = None,
) -> dict:
    """
    Creates a directed edge (relationship) between two existing nodes in Neo4j.
    Takes source node name, target node name, relationship type, and optional properties.
    Returns the created relationship as a dict.
    """

    # Check if we have mapped names for the source and target
    actual_source_name = ctx.node_name_mapping.get(source_name, source_name)
    actual_target_name = ctx.node_name_mapping.get(target_name, target_name)

    logging.info(
        f"[CREATE_EDGE]\nSOURCE: {source_name} -> {actual_source_name}\n->\nTARGET:{target_name} -> {actual_target_name}\nWITH TYPE:{relationship_type} AND PROPERTIES: {properties}"
    )

    # Use the properties dict directly
    props_dict = properties or {}

    prop_keys = ", ".join(f"{key}: ${key}" for key in props_dict)
    prop_str = f"{{{prop_keys}}}" if prop_keys else ""

    # First, verify both nodes exist using the actual names
    check_nodes_query = """
    MATCH (source) WHERE source.name = $source_name 
    MATCH (target) WHERE target.name = $target_name 
    RETURN source.name as source_name, target.name as target_name
    """

    async with ctx.neo4jdriver.session() as session:

        async def check_nodes(tx: AsyncTransaction):
            result = await tx.run(
                check_nodes_query, {
                    "source_name": actual_source_name,
                    "target_name": actual_target_name
                })
            records = await result.data()
            return records

        try:
            async with ctx.lock:
                node_check = await session.execute_read(check_nodes)

            if not node_check:
                missing_nodes = []
                # Check which specific nodes are missing
                check_source_query = "MATCH (n) WHERE n.name = $source_name RETURN n.name as name"
                check_target_query = "MATCH (n) WHERE n.name = $target_name RETURN n.name as name"

                async def check_source(tx: AsyncTransaction):
                    result = await tx.run(check_source_query,
                                          {"source_name": actual_source_name})
                    return await result.data()

                async def check_target(tx: AsyncTransaction):
                    result = await tx.run(check_target_query,
                                          {"target_name": actual_target_name})
                    return await result.data()

                async with ctx.lock:
                    source_exists = await session.execute_read(check_source)
                    target_exists = await session.execute_read(check_target)

                if not source_exists:
                    missing_nodes.append(
                        f"source node '{actual_source_name}' (original: '{source_name}')"
                    )
                if not target_exists:
                    missing_nodes.append(
                        f"target node '{actual_target_name}' (original: '{target_name}')"
                    )

                raise RuntimeError(
                    f"Cannot create edge: {', '.join(missing_nodes)} not found in database"
                )

        except RuntimeError:
            raise  # Re-raise our custom error
        except Exception as e:
            logging.error(f"Error checking nodes existence: {str(e)}")
            raise RuntimeError(f"Failed to verify nodes exist: {str(e)}")

        # Now create the edge using the actual names
        query = (
            "MATCH (source) WHERE source.name = $source_name "
            "MATCH (target) WHERE target.name = $target_name "
            f"MERGE (source)-[r:{relationship_type} {prop_str}]->(target) "
            "RETURN r")
        params = {
            "source_name": actual_source_name,
            "target_name": actual_target_name,
            **props_dict
        }

        logging.info(f"[CREATE_EDGE] Executing query: {query}")
        logging.info(f"[CREATE_EDGE] With params: {params}")

        async def write_work(tx: AsyncTransaction):
            result = await tx.run(query, params)
            record_list = await result.data()
            record = record_list[0] if record_list else None
            if not record:
                raise RuntimeError(
                    "Failed to create edge - no relationship returned from query"
                )
            return record

        try:
            async with ctx.lock:
                edge = await session.execute_write(write_work)
                logging.info(
                    f"Successfully created edge: {actual_source_name} -> {actual_target_name} with type: {relationship_type} and properties: {properties}"
                )
                return edge
        except Exception as e:
            logging.error(f"Error in create_edge: {str(e)}")
            logging.error(f"Query was: {query}")
            logging.error(f"Params were: {params}")
            raise RuntimeError(f"Failed to create edge: {str(e)}")


async def core_find_node(ctx: GraphOpsCtx,
                         query_text: str,
                         node_type: Literal["Convergence", "Capability",
                                            "Milestone", "Trend", "Idea",
                                            "Bet", "LTC", "LAC"],
                         top_k: int = 25,
                         openai_embedding_client=None) -> list:
    """
    Finds nodes in knowledge graph that are similar to a given query text.
    Uses vector similarity search based on node descriptions.
    Returns a list of nodes with their names, descriptions, and similarity scores.
    Allowed node_type values: Convergence, Capability, Milestone, Trend, Idea, LTC, LAC
    """

    logging.info(
        f"[FIND_NODE] SIMILAR TO:\n{query_text}\nOF TYPE:\n{node_type}")

    if openai_embedding_client is None:
        raise ValueError("openai_embedding_client is required for find_node")

    # calculate embedding for the query text
    emb_response = await openai_embedding_client.embeddings.create(
        model=EMBEDDING_MODEL, input=query_text)
    query_embedding = emb_response.data[0].embedding

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

    def filter_embedding(obj):
        """
        Recursively removes the 'embedding' key and converts Neo4j Date/DateTime to strings.
        """
        if isinstance(obj, dict):
            return {
                k: filter_embedding(v)
                for k, v in obj.items() if k != 'embedding'
            }
        elif isinstance(obj, list):
            return [filter_embedding(item) for item in obj]
        elif isinstance(obj, Date):
            return obj.iso_format(
            )  # Convert Neo4j Date to ISO 8601 string (e.g., "2025-07-28")
        elif isinstance(obj, DateTime):
            return obj.iso_format(
            )  # Convert Neo4j DateTime to ISO 8601 string (e.g., "2025-07-28T10:55:00+00:00")
        return obj

    async with ctx.neo4jdriver.session() as session:

        async def read_work(tx: AsyncTransaction):
            result = await tx.run(
                cypher_query, {
                    "index_name":
                    f"{node_type.lower()}_description_embeddings",
                    "top_k": top_k,
                    "embedding": query_embedding
                })
            records = await result.data()
            if not records:
                return []
            filtered_records = [filter_embedding(record) for record in records]
            return filtered_records

        async with ctx.lock:
            try:
                results = await session.execute_read(read_work)
                logging.info(
                    f"Found {len(results)} nodes similar to {query_text}")
                return results
            except Exception as e:
                logging.error(f"Error in find_node: {str(e)}")
                raise RuntimeError(f"Failed to find nodes: {str(e)}")


async def core_dfs(ctx: GraphOpsCtx,
                   node_name: str,
                   node_type: Literal["Convergence", "Capability", "Milestone",
                                      "LTC", "PTC", "LAC", "PAC", "Trend",
                                      "Idea", "Bet", "Party"],
                   depth: int = 3) -> List[Dict[str, Any]]:
    """
    Performs a depth-first search (DFS) on a Neo4j graph starting from a node
    identified by its name, up to a specified depth, stopping at EmTech nodes.

    Args:
        ctx (GraphOpsCtx): Context object containing Neo4j driver and lock.
        node_name (str): Name of the starting node.
        node_type (Literal): the type ("Label") of the node
        depth (int, optional): Maximum depth for DFS traversal. Defaults to 3.

    Returns:
        List[Dict[str, Any]]: A list of dictionaries, each containing:
            - nodes: List of node dictionaries with 'name' and 'description'.
            - edges: List of edge dictionaries with 'source_node_name',
                    'relationship', and 'end_node_name'.

    Raises:
        ValueError: If node_name is empty or depth is negative.
        RuntimeError: If the query fails due to database or other errors.
    """
    if not node_name or not isinstance(node_name, str):
        raise ValueError("node_name must be a non-empty string")
    if not isinstance(depth, int) or depth < 0:
        raise ValueError("depth must be a non-negative integer")

    logging.info(f"[DFS]:\nNODE_NAME: {node_name}\nDEPTH: {depth}")

    # Query 1: Collect nodes in DFS up to specified depth, stopping at EmTech nodes
    nodes_query = f"""
    MATCH (startNode:{node_type} {{name: $node_name}})
    WITH startNode
    CALL apoc.path.subgraphNodes(startNode, {{
        maxLevel: $depth,
        bfs: false,
        labelFilter: '-EmTech'
    }}) YIELD node
    RETURN collect({{ name: node.name, description: node.description }}) AS nodes
    """

    # Query 2: Collect edges in DFS up to specified depth, stopping at EmTech nodes
    edges_query = f"""
    MATCH (startNode:{node_type} {{name: $node_name}})
    WITH startNode
    CALL apoc.path.expandConfig(startNode, {{
        maxLevel: $depth,
        bfs: false,
        labelFilter: '-EmTech'
    }}) YIELD path
    WHERE size(relationships(path)) > 0
    UNWIND relationships(path) AS rel
    RETURN collect({{
        source_node_name: startNode(rel).name,
        relationship: type(rel),
        end_node_name: endNode(rel).name
    }}) AS edges
    """

    async with ctx.neo4jdriver.session() as session:

        async def read_nodes(tx: AsyncTransaction):
            result = await tx.run(nodes_query, {
                "node_name": node_name,
                "depth": depth
            })
            record = await result.single()
            return record["nodes"] if record else []

        async def read_edges(tx: AsyncTransaction):
            result = await tx.run(edges_query, {
                "node_name": node_name,
                "depth": depth
            })
            record = await result.single()
            return record["edges"] if record else []

        async with ctx.lock:
            try:
                nodes = await session.execute_read(read_nodes)
                edges = await session.execute_read(read_edges)
                return [{"nodes": nodes, "edges": edges}]
            except Exception as e:
                logging.error(f"Error in dfs: {str(e)}")
                raise RuntimeError(f"Failed dfs(): {str(e)}")
