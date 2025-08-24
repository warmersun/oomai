from datetime import datetime, timedelta
from xai_sdk.chat import SearchParameters, system, user
from xai_sdk.search import x_source, rss_source
from xai_sdk import AsyncClient
from typing import Optional, List  # <-- add List

async def core_x_search(
    xai_client: AsyncClient, 
    prompt: str, 
    included_handles: Optional[List[str]] = None,
    rss_url: Optional[str] = None,
    last_24hrs: Optional[bool] = False, 
    system_prompt:Optional[str] = None,
) -> str: 
    """Search on X and return a detailed summary."""

    if rss_url:
        src = rss_source([rss_url])
    else:
        src = x_source(included_x_handles=included_handles) if included_handles else x_source()

    chat = xai_client.chat.create(
        model="grok-3-mini",
        search_parameters=SearchParameters(
            mode="on",
            sources=[src],
            from_date=(datetime.now() - timedelta(days=1)) if last_24hrs else None,
        ),
        messages=[
            system(system_prompt) if system_prompt else system("Search on X and return a detailed summary.") ,
            user(prompt),
        ]
    )

    response = await chat.sample()
    return response.content
