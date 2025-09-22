import chainlit as cl

@cl.on_chat_start
async def on_start():
    # Example Mermaid diagram string (replace with your own or dynamic input)
    diagram_str = """
graph TD
    A[Start] --> B{Decision}
    B -->|Yes| C[Option 1]
    B -->|No| D[Option 2]
    C --> E[End]
    D --> E[End]
    """

    # Create the custom element
    mermaid_element = cl.CustomElement(
        name="MermaidDiagram",
        props={"diagram": diagram_str},
        display="inline"  # Or "side" or "page" as needed
    )

    # Send it in a message
    await cl.Message(
        content="Here's your Mermaid diagram:",
        elements=[mermaid_element]
    ).send()