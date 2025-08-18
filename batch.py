import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import yaml
from collections import namedtuple
from lark import Lark, ParseError
# drivers
from neo4j import AsyncGraphDatabase
from openai import AsyncOpenAI
from groq import AsyncGroq
from xai_sdk import AsyncClient
from xai_sdk.chat import SearchParameters, system, user, tool, tool_result
from xai_sdk.search import rss_source, web_source, x_source
from neo4j.time import Date, DateTime
# tools
from function_tools import (
    core_execute_cypher_query,
    core_create_node,
    core_create_edge,
    core_find_node,
    GraphOpsCtx,
    core_x_search,
    TOOLS_DEFINITIONS,
)


logging.basicConfig(level=logging.WARNING)

logger = logging.getLogger('kg_batch')
logger.setLevel(logging.INFO)

class Neo4jDateEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (Date, DateTime)):
            return o.iso_format()  # Convert Neo4j Date/DateTime to ISO 8601 string
        return super().default(o)

with open("knowledge_graph/schema.md", "r") as f:
    schema = f.read()

embedding_model = "text-embedding-3-large"
llm_model = "grok-4"

LAST_RUN_FILE = "last_run_timestamp.txt"

TOOLS = [
    TOOLS_DEFINITIONS["execute_cypher_query"],
    TOOLS_DEFINITIONS["create_node"],
    TOOLS_DEFINITIONS["create_edge"],
    TOOLS_DEFINITIONS["find_node"],
    {"type": "web_search_preview", "search_context_size":"high"},
]

AVAILABLE_FUNCTIONS = {
    "execute_cypher_query": core_execute_cypher_query,
    "create_node": core_create_node,
    "create_edge": core_create_edge,
    "find_node": core_find_node,
}

class Neo4jDateEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (Date, DateTime)):
            return o.iso_format()  # Convert Neo4j Date/DateTime to ISO 8601 string
        return super().default(o)       

# Function to create the response, streaming
async def create_response(openai_client, input_data, previous_response_id=None):
    with open("knowledge_graph/system_prompt_batch_gpt5.md", "r") as f:
        system_prompt = f.read()

    kwargs = {
        "model": "gpt-5",
        "instructions": system_prompt,
        "input": input_data,
        "tools": TOOLS,
        "stream": True,
        "reasoning": {"effort": "high"},
        "safety_identifier": "kg_batch",
    }
    if previous_response_id:
        kwargs["previous_response_id"] = previous_response_id
    return await openai_client.responses.create(**kwargs)

# Function to process the streaming response
async def process_stream(response, ctx: GraphOpsCtx, groq_client, openai_client):
    tool_calls = []
    content = ""
    reasoning = ""
    response_id = None
    current_tool = None
    output_message = ""
    
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
            output_message += event.delta
        elif event.type == "response.reasoning_summary.delta":
            reasoning += event.delta
            output_message += "\nReasoning: " + event.delta
        elif event.type == "response.web_search_call.searching":
            logger.info("Searching the web...")
        elif event.type == "response.web_search_call.completed":
            pass
        elif event.type == "response.done":
            pass  # Can check finish_reason here if needed
    if tool_calls:
        new_input = []
        for tool_call in tool_calls:
            if tool_call["type"] == "custom_tool":
                # custom tool call
                if tool_call["name"] == "execute_cypher_query":
                    function_response = await core_execute_cypher_query(ctx, tool_call["input"])
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
                    # create nodes needs extra args, to have the groq and openai clients
                    if function_name == "create_node":
                        function_args["groq_client"] = groq_client
                        function_args["openai_client"] = openai_client
                    # find nodes needs extra args, to have the openai client
                    if function_name == "find_node":
                        function_args["openai_client"] = openai_client
                except json.JSONDecodeError:
                    function_args = {}
                if function_name in AVAILABLE_FUNCTIONS:
                    try:
                        function_response = await AVAILABLE_FUNCTIONS[function_name](**function_args)
                        new_input.append({
                            "type": "function_call_output",
                            "call_id": tool_call["id"],
                            "output":  json.dumps(function_response, cls=Neo4jDateEncoder),
                        })
                    except Exception as e:
                        logger.error(f"Error calling function {function_name}: {str(e)}")
                        new_input.append({
                            "type": "function_call_output",
                            "call_id": tool_call["id"],
                            "output":  json.dumps({"error": str(e)}),
                        })
                        raise e
                        
            logger.info(f"[OUTPUT MESSAGE] {output_message}")
        return response_id, True, new_input
    else:
        if reasoning:
            output_message += "\nFull Reasoning Summary: " + reasoning
        logger.info(f"[OUTPUT MESSAGE] {output_message}")
        return response_id, False, None

