import chainlit as cl
import json
import os
from typing import Any, Dict, List

from neo4j import AsyncGraphDatabase
from chainlit.logger import logger
from openai import AsyncOpenAI
from groq import AsyncGroq
from xai_sdk import AsyncClient

from function_tools import (
    execute_cypher_query,
    create_node,
    create_edge,
    find_node,
    GraphOpsCtx,
    x_search,
)
from function_tools.graph_ops import KVPair

with open("knowledge_graph/schema.md", "r") as f:
    schema = f.read()
with open("knowledge_graph/system_prompt.md", "r") as f:
    system_prompt_template = f.read()
system_prompt = system_prompt_template.format(schema=schema)


# ---------------------------------------------------------------------------
# Tool specifications for the Responses API
# ---------------------------------------------------------------------------
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "execute_cypher_query",
            "description": "Execute a Cypher query against the Neo4j database and return the results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The Cypher query to execute.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_node",
            "description": "Create a node in the knowledge graph.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_type": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["node_type", "name", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_edge",
            "description": "Create an edge between two nodes in the knowledge graph.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_id": {"type": "string"},
                    "target_id": {"type": "string"},
                    "relationship_type": {"type": "string"},
                    "properties": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "key": {"type": "string"},
                                "value": {
                                    "type": ["string", "number", "boolean"],
                                },
                            },
                            "required": ["key", "value"],
                        },
                    },
                },
                "required": ["source_id", "target_id", "relationship_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_node",
            "description": "Find nodes in the knowledge graph similar to a given query text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query_text": {"type": "string"},
                    "node_type": {
                        "type": "string",
                        "enum": [
                            "Convergence",
                            "Capability",
                            "Milestone",
                            "Trend",
                            "Idea",
                            "LTC",
                            "LAC",
                        ],
                    },
                    "top_k": {"type": "integer", "default": 5},
                },
                "required": ["query_text", "node_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "x_search",
            "description": "Search on X and return a detailed summary.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "included_handles": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["prompt"],
            },
        },
    },
]


class _Wrapper:
    """Minimal context wrapper to satisfy existing tool signatures."""

    def __init__(self, ctx: GraphOpsCtx):
        self.context = ctx


async def _call_tool(ctx: GraphOpsCtx, name: str, arguments: Dict[str, Any]):
    wrapper = _Wrapper(ctx)
    if name == "execute_cypher_query":
        return await execute_cypher_query(wrapper, **arguments)
    if name == "create_node":
        return await create_node(wrapper, **arguments)
    if name == "create_edge":
        props = arguments.get("properties")
        if props is not None:
            arguments["properties"] = [KVPair(**p) for p in props]
        return await create_edge(wrapper, **arguments)
    if name == "find_node":
        return await find_node(wrapper, **arguments)
    if name == "x_search":
        return await x_search(**arguments)
    raise ValueError(f"Unknown tool: {name}")


@cl.on_chat_start
async def start_chat():
    neo4jdriver = AsyncGraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
    )
    await neo4jdriver.verify_connectivity()
    cl.user_session.set("neo4jdriver", neo4jdriver)

    groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))
    cl.user_session.set("groq_client", groq_client)

    openai_client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    cl.user_session.set("openai_client", openai_client)

    xai_client = AsyncClient(
        api_key=os.getenv("XAI_API_KEY"),
        timeout=3600,
    )
    cl.user_session.set("xai_client", xai_client)

    # conversation history
    cl.user_session.set("history", [])


@cl.on_chat_end
async def end_chat():
    neo4jdriver = cl.user_session.get("neo4jdriver")
    assert neo4jdriver is not None, "No Neo4j driver found in user session"
    await neo4jdriver.close()


@cl.on_message
async def on_message(message: cl.Message):
    neo4jdriver = cl.user_session.get("neo4jdriver")
    assert neo4jdriver is not None, "No Neo4j driver found in user session"
    openai_client = cl.user_session.get("openai_client")
    assert openai_client is not None, "No OpenAI client found in user session"

    history: List[Dict[str, Any]] = cl.user_session.get("history") or []
    history.append({"role": "user", "content": message.content})

    async with neo4jdriver.session() as session:
        tx = await session.begin_transaction()
        ctx = GraphOpsCtx(tx)
        try:
            output_message = cl.Message(content="")
            while True:
                async with openai_client.responses.stream(
                    model="gpt-5",
                    instructions=system_prompt,
                    input=history,
                    tools=TOOL_DEFINITIONS,
                    parallel_tool_calls=True,
                    reasoning={"effort": "high"},
                ) as stream:
                    async for event in stream:
                        if event.type == "response.output_text.delta":
                            await output_message.stream_token(event.delta)
                    final_response = await stream.get_final_response()

                if final_response.output_text:
                    history.append({
                        "role": "assistant",
                        "content": final_response.output_text,
                    })

                # No tool calls -> done
                tool_calls = getattr(final_response, "tool_calls", []) or []
                if not tool_calls:
                    break

                for call in tool_calls:
                    name = call["name"] if isinstance(call, dict) else call.name
                    arguments_json = call.get("arguments") if isinstance(call, dict) else call.function.arguments
                    arguments = json.loads(arguments_json) if isinstance(arguments_json, str) else arguments_json
                    result = await _call_tool(ctx, name, arguments)
                    history.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id") if isinstance(call, dict) else call.id,
                            "name": name,
                            "content": json.dumps(result),
                        }
                    )
            await output_message.update()
            await tx.commit()
            cl.user_session.set("history", history)
        except Exception as e:
            logger.error(f"Rolling back the Neo4j transaction. Error: {str(e)}")
            await tx.cancel()
        finally:
            await tx.close()
