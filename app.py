import chainlit as cl
import os
from xai_sdk import AsyncClient
from xai_sdk.chat import system, user, tool, tool_result
from neo4j import AsyncGraphDatabase
from neo4j.exceptions import Neo4jError
from chainlit.logger import logger
import json
from openai import AsyncOpenAI
import asyncio
from typing import List, Dict, Any



with open("knowledge_graph/schema.md", "r") as f:
    schema = f.read()


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

    # Sending an action button within a chatbot message
    actions = [
        cl.Action(
            name="action_button",
            icon="lightbulb",
            payload={"value": "idea1"},
            label="Singularity 1"
        ),
        cl.Action(
            name="action_button",
            icon="lightbulb",
            payload={"value": "idea2"},
            label="Singularity 2"
        ),
        cl.Action(
            name="action_button",
            icon="lightbulb-off",
            payload={"value": "idea3"},
            label="LEV 1"
        )
    ]

    await cl.Message(content="Click here:", actions=actions).send()

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

async def smart_upsert(node_type: str, name: str, description: str) -> str:
    """
    Performs a smart UPSERT for a node in Neo4j.
    - Queries for similar nodes based on description embedding similarity >= 0.9 (top 100 candidates, filtered).
    - Uses Grok4 LLM to check if any is semantically the same.
    - If same, combines descriptions using LLM and updates the node.
    - If not, creates a new node.
    - Returns the node's elementId.
    """
    neo4jdriver = cl.user_session.get("neo4jdriver")
    assert neo4jdriver is not None, "No Neo4j driver found in user session"
    xai_client = cl.user_session.get("xai_client")
    assert xai_client is not None, "No xAI client found in user session"
    openai_client = cl.user_session.get("openai_client")
    assert openai_client is not None, "No OpenAI client found in user session"
    
    index_name = f"{node_type.lower()}_description_embeddings"
    embedding_model = "text-embedding-3-large"  # OpenAI's embedding model
    llm_model = "grok-3-mini"

    async with neo4jdriver.session() as session:
        # Generate embedding for the new description using OpenAI
        emb_response = await openai_client.embeddings.create(
            model=embedding_model,
            input=description
        )
        new_embedding = emb_response.data[0].embedding

        # Query for similar nodes with score >= 0.9 (use large topK and filter)
        similar_query = """
        CALL db.index.vector.queryNodes($index_name, 100, $vector)
        YIELD node, score
        WHERE score >= 0.9
        RETURN elementId(node) AS node_id, node.description AS description, score
        ORDER BY score DESC
        LIMIT 10
        """
        similar_result = await session.run(similar_query, index_name=index_name, vector=new_embedding)
        similar_nodes: List[Dict[str, Any]] = await similar_result.data()

        found_same_id = None
        old_description = None
        for sim in similar_nodes:
            old_desc = sim['description']
            logger.info(f"Checking similarity with node {sim['node_id']} with the old description: {old_desc}")
            # Use xAI's Grok4 LLM to check semantic equivalence
            equivalence_prompt = f"""
            Are these two descriptions describing essentially the same idea semantically? Respond with 'yes' or 'no' only.

            Description 1: {old_desc}

            Description 2: {description}
            """
            chat = xai_client.chat.create(
                model=llm_model,
                messages=[system(equivalence_prompt)],
                temperature=0.0  # For deterministic response
            )
            llm_response = await chat.sample()
            answer = llm_response.content.strip().lower()
            if answer == 'yes':
                found_same_id = sim['node_id']
                old_description = old_desc  # Save for combining
                break

        if found_same_id:
            logger.info(f"Found semantically equivalent node with id: {found_same_id}")
            
            # Combine descriptions using xAI's Grok4 LLM
            combine_prompt = f"""
            Merge these two descriptions into a single, improved, coherent description. Retain key details from both, eliminate redundancies, and enhance clarity.
            Return the combined description only.

            Description 1: {old_description}

            Description 2: {description}
            """
            chat = xai_client.chat.create(
                model=llm_model,
                messages=[system(combine_prompt)],
            )
            combine_response = await chat.sample()
            updated_description = combine_response.content.strip()

            logger.info(f"Old description: {old_description}")
            logger.info(f"New description: {description}")
            logger.info(f"Combined description: {updated_description}")

            # Generate new embedding for the updated description using OpenAI
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
            return create_record['id']

@cl.on_message
async def on_message(message: cl.Message):
    # Your custom logic goes here...
    xai_client = cl.user_session.get("xai_client")
    assert xai_client is not None, "No xAI client found in user session"
    chat = xai_client.chat.create(
        model="grok-4",
        messages=[system(f"""
            You are a helpful assistant that can answer questions about a knowledge graph. Use the `execute_cypher_query` function tool to query the graph.

            As a rule of thumb, write queries that return the entire node or edge so you can see all properties.
            When working with relationships the query should ask for the properties explicitly
            e.g. 
            instead of
            MATCH (i:Idea)-[r:RELATES_TO]->(n {{name:'3D printing'}}) RETURN i, r, n
            use
            MATCH (i:Idea)-[r:RELATES_TO]->(n {{name:'3D printing'}}) RETURN i, r.properties AS relProps, n

            Help the user to traverse the graph and find related nodes or edges but always talk in a simple, natural tone. The user does not need to know anything about the graph schema. Don't mention nodes, edges, node and edge types to the user. Just use what respondes you receive from the knowldege graph and make it interesting and fun.

            The knowledge graph has the following schema:
            {schema}
            """
        )],
        tools=[cypher_query_tool],
    )
    chat.append(user(message.content))
    response = await chat.sample()
    
    # usage = response.usage
    # # Send a response back to the user
    # elements = [
    #     cl.Text(name="usage", content=f"Tokens used - Prompt: {usage.prompt_tokens}, Completion: {usage.completion_tokens}, Reasoning: {usage.reasoning_tokens}, Total: {usage.total_tokens}", display="inline")
    # ]

    if response.content:
        await cl.Message(content=response.content).send()
        
    if response.tool_calls:
        for tool_call in response.tool_calls:
            tool_args = json.loads(tool_call.function.arguments)
            results = await execute_cypher_query(tool_args["query"])
            chat.append(tool_result(json.dumps(results)))

        response = await chat.sample()
        await cl.Message(content=response.content).send()
            
@cl.action_callback("action_button")
async def on_action(action: cl.Action):
    if action.payload["value"] == "idea1":
        str = await smart_upsert("Idea", "Singularity", "The technological singularity is a hypothetical future point where artificial intelligence surpasses human intelligence, leading to unpredictable, rapid advancements in technology and society.")
        await cl.Message(content=f"node: {str}").send()
    elif action.payload["value"] == "idea2":
        str = await smart_upsert("Idea", "Singularity", "The Singularity refers to a hypothetical future point when technological growth, driven by superintelligent AI, becomes uncontrollable and irreversible, profoundly transforming human civilization.")
        await cl.Message(content=f"node: {str}").send()
    elif action.payload["value"] == "idea3":
        str = await smart_upsert("Idea", "LEV", "LEV is a hypothetical point in time when technological growth becomes uncontrollable and irreversible, resulting in unforeseeable changes to human civilization.")