async def main() -> None:
    neo4jdriver = AsyncGraphDatabase.driver(
        os.environ['NEO4J_URI'],
        auth=(os.environ['NEO4J_USERNAME'], os.environ['NEO4J_PASSWORD']),
        liveness_check_timeout=0,
        max_connection_lifetime=2700,
        # keep_alive=False,
    )
    await neo4jdriver.verify_connectivity()
    groq_client = AsyncGroq(
        api_key=os.getenv("GROQ_API_KEY"),
    )
    openai_client = AsyncOpenAI(api_key=os.environ['OPENAI_API_KEY'])
    xai_client = AsyncClient(
        api_key=os.getenv("XAI_API_KEY"),
        timeout=3600
    )

    with open("knowledge_graph/batch_sources.yaml", "r") as f:
        config = yaml.safe_load(f)

    with open("knowledge_graph/schema.md", "r") as f:
        schema = f.read()
    
    with open("knowledge_graph/system_prompt_batch_extract_grok3.md", "r") as f:
        system_prompt_batch_extract_grok3 = f.read().format(schema=schema)

    for source in config.get("sources", []):
        prompt = source.get("prompt", "Do nothing, just say 'No insttuctions given!'")
        
        logger.info(f"Processing {source.get('name')}")

        extract_for_kg = None
        if source.get("source_type") == "RSS" and "url" in source:
            extract_for_kg = await core_x_search(
                xai_client=xai_client, 
                prompt=prompt, 
                rss_url=source.get("url"),
                last_24hrs=True,
                system_prompt=system_prompt_batch_extract_grok3)
        elif source.get("source_type") == "X" and "handles" in source:
            extract_for_kg = await core_x_search(
                xai_client=xai_client, 
                prompt=prompt, 
                included_handles=source.get("handles", []),
                last_24hrs=True,
                system_prompt=system_prompt_batch_extract_grok3)
        else:
            logger.error(f"Unknown source type: {source.get('source_type')} or missing required parameters")
        assert extract_for_kg is not None, "Failed to extract for KG"
        logger.info(f"Processed {source.get('name')}:\n{extract_for_kg}")

        logger.info("Now processing the extracted content into the knowledge graph.")

        # create Neo4j session
        async with neo4jdriver.session() as session:
            # setup context: begin Neo5j transation and create lock
            lock = asyncio.Lock()
            previous_id = None
            input_data = [
                {
                    "role": "user",
                    "content": extract_for_kg
                }
            ]
            while True:
                tx = await session.begin_transaction()
                ctx = GraphOpsCtx(tx, lock)
                try:
                    response = await create_response(openai_client, input_data, previous_id)
                    previous_id, needs_continue, new_input = await process_stream(response, ctx, groq_client, openai_client)
                    if not needs_continue:
                        break
                    input_data = new_input
    
                    # Commit the Neo4j transaction
                    logger.warning("✅ Committing the Neo4j transaction.")
                    await tx.commit()
                except asyncio.CancelledError:
                    logger.error("❌ Rolling back the Neo4j transaction due to cancellation.")
                    if tx is not None:
                        await tx.cancel()
                    else:
                        logger.error("No Neo4j transaction to cancel.")

                except Exception as e:
                    logger.error(f"❌ Rolling back the Neo4j transaction. Error: {str(e)}")
                    if tx is not None:
                        await tx.rollback()
                    else:
                        logger.error("No Neo4j transaction to rollback.")
                finally:
                    if tx is not None:
                        await tx.close()
                    else:
                        logger.error("No Neo4j transaction to close.")
    
    await neo4jdriver.close()


if __name__ == "__main__":
    asyncio.run(main())