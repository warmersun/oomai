from datetime import datetime, timedelta
from xai_sdk.chat import SearchParameters, system, user
from xai_sdk.search import x_source, web_source, rss_source
from xai_sdk import AsyncClient
from typing import Optional, List, Tuple
import logging

async def core_x_search(
    xai_client: AsyncClient, 
    prompt: str, 
    user_identifier: str = None,
    included_handles: Optional[List[str]] = None,
    rss_url: str = None,
    last_24hrs: Optional[bool] = False, 
    system_prompt:Optional[str] = None,
) -> Tuple[str, int, int, int]:
    """Search on X and return a detailed summary."""
    logging.info(f"""
[X_SEARCH]: {prompt}
input parameters:
  user_identifier={user_identifier}
  included_handles={included_handles}
  rss_url={rss_url}
  last_24hrs={last_24hrs}
  system_prompt={system_prompt}
"""
    )
    sources = [
        web_source(excluded_websites=["wikipedia.org", "gartner.com", "weforum.com", "forbes.com", "accenture.com"])
    ]

    if included_handles:
        sources.append(x_source(included_x_handles=included_handles))
    else:
        sources.append(x_source())

    if last_24hrs:
        now = datetime.now()
        from_date = now - timedelta(hours=24)
        to_date = now
        search_parameters = SearchParameters(
            mode="on",
            sources=sources,
            from_date=from_date,
            to_date=to_date,
            return_citations=False,
        )
    else:
        search_parameters = SearchParameters(
            mode="on",
            sources=sources,
            return_citations=False,
        )

    if rss_url:
        search_parameters.sources.append(rss_source([rss_url]))

    chat = xai_client.chat.create(
        model="grok-4-fast",
        search_parameters=search_parameters,
        messages=[
            system(system_prompt) if system_prompt else system("Search on X and return a detailed summary.") ,
            user(prompt),
        ],
        user=user_identifier if user_identifier else None,
    )

    response = await chat.sample()
    logging.info(f"[X_SEARCH_RESPONSE]:\n{response.content}")
    return response.content, response.usage.prompt_tokens, response.usage.completion_tokens, response.usage.num_sources_used    
