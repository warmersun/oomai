import os
import json
import chainlit as cl
from chainlit.logger import logger
import asyncio
import re
# drivers
from neo4j import AsyncGraphDatabase
from neo4j.time import Date, DateTime
from groq import AsyncGroq
from openai import AsyncOpenAI
from xai_sdk import AsyncClient
from elevenlabs.client import ElevenLabs
from elevenlabs.types import VoiceSettings
# function tools
from function_tools import (
    execute_cypher_query,
    create_node,
    create_edge,
    find_node,
    GraphOpsCtx,
    x_search,
    plan_tasks,
    get_tasks,
    mark_task_as_running,
    mark_task_as_done,
)


class Neo4jDateEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (Date, DateTime)):
            return o.iso_format()  # Convert Neo4j Date/DateTime to ISO 8601 string
        return super().default(o)

with open("knowledge_graph/schema.md", "r") as f:
    schema = f.read()
with open("knowledge_graph/system_prompt_gpt5.md", "r") as f:
    system_prompt_template = f.read()
system_prompt = system_prompt_template.format(schema=schema)

embedding_model = "text-embedding-3-large"

# Define the tools (functions) - flattened structure for Responses API
tools = [
    {
        "type": "function",
        "name": "execute_cypher_query",
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
    {
        "type": "function",
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
        }
    },
    {
        "type": "function",
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
    {
        "type": "function",
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
                    "enum": ["Convergence", "Capability", "Milestone", "Trend", "Idea", "LTC", "LAC"],
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
    {
        "type": "function",
        "name": "x_search",
        "description": """
        Search on X and return a detailed summary.
        """,
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The search prompt.",
                },
                "included_handles": {
                    "type": "array",
                    "items": {
                        "type": "string",
                    },
                    "description": "Optional list of included X handles.",
                },
            },
            "required": ["prompt"]
        },
    },
    {
        "type": "function",
        "name": "plan_tasks",
        "description": """
        Completely rewrites the list of planned tasks, preserving done tasks.
        Done tasks remain unchanged and are not altered.
        The TaskList will show both DONE and planned tasks.
        """,
        "parameters": {
            "type": "object",
            "properties": {
                "planned_tasks": {
                    "type": "array",
                    "items": {
                        "type": "string",
                    },
                    "description": "The list of planned tasks.",
                },
            },
            "required": ["planned_tasks"]
        }
    },
    {
        "type": "function",
        "name": "get_tasks",
        "description": """
         Returns a dictionary with two lists: tasks that are done and planned tasks.
        Planned tasks include those in READY, RUNNING, FAILED, etc., but not DONE.
        """,
        "parameters": {
            "type": "object",
            "properties": {},
        }
    },
    {
        "type": "function",
        "name": "mark_task_as_running",
        "description": """
        Marks a task as done by updating its status to DONE, only if it's not already done.
        Does not affect done tasks. Refreshes the TaskList, which shows both DONE and planned tasks.
        """,
        "parameters": {
            "type": "object",
            "properties": {
                "task_title": {
                    "type": "string",
                },
            },
            "required": ["task_title"]
        },
    },
    {
        "type": "function",
        "name": "mark_task_as_done",
        "description": """
        Marks a task as running by updating its status to RUNNING, only if it's not done.
        Does not affect done tasks. Refreshes the TaskList, which shows both DONE and planned tasks.
        """,
        "parameters": {
            "type": "object",
            "properties": {
                "task_title": {
                    "type": "string",
                },
            },
            "required": ["task_title"]
        }
    },
]

available_functions = {
    "execute_cypher_query": execute_cypher_query,
    "create_node": create_node,
    "create_edge": create_edge,
    "find_node": find_node,
    "x_search": x_search,
    "plan_tasks": plan_tasks,
    "get_tasks": get_tasks,
    "mark_task_as_running": mark_task_as_running,
    "mark_task_as_done": mark_task_as_done,
}

# Function to create the response with streaming
async def create_response(input_data, previous_response_id=None):
    openai_client = cl.user_session.get("openai_client")
    assert openai_client is not None, "No OpenAI client found in user session"
    kwargs = {
        "model": "gpt-5",
        "instructions": system_prompt,
        "input": input_data,
        "tools": tools,
        "stream": True,
        "reasoning": {"effort": "high"},
    }
    if previous_response_id:
        kwargs["previous_response_id"] = previous_response_id
    return await openai_client.responses.create(**kwargs)

# Function to process the streaming response
async def process_stream(response, ctx: GraphOpsCtx, output_message: cl.Message):
    tool_calls = []
    content = ""
    reasoning = ""
    response_id = None
    current_tool = None
    async for event in response:
        if event.type == "response.created":
            response_id = event.response.id
        elif event.type == "response.output_item.added":
            item = event.item
            if item.type == "function_call":
                current_tool = {
                    "id": item.call_id,
                    "type": "function",
                    "function": {
                        "name": item.name,
                        "arguments": ""
                    }
                }
                tool_calls.append(current_tool)
        elif event.type == "response.function_call_arguments.delta":
            if current_tool:
                current_tool["function"]["arguments"] += event.delta
        elif event.type == "response.output_text.delta":
            content += event.delta
            await output_message.stream_token(event.delta)
        elif event.type == "response.reasoning_summary.delta":
            reasoning += event.delta
            await output_message.stream_token("\nReasoning: " + event.delta)
        elif event.type == "response.done":
            pass  # Can check finish_reason here if needed
    if tool_calls:
        new_input = []
        for tool_call in tool_calls:
            function_name = tool_call["function"]["name"]
            try:
                function_args = json.loads(tool_call["function"]["arguments"])
                if function_name in ["execute_cypher_query", "create_node", "create_edge", "find_node"]:
                    function_args = {"ctx": ctx, **function_args}
            except json.JSONDecodeError:
                function_args = {}
            if function_name in available_functions:
                function_response = await available_functions[function_name](**function_args)
                new_input.append({
                    "type": "function_call_output",
                    "call_id": tool_call["id"],
                    "output":  json.dumps(function_response, cls=Neo4jDateEncoder),
                })
        return response_id, True, new_input
    else:
        if reasoning:
            await output_message.stream_token("\nFull Reasoning Summary: " + reasoning)
        return response_id, False, None

