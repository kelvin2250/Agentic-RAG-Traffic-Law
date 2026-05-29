import os
import json
from typing import Optional, List, Dict, Any
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.types import CallToolResult

class BrightDataClient:
    def __init__(self, token: Optional[str] = None, pro: bool = True):
        self.token = token or os.getenv("BRIGHTDATA_TOKEN")
        if not self.token:
            raise ValueError("API token khong duoc cung cap. Dat BRIGHTDATA_TOKEN trong file .env")
        
        self.pro = "1" if pro else "0"
        self.url = f"https://mcp.brightdata.com/sse?token={self.token}&pro={self.pro}"

    def _parse_serp_response(self, search_result: CallToolResult) -> List[Dict[str, str]]:
        parsed_results = []
        if not search_result or not hasattr(search_result, 'content'):
            return parsed_results

        for block in search_result.content:
            if hasattr(block, 'text') and block.text:
                try:
                    data = json.loads(block.text)
                    items = data.get("organic", data.get("results", []))
                    
                    for item in items:
                        link = item.get("link") or item.get("url")
                        if link:
                            parsed_results.append({
                                "title": item.get("title", ""),
                                "link": link,
                                "description": item.get("description", "")
                            })
                except json.JSONDecodeError:
                    continue
        return parsed_results

    async def search_web(self, query: str, domains: Optional[List[str]] = None) -> List[Dict[str, str]]:
        refined_query = query
        if domains:
            site_filters = " OR ".join([f"site:{d}" for d in domains])
            refined_query = f"{query} ({site_filters})"

        async with sse_client(self.url) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                
                try:
                    result: CallToolResult = await session.call_tool(
                        "search_engine", 
                        arguments={"query": refined_query}
                    )
                    return self._parse_serp_response(result)
                except Exception as e:
                    print(f"Loi khi thuc hien search_engine: {e}")
                    return []

    async def scrape_url(self, target_url: str) -> str:
        async with sse_client(self.url) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                
                try:
                    result: CallToolResult = await session.call_tool(
                        "scrape_as_markdown", 
                        arguments={"url": target_url}
                    )
                    if result and hasattr(result, 'content') and result.content:
                        return result.content[0].text if hasattr(result.content[0], 'text') else ""
                    return ""
                except Exception as e:
                    print(f"Loi khi cao URL {target_url}: {e}")
                    return ""