import logging
from langgraph.graph import StateGraph, START, END
from langgraph.constants import Send

from ai.agents.state import AgentState
from ai.agents.orchestrator import orchestrator_node
from ai.agents.knowledge import knowledge_node
from ai.agents.analyst import AnalystAgent
from ai.agents.sanction import SanctionAgent
from ai.agents.validator import validator_node
from ai.agents.admin_procedure import AdminProcedureAgent
from ai.agents.answer_generate import answer_generate_node
from ai.infrastructure.config import settings

logger = logging.getLogger(__name__)


# ROUTING FUNCTIONS

def route_after_orchestrator(state: AgentState) -> str:
    """
    Sau Orchestrator:
    - GENERAL_CHAT / OUT_OF_SCOPE ➔ END (final_response đã set sẵn)
    - LEGAL_CHAT ➔ knowledge
    """
    primary = state.get("primary_intent", "LEGAL_CHAT")
    if primary in ("GENERAL_CHAT", "OUT_OF_SCOPE"):
        logger.info(f"route → END (short-circuit: {primary})")
        return "end"
    logger.info("route → knowledge")
    return "knowledge"


def _intent_to_node(intent: str) -> str:
    """Chuyển intent chi tiết sang tên node tương ứng trong Graph."""
    if intent == "BEHAVIOR_ANALYSIS":
        return "analyst"
    elif intent == "PENALTY_LOOKUP":
        return "sanction"
    elif intent == "ADMIN_PROCEDURE":
        return "admin_procedure"
    return "synthesizer"


def route_after_knowledge(state: AgentState) -> str:
    """
    Sau Knowledge Node (Compound Loop Gate):
    1. Nếu còn sub-queries chưa xử lý ➔ quay lại knowledge (loop)
    2. Nếu đã xử lý xong ➔ rẽ nhánh theo detailed_intents (song song hoặc tuần tự)
    """
    sub_queries: list = state.get("sub_queries", [])
    current_idx: int = state.get("current_query_idx", 0)
    loop_count: int = state.get("knowledge_loop_count", 0)
    parallel_mode: bool = state.get("parallel_mode", True)
    current_intent_idx: int = state.get("current_intent_idx", 0)
    intents: list = state.get("detailed_intents", [])

    # Safety guard: ngăn infinite loop nếu index không được advance đúng cách
    if loop_count >= settings.max_knowledge_loops:
        logger.warning(
            f"⚠️ Knowledge loop vượt ngưỡng an toàn ({loop_count}/{settings.max_knowledge_loops}). "
            "Route ➔ synthesizer (fallback)"
        )
        return "synthesizer"

    # Compound query loop — chạy tuần tự từng sub-query
    if current_idx < len(sub_queries):
        logger.info(
            f"🚀 route ➔ knowledge (loop: sub-query {current_idx + 1}/{len(sub_queries)})"
        )
        return "knowledge"

    # Chạy song song (Parallel Mode) ở lượt đầu tiên
    if parallel_mode:
        sends = []
        seen = set()
        for intent in intents:
            if intent not in seen:
                seen.add(intent)
                node_target = _intent_to_node(intent)
                if node_target != "synthesizer":
                    sends.append(Send(node_target, state))
        if sends:
            logger.info(f"route → Parallel Fan-out tới: {list(seen)}")
            return sends
        return "synthesizer"

    # Chạy tuần tự (Sequential Fallback Mode)
    else:
        if current_intent_idx < len(intents):
            next_intent = intents[current_intent_idx]
            node_target = _intent_to_node(next_intent)
            logger.info(f"route → Sequential mode: chạy intent {next_intent} ({current_intent_idx+1}/{len(intents)})")
            return node_target
        return "synthesizer"


