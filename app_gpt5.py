import os
import json
import chainlit as cl
from chainlit.logger import logger
from chainlit.input_widget import Select
import asyncio
import re
import yaml
from typing import Optional
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
    TOOLS_DEFINITIONS,
)


class Neo4jDateEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (Date, DateTime)):
            return o.iso_format()  # Convert Neo4j Date/DateTime to ISO 8601 string
        return super().default(o)

with open("knowledge_graph/schema.md", "r") as f:
    schema = f.read()
with open("knowledge_graph/system_prompt_gpt5.md", "r") as f:
    system_prompt_edit_template = f.read()
with open("knowledge_graph/system_prompt_gpt5_readonly.md", "r") as f:
    system_prompt_readonly_template = f.read()
SYSTEM_PROMPT_EDIT = system_prompt_edit_template.format(schema=schema)
SYSTEM_PROMPT_READONLY = system_prompt_readonly_template.format(schema=schema)

with open("knowledge_graph/command_sources.yaml", "r") as f:
    config = yaml.safe_load(f)
COMMAND_DATA = config['commands']


# Define the tools (functions) - flattened structure for Responses API
TOOLS_EDIT = [
    TOOLS_DEFINITIONS["execute_cypher_query"],
    TOOLS_DEFINITIONS["create_node"],
    TOOLS_DEFINITIONS["create_edge"],
    TOOLS_DEFINITIONS["find_node"],
    TOOLS_DEFINITIONS["x_search"],
    TOOLS_DEFINITIONS["plan_tasks"],
    TOOLS_DEFINITIONS["get_tasks"],
    TOOLS_DEFINITIONS["mark_task_as_running"],
    TOOLS_DEFINITIONS["mark_task_as_done"],
    {"type": "web_search_preview", "search_context_size":"high"},
]

TOOLS_READONLY = [
    TOOLS_DEFINITIONS["execute_cypher_query"],
    TOOLS_DEFINITIONS["find_node"],
    TOOLS_DEFINITIONS["x_search"],
    TOOLS_DEFINITIONS["plan_tasks"],
    TOOLS_DEFINITIONS["get_tasks"],
    TOOLS_DEFINITIONS["mark_task_as_running"],
    TOOLS_DEFINITIONS["mark_task_as_done"],
    {"type": "web_search_preview", "search_context_size":"high"}
]

AVAILABLE_FUNCTIONS_EDIT = {
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

AVAILABLE_FUNCTIONS_READONLY = {
    "execute_cypher_query": execute_cypher_query,
    "find_node": find_node,
    "x_search": x_search,
    "plan_tasks": plan_tasks,
    "get_tasks": get_tasks,
    "mark_task_as_running": mark_task_as_running,
    "mark_task_as_done": mark_task_as_done,
}

READ_ONLY_PROFILE = "Read-Only"
READ_EDIT_PROFILE = "Read/Edit"

# Function to create the response with streaming
async def create_response(input_data, previous_response_id=None):
    openai_client = cl.user_session.get("openai_client")
    assert openai_client is not None, "No OpenAI client found in user session"
    reasoning_effort = cl.user_session.get("reasoning_effort")
    assert reasoning_effort is not None, "No reasoning effort found in user session"
    current_user = cl.user_session.get("user")
    assert current_user is not None, "No user found in user session"
    system_prompt=cl.user_session.get("system_prompt")
    assert system_prompt is not None, "No system prompt found in user session"
    tools=cl.user_session.get("tools")
    assert tools is not None, "No tools found in user session"
    kwargs = {
        "model": "gpt-5",
        "instructions": system_prompt,
        "input": input_data,
        "tools": tools,
        "stream": True,
        "reasoning": {"effort": reasoning_effort},
        "safety_identifier": current_user.identifier,
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
    search_msg = cl.Message(content="Searching the web...")
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
                        "arguments": "",
                    }
                }
                tool_calls.append(current_tool)
            elif item.type == "custom_tool_call":
                current_tool = {
                    "id": item.call_id,
                    "type": "custom_tool",
                    "name": item.name,
                    "input": item.input,
                }
                tool_calls.append(current_tool)
        elif event.type == "response.function_call_arguments.delta":
            if current_tool:
                current_tool["function"]["arguments"] += event.delta
        elif event.type == "response.custom_tool_call_input.delta":
            if current_tool:
                current_tool["input"] += event.delta
        elif event.type == "response.output_text.delta":
            content += event.delta
            await output_message.stream_token(event.delta)
        elif event.type == "response.reasoning_summary.delta":
            reasoning += event.delta
            await output_message.stream_token("\nReasoning: " + event.delta)
        elif event.type == "response.web_search_call.searching":
            await search_msg.send()
        elif event.type == "response.web_search_call.completed":
            await search_msg.remove()
        elif event.type == "response.done":
            pass  # Can check finish_reason here if needed
    if tool_calls:
        available_functions = cl.user_session.get("available_functions")
        assert available_functions is not None, "No available functions found in user session"
        new_input = []
        for tool_call in tool_calls:
            if tool_call["type"] == "custom_tool":
                # custom tool call
                if tool_call["name"] == "execute_cypher_query":
                    function_response = await execute_cypher_query(ctx, tool_call["input"])
                    new_input.append({
                        "type": "function_call_output",
                        "call_id": tool_call["id"],
                        "output":  json.dumps(function_response, cls=Neo4jDateEncoder),
                    })
            else:
                function_name = tool_call["function"]["name"]
                try:
                    function_args = json.loads(tool_call["function"]["arguments"])
                    if function_name in ["create_node", "create_edge", "find_node"]:
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

