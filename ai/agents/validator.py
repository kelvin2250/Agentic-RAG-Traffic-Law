# ai/agents/validator.py
"""
Validator Node — "Quality Assurance Officer" bằng Code thuần (Không LLM).
"""
import logging
from ai.agents.state import AgentState

logger = logging.getLogger(__name__)

def validator_node(state: AgentState) -> dict:
    """
    Thực thi kiểm tra chất lượng bằng logic code thuần. Latency ~0ms.
    """
    session_id = state.get("session_id", "N/A")
    logger.info(f"[{session_id}] Validator Node bắt đầu kiếm định chất lượng...")

    intents = state.get("detailed_intents", [])
    if not intents:
        old_intent = state.get("detailed_intent", "NONE")
        if old_intent and old_intent != "NONE":
            intents = [old_intent]

    parallel_mode = state.get("parallel_mode", True)
    current_intent_idx = state.get("current_intent_idx", 0)

    extracted_facts = state.get("extracted_facts", {})
    legal_analysis = state.get("legal_analysis", "")
    sanction_details = state.get("sanction_details", {})
    admin_procedure_details = state.get("admin_procedure_details", {})
    retrieved_docs = state.get("retrieved_docs", [])
    retry_count = state.get("retry_count", 0)

    # Xác định các intent cần kiểm định trong vòng này
    active_intents = []
    if parallel_mode:
        active_intents = intents
    else:
        if current_intent_idx < len(intents):
            active_intents = [intents[current_intent_idx]]

    is_valid = True
    missing_reasons = []

    # ── 1. Kiểm định cho Phân tích hành vi (BEHAVIOR_ANALYSIS) ───────────────
    if "BEHAVIOR_ANALYSIS" in active_intents:
        analyst_valid = True
        # Lấy linh hoạt legal_basis (chấp nhận cả chuỗi, mảng hoặc None)
        raw_legal_basis = extracted_facts.get("legal_basis", "")
        
        # Chuẩn hóa dữ liệu về dạng chuỗi sạch để kiểm tra
        if isinstance(raw_legal_basis, list):
            basis_str = " ".join([str(item) for item in raw_legal_basis if item])
        elif isinstance(raw_legal_basis, str):
            basis_str = raw_legal_basis.strip()
        else:
            basis_str = ""

        # Xác định xem Agent có điền căn cứ pháp lý hay không
        has_basis = len(basis_str) > 0 and basis_str.lower() != "null"
        
        # Gom cả lập luận (legal_analysis) và căn cứ pháp lý (basis_str) để quét từ khóa
        analysis_str = legal_analysis if isinstance(legal_analysis, str) else ""
        full_text_to_scan = f"{analysis_str} {basis_str}"
        
        keywords = ["Điều", "Khoản", "Điểm", "Nghị định", "Luật", "Thông tư"]
        has_keywords = any(kw in full_text_to_scan for kw in keywords)
        
        is_violation = extracted_facts.get("is_violation", True)
        
        # Tiến hành kiểm định dựa trên dữ liệu đã chuẩn hóa
        if is_violation and not (has_basis or has_keywords):
            analyst_valid = False
            missing_reasons.append("Không tìm thấy trích dẫn hoặc từ khóa căn cứ pháp lý (Điều/Khoản/Nghị định) trong kết quả phân tích hành vi vi phạm.")
        elif not analysis_str.strip():
            analyst_valid = False
            missing_reasons.append("Lập luận phân tích hành vi (cot_trace) của Analyst rỗng.")

        is_valid = is_valid and analyst_valid

    # ── 2. Kiểm định cho Tra cứu mức phạt (PENALTY_LOOKUP) ──────────────────
    if "PENALTY_LOOKUP" in active_intents:
        sanction_valid = True
        violations = sanction_details.get("violations", [])
        unresolved_reason = sanction_details.get("unresolved_reason")
        
        # Trường hợp 1: Có dữ liệu vi phạm được bóc tách
        if violations:
            has_citations = any(
                v.get("legal_basis") and str(v.get("legal_basis")).strip().lower() not in ("null", "none", "")
                for v in violations
            )
            if not has_citations:
                sanction_valid = False
                missing_reasons.append("Không tìm thấy trích dẫn cơ sở pháp lý (Điều/Khoản) hợp lệ trong danh sách chế tài.")
                
        # Trường hợp 2: Danh sách rỗng nhưng Agent giải trình được lý do (Hợp lệ)
        elif unresolved_reason and str(unresolved_reason).strip():
            logger.info(f"[{session_id}] Không có chế tài do: {unresolved_reason}. Validator chấp nhậ n.")
            
        # Trường hợp 3: Danh sách rỗng và cũng không có lý do giải trình
        else:
            sanction_valid = False
            missing_reasons.append("Danh sách chế tài trống và không có lý do giải trình (unresolved_reason) từ Sanction Agent.")

        is_valid = is_valid and sanction_valid

    # ── 3. Kiểm định cho Thủ tục Hành chính (ADMIN_PROCEDURE) ────────────────
    if "ADMIN_PROCEDURE" in active_intents:
        admin_valid = True
        steps = admin_procedure_details.get("steps", [])
        procedure_name = admin_procedure_details.get("procedure_name", "")
        
        if not retrieved_docs:
            admin_valid = False
            missing_reasons.append("Không tìm thấy tài liệu quy trình thủ tục hành chính trong cơ sở dữ liệu.")
        elif not procedure_name or procedure_name == "N/A":
            admin_valid = False
            missing_reasons.append("Không thể trích xuất tên thủ tục hành chính từ tài liệu.")
        elif not steps:
            admin_valid = False
            missing_reasons.append("Không thể trích xuất các bước thực hiện thủ tục hành chính.")

        is_valid = is_valid and admin_valid

    # ── 4. Fallback cho các intent khác (NONE, GENERAL_CHAT, v.v.) ────────────
    if not any(i in ["BEHAVIOR_ANALYSIS", "PENALTY_LOOKUP", "ADMIN_PROCEDURE"] for i in active_intents):
        logger.debug(f"[{session_id}] Các Intents {active_intents} không yêu cầu kiếm định cụ thể. Bỏ qua.")

    reasons_str = "; ".join(missing_reasons)

    # ── 5. Cấu trúc báo cáo kiểm định (Validation Report) ────────────────────
    validation_report = {
        "is_valid": is_valid,
        "verified_citations": ["Đã xác minh sự tồn tại của dữ liệu"] if is_valid else [],
        "unverified_citations": missing_reasons,
        "disclaimer_needed": not is_valid,
        "reasoning": "Kiểm định chất lượng: " + ("ĐẠT" if is_valid else f"KHÔNG ĐẠT ({reasons_str})"),
    }

    # Xây dựng các cập nhật cho State
    updates = {
        "validation_report": validation_report,
    }

    if not is_valid:
        # Chuyển đổi trạng thái sang Sequential và quay đầu sửa lỗi từ index 0
        updates["parallel_mode"] = False
        # Nếu đang ở parallel mà tạch -> Reset index về 0 để chạy tuần tự sửa sai
        # Nếu đã ở sequential rồi mà tiếp tục tạch -> giữ nguyên index hiện tại để chạy lại đúng node đó
        if parallel_mode:
            updates["current_intent_idx"] = 0
        
        new_retry_count = retry_count + 1
        updates["retry_count"] = new_retry_count
        updates["errors"] = [f"validation_fail (Retry #{new_retry_count}): {reasons_str}"]
        
        logger.warning(f"[{session_id}] Kiếm định THẤT BẠI. Chuyển đổi luồng: parallel_mode=False, current_intent_idx={updates.get('current_intent_idx', current_intent_idx)}")
    else:
        logger.info(f"[{session_id}] Kiếm định THÀNH CÔNG.")
        # Nếu đang ở sequential và thành công -> tăng index để chạy tiếp node kế tiếp
        if not parallel_mode:
            updates["current_intent_idx"] = current_intent_idx + 1

    return updates