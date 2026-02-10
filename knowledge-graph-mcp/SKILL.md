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

## Modes of Operation

### 1. Question Answering Mode

Use the knowledge graph to build context and answer questions.

**Tools**: `execute_cypher_query`, `find_node`, `dfs`

**How to gather context:**
1. Start with `find_node` for semantic search - locate relevant concepts by meaning, not exact names
2. Use `execute_cypher_query` for targeted lookups - when you know what you're looking for
3. Traverse with `dfs` - explore connections from a node to discover related knowledge
4. Iterate until you have enough context to answer thoroughly

### 2. Information Capturing Mode

When provided with research, articles, or documents, decompose content into nodes and relationships.

**Tools**: `create_node`, `create_edge`

**Important rules:**
- **Never use Cypher to create nodes or edges** - Always use `create_node` and `create_edge`
- **Safe to call `create_node` directly** - It automatically detects semantically similar nodes and merges descriptions, so no need to check for duplicates first

Before capturing information, read the `schema://population_guidance` resource for best practices on how to create different types of nodes.

## Output Guidelines

When responding to users:

- **Use natural language** - Respond conversationally, avoid graph terminology like "nodes" or "edges"
- **Avoid abbreviations** - Don't say "LAC", "PAC", "LTC", or "PTC". Use plain terms like "use case", "application", "product", or "service"
- **Markdown only** - No JSON, CSV, or tabular output unless specifically requested

## Available Tools

### execute_cypher_query
Execute **read-only** Cypher queries against the graph. Use for targeted searches and complex relationship patterns.

**Best practices:**
- Always use explicit node labels and relationship types
- Always limit results (e.g., `LIMIT 10`)

```
Query: MATCH (e:EmTech)-[:ENABLES]->(c:Capability) RETURN e.name, c.name LIMIT 10
```

### find_node
Semantic search using embeddings - finds nodes by meaning, not just exact text match.

```
query_text: language models understanding context
node_type: Capability
top_k: 10
```

### dfs
Depth-first traversal from a starting node. Great for exploring connections and building context.

```
node_name: Context Retention in Dialogs
node_type: Capability
depth: 2
```

### create_node
Create nodes with smart deduplication. The system will merge if a semantically similar node exists.

```
node_type: Capability
name: Context Retention in Dialogs
description: The ability of LLMs to maintain context across long conversations
```

### create_edge
Create relationships between existing nodes.

```
source_name: Artificial Intelligence
target_name: Context Retention in Dialogs
relationship_type: ENABLES
```

## Available Resources

Read these resources to understand the graph structure:

| URI | Description |
|-----|-------------|
| `schema://graph` | Complete graph schema |
| `schema://node_types` | Node type definitions |
| `schema://edge_types` | Relationship type definitions |
| `schema://taxonomy` | EmTech reference taxonomy |
| `schema://population_guidance` | **Read this in Information Capturing mode** - best practices for creating nodes and edges |

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
