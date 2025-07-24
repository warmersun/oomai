import chainlit as cl
import os
from xai_sdk import AsyncClient
from xai_sdk.chat import system, user, tool, tool_result
from neo4j import AsyncGraphDatabase
from neo4j.exceptions import Neo4jError
from chainlit.logger import logger
import json
from openai import AsyncOpenAI
from typing import List, Dict, Any, Optional
    
    
with open("knowledge_graph/schema.md", "r") as f:
    schema = f.read()

embedding_model = "text-embedding-3-large"
llm_model = "grok-4"
    
    
@cl.on_chat_start
async def start_chat():
    neo4jdriver = AsyncGraphDatabase.driver(os.environ['NEO4J_URI'], auth=(os.environ['NEO4J_USERNAME'], os.environ['NEO4J_PASSWORD']))
    cl.user_session.set("neo4jdriver", neo4jdriver)
    await neo4jdriver.verify_connectivity()
    xai_client = AsyncClient(
        api_key=os.getenv("XAI_API_KEY"),
        timeout=3600, # override default timeout with longer timeout for reasoning models
    )
    cl.user_session.set("xai_client", xai_client)
    openai_client = AsyncOpenAI(api_key=os.environ['OPENAI_API_KEY'])
    cl.user_session.set("openai_client",openai_client)

@cl.on_chat_end
async def end_chat():
    neo4jdriver = cl.user_session.get("neo4jdriver")
    assert neo4jdriver is not None, "No Neo4j driver found in user session"
    await neo4jdriver.close()
    
@cl.step(name="Cypher Query", type="tool", show_input=True)
async def execute_cypher_query(query: str) -> list:
    """
    Executes the provided Cypher query against the Neo4j database and returns the results.
    Robust error handling is implemented to catch exceptions from invalid queries or empty result sets.

    Returns:
        list: A list of dictionaries representing the records from the database query.

    Raises:
        RuntimeError: If there is an error executing the Cypher query.
    """
    neo4jdriver = cl.user_session.get("neo4jdriver")
    assert neo4jdriver is not None, "No Neo4j driver found in user session"
    try:
        async with neo4jdriver.session() as session:
            result = await session.run(query)
            # Convert the results to a list of dictionaries
            records = await result.data()
            if not records:
                logger.warning("Query executed successfully but returned no results.")
                # You can decide here whether to return an empty list or raise an error
                return []
            return records
    except Neo4jError as e:
        # Catch errors thrown by the Neo4j driver specifically
        logger.error(f"Neo4j error executing query: {e}")
        raise RuntimeError(f"Error executing query: {e}")
    except Exception as e:
        # Catch any other unexpected errors
        logger.error(f"Unexpected error executing query: {e}")
        raise RuntimeError(f"Unexpected error executing query: {e}")
    
cypher_query_tool = tool(
    name="cypher_query",
    description="Executes the provided Cypher query against the Neo4j database and returns the results. Robust error handling is implemented to catch exceptions from invalid queries or empty result sets.",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The Cypher query to execute.",
            },
        },
        "required": ["query"],
    }
)

@cl.step(name="Create Node", type="tool", show_input=True)
async def create_node(node_type: str, name: str, description: str) -> str:
    if node_type in ["Convergence", "Capability", "Milestone", "Trend", "Idea"]:
        return await smart_upsert(node_type, name, description)
    else:
        return await merge_node(node_type, name, description)    

