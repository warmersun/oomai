import chainlit as cl
from .core_graph_ops import GraphOpsCtx
from .core_graph_ops import core_execute_cypher_query
from .core_graph_ops import core_create_node
from .core_graph_ops import core_create_edge
from .core_graph_ops import core_find_node
from .core_graph_ops import core_scan_ideas
from .core_graph_ops import core_scan_trends
from .core_graph_ops import core_dfs
from typing import List, Optional, Literal, Dict, Union


async def execute_cypher_query(ctx: GraphOpsCtx, query: str) -> List[dict]:
    async with cl.Step(name="Execute_Cypher_Query", type="retrieval") as step:
        step.show_input = True
        step.input = {"query": query}

        step_message = cl.Message(content=f"Executing Cypher query: `{query}`")
        await step_message.send()

        output = await core_execute_cypher_query(ctx, query)

        step.output = output
        debug = cl.user_session.get("debug_settings")
        if not debug:
            await step.remove()
        return output

async def create_node(ctx: GraphOpsCtx, node_type: str, name: str, description: str) -> str:
    async with cl.Step(name="Create_Node", type="tool") as step:
        step.show_input = True
        step.input = {"node_type": node_type, "name": name, "description": description}

        groq_client = cl.user_session.get("groq_client")
        openai_embedding_client = cl.user_session.get("openai_embedding_client")

        step_message = cl.Message(content=f"Creating node: {name} of type {node_type} with description: {description}")
        await step_message.send()

        output = await core_create_node(ctx, node_type, name, description, groq_client, openai_embedding_client)

        step.output = output
        debug = cl.user_session.get("debug_settings")
        if not debug:
            await step.remove()
        return output

async def create_edge(
    ctx: GraphOpsCtx,
    source_name: str,
    target_name: str,
    relationship_type: str,
    properties: Optional[Dict[str, Union[str, int, float, bool]]] = None,
) -> dict:
    async with cl.Step(name="Create_Edge", type="tool") as step:
        step.show_input = True
        step.input = {
            "source_name": source_name,
            "target_name": target_name,
            "relationship_type": relationship_type,
            "properties": [{"key": k, "value": v} for k, v in (properties or {}).items()],
        }

        step_message = cl.Message(content=f"Creating edge between {source_name} and {target_name} with type {relationship_type} and properties {properties}")
        await step_message.send()

        output = await core_create_edge(ctx, source_name, target_name, relationship_type, properties)
        step.output = output
        debug = cl.user_session.get("debug_settings")
        if not debug:
            await step.remove()
        return output

async def find_node(
    ctx: GraphOpsCtx,
    query_text: str,
    node_type: Literal[
        "Convergence", "Capability", "Milestone", "Trend", "Idea", "LTC", "LAC"
    ],
    top_k: int = 25
) -> list:
    async with cl.Step(name="Find_Node", type="retrieval") as step:
        step.show_input = True
        step.input = {"query_text": query_text, "node_type": node_type, "top_k": top_k}

        openai_embedding_client = cl.user_session.get("openai_embedding_client")
        assert openai_embedding_client is not None, "No OpenAI client found in user session"

        step_message = cl.Message(content=f"Finding upto {top_k} {node_type}: `{query_text}`")
        await step_message.send()

        output = await core_find_node(ctx, query_text, node_type, top_k, openai_embedding_client)

        step.output = output
        debug = cl.user_session.get("debug_settings")
        if not debug:
            await step.remove()
        return output

async def scan_ideas(
    ctx: GraphOpsCtx,
    query_probes: List[str],
    top_k_per_probe: int = 20,
    max_results: int = 80,
) -> list:
    async with cl.Step(name="Scan_Ideas", type="retrieval") as step:
        step.show_input = True
        step.input = {"query_probes": query_probes, "top_k_per_probe": top_k_per_probe, "max_results": max_results}

        openai_embedding_client = cl.user_session.get("openai_embedding_client")
        assert openai_embedding_client is not None, "No OpenAI client found in user session"

        step_message = cl.Message(content=f"Scanning ideas and bets with {len(query_probes)} probes (up to {max_results} results)")
        await step_message.send()

        output = await core_scan_ideas(ctx, query_probes, top_k_per_probe, max_results, openai_embedding_client)

        step.output = output
        debug = cl.user_session.get("debug_settings")
        if not debug:
            await step.remove()
        return output

async def scan_trends(
    ctx: GraphOpsCtx,
    query_probes: List[str],
    top_k_per_probe: int = 20,
    max_results: int = 80,
    emtech_filter: Optional[str] = None,
) -> list:
    async with cl.Step(name="Scan_Trends", type="retrieval") as step:
        step.show_input = True
        step.input = {"query_probes": query_probes, "top_k_per_probe": top_k_per_probe, "max_results": max_results, "emtech_filter": emtech_filter}

        openai_embedding_client = cl.user_session.get("openai_embedding_client")
        assert openai_embedding_client is not None, "No OpenAI client found in user session"

        filter_msg = f" (filtered to {emtech_filter})" if emtech_filter else ""
        step_message = cl.Message(content=f"Scanning trends with {len(query_probes)} probes{filter_msg} (up to {max_results} results)")
        await step_message.send()

        output = await core_scan_trends(ctx, query_probes, top_k_per_probe, max_results, emtech_filter, openai_embedding_client)

        step.output = output
        debug = cl.user_session.get("debug_settings")
        if not debug:
            await step.remove()
        return output

async def dfs(
    ctx: GraphOpsCtx,
    node_name: str,
    node_type: Literal[
        "Convergence", "Capability", "Milestone", "LTC", "PTC", "LAC", "PAC", "Trend", "Idea", "Party"
    ],
    depth: int = 3,
    max_nodes: int = 100,
    include_descriptions: bool = True
) -> list:
    async with cl.Step(name="Depth-First_Search", type="retrieval") as step:
        step.show_input = True
        step.input = {"node_name": node_name, "node_type": node_type, "depth": depth, "max_nodes": max_nodes, "include_descriptions": include_descriptions}

        step_message = cl.Message(content=f"Performing depth-first search on `{node_name}`, with depth of {depth}")
        await step_message.send()

        try:
            output = await core_dfs(ctx, node_name, node_type, depth, max_nodes, include_descriptions)
            
            step.output = output
            debug = cl.user_session.get("debug_settings")
            if not debug:
                await step.remove()
            return output
        except RuntimeError as e:
            error_msg = f"❌ {str(e)}"
            await cl.Message(content=error_msg).send()
            step.output = {"error": str(e)}
            return []