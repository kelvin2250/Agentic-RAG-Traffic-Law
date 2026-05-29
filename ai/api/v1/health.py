# ai/api/v1/health.py
import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException
from qdrant_client import QdrantClient
from ai.infrastructure.config import settings

logger = logging.getLogger("ai.api.health")
router = APIRouter()

@router.get("/health")
async def health_check():
    """
    Kiểm tra trạng thái hoạt động của hệ thống (Qdrant & LLM Config).
    """
    health_status = {
        "status": "healthy",
        "qdrant": {"status": "unknown"},
        "llm": {
            "gemini": "not_configured",
            "deepseek": "not_configured",
            "cohere": "not_configured"
        }
    }
    
    # 1. Kiểm tra Qdrant
    try:
        if settings.qdrant_url:
            client = QdrantClient(url=settings.qdrant_url, timeout=5.0)
            collections_res = client.get_collections()
            collections = [c.name for c in collections_res.collections]
            
            if settings.qdrant_collection in collections:
                health_status["qdrant"] = {
                    "status": "connected",
                    "url": settings.qdrant_url,
                    "collection": settings.qdrant_collection,
                    "available_collections": collections
                }
            else:
                health_status["qdrant"] = {
                    "status": "warning",
                    "url": settings.qdrant_url,
                    "message": f"Collection '{settings.qdrant_collection}' not found in Qdrant.",
                    "available_collections": collections
                }
        else:
            qdrant_path = Path(settings.qdrant_path)
            if not qdrant_path.exists():
                health_status["qdrant"] = {
                    "status": "error",
                    "message": f"Qdrant path not found: {settings.qdrant_path}"
                }
                health_status["status"] = "unhealthy"
            else:
                client = QdrantClient(path=str(qdrant_path), read_only=True)
                collections_res = client.get_collections()
                collections = [c.name for c in collections_res.collections]
                
                if settings.qdrant_collection in collections:
                    health_status["qdrant"] = {
                        "status": "connected",
                        "collection": settings.qdrant_collection,
                        "available_collections": collections
                    }
                else:
                    health_status["qdrant"] = {
                        "status": "warning",
                        "message": f"Collection '{settings.qdrant_collection}' not found in Qdrant.",
                        "available_collections": collections
                    }
    except Exception as e:
        logger.error(f"Error checking Qdrant health: {e}", exc_info=True)
        health_status["qdrant"] = {
            "status": "error",
            "message": str(e)
        }
        health_status["status"] = "unhealthy"

    # 2. Kiểm tra cấu hình API Keys của LLM
    if settings.google_api_key and not settings.google_api_key.startswith("your-"):
        health_status["llm"]["gemini"] = "configured"
    if settings.deepseek_api_key and not settings.deepseek_api_key.startswith("your-"):
        health_status["llm"]["deepseek"] = "configured"
    if settings.cohere_api_key and not settings.cohere_api_key.startswith("your-"):
        health_status["llm"]["cohere"] = "configured"

    # Trả về kết quả hoặc lỗi 500 nếu hệ thống hỏng
    if health_status["status"] == "unhealthy":
        raise HTTPException(status_code=500, detail=health_status)
        
    return health_status
