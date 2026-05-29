# ai/infrastructure/redis_client.py
"""
Redis client cho Conversation Memory persistence.

Key pattern : conv_history:{session_id}
Value       : JSON array of serialized LangChain messages
TTL         : redis_conversation_ttl (default 3600s = 1 giờ)

Fallback: Nếu REDIS_URL không được set, mọi thao tác là no-op —
          dev local không cần cài Redis vẫn chạy được.
"""
import json
import logging
from typing import List

from langchain_core.messages import BaseMessage, messages_from_dict, messages_to_dict

from ai.infrastructure.config import settings

logger = logging.getLogger(__name__)

# ── Singleton Redis connection ────────────────────────────────────────────────
_redis = None
_redis_available: bool | None = None  # None = chưa kiểm tra, True/False = kết quả


async def _get_redis():
    """Trả về Redis client singleton. Trả về None nếu không cấu hình hoặc không kết nối được."""
    global _redis, _redis_available

    # Đã biết là không available → trả None luôn
    if _redis_available is False:
        return None

    # Đã có client → trả về
    if _redis is not None:
        return _redis

    # Lần đầu khởi tạo
    if not settings.redis_url:
        logger.info("📭 REDIS_URL không được cấu hình — Conversation history sẽ không được persist.")
        _redis_available = False
        return None

    try:
        import redis.asyncio as aioredis  # lazy import, tránh lỗi ImportError nếu chưa cài
        client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        # Ping để verify connection
        await client.ping()
        _redis = client
        _redis_available = True
        logger.info(f"Redis connected: {settings.redis_url}")
    except Exception as e:
        logger.warning(f"Không thể kết nối Redis ({settings.redis_url}): {e}. Sẽ dùng in-memory fallback.")
        _redis_available = False
        return None

    return _redis


# ── Public API ────────────────────────────────────────────────────────────────

async def load_history(session_id: str) -> List[BaseMessage]:
    """
    Load conversation history từ Redis cho session_id.
    Giới hạn redis_max_history messages cuối cùng.
    Trả về [] nếu Redis không available hoặc chưa có history.
    """
    r = await _get_redis()
    if r is None:
        return []

    try:
        raw = await r.get(f"conv_history:{session_id}")
        if not raw:
            return []
        data = json.loads(raw)
        messages = messages_from_dict(data)
        # Giới hạn số messages giữ lại
        max_msgs = settings.redis_max_history
        trimmed = messages[-max_msgs:] if len(messages) > max_msgs else messages
        logger.debug(f"[{session_id}] 📜 Loaded {len(trimmed)} messages from Redis.")
        return trimmed
    except Exception as e:
        logger.error(f"[{session_id}] load_history error: {e}")
        return []


async def save_history(session_id: str, messages: List[BaseMessage]) -> None:
    """
    Lưu conversation history vào Redis với TTL = redis_conversation_ttl.
    Tự động trim về redis_max_history trước khi lưu.
    No-op nếu Redis không available.
    """
    r = await _get_redis()
    if r is None:
        return

    try:
        max_msgs = settings.redis_max_history
        to_save = list(messages)[-max_msgs:] if len(messages) > max_msgs else list(messages)
        data = messages_to_dict(to_save)
        await r.set(
            f"conv_history:{session_id}",
            json.dumps(data, ensure_ascii=False),
            ex=settings.redis_conversation_ttl,
        )
        logger.debug(f"[{session_id}] Saved {len(to_save)} messages to Redis (TTL={settings.redis_conversation_ttl}s).")
    except Exception as e:
        logger.error(f"[{session_id}] save_history error: {e}")


async def clear_history(session_id: str) -> None:
    """Xóa toàn bộ conversation history cho session_id. No-op nếu Redis không available."""
    r = await _get_redis()
    if r is None:
        return

    try:
        deleted = await r.delete(f"conv_history:{session_id}")
        if deleted:
            logger.info(f"[{session_id}] Đã xóa conversation history khỏi Redis.")
    except Exception as e:
        logger.error(f"[{session_id}] clear_history error: {e}")


async def get_redis_info() -> dict:
    """Trả về thông tin Redis connection để health check."""
    r = await _get_redis()
    if r is None:
        return {"status": "unavailable", "redis_url": settings.redis_url}
    try:
        info = await r.info("server")
        return {
            "status": "ok",
            "redis_version": info.get("redis_version"),
            "redis_url": settings.redis_url,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}
