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
            payload={"value": "singularity_is_near"},
            label="The Singularity is Near"
        ),
        cl.Action(
            name="action_button",
            icon="lightbulb",
            payload={"value": "singularity_is_nearer"},
            label="The Singularity is Nearer"
        ),
        cl.Action(
            name="action_button",
            icon="lightbulb",
            payload={"value": "how_to_create_a_mind"},
            label="How to Create a Mind"
        )
    ]

    await cl.Message(content="Click here:", actions=actions).send()
    nodes = []
    cl.user_session.set("nodes", nodes)

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
    llm_model = "grok-4"

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
        WHERE score >= 0.8
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
            Merge these two descriptions into a single, improved, coherent description. Retain key details from both, eliminate redundancies, and enhance clarity. If Description 2 does not add new information, just return Description 1.
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

THE_SINGULARITY_IS_NEAR = [
    ("The Singularity", "A future period in which the pace of technological change will be so rapid and its impact so profound that human life will be irreversibly transformed. It marks the point where the intelligence of our human-machine civilization will vastly exceed the intelligence of unenhanced biological humans."),
    ("The Law of Accelerating Returns", "The core theory underlying the Singularity. It states that fundamental measures of information technology follow a predictable and exponential trajectory of growth. This is because evolution (both biological and technological) builds on its own increasing order, with each stage using the more sophisticated methods of the previous stage to progress, leading to an acceleration of the rate of progress itself."),
    ("The Six Epochs of Evolution", "A framework for viewing the history of the universe as a series of six stages of evolution, each one faster than the last: Physics and Chemistry, Biology and DNA, Brains, Technology, The Merger of Human and Machine Intelligence, and The Universe Wakes Up."),
    ("Exponential vs. Linear View of the Future", "Most people have an 'intuitive linear' view, expecting the future to unfold at the same pace as the recent past. However, the 'historical exponential' view shows that the rate of change is itself accelerating. This leads most people to dramatically underestimate the amount of technological progress that will occur in the coming decades."),
    ("GNR (Genetics, Nanotechnology, Robotics)", "The three overlapping and synergistic revolutions that are driving us toward the Singularity: Genetics (reprogramming biology), Nanotechnology (manipulating matter at the molecular level), and Robotics (creating strong AI by reverse-engineering the human brain)."),
    ("Reverse-Engineering the Human Brain", "The process of scanning and understanding the physical structure and information-processing methods of the human brain in sufficient detail to create nonbiological, software-based models that are functionally equivalent. This is considered the key to achieving strong AI."),
    ("The S-Curve of a Technology Paradigm", "A specific technology or method follows an S-shaped life cycle: slow initial growth, followed by rapid explosive growth, and finally a leveling off as the paradigm matures and its potential is exhausted. The overall exponential trend of technology is a cascade of these S-curves, where a new, more powerful paradigm takes over when the previous one levels off.")
]
THE_SINGULARITY_IS_NEARER = [
    ("The Singularity", "A future period, predicted around 2045, where the pace of technological change will be so rapid and its impact so profound that human life will be irreversibly transformed through the merging of human and artificial intelligence."),
    ("Law of Accelerating Returns (LOAR)", "The core theory that information technologies progress exponentially because each advance facilitates the creation of the next, more powerful generation of technology. This is considered more fundamental than Moore's Law."),
    ("The Six Epochs", "A model of the evolution of information processing in the universe, progressing from (1) Physics/Chemistry, to (2) Biology/DNA, to (3) Brains, to (4) Technology, to (5) The Merger of Human and Machine Intelligence, and finally to (6) The Universe Waking Up."),
    ("Turing Test", "A test for artificial intelligence to determine if it can think and communicate indistinguishably from a human. Kurzweil predicts a robust version will be passed by 2029."),
    ("Brain-Computer Interfaces (BCIs)", "Future technology, likely using nanobots, that will connect the human neocortex directly to the cloud, allowing for a vast expansion of human intelligence and memory."),
    ("Connectionist AI", "An approach to AI based on networks of interconnected nodes (neural networks) that learn from data. This approach, particularly deep learning, has overcome the limitations of rule-based symbolic AI and is driving current AI progress."),
    ("The Neocortex Model for AI", "The idea that the human neocortex, with its hierarchical and modular structure, serves as a blueprint for creating advanced artificial intelligence. AI is seen as re-creating the neocortex's pattern-recognition abilities."),
    ("Panprotopsychism", "A philosophical view on consciousness suggesting it is a fundamental property of the universe. Complex information processing, as found in brains (biological or artificial), 'awakens' this latent potential for subjective experience."),
    ("Digital Immortality / Mind Uploading", "The concept of preserving personal identity by transferring the information pattern of a human brain (memories, personality, skills) to a non-biological substrate, allowing for backups and continued existence beyond the biological body."),
    ("After Life Technology (Replicants)", "The creation of AI-powered avatars of deceased individuals based on their digital footprint (texts, photos, videos). This serves as an early step towards full mind uploading and raises questions about identity and consciousness."),
    ("Exponential Improvement of Human Well-being", "The argument that, contrary to common perception, technology is driving exponential improvements in nearly every aspect of human life, including wealth, health, education, and safety."),
    ("Three Bridges to Radical Life Extension", "A three-stage strategy to extend human lifespan indefinitely. Bridge 1 uses today's medicine and health practices. Bridge 2 involves the biotechnology revolution to cure diseases like cancer and aging. Bridge 3 uses nanotechnology for cellular repair at the molecular level.")
]
HOW_TO_CREATE_A_MIND = [
    ("Pattern Recognition Theory of Mind (PRTM)", "The theory that the basic algorithm of the neocortex is to recognize, remember, and predict patterns. It operates on a hierarchy of patterns, where complex patterns are composed of simpler ones."),
    ("Hierarchical Thinking", "The ability of the neocortex to understand and build complex structures of ideas by recursively linking patterns. This is a key feature of human intelligence."),
    ("Law of Accelerating Returns (LOAR)", "The concept that evolutionary processes, including both biological and technological evolution, accelerate over time. This applies to the exponential growth of information technology and has implications for the future of AI and the brain."),
    ("The Old Brain", "The pre-mammalian parts of the brain that are responsible for basic drives like pleasure and fear. The neocortex modulates and sublimates these primitive motivations."),
    ("Biologically Inspired Digital Neocortex", "The idea of creating artificial intelligence by reverse-engineering the principles of the human neocortex. A digital neocortex could be faster, more scalable, and able to share knowledge instantly."),
    ("Thought Experiments on the Mind", "Using introspection and self-reflection to understand the processes of the mind, such as memory, perception, and the nature of thought."),
    ("Hierarchical Hidden Markov Models (HHMM)", "A mathematical technique used in artificial intelligence for pattern recognition, especially in speech and language, which mirrors the hierarchical and probabilistic nature of the neocortex."),
    ("The Role of Redundancy", "The brain stores important patterns with a high degree of redundancy, which allows for robust recognition even with variations and incomplete information."),
    ("Creativity as Metaphor", "Creativity is the result of the neocortex's ability to act as a metaphor machine, recognizing patterns and making connections between different concepts and disciplines."),
    ("Love as a Neocortical Process", "Love, from an evolutionary perspective, is a mechanism to ensure a stable environment for children while their neocortices develop. It involves both ancient brain chemistry and complex neocortical patterns.")
]

