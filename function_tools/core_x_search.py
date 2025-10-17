from datetime import datetime, timedelta
from xai_sdk.chat import system, user
from xai_sdk.tools import web_search, x_search
from xai_sdk import AsyncClient
from typing import Optional, List, Tuple
import logging

async def core_x_search(
    xai_client: AsyncClient, 
    prompt: str, 
    user_identifier: str = None,
    included_handles: Optional[List[str]] = None,
    last_24hrs: Optional[bool] = False, 
    system_prompt:Optional[str] = None,
) -> Tuple[str, int, int, int]:
    """Agentic search on X and web."""
    logging.info(f"""
[X_SEARCH]: {prompt}
input parameters:
  user_identifier={user_identifier}
  included_handles={included_handles}
  last_24hrs={last_24hrs}
  system_prompt={system_prompt}
"""
    )
    tools = [
        web_search(excluded_domains=["wikipedia.org", "gartner.com", "weforum.com", "forbes.com", "accenture.com"], enable_image_understanding=True), 
    ]
    x_search_params = {'enable_image_understanding': True, 'enable_video_understanding': False}

    if last_24hrs:
        now = datetime.now()
        from_date = now - timedelta(hours=24)
        to_date = now
        x_search_params['from_date'] = from_date
        x_search_params['to_date'] = to_date
    if included_handles:
        x_search_params['allowed_x_handles'] = included_handles

    logging.info(f"x_search parameters: {x_search_params}")

    tools.append(x_search(**x_search_params))

    chat = xai_client.chat.create(
        model="grok-4-fast",
        tools=tools,
        messages=[
            system(system_prompt) if system_prompt else system("Search on X and return a detailed summary.") ,
            user(prompt),
        ],
        user=user_identifier if user_identifier else None,
    )

    response = await chat.sample()
    logging.info(f"[X_SEARCH_RESPONSE]:\n{response.content}")
    return response.content, response.usage.prompt_tokens, response.usage.completion_tokens, response.usage.num_sources_used    
