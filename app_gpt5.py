import asyncio
import chainlit as cl
import os
from neo4j import AsyncGraphDatabase
from chainlit.logger import logger
from openai import AsyncOpenAI
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
from agents import Agent, ModelSettings, ReasoningItem, Runner, TResponseInputItem, WebSearchTool
from openai.types.responses.response_text_delta_event import (
    ResponseTextDeltaEvent,
)
from groq import AsyncGroq
from openai.types.shared import Reasoning
from xai_sdk import AsyncClient
from typing import Any
import re
from elevenlabs.types import VoiceSettings
from elevenlabs.client import ElevenLabs
from asyncio import Lock


with open("knowledge_graph/schema.md", "r") as f:
    schema = f.read()
with open("knowledge_graph/system_prompt_gpt5.md", "r") as f:
    system_prompt_template = f.read()
system_prompt = system_prompt_template.format(schema=schema)

embedding_model = "text-embedding-3-large"


@cl.on_chat_start
async def start_chat():
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
    agent = Agent[GraphOpsCtx](
        model="gpt-5",
        model_settings=ModelSettings(
            reasoning=Reasoning(
                effort="high",
            ),
            # extra_args={"verbosity":"low"}
            parallel_tool_calls=True, # parallel tool use does not work with Neo4j driver
        ),
        name="oom.ai.gpt",
        instructions=system_prompt,
        tools=[
            execute_cypher_query,
            create_node,
            create_edge,
            find_node,
            WebSearchTool(search_context_size="high"),
            x_search,
            plan_tasks,
            get_tasks,
            mark_task_as_running,
            mark_task_as_done,
        ])        
    cl.user_session.set("agent", agent)
    
@cl.on_chat_end
async def end_chat():
    neo4jdriver = cl.user_session.get("neo4jdriver")
    assert neo4jdriver is not None, "No Neo4j driver found in user session"
    await neo4jdriver.close()

@cl.on_message
async def on_message(message: cl.Message):
    last_tts_action = cl.user_session.get("tts_action")
    if last_tts_action is not None:
        await last_tts_action.remove()

    neo4jdriver = cl.user_session.get("neo4jdriver")
    assert neo4jdriver is not None, "No Neo4j driver found in user session"
    openai_client = cl.user_session.get("openai_client")
    assert openai_client is not None, "No OpenAI client found in user session"
    agent = cl.user_session.get("agent")
    assert agent is not None, "No agent found in user session"
    async with neo4jdriver.session() as session:
        tts_action = cl.Action(name="tts", payload={"value": "tts"}, icon="circle-play", tooltip="Read out loud" )
        tx = await session.begin_transaction()
        lock = asyncio.Lock()
        ctx = GraphOpsCtx(tx, lock)          
        try:

            last_result = cl.user_session.get("last_result")
    
            new_input: list[TResponseInputItem] = (  
                last_result.to_input_list() + [{"role": "user", "content": message.content}]  if last_result else [{"role": "user", "content": message.content}]  
            )

            output_message = cl.Message(content="", actions=[tts_action])
            result = Runner.run_streamed(starting_agent=agent, input=new_input, context=ctx, max_turns=500)

            async for event in result.stream_events():
                if isinstance(event, ReasoningItem):
                    reasoning_item: Any = event
                    await cl.Message(content=f"🤔 {reasoning_item.summary[0].text}").send()
                elif event.type == "raw_response_event" and isinstance(event.data, ResponseTextDeltaEvent):
                    await output_message.stream_token(event.data.delta)
                elif event.type == "run_item_stream_event":
                    if event.name == "tool_called" and event.item.type == "tool_call_item":
                        if hasattr(event.item.raw_item, "type") and event.item.raw_item.type == "web_search_call":
                            logger.warning(f"Web search call: {event.item.raw_item}")
            await output_message.update()
            await tx.commit()
            cl.user_session.set("last_result", result)
            cl.user_session.set("last_message", result.final_output)
        except Exception as e:
            logger.error(f"Rolling back the Neo4j transaction. Error: {str(e)}")
            await tx.cancel()
        finally:
            cl.user_session.set("tts_action", tts_action)
            await tx.close()

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


