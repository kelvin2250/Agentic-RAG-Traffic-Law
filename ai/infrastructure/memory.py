import json
import logging
from typing import List, Optional, Tuple
from dataclasses import dataclass, field, asdict

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_core.language_models import BaseChatModel

from ai.infrastructure.config import settings
from ai.infrastructure.llm_router import get_llm

logger = logging.getLogger(__name__)

KEEP_RAW = 5


@dataclass
class MemoryBlob:
    """Serializable memory payload stored in Redis."""
    summary: str = ""
    recent_messages: list = field(default_factory=list)
    total_count: int = 0


class ConversationMemory:
    """
    Hierarchical conversation memory with Redis persistence.
    
    - Keeps last N messages raw.
    - Compresses older messages via LLM summarization.
    - Fallbacks to in-memory dict if Redis unavailable (with safe protection).
    """
    
    def __init__(
        self,
        redis_url: Optional[str] = None,
        ttl: int = 3600,
        keep_raw: int = KEEP_RAW,
        token_threshold: int = 4000,
        summarizer: Optional[BaseChatModel] = None,
        domain_context: str = "luật giao thông đường bộ Việt Nam"
    ):
        self._redis_url = redis_url or settings.redis_url
        self._ttl = ttl
        self._keep_raw = keep_raw
        self._token_threshold = token_threshold
        self._summarizer = summarizer  # Dễ dàng inject mock model khi test
        self._domain_context = domain_context
        self._redis = None
        self._redis_ok: Optional[bool] = None
        
        # Bổ sung giới hạn cho fallback để tránh nguy cơ sập RAM (Memory Leak)
        self._fallback: dict[str, MemoryBlob] = {}
        self._max_fallback_size = 1000 
    
    # ── Redis connection (lazy) ──────────────────────────────────────────
    
    async def _redis_client(self):
        """Lazy-init Redis client. Returns None if unavailable."""
        if self._redis_ok is False:
            return None
        if self._redis is not None:
            return self._redis
        if not self._redis_url:
            self._redis_ok = False
            return None
        try:
            import redis.asyncio as aioredis
            client = aioredis.from_url(
                self._redis_url, decode_responses=True,
                socket_connect_timeout=2
            )
            await client.ping()
            self._redis = client
            self._redis_ok = True
        except Exception as e:
            logger.warning(f"Redis unavailable, switching to safe fallback store: {e}")
            self._redis_ok = False
            return None
        return self._redis

    # ── Token Counting ──────────────────────────────────────────────────
    
    @staticmethod
    def _count_tokens(text: str, model_name: str = "cl100k_base") -> int:
        """Estimate token count for a text snippet."""
        try:
            import tiktoken
            encoding = tiktoken.get_encoding(model_name)
            return len(encoding.encode(text))
        except Exception:
            # Fallback thô: trung bình ~4 ký tự cho 1 token tiếng Việt
            return len(text) // 4

    def _estimate_total_tokens(self, messages: List[BaseMessage], summary: str = "") -> int:
        """Estimate total tokens of current messages and existing summary."""
        total = self._count_tokens(summary)
        for m in messages:
            total += self._count_tokens(m.content)
        return total
    
    # ── Summarization ───────────────────────────────────────────────────
    
    async def _summarize(self, messages: List[BaseMessage], existing_summary: str = "") -> str:
        """Compress old messages via LLM."""
        if not messages and not existing_summary:
            return ""
        
        lines = [f"{'User' if isinstance(m, HumanMessage) else 'Assistant'}: {m.content}"
                 for m in messages]
        history_text = "\n".join(lines)
        
        prompt = (
            f"Tóm tắt lịch sử hội thoại về {self._domain_context}.\n\n"
            f"{f'Tóm tắt hiện tại: {existing_summary}' if existing_summary else ''}\n\n"
            f"Tin nhắn mới:\n{history_text}\n\n"
            f"Yêu cầu: Giữ lại các thông tin quan trọng về pháp luật giao thông đường bộ mà người dùng đã hỏi"
        )
        
        try:
            llm = self._summarizer or get_llm(settings.deepseek_model_default)
            resp = await llm.ainvoke([{"role": "user", "content": prompt}])
            return resp.content.strip()
        except Exception as e:
            logger.error(f"LLM Summarization failed: {e}")
            return existing_summary  # Trả về summary cũ nếu gọi LLM lỗi để tránh sập luồng chat
    
    # ── Public API ───────────────────────────────────────────────────────
    
    async def load(self, session_id: str) -> Tuple[str, List[BaseMessage]]:
        """
        Load memory for session.
        Returns: (summary_text, recent_raw_messages)
        """
        r = await self._redis_client()
        if r is not None:
            try:
                raw = await r.get(f"conv:{session_id}")
                if raw:
                    data = json.loads(raw)
                    # Khởi tạo an toàn tránh lỗi nếu thiếu key trong JSON
                    blob = MemoryBlob(
                        summary=data.get("summary", ""),
                        recent_messages=data.get("recent_messages", []),
                        total_count=data.get("total_count", 0)
                    )
                    recent = self._deserialize(blob.recent_messages)
                    return blob.summary, recent
            except Exception as e:
                logger.error(f"Load memory from Redis error: {e}")
        
        # Fallback an toàn sang RAM dict
        blob = self._fallback.get(session_id, MemoryBlob())
        return blob.summary, self._deserialize(blob.recent_messages)
    
    async def save(self, session_id: str, all_messages: List[BaseMessage]) -> None:
        """
        Save memory with hierarchical strategy.
        
        Always persists to Redis (primary store).
        Fallback only used if Redis unavailable (temporary).
        """
        existing_summary = ""
        
        # Lấy summary hiện tại từ Redis (nếu có)
        r = await self._redis_client()
        if r is not None:
            try:
                raw = await r.get(f"conv:{session_id}")
                if raw:
                    existing_summary = json.loads(raw).get("summary", "")
            except Exception as e:
                logger.error(f"Failed to fetch existing summary from Redis: {e}")
        
        # Kiểm tra ngưỡng Token để decide khi nào gọi LLM summarization
        total_tokens = self._estimate_total_tokens(all_messages, existing_summary)
        
        # Chỉ gọi LLM summarize khi CÙNG LÚC:
        # 1. Tổng token vượt ngưỡng
        # 2. Số lượng message vượt keep_raw (có tin nhắn cũ cần nén)
        if total_tokens > self._token_threshold and len(all_messages) > self._keep_raw:
            old = all_messages[:-self._keep_raw]
            recent = all_messages[-self._keep_raw:]
            
            logger.info(f"[{session_id}] Context tokens ({total_tokens}) exceeded threshold ({self._token_threshold}). Summarizing {len(old)} old messages...")
            summary = await self._summarize(old, existing_summary)
            blob = MemoryBlob(
                summary=summary,
                recent_messages=self._serialize(recent),
                total_count=len(all_messages),
            )
        else:
            # Dưới threshold: giữ nguyên summary cũ, lưu tất cả messages
            blob = MemoryBlob(
                summary=existing_summary,
                recent_messages=self._serialize(all_messages),
                total_count=len(all_messages),
            )
        
        # ── PRIMARY: Persist vào Redis ────────────────────────────────────
        if r is not None:
            try:
                payload = json.dumps(asdict(blob), ensure_ascii=False)
                await r.set(f"conv:{session_id}", payload, ex=self._ttl)
                logger.debug(f"[{session_id}] Memory saved to Redis: {len(all_messages)} messages, summary_len={len(existing_summary)}")
                return
            except Exception as e:
                logger.error(f"Failed to save to Redis, falling back to RAM: {e}")
        
        # ── FALLBACK: Lưu vào in-memory dict nếu Redis không có ────────────
        # Bảo vệ RAM: xóa bớt entry cũ nếu fallback dict quá lớn
        if len(self._fallback) >= self._max_fallback_size and session_id not in self._fallback:
            first_key = next(iter(self._fallback))
            self._fallback.pop(first_key, None)
            logger.warning(f"Fallback store full, evicted oldest session: {first_key}")
            
        self._fallback[session_id] = blob
        logger.warning(f"[{session_id}] Memory saved to fallback (RAM only, not persistent)")
    
    async def clear(self, session_id: str) -> None:
        """Delete memory for session."""
        r = await self._redis_client()
        if r is not None:
            try:
                await r.delete(f"conv:{session_id}")
            except Exception as e:
                logger.error(f"Failed to delete key from Redis: {e}")
        self._fallback.pop(session_id, None)
    
    # ── Serialization helpers ───────────────────────────────────────────
    
    @staticmethod
    def _serialize(msgs: List[BaseMessage]) -> list:
        return [{"role": "user" if isinstance(m, HumanMessage) else "assistant",
                 "content": m.content} for m in msgs]
    
    @staticmethod
    def _deserialize(data: list) -> List[BaseMessage]:
        if not data:
            return []
        return [
            HumanMessage(content=m["content"]) if m["role"] == "user"
            else AIMessage(content=m["content"])
            for m in data
        ]


# Singleton instance
memory = ConversationMemory()
