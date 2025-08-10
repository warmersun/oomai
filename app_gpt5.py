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
)
from agents import Agent, ModelSettings, Runner, TResponseInputItem, WebSearchTool
from openai.types.responses.response_text_delta_event import (
    ResponseTextDeltaEvent,
)
from groq import AsyncGroq
from openai.types.shared import Reasoning
from xai_sdk import AsyncClient


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
    xai_client = AsyncClient(
        api_key=os.getenv("XAI_API_KEY"),
        timeout=3600, # override default timeout with longer timeout for reasoning models
    )
    cl.user_session.set("xai_client", xai_client)
    agent = Agent[GraphOpsCtx](
        model="gpt-5",
        model_settings=ModelSettings(
            reasoning=Reasoning(
                effort="high",
            ),
            # extra_args={"verbosity":"low"}
            parallel_tool_calls=True,
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
        ])        
    cl.user_session.set("agent", agent)
    
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
    agent = cl.user_session.get("agent")
    assert agent is not None, "No agent found in user session"
    async with neo4jdriver.session() as session:
        tx = await session.begin_transaction()
        ctx = GraphOpsCtx(tx)
        try:

            last_result = cl.user_session.get("last_result")
    
            new_input: list[TResponseInputItem] = (  
                last_result.to_input_list() + [{"role": "user", "content": message.content}]  if last_result else [{"role": "user", "content": message.content}]  
            )
    
            result = Runner.run_streamed(starting_agent=agent, input=new_input, context=ctx, max_turns=500)
            output_message = cl.Message(content="")

            async for event in result.stream_events():
                if event.type == "raw_response_event":
                    if isinstance(event.data, ResponseTextDeltaEvent):
                        await output_message.stream_token(event.data.delta)
                elif event.type == "run_item_stream_event":
                    if event.name == "tool_called" and event.item.type == "tool_call_item":
                        if hasattr(event.item.raw_item, "type") and event.item.raw_item.type == "web_search_call":
                            logger.warn("Web search call detected.")
            await output_message.update()
            await tx.commit()
            cl.user_session.set("last_result", result)
        except Exception as e:
            logger.error(f"Rolling back the Neo4j transaction. Error: {str(e)}")
            await tx.cancel()
        finally:
            await tx.close()