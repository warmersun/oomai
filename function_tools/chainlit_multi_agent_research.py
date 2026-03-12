import chainlit as cl

from .core_multi_agent_research import core_multi_agent_research


async def multi_agent_research(
    prompt: str,
    system_prompt: str | None = None,
    agent_count: int = 4,
) -> str:
    """Chainlit wrapper around core_multi_agent_research with a visual step."""
    async with cl.Step(name="Multi_Agent_Research", type="tool") as step:
        step.show_input = True
        step.input = {
            "prompt": prompt,
            "agent_count": agent_count,
        }

        step_message = cl.Message(content=f"🧠 Running multi-agent research: `{prompt}`")
        await step_message.send()

        xai_client = cl.user_session.get("xai_client")
        user_obj = cl.user_session.get("user")
        user_identifier = user_obj.identifier if user_obj else None

        output = await core_multi_agent_research(
            xai_client,
            prompt=prompt,
            user_identifier=user_identifier,
            system_prompt=system_prompt,
            agent_count=agent_count,
        )

        step.output = output
        debug = cl.user_session.get("debug_settings")
        if not debug:
            await step.remove()
        return output
