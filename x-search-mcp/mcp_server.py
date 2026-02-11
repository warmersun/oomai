"""
X Search MCP Server

Provides agentic search on X (Twitter) and web via xAI's Grok API.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import List, Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from xai_sdk import AsyncClient
from xai_sdk.chat import system, user
from xai_sdk.tools import web_search, x_search

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialize MCP server
mcp = FastMCP(
    "X Search MCP Server",
    dependencies=["xai-sdk"],
)

# Global client - initialized on first use
_xai_client: Optional[AsyncClient] = None


def get_xai_client() -> AsyncClient:
    """Get or create xAI client."""
    global _xai_client
    if _xai_client is None:
        api_key = os.environ.get("XAI_API_KEY")
        if not api_key:
            raise ValueError("XAI_API_KEY environment variable is required")
        _xai_client = AsyncClient(api_key=api_key)
    return _xai_client


@mcp.tool()
async def search_x(
    query: str,
    included_handles: Optional[List[str]] = None,
    last_24hrs: bool = False,
    system_prompt: Optional[str] = None,
) -> str:
    """
    Search X (Twitter) and the web using xAI's Grok model.
    
    Performs an agentic search that can understand context, analyze images,
    and synthesize information from X posts and web pages.
    
    Args:
        query: The search query or question to research
        included_handles: Optional list of X handles to focus on (e.g., ["@elonmusk", "@OpenAI"])
        last_24hrs: If True, only search posts from the last 24 hours
        system_prompt: Optional custom system prompt for the search agent
    
    Returns:
        A detailed summary of the search results
    """
    logging.info(f"""
[X_SEARCH]: {query}
input parameters:
  included_handles={included_handles}
  last_24hrs={last_24hrs}
  system_prompt={system_prompt}
""")
    
    client = get_xai_client()
    
    # Configure tools
    tools = [
        web_search(
            excluded_domains=["wikipedia.org", "gartner.com", "weforum.com", "forbes.com", "accenture.com"],
            enable_image_understanding=True
        ),
    ]
    
    x_search_params = {
        'enable_image_understanding': True,
        'enable_video_understanding': False
    }
    
    if last_24hrs:
        now = datetime.now()
        from_date = now - timedelta(hours=24)
        x_search_params['from_date'] = from_date
        x_search_params['to_date'] = now
        
    if included_handles:
        x_search_params['allowed_x_handles'] = included_handles
    
    logging.info(f"x_search parameters: {x_search_params}")
    tools.append(x_search(**x_search_params))
    
    # Create chat and get response
    chat = client.chat.create(
        model="grok-4-1-fast",
        reasoning_effort="high",
        tools=tools,
        messages=[
            system(system_prompt) if system_prompt else system("Search on X and return a detailed summary."),
            user(query),
        ],
    )
    
    response = await chat.sample()
    logging.info(f"[X_SEARCH_RESPONSE]:\n{response.content}")
    logging.info(f"[USAGE]:\n{response.usage}")
    
    return response.content


if __name__ == "__main__":
    mcp.run()
