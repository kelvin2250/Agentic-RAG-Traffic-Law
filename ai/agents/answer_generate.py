# ai/agents/answer_generate.py
"""
Answer Generate Node.

Role: FORMATTER only.
- Nhan du lieu da phan tich hoan chinh tu Analyst + Sanction + Validator.
- Trinh bay lai thanh cau tra loi Markdown ro rang.
- KHONG suy luan them, KHONG gia dinh them.
"""
import json
import logging
import asyncio
from typing import Any, Dict, Optional

from ai.agents.state import AgentState
from ai.infrastructure.llm_router import get_llm
from ai.infrastructure.config import settings

logger = logging.getLogger(__name__)

# ═══ Module-level stream queue: set từ API endpoint, read từ answer_generate ═══
_stream_queue: Optional[asyncio.Queue] = None

def set_stream_queue(queue: Optional[asyncio.Queue]):
    """Set stream queue từ API endpoint trước khi invoke graph."""
    global _stream_queue
    _stream_queue = queue


# ──────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPT -- ngan gon, chi dinh vai tro formatter
# ──────────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
Ban la tro ly phap luat giao thong duong bo Viet Nam.
Nhiem vu: Nhan du lieu phan tich da hoan chinh va trinh bay lai thanh cau tra loi Markdown.

Quy tac:
- KHONG suy luan them, KHONG bia them thong tin ngoai du lieu duoc cung cap.
- KHONG tu y them cac canh bao (warning/disclaimer) ve tinh day du hay chinh xac cua du lieu. 
  Chi them canh bao khi trong input co tag [DISCLAIMER: ...] tuong ung.
