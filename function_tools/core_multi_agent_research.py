from typing import Optional
import logging

from xai_sdk import AsyncClient
from xai_sdk.chat import system, user
from xai_sdk.tools import web_search, x_search


MULTI_AGENT_MODEL = "grok-4.20-multi-agent-beta-0309"


async def core_multi_agent_research(
    xai_client: AsyncClient,
    prompt: str,
    user_identifier: Optional[str] = None,
    system_prompt: Optional[str] = None,
    agent_count: int = 4,
) -> str:
    """Run Grok multi-agent research with built-in web and X search tools."""
    if agent_count not in [4, 16]:
        raise ValueError("agent_count must be either 4 or 16")

    logging.info(
        "\n[MULTI_AGENT_RESEARCH]: %s\ninput parameters:\n  user_identifier=%s\n  agent_count=%s\n",
        prompt,
        user_identifier,
        agent_count,
    )

    chat = xai_client.chat.create(
        model=MULTI_AGENT_MODEL,
        agent_count=agent_count,
        tools=[
            web_search(enable_image_understanding=True),
            x_search(enable_image_understanding=True,
                     enable_video_understanding=True),
        ],
        messages=[
            system(system_prompt)
            if system_prompt else
            system("Research on X and the web, then return a detailed, cited summary."),
            user(prompt),
        ],
        user=user_identifier if user_identifier else None,
    )

    response = await chat.sample()
    logging.info("[MULTI_AGENT_RESEARCH_RESPONSE]:\n%s", response.content)
    logging.info("[USAGE]:\n%s", response.usage)
    logging.info("[SERVER_SIDE_TOOL_USAGE]:\n%s",
                 response.server_side_tool_usage)
    return response.content
