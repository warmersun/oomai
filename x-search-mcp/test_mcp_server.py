"""
Test client for X Search MCP Server

Run: uv run python test_mcp_server.py
"""

import asyncio
import os
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def test_mcp_server():
    print("=" * 60)
    print("X Search MCP Server Test")
    print("=" * 60)
    
    # Pass environment to subprocess
    env = os.environ.copy()
    
    server_params = StdioServerParameters(
        command="uv",
        args=["run", "python", "mcp_server.py"],
        env=env,
    )
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize
            await session.initialize()
            
            # List tools
            print("\n📋 Available Tools:")
            tools = await session.list_tools()
            for tool in tools.tools:
                print(f"  - {tool.name}: {tool.description[:60]}...")
            
            # Test search
            print("\n🔍 Testing search_x tool:")
            result = await session.call_tool(
                "search_x",
                {
                    "query": "What is MCP (Model Context Protocol)?",
                    "last_24hrs": False
                }
            )
            
            content = result.content[0].text
            print(f"  Response preview: {content[:500]}...")
            print(f"  Total length: {len(content)} chars")
            
            print("\n" + "=" * 60)
            print("✅ All tests completed!")
            print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_mcp_server())