@cl.action_callback("action_button")
async def on_action(action: cl.Action):
    nodes = cl.user_session.get("nodes")
    assert nodes is not None, "No nodes found in user session"
    if action.payload["value"] == "singularity_is_near":
        for name, description in THE_SINGULARITY_IS_NEAR:
            new_node= await smart_upsert("Idea", name, description)
            if new_node in nodes:
                await cl.Message(content=f"UPDATED {name}").send()
            else:
                await cl.Message(content=f"INSERTED {name}").send()
                nodes.append(new_node)
    elif action.payload["value"] == "singularity_is_nearer":
        for name, description in THE_SINGULARITY_IS_NEARER:
            new_node= await smart_upsert("Idea", name, description)
            if new_node in nodes:
                await cl.Message(content=f"UPDATED {name}").send()
            else:
                await cl.Message(content=f"INSERTED {name}").send()
                nodes.append(new_node)
    elif action.payload["value"] == "how_to_create_a_mind":
        for name, description in HOW_TO_CREATE_A_MIND:
            new_node= await smart_upsert("Idea", name, description)
            if new_node in nodes:
                await cl.Message(content=f"UPDATED {name}").send()
            else:
                await cl.Message(content=f"INSERTED {name}").send()
                nodes.append(new_node)
    cl.user_session.set("nodes",nodes)