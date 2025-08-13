import os
import json
import sys
from openai import OpenAI

# Initialize OpenAI client
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# Define the tools (functions) - flattened structure for Responses API
tools = [
    {
        "type": "function",
        "name": "get_weather",
        "description": "Get the current weather in a given location",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "The city, e.g. Paris",
                },
                "unit": {
                    "type": "string",
                    "enum": ["celsius", "fahrenheit"],
                    "description": "The unit of temperature (default: fahrenheit)",
                },
            },
            "required": ["location"],
        }
    }
]

# Define the available functions
def get_weather(location, unit="fahrenheit"):
    # Dummy function for example purposes - in real use, this could call an API
    weather_info = {
        "location": location,
        "temperature": "72" if unit == "fahrenheit" else "22",
        "unit": unit,
        "forecast": ["sunny", "windy"],
    }
    return json.dumps(weather_info)

available_functions = {
    "get_weather": get_weather,
}

# Function to create the response with streaming
def create_response(input_data, previous_response_id=None):
    kwargs = {
        "model": "gpt-5",
        "instructions": """
        <tool_preambles>
        - Always begin by rephrasing the user's goal in a friendly, clear, and concise manner, before calling any tools.
        - Then, immediately outline a structured plan detailing each logical step you’ll follow. - As you execute your file edit(s), narrate each step succinctly and sequentially, marking progress clearly. 
        - Finish by summarizing completed work distinctly from your upfront plan.
        </tool_preambles>
        """,
        "input": input_data,
        "tools": tools,
        "stream": True,
        "reasoning": {"summary": "auto"},
    }
    if previous_response_id:
        kwargs["previous_response_id"] = previous_response_id
    return client.responses.create(**kwargs)

# Function to process the streaming response
def process_stream(response):
    tool_calls = []
    content = ""
    reasoning = ""
    response_id = None
    current_tool = None

    for event in response:
        if event.type == "response.created":
            response_id = event.response.id
        elif event.type == "response.output_item.added":
            item = event.item
            if item.type == "function_call":
                current_tool = {
                    "id": item.call_id,
                    "type": "function",
                    "function": {
                        "name": item.name,
                        "arguments": ""
                    }
                }
                tool_calls.append(current_tool)
        elif event.type == "response.function_call_arguments.delta":
            if current_tool:
                current_tool["function"]["arguments"] += event.delta
        elif event.type == "response.output_text.delta":
            content += event.delta
            sys.stdout.write(event.delta)
            sys.stdout.flush()
        elif event.type == "response.reasoning_summary.delta":
            reasoning += event.delta
            sys.stdout.write("\nReasoning: " + event.delta)
            sys.stdout.flush()
        elif event.type == "response.done":
            pass  # Can check finish_reason here if needed

    if tool_calls:
        new_input = []
        for tool_call in tool_calls:
            function_name = tool_call["function"]["name"]
            try:
                function_args = json.loads(tool_call["function"]["arguments"])
            except json.JSONDecodeError:
                function_args = {}
            if function_name in available_functions:
                function_response = available_functions[function_name](**function_args)
                new_input.append({
                    "type": "function_call_output",
                    "call_id": tool_call["id"],
                    "output": function_response,
                })
        return response_id, True, new_input
    else:
        if reasoning:
            print("\nFull Reasoning Summary: " + reasoning)
        return response_id, False, None

# Main execution
if __name__ == "__main__":
    # Example user message that triggers function call and reasoning
    input_data = [
        {
            "role": "user",
            "content": "Tell a joke about the weather in Paris"
        }
    ]

    previous_id = None
    while True:
        response = create_response(input_data, previous_id)
        previous_id, needs_continue, new_input = process_stream(response)
        print()  # New line after streaming
        if not needs_continue:
            break
        input_data = new_input