# ai/tools/web_search.py
"""
Web Search Fallback Tool — MCP BrightData Bridge.

Flow:
  1. SERP Search  → trusted_web_search (BrightData) → lấy top URL nhanh
  2. Scrape       → scrape_legal_page × 3 URL song song (asyncio.gather)
  3. Rerank       → reranking_documents (Cohere) qua MCP Rerank Server
"""
import asyncio
import json
import logging
from typing import List

from ai.mcp.client import get_retrieval_client, get_rerank_client
from ai.infrastructure.config import settings

logger = logging.getLogger(__name__)


async def _scrape_single_url(
    retrieval_client,
    url: str,
    title: str,
    max_chars: int,
) -> dict | None:
    """
    Scrape một URL qua MCP retrieval server.
    Trả về dict document hoặc None nếu thất bại/trống.
    """
    try:
        scrape_res = await retrieval_client.call_tool(
            "scrape_legal_page", {"url": url}
        )
        if not scrape_res or not scrape_res.content:
            return None

        raw_text = scrape_res.content[0].text if hasattr(scrape_res.content[0], "text") else ""
        content = raw_text[:max_chars].strip()

        if not content:
            logger.warning(f"Scrape trả về rỗng: {url}")
            return None

        return {
            "page_content": content,
            "metadata": {
                "source": url,
                "title": title,
                "origin": "web",
            },
            "score": 0.35,  # Default fallback score trước khi rerank
        }

    except Exception as e:
        logger.warning(f"Scrape thất bại [{url}]: {e}")
        return None


async def web_search(query: str, top_k: int = 3) -> List[dict]:
    """
    Fallback web search qua MCP Retrieval Server (port 8100) + Rerank Server (port 8200).

    Flow:
      1. SERP → lấy top URLs nhanh (BrightData search_engine)
      2. Scrape song song top N URL bằng asyncio.gather
      3. Rerank toàn bộ scraped content qua Cohere API

    Args:
        query:  Câu truy vấn gốc (ngôn ngữ người dùng — SERP hoạt động tốt hơn với ngôn ngữ tự nhiên)
        top_k:  Số kết quả tối đa trả về sau rerank

    Returns:
        List[dict] với page_content, metadata (source, title, origin), score
    """
    retrieval_client = get_retrieval_client()
    rerank_client = get_rerank_client()

    scrape_limit = settings.web_scrape_limit
    max_chars = settings.web_content_max_chars

    # ── Bước 1: SERP Search ──────────────────────────────────────────────────
    logger.info(f"[Web Search] SERP: '{query}'")
    try:
        search_res = await retrieval_client.call_tool(
            "trusted_web_search", {"query": query}
        )
        if not search_res or not search_res.content:
            logger.warning("SERP trả về response rỗng.")
            return []

        search_data: list = json.loads(search_res.content[0].text)

    except Exception as e:
        logger.error(f"SERP search thất bại: {e}")
        return []

    if not search_data:
        logger.warning("SERP không tìm thấy kết quả nào.")
        return []

    top_items = search_data[:scrape_limit]
    logger.info(
        f"📋 SERP: {len(search_data)} kết quả → scrape song song {len(top_items)} URL"
    )

    # ── Bước 2: Scrape song song ─────────────────────────────────────────────
    scrape_tasks = [
        _scrape_single_url(retrieval_client, item["link"], item.get("title", ""), max_chars)
        for item in top_items
    ]
    raw_results = await asyncio.gather(*scrape_tasks, return_exceptions=True)

    # Lọc None và exception, chỉ giữ dict hợp lệ
    docs: list[dict] = [
        r for r in raw_results
        if isinstance(r, dict) and r is not None
    ]

    if not docs:
        logger.warning("Không scrape được nội dung nào từ các URL SERP.")
        return []

    logger.info(f"📥 Scrape thành công: {len(docs)}/{len(top_items)} trang.")

    # ── Bước 3: Rerank ───────────────────────────────────────────────────────
    # Rerank chỉ có ý nghĩa khi có >= 2 documents để so sánh
    if len(docs) < 2:
        logger.info("Chỉ có 1 document — bỏ qua rerank.")
        return docs[:top_k]

    logger.info(f"🧬 Rerank {len(docs)} documents qua Cohere (port 8200)...")
    try:
        documents_text = [d["page_content"] for d in docs]
        rerank_res = await rerank_client.call_tool(
            "reranking_documents",
            {
                "query": query,
                "documents": documents_text,
                "top_n": min(top_k, len(docs)),
            },
        )

        if not rerank_res or not rerank_res.content:
            raise ValueError("Rerank server trả về response rỗng")

        ranked_data: list = json.loads(rerank_res.content[0].text)

        # Ánh xạ score Cohere trở lại docs gốc (giữ nguyên metadata)
        reranked: list[dict] = []
        for item in ranked_data:
            original_doc = docs[item["index"]].copy()
            original_doc["score"] = float(item["score"])
            reranked.append(original_doc)

        if reranked:
            logger.info(
                f"Rerank xong. Top score: {reranked[0]['score']:.4f} "
                f"| Source: {reranked[0]['metadata'].get('source', 'N/A')}"
            )

        return reranked

    except Exception as e:
        logger.warning(f"Rerank thất bại — dùng thứ tự SERP gốc: {e}")
        return docs[:top_k]
