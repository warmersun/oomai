import chainlit as cl
from .core_x_search import core_x_search
from typing import Optional, List


async def x_search(
    prompt: str,
    included_handles: Optional[List[str]] = None,
    last_24hrs: Optional[bool] = False,
    system_prompt: Optional[str] = None,
    enable_video: Optional[bool] = False,
) -> str:
    """Chainlit wrapper around core_x_search that shows a Step in the UI."""
    async with cl.Step(name="X_Search", type="tool") as step:
        step.show_input = True
        step.input = {
            "prompt": prompt,
            "included_handles": included_handles,
            "last_24hrs": last_24hrs,
            "enable_video": enable_video,
        }

        step_message = cl.Message(
            content=f"🔍 Searching X and web: `{prompt}`"
        )
        await step_message.send()

        xai_client = cl.user_session.get("xai_client")
        user_obj = cl.user_session.get("user")
        user_identifier = user_obj.identifier if user_obj else None

        output = await core_x_search(
            xai_client,
            prompt=prompt,
            user_identifier=user_identifier,
            included_handles=included_handles,
            last_24hrs=last_24hrs,
            system_prompt=system_prompt,
            enable_video=enable_video,
        )

        step.output = output
        debug = cl.user_session.get("debug_settings")
        if not debug:
            await step.remove()
        return output
