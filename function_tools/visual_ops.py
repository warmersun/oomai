import chainlit as cl

# note: visualizations don't create new clMessage because these functions get called while we're within a step and that step gets removed at the end.
# Instead, they append to session variables and the main loop picks it up from there.

async def display_mermaid_diagram(diagram_str: str):
    diagrams = cl.user_session.get("diagrams")
    assert diagrams is not None, "No diagrams found in user session"
    diagrams.append(diagram_str)
    cl.user_session.set("diagrams", diagrams)

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
    convergence_canvases = cl.user_session.get("convergence_canvases")
    assert convergence_canvases is not None, "No convergence canvases found in user session"
    convergence_canvases.append(json_str)
    cl.user_session.set("convergence_canvases", convergence_canvases)
    
async def visualize_oom(months_per_doubling: int) -> None:
    oom_visualizers = cl.user_session.get("oom_visualizers")
    assert oom_visualizers is not None, "No OOM Visualizers found in user session"
    oom_visualizers.append(months_per_doubling)
    cl.user_session.set("oom_visualizers", oom_visualizers)
    