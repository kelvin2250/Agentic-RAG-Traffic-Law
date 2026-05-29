# ai/tools/hybrid_search.py
"""
Hybrid Search Tool — BM25 + Vector (Qdrant) + Cohere Rerank.

Dùng module-level singleton để tránh khởi tạo lại HybridRetriever
(load 18K BM25 chunks + Qdrant client) mỗi request.
"""
import logging
from typing import List, Dict, Any

from ai.rag.hybrid_retrieval import HybridRetriever
from ai.infrastructure.config import settings

logger = logging.getLogger(__name__)

# ── Module-level Singleton ───────────────────────────────────────────────────
# HybridRetriever.__init__ tốn ~2-5s (load BM25 chunks + Qdrant client).
# Khởi tạo 1 lần khi module được import, tái sử dụng cho mọi request.
_retriever: HybridRetriever | None = None


def _get_retriever() -> HybridRetriever:
    """Lazy-init singleton HybridRetriever."""
    global _retriever
    if _retriever is None:
        logger.info("🔧 Khởi tạo HybridRetriever singleton (lần đầu)...")
        _retriever = HybridRetriever(settings=settings)
        logger.info("HybridRetriever sẵn sàng.")
    return _retriever


# ── Public API ───────────────────────────────────────────────────────────────

async def hybrid_search(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """
    Tìm kiếm kết hợp BM25 + Vector + Cohere Rerank trên local KB.

    Args:
        query:  Câu truy vấn pháp lý (nên đã qua rewrite_query để tối ưu thuật ngữ).
        top_k:  Số lượng kết quả tối đa trả về sau rerank.

    Returns:
        List[dict] — mỗi phần tử có:
          - page_content: str   — nội dung đoạn luật
          - metadata: dict      — chunk_id, file_name, article, type, ...
          - score: float        — relevance score từ Cohere Rerank [0.0 - 1.0]
    """
    retriever = _get_retriever()

    try:
        docs = await retriever.search(query, top_k=top_k)
    except Exception as e:
        logger.error(f"HybridRetriever.search() thất bại: {e}", exc_info=True)
        return []

    if not docs:
        logger.info(f"Local KB không tìm thấy kết quả cho: '{query[:60]}'")
        return []

    # Chuẩn hóa sang List[dict] — loại bỏ LangChain Document object
    results: list[dict] = []
    for doc in docs:
        meta = doc.metadata or {}
        score = meta.get("score") or meta.get("relevance_score", 0.0)
        results.append({
            "page_content": doc.page_content,
            "metadata": meta,
            "score": float(score),
        })

    logger.debug(
        f"hybrid_search: '{query[:50]}' → {len(results)} docs "
        f"(top score: {results[0]['score']:.4f})"
    )
    return results