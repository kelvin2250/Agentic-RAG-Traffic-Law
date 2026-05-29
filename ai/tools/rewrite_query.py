# ai/tools/rewrite_query.py
"""
Query Rewrite Tool — Chuyển ngôn ngữ đời thường sang ngôn ngữ pháp lý chuẩn xác.

Phiên bản đơn giản hóa, độc lập và không phụ thuộc vào phân loại intent.
"""
import logging

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from ai.infrastructure.config import settings
from ai.infrastructure.llm_router import get_llm

logger = logging.getLogger(__name__)


# ── Generic Legal Prompt ─────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
Bạn là chuyên gia pháp lý chuyên sâu về Luật Giao thông Đường bộ Việt Nam.

Nhiệm vụ: Chuyển đổi câu truy vấn ngôn ngữ đời thường thành ngôn ngữ pháp lý \
chuẩn xác để tìm kiếm hiệu quả trong cơ sở dữ liệu luật (văn bản quy phạm pháp luật hiện hành).

Quy tắc bắt buộc:
1. Giữ nguyên ý nghĩa cốt lõi — KHÔNG thêm thông tin không có trong query gốc.
2. Thay từ ngữ đời thường bằng thuật ngữ pháp lý tương đương, ví dụ:
   - "vượt đèn đỏ"    → "không chấp hành hiệu lệnh đèn tín hiệu giao thông"
   - "bị giữ xe"      → "tạm giữ phương tiện vi phạm hành chính"
   - "trừ điểm bằng"  → "trừ điểm giấy phép lái xe"
   - "đăng kiểm xe"   → "kiểm định an toàn kỹ thuật và bảo vệ môi trường"
   - "chở 3"          → "chở người vượt quy định cho phép"
3. CHỈ trả về câu truy vấn đã tối ưu — không giải thích, không dấu ngoặc kép.

Query gốc: {query}
Câu truy vấn pháp lý tối ưu:\
"""


# ── Public API ───────────────────────────────────────────────────────────────

async def rewrite_query(original_query: str) -> str:
    """
    Chuyển đổi ngôn ngữ đời thường thành ngôn ngữ pháp lý chuẩn xác.

    Phiên bản không phụ thuộc intent, tối ưu hóa query tổng quát để phục vụ 
    cho việc hybrid search trong cơ sở dữ liệu pháp luật.

    Args:
        original_query: Câu hỏi gốc từ người dùng.

    Returns:
        Câu truy vấn pháp lý tối ưu (hoặc query gốc nếu LLM call thất bại).
    """
    llm = get_llm("gemini-2.0-flash")  # Gemini nhanh hơn cho task đơn giản
    prompt = ChatPromptTemplate.from_template(_SYSTEM_PROMPT)
    chain = prompt | llm | StrOutputParser()

    try:
        rewritten = await chain.ainvoke({
            "query": original_query,
        })
        result = rewritten.strip()
        logger.info(
            f"Rewrite (Generic): '{original_query[:50]}' → '{result[:80]}'"
        )
        return result

    except Exception as e:
        # Graceful fallback — không làm gián đoạn luồng Graph
        logger.warning(f"rewrite_query thất bại, dùng query gốc: {e}")
        return original_query