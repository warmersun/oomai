import chainlit as cl

async def display_convergence_canvas(json_str: str) -> None:
    """Display a “Convergence Canvas” visualization in the chat UI.

    Args:
        json_str (str): JSON-encoded string that **must** represent a single
            JSON object.  
            - **Keys**: Emerging-technology identifiers drawn from the allowed
              list below.  
              - `"ai"`  
              - `"arvr"`  
              - `"computing"`  
              - `"crypto"`  
              - `"energy"`  
              - `"iot"`  
              - `"networks"`  
              - `"robot"`  
              - `"synbio"`  
              - `"threeDprinting"`  
              - `"transportation"`  
            - **Values**: Plain-text descriptions explaining each selected
              technology's role in the solution.

            Example (must be stringified before passing):

            ```json
            {
              "robot": "Robots for automated assembly tasks.",
              "ai": "AI algorithms for real-time quality control."
            }
            ```

    Returns:
        None: The function sends the rendered visualization to the UI and
        produces no direct return value.
    """
    elem = cl.CustomElement(name="Pathway", props={"data": json_str})
    await cl.Message(content="Convergence Canvas:", elements=[elem]).send()

async def visualize_oom(months_per_doubling: int) -> None:
    element = cl.CustomElement(name="OomVisualizer", props={"monthsPerDoubling": months_per_doubling})
    await cl.Message(content="📈 OOM Visualizer", elements=[element]).send()
