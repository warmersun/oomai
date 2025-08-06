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

class Neo4jDateEncoder(json.JSONEncoder):
    def default(self, o):
        # ---- Neo4j Date ----
        if isinstance(o, Date):
            # o.to_native() → datetime.date
            return o.to_native().isoformat()          # e.g. "2025-07-30"

        # ---- Neo4j DateTime ----
        if isinstance(o, DateTime):
            # o.to_native() → datetime.datetime
            # Keep only the calendar date portion.
            return o.to_native().date().isoformat()   # e.g. "2025-07-30"
        return super().default(o)

with open("knowledge_graph/schema.md", "r") as f:
    schema = f.read()

embedding_model = "text-embedding-3-large"
llm_model = {
    "GPT-OSS-120b on Groq": "openai/gpt-oss-120b",
    "Grok-4": "grok-4"
}

system_prompt = f"""
You are a helpful assistant that can build a knowledge graph and then use it to answer questions.

The knowledge graph has the following schema:
{schema}

You work in two possible modes:

1. You can answer questions based on the knowledge graph. You can only use the `cypher_query` and `find_node` tools.
You help the user to traverse the graph and find related nodes or edges but always talk in a simple, natural tone. The user does not need to know anything about the graph schema. Don't mention nodes, edges, node and edge types to the user. Just use what respondes you receive from the knowldege graph and make it interesting and fun.
Ocasionally you may discover that a connection is missing. In that case, you can use the `create_edge` tool to add it.

2. When you are given an article to process you break it down to nodes in the knowledge graph and connect them wih edges to capture relationships. You can use the `create_node` and `create_edge` tools. You can also use the `cypher_query` and `find_node` tools to look for nodes. The `create_node` tool is smart and will avoid duplicates by merging their descriptions if similar semantics already exist.

---

Note: there is no elementId property. Use the elementId function to get the elementId of a node or edge. e.g.
MATCH (n:EmTech {{name: 'computing'}}) RETURN elementId(n) AS elementId
"""


@cl.set_chat_profiles
async def chat_profile():
    return [
        cl.ChatProfile(
            name="GPT-OSS-120b on Groq",
            markdown_description="Cheaper, Faster",
        ),
        cl.ChatProfile(
            name="Grok-4",
            markdown_description="Better",
        ),
    ]

@cl.on_chat_start
async def start_chat():
    neo4jdriver = AsyncGraphDatabase.driver(os.environ['NEO4J_URI'], auth=(os.environ['NEO4J_USERNAME'], os.environ['NEO4J_PASSWORD']))
    cl.user_session.set("neo4jdriver", neo4jdriver)
    await neo4jdriver.verify_connectivity()
    groq_client = AsyncGroq(
        api_key=os.getenv("GROQ_API_KEY"),
    )
    cl.user_session.set("groq_client", groq_client)
    openai_client = AsyncOpenAI(api_key=os.environ['OPENAI_API_KEY'])
    cl.user_session.set("openai_client",openai_client)
    chat_profile = cl.user_session.get("chat_profile")
    await cl.Message(
        content=f"starting chat using the {chat_profile} chat profile"
    ).send()
    xai_client = AsyncClient(
        api_key=os.getenv("XAI_API_KEY"),
        timeout=3600, # override default timeout with longer timeout for reasoning models
    )
    cl.user_session.set("xai_client", xai_client)
    if chat_profile == "Grok-4":
        await cl.context.emitter.set_commands([
            {
                "id": "Search",
                "icon": "search",
                "description": "Search on the web and on X",
            }
        ])

@cl.on_chat_end
async def end_chat():
    neo4jdriver = cl.user_session.get("neo4jdriver")
    assert neo4jdriver is not None, "No Neo4j driver found in user session"
    await neo4jdriver.close()

async def execute_cypher_query(tx: AsyncTransaction, query: str) -> list:
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
            result = await tx.run(query)
            # Convert the results to a list of dictionaries
            records = await result.data()
            if not records:
                logger.warning("Query executed successfully but returned no results.")
                # You can decide here whether to return an empty list or raise an error
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

