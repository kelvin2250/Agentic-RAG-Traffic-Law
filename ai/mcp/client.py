"""
MCP Client - Connect to MCP tool servers via SSE.

Helper for agents to call MCP tools over HTTP streams.
"""
import logging
import os
from typing import Any
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


class MCPClient:
    """
    Client for connecting to MCP tool servers using SSE transport.
    """
    
    def __init__(self, sse_url: str):
        """
        Initialize MCP client.
        
        Args:
            sse_url: URL for SSE transport (e.g., http://localhost:8100/mcp/sse)
        """
        if not sse_url:
            raise ValueError("sse_url must be provided")
        self.sse_url = sse_url
    
    @asynccontextmanager
    async def connect(self):
        """Connect to MCP server over SSE and yield session."""
        from mcp import ClientSession
        from mcp.client.sse import sse_client
        
        try:
            async with sse_client(self.sse_url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session
        except Exception as e:
            logger.error(f"MCP SSE connection failed to {self.sse_url}: {e}")
            raise
    
    async def call_tool(self, tool_name: str, arguments: dict) -> Any:
        """
        Call a tool on the MCP server.
        
        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments
            
        Returns:
            Tool result (CallToolResult)
        """
        async with self.connect() as session:
            result = await session.call_tool(tool_name, arguments)
            return result

def get_retrieval_client() -> MCPClient:
    """Get SSE client for Retrieval (Search, Scrape, Chunking) MCP server."""
    url = os.getenv("MCP_RETRIEVAL_URL", "http://localhost:8100/mcp/sse")
    return MCPClient(sse_url=url)


def get_rerank_client() -> MCPClient:
    """Get SSE client for Rerank (Cohere) MCP server."""
    url = os.getenv("MCP_RERANK_URL", "http://localhost:8200/mcp/sse")
    return MCPClient(sse_url=url)