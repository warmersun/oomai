"""
Test MCP Server - Connect and Query the Knowledge Graph

Run with: uv run python test_mcp_server.py
"""

import asyncio
import json
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def test_mcp_server():
    """Connect to the MCP server and test graph operations."""
    
    server_params = StdioServerParameters(
        command="uv",
        args=["run", "python", "mcp_server.py"],
        cwd="/home/sic/dev/xaineo4j",
    )
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize the session
            await session.initialize()
            
            print("=" * 60)
            print("MCP Server Test")
            print("=" * 60)
            
            # Test 1: List available tools
            print("\n📋 Available Tools:")
            tools = await session.list_tools()
            for tool in tools.tools:
                print(f"  - {tool.name}: {tool.description[:60]}...")
            
            # Test 2: List available resources
            print("\n📚 Available Resources:")
            resources = await session.list_resources()
            for resource in resources.resources:
                print(f"  - {resource.uri}: {resource.name}")
            
            # Test 3: Read a resource (schema node types)
            print("\n📖 Reading schema://node_types resource:")
            resource_content = await session.read_resource("schema://node_types")
            content_text = resource_content.contents[0].text[:500]
            print(f"  {content_text}...")
            
            # Test 4: Execute a Cypher query
            print("\n🔍 Testing execute_cypher_query tool:")
            result = await session.call_tool(
                "execute_cypher_query",
                {"query": "MATCH (e:EmTech) RETURN e.name AS name LIMIT 5"}
            )
            print(f"  EmTech nodes: {result.content[0].text}")
            
            # Test 5: Test DFS traversal
            print("\n🌲 Testing dfs tool:")
            result = await session.call_tool(
                "dfs",
                {
                    "node_name": "artificial intelligence",
                    "node_type": "Capability",
                    "depth": 1
                }
            )
            dfs_result = json.loads(result.content[0].text)
            if "error" not in dfs_result:
                print(f"  Found {len(dfs_result[0].get('nodes', []))} nodes")
                print(f"  Found {len(dfs_result[0].get('edges', []))} edges")
            else:
                print(f"  Note: {dfs_result.get('error', 'No AI capability node found')}")
            
            print("\n" + "=" * 60)
            print("✅ All tests completed!")
            print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_mcp_server())
