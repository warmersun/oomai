#!/bin/bash
# Start the Knowledge Graph MCP Server
# Usage: ./start-server.sh [--dev]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ROOT_DIR="$(dirname "$PROJECT_DIR")"

cd "$ROOT_DIR"

# Check for required environment variables
if [[ -z "$NEO4J_URI" ]] && [[ ! -f .env ]]; then
    echo "Error: NEO4J_URI not set and no .env file found"
    echo "Required environment variables:"
    echo "  - NEO4J_URI"
    echo "  - NEO4J_USERNAME"
    echo "  - NEO4J_PASSWORD"
    echo "  - OPENAI_API_KEY"
    echo "  - GROQ_API_KEY"
    exit 1
fi

if [[ "$1" == "--dev" ]]; then
    echo "Starting MCP server in development mode with inspector..."
    uv run mcp dev mcp_server.py
else
    echo "Starting MCP server..."
    uv run python mcp_server.py
fi
