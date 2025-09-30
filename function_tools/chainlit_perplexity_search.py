import chainlit as cl
from .core_perplexity_search import core_perplexity_search
from typing import List
import json

async def perplexity_search(queries: List[str], max_results: int = 5) -> str:
    """Search using Perplexity and return a detailed summary."""
    
    async with cl.Step(name="Search Perplexity", type="tool") as step:
        step.show_input = True
        step.input = {"queries": queries, "max_results": max_results}

        message = f"Searching with Perplexity for {len(queries)} queries"
        if len(queries) == 1:
            message += f": `{queries[0]}`"
        else:
            message += f": {', '.join([f'`{q}`' for q in queries[:3]])}"
            if len(queries) > 3:
                message += f" and {len(queries) - 3} more"
        step_message = cl.Message(content=message)
        await step_message.send()

        results = await core_perplexity_search(queries, max_results)
        
        step.output = results
        
        debug = cl.user_session.get("debug_settings")
        if not debug:
            await step.remove()
        return results

