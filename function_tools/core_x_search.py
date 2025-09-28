from datetime import datetime, timedelta
from xai_sdk.chat import SearchParameters, system, user
from xai_sdk.search import x_source, web_source
from xai_sdk import AsyncClient
from typing import Optional, List
from chainlit_xai_util import count_usage

async def core_x_search(
    xai_client: AsyncClient, 
    prompt: str, 
    included_handles: Optional[List[str]] = None,
    last_24hrs: Optional[bool] = False, 
    system_prompt:Optional[str] = None,
) -> str:
    """Search on X and return a detailed summary."""

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
        )
    else:
        search_parameters = SearchParameters(
            mode="on",
            sources=sources,
        )
    chat = xai_client.chat.create(
        model="grok-4-fast",
        search_parameters=search_parameters,
        messages=[
            system(system_prompt) if system_prompt else system("Search on X and return a detailed summary.") ,
            user(prompt),
        ]
    )

    response = await chat.sample()
    await count_usage(response.usage.prompt_tokens, response.usage.completion_tokens, response.usage.num_sources_used)
    return response.content
