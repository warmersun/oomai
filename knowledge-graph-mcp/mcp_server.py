"""
MCP Server for Knowledge Graph Operations

Exposes Neo4j knowledge graph operations as MCP tools and schema as resources.
Run with: uv run mcp dev mcp_server.py
"""

import json
import logging
from typing import Literal, Optional, Dict, Union
from asyncio import Lock

from mcp.server.fastmcp import FastMCP
from neo4j import AsyncGraphDatabase
from openai import AsyncOpenAI

from config import (
    NEO4J_URI,
    NEO4J_USERNAME,
    NEO4J_PASSWORD,
    OPENAI_API_KEY,
    GROQ_API_KEY,
)
from function_tools.core_graph_ops import (
    GraphOpsCtx,
    core_execute_cypher_query,
    core_create_node,
    core_create_edge,
    core_find_node,
    core_dfs,
    Neo4jDateEncoder,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize MCP server
mcp = FastMCP(
    "Knowledge Graph MCP Server",
    dependencies=["neo4j", "openai"],
)

# Global context - will be initialized on first use
_ctx: Optional[GraphOpsCtx] = None
_openai_client: Optional[AsyncOpenAI] = None
_groq_client = None


async def get_context() -> GraphOpsCtx:
    """Get or create the Neo4j context."""
    global _ctx
    if _ctx is None:
        driver = AsyncGraphDatabase.driver(
            NEO4J_URI,
            auth=(NEO4J_USERNAME, NEO4J_PASSWORD),
        )
        _ctx = GraphOpsCtx(
            neo4jdriver=driver,
            lock=Lock(),
        )
    return _ctx


async def get_openai_client() -> AsyncOpenAI:
    """Get or create the OpenAI client for embeddings."""
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    return _openai_client


async def get_groq_client():
    """Get or create the Groq client for LLM operations."""
    global _groq_client
    if _groq_client is None:
        from openai import AsyncOpenAI as AsyncGroq
        _groq_client = AsyncGroq(
            api_key=GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1",
        )
    return _groq_client


# =============================================================================
# MCP TOOLS - Graph Operations
# =============================================================================


@mcp.tool()
async def execute_cypher_query(query: str) -> str:
    """
    Execute a read-only Cypher query against the Neo4j knowledge graph.
    
    Only supports safe, query-only operations: MATCH, OPTIONAL MATCH, UNWIND, 
    WITH, RETURN, UNION. No data modification allowed.
    
    Use patterns like: (e:EmTech {name: 'artificial intelligence'})-[:ENABLES]->(c:Capability)
    
    Returns query results as JSON.
    
    Args:
        query: A read-only Cypher query string
    """
    ctx = await get_context()
    try:
        results = await core_execute_cypher_query(ctx, query)
        return json.dumps(results, cls=Neo4jDateEncoder, indent=2)
    except RuntimeError as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def create_node(node_type: str, name: str, description: str) -> str:
    """
    Create or update a node in the knowledge graph.
    
    For nodes with embeddings (Convergence, Capability, Milestone, Trend, Idea, 
    LTC, LAC), performs smart deduplication by checking for similar nodes.
    
    Node types: EmTech, Convergence, Capability, Milestone, LTC, PTC, LAC, PAC, 
    Trend, Idea, Party
    
    Args:
        node_type: The type/label of the node (e.g., 'Capability', 'Party')
        name: A short, unique name for the node in Title Case
        description: Detailed description of the node
    
    Returns:
        The name of the created/matched node (may differ from input if merged)
    """
    ctx = await get_context()
    openai_client = await get_openai_client()
    groq_client = await get_groq_client()
    
    try:
        result = await core_create_node(
            ctx, node_type, name, description,
            groq_client=groq_client,
            openai_embedding_client=openai_client,
        )
        return result
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def create_edge(
    source_name: str,
    target_name: str,
    relationship_type: str,
    properties: Optional[Dict[str, Union[str, int, float, bool]]] = None,
) -> str:
    """
    Create a directed relationship between two existing nodes.
    
    Edge types: DECOMPOSES, ACCELERATES, IS_ACCELERATED_BY, ENABLES, 
    HAS_MILESTONE, UNLOCKS, REACHES, PREDICTS, LOOKS_AT, PROVIDES, 
    IS_REALIZED_BY, MAKES, USES, RELATES_TO
    
    Args:
        source_name: Name of the source node
        target_name: Name of the target node  
        relationship_type: Type of relationship (e.g., 'ENABLES', 'USES')
        properties: Optional properties for the edge (e.g., {'explanation': '...'})
    
    Returns:
        The created relationship as JSON
    """
    ctx = await get_context()
    
    try:
        result = await core_create_edge(
            ctx, source_name, target_name, relationship_type, properties
        )
        return json.dumps(result, cls=Neo4jDateEncoder, indent=2)
    except RuntimeError as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def find_node(
    query_text: str,
    node_type: Literal["Convergence", "Capability", "Milestone", "Trend", "Idea", "Bet", "LTC", "LAC"],
    top_k: int = 25,
) -> str:
    """
    Find nodes similar to a query using vector semantic search.
    
    Uses embeddings to find nodes with similar descriptions.
    
    Args:
        query_text: Text to search for similar nodes
        node_type: Type of node to search (Convergence, Capability, Milestone, Trend, Idea, LTC, or LAC)
        top_k: Maximum number of results to return (default 25)
    
    Returns:
        List of matching nodes with names, descriptions, and similarity scores
    """
    ctx = await get_context()
    openai_client = await get_openai_client()
    
    try:
        results = await core_find_node(
            ctx, query_text, node_type, top_k, openai_client
        )
        return json.dumps(results, cls=Neo4jDateEncoder, indent=2)
    except RuntimeError as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def dfs(
    node_name: str,
    node_type: Literal["Convergence", "Capability", "Milestone", "LTC", "PTC", "LAC", "PAC", "Trend", "Idea", "Bet", "Party"],
    depth: int = 3,
) -> str:
    """
    Perform depth-first search traversal starting from a node.
    
    Returns all connected nodes and edges up to the specified depth,
    stopping at EmTech nodes.
    
    Args:
        node_name: Name of the starting node
        node_type: Type of the starting node
        depth: Maximum depth for traversal (default 3)
    
    Returns:
        JSON with 'nodes' (list of {name, description}) and 
        'edges' (list of {source_node_name, relationship, end_node_name})
    """
    ctx = await get_context()
    
    try:
        results = await core_dfs(ctx, node_name, node_type, depth)
        return json.dumps(results, cls=Neo4jDateEncoder, indent=2)
    except (ValueError, RuntimeError) as e:
        return json.dumps({"error": str(e)})


# =============================================================================
# MCP RESOURCES - Schema Information
# =============================================================================

# Load schema content (relative to this file)
import os as _os
_BASE_DIR = _os.path.dirname(__file__)
with open(_os.path.join(_BASE_DIR, "knowledge_graph", "schema.md"), "r") as f:
    SCHEMA_CONTENT = f.read()


def extract_section(content: str, start_marker: str, end_marker: str) -> str:
    """Extract a section from markdown content between markers."""
    start_idx = content.find(start_marker)
    if start_idx == -1:
        return ""
    end_idx = content.find(end_marker, start_idx + len(start_marker))
    if end_idx == -1:
        end_idx = len(content)
    return content[start_idx:end_idx].strip()


@mcp.resource("schema://graph")
def get_full_schema() -> str:
    """
    Complete knowledge graph schema including node types, edge types, 
    vector indices, and EmTech taxonomy.
    """
    return SCHEMA_CONTENT


@mcp.resource("schema://taxonomy")
def get_taxonomy() -> str:
    """
    EmTech taxonomy - reference data for emerging technology categories.
    
    EmTechs are fixed reference data - do not create new EmTech nodes.
    Available categories: computing, energy, artificial intelligence, robots, 
    networks, 3D printing, IoT, VR, synthetic biology, quantum computing, etc.
    """
    return extract_section(SCHEMA_CONTENT, "## taxonomy", "END_OF_FILE_MARKER")


# Load schema population guidance
with open(_os.path.join(_BASE_DIR, "knowledge_graph", "schema_population_guidance.md"), "r") as f:
    POPULATION_GUIDANCE_CONTENT = f.read()


@mcp.resource("schema://population_guidance")
def get_population_guidance() -> str:
    """
    Guidelines for populating the knowledge graph correctly.
    
    Contains best practices for creating each node type, including when to 
    create vs reuse nodes, how to associate relationships, and common pitfalls.
    """
    return POPULATION_GUIDANCE_CONTENT


# =============================================================================
# Server Entry Point
# =============================================================================

if __name__ == "__main__":
    mcp.run()
