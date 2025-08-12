import chainlit as cl
import os
from xai_sdk import AsyncClient
from xai_sdk.chat import SearchParameters, system, user, tool, tool_result
from groq import AsyncGroq
from neo4j import AsyncGraphDatabase
from neo4j.exceptions import CypherSyntaxError
from chainlit.logger import logger
import json
from openai import AsyncOpenAI
from typing import Optional

from neo4j.time import Date, DateTime
from function_tools import (
    web_search_brave_tool,
    web_search_brave,
    execute_cypher_query,
    create_node,
    create_edge,
    find_node,
    GraphOpsCtx,
)
import asyncio
import re
from elevenlabs.types import VoiceSettings
from elevenlabs.client import ElevenLabs
from agents import RunContextWrapper


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

elevenlabs_client= ElevenLabs(api_key=os.environ['ELEVENLABS_API_KEY'])


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
}

# use in x.ai
# tool( name= find_node_tool["function"]["name"], description=find_node_tool["function"]["description"], parameters=find_node_tool["function"]["parameters"])

@cl.on_message
async def on_message(message: cl.Message):
    last_tts_action = cl.user_session.get("tts_action")
    if last_tts_action is not None:
        await last_tts_action.remove()

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
):
    """Execute the LLM chat loop with optional streaming."""

    xai_client = cl.user_session.get("xai_client")
    assert xai_client is not None, "No xAI client found in user session"

    tts_action = cl.Action(name="tts", payload={"value": "tts"}, icon="circle-play", tooltip="Read out loud" )
    msg: Optional[cl.Message] = cl.Message(content="", actions=[tts_action]) if stream else None

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
                lock = asyncio.Lock()
                ctx = GraphOpsCtx(tx, lock)
                tool_name = "unknown"
                try:
                    for tool_call in response.tool_calls:
                        tool_name = tool_call.function.name
                        tool_args = json.loads(tool_call.function.arguments)
                        try:
                            if tool_name == "cypher_query":
                                results = await execute_cypher_query(RunContextWrapper[GraphOpsCtx](ctx), tool_args["query"])
                                chat.append(tool_result(json.dumps(results, cls=Neo4jDateEncoder)))
                            elif tool_name == "create_node":
                                result = await create_node(RunContextWrapper[GraphOpsCtx](ctx), tool_args["node_type"], tool_args["name"], tool_args["description"])
                                chat.append(tool_result(json.dumps({"elementId": result})))
                            elif tool_name == "create_edge":
                                result = await create_edge(
                                    RunContextWrapper[GraphOpsCtx](ctx),
                                    tool_args["source_id"],
                                    tool_args["target_id"],
                                    tool_args["relationship_type"],
                                    tool_args.get("properties", {}),
                                )
                                chat.append(tool_result(json.dumps(result, cls=Neo4jDateEncoder)))
                            elif tool_name == "find_node":
                                results = await find_node(
                                    RunContextWrapper[GraphOpsCtx](ctx),
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
    logger.warning(f"Total tokens: {response.usage.total_tokens}")

    cl.user_session.set("last_message", response.content)
    cl.user_session.set("tts_action", tts_action)

async def run_chat_gpt_oss(message: cl.Message):
    groq_client = cl.user_session.get("groq_client")
    assert groq_client is not None, "No Groq client found in user session"

    tts_action = cl.Action(name="tts", payload={"value": "tts"}, icon="circle-play", tooltip="Read out loud" )

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
                lock = asyncio.Lock()
                ctx = GraphOpsCtx(tx, lock)
                tool_name = "unknown"
                try:
                    for tool_call in response_message.tool_calls:
                        tool_name = tool_call.function.name
                        tool_args = json.loads(tool_call.function.arguments)
                        try:
                            if tool_name == "cypher_query":
                                results = await execute_cypher_query(RunContextWrapper[GraphOpsCtx](ctx), tool_args["query"])
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "content": json.dumps(results, cls=Neo4jDateEncoder),
                                })
                            elif tool_name == "create_node":
                                result = await create_node(RunContextWrapper[GraphOpsCtx](ctx), tool_args["node_type"], tool_args["name"], tool_args["description"])
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "content": json.dumps({"elementId": result}),
                                })
                            elif tool_name == "create_edge":
                                logger.error(f"Creating edge: {tool_args}")
                                result = await create_edge(
                                    RunContextWrapper[GraphOpsCtx](ctx),
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
                                    RunContextWrapper[GraphOpsCtx](ctx),
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
            await cl.Message(content=content, actions=[tts_action]).send()
            if hasattr(response, "usage"):
                logger.warning(f"Total tokens: {response.usage.total_tokens}")
            break

    cl.user_session.set("last_message", content)
    cl.user_session.set("tts_action", tts_action)


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
    assert last_message is not None, "Last message must be set."
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

        
