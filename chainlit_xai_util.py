import json
import chainlit as cl
from chainlit.logger import logger
from xai_sdk.search import SearchParameters
from xai_sdk.chat import tool_result, user, assistant, tool  # Assuming these exist
from typing import Any  # For GraphOpsCtx, assume it's defined elsewhere
import asyncio


async def process_stream(user_input: str, ctx: Any, output_message: cl.Message) -> bool:
    # Retrieve from session
    user_and_assistant_messages = cl.user_session.get("user_and_assistant_messages")
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
    search_settings = cl.user_session.get("search_settings")
    assert search_settings is not None, "No search settings found in user session"

    # Append the new user input as a proper message object
    user_and_assistant_messages.append(user(user_input))

    error_count = 0

    # Create chat session
    if search_settings:
        search_parameters = SearchParameters()
    else:
        search_parameters = None
    chat = xai_client.chat.create(
        model="grok-4-fast",
        search_parameters=search_parameters,
        tools=tools,
        tool_choice="auto"  # Assuming this is supported, based on previous example
    )
    for message in system_messages:
        chat.append(message)
    for message in user_and_assistant_messages:
        chat.append(message)

    counter = 0
    while counter < 100:
        counter += 1
        logger.warning(f"Counter: {counter}")
        # Stream the response
        async for response, chunk in chat.stream():
            if chunk.content:  # Assuming chunk has content for text deltas
                text_chunk = chunk.content
                await output_message.stream_token(text_chunk)  # Stream to output

        # After streaming, append the full assistant content
        user_and_assistant_messages.append(assistant(response.content))

        # Check if there are tool calls in the final response
        if not hasattr(response, "tool_calls") or not response.tool_calls:
            # No tool calls, done
            assert response.finish_reason == "REASON_STOP", "Expected finish reason to be REASON_STOP"
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
                result_str = json.dumps(result) if not isinstance(result, str) else result
                chat.append(tool_result(result_str))

            except asyncio.CancelledError:
                logger.error("❌ Error while processing LLM response. CancelledError.")
                await cl.Message(content="❌ Error while processing LLM response. CancelledError", type="system_message").send()
                return False
            except Exception as e:
                logger.error(f"❌ Error while processing LLM response. Error: {str(e)}")                
                error_count += 1
                if error_count >= 3:
                    await cl.Message(content=f"❌ Error while processing LLM response. Error: {str(e)}", type="system_message").send()
                    return False
                # else - if we didn't return
                chat.append(tool_result(json.dumps({"error": str(e)})))
                break

    search_settings = cl.user_session.get("search_settings")
    if search_settings:
        logger.info(f"Number of sources used in Live Search: {response.usage.num_sources_used}")