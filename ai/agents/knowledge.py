# ai/agents/knowledge.py
"""
Knowledge Agent — "Law Librarian" của hệ thống.

Nhiệm vụ:
  1. Rewrite query sang ngôn ngữ pháp lý (intent-aware)
  2. Hybrid Search trên local KB (BM25 + Vector + Cohere Rerank)
  3. Score Gatekeeper: nếu local score < threshold → fallback Web Search
  4. Tích lũy (accumulate) docs vào State — không ghi đè giữa các sub-queries

Thiết kế quan trọng:
  - Xử lý cuốn chiếu (sequential) từng sub-query qua `current_query_idx`
  - Dedup qua merge_docs reducer trong State (không cần dedup thủ công)
  - Advance `current_query_idx` sau mỗi lượt để Graph tự loop nếu còn sub-queries
  - Web fallback chỉ kích hoạt lần đầu (retry_count = 0) để tránh gọi web lặp
"""
import logging
from typing import Any, Dict

from ai.agents.state import AgentState
from ai.infrastructure.config import settings
from ai.tools.hybrid_search import hybrid_search
from ai.tools.rewrite_query import rewrite_query
from ai.tools.web_search import web_search

logger = logging.getLogger(__name__)


async def knowledge_node(state: AgentState) -> Dict[str, Any]:
    """
    LangGraph Node — Retrieval & Fallback.

    Input  : state["sub_queries"], state["current_query_idx"],
             state["detailed_intent"], state["retry_count"]
    Output : retrieved_docs (accumulated), retrieval_source, confidence_score,
             rewritten_query, current_query_idx (incremented)
    """
    session_id = state.get("session_id", "N/A")

    # ── 1. Xác định sub-query đang xử lý trong lượt này ─────────────────────
    sub_queries: list = state.get("sub_queries", [])
    current_idx: int = state.get("current_query_idx", 0)
    retry_count: int = state.get("retry_count", 0)
    detailed_intent: str = state.get("detailed_intent", "NONE")
    knowledge_loop_count: int = state.get("knowledge_loop_count", 0)

    if sub_queries and current_idx < len(sub_queries):
        active_query = sub_queries[current_idx]
        logger.info(
            f"[{session_id}] Knowledge [{current_idx + 1}/{len(sub_queries)}]: "
            f"'{active_query[:70]}'"
        )
    else:
        # Fallback khi sub_queries rỗng (không nên xảy ra nếu Orchestrator đúng)
        active_query = state.get("user_query", "")
        logger.info(f"[{session_id}] Knowledge (query đơn): '{active_query[:70]}'")

    if not active_query:
        logger.error(f"[{session_id}] active_query rỗng — bỏ qua knowledge node.")
        return {
            "retrieval_source": "error",
            "confidence_score": 0.0,
            "current_query_idx": current_idx + 1,
            "knowledge_loop_count": knowledge_loop_count + 1,
            "errors": ["knowledge_error: active_query rỗng"],
        }

    try:
        # ── 2. Nới top_k khi retry (Validator yêu cầu thêm context) ──────────
        top_k = settings.knowledge_top_k
        if retry_count > 0:
            top_k += 2
            logger.info(f"[{session_id}] Retry #{retry_count} — mở rộng top_k={top_k}")

        # ── 3. Rewrite query → ngôn ngữ pháp lý ────────────────────────────────
        rewritten = await rewrite_query(active_query)

        # ── 4. Hybrid Search trên local KB ───────────────────────────────────
        logger.info(f"[{session_id}] Hybrid Search: '{rewritten[:70]}'")
        local_docs: list[dict] = await hybrid_search(rewritten, top_k=top_k)

        # Gắn sub_query index để downstream agents biết doc thuộc câu hỏi nào
        for doc in local_docs:
            doc["associated_sub_query_idx"] = current_idx

        # ── 5. Score Gatekeeper ───────────────────────────────────────────────
        max_score = max((d["score"] for d in local_docs), default=0.0)
        threshold = settings.score_threshold

        retrieval_source = "local"
        final_docs = local_docs

        if max_score < threshold or not local_docs:
            # Chỉ fallback web khi retry_count = 0 để tránh vòng lặp tốn kém
            if retry_count == 0:
                logger.warning(
                    f"[{session_id}] Local score thấp "
                    f"({max_score:.3f} < {threshold}) — Web Search Fallback."
                )
                web_docs: list[dict] = await web_search(active_query, top_k=5)

                for doc in web_docs:
                    doc["associated_sub_query_idx"] = current_idx

                if web_docs:
                    final_docs = local_docs + web_docs
                    retrieval_source = "hybrid" if local_docs else "web"
                    web_max_score = max(d["score"] for d in web_docs)
                    max_score = max(max_score, web_max_score)
                    logger.info(
                        f"[{session_id}] Web fallback: +{len(web_docs)} docs "
                        f"(best score: {web_max_score:.3f})"
                    )
                else:
                    logger.warning(f"[{session_id}] Web search cũng trả về rỗng.")
            else:
                logger.info(
                    f"[{session_id}] ℹ️ Retry mode — bỏ qua web fallback để tránh loop."
                )

        # ── 6. Log summary ────────────────────────────────────────────────────
        logger.info(
            f"[{session_id}] Retrieval done: {len(final_docs)} docs "
            f"| source={retrieval_source} | max_score={max_score:.3f}"
        )

        # ── 7. Advance current_query_idx ──────────────────────────────────────
        # Graph sẽ kiểm tra: nếu next_idx < len(sub_queries) → loop lại Knowledge
        next_idx = current_idx + 1

        return {
            # retrieved_docs dùng merge_docs reducer → tự dedup + sort theo score
            "retrieved_docs": final_docs,
            "retrieval_source": retrieval_source,
            "confidence_score": float(max_score),
            "rewritten_query": rewritten,
            "current_query_idx": next_idx,   # ← Advance để Graph biết đã xong lượt này
            "knowledge_loop_count": knowledge_loop_count + 1,
        }

    except Exception as e:
        logger.error(
            f"[{session_id}] Knowledge Node lỗi nghành trọng: {e}",
            exc_info=True,
        )
        return {
            # Giữ lại docs đã tìm được từ các lượt trước — không xóa
            "retrieved_docs": [],
            "retrieval_source": "error",
            "confidence_score": 0.0,
            "current_query_idx": current_idx + 1,  # Vẫn advance để không bị stuck
            "knowledge_loop_count": knowledge_loop_count + 1,
            "errors": [f"knowledge_error: {str(e)}"],
        }