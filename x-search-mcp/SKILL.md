---
name: x-search-mcp
description: Search X (Twitter) and the web using xAI's Grok model. Performs agentic search with image understanding. Use when you need to find recent posts, trends, or real-time information from X.
license: MIT
compatibility: Requires MCP client support and xAI API access
metadata:
  author: warmersun
  version: "1.0"
---

# X Search MCP Server

This skill provides agentic search on X (Twitter) and the web using xAI's Grok model.

## Prerequisites

1. **xAI API Key** - Get from [x.ai](https://x.ai)
2. Set environment variable: `XAI_API_KEY`

## Starting the Server

```bash
uv run python mcp_server.py
```

## Available Tools

### search_x

Search X and the web with natural language queries.

**Parameters:**
- `query` (required): The search query or question
- `included_handles` (optional, default: `null`): List of X handles to focus on
- `last_24hrs` (optional, default: `false`): Only search last 24 hours
- `system_prompt` (optional, default: `"Search on X and return a detailed summary."`): Custom instructions for the search agent

**Example - Basic search:**
```
query: "What are the latest developments in AI agents?"
```

**Example - Last 24 hours:**
```
query: "Breaking news in tech"
last_24hrs: true
```

**Example - Specific handles:**
```
query: "What did they say about MCP?"
included_handles: ["@AnthropicAI", "@OpenAI"]
```

**Example - Custom system prompt:**
```
query: "AI agent frameworks 2024"
system_prompt: "You are a tech analyst. Search X and web for information, then provide a structured comparison with pros/cons for each framework mentioned."
```

## MCP Client Configuration

```json
{
  "mcpServers": {
    "x-search": {
      "command": "uv",
      "args": ["run", "python", "mcp_server.py"],
      "cwd": "./x-search-mcp",
      "env": {
        "XAI_API_KEY": "your-api-key"
      }
    }
  }
}
```
