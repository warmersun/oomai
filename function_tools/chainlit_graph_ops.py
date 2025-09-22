import chainlit as cl
from .core_graph_ops import GraphOpsCtx
from .core_graph_ops import core_execute_cypher_query
from .core_graph_ops import core_create_node
from .core_graph_ops import core_create_edge
from .core_graph_ops import core_find_node
from typing import List, Optional, Literal, Dict, Union


async def execute_cypher_query(ctx: GraphOpsCtx, query: str) -> List[dict]:
    async with cl.Step(name="Execute_Cypher_Query", type="retrieval") as step:
        step.show_input = True
        step.input = {"query": query}

        output = await core_execute_cypher_query(ctx, query)
        step.output = output
        return output

async def create_node(ctx: GraphOpsCtx, node_type: str, name: str, description: str) -> str:
    async with cl.Step(name="Create_Node", type="tool") as step:
        step.show_input = True
        step.input = {"node_type": node_type, "name": name, "description": description}

        groq_client = cl.user_session.get("groq_client")
        openai_embedding_client = cl.user_session.get("openai_embedding_client")

        output = await core_create_node(ctx, node_type, name, description, groq_client, openai_embedding_client)
        step.output = output
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

        output = await core_create_edge(ctx, source_name, target_name, relationship_type, properties)
        step.output = output
        return output

async def find_node(
    ctx: GraphOpsCtx,
    query_text: str,
    node_type: Literal[
        "Convergence", "Capability", "Milestone", "Trend", "Idea", "LTC", "LAC"
    ],
    top_k: int = 5
) -> list:
    async with cl.Step(name="Find_Node", type="retrieval") as step:
        step.show_input = True
        step.input = {"query_text": query_text, "node_type": node_type, "top_k": top_k}

        openai_embedding_client = cl.user_session.get("openai_embedding_client")
        assert openai_embedding_client is not None, "No OpenAI client found in user session"

        output = await core_find_node(ctx, query_text, node_type, top_k, openai_embedding_client)
        step.output = output
        return output