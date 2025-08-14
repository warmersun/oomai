import chainlit as cl
from xai_sdk.chat import SearchParameters, system, user, tool, tool_result
from xai_sdk.search import x_source
from typing import Optional, List  # <-- add List

async def x_search(prompt: str, included_handles: Optional[List[str]] = None) -> str: 
    """Search on X and return a detailed summary."""
    async with cl.Step(name="Search X", type="tool") as step:
        step.show_input = True
        step.input = {"prompt": prompt, "included_handles": included_handles}

        xai_client = cl.user_session.get("xai_client")
        assert xai_client is not None, "No xAI client found in user session"

        src = x_source(included_x_handles=included_handles) if included_handles else x_source()

        chat = xai_client.chat.create(
            model="grok-3-mini",
            search_parameters=SearchParameters(
                mode="on",
                sources=[src]
            ),
            messages=[
                system("Search on X and return a detailed summary."),
                user(prompt),
            ]
        )

        response = await chat.sample()
        step.output = response.content

        # be defensive if these attrs might be absent:
        citations = getattr(response, "citations", None)
        num_sources_used = getattr(response, "num_sources_used", None)

        return response.content
        