def route_after_validator(state: AgentState) -> str:
    """
    Sau Validator (Retry Gate & Final Routing):
    - Nếu hợp lệ HOẶC đã hết lượt sửa sai ➔ synthesizer (Answer Generate Node)
    - Nếu không hợp lệ và còn lượt sửa sai ➔ Quay đầu sửa sai tuần tự (Sequential Fallback)
    """
    retry_count: int = state.get("retry_count", 0)
    max_retries: int = state.get("max_retries", 2)
    validation_report = state.get("validation_report", {})
    is_valid: bool = validation_report.get("is_valid", True)
    parallel_mode: bool = state.get("parallel_mode", True)
    current_intent_idx: int = state.get("current_intent_idx", 0)
    intents: list = state.get("detailed_intents", [])

    # 1. Trường hợp đi tiếp sinh câu trả lời (Đạt chuẩn hoặc Hết lượt sửa sai)
    if is_valid or retry_count >= max_retries:
        if not is_valid:
            logger.warning(f"Hết lượng sửa sai ({retry_count}/{max_retries}). Tiến hành xuất phản hồi kèm disclaimer.")
            return "synthesizer"
        
        # Nếu đang ở chế độ Sequential và chưa chạy hết danh sách intent, đi tiếp sang intent tiếp theo
        if not parallel_mode and current_intent_idx < len(intents):
            next_intent = intents[current_intent_idx]
            logger.info(f"Hợp lệ. Chuyển sang intent tiếp theo trong chế độ tuần tự: {next_intent}")
            return _intent_to_node(next_intent)

        logger.info("Kiếm định hoàn tất thành công. Tiến hành xuất phản hồi.")
        return "synthesizer"

    # 2. Trường hợp quay đầu sửa sai (Còn lượt retry)
    # Tại đây ta chắc chắn parallel_mode đang là False (do validator_node gạt cờ khi is_valid=False).
    # Định tuyến thẳng đến nút hiện tại để chạy lại
    if current_intent_idx < len(intents):
        retry_intent = intents[current_intent_idx]
        retry_target = _intent_to_node(retry_intent)
        logger.info(
            f"Quay đầu sửa lỗi trong chế độ tuần tự: chạy lại {retry_target} "
            f"(Lượt retry #{retry_count}/{max_retries})"
        )
        return retry_target

    return "knowledge"


# GRAPH BUILDER

def build_graph():
    """
    Xây dựng và compile LangGraph StateGraph 
    Returns:
        CompiledGraph — sẵn sàng invoke.
    """
    g = StateGraph(AgentState)

    # Khởi tạo các Agent Node Instances
    analyst_node = AnalystAgent()
    sanction_node = SanctionAgent()
    admin_procedure_node = AdminProcedureAgent()

    # ── Register Nodes ────────────────────────────────────────────────────────
    g.add_node("orchestrator", orchestrator_node)
    g.add_node("knowledge", knowledge_node)
    g.add_node("analyst", analyst_node)
    g.add_node("sanction", sanction_node)
    g.add_node("validator", validator_node)
    g.add_node("synthesizer", answer_generate_node)
    g.add_node("admin_procedure", admin_procedure_node)

    # ── Edges ─────────────────────────────────────────────────────────────────
    g.add_edge(START, "orchestrator")

    # Orchestrator ➔ short-circuit hoặc knowledge
    g.add_conditional_edges(
        "orchestrator",
        route_after_orchestrator,
        {
            "end": END,          # GENERAL_CHAT / OUT_OF_SCOPE
            "knowledge": "knowledge",
        },
    )

    # Knowledge ➔ loop (compound) hoặc next agent
    g.add_conditional_edges(
        "knowledge",
        route_after_knowledge,
        {
            "knowledge": "knowledge",     # Compound query loop
            "analyst": "analyst",
            "sanction": "sanction",
            "admin_procedure": "admin_procedure",
            "synthesizer": "synthesizer", # Fallback khi quá nhiều loop hoặc intent không xác định
        },
    )

    # Worker Agents luôn đi trực tiếp đến Validator
    g.add_edge("analyst", "validator")
    g.add_edge("sanction", "validator")
    g.add_edge("admin_procedure", "validator")

    # Validator ➔ rẽ nhánh kết quả hoặc quay đầu sửa sai (retry)
    g.add_conditional_edges(
        "validator",
        route_after_validator,
        {
            "synthesizer": "synthesizer",
            "knowledge": "knowledge",       # Quay đầu tìm tài liệu
            "analyst": "analyst",           # Quay đầu phân tích lại
            "sanction": "sanction",         # Quay đầu bóc phạt lại
            "admin_procedure": "admin_procedure", # Quay đầu trích xuất thủ tục lại
        },
    )

    g.add_edge("synthesizer", END)

    compiled = g.compile()
    logger.info("LangGraph v3 compiled thành công.")
    return compiled


# ── Singleton Graph Instance ─────────────────────────────────────────────────
_graph = None


def get_graph():
    """Lazy-init singleton graph instance."""
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph