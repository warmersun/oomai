import os
import json
import chainlit as cl
from chainlit.logger import logger
from chainlit.input_widget import Switch
import asyncio
import re
from chainlit.types import ThreadDict
from literalai.observability.filter import OrderBy
import yaml
from typing import Optional, Dict
from mdclense.parser import MarkdownParser
# drivers
from neo4j import AsyncGraphDatabase
from neo4j.time import Date, DateTime
from groq import AsyncGroq
from openai import AsyncOpenAI
from xai_sdk import AsyncClient
from xai_sdk.chat import user, system, assistant, tool_result
from elevenlabs.client import ElevenLabs
from elevenlabs.types import VoiceSettings
# function tools
from function_tools import (
    execute_cypher_query,
    create_node,
    create_edge,
    find_node,
    scan_ideas,
    scan_trends,
    dfs,
    GraphOpsCtx,
    plan_tasks,
    get_tasks,
    mark_task_as_running,
    mark_task_as_done,
    mark_all_tasks_as_done,
    display_mermaid_diagram,
    display_convergence_canvas,
    visualize_oom,
    TOOLS_DEFINITIONS,
    x_search,
)
from chainlit_xai_util import generate_response
from utils import Neo4jDateEncoder
from config import OPENAI_API_KEY, GROQ_API_KEY, XAI_API_KEY, ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, USER_PARTY_NAME

with open("knowledge_graph/schema.md", "r") as f:
    schema = f.read()
with open("knowledge_graph/schema_population_guidance.md", "r") as f:
    schema_population_guidance = f.read()
with open("knowledge_graph/system_prompt_grok4.md", "r") as f:
    system_prompt_edit_template = f.read()
with open("knowledge_graph/system_prompt_grok4_readonly.md", "r") as f:
    system_prompt_readonly_template = f.read()
SYSTEM_PROMPT_EDIT = system_prompt_edit_template.format(schema=schema, schema_population_guidance=schema_population_guidance, user_party_name=USER_PARTY_NAME)
SYSTEM_PROMPT_READONLY = system_prompt_readonly_template.format(schema=schema, user_party_name=USER_PARTY_NAME)
with open("knowledge_graph/system_prompt_readonly_step1.md", "r") as f:
    SYSTEM_PROMPT_READONLY_STEP1 = f.read().format(schema=schema, user_party_name=USER_PARTY_NAME)
with open("knowledge_graph/system_prompt_readonly_step2.md", "r") as f:
    SYSTEM_PROMPT_READONLY_STEP2 = f.read().format(schema=schema, user_party_name=USER_PARTY_NAME)

with open("knowledge_graph/command_sources.yaml", "r") as f:
    config = yaml.safe_load(f)
COMMAND_DATA = config['commands']

# Create filtered command lists based on mode flags in YAML
commands_edit = [{
    "id": command_id,
    "icon": data['icon'],
    "description": data['description']
} for command_id, data in COMMAND_DATA.items()
                 if 'edit' in data.get('modes', [])]

commands_readonly = [{
    "id": command_id,
    "icon": data['icon'],
    "description": data['description']
} for command_id, data in COMMAND_DATA.items()
                     if 'readonly' in data.get('modes', [])]



# Define the tools (functions) - flattened structure for Responses API
TOOLS_EDIT = [
    TOOLS_DEFINITIONS["execute_cypher_query"],
    TOOLS_DEFINITIONS["create_node"],
    TOOLS_DEFINITIONS["create_edge"],
    TOOLS_DEFINITIONS["find_node"],
    TOOLS_DEFINITIONS["scan_ideas"],
    TOOLS_DEFINITIONS["scan_trends"],
    TOOLS_DEFINITIONS["dfs"],
    TOOLS_DEFINITIONS["plan_tasks"],
    TOOLS_DEFINITIONS["get_tasks"],
    TOOLS_DEFINITIONS["mark_task_as_running"],
    TOOLS_DEFINITIONS["mark_task_as_done"],
    TOOLS_DEFINITIONS["display_mermaid_diagram"],
    TOOLS_DEFINITIONS["display_convergence_canvas"],
    TOOLS_DEFINITIONS["visualize_oom"],
    TOOLS_DEFINITIONS["x_search"],
]

TOOLS_READONLY = [
    TOOLS_DEFINITIONS["execute_cypher_query"],
    TOOLS_DEFINITIONS["find_node"],
    TOOLS_DEFINITIONS["scan_ideas"],
    TOOLS_DEFINITIONS["scan_trends"],
    TOOLS_DEFINITIONS["dfs"],
    TOOLS_DEFINITIONS["plan_tasks"],
    TOOLS_DEFINITIONS["get_tasks"],
    TOOLS_DEFINITIONS["mark_task_as_running"],
    TOOLS_DEFINITIONS["mark_task_as_done"],
    TOOLS_DEFINITIONS["display_mermaid_diagram"],
    TOOLS_DEFINITIONS["display_convergence_canvas"],
    TOOLS_DEFINITIONS["visualize_oom"],
    TOOLS_DEFINITIONS["x_search"],
]



AVAILABLE_FUNCTIONS_EDIT = {
    "execute_cypher_query": execute_cypher_query,
    "create_node": create_node,
    "create_edge": create_edge,
    "find_node": find_node,
    "scan_ideas": scan_ideas,
    "scan_trends": scan_trends,
    "dfs": dfs,
    "plan_tasks": plan_tasks,
    "get_tasks": get_tasks,
    "mark_task_as_running": mark_task_as_running,
    "mark_task_as_done": mark_task_as_done,
    "display_mermaid_diagram": display_mermaid_diagram,
    "display_convergence_canvas": display_convergence_canvas,
    "visualize_oom": visualize_oom,
    "x_search": x_search,
}

AVAILABLE_FUNCTIONS_READONLY = {
    "execute_cypher_query": execute_cypher_query,
    "find_node": find_node,
    "scan_ideas": scan_ideas,
    "scan_trends": scan_trends,
    "dfs": dfs,
    "plan_tasks": plan_tasks,
    "get_tasks": get_tasks,
    "mark_task_as_running": mark_task_as_running,
    "mark_task_as_done": mark_task_as_done,
    "display_mermaid_diagram": display_mermaid_diagram,
    "display_convergence_canvas": display_convergence_canvas,
    "visualize_oom": visualize_oom,
    "x_search": x_search,
}

TOOLS_VISUALIZATION = [
    TOOLS_DEFINITIONS["display_mermaid_diagram"],
    TOOLS_DEFINITIONS["display_convergence_canvas"],
    TOOLS_DEFINITIONS["visualize_oom"],
    TOOLS_DEFINITIONS["x_search"],
]

AVAILABLE_FUNCTIONS_VISUALIZATION = {
    "display_mermaid_diagram": display_mermaid_diagram,
    "display_convergence_canvas": display_convergence_canvas,
    "visualize_oom": visualize_oom,
    "x_search": x_search,
}



READ_ONLY_PROFILE = "Read-Only"
READ_EDIT_PROFILE = "Read/Edit"


@cl.set_chat_profiles
async def set_chat_profile(current_user: cl.User):
    profiles = [
        cl.ChatProfile(
            name=READ_ONLY_PROFILE,
            markdown_description="Query the knowledge graph in read-only mode.",
        ),
        cl.ChatProfile(
            name=READ_EDIT_PROFILE,
            markdown_description="Query and update the knowledge graph.",
        )
    ]
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
    groq_client = AsyncGroq(api_key=GROQ_API_KEY, )
    cl.user_session.set("groq_client", groq_client)
    xai_client = AsyncClient(
        api_key=XAI_API_KEY,
        timeout=
        3600,  # override default timeout with longer timeout for reasoning models
    )
    cl.user_session.set("xai_client", xai_client)
    openai_embedding_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    cl.user_session.set("openai_embedding_client", openai_embedding_client)
    elevenlabs_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
    cl.user_session.set("elevenlabs_client", elevenlabs_client)
    # locking
    message_lock = asyncio.Lock()
    cl.user_session.set("message_lock", message_lock)
    # settings
    settings = await cl.ChatSettings([
        Switch(
            id="debug",
            label="Debug",
            initial=True,
            tooltip="Debug on or off",
            description="See knowledge graph, web and X search.",
        ),
    ]).send()
    cl.user_session.set("debug_settings", settings["debug"])
    chat_profile = cl.user_session.get("chat_profile")
    if chat_profile == READ_EDIT_PROFILE:
        cl.user_session.set("system_messages", [system(SYSTEM_PROMPT_EDIT)])
        cl.user_session.set("tools", TOOLS_EDIT)
        cl.user_session.set("function_map", AVAILABLE_FUNCTIONS_EDIT)
        # only edit mode has commands
        await cl.context.emitter.set_commands(commands_edit)
    else:
        cl.user_session.set("system_messages",
                            [system(SYSTEM_PROMPT_READONLY)])
        cl.user_session.set("tools", TOOLS_READONLY)
        cl.user_session.set("function_map", AVAILABLE_FUNCTIONS_READONLY)
        await cl.context.emitter.set_commands(commands_readonly)
    functions_with_ctx = [
        "create_node", "create_edge", "find_node", "scan_ideas", "scan_trends", "dfs",
        "execute_cypher_query"
    ]
    cl.user_session.set("functions_with_ctx", functions_with_ctx)


@cl.on_settings_update
async def on_settings_update(settings):
    cl.user_session.set("debug_settings", settings["debug"])


@cl.on_chat_end
async def end_chat():
    await _neo4j_disconnect()


@cl.on_message
async def on_message(message: cl.Message):
    # usage logic removed

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
            logger.warning(
                "Neo4j driver not found in user session. Reconnecting...")
            await _neo4j_connect()
            neo4jdriver = cl.user_session.get("neo4jdriver")

        tts_action = cl.Action(name="tts",
                               payload={"value": "tts"},
                               icon="circle-play",
                               tooltip="Read out loud")

        # setup context: begin Neo4j transation and create lock
        lock = asyncio.Lock()
        ctx = GraphOpsCtx(neo4jdriver, lock)
        # predefined answers
        output_message = cl.Message(content="💭🤔💭",
                                    actions=[tts_action])

        diagram_message = cl.Message(content="")
        cl.user_session.set("diagram_message", diagram_message)

        cl.user_session.set("diagrams", [])
        cl.user_session.set("convergence_canvases", [])
        cl.user_session.set("oom_visualizers", [])

        # Helper to get session vars
        def get_session_vars(mode="readonly"):
            xai_client = cl.user_session.get("xai_client")
            functions_with_ctx = cl.user_session.get("functions_with_ctx")
            if mode == "readonly":
                tools = TOOLS_READONLY
                function_map = AVAILABLE_FUNCTIONS_READONLY
            elif mode == "visualization":
                tools = TOOLS_VISUALIZATION
                function_map = AVAILABLE_FUNCTIONS_VISUALIZATION
            else: # edit
                tools = TOOLS_EDIT
                function_map = AVAILABLE_FUNCTIONS_EDIT
            return xai_client, tools, function_map, functions_with_ctx

        async with cl.Step(name="the Knowledge Graph",
                           type="tool",
                           default_open=True) as step:
            # Check if we are in Read-Only mode for the two-step process
            chat_profile = cl.user_session.get("chat_profile")
            
            # Common session vars
            user_and_assistant_messages = cl.user_session.get("user_and_assistant_messages")
            # Append user input to main history
            user_and_assistant_messages.append(user(processed_message))

            if chat_profile == READ_ONLY_PROFILE:
                # STEP 1: Research & Blueprinting
                xai_client, tools, function_map, functions_with_ctx = get_session_vars("readonly")
                
                # Construct messages for Step 1
                step1_messages = [system(SYSTEM_PROMPT_READONLY_STEP1)] + user_and_assistant_messages
                
                # Run step 1
                step1_response = await generate_response(
                    xai_client, tools, function_map, functions_with_ctx, ctx, step1_messages
                )
                await mark_all_tasks_as_done()
                
                if step1_response:
                    # Append Step 1 response to main history
                    user_and_assistant_messages.append(assistant(step1_response))
                    cl.user_session.set("user_and_assistant_messages", user_and_assistant_messages)

                    # display the enriched prompt
                    elements = [
                        cl.Text(name="prompt", content=f"```\n{step1_response}\n```", display="page")
                    ]
                    await cl.Message(content="Enriched prompt", elements=elements).send()
                    
                    # The content of blueprint_message is now the PROMPT for Step 2
                    step2_prompt = step1_response
                    
                    # STEP 2: Visualization / Inference
                    xai_client, tools, function_map, functions_with_ctx = get_session_vars("visualization")
                    
                    # Show a task for Step 2 so the user knows what's happening
                    step2_task_title = "Synthesizing response from enriched context and questions"
                    task_list = cl.user_session.get('task_list')
                    if task_list is None:
                        task_list = cl.TaskList()
                        cl.user_session.set('task_list', task_list)
                    step2_task = cl.Task(title=step2_task_title, status=cl.TaskStatus.RUNNING)
                    await task_list.add_task(step2_task)
                    tasks_dict = cl.user_session.get('tasks', {})
                    tasks_dict[step2_task_title] = step2_task
                    cl.user_session.set('tasks', tasks_dict)
                    await task_list.send()

                    # Retrieve Step 2 specific history
                    step2_messages = cl.user_session.get("step2_messages")
                    if step2_messages is None:
                        step2_messages = []
                    
                    # Append input (Enriched Prompt) to Step 2 history
                    step2_messages.append(user(step2_prompt))

                    # Construct messages for Step 2
                    step2_input_messages = [system(SYSTEM_PROMPT_READONLY_STEP2)] + step2_messages

                    # We pass the step2_prompt as the input to the second step
                    # But we want the final output to be in 'output_message'
                    await output_message.send()
                    
                    step2_response = await generate_response(
                        xai_client, tools, function_map, functions_with_ctx, ctx, step2_input_messages
                    )

                    # Mark step 2 task as done
                    step2_task.status = cl.TaskStatus.DONE
                    await task_list.send()

                    if step2_response:
                        # Append Step 2 response to Step 2 history
                        step2_messages.append(assistant(step2_response))
                        cl.user_session.set("step2_messages", step2_messages)
                        
                        # Also append to main history so it's consistent
                        user_and_assistant_messages.append(assistant(step2_response))
                        cl.user_session.set("user_and_assistant_messages", user_and_assistant_messages)

                        output_message.content = step2_response
                        await output_message.update()
                        success = True
                    else:
                        success = False
                else:
                     await cl.Message(content="❌ Error during research step.", type="system_message").send()
                     success = False
            
            else:
                # Normal Edit Mode (Single Step)
                xai_client, tools, function_map, functions_with_ctx = get_session_vars("edit")
                
                # Construct messages
                edit_messages = [system(SYSTEM_PROMPT_EDIT)] + user_and_assistant_messages

                await output_message.send()
                response_content = await generate_response(
                    xai_client, tools, function_map, functions_with_ctx, ctx, edit_messages
                )
                await mark_all_tasks_as_done()
                
                if response_content:
                    # Append to history
                    user_and_assistant_messages.append(assistant(response_content))
                    cl.user_session.set("user_and_assistant_messages", user_and_assistant_messages)
                    
                    output_message.content = response_content
                    await output_message.update()
                    success = True
                else:
                    success = False

        if success:
            # process visualizations
            # 1. Mermaid diagrams
            diagrams = cl.user_session.get("diagrams")
            assert diagrams is not None, "No diagrams found in user session"
            for diagram in diagrams:
                mermaid_diagram = cl.CustomElement(name="MermaidDiagram",
                                                   props={"diagram": diagram},
                                                   display="inline")
                output_message.elements.append(mermaid_diagram)
            await output_message.update()
            # 2. Convergence Canvas
            convergence_canvases = cl.user_session.get("convergence_canvases")
            assert convergence_canvases is not None, "No convergence canvases found in user session"
            for convergence_canvas in convergence_canvases:
                convergence_canvas_element = cl.CustomElement(
                    name="Pathway",
                    props={"data": convergence_canvas},
                    display="inline")
                output_message.elements.append(convergence_canvas_element)
                await output_message.update()
            # 3. OOM Visualizer
            oom_visualizers = cl.user_session.get("oom_visualizers")
            assert oom_visualizers is not None, "No OOM Visualizers found in user session"
            for oom_visualizer in oom_visualizers:
                oom_visualizers_element = cl.CustomElement(
                    name="OomVisualizer",
                    props={"monthsPerDoubling": oom_visualizer},
                    display="inline")
                output_message.elements.append(oom_visualizers_element)
                await output_message.update()
        else:
            logger.error("Error in generate_response")
            await cl.Message(content="❌ Error while Processing LLM reposonse.",
                             type="system_message").send()
            await _neo4j_connect()

        debug = cl.user_session.get("debug_settings")
        if not debug:
            await step.remove()

        cl.user_session.set("last_message", output_message.content)


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
        plain_text = re.sub(r'^\s*[-*+]\s+',
                            '',
                            plain_text,
                            flags=re.MULTILINE)  # Remove list markers
        plain_text = re.sub(r'^\s*\d+\.\s+',
                            '',
                            plain_text,
                            flags=re.MULTILINE)  # Remove numbered list markers

        # Remove excessive punctuation that might sound awkward in TTS
        plain_text = re.sub(r'[.]{3,}', '...',
                            plain_text)  # Normalize ellipses
        plain_text = re.sub(r'[!]{2,}', '!',
                            plain_text)  # Normalize exclamation marks
        plain_text = re.sub(r'[?]{2,}', '?',
                            plain_text)  # Normalize question marks

        # Clean up any remaining markdown syntax
        plain_text = re.sub(r'#{1,6}\s*', '',
                            plain_text)  # Remove heading markers
        plain_text = re.sub(r'^\s*[-=]+\s*$',
                            '',
                            plain_text,
                            flags=re.MULTILINE)  # Remove horizontal rules

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
    audio_generator = elevenlabs_client.text_to_speech.convert(
        model_id="eleven_flash_v2_5",
        text=text,
        voice_id=ELEVENLABS_VOICE_ID,
        output_format="mp3_44100_128",
        voice_settings=VoiceSettings(stability=0.4,
                                     similarity_boost=0.75,
                                     use_speaker_boost=True,
                                     speed=1.0))
    audio = b"".join(audio_generator)
    return audio


# async def text_to_speech(text: str):
#     groq_client = cl.user_session.get("groq_client")
#     assert groq_client is not None, "No Groq client found in user session"
#     text = clean_text_for_tts(text)

#     model = "playai-tts"
#     voice = "Cheyenne-PlayAI"
#     response_format = "mp3"
#     sample_rate = 44100

#     response = await groq_client.audio.speech.create(
#         model=model,
#         voice=voice,
#         input=text,
#         response_format=response_format,
#         sample_rate = sample_rate
#     )

#     audio_bytes = await response.read()
#     return audio_bytes


@cl.action_callback("tts")
async def tts(action: cl.Action):
    # usage logic removed

    last_message = cl.user_session.get("last_message")
    if last_message is not None:
        if not isinstance(last_message, str):
            last_message = getattr(last_message, "response", str(last_message))
        audio_bytes = text_to_speech(last_message)

        output_audio_el = cl.Audio(
            auto_play=True,
            content=audio_bytes,
            mime="audio/mp3",
        )

        await cl.Message(content="👂 Listen...",
                         elements=[output_audio_el]).send()

    await action.remove()


def _process_command(message: cl.Message) -> str:
    if message.command:
        if message.command in COMMAND_DATA:
            template = COMMAND_DATA[message.command]['template']
            return template.format(user_input=message.content)
    return message.content


# Callbacks for persistence


@cl.on_shared_thread_view
async def shared_thread_view(thread, viewer):
    # Allow anonymous access to shared threads
    return True