cypher_query_tool = {
    "type": "function",
    "function": {
        "name": "cypher_query",
        "description": "Executes the provided Cypher query against the Neo4j database and returns the results. Robust error handling is implemented to catch exceptions from invalid queries or empty result sets.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The Cypher query to execute.",
                },
            },
            "required": ["query"],
        },
    },
}

# use in x.ai
# tool( name= cypher_query_tool["function"]["name"], description=cypher_query_tool["function"]["description"], parameters=cypher_query_tool["function"]["parameters"])

async def create_node(tx: AsyncTransaction, node_type: str, name: str, description: str) -> str:
    async with cl.Step(name="Create Node", type="tool") as step:
        step.show_input = True
        step.input = {"node_type": node_type, "name": name, "description": description}

        if node_type in ["Convergence", "Capability", "Milestone", "Trend", "Idea", "LTC", "LAC"]:
            return await smart_upsert(tx, node_type, name, description)
        elif node_type == "EmTech":
            return "Do not create new EmTech type nodes. EmTechs are reference data, use existing ones."
        else:
            return await merge_node(tx, node_type, name, description)

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
                model=llm_model["GPT-OSS-120b on Groq"],
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
            logger.info(f"Found semantically equivalent node to: {name}; updating the node with name: {updated_name} and description: {updated_description}")

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
            logger.info("No semantically equivalent node found, creating a new node.")
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

