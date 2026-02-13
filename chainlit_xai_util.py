import json
import chainlit as cl
from chainlit.logger import logger
from xai_sdk.chat import tool_result, user, assistant, tool
# Note: web_search removed - all searches go through x_search tool (core_x_search)
from typing import Any, Optional, List, Dict, Callable
import asyncio


async def generate_response(
    xai_client: Any,
    tools: List[Any],
    function_map: Dict[str, Callable],
    functions_with_ctx: List[str],
    ctx: Any,
    messages: List[Any]
) -> Optional[str]:
    """
    Generates a response from the LLM, handling tool calls.
    Returns the final response content as a string, or None if there was an error.
    
    Args:
        xai_client: The initialized XAI client.
        tools: List of tool definitions.
        function_map: Dictionary mapping function names to implementations.
        functions_with_ctx: List of function names that require context.
        ctx: Context for graph operations.
        messages: Full list of messages to send to the LLM (system + history).
    """

    error_count = 0

    # Create chat session
    chat = xai_client.chat.create(
        model="grok-4-1-fast",
        tools=tools,
        tool_choice="auto",
        user="tamas.simon@warmersun.com",
    )
    
    for message in messages:
        chat.append(message)

    counter = 0
    while counter < 100:
        counter += 1
        logger.warning(f"Parallel tool call counter: {counter}")
        # Stream the response
        response = await chat.sample()

        # Check if there are tool calls in the final response
        if not hasattr(response, "tool_calls") or not response.tool_calls:
            # No tool calls, done
            assert response.finish_reason == f"REASON_STOP", f"Expected finish reason to be REASON_STOP, got {response.finish_reason}"
            
            logger.info(f"Usage: {response.usage}")
            logger.info(f"Server side tool usage: {response.server_side_tool_usage}")
            return response.content

        assert response.finish_reason == f"REASON_TOOL_CALLS", f"Expected finish reason to be REASON_TOOL_CALLS, got {response.finish_reason}"
        chat.append(response)

        logger.info(f"Going to process tool calls: {len(response.tool_calls)}")
        # Handle function calls
        for tool_call in response.tool_calls:
            try:
                function_name = tool_call.function.name  # Access as attribute
                function_args = json.loads(tool_call.function.arguments)
                if function_name in functions_with_ctx:
                    function_args = {"ctx": ctx, **function_args}
                result = await function_map[function_name](**function_args)

                # Convert result to JSON string for tool_result
                result_str = json.dumps(result) if not isinstance(
                    result, str) else result
                chat.append(tool_result(result_str))

            except asyncio.CancelledError:
                logger.error(
                    "❌ Error while processing LLM response. CancelledError.")
                await cl.Message(
                    content=
                    "❌ Error while processing LLM response. CancelledError",
                    type="system_message").send()
                return None
            except Exception as e:
                logger.error(
                    f"❌ Error while processing LLM response. Error: {str(e)}")
                error_count += 1
                if error_count >= 3:
                    await cl.Message(
                        content=
                        f"❌ Error while processing LLM response. Error: {str(e)}",
                        type="system_message").send()
                    return None
                # else - if we didn't return
                chat.append(tool_result(json.dumps({"error": str(e)})))
                break
    return None

