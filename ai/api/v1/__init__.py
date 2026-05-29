# ai/api/v1/__init__.py
from fastapi import APIRouter
from ai.api.v1.chat import router as chat_router
from ai.api.v1.health import router as health_router

router = APIRouter()
router.include_router(health_router, prefix="", tags=["System"])
router.include_router(chat_router, prefix="", tags=["Conversations"])