@cl.on_chat_start
async def start():
    cl.user_session.set("input_data", [])
    cl.user_session.set("previous_id", None)
    neo4jdriver = AsyncGraphDatabase.driver(
        os.environ['NEO4J_URI'], 
        auth=(os.environ['NEO4J_USERNAME'], os.environ['NEO4J_PASSWORD'])
    )
    await neo4jdriver.verify_connectivity()
    cl.user_session.set("neo4jdriver", neo4jdriver)
    groq_client = AsyncGroq(
        api_key=os.getenv("GROQ_API_KEY"),
    )
    cl.user_session.set("groq_client", groq_client)
    openai_client = AsyncOpenAI(api_key=os.environ['OPENAI_API_KEY'])
    cl.user_session.set("openai_client",openai_client)
    xai_client = AsyncClient(
        api_key=os.getenv("XAI_API_KEY"),
        timeout=3600, # override default timeout with longer timeout for reasoning models
    )
    cl.user_session.set("xai_client", xai_client)
    elevenlabs_client= ElevenLabs(api_key=os.environ['ELEVENLABS_API_KEY'])
    cl.user_session.set("elevenlabs_client", elevenlabs_client)

@cl.on_chat_end
async def end_chat():
    neo4jdriver = cl.user_session.get("neo4jdriver")
    assert neo4jdriver is not None, "No Neo4j driver found in user session"
    await neo4jdriver.close()
    cl.user_session.set("neo4jdriver", None)
    
@cl.on_message
async def on_message(message: cl.Message):
    # TTS cleanup
    last_tts_action = cl.user_session.get("tts_action")
    if last_tts_action is not None:
        await last_tts_action.remove()
    # get drivers from session
    neo4jdriver = cl.user_session.get("neo4jdriver")
    assert neo4jdriver is not None, "No Neo4j driver found in user session"
    openai_client = cl.user_session.get("openai_client")
    assert openai_client is not None, "No OpenAI client found in user session"
    # create Neo4j session 
    async with neo4jdriver.session() as session:
        tts_action = cl.Action(name="tts", payload={"value": "tts"}, icon="circle-play", tooltip="Read out loud" )
        # setup context: begin Neo5j transation and create lock
        tx = await session.begin_transaction()
        lock = asyncio.Lock()
        ctx = GraphOpsCtx(tx, lock)          
        try:
            input_data = cl.user_session.get("input_data")
            input_data.append({
                "role": "user",
                "content": message.content
            })
            previous_id = cl.user_session.get("previous_id")

            output_message = cl.Message(content="", actions=[tts_action])

            while True:
                response = await create_response(input_data, previous_id)
                previous_id, needs_continue, new_input = await process_stream(response, ctx, output_message)
                if not needs_continue:
                    break
                input_data = new_input

            await output_message.update()
            cl.user_session.set("input_data", input_data)
            cl.user_session.set("previous_id", previous_id)

        except Exception as e:
            logger.error(f"Rolling back the Neo4j transaction. Error: {str(e)}")
            await tx.cancel()
        finally:
            cl.user_session.set("tts_action", tts_action)
            await tx.close()

# Text to Speech

def clean_text_for_tts(text: str) -> str:
    """Remove markdown, links and other artifacts before TTS."""
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"`[^`]*`", "", text)
    text = re.sub(r"!\[[^\]]*\]\([^\)]+\)", "", text)
    text = re.sub(r"\[[^\]]+\]\([^\)]+\)", "", text)
    text = re.sub(r"[*_~]", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def text_to_speech(text: str):
    elevenlabs_client = cl.user_session.get("elevenlabs_client")
    assert elevenlabs_client is not None, "No ElevenLabs client found in user session"
    text = clean_text_for_tts(text)
    audio = elevenlabs_client.text_to_speech.convert(
        model_id="eleven_flash_v2_5",
        text=text,
        voice_id=os.environ['ELEVENLABS_VOICE_ID'],
        output_format="mp3_44100_128",
        voice_settings=VoiceSettings(
            stability=0.5,
            similarity_boost=0.76,
            use_speaker_boost=True,
            speed=1.0
        )
    )
    return audio

@cl.action_callback("tts")
async def tts(action: cl.Action):
    last_message = cl.user_session.get("last_message")
    if last_message is not None:
        if not isinstance(last_message, str):
            last_message = getattr(last_message, "response", str(last_message))
        audio_generator = text_to_speech(last_message)

        output_audio_el = cl.Audio(
            auto_play=True,
            content=b"".join(audio_generator),
            mime="audio/mp3"
        )

        await cl.Message(content="👂 Listen...", elements=[output_audio_el]).send()

    await action.remove()
