# Knowledge Graph MCP Server

A self-contained MCP server for Neo4j knowledge graphs.

## Installation

```bash
cd knowledge-graph-mcp
uv sync
```

## Configuration

Create a `.env` file:

```
NEO4J_URI=neo4j+s://your-db.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your-password
OPENAI_API_KEY=sk-...
GROQ_API_KEY=gsk_...
```

## Run

```bash
uv run python mcp_server.py
```

Or use the entry point after install:
```bash
uv run knowledge-graph-mcp
```