async def merge_node(node_type: str, name: str, description: str) -> str:
    """
    Performs a simple MERGE operation to create or match a node in Neo4j with the given type, name, and description.
    If a node with the same name and type exists, it updates the description; otherwise, it creates a new node.
    Returns the Neo4j elementId of the matched or created node as a string.

    Args:
        node_type (str): The type/label of the node (e.g., 'EmTech', 'Capability', 'Organization').
        name (str): A short, unique name for the node (e.g., 'AI', 'OpenAI').
        description (str): A detailed description of the node.

    Returns:
        str: The elementId of the matched or created node.

    Raises:
        RuntimeError: If the Neo4j driver is not found or the query fails.
    """
    neo4jdriver = cl.user_session.get("neo4jdriver")
    if neo4jdriver is None:
        raise RuntimeError("No Neo4j driver found in user session")

    async with neo4jdriver.session() as session:
        try:
            query = f"""
            MERGE (n:`{node_type}` {{name: $name}})
            SET n.description = $description
            RETURN elementId(n) AS node_id
            """
            result = await session.run(query, name=name, description=description)
            record = await result.single()
            if record is None:
                raise RuntimeError("Failed to merge node")
            return record["node_id"]
        except Exception as e:
            logger.error(f"Error in merge_node: {str(e)}")
            raise RuntimeError(f"Failed to merge node: {str(e)}")

