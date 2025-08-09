import chainlit as cl
import os
from neo4j import AsyncGraphDatabase, AsyncTransaction
from neo4j.exceptions import CypherSyntaxError, Neo4jError
from chainlit.logger import logger
import json
from openai import AsyncOpenAI
from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel
from neo4j.time import Date, DateTime
from function_tools import (
    execute_cypher_query,
    create_node,
    create_edge,
    find_node,
    GraphOpsCtx,
)
from agents import Agent, Runner
from openai.types.responses.response_text_delta_event import (
    ResponseTextDeltaEvent,
)
from groq import AsyncGroq


with open("knowledge_graph/schema.md", "r") as f:
    schema = f.read()
with open("knowledge_graph/system_prompt.md", "r") as f:
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
    async with neo4jdriver.session() as session:
        tx = await session.begin_transaction()
        ctx = GraphOpsCtx(tx)

        agent = Agent[GraphOpsCtx](
            name="oom.ai.gpt",
            instructions=system_prompt,
            tools=[
                execute_cypher_query,
                create_node,
                create_edge,
                find_node,
            ])

        message = cl.Message(content="")
        result = Runner.run_streamed(agent, message.content, ctx)
        async for event in result.stream_events():
            if event.type == "raw_response_event" and isinstance(event.data, ResponseTextDeltaEvent):
                await message.stream_token(event.data.delta)
        await message.update()
