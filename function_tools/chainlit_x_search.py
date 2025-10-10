import chainlit as cl
from .core_x_search import core_x_search
from typing import Optional, List
from chainlit_xai_util import count_usage

async def x_search(
	prompt: str, 
	included_handles: Optional[List[str]] = None, 
	rss_url: str = None,
	last_24hrs: Optional[bool] = False, 
	system_prompt:Optional[str] = None
	) -> str:
	"""Search on X and return a detailed summary."""
	xai_client = cl.user_session.get("xai_client")
	assert xai_client is not None, "No xAI client found in user session"
	
	async with cl.Step(name="Search X", type="tool") as step:
		step.show_input = True
		step.input = {"prompt": prompt, "included_handles": included_handles, "rss_url": rss_url, "last_24hrs": last_24hrs, "system_prompt": system_prompt}

		message = f"Searching on X with prompt: `{prompt}`"
		details = []
		if included_handles:
			details.append(f"including handles: {', '.join(included_handles)}")
		if rss_url:
			details.append(f"RSS feed: {rss_url}")
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
		output = await core_x_search(
			xai_client=xai_client,
			user_identifier=logged_in_user.identifier,
			prompt=prompt,
			included_handles=included_handles,
			rss_url=rss_url,
			last_24hrs=last_24hrs,
			system_prompt=system_prompt,
		)
		await count_usage(output[1], output[2], output[3])
		step.output = output[0]
		debug = cl.user_session.get("debug_settings")
		if not debug:
			await step.remove()
		return output[0]
		
