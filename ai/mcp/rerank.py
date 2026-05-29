import os
import json
import logging
import argparse
from typing import List
from dotenv import load_dotenv
# Thư viện Rerank
import cohere

# Thư viện hạ tầng MCP & Starlette
from mcp.server.fastmcp import FastMCP
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import Response

# 0. Cấu hình Logging & Biến môi trường
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
load_dotenv()

# 1. Khởi tạo FastMCP Server chuyên dụng cho Rerank
mcp = FastMCP("RerankOrchestrator")

# 2. Khởi tạo kết nối Cohere Client thông qua API Key bảo mật
COHERE_API_KEY = os.getenv("COHERE_API_KEY")
if not COHERE_API_KEY:
    logger.warning("Cảnh báo: Thiếu COHERE_API_KEY trong file .env")
cohere_client = cohere.ClientV2(api_key=COHERE_API_KEY)

# 3. Định nghĩa công cụ (Tool) Rerank
@mcp.tool()
def reranking_documents(query: str, documents: List[str], top_n: int = 3) -> str:
    """
    Sử dụng Cohere API Rerank v3.5 đa ngôn ngữ để sắp xếp các đoạn luật khớp nhất với câu hỏi.
    """
    if not query or not documents:
        return json.dumps([])

    try:
        # Gọi trực tiếp API Endpoint thế hệ mới của Cohere
        response = cohere_client.rerank(
            model="rerank-v3.5", # Tối ưu đa ngôn ngữ chuyên dụng cho tiếng Việt
            query=query,
            documents=documents,
            top_n=top_n
        )
        
        ranked_results = []
        for result in response.results:
            idx = result.index
            ranked_results.append({
                "document": documents[idx],
                "score": float(result.relevance_score),
                "index": int(idx)
            })
            
        return json.dumps(ranked_results, ensure_ascii=False)
        
    except Exception as e:
        logger.error(f"Lỗi khi thực thi Cohere Rerank API: {e}")
        return json.dumps({"error": str(e)})


# 4. Cấu trúc Server theo Starlette Pattern (Đồng bộ 100% với file retrieval thành công)
# Sử dụng chính xác hậu tố đường dẫn làm prefix cho session query
sse = SseServerTransport("/mcp/messages/")

async def handle_sse(request):
    # Sử dụng chính xác request.scope, request.receive và ẩn số request._send
    # SSE data được gửi trực tiếp qua request._send bên trong connect_sse context.
    # Bắt buộc return Response() để Starlette routing không bị crash (NoneType not callable).
    async with sse.connect_sse(
        request.scope, request.receive, request._send
    ) as streams:
        await mcp._mcp_server.run(
            streams[0], streams[1], mcp._mcp_server.create_initialization_options()
        )
    return Response()

# Khởi tạo Starlette App độc lập thay thế cho FastAPI
app = Starlette(
    routes=[
        Route("/mcp/sse", endpoint=handle_sse),
        Mount("/mcp/messages/", app=sse.handle_post_message),
    ]
)


if __name__ == "__main__":
    import uvicorn
    
    parser = argparse.ArgumentParser(description="Rerank Orchestrator MCP Server")
    parser.add_argument("--port", type=int, default=8200) # Mặc định port 8200 cho Rerank
    args = parser.parse_args()
    
    logger.info(f"MCP Server chuẩn ASGI (Starlette Pattern - Rerank) đã sẵn sàng hoạt động!")
    logger.info(f"Endpoint SSE: http://localhost:{args.port}/mcp/sse")
    logger.info(f"Endpoint Messages: http://localhost:{args.port}/mcp/messages/")
    
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="info")