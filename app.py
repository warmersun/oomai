import os
import json
import chainlit as cl
from chainlit.logger import logger
from chainlit.input_widget import Switch
import asyncio
import re
from literalai.observability.filter import OrderBy
import yaml
from typing import Optional
from mdclense.parser import MarkdownParser
# drivers
from neo4j import AsyncGraphDatabase
from neo4j.time import Date, DateTime
from groq import AsyncGroq
from openai import AsyncOpenAI
from xai_sdk import AsyncClient
from xai_sdk.chat import user, system, assistant, tool_result
from xai_sdk.search import SearchParameters
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
    display_mermaid_diagram,
    display_convergence_canvas,
    visualize_oom,
    TOOLS_DEFINITIONS,
)
from chainlit_xai_util import process_stream
from utils import Neo4jDateEncoder

from config import OPENAI_API_KEY, GROQ_API_KEY, XAI_API_KEY, ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, BRAVE_SEARCH_API_KEY, NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD


with open("knowledge_graph/schema.md", "r") as f:
    schema = f.read()
with open("knowledge_graph/system_prompt_grok4.md", "r") as f:
    system_prompt_edit_template = f.read()
with open("knowledge_graph/system_prompt_grok4_readonly.md", "r") as f:
    system_prompt_readonly_template = f.read()
SYSTEM_PROMPT_EDIT = system_prompt_edit_template.format(schema=schema)
SYSTEM_PROMPT_READONLY = system_prompt_readonly_template.format(schema=schema)

with open("knowledge_graph/command_sources.yaml", "r") as f:
    config = yaml.safe_load(f)
COMMAND_DATA = config['commands']

# Create filtered command lists based on mode flags in YAML
commands_edit = [
    {
        "id": command_id,
        "icon": data['icon'],
        "description": data['description']
    }
    for command_id, data in COMMAND_DATA.items()
    if 'edit' in data.get('modes', [])
]

commands_readonly = [
    {
        "id": command_id,
        "icon": data['icon'],
        "description": data['description']
    }
    for command_id, data in COMMAND_DATA.items()
    if 'readonly' in data.get('modes', [])
]

# Define the tools (functions) - flattened structure for Responses API
TOOLS_EDIT = [
    TOOLS_DEFINITIONS["execute_cypher_query"],
    TOOLS_DEFINITIONS["create_node"],
    TOOLS_DEFINITIONS["create_edge"],
    TOOLS_DEFINITIONS["find_node"],
    TOOLS_DEFINITIONS["plan_tasks"],
    TOOLS_DEFINITIONS["get_tasks"],
    TOOLS_DEFINITIONS["mark_task_as_running"],
    TOOLS_DEFINITIONS["mark_task_as_done"],
    TOOLS_DEFINITIONS["display_mermaid_diagram"],
    TOOLS_DEFINITIONS["display_convergence_canvas"],
    TOOLS_DEFINITIONS["visualize_oom"],
]

TOOLS_READONLY = [
    TOOLS_DEFINITIONS["execute_cypher_query"],
    TOOLS_DEFINITIONS["find_node"],
    TOOLS_DEFINITIONS["plan_tasks"],
    TOOLS_DEFINITIONS["get_tasks"],
    TOOLS_DEFINITIONS["mark_task_as_running"],
    TOOLS_DEFINITIONS["mark_task_as_done"],
    TOOLS_DEFINITIONS["display_mermaid_diagram"],
    TOOLS_DEFINITIONS["display_convergence_canvas"],
    TOOLS_DEFINITIONS["visualize_oom"],
]

AVAILABLE_FUNCTIONS_EDIT = {
    "execute_cypher_query": execute_cypher_query,
    "create_node": create_node,
    "create_edge": create_edge,
    "find_node": find_node,
    "plan_tasks": plan_tasks,
    "get_tasks": get_tasks,
    "mark_task_as_running": mark_task_as_running,
    "mark_task_as_done": mark_task_as_done,
    "display_mermaid_diagram": display_mermaid_diagram,
    "display_convergence_canvas": display_convergence_canvas,
    "visualize_oom": visualize_oom,
}

AVAILABLE_FUNCTIONS_READONLY = {
    "execute_cypher_query": execute_cypher_query,
    "find_node": find_node,
    "plan_tasks": plan_tasks,
    "get_tasks": get_tasks,
    "mark_task_as_running": mark_task_as_running,
    "mark_task_as_done": mark_task_as_done,
    "display_mermaid_diagram": display_mermaid_diagram,
    "display_convergence_canvas": display_convergence_canvas,
    "visualize_oom": visualize_oom,
}