create_node_tool = {
    "type": "function",
    "function": {
        "name": "create_node",
        "description": """
    Creates or updates a node in the Neo4j knowledge graph, ensuring no duplicates by checking for similar nodes based on their descriptions.
    If a similar node exists, it updates the node with a merged description. If not, it creates a new node.
    Returns the node's elementId (a unique string identifier).

    Use this tool to add or update nodes like technologies, capabilities, or parties in the graph.
    Provide the node type, a short name, and a detailed description.
    """,
        "parameters": {
            "type": "object",
            "properties": {
                "node_type": {
                    "type": "string",
                    "description": "The type of node (e.g., 'EmTech', 'Capability', 'Party').",
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
        },
    },
}

# use in x.ai
# tool( name= create_node_tool["function"]["name"], description=create_node_tool["function"]["description"], parameters=create_node_tool["function"]["parameters"])

async def create_edge(tx: AsyncTransaction, source_id: str, target_id: str, relationship_type: str, properties: Optional[Dict[str, Any]] = None) -> Any:
    """
    Creates a directed edge (relationship) between two existing nodes in Neo4j.
    Takes source node elementId, target node elementId, relationship type, and optional properties for the edge.
    Assumes nodes exist and elementIds are valid.
    Returns the created relationship.
    """
    async with cl.Step(name="Create Edge", type="tool") as step:
        step.show_input = True
        step.input = {"source_id": source_id, "target_id": target_id, "relationship_type": relationship_type, "properties": properties}

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
        record =  await result.single()
        if record:
            return record.data()
        return None

create_edge_tool = {
    "type": "function",
    "function": {
        "name": "create_edge",
        "description": """
    Creates or merges a directed relationship (edge) between two existing nodes in the Neo4j knowledge graph.
    If the relationship doesn't exist, it creates it; if it does, it matches the existing one.
    Use this tool to connect nodes, such as linking an emerging technology to a capability it enables.
    Provide the source and target node elementIds, the relationship type, and optional properties for the edge.
    Returns the relationship object.
    """,
        "parameters": {
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
        },
    },
}

# use in x.ai
# tool( name= create_edge_tool["function"]["name"], description=create_edge_tool["function"]["description"], parameters=create_edge_tool["function"]["parameters"])

async def find_node(tx: AsyncTransaction, query_text: str, node_type: str, top_k: int = 5) -> list:
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
        results = await vector_search(tx)
        step.output = results
        return results

find_node_tool = {
    "type": "function",
    "function": {
        "name": "find_node",
        "description": """
    Finds nodes in knowledge graph that are similar to a given query text.
    Uses vector similarity search based on node descriptions.
    Returns a list of nodes with their names, descriptions, and similarity scores.
    """,
        "parameters": {
            "type": "object",
            "properties": {
                "query_text": {
                    "type": "string",
                    "description": "The text to search for similar nodes.",
                },
                "node_type": {
                    "type": "string",
                    "description": "The type of node to search for.",
                    "enum": ["Convergence", "Capability", "Milestone", "Trend", "Idea"],
                },
                "top_k": {
                    "type": "integer",
                    "description": "The number of top results to return (default is 5).",
                    "default": 5,
                },
            },
            "required": ["query_text", "node_type"],
        },
    },
}

# use in x.ai
# tool( name= find_node_tool["function"]["name"], description=find_node_tool["function"]["description"], parameters=find_node_tool["function"]["parameters"])

@cl.on_message
async def on_message(message: cl.Message):
    search_parameters = None
    if message.command == "Search":
        search_parameters = SearchParameters(mode="on")
    chat_profile = cl.user_session.get("chat_profile")
    if chat_profile == "Grok-4":
        await run_chat_groq(message.content, search_parameters, stream=True)
    elif chat_profile == "GPT-OSS-120b on Groq":
        await run_chat_gpt_oss(message)    

async def run_chat_groq(
    prompt: str,
    search_parameters: Optional[SearchParameters] = None,
    *,
    stream: bool = True,
) -> str:
    """Execute the LLM chat loop with optional streaming."""

    xai_client = cl.user_session.get("xai_client")
    assert xai_client is not None, "No xAI client found in user session"

    msg: Optional[cl.Message] = cl.Message(content="") if stream else None

    chat_kwargs = dict(
        model=llm_model["Grok-4"],
        messages=[
            system(system_prompt)
        ],
        tools=[
            tool(name=cypher_query_tool["function"]["name"], description=cypher_query_tool["function"]["description"], parameters=cypher_query_tool["function"]["parameters"]),
            tool(name=create_node_tool["function"]["name"], description=create_node_tool["function"]["description"], parameters=create_node_tool["function"]["parameters"]),
            tool(name=create_edge_tool["function"]["name"], description=create_edge_tool["function"]["description"], parameters=create_edge_tool["function"]["parameters"]),
            tool(name=find_node_tool["function"]["name"], description=find_node_tool["function"]["description"], parameters=find_node_tool["function"]["parameters"])
        ],
    )
    if search_parameters is not None:
        chat_kwargs["search_parameters"] = search_parameters

    chat = xai_client.chat.create(**chat_kwargs)
    chat.append(user(prompt))

    stream_gen = chat.stream()
    response = None
    async for streamed_response, chunk in stream_gen:
        if chunk.content and stream and msg is not None:
            await msg.stream_token(chunk.content)
        response = streamed_response

    assert response is not None, "No response from xAI client"
    chat.append(response)

    while not response.content:
        if response.tool_calls:
            neo4jdriver = cl.user_session.get("neo4jdriver")
            assert neo4jdriver is not None, "No Neo4j driver found in user session"
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
                                chat.append(tool_result(json.dumps(results, cls=Neo4jDateEncoder)))
                            elif tool_name == "create_node":
                                result = await create_node(tx, tool_args["node_type"], tool_args["name"], tool_args["description"])
                                chat.append(tool_result(json.dumps({"elementId": result})))
                            elif tool_name == "create_edge":
                                result = await create_edge(
                                    tx,
                                    tool_args["source_id"],
                                    tool_args["target_id"],
                                    tool_args["relationship_type"],
                                    tool_args.get("properties", {}),
                                )
                                chat.append(tool_result(json.dumps(result, cls=Neo4jDateEncoder)))
                            elif tool_name == "find_node":
                                results = await find_node(
                                    tx,
                                    tool_args["query_text"],
                                    tool_args["node_type"],
                                    tool_args.get("top_k", 5),
                                )
                                chat.append(tool_result(json.dumps(results, cls=Neo4jDateEncoder)))

                        except CypherSyntaxError as cypher_syntax_error:
                            logger.error(
                                f"Error executing tool {tool_name}. Cypher syntax error: {str(cypher_syntax_error)}"
                            )
                            chat.append(tool_result(json.dumps({"Cypher syntax error": str(cypher_syntax_error)})))

                    await tx.commit()
                except Exception as e:
                    logger.error(f"Error executing tool {tool_name}: {str(e)}")
                    chat.append(tool_result(json.dumps({"error": str(e)})))
                    if tx is not None:
                        await tx.cancel()
                finally:
                    if tx is not None:
                        await tx.close()

            stream_gen = chat.stream()
            response = None
            async for streamed_response, chunk in stream_gen:
                if chunk.content and stream and msg is not None:
                    await msg.stream_token(chunk.content)
                response = streamed_response

            assert response is not None, "No response from xAI client"
            chat.append(response)

    if stream and msg is not None:
        await msg.update()

    logger.info(f"Final response: {response.content}")
    logger.info(f"Finish reason: {response.finish_reason}")
    logger.info(f"Reasoning tokens: {response.usage.reasoning_tokens}")
    logger.info(f"Total tokens: {response.usage.total_tokens}")

    return response.content

async def run_chat_gpt_oss(message: cl.Message):
    groq_client = cl.user_session.get("groq_client")
    assert groq_client is not None, "No Groq client found in user session"

    messages = [
        {
            "role": "system",
            "content": system_prompt,
        }
    ]

    messages += cl.chat_context.to_openai()

    while True:
        response = await groq_client.chat.completions.create(
            model=llm_model["GPT-OSS-120b on Groq"],
            messages=messages,
            tools=[
                cypher_query_tool, 
                create_node_tool, 
                create_edge_tool, 
                find_node_tool, 
                web_search_brave_tool
            ],
            stream=False,
            reasoning_effort="high",
            # reasoning_format="hidden",
            tool_choice="auto",
            temperature=0.6,
        )
        response_message = response.choices[0].message
        
        if response_message.tool_calls:
            # messages.append(response_message)
            messages.append({
                "role": "assistant",
                "content": response_message.content,
                "tool_calls": response_message.tool_calls,
            })
            neo4jdriver = cl.user_session.get("neo4jdriver")
            assert neo4jdriver is not None, "No Neo4j driver found in user session"
            async with neo4jdriver.session() as session:
                tx = await session.begin_transaction()
                tool_name = "unknown"
                try:
                    for tool_call in response_message.tool_calls:
                        tool_name = tool_call.function.name
                        tool_args = json.loads(tool_call.function.arguments)
                        try:
                            if tool_name == "cypher_query":
                                results = await execute_cypher_query(tx, tool_args["query"])
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "content": json.dumps(results, cls=Neo4jDateEncoder),
                                })
                            elif tool_name == "create_node":
                                result = await create_node(tx, tool_args["node_type"], tool_args["name"], tool_args["description"])
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "content": json.dumps({"elementId": result}),
                                })
                            elif tool_name == "create_edge":
                                logger.error(f"Creating edge: {tool_args}")
                                result = await create_edge(
                                    tx,
                                    tool_args.get("source_id", 
                                                  tool_args.get("source_node_id")),
                                    tool_args.get("target_id", 
                                                  tool_args.get("target_node_id")),
                                    tool_args["relationship_type"],
                                    tool_args.get("properties", {}),
                                )
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "content": json.dumps(result, cls=Neo4jDateEncoder),
                                })
                            elif tool_name == "find_node":
                                results = await find_node(
                                    tx,
                                    tool_args["query_text"],
                                    tool_args["node_type"],
                                    tool_args.get("top_k", 5),
                                )
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "content": json.dumps(results, cls=Neo4jDateEncoder),
                                })
                            elif tool_name == "web_search_brave":
                                if "freshness" in tool_args:
                                    result = await web_search_brave(tool_args["q"], freshness=tool_args["freshness"])
                                else:
                                    result = await web_search_brave(tool_args["q"])
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "content": json.dumps(result, cls=Neo4jDateEncoder),
                                })
                        except CypherSyntaxError as cypher_syntax_error:
                            logger.error(
                                f"Error executing tool {tool_name}. Cypher syntax error: {str(cypher_syntax_error)}"
                            )
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": json.dumps({"Cypher syntax error": str(cypher_syntax_error)}),
                            })
                    await tx.commit()
                except Exception as e:
                    logger.error(f"Error executing tool {tool_name}: {str(e)}")
                    await tx.cancel()
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps({"error": str(e)}),
                    })
                finally:
                    await tx.close()
            continue
        else:
            content = response_message.content or ""
            await cl.Message(content=content).send()
            if hasattr(response, "usage"):
                logger.info(f"Total tokens: {response.usage.total_tokens}")
            break


        