async def smart_upsert(node_type: str, name: str, description: str) -> str:
    """
    Performs a smart UPSERT for a node in Neo4j.
    - Queries for similar nodes based on description embedding similarity >= 0.8 (top 100 candidates, filtered).
    - Uses Grok4 LLM to check if any is semantically the same.
    - If same, combines descriptions using LLM and updates the node.
    - If not, creates a new node.
    - Returns the node's elementId.
    """
    neo4jdriver = cl.user_session.get("neo4jdriver")
    if neo4jdriver is None:
        raise ValueError("No Neo4j driver found in user session")
    xai_client = cl.user_session.get("xai_client")
    if xai_client is None:
        raise ValueError("No xAI client found in user session")
    openai_client = cl.user_session.get("openai_client")
    if openai_client is None:
        raise ValueError("No OpenAI client found in user session")

    index_name = f"{node_type.lower()}_description_embeddings"

    async with neo4jdriver.session() as session:
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
            RETURN elementId(node) AS node_id, node.description AS description, score
            ORDER BY score DESC
            LIMIT 10
            """
            similar_result = await session.run(similar_query, index_name=index_name, vector=new_embedding)
            similar_nodes: List[Dict[str, Union[str, float]]] = await similar_result.data()

            found_same_id = None
            old_description = None
            for sim in similar_nodes:
                old_desc = sim['description']
                logger.info(f"Checking similarity with node {sim['node_id']} (score: {sim['score']:.2f})")
                # Check semantic equivalence with LLM
                equivalence_prompt = (
                    "Are these two descriptions describing essentially the same idea semantically? "
                    "Respond with 'yes' or 'no' only.\n\n"
                    f"Description 1: {old_desc}\n\n"
                    f"Description 2: {description}"
                )
                chat = xai_client.chat.create(
                    model=llm_model,
                    temperature=0.0
                )
                chat.append(system(equivalence_prompt))                
                llm_response = await chat.sample()
                answer = llm_response.content.strip().lower()
                if answer == 'yes':
                    found_same_id = sim['node_id']
                    old_description = old_desc
                    break
                elif answer != 'no':
                    logger.warning(f"Unexpected LLM response: {answer}")

            if found_same_id:
                logger.info(f"Found semantically equivalent node with id: {found_same_id}")

                # Combine descriptions
                combine_prompt = (
                    "Merge these two descriptions into a single, improved, coherent description. "
                    "Retain key details from both, eliminate redundancies, and enhance clarity. "
                    "If Description 2 does not add new information, return Description 1.\n\n"
                    f"Description 1: {old_description}\n\n"
                    f"Description 2: {description}"
                )
                chat = xai_client.chat.create(
                    model=llm_model,
                )
                chat.append(system(combine_prompt))
                combine_response = await chat.sample()
                updated_description = combine_response.content.strip()

                logger.info(f"Old description: {old_description}")
                logger.info(f"New description: {description}")
                logger.info(f"Combined description: {updated_description}")

                # Generate new embedding for the updated description
                updated_emb_response = await openai_client.embeddings.create(
                    model=embedding_model,
                    input=updated_description
                )
                updated_embedding = updated_emb_response.data[0].embedding

                # Update the existing node
                update_query = """
                MATCH (n)
                WHERE elementId(n) = $node_id
                SET n.description = $description, n.embedding = $embedding
                RETURN elementId(n) AS id
                """
                update_result = await session.run(update_query, node_id=found_same_id, description=updated_description, embedding=updated_embedding)
                update_record = await update_result.single()
                if update_record is None:
                    raise RuntimeError(f"Failed to update node with elementId: {found_same_id}")
                return update_record['id']
            else:
                logger.info("No semantically equivalent node found, creating a new node.")
                # Create a new node
                create_query = f"""
                CREATE (n:`{node_type}` {{name: $name, description: $description, embedding: $embedding}})
                RETURN elementId(n) AS id
                """
                create_result = await session.run(create_query, name=name, description=description, embedding=new_embedding)
                create_record = await create_result.single()
                if create_record is None:
                    raise RuntimeError("Failed to create new node")
                return create_record['id']
        except Exception as e:
            logger.error(f"Error in smart_upsert: {str(e)}")
            raise

create_node_tool = tool(
    name="create_node",
    description="""
    Creates or updates a node in the Neo4j knowledge graph, ensuring no duplicates by checking for similar nodes based on their descriptions. 
    If a similar node exists, it updates the node with a merged description. If not, it creates a new node. 
    Returns the node's elementId (a unique string identifier).

    Use this tool to add or update nodes like technologies, capabilities, or organizations in the graph. 
    Provide the node type, a short name, and a detailed description.
    """,
    parameters={
        "type": "object",
        "properties": {
            "node_type": {
                "type": "string",
                "description": "The type of node (e.g., 'EmTech', 'Capability', 'Organization').",
            },
            "name": {
                "type": "string",
                "description": "A short, unique name for the node (e.g., 'AI', 'OpenAI').",
            },
            "description": {
                "type": "string",
                "description": "A detailed description of the node for similarity checks and updates.",
            },
        },
        "required": ["node_type", "name", "description"],
    }
)

@cl.step(name="Create Edge", type="tool", show_input=True)
async def create_edge(source_id: str, target_id: str, relationship_type: str, properties: Optional[Dict[str, Any]] = None) -> Any:
    """
    Creates a directed edge (relationship) between two existing nodes in Neo4j.
    Takes source node elementId, target node elementId, relationship type, and optional properties for the edge.
    Assumes nodes exist and elementIds are valid.
    Returns the created relationship.
    """
    neo4jdriver = cl.user_session.get("neo4jdriver")
    assert neo4jdriver is not None, "No Neo4j driver found in user session"
    if properties is None:
        properties = {}
    async with neo4jdriver.session() as session:
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
        result = await session.run(query, **params)
        record =  await result.single()
        if record:
            return record.data()['r'] # Returns a dict like {'elementId': '...', 'type': 'MAKES', 'properties': {...}, ...}
        return None
        
    
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
            "source_id": {
                "type": "string",
                "description": "The elementId of the source node.",
            },
            "target_id": {
                "type": "string",
                "description": "The elementId of the target node.",
            },
            "relationship_type": {
                "type": "string",
                "description": "The type of relationship (e.g., 'ENABLES', 'USES', 'RELATES_TO').",
            },
            "properties": {
                "type": "object",
                "description": "Optional additional properties for the relationship (e.g., {'explanation': 'details'}).",
                "additionalProperties": True,
            },
        },
        "required": ["source_id", "target_id", "relationship_type"],
    }
)

async def find_node(query_text: str, node_type: str, top_k: int = 5):
    openai_client = cl.user_session.get("openai_client")
    assert openai_client is not None, "No OpenAI client found in user session"
    neo4jdriver = cl.user_session.get("neo4jdriver")
    assert neo4jdriver is not None, "No Neo4j driver found in user session"
    
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
        RETURN {name: node.name, description: node.description} AS node, score
        ORDER BY score DESC
        """
        result = await tx.run(cypher_query, index_name=f"{node_type.lower()}_description_embeddings", top_k=top_k, embedding=query_embedding)
        return [await record.data() async for record in result]

    # execute the query
    async with neo4jdriver.session() as session:
        results = await session.execute_read(vector_search)

    return results

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
            "query_text": {
                "type": "string",
                "description": "The text to search for similar nodes.",
            },
            "node_type": {
                "type": "string",
                "description": "The type of node to search for.",
                "enum": ["Convergence", "Capability", "Milestone", "Trend", "Idea"]
            },
            "top_k": {
                "type": "integer",
                "description": "The number of top results to return (default is 5).",
                "default": 5,
            },
        },
        "required": ["query_text", "node_type"]
    }
)

