import chainlit as cl
from .core_x_search import core_x_search
from typing import Optional, List  # <-- add List

async def x_search(prompt: str, included_handles: Optional[List[str]] = None, last_24hrs: Optional[bool] = False, system_prompt:Optional[str] = None) -> str:
  """Search on X and return a detailed summary."""
  xai_client = cl.user_session.get("xai_client")
  assert xai_client is not None, "No xAI client found in user session"
  
  async with cl.Step(name="Search X", type="tool") as step:
    step.show_input = True
    step.input = {"prompt": prompt, "included_handles": included_handles}
    xai_client = cl.user_session.get("xai_client")
    assert xai_client is not None, "No xAI client found in user session"
    output = await core_x_search(xai_client, prompt, included_handles, last_24hrs, system_prompt)
    step.output = output
    return output
    