READ_ONLY_PROFILE = "Read-Only"
READ_EDIT_PROFILE = "Read/Edit"


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

async def _neo4j_connect():
    # disconnect if already connected
    await _neo4j_disconnect()
    # driver
    neo4jdriver = AsyncGraphDatabase.driver(
        NEO4J_URI,
        auth=(NEO4J_USERNAME, NEO4J_PASSWORD),
        liveness_check_timeout=0,
        max_connection_lifetime=30,
        max_connection_pool_size=5,
    )
    await neo4jdriver.verify_connectivity()
    cl.user_session.set("neo4jdriver", neo4jdriver)
    logger.info("Neo4j driver connected.")

async def _neo4j_disconnect():
    neo4jdriver = cl.user_session.get("neo4jdriver")
    if neo4jdriver is not None:
        await neo4jdriver.close()
        cl.user_session.set("neo4jdriver", None)
    logger.info("Neo4j driver disconnected.")
      
@cl.on_chat_start
async def start():    
    cl.user_session.set("user_and_assistant_messages", [])
    await _neo4j_connect()
    groq_client = AsyncGroq(
        api_key=GROQ_API_KEY,
    )
    cl.user_session.set("groq_client", groq_client)
    xai_client = AsyncClient(
        api_key=XAI_API_KEY,
        timeout=3600, # override default timeout with longer timeout for reasoning models
    )
    cl.user_session.set("xai_client", xai_client)
    openai_embedding_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    cl.user_session.set("openai_embedding_client", openai_embedding_client)
    elevenlabs_client= ElevenLabs(api_key=ELEVENLABS_API_KEY)
    cl.user_session.set("elevenlabs_client", elevenlabs_client)
    # locking
    message_lock = asyncio.Lock()
    cl.user_session.set("message_lock", message_lock)
    # settings
    settings = await cl.ChatSettings(
        [
            Switch(
                id="search",
                label="Search",
                initial_value=False,
                tooltip="Search on or off",
                description="Search on X, Web and News",
            ),
            Switch(
                id="debug",
                label="Debug",
                initial_value=False,
                tooltip="Debug on or off",
                description="See knowledge graph usage details",
            ),
        ]
    ).send()
    cl.user_session.set("search_settings", settings["search"])
    cl.user_session.set("debug_settings", settings["debug"])
    chat_profile = cl.user_session.get("chat_profile")
    if chat_profile == READ_EDIT_PROFILE:
        cl.user_session.set("system_messages", [system(SYSTEM_PROMPT_EDIT)])
        cl.user_session.set("tools", TOOLS_EDIT)
        cl.user_session.set("function_map", AVAILABLE_FUNCTIONS_EDIT)
        # only edit mode has commands
        await cl.context.emitter.set_commands(commands_edit)
    else:
        cl.user_session.set("system_messages", [system(SYSTEM_PROMPT_READONLY)])
        cl.user_session.set("tools", TOOLS_READONLY)
        cl.user_session.set("function_map", AVAILABLE_FUNCTIONS_READONLY)
        await cl.context.emitter.set_commands(commands_readonly)
    functions_with_ctx = ["create_node", "create_edge", "find_node", "execute_cypher_query"]
    cl.user_session.set("functions_with_ctx", functions_with_ctx)

@cl.on_settings_update
async def on_settings_update(settings):
    cl.user_session.set("search_settings", settings["search"])
    cl.user_session.set("debug_settings", settings["debug"])

@cl.on_chat_end
async def end_chat():
    await _neo4j_disconnect()