@cl.on_message
async def on_message(message: cl.Message):
    # Your custom logic goes here...
    xai_client = cl.user_session.get("xai_client")
    assert xai_client is not None, "No xAI client found in user session"
    chat = xai_client.chat.create(
        model="grok-4",
        messages=[system(f"""
            You are a helpful assistant that can esearch a topic, build a knowledge graph and then use it to answer questions.

            The knowledge graph has the following schema:
            {schema}

            When you do research, or process an article break it down to nodes in the knowledge graph and connect them wih edges to capture relationships.
            
            As a rule of thumb, write queries that return the node with its `name` and `description` properties, but not the `embedding` vecotr and the edge with all its properties.
            When working with relationships the query should ask for the properties explicitly
            e.g. 
            instead of
            MATCH (i:Idea)-[r:RELATES_TO]->(n {{name:'3D printing'}}) RETURN i, r, n
            use
            MATCH (i:Idea)-[r:RELATES_TO]->(n {{name:'3D printing'}}) RETURN {{name: i.name, description: i.description}} AS i, r.properties AS relProps, {{name: n.name, description: n.description}} AS n

            Help the user to traverse the graph and find related nodes or edges but always talk in a simple, natural tone. The user does not need to know anything about the graph schema. Don't mention nodes, edges, node and edge types to the user. Just use what respondes you receive from the knowldege graph and make it interesting and fun.

            """
        )],
        tools=[cypher_query_tool, create_node_tool, create_edge_tool, find_node_tool],
    )
    chat.append(user(message.content))
    response = await chat.sample()
    chat.append(response)

    while not response.content:
        if response.tool_calls:
            for tool_call in response.tool_calls:
                tool_name = "unknown"
                try:
                    tool_name = tool_call.function.name
                    tool_args = json.loads(tool_call.function.arguments)
                    
                    if tool_name == "cypher_query":
                        results = await execute_cypher_query(tool_args["query"])
                        chat.append(tool_result(json.dumps(results)))
                    elif tool_name == "create_node":
                        results = await create_node(tool_args["node_type"], tool_args["name"], tool_args["description"])
                        chat.append(tool_result(json.dumps({"elementId": results})))
                    elif tool_name == "create_edge":
                        results = await create_edge(
                            tool_args["source_id"], 
                            tool_args["target_id"], 
                            tool_args["relationship_type"], 
                            tool_args.get("properties", {})
                        )
                        rel_data = results["r"].data() if results else None
                        chat.append(tool_result(json.dumps({"relationship": rel_data})))
                    elif tool_name == "find_node":
                        results = await find_node(tool_args["query_text"], tool_args["node_type"], tool_args.get("top_k", 5))
                        chat.append(tool_result(json.dumps(results)))
    
                except Exception as e:
                    logger.error(f"Error executing tool {tool_name}: {str(e)}")
                    chat.append(tool_result(json.dumps({"error": str(e)})))
    
            response = await chat.sample()            
            chat.append(response)
            
    await cl.Message(content=response.content).send()
    logger.info(f"Final response: {response.content}")
    logger.info(f"Finish reason: {response.finish_reason}")
    logger.info(f"Reasoning tokens: {response.usage.reasoning_tokens}")
    logger.info(f"Total tokens: {response.usage.total_tokens}")
        