- Neu co tag [DISCLAIMER: citation-mismatch]: them blockquote canh bao o dau phan hoi.
- Neu co tag [DISCLAIMER: web-source]: them blockquote canh bao nguon internet.
- Dung Markdown: section Ket luan / Che tai (neu co) / Co so Phap ly.
- Ngan gon, suc tich, khong lap lai.
"""


# ──────────────────────────────────────────────────────────────────────────
# LLM SINGLETON
# ──────────────────────────────────────────────────────────────────────────

_llm = None


def _get_llm():
    global _llm
    if _llm is None:
        # Sử dụng model từ config (mặc định: gemini-2.0-flash để text generation nhanh)
        model_name = getattr(settings, 'answer_generate_model', 'gemini-2.0-flash')
        _llm = get_llm(model_name)
        logger.info(f"Answer Generate LLM initialized with model: {model_name}")
    return _llm


# ──────────────────────────────────────────────────────────────────────────
# NODE FUNCTION
# ──────────────────────────────────────────────────────────────────────────

async def answer_generate_node(state: AgentState) -> Dict[str, Any]:
    """
    LangGraph Node: format ket qua phan tich thanh phan hoi cuoi cung.

    Input:
        state["user_query"], state["extracted_facts"], state["legal_analysis"],
        state["sanction_details"], state["validation_report"],
        state["retrieval_source"], state["retrieved_docs"]
    Output:
        state["final_response"]
    """
    session_id = state.get("session_id", "N/A")

    # ── Early-return guard: không có worker nào chạy → fallback ngắn gọn ──
    intents = state.get("detailed_intents", [])
    if not intents:
        old_intent = state.get("detailed_intent", "NONE")
        if old_intent and old_intent != "NONE":
            intents = [old_intent]

    has_worker_data = bool(
        state.get("extracted_facts") or state.get("sanction_details") or state.get("admin_procedure_details")
    )
    has_valid_intent = any(i in ("BEHAVIOR_ANALYSIS", "PENALTY_LOOKUP", "ADMIN_PROCEDURE") for i in intents)
    if not has_worker_data and not has_valid_intent:
        user_query = state.get("user_query", "")
        logger.info(f"[{session_id}] Synthesizer early-return: không có worker data cho các intents {intents}")
        return {
            "final_response": (
                "Tôi không thể xử lý yêu cầu này do không xác định được loại câu hỏi. "
                "Vui lòng đặt lại câu hỏi rõ ràng hơn về một trong các lĩnh vực:\n\n"
                "1️⃣ **Phân tích tình huống giao thông** — Hỏi về tình huống bạn gặp phải.\n"
                "2️⃣ **Tra cứu mức phạt** — Hỏi về mức phạt, điểm trừ của một lỗi cụ thể.\n"
                "3️⃣ **Thủ tục hành chính** — Hỏi về đăng ký xe, đổi bằng lái, giấy tờ.\n\n"
                f"*📝 Câu hỏi của bạn: {user_query[:200]}*"
            ),
        }

    logger.info(f"[{session_id}] answer_generate_node: bat dau format phan hoi...")

    user_query      = state.get("user_query", "")
    sub_queries     = state.get("sub_queries", [user_query])
    conversation_history = state.get("conversation_history", [])
    extracted_facts = state.get("extracted_facts", {})
    legal_analysis  = state.get("legal_analysis", "")
    sanction_details = state.get("sanction_details", {})
    admin_procedure_details = state.get("admin_procedure_details", {})
    validation_report = state.get("validation_report", {})
    retrieval_source = state.get("retrieval_source", "local")
    retrieved_docs  = state.get("retrieved_docs", [])

    # Disclaimer flags — chỉ hiển thị khi thực sự có vấn đề về dữ liệu,
    # không hiển thị khi sanction agent gặp lỗi nội bộ (đã có retry/failover)
    disclaimer_parts = []
    
    # Chỉ gắn disclaimer citation-mismatch khi có sanction_details nhưng thiếu citations
    # (tức là dữ liệu có nhưng không trích xuất được căn cứ pháp lý)
    if validation_report.get("disclaimer_needed", False):
        sanction_violations = sanction_details.get("violations", []) if sanction_details else []
        # Nếu sanction_details có violations (đã trích xuất thành công) nhưng vẫn thiếu citations
        if sanction_violations:
            disclaimer_parts.append("citation-mismatch")
    
    if retrieval_source in ("web", "hybrid"):
        disclaimer_parts.append("web-source")
    
    disclaimer_tag = (
        f"[DISCLAIMER: {', '.join(disclaimer_parts)}]"
        if disclaimer_parts else ""
    )

    # Top-3 doc snippets
    doc_snippets = "\n".join(
        f"- [{doc.get('metadata', {}).get('source', 'N/A')}] "
        f"{doc.get('page_content', '')[:300]}"
        for doc in retrieved_docs[:3]
    ) or "(Khong co tai lieu)"

    # User message: inject data, LLM chi format
    user_msg_parts = [
        "## Cau hoi nguoi dung",
        f"{user_query}\n"
    ]

    # ── Conversation context: de LLM hieu ngu canh hoi thoai ──
    if conversation_history and len(conversation_history) > 0:
        recent = list(conversation_history)[-4:]  # last 2 turns
        user_msg_parts.append("## Ngu canh hoi thoai gan day")
        for msg in recent:
            role = "Nguoi dung" if getattr(msg, "type", "") == "human" else "Tro ly"
            user_msg_parts.append(f"{role}: {msg.content}")
        user_msg_parts.append("")

    # ── Sub-query da rewrite (chinh xac hon user_query goc) ──
    if sub_queries and len(sub_queries) > 0:
        user_msg_parts.append(f"## Cau hoi da duoc lam ro\n{sub_queries[0]}\n")

    if extracted_facts:
        user_msg_parts.append(f"## Ket qua Analyst\n{json.dumps(extracted_facts, ensure_ascii=False, indent=2)}\n")

    if legal_analysis:
        user_msg_parts.append(f"Lap luan:\n{legal_analysis}\n")

    if sanction_details and sanction_details.get("violations"): # Hoặc điều kiện check data thực tế của bạn
        user_msg_parts.append(f"## Ket qua Sanction\n{json.dumps(sanction_details, ensure_ascii=False, indent=2)}\n")

    if admin_procedure_details:
        user_msg_parts.append(f"## Ket qua Thu tuc Hanh chinh\n{json.dumps(admin_procedure_details, ensure_ascii=False, indent=2)}\n")

    user_msg_parts.append(f"## Tai lieu phap ly (top-3)\n{doc_snippets}\n")

    if disclaimer_tag:
        user_msg_parts.append(disclaimer_tag)

    user_msg = "\n".join(user_msg_parts)

    try:
        llm = _get_llm()
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ]
        
        # ═══ STREAMING MODE: dùng module-level _stream_queue ═══
        if _stream_queue is not None:
            full_text = ""
            async for chunk in llm.astream(messages):
                content = chunk.content if hasattr(chunk, "content") else str(chunk)
                full_text += content
                await _stream_queue.put({"token": content})
            await _stream_queue.put({"done": True})
            logger.info(f"[{session_id}] answer_generate_node: stream hoan thanh ({len(full_text)} chars).")
            return {"final_response": full_text}
        
        # Non-streaming mode (default)
        response = await llm.ainvoke(messages)
        final_text = response.content
        logger.info(f"[{session_id}] answer_generate_node: hoan thanh.")
        return {"final_response": final_text}

    except Exception as e:
        logger.error(f"[{session_id}] answer_generate_node error: {e}", exc_info=True)
        fallback = (
            "**He thong gap su co khi bien tap cau tra loi.**\n\n"
            f"Tom tat: {legal_analysis[:300] if legal_analysis else '(trong)'}\n\n"
            f"Muc phat: {sanction_details.get('total_fine_min', 0):,}"
            f" - {sanction_details.get('total_fine_max', 0):,} VND\n\n"
        )
        return {
            "final_response": fallback,
            "errors": [f"answer_generate_error: {str(e)}"],
        }