@cl.on_message
async def on_message(message: cl.Message):
    error_count = 0
    message_lock = cl.user_session.get("message_lock")
    assert message_lock is not None, "No message lock found in user session"
    async with message_lock:
        # TTS cleanup
        last_tts_action = cl.user_session.get("tts_action")
        if last_tts_action is not None:
            await last_tts_action.remove()
        # process command
        processed_message = _process_command(message)
    
        # get drivers from session
        neo4jdriver = cl.user_session.get("neo4jdriver")
        if neo4jdriver is None:
            logger.warning("Neo4j driver not found in user session. Reconnecting...")
            await _neo4j_connect()           
     
        tts_action = cl.Action(name="tts", payload={"value": "tts"}, icon="circle-play", tooltip="Read out loud" )
        
        # setup context: begin Neo4j transation and create lock
        lock = asyncio.Lock()
        ctx = GraphOpsCtx(neo4jdriver, lock)
        # setup outlook message
        output_message = cl.Message(content="", actions=[tts_action])
        diagram_message = cl.Message(content="")
        cl.user_session.set("diagram_message", diagram_message)

        cl.user_session.set("diagrams", [])
        cl.user_session.set("convergence_canvases", [])
        cl.user_session.set("oom_visualizers", [])

        async with cl.Step(name="the Knowledge Graph", type="tool", default_open=True) as step:
            success = await process_stream(message.content, ctx, output_message)
            step.output = success

        if success:
            # process visualizations
            # 1. Mermaid diagrams
            diagrams = cl.user_session.get("diagrams")
            assert diagrams is not None, "No diagrams found in user session"
            for diagram in diagrams:
                mermaid_diagram = cl.CustomElement(name="MermaidDiagram", props={"diagram": diagram}, display="inline")
                output_message.elements.append(mermaid_diagram)
            await output_message.update()
            # 2. Convergence Canvas
            convergence_canvases = cl.user_session.get("convergence_canvases")
            assert convergence_canvases is not None, "No convergence canvases found in user session"
            for convergence_canvas in convergence_canvases:
                convergence_canvas_element = cl.CustomElement(name="Pathway", props={"data": convergence_canvas}, display="inline")
                output_message.elements.append(convergence_canvas_element)
                await output_message.update()
            # 3. OOM Visualizer
            oom_visualizers = cl.user_session.get("oom_visualizers")
            assert oom_visualizers is not None, "No OOM Visualizers found in user session"
            for oom_visualizer in oom_visualizers:
                oom_visualizers_element = cl.CustomElement(name="OomVisualizer", props={"monthsPerDoubling": oom_visualizer}, display="inline")
                output_message.elements.append(oom_visualizers_element)
                await output_message.update()
        else:
            logger.error("Error in proccess_stream")
            await cl.Message(content="❌ Error while Processing LLM reposonse.", type="system_message").send()

        debug = cl.user_session.get("debug_settings")
        if not debug:
            await step.remove()


        cl.user_session.set("last_message", output_message.content)

    
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
    """
    Convert markdown text to clean plain text suitable for ElevenLabs TTS.
    
    This function uses mdclense to properly parse markdown and convert it to
    plain text while preserving the content structure and readability.
    """
    if not text or not text.strip():
        return ""
    
    try:
        # Use mdclense to convert markdown to plain text
        parser = MarkdownParser()
        plain_text = parser.parse(text)
        
        # Additional cleaning for TTS optimization
        # Remove excessive whitespace and normalize spacing
        plain_text = re.sub(r'\s+', ' ', plain_text)
        
        # Remove any remaining HTML tags that might have slipped through
        plain_text = re.sub(r'<[^>]+>', '', plain_text)
        
        # Clean up common markdown artifacts that might remain
        plain_text = re.sub(r'^\s*[-*+]\s+', '', plain_text, flags=re.MULTILINE)  # Remove list markers
        plain_text = re.sub(r'^\s*\d+\.\s+', '', plain_text, flags=re.MULTILINE)  # Remove numbered list markers
        
        # Remove excessive punctuation that might sound awkward in TTS
        plain_text = re.sub(r'[.]{3,}', '...', plain_text)  # Normalize ellipses
        plain_text = re.sub(r'[!]{2,}', '!', plain_text)    # Normalize exclamation marks
        plain_text = re.sub(r'[?]{2,}', '?', plain_text)    # Normalize question marks
        
        # Clean up any remaining markdown syntax
        plain_text = re.sub(r'#{1,6}\s*', '', plain_text)   # Remove heading markers
        plain_text = re.sub(r'^\s*[-=]+\s*$', '', plain_text, flags=re.MULTILINE)  # Remove horizontal rules
        
        # Final cleanup
        plain_text = plain_text.strip()
        
        return plain_text
        
    except Exception as e:
        # Fallback to regex-based cleaning if mdclense fails
        logger.warning(f"mdclense parsing failed, falling back to regex: {e}")
        
        # Original regex-based approach as fallback
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
        voice_id=ELEVENLABS_VOICE_ID,
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
            return template.format(user_input=message.content)
    return message.content
    