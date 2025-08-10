import chainlit as cl
from xai_sdk.chat import SearchParameters, system, user, tool, tool_result
from xai_sdk.search import x_source
from agents import function_tool


@function_tool
async def x_search(prompt: str) -> dict:
    """Search on X and return a detailed summary."""
    async with cl.Step(name="Search X", type="tool") as step:
        step.show_input = True
        step.input = {"prompt": prompt}
    
        xai_client = cl.user_session.get("xai_client")
        assert xai_client is not None, "No xAI client found in user session"
    
        chat = xai_client.chat.create(
            model="grok-3-mini",
            search_parameters=SearchParameters(
                mode="on",
                sources=[x_source()]
            ),
            messages=[
                system("Search on X and return a detailed summary."),
                user(prompt),
            ]
        )
    
        response = await chat.sample()
        step.output = response.content
        return response.content