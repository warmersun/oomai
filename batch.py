import asyncio
import json
import logging
import yaml
# drivers
from neo4j import AsyncGraphDatabase
from openai import AsyncOpenAI
from groq import AsyncGroq
from xai_sdk import AsyncClient
from xai_sdk.chat import user, system, assistant, tool_result
# tools
from function_tools import (
    core_execute_cypher_query,
    core_create_node,
    core_create_edge,
    core_find_node,
    core_scan_ideas,
    core_dfs,
    core_x_search,
    core_perplexity_search,
    fetch_recent_transcripts,
    GraphOpsCtx,
    TOOLS_DEFINITIONS,
)
from config import OPENAI_API_KEY, GROQ_API_KEY, XAI_API_KEY, NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD
from utils import Neo4jDateEncoder


logging.basicConfig(level=logging.WARNING)

logger = logging.getLogger('kg_batch')
logger.setLevel(logging.INFO)

with open("knowledge_graph/schema.md", "r") as f:
    schema = f.read()

with open("knowledge_graph/schema_population_guidance.md", "r") as f:
    schema_population_guidance = f.read()

embedding_model = "text-embedding-3-large"

LAST_RUN_FILE = "last_run_timestamp.txt"

TOOLS = [
    TOOLS_DEFINITIONS["execute_cypher_query"],
    TOOLS_DEFINITIONS["create_node"],
    TOOLS_DEFINITIONS["create_edge"],
    TOOLS_DEFINITIONS["find_node"],
    TOOLS_DEFINITIONS["scan_ideas"],
    TOOLS_DEFINITIONS["dfs"],
    TOOLS_DEFINITIONS["x_search"],
    TOOLS_DEFINITIONS["perplexity_search"],
]

AVAILABLE_FUNCTIONS = {
    "execute_cypher_query": core_execute_cypher_query,
    "create_node": core_create_node,
    "create_edge": core_create_edge,
    "find_node": core_find_node,
    "scan_ideas": core_scan_ideas,
    "dfs": core_dfs,
    "x_search": core_x_search,
    "perplexity_search": core_perplexity_search,
}

# Function to create the response, streaming
def create_response(xai_client, prompt: str):
    with open("knowledge_graph/system_prompt_batch_grok4.md", "r") as f:
        system_prompt_template = f.read()
    system_prompt = system_prompt_template.format(schema=schema, schema_population_guidance=schema_population_guidance)

    chat = xai_client.chat.create(
        model="grok-4-1-fast",
        tools=TOOLS,
        tool_choice="auto"
    )
    # Add system message
    chat.append(system(system_prompt))
    chat.append(user(prompt))
    return chat

# Function to process the chat - no streaming needed
async def process(chat, ctx: GraphOpsCtx, groq_client, openai_embedding_client, xai_client, is_video_source=False):
    error_count = 0
    counter = 0

    while counter < 100:
        counter += 1
        logger.debug(f"Counter: {counter}")
        response = await chat.sample()
        logger.info("Response received.")

        if not hasattr(response, "tool_calls") or not response.tool_calls:
            assert response.finish_reason == "REASON_STOP", "Expected finish reason to be REASON_STOP"
            logger.info("No tool calls, done.")
            logger.info(f"Response:\n{response.content}")
            return

        assert response.finish_reason == "REASON_TOOL_CALLS", f"Expected finish reason to be REASON_TOOL_CALLS, got {response.finish_reason}"
        chat.append(response)

        logger.info(f"Going to process tool calls: {len(response.tool_calls)}")
        for tool_call in response.tool_calls:
            try:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)
                if function_name in ["create_node", "create_edge", "find_node", "scan_ideas", "dfs", "execute_cypher_query"]:
                    function_args = {"ctx": ctx, **function_args}
                # create nodes needs extra args, to have the groq and openai clients
                if function_name == "create_node":
                    function_args["groq_client"] = groq_client
                    function_args["openai_embedding_client"] = openai_embedding_client
                # find nodes and scan_ideas need extra args, to have the openai client
                if function_name in ["find_node", "scan_ideas"]:
                    function_args["openai_embedding_client"] = openai_embedding_client
                # x_search needs extra args, to have the xai client
                if function_name == "x_search":
                    function_args["xai_client"] = xai_client
                    if is_video_source:
                        function_args["enable_video"] = True

                result = await AVAILABLE_FUNCTIONS[function_name](**function_args)

                # Convert result to JSON string for tool_result
                result_str = json.dumps(result, cls=Neo4jDateEncoder)
                chat.append(tool_result(result_str))

            except Exception as e:
                logger.error(f"Error while processing tool call {function_name}: {str(e)}")
                error_count += 1
                if error_count >= 10:
                    raise e
                # Add error result
                chat.append(tool_result(json.dumps({"error": str(e)})))
                # Do not break here; allow other tool calls in the same turn to proceed
                # break

