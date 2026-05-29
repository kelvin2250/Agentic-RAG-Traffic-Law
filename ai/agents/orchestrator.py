# ai/agents/orchestrator.py
"""
Orchestrator Agent — "Managing Partner" của hệ thống Pháp luật Giao thông.

Nhiệm vụ:
  1. Phân loại Intent 2-layer (primary → detailed)
  2. Bẻ tách câu hỏi phức hợp thành sub-queries độc lập
  3. Xây dựng routing_plan động cho từng loại intent
  4. Short-circuit GENERAL_CHAT / OUT_OF_SCOPE không cần qua Knowledge Agent

Kỹ thuật:
  - Dùng LangChain với ChatGoogleGenerativeAI
  - Module-level singleton model — không khởi tạo lại mỗi request
  - Async với ainvoke()
  - Truyền conversation context vào prompt để hiểu ngữ cảnh hội thoại
  - with_structured_output() cho Pydantic schema
"""
import asyncio
import logging
from typing import Any, Dict, Optional

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage

from ai.agents.state import AgentState
from ai.schemas.common import OrchestratorJSONOutput
from ai.infrastructure.config import settings

logger = logging.getLogger(__name__)


# ── Module-level Singleton ───────────────────────────────────────────────────
# Khởi tạo ChatGoogleGenerativeAI 1 lần, dùng mãi
_chain_model: Optional[ChatGoogleGenerativeAI] = None


def _get_orchestrator_model() -> ChatGoogleGenerativeAI:
    """Lazy-init singleton LangChain ChatGoogleGenerativeAI với structured output."""
    global _chain_model
    if _chain_model is None:
        model = ChatGoogleGenerativeAI(
            model=settings.orchestrator_model,
            google_api_key=settings.google_api_key,  # pass key từ config
            temperature=0.0,  # Classification cần nhất quán tuyệt đối
        )
        # Thêm structured output cho Pydantic schema
        _chain_model = model.with_structured_output(OrchestratorJSONOutput)
        logger.info("ChatGoogleGenerativeAI singleton khởi tạo thành công.")
    return _chain_model


# ── System Prompt ────────────────────────────────────────────────────────────

_SYSTEM_INSTRUCTION = """\
Bạn là Managing Partner (Cổng tiếp nhận kiêm điều phối) của hệ thống Trợ lý \
Pháp luật Giao thông Đường bộ Việt Nam. Nhiệm vụ duy nhất: phân tích câu hỏi \
thành dữ liệu cấu trúc sạch để định tuyến hệ thống — KHÔNG tự trả lời.

══ QUY TẮC PHÂN LOẠI INTENT (2-LAYER) ══

Layer 1 — primary_intent:
• GENERAL_CHAT  : Chào hỏi, tạm biệt, cảm ơn, hỏi bạn là AI gì.
• OUT_OF_SCOPE  : Hoàn toàn ngoài phạm vi luật giao thông VN
                  (nấu ăn, viết code, luật hình sự, luật đất đai, chính trị...).
• LEGAL_CHAT    : Mọi câu hỏi liên quan đến giao thông đường bộ, đăng kiểm,
                  xử phạt, bằng lái, biển số xe, VNeID...

Layer 2 — detailed_intents (list[str], chỉ khi primary_intent = LEGAL_CHAT):
Xác định một hoặc nhiều intent chi tiết mà câu hỏi hướng tới:
• BEHAVIOR_ANALYSIS : Cần phân tích xem hành vi thực tế có vi phạm luật giao thông hay không.
                      Dấu hiệu: "Tôi đi...", "Khi gặp biển...", "Xe tôi..."
• PENALTY_LOOKUP    : Cần tra cứu chế tài phạt tiền, tước bằng lái, hoặc giam xe của lỗi vi phạm.
                      Dấu hiệu: "phạt bao nhiêu", "trừ mấy điểm", "bị giam xe không"
• ADMIN_PROCEDURE   : Quy trình, thủ tục hành chính, đăng kiểm, đổi bằng lái, giấy tờ xe.
                      Dấu hiệu: "thủ tục", "giấy tờ cần", "đổi bằng", "VNeID"
Lưu ý: Nếu câu hỏi hỏi cả vi phạm lẫn mức phạt (ví dụ: 'Xe máy chở 3 có bị phạt không và phạt bao nhiêu?'), chọn cả hai intent ['BEHAVIOR_ANALYSIS', 'PENALTY_LOOKUP'].

══ QUY TẮC BẺ TÁCH CÂU HỎI PHỨC HỢP ══

• is_compound = true  → câu hỏi chứa ≥ 2 hành vi vi phạm độc lập,
                        hoặc hỏi ≥ 2 nội dung thuộc điều khoản khác nhau.
• Bẻ nhỏ thành sub_queries tường minh, mỗi câu độc lập ngữ nghĩa:
  VD: "Xe máy chở 3 và vượt đèn đỏ bị phạt bao nhiêu?"
  → ["Xe máy chở người vượt số lượng cho phép bị phạt bao nhiêu?",
     "Xe máy không chấp hành hiệu lệnh đèn tín hiệu giao thông bị phạt bao nhiêu?"]
• is_compound = false → sub_queries chứa đúng 1 phần tử là câu hỏi gốc.
"""


