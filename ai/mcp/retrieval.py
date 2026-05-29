import os
import json
import logging
import argparse
from dotenv import load_dotenv

# Thư viện xử lý văn bản & sinh mã nhúng
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings

# Thư viện hạ tầng MCP & Starlette
from mcp.server.fastmcp import FastMCP
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import Response

# Giả định client nội bộ của bạn
from .brightdata import BrightDataClient

# 0. Cấu hình Logging & Biến môi trường
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
load_dotenv()

# 1. Khởi tạo FastMCP Server chuyên dụng
mcp = FastMCP("RetrievalOrchestrator")

# 2. Khởi tạo tài nguyên nội bộ
BRIGHTDATA_TOKEN = os.getenv("BRIGHTDATA_TOKEN")
bd_client = BrightDataClient(token=BRIGHTDATA_TOKEN, pro=True)
TRUSTED_DOMAINS = ["thuvienphapluat.vn", "bocongan.gov.vn"]

logger.info("⏳ Loading local embedding model...")
embeddings_model = HuggingFaceEmbeddings(
    model_name="huyydangg/DEk21_hcmute_embedding",
    model_kwargs={'device': 'cpu'},
    encode_kwargs={'normalize_embeddings': True}
)

# 3. Định nghĩa các công cụ phục vụ cho Gateway Tra cứu
@mcp.tool()
async def trusted_web_search(query: str) -> str:
    """Tìm kiếm thông tin pháp luật giao thông bảo mật trên các trang tin chính thống."""
    results = await bd_client.search_web(query=query, domains=TRUSTED_DOMAINS)
    return json.dumps(results, ensure_ascii=False)

@mcp.tool()
async def scrape_legal_page(url: str) -> str:
    """Cào toàn bộ nội dung văn bản của một trang web pháp luật và trả về dạng Markdown sạch."""
    return await bd_client.scrape_url(target_url=url)

@mcp.tool()
def retrieval_chunking(text: str, chunk_size: int = 500) -> str:
    """Cắt nhỏ văn bản luật dài thành các đoạn nhỏ và sinh mã nhúng vector."""
    if not text.strip():
        return json.dumps([])
        
    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=50)
    chunks = splitter.split_text(text)
    vectors = embeddings_model.embed_documents(chunks)
    
    output = [
        {"chunk_id": idx, "content": chunk, "embedding": vector}
        for idx, (chunk, vector) in enumerate(zip(chunks, vectors))
    ]
    return json.dumps(output, ensure_ascii=False)


# 4. Học tập 100% cấu trúc Server từ file chạy thành công của bạn
# Sử dụng chính xác hậu tố đường dẫn mong muốn của bạn làm prefix cho session query
sse = SseServerTransport("/mcp/messages/")

async def handle_sse(request):
    # Sử dụng chính xác request.scope, request.receive và ẩn số request._send giống file mẫu
    # SSE data được gửi trực tiếp qua request._send bên trong connect_sse context.
    # Bắt buộc return Response() để Starlette routing không bị crash (NoneType not callable).
    async with sse.connect_sse(
        request.scope, request.receive, request._send
    ) as streams:
        await mcp._mcp_server.run(
            streams[0], streams[1], mcp._mcp_server.create_initialization_options()
        )
    return Response()

# Khởi tạo Starlette App
# Lưu ý: handle_post_message là raw ASGI app (tự gọi send) → dùng Mount thay vì Route
# handle_sse cũng là long-lived SSE connection, không trả về Response
app = Starlette(
    routes=[
        Route("/mcp/sse", endpoint=handle_sse),
        Mount("/mcp/messages/", app=sse.handle_post_message),
    ]
)


if __name__ == "__main__":
    import uvicorn
    
    parser = argparse.ArgumentParser(description="Retrieval Orchestrator MCP Server")
    parser.add_argument("--port", type=int, default=8100)
    args = parser.parse_args()
    
    logger.info(f"MCP Server chuẩn ASGI (Starlette Pattern) đã sẵn sàng hoạt động!")
    logger.info(f"Endpoint SSE: http://localhost:{args.port}/mcp/sse")
    logger.info(f"Endpoint Messages: http://localhost:{args.port}/mcp/messages/")
    
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="info")