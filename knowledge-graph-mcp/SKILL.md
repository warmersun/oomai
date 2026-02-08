---
name: knowledge-graph-mcp
description: Connect to a Neo4j knowledge graph for emerging technologies via MCP. Query the graph with Cypher, create nodes and relationships, perform semantic search, and traverse the graph. Use when working with technology research, trend analysis, or building knowledge about emerging tech convergence.
license: MIT
compatibility: Requires MCP client support, Neo4j database, OpenAI API (embeddings), and Groq API (LLM for deduplication)
metadata:
  author: warmersun
  version: "1.0"
---

# Knowledge Graph MCP Server

This skill provides access to a Neo4j-based knowledge graph focused on emerging technologies, capabilities, milestones, and their convergence.

## Prerequisites

1. **Neo4j Database** - A running Neo4j instance with the schema populated
2. **API Keys** in environment:
   - `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`
   - `OPENAI_API_KEY` (for embeddings)
   - `GROQ_API_KEY` (for smart deduplication)

## Starting the Server

```bash
uv run python mcp_server.py
```

Or use the provided script:
```bash
./scripts/start-server.sh
```

## Available Tools

### execute_cypher_query
Execute read-only Cypher queries against the graph.

```
Query: MATCH (e:EmTech)-[:ENABLES]->(c:Capability) RETURN e.name, c.name LIMIT 10
```

### create_node
Create or update nodes with smart deduplication.

```
node_type: Capability
name: Context Retention in Dialogs
description: The ability of LLMs to maintain context across long conversations
```

### create_edge
Create relationships between existing nodes.

```
source_name: artificial intelligence
target_name: Context Retention in Dialogs
relationship_type: ENABLES
```

### find_node
Semantic search for similar nodes using embeddings.

```
query_text: language models understanding context
node_type: Capability
top_k: 10
```

### dfs
Depth-first traversal from a starting node.

```
node_name: artificial intelligence
node_type: Capability
depth: 2
```

## Available Resources

| URI | Description |
|-----|-------------|
| `schema://graph` | Complete graph schema |
| `schema://node_types` | Node type definitions |
| `schema://edge_types` | Relationship type definitions |
| `schema://taxonomy` | EmTech reference taxonomy |
| `schema://population_guidance` | Best practices for populating the graph |

## Schema Overview

### Node Types
- **EmTech** - Emerging technologies (fixed taxonomy, do not create)
- **Capability** - What technology enables
- **Milestone** - Measurable achievements in capability
- **Convergence** - How EmTechs accelerate each other
- **LTC/PTC** - Logical/Physical Technology Components
- **LAC/PAC** - Logical/Physical Application Components
- **Trend** - Predictions about capability progression
- **Idea** - Ideas, policies, predictions
- **Party** - Organizations or people

### Key Relationships
- `(:EmTech)-[:ENABLES]->(:Capability)`
- `(:Capability)-[:HAS_MILESTONE]->(:Milestone)`
- `(:Milestone)-[:UNLOCKS]->(:LAC)`
- `(:LTC)-[:IS_REALIZED_BY]->(:PTC)`
- `(:Party)-[:MAKES]->(:PTC)`

## Example Workflow

1. **Read the schema**: Access `schema://graph` resource
2. **Find existing nodes**: Use `find_node` to search semantically
3. **Query relationships**: Use `execute_cypher_query` for complex patterns
4. **Add new knowledge**: Use `create_node` then `create_edge`
5. **Explore connections**: Use `dfs` to traverse from a node

## MCP Client Configuration

Example configuration (adjust the directory path to where you installed this skill):

```json
{
  "mcpServers": {
    "knowledge-graph": {
      "command": "uv",
      "args": ["run", "python", "mcp_server.py"],
      "cwd": "./knowledge-graph-mcp"
    }
  }
}
```