# ── Short-circuit Responses ──────────────────────────────────────────────────

_GENERAL_CHAT_RESPONSES = {
    "greeting": (
        "Xin chào! Tôi là Trợ lý Pháp luật Giao thông Đường bộ Việt Nam. "
        "Tôi có thể giúp bạn tra cứu mức xử phạt, phân tích tình huống giao thông, "
        "và tìm hiểu thủ tục hành chính liên quan đến xe cộ. "
        "Bạn cần tư vấn gì hôm nay?"
    ),
    "default": (
        "Tôi là Trợ lý Pháp luật Giao thông Đường bộ Việt Nam, "
        "chuyên tư vấn về luật giao thông, mức xử phạt và thủ tục hành chính xe cộ. "
        "Bạn có câu hỏi gì về giao thông đường bộ không?"
    ),
}

_OUT_OF_SCOPE_RESPONSE = (
    "Xin lỗi, câu hỏi này nằm ngoài phạm vi tư vấn của tôi. "
    "Tôi chỉ có thể hỗ trợ các vấn đề liên quan đến Luật Giao thông Đường bộ "
    "Việt Nam: xử phạt vi phạm, phân tích tình huống lái xe, "
    "thủ tục đăng ký/đăng kiểm xe và giấy phép lái xe."
)


def _build_general_chat_response(query: str) -> str:
    """Trả về câu trả lời phù hợp cho GENERAL_CHAT dựa trên content."""
    q_lower = query.lower()
    if any(w in q_lower for w in ["chào", "hello", "hi", "xin chào", "alo"]):
        return _GENERAL_CHAT_RESPONSES["greeting"]
    return _GENERAL_CHAT_RESPONSES["default"]


def _format_conversation_context(state: AgentState) -> str:
    """
    Format lịch sử hội thoại gần nhất và tóm tắt để đưa vào prompt.
    Giới hạn 6 messages gần nhất (3 turns) để tránh tràn context.
    """
    summary = state.get("conversation_summary", "")
    history = state.get("conversation_history", [])
    
    lines = []
    if summary:
        lines.append(f"Tóm tắt các cuộc đối thoại trước đó:\n{summary}\n")

    recent = list(history)[-6:]
    if recent:
        lines.append("Lịch sử hội thoại gần đây:")
        for msg in recent:
            role = "Người dùng" if msg.type == "human" else "Trợ lý"
            lines.append(f"{role}: {msg.content}")

    lines.append(f"\nCâu hỏi mới: {state['user_query']}")
    return "\n".join(lines)


# ── Main Node Function ───────────────────────────────────────────────────────

