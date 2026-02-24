#!/usr/bin/env python3
"""
scraper.py — CLI version of batch.py

Accepts a source type, source parameters, and a processing instruction prompt
on the command line. Designed for cron job usage.

Examples:
    python scraper.py x --handles EMostaque elonmusk --prompt "Track AI developments..."
    python scraper.py youtube --channel-url "https://www.youtube.com/@allin" --prompt "Analyze..."
    python scraper.py x-video --handles SawyerMerritt --prompt "Track robotics videos..."
    python scraper.py web --url "https://news.smol.ai" --prompt "Retrieve latest AI news..."
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime

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

logger = logging.getLogger("kg_scraper")

with open("knowledge_graph/schema.md", "r") as f:
    schema = f.read()

with open("knowledge_graph/schema_population_guidance.md", "r") as f:
    schema_population_guidance = f.read()

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


def create_response(xai_client, prompt: str, model: str):
    with open("knowledge_graph/system_prompt_batch_grok4.md", "r") as f:
        system_prompt_template = f.read()
    system_prompt = system_prompt_template.format(schema=schema, schema_population_guidance=schema_population_guidance)

    chat = xai_client.chat.create(
        model=model,
        tools=TOOLS,
        tool_choice="auto",
    )
    chat.append(system(system_prompt))
    chat.append(user(prompt))
    return chat


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
                if function_name == "create_node":
                    function_args["groq_client"] = groq_client
                    function_args["openai_embedding_client"] = openai_embedding_client
                if function_name in ["find_node", "scan_ideas"]:
                    function_args["openai_embedding_client"] = openai_embedding_client
                if function_name == "x_search":
                    function_args["xai_client"] = xai_client
                    if is_video_source:
                        function_args["enable_video"] = True

                result = await AVAILABLE_FUNCTIONS[function_name](**function_args)
                result_str = json.dumps(result, cls=Neo4jDateEncoder)
                chat.append(tool_result(result_str))

            except Exception as e:
                logger.error(f"Error while processing tool call {function_name}: {str(e)}")
                error_count += 1
                if error_count >= 10:
                    raise e
                chat.append(tool_result(json.dumps({"error": str(e)})))


def build_prompt_for_x(args) -> tuple[str, bool]:
    """Build the final prompt for an X source."""
    handles_str = ", ".join(args.handles)
    suffix = f"\n\n[Source: X handles {handles_str}, last 24 hours]"
    return args.prompt + suffix, False


async def build_prompt_for_youtube(args) -> tuple[str, bool]:
    """Build the final prompt for a YouTube source."""
    logger.info(f"Fetching recent transcripts from {args.channel_url}")
    transcripts = await fetch_recent_transcripts(args.channel_url)
    if not transcripts:
        logger.info("No new episodes found — nothing to process.")
        return None, False
    transcript_text = ""
    for t in transcripts:
        transcript_text += f"\n\n--- Episode: {t['title']} ({t['url']}) ---\n{t['transcript']}"
    suffix = f"\n\n[Source: YouTube channel transcript]\n{transcript_text}"
    logger.info(f"Found {len(transcripts)} new episode(s)")
    return args.prompt + suffix, False


def build_prompt_for_x_video(args) -> tuple[str, bool]:
    """Build the final prompt for an X-Video source."""
    handles_str = ", ".join(args.handles)
    suffix = (
        f"\n\n[Source: X-Video from handles {handles_str}, last 24 hours]\n"
        f"IMPORTANT: This is a VIDEO source. Use x_search with the included_handles "
        f"parameter set to [{handles_str}] and last_24hrs=true to find the latest "
        f"video episode from this account. The x_search tool has video understanding "
        f"enabled for this source — it will watch and transcribe the video content. "
        f"Process the full video content into the knowledge graph as instructed above."
    )
    return args.prompt + suffix, True


def build_prompt_for_web(args) -> tuple[str, bool]:
    """Build the final prompt for a Web source."""
    url = args.url
    suffix = (
        f"\n\n[Source: Web site {url}, last 24 hours]\n"
        f"IMPORTANT: This is a WEB source. Use x_search to check {url} for new articles "
        f"or pages published in the last 24 hours. Do NOT restrict the search to any X handles. "
        f"Read the full content of any new items found and process them into the knowledge graph."
    )
    return args.prompt + suffix, False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scraper",
        description="CLI tool for scraping sources into the knowledge graph. "
                    "Use subcommands to specify the source type.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            '  python scraper.py x --handles EMostaque elonmusk --prompt "Track AI developments..."\n'
            '  python scraper.py youtube --channel-url "https://www.youtube.com/@allin" --prompt "Analyze..."\n'
            '  python scraper.py x-video --handles SawyerMerritt --prompt "Track robotics videos..."\n'
            '  python scraper.py web --url "https://news.smol.ai" --prompt "Retrieve latest AI news..."\n'
        ),
    )
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="Logging level (default: INFO)")
    parser.add_argument("--model", default="grok-4-1-fast",
                        help="Model to use (default: grok-4-1-fast)")

    subparsers = parser.add_subparsers(dest="source_type", required=True, help="Source type")

    # --- x ---
    x_parser = subparsers.add_parser("x", help="Scan X (Twitter) handles")
    x_parser.add_argument("--handles", nargs="+", required=True, help="X handles to scan")
    x_parser.add_argument("--prompt", required=True, help="Processing instruction prompt")
    x_parser.add_argument("--name", default=None, help="Name for this job (used in logs)")

    # --- youtube ---
    yt_parser = subparsers.add_parser("youtube", help="Fetch and process YouTube channel transcripts")
    yt_parser.add_argument("--channel-url", required=True, help="YouTube channel URL")
    yt_parser.add_argument("--prompt", required=True, help="Processing instruction prompt")
    yt_parser.add_argument("--name", default=None, help="Name for this job (used in logs)")

    # --- x-video ---
    xv_parser = subparsers.add_parser("x-video", help="Watch and process X videos")
    xv_parser.add_argument("--handles", nargs="+", required=True, help="X handles to scan for videos")
    xv_parser.add_argument("--prompt", required=True, help="Processing instruction prompt")
    xv_parser.add_argument("--name", default=None, help="Name for this job (used in logs)")

    # --- web ---
    web_parser = subparsers.add_parser("web", help="Scrape a website for new content")
    web_parser.add_argument("--url", required=True, help="Website URL to scrape")
    web_parser.add_argument("--prompt", required=True, help="Processing instruction prompt")
    web_parser.add_argument("--name", default=None, help="Name for this job (used in logs)")

    return parser


async def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(level=logging.WARNING)
    logger.setLevel(getattr(logging, args.log_level))

    # Generate a default name if not provided
    job_name = args.name or f"{args.source_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    logger.info(f"Starting scraper job: {job_name}")

    # Build the prompt based on source type
    if args.source_type == "x":
        prompt, is_video_source = build_prompt_for_x(args)
    elif args.source_type == "youtube":
        prompt, is_video_source = await build_prompt_for_youtube(args)
        if prompt is None:
            logger.info("No new content to process. Exiting.")
            return
    elif args.source_type == "x-video":
        prompt, is_video_source = build_prompt_for_x_video(args)
    elif args.source_type == "web":
        prompt, is_video_source = build_prompt_for_web(args)
    else:
        logger.error(f"Unknown source type: {args.source_type}")
        sys.exit(1)

    # Initialize clients
    neo4jdriver = AsyncGraphDatabase.driver(
        NEO4J_URI,
        auth=(NEO4J_USERNAME, NEO4J_PASSWORD),
        liveness_check_timeout=0,
        max_connection_lifetime=30,
        max_connection_pool_size=5,
    )
    await neo4jdriver.verify_connectivity()
    groq_client = AsyncGroq(api_key=GROQ_API_KEY)
    openai_embedding_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    xai_client = AsyncClient(api_key=XAI_API_KEY, timeout=3600)

    lock = asyncio.Lock()
    ctx = GraphOpsCtx(neo4jdriver, lock)

    try:
        logger.info("Processing content into the knowledge graph...")
        chat = create_response(xai_client, prompt, args.model)
        await process(chat, ctx, groq_client, openai_embedding_client, xai_client, is_video_source=is_video_source)
        logger.info(f"✅ Job '{job_name}' completed successfully.")
    except Exception as e:
        logger.error(f"❌ Job '{job_name}' failed: {str(e)}")
        sys.exit(1)
    finally:
        await neo4jdriver.close()


if __name__ == "__main__":
    asyncio.run(main())