@cl.on_chat_resume
async def on_chat_resume(thread: ThreadDict):
    thread_messages = []

    try:
        # Debug: Log thread structure for troubleshooting
        logger.info(f"Thread keys: {list(thread.keys())}")

        # Try different possible structures for accessing messages
        messages = thread.get("messages", thread.get("steps", []))
        logger.info(f"Found {len(messages)} messages in thread")

        for message in messages:
            # Skip messages with parentId (they're likely step details, not main messages)
            if message.get("parentId") is not None:
                continue

            message_type = message.get("type", "")
            message_content = message.get("output", message.get("content", ""))

            # Skip empty messages
            if not message_content:
                continue

            if message_type == "user_message":
                thread_messages.append(user(message_content))
            elif message_type == "assistant_message":
                thread_messages.append(assistant(message_content))
            elif message_type == "tool_call":
                # Handle tool calls - reconstruct them for xai_sdk
                # Tool calls might need special handling depending on xai_sdk format
                logger.info(f"Found tool call: {message_content}")
                # For now, treat as assistant message to preserve context
                thread_messages.append(
                    assistant(f"[Tool call: {message_content}]"))
            elif message_type == "tool_result":
                # Handle tool results
                logger.info(f"Found tool result: {message_content}")
                # For now, treat as assistant message to preserve context
                thread_messages.append(
                    assistant(f"[Tool result: {message_content}]"))
            else:
                # For any other message type, treat as assistant message
                logger.info(
                    f"Found message type '{message_type}': {message_content[:100]}..."
                )
                thread_messages.append(assistant(message_content))

    except Exception as e:
        logger.error(f"Error processing thread messages: {e}")
        logger.error(
            f"Thread structure: {json.dumps(thread, indent=2, default=str)}")
        # Fallback to empty message list
        thread_messages = []

    logger.info(f"Processed {len(thread_messages)} messages for chat resume")
    cl.user_session.set("user_and_assistant_messages", thread_messages)
    await _neo4j_connect()
    groq_client = AsyncGroq(api_key=GROQ_API_KEY, )
    cl.user_session.set("groq_client", groq_client)
    xai_client = AsyncClient(
        api_key=XAI_API_KEY,
        timeout=
        3600,  # override default timeout with longer timeout for reasoning models
    )
    cl.user_session.set("xai_client", xai_client)
    openai_embedding_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    cl.user_session.set("openai_embedding_client", openai_embedding_client)
    elevenlabs_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
    cl.user_session.set("elevenlabs_client", elevenlabs_client)
    # locking
    message_lock = asyncio.Lock()
    cl.user_session.set("message_lock", message_lock)
    # settings
    settings = await cl.ChatSettings([
        Switch(
            id="debug",
            label="Debug",
            initial=True,
            tooltip="Debug on or off",
            description="See knowledge graph, web and X search.",
        ),
    ]).send()
    cl.user_session.set("debug_settings", settings["debug"])
    chat_profile = cl.user_session.get("chat_profile")
    if chat_profile == READ_EDIT_PROFILE:
        cl.user_session.set("system_messages", [system(SYSTEM_PROMPT_EDIT)])
        cl.user_session.set("tools", TOOLS_EDIT)
        cl.user_session.set("function_map", AVAILABLE_FUNCTIONS_EDIT)
        # only edit mode has commands
        await cl.context.emitter.set_commands(commands_edit)
    else:
        cl.user_session.set("system_messages",
                            [system(SYSTEM_PROMPT_READONLY)])
        cl.user_session.set("tools", TOOLS_READONLY)
        cl.user_session.set("function_map", AVAILABLE_FUNCTIONS_READONLY)
        await cl.context.emitter.set_commands(commands_readonly)
    functions_with_ctx = [
        "create_node", "create_edge", "find_node", "scan_ideas", "scan_trends", "dfs",
        "execute_cypher_query"
    ]
    cl.user_session.set("functions_with_ctx", functions_with_ctx)
    cl.user_session.set("task_list", None)
    cl.user_session.set("tasks", {})


# Auth


