import hashlib
from typing import Annotated, Sequence, TypedDict, List, Optional
from langchain_core.messages import BaseMessage


# ═══════════════════════════════════════════════════════════════════════════
# CUSTOM REDUCERS
# ═══════════════════════════════════════════════════════════════════════════

def merge_docs(existing: Sequence[dict], new: Sequence[dict]) -> Sequence[dict]:
    """
    Custom Reducer cho retrieved_docs:
    1. Hợp nhất tài liệu cũ và mới.
    2. Lọc trùng dựa trên chunk_id hoặc MD5 hash.
    3. CHIẾN THUẬT MỚI: Loại bỏ thẳng tay các tài liệu có score < 0.3.
    4. Sắp xếp lại theo relevance score giảm dần.
    5. Giới hạn nghiêm ngặt tối đa Top 5 tài liệu chất lượng nhất.
    """
    existing = list(existing or [])
    new = list(new or [])
    if not new and not existing:
        return []

    def get_doc_key(d: dict) -> str:
        if d.get("chunk_id"):
            return str(d["chunk_id"])
        if d.get("metadata", {}).get("chunk_id"):
            return str(d["metadata"]["chunk_id"])
        content = d.get("page_content", "")
        return hashlib.md5(content.encode("utf-8")).hexdigest()

    merged_dict: dict[str, dict] = {}

    # Gộp chung hai danh sách để xử lý một lượt
    for doc in existing + new:
        # Lấy score tối ưu từ các tầng (Ưu tiên score gốc của Cohere Rerank)
        score = doc.get("score", 0.0) or doc.get("metadata", {}).get("relevance_score", 0.0) or 0.0
        
        # ── LOGIC LỌC SÀN ĐIỂM SỐ (SCORE FLOOR FILTER) ──────────────────────
        # Nếu tài liệu có độ đồng dạng quá thấp (< 0.3), bỏ qua hoàn toàn
        if score < 0.3:
            continue

        key = get_doc_key(doc)
        if key not in merged_dict:
            merged_dict[key] = doc
        else:
            # Nếu trùng tài liệu, ưu tiên giữ lại bản ghi có score cao hơn
            existing_score = merged_dict[key].get("score", 0.0) or merged_dict[key].get("metadata", {}).get("relevance_score", 0.0) or 0.0
            if score > existing_score:
                merged_dict[key] = doc

    # Sắp xếp toàn bộ tài liệu hợp lệ theo thứ tự điểm số giảm dần
    sorted_docs = sorted(
        merged_dict.values(),
        key=lambda d: d.get("score", 0.0) or d.get("metadata", {}).get("relevance_score", 0.0) or 0.0,
        reverse=True,
    )

    # Chốt chặn số lượng: Chỉ lấy tối đa 5 tài liệu xuất sắc nhất vượt qua vòng gửi xe
    return sorted_docs[:5]


def append_errors(existing: List[str], new: List[str]) -> List[str]:
    """
    Custom Reducer cho errors: tích lũy các lỗi mới.
    Hỗ trợ gom lỗi từ các nhánh song song chạy đồng thời (Fan-in).
    """
    existing_list = list(existing or [])
    new_list = list(new or [])
    for err in new_list:
        if err not in existing_list:
            existing_list.append(err)
    return existing_list


# ═══════════════════════════════════════════════════════════════════════════
# AGENT STATE — Source of Truth cho toàn bộ LangGraph
# ═══════════════════════════════════════════════════════════════════════════

class AgentState(TypedDict, total=False):
    # ── Input (bắt buộc từ caller)
    user_query: str         
    session_id: str        

    # ── Conversation Memory (loaded from Redis, persisted after each turn) 
    conversation_history: Sequence[BaseMessage]
    conversation_summary: str

    # ── Orchestrator Output 
    primary_intent: str # GENERAL_CHAT | OUT_OF_SCOPE | LEGAL_CHAT
    detailed_intent: str # BEHAVIOR_ANALYSIS | PENALTY_LOOKUP | ADMIN_PROCEDURE | NONE (Deprecated)
    detailed_intents: List[str] # Danh sách intents chi tiết

    is_compound: bool        # True nếu câu hỏi phức hợp chứa nhiều vi phạm độc lập
    sub_queries: List[str]   # Danh sách câu hỏi con sau khi bẻ tách
    current_query_idx: int   # Index sub-query đang được Knowledge Node xử lý

    # ── State điều khiển chế độ chạy song song & tuần tự
    parallel_mode: bool      # Mặc định True. Chuyển sang False nếu gặp lỗi kiểm định để chạy sequential.
    current_intent_idx: int  # Chỉ mục intent đang được xử lý trong chế độ Sequential.

    # Kế hoạch định tuyến động — danh sách node sẽ đi qua theo thứ tự
    routing_plan: List[str]  # Ví dụ: ["knowledge", "analyst", "sanction", "validator"]

    orchestrator_confidence: float   # Độ tin cậy phân loại intent [0.0 - 1.0]
    orchestrator_reasoning: str      # Chain-of-thought giải thích phân loại

    # ── Knowledge Agent Output ───────────────────────────────────────────────
    rewritten_query: str     # Query đã dịch sang ngôn ngữ pháp lý
    retrieved_docs: Annotated[Sequence[dict], merge_docs]
    # Mỗi doc: {"page_content": str, "metadata": dict, "score": float,
    #           "associated_sub_query_idx": int}

    retrieval_source: str    # "local" | "web" | "hybrid" | "error"
    confidence_score: float  # Score cao nhất trong lần retrieval này

    # ── Downstream Agent Outputs ─────────────────────────────────────────────
    extracted_facts: dict    # Analyst: tình tiết cốt lõi bóc tách từ query
    legal_analysis: str      # Analyst: lập luận phân tích hành vi vi phạm
    sanction_details: dict   # Sanction: khung phạt, điểm GPLX, hình phạt bổ sung
    admin_procedure_details: dict  # Admin Procedure: các bước thủ tục, giấy tờ, lệ phí
    final_response: str      # Synthesizer: câu trả lời cuối cùng cho user

    # ── Control Flow ─────────────────────────────────────────────────────────
    retry_count: int         # Số lần đã retry (Validator → Knowledge)
    max_retries: int         # Giới hạn retry tối đa (default: 2)
    next_node: str           # Override định tuyến tiếp theo nếu cần
    knowledge_loop_count: int # Đếm số lần đã loop lại node knowledge (Compound Query)
    validation_report: dict  # Validator: báo cáo kiểm định chất lượng
    errors: Annotated[List[str], append_errors]  # Tích lũy lỗi theo thời gian