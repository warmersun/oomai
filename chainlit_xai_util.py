import json
import chainlit as cl
from chainlit.logger import logger
from xai_sdk.chat import tool_result, user, assistant, tool
from xai_sdk.tools import x_search, web_search
from typing import Any  # For GraphOpsCtx, assume it's defined elsewhere
import asyncio


async def process_stream(user_input: str, ctx: Any,
                         output_message: cl.Message) -> bool:
    # Retrieve from session
    user_and_assistant_messages = cl.user_session.get(
        "user_and_assistant_messages")
    assert user_and_assistant_messages is not None, "No user and assistant messages found in user session"
    system_messages = cl.user_session.get("system_messages")
    assert system_messages is not None, "No system messages found in user session"
    tools = cl.user_session.get("tools")
    assert tools is not None, "No tools found in user session"
    xai_client = cl.user_session.get("xai_client")
    assert xai_client is not None, "No xai_client found in user session"
    function_map = cl.user_session.get("function_map")
    assert function_map is not None, "No function_map found in user session"
    functions_with_ctx = cl.user_session.get("functions_with_ctx")
    assert functions_with_ctx is not None, "No functions_with_ctx found in user session"
    
    # Append the new user input as a proper message object
    user_and_assistant_messages.append(user(user_input))

    error_count = 0

    client_and_server_side_tools = tools.copy()
    client_and_server_side_tools.append(web_search(excluded_domains=["wikipedia.org", "gartner.com", "weforum.com", "forbes.com", "accenture.com"], enable_image_understanding=True))

    # Create chat session
    chat = xai_client.chat.create(
        model="grok-4-1-fast",
        tools=client_and_server_side_tools,
        tool_choice="auto",
        user="tamas.simon@warmersun.com",
    )
    for message in system_messages:
        chat.append(message)
    for message in user_and_assistant_messages:
        chat.append(message)

    counter = 0
    while counter < 100:
        counter += 1
        logger.warning(f"Parallel tool call counter: {counter}")
        # Stream the response
        response = await chat.sample()

        # After streaming, append the full assistant content
        user_and_assistant_messages.append(assistant(response.content))

        # Check if there are tool calls in the final response
        if not hasattr(response, "tool_calls") or not response.tool_calls:
            # No tool calls, done
            assert response.finish_reason == "REASON_STOP", "Expected finish reason to be REASON_STOP"
            output_message.content = response.content
            await output_message.update()
            # update session variable
            cl.user_session.set("user_and_assistant_messages", user_and_assistant_messages)
            logger.info(f"Usage: {response.usage}")
            logger.info(f"Server side tool usage: {response.server_side_tool_usage}")
            return True

        assert response.finish_reason == "REASON_TOOL_CALLS", "Expected finish reason to be REASON_TOOL_CALLS"
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
                return False
            except Exception as e:
                logger.error(
                    f"❌ Error while processing LLM response. Error: {str(e)}")
                error_count += 1
                if error_count >= 3:
                    await cl.Message(
                        content=
                        f"❌ Error while processing LLM response. Error: {str(e)}",
                        type="system_message").send()
                    return False
                # else - if we didn't return
                chat.append(tool_result(json.dumps({"error": str(e)})))
                break

