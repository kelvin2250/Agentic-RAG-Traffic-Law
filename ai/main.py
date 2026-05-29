# ai/main.py
import logging
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn

# Configure console output to support UTF-8 on Windows
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

from ai.api.v1 import router as api_v1_router
from ai.api.middleware import setup_middleware

# Thiết lập logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("ai.main")


# ═══════════════════════════════════════════════════════════════════════════
# PRE-WARM: Nạp sẵn tất cả singleton khi container startup
# Tiết kiệm ~25s cho query đầu tiên của người dùng
# ═══════════════════════════════════════════════════════════════════════════

async def _prewarm_services():
    """Nạp sẵn tất cả singleton khi container startup."""
    import time
    t_start = time.monotonic()

    # 1. Pre-warm HybridRetriever (BM25 + Qdrant + Embeddings + Cohere)
    #    → trigger load embedding model từ HuggingFace (~20-25s)
    logger.info("[1/2] Pre-warming HybridRetriever + Embedding Model...")
    try:
        from ai.tools.hybrid_search import _get_retriever
        _get_retriever()
        logger.info(f"   HybridRetriever ready ({time.monotonic() - t_start:.1f}s)")
    except Exception as e:
        logger.warning(f"   HybridRetriever pre-warm failed: {e}")
    t1 = time.monotonic()

    # 2. Pre-warm LLM singletons (chỉ verify API key, không gọi model)
    logger.info("[2/2] Pre-warming LLM singletons...")
    try:
        from ai.agents.answer_generate import _get_llm
        from ai.infrastructure.llm_router import get_llm
        from ai.infrastructure.config import settings

        _get_llm()
        get_llm(settings.orchestrator_model)
        get_llm(settings.sanction_model)
        logger.info(f"   LLM singletons ready ({time.monotonic() - t1:.1f}s)")
    except Exception as e:
        logger.warning(f"   LLM pre-warm failed: {e}")

    total = time.monotonic() - t_start
    logger.info(f"All services pre-warmed in {total:.1f}s — ready for traffic!")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: pre-warm tất cả singleton. Shutdown: cleanup."""
    logger.info("Application startup — pre-warming services...")
    await _prewarm_services()
    yield
    logger.info("Application shutdown")


# Khởi tạo FastAPI App (với lifespan để pre-warm)
app = FastAPI(
    title="Traffic Law AI Service",
    description="Microservice chạy Multi-Agent RAG hệ thống Luật Giao thông Việt Nam",
    version="1.0.0",
    lifespan=lifespan,
)

# Thiết lập CORS và Logging Middleware
setup_middleware(app)

# Đăng ký API router v1
app.include_router(api_v1_router, prefix="/api/v1")


@app.get("/")
async def root_endpoint():
    """Endpoint gốc chỉ hiển thị thông tin giới thiệu dịch vụ."""
    return {
        "service": "Vietnam Traffic Law AI Service",
        "version": "1.0.0",
        "documentation": "/docs"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint for Docker healthcheck."""
    return {"status": "healthy"}


if __name__ == "__main__":
    logger.info("Starting Traffic Law AI Service on http://0.0.0.0:8001")
    uvicorn.run("ai.main:app", host="0.0.0.0", port=8001, reload=True)
