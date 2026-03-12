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
) -> str:
    """Run Grok multi-agent research (16-agent setup) with built-in web and X search tools."""

    logging.info(
        "\n[MULTI_AGENT_RESEARCH]: %s\ninput parameters:\n  user_identifier=%s\n  agent_count=16\n",
        prompt,
        user_identifier,
    )

    chat = xai_client.chat.create(
        model=MULTI_AGENT_MODEL,
        agent_count=16,
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
    logging.info(
        "[SERVER_SIDE_TOOL_USAGE]:\n%s",
        response.server_side_tool_usage,
    )
    return response.content