async def main() -> None:
    neo4jdriver = AsyncGraphDatabase.driver(
        NEO4J_URI,
        auth=(NEO4J_USERNAME, NEO4J_PASSWORD),
        liveness_check_timeout=0,
        max_connection_lifetime=30,
        max_connection_pool_size=5,
    )
    await neo4jdriver.verify_connectivity()
    groq_client = AsyncGroq(
        api_key=GROQ_API_KEY,
    )
    openai_embedding_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    xai_client = AsyncClient(
        api_key=XAI_API_KEY,
        timeout=3600
    )

    with open("knowledge_graph/batch_sources.yaml", "r") as f:
        config = yaml.safe_load(f)

    for source in config.get("sources", []):
        prompt = source.get("prompt", "Do nothing, just say 'No insttuctions given!'")

        logger.info(f"\n\nProcessing {source.get('name')}")

        # Append source info to the prompt based on source type
        source_type = source.get("source_type")
        is_video_source = False

        if source_type == "X" and "handles" in source:
            handles_str = ", ".join(source.get("handles", []))
            prompt += f"\n\n[Source: X handles {handles_str}, last 24 hours]"

        elif source_type == "YouTube" and "channel_url" in source:
            logger.info(f"Fetching recent transcripts from {source['channel_url']}")
            transcripts = await fetch_recent_transcripts(source["channel_url"])
            if not transcripts:
                logger.info(f"No new episodes found for {source.get('name')} — skipping.")
                continue
            transcript_text = ""
            for t in transcripts:
                transcript_text += f"\n\n--- Episode: {t['title']} ({t['url']}) ---\n{t['transcript']}"
            prompt += f"\n\n[Source: YouTube channel transcript]\n{transcript_text}"
            logger.info(f"Found {len(transcripts)} new episode(s) for {source.get('name')}")

        elif source_type == "X-Video" and "handles" in source:
            is_video_source = True
            handles_str = ", ".join(source.get("handles", []))
            prompt += (
                f"\n\n[Source: X-Video from handles {handles_str}, last 24 hours]\n"
                f"IMPORTANT: This is a VIDEO source. Use x_search with the included_handles "
                f"parameter set to [{handles_str}] and last_24hrs=true to find the latest "
                f"video episode from this account. The x_search tool has video understanding "
                f"enabled for this source — it will watch and transcribe the video content. "
                f"Process the full video content into the knowledge graph as instructed above."
            )

        elif source_type == "Web" and "url" in source:
            url = source.get("url")
            prompt += (
                f"\n\n[Source: Web site {url}, last 24 hours]\n"
                f"IMPORTANT: This is a WEB source. Use x_search to check {url} for new articles "
                f"or pages published in the last 24 hours. Do NOT restrict the search to any X handles. "
                f"Read the full content of any new items found and process them into the knowledge graph."
            )

        else:
            logger.error(f"Unknown source type: {source_type} or missing required parameters")
            continue

        lock = asyncio.Lock()
        ctx = GraphOpsCtx(neo4jdriver, lock)

        try:
            logger.info("Now processing content from sources into the knowledge graph using Grok-4-fast with built-in search.")
            chat = create_response(xai_client, prompt)
            await process(chat, ctx, groq_client, openai_embedding_client, xai_client, is_video_source=is_video_source)
            logger.info(f"✅ Processed {source.get('name')} successfully.")
        except Exception as e:
            logger.error(f"❌ Error while processing {source.get('name')}: {str(e)}")

    await neo4jdriver.close()
    logger.info("\n\nBatch processing completed.")

if __name__ == "__main__":
    asyncio.run(main())