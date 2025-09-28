import chainlit as cl
from .core_x_search import core_x_search
from typing import Optional, List

async def x_search(
	prompt: str, 
	included_handles: Optional[List[str]] = None, 
	last_24hrs: Optional[bool] = False, 
	system_prompt:Optional[str] = None
	) -> str:
	"""Search on X and return a detailed summary."""
	xai_client = cl.user_session.get("xai_client")
	assert xai_client is not None, "No xAI client found in user session"
	
	async with cl.Step(name="Search X", type="tool") as step:
		step.show_input = True
		step.input = {"prompt": prompt, "included_handles": included_handles, "last_24hrs": last_24hrs, "system_prompt": system_prompt}

		message = f"Searching on X with prompt: {prompt}"
		details = []
		if included_handles:
			details.append(f"including handles: {', '.join(included_handles)}")
		if last_24hrs:
			details.append("limited to the last 24 hours")
		if details:
			message += " (" + "; ".join(details) + ")"
		step_message = cl.Message(content=message)
		await step_message.send()

		xai_client = cl.user_session.get("xai_client")
		assert xai_client is not None, "No xAI client found in user session"
		logged_in_user = cl.user_session.get("user")
		assert logged_in_user is not None, "No user found in user session"
		output = await core_x_search(xai_client, logged_in_user.identifier, prompt, included_handles, last_24hrs, system_prompt)

		step.output = output
		debug = cl.user_session.get("debug_settings")
		if not debug:
			await step.remove()
		return output
		