commands = [
    {
        "id": command_id,
        "icon": data['icon'],
        "description": data['description']
    }
    for command_id, data in COMMAND_DATA.items()
]

@cl.set_chat_profiles
async def set_chat_profile(current_user: cl.User):
    profiles = [
        cl.ChatProfile(
            name=READ_ONLY_PROFILE,
            markdown_description="Query the knowledge graph in read-only mode.",
        )
    ]
    if current_user.metadata.get("role") == "admin":
        profiles.append(
            cl.ChatProfile(
                name=READ_EDIT_PROFILE,
                markdown_description="Query and update the knowledge graph.",
            )
        )
    return profiles

@cl.on_chat_start
async def start():
    cl.user_session.set("input_data", [])
    cl.user_session.set("previous_id", None)
    neo4jdriver = AsyncGraphDatabase.driver(
        os.environ['NEO4J_URI'],
        auth=(os.environ['NEO4J_USERNAME'], os.environ['NEO4J_PASSWORD']),
        liveness_check_timeout=0,
        max_connection_lifetime=2700,
        # keep_alive=False,
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
    # settings
    settings = await cl.ChatSettings(
        [
            Select(
                id="reasoning_effort",
                label="Reasoning Effort",
                values=["low", "medium", "high"],
                initial_index=2,
                tooltip=" Controls how many reasoning tokens the model generates before producing a response. Higher takes longer to respond but gives better results.",
                description="Set the reasoning effort for GPT-5.",
            )
        ]
    ).send()
    cl.user_session.set("reasoning_effort", settings["reasoning_effort"])

    chat_profile = cl.user_session.get("chat_profile")
    if chat_profile == READ_EDIT_PROFILE:
        cl.user_session.set("system_prompt", SYSTEM_PROMPT_EDIT)
        cl.user_session.set("tools", TOOLS_EDIT)
        cl.user_session.set("available_functions", AVAILABLE_FUNCTIONS_EDIT)
        # only edit mode has commands
        await cl.context.emitter.set_commands(commands)
    else:
        cl.user_session.set("system_prompt", SYSTEM_PROMPT_READONLY)
        cl.user_session.set("tools", TOOLS_READONLY)
        cl.user_session.set("available_functions", AVAILABLE_FUNCTIONS_READONLY)

@cl.on_settings_update
async def on_settings_update(settings):
    cl.user_session.set("reasoning_effort", settings["reasoning_effort"])

@cl.on_chat_end
async def end_chat():
    neo4jdriver = cl.user_session.get("neo4jdriver")
    if neo4jdriver is not None:
        await neo4jdriver.close()
    cl.user_session.set("neo4jdriver", None)

@cl.on_chat_resume
async def resume_chat():
    neo4jdriver = cl.user_session.get("neo4jdriver")
    if neo4jdriver is None:
        logger.warning("No Neo4j driver found in user session, creating a new one.")
        neo4jdriver = AsyncGraphDatabase.driver(
            os.environ['NEO4J_URI'],
            auth=(os.environ['NEO4J_USERNAME'], os.environ['NEO4J_PASSWORD']),
            liveness_check_timeout=0,
            max_connection_lifetime=2700,
            # keep_alive=False,
        )
        await neo4jdriver.verify_connectivity()
        cl.user_session.set("neo4jdriver", neo4jdriver)

@cl.on_message
async def on_message(message: cl.Message):
    # TTS cleanup
    last_tts_action = cl.user_session.get("tts_action")
    if last_tts_action is not None:
        await last_tts_action.remove()
    # process command
    processed_message = _process_command(message)

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
                "content": processed_message
            })
            previous_id = cl.user_session.get("previous_id")

            output_message = cl.Message(content="", actions=[tts_action])

            while True:
                response = await create_response(input_data, previous_id)
                previous_id, needs_continue, new_input = await process_stream(response, ctx, output_message)
                if not needs_continue:
                    break
                input_data = new_input

            # Commit the Neo4j transaction
            logger.warning("Committing the Neo4j transaction.")
            await tx.commit()
            
            await output_message.update()
            cl.user_session.set("last_message", output_message.content)
            cl.user_session.set("input_data", input_data)
            cl.user_session.set("previous_id", previous_id)

        except asyncio.CancelledError:
            logger.error("Rolling back the Neo4j transaction due to cancellation.")
            if tx is not None:
                await tx.cancel()
            else:
                logger.error("No Neo4j transaction to cancel.")
            raise
        except Exception as e:
            logger.error(f"Rolling back the Neo4j transaction. Error: {str(e)}")
            if tx is not None:
                await tx.rollback()
            else:
                logger.error("No Neo4j transaction to rollback.")
        finally:
            cl.user_session.set("tts_action", tts_action)
            if tx is not None:
                await tx.close()
            else:
                logger.error("No Neo4j transaction to close.")

@cl.password_auth_callback
def auth_callback(username: str, password: str) -> Optional[cl.User]:
    if (username, password) == ("Sic", "kadima"):
        return cl.User(identifier="Sic", metadata={"role": "admin", "provider": "credentials"})
    elif (username, password) == ("User", "oom.today"):
        return cl.User(identifier=username, metadata={"role": "user", "provider": "credentials"})
    else:
        return None

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
            mime="audio/mp3",
        )

        await cl.Message(content="👂 Listen...", elements=[output_audio_el]).send()

    await action.remove()

def _process_command(message: cl.Message) -> str:
    if message.command:
        if message.command in COMMAND_DATA:
            template = COMMAND_DATA[message.command]['template']
            return template + message.content
    return message.content
    