async def orchestrator_node(state: AgentState) -> Dict[str, Any]:
    """
    LangGraph Node — Gateway đầu tiên của toàn bộ Graph.

    Input  : state["user_query"], state["conversation_history"]
    Output : primary_intent, detailed_intent, is_compound, sub_queries,
             current_query_idx, routing_plan, retry_count, max_retries,
             orchestrator_confidence, orchestrator_reasoning,
             [final_response nếu GENERAL_CHAT / OUT_OF_SCOPE]
    """
    user_query = state["user_query"]
    session_id = state.get("session_id", "N/A")
    logger.info(f"[{session_id}] Orchestrator xử lý: '{user_query[:80]}'")

    model = _get_orchestrator_model()
    contents = _format_conversation_context(state)

    try:
        # ── Gọi Gemini qua LangChain với structured output ───────────────────
        messages = [
            SystemMessage(content=_SYSTEM_INSTRUCTION),
            HumanMessage(content=contents),
        ]
        
        structured: OrchestratorJSONOutput = await model.ainvoke(messages)

        logger.info(
            f"[{session_id}] Intent: {structured.primary_intent} "
            f"→ {structured.detailed_intents} "
            f"| compound={structured.is_compound} "
            f"| confidence={structured.confidence_score:.2f}"
        )

        # ── Short-circuit: GENERAL_CHAT ───────────────────────────────────────
        if structured.primary_intent == "GENERAL_CHAT":
            logger.info(f"[{session_id}] Short-circuit GENERAL_CHAT.")
            return {
                "primary_intent": "GENERAL_CHAT",
                "detailed_intent": "NONE",
                "detailed_intents": [],
                "is_compound": False,
                "sub_queries": [user_query],
                "current_query_idx": 0,
                "parallel_mode": True,
                "current_intent_idx": 0,
                "routing_plan": [],        # Không route đến agent nào
                "retry_count": 0,
                "max_retries": settings.max_retries,
                "knowledge_loop_count": 0,
                "orchestrator_confidence": structured.confidence_score,
                "orchestrator_reasoning": structured.reasoning_trace,
                "final_response": _build_general_chat_response(user_query),
            }

        # ── Short-circuit: OUT_OF_SCOPE ───────────────────────────────────────
        if structured.primary_intent == "OUT_OF_SCOPE":
            logger.info(f"[{session_id}] Short-circuit OUT_OF_SCOPE.")
            return {
                "primary_intent": "OUT_OF_SCOPE",
                "detailed_intent": "NONE",
                "detailed_intents": [],
                "is_compound": False,
                "sub_queries": [user_query],
                "current_query_idx": 0,
                "parallel_mode": True,
                "current_intent_idx": 0,
                "routing_plan": [],
                "retry_count": 0,
                "max_retries": settings.max_retries,
                "knowledge_loop_count": 0,
                "orchestrator_confidence": structured.confidence_score,
                "orchestrator_reasoning": structured.reasoning_trace,
                "final_response": _OUT_OF_SCOPE_RESPONSE,
            }

        # ── LEGAL_CHAT: Xây dựng routing_plan động ───────────────────────────
        detailed_intents = structured.detailed_intents or ["BEHAVIOR_ANALYSIS"]
        # Đảm bảo tính tương thích ngược cho các node cũ đọc detailed_intent
        detailed_intent = detailed_intents[0] if detailed_intents else "BEHAVIOR_ANALYSIS"

        routing_plan = ["knowledge"]
        workers = []
        if "BEHAVIOR_ANALYSIS" in detailed_intents:
            workers.append("analyst")
        if "PENALTY_LOOKUP" in detailed_intents:
            workers.append("sanction")
        if "ADMIN_PROCEDURE" in detailed_intents:
            workers.append("admin_procedure")
        
        routing_plan.extend(workers)
        routing_plan.append("validator")

        logger.info(
            f"[{session_id}] 🗺️ Routing plan: {routing_plan} "
            f"| Sub-queries ({len(structured.sub_queries)}): {structured.sub_queries}"
        )

        return {
            "primary_intent": "LEGAL_CHAT",
            "detailed_intent": detailed_intent,
            "detailed_intents": detailed_intents,
            "is_compound": structured.is_compound,
            "sub_queries": structured.sub_queries,
            "current_query_idx": 0,        # Reset về đầu danh sách sub-queries
            "parallel_mode": True,         # Khởi tạo chế độ Parallel ban đầu
            "current_intent_idx": 0,       # Reset chỉ mục intent tuần tự
            "routing_plan": routing_plan,
            "retry_count": 0,              # Reset retry counter
            "max_retries": settings.max_retries,
            "knowledge_loop_count": 0,
            "orchestrator_confidence": structured.confidence_score,
            "orchestrator_reasoning": structured.reasoning_trace,
        }

    except Exception as e:
        # Lỗi từ LangChain / Gemini API — log và fallback an toàn
        logger.error(
            f"[{session_id}] Orchestrator lỗi: {e}",
            exc_info=True,
        )
        return {
            "primary_intent": "LEGAL_CHAT",
            "detailed_intent": "BEHAVIOR_ANALYSIS",  # Route an toàn nhất
            "detailed_intents": ["BEHAVIOR_ANALYSIS"],
            "is_compound": False,
            "sub_queries": [user_query],
            "current_query_idx": 0,
            "parallel_mode": True,
            "current_intent_idx": 0,
            "routing_plan": ["knowledge", "analyst", "sanction", "validator"],
            "retry_count": 0,
            "max_retries": settings.max_retries,
            "knowledge_loop_count": 0,
            "orchestrator_confidence": 0.0,
            "orchestrator_reasoning": f"Fallback do lỗi: {str(e)}",
            "errors": [f"orchestrator_error: {str(e)}"],
        }