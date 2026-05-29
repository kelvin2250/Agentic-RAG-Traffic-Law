# ai/agents/analyst.py
"""
Analyst Agent — "Legal Counsel" của hệ thống.

Nhiệm vụ:
  1. Tích lũy ngữ cảnh vụ việc (Case Context Memory) qua hội thoại và truy vấn mới.
  2. Phân tích 4 yếu tố cấu thành vi phạm (Four-Element Analysis).
  3. Phát hiện bất khả kháng (force majeure) / tình thế cấp thiết để loại bỏ lỗi.
  4. Đối chiếu hành vi với tài liệu luật (retrieved_docs) để xác định Điều/Khoản vi phạm.
"""
import logging
from typing import Any, Dict

from ai.agents.base import BaseAgent
from ai.agents.state import AgentState
from ai.infrastructure.config import settings
from ai.schemas.analyst import AnalystOutput

logger = logging.getLogger(__name__)




# ═══════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPT
# ═══════════════════════════════════════════════════════════════════════════

_ANALYST_SYSTEM_PROMPT = """\
Bạn là Legal Analyst Agent (Chuyên viên Phân tích Pháp lý) trong hệ thống Pháp luật Giao thông Đường bộ Việt Nam.
Nhiệm vụ của bạn là nhận định tình huống thực tế của người dùng, phân tích xem hành vi đó có cấu thành lỗi vi phạm hành chính hay không dựa trên tài liệu pháp luật được cung cấp.

══ QUY TRÌNH PHÂN TÍCH BẮT BUỘC (CHAIN-OF-THOUGHT) ══

Hãy tiến hành suy luận kỹ lưỡng theo các bước sau:
1. Tóm tắt tình huống thực tế của người dùng dựa trên lịch sử hội thoại (nếu có) và câu hỏi mới.
2. Cập nhật Case Context Memory (bộ nhớ ngữ cảnh vụ việc):
   - Xác định loại xe, địa điểm, các dấu hiệu camera, và đặc biệt là các tình tiết bất thường.
   - Luôn giữ lại ngữ cảnh cũ từ câu hỏi trước nếu câu hỏi mới không phủ định (ví dụ: câu trước nói đi "xe máy", câu này hỏi "vượt đèn đỏ" thì loại xe vẫn là "xe máy").
3. Phân tích 4 yếu tố cấu thành vi phạm:
   - Chủ thể: Ai thực hiện hành vi?
   - Khách thể: Quy định an toàn giao thông nào bị xâm hại?
   - Mặt chủ quan: Lỗi cố ý hay vô ý. ĐẶC BIỆT LƯU Ý các trường hợp loại trừ vi phạm hành chính (Tình thế cấp thiết, Sự kiện bất khả kháng, Sự kiện bất ngờ, Thực hiện theo yêu cầu của người có thẩm quyền như CSGT). Nếu rơi vào các trường hợp này thì kết luận là KHÔNG vi phạm (is_violation = false).
   - Mặt khách quan: Hành vi cụ thể được mô tả.
4. Đối chiếu hành vi với tài liệu pháp luật (được cung cấp trong Retrieved Documents). Trích xuất chính xác Điều, Khoản, Điểm điều chỉnh hành vi này.
5. Đưa ra kết luận pháp lý cuối cùng rõ ràng.

══ ĐẦU RA YÊU CẦU ══
Đầu ra của bạn PHẢI là một khối JSON duy nhất nằm trong cú pháp ```json ... ``` khớp chính xác với JSON Schema dưới đây:
{
  "case_context": {
    "vehicle_type": "loại xe (ô tô, xe máy, xe máy điện, xe đạp, đi bộ, hoặc null nếu chưa rõ)",
    "location": "địa điểm (nội đô, cao tốc, đường nông thôn, ngã tư...)",
    "has_camera": true/false/null,
    "force_majeure_signals": "các tình tiết khẩn cấp, bất khả kháng (VD: tránh xe cứu thương...)"
  },
  "four_elements": {
    "subject": "phân tích chủ thể",
    "object": "phân tích khách thể",
    "subjective": "phân tích mặt chủ quan (lỗi, bất khả kháng)",
    "objective": "phân tích mặt khách quan"
  },
  "is_violation": true/false,
  "legal_basis": "Điều/Khoản trích xuất từ tài liệu luật nếu có (VD: 'Điều 11 khoản 4b'), hoặc null nếu không tìm được",
  "cot_trace": "toàn bộ lập luận phân tích chi tiết từng bước (Chain-of-Thought)"
}

Chỉ được phép căn cứ vào các tài liệu pháp luật được cung cấp trong Retrieved Documents. Tuyệt đối không tự suy đoán các điều luật không xuất hiện trong tài liệu.
"""


# ═══════════════════════════════════════════════════════════════════════════
# ANALYST AGENT CLASS
# ═══════════════════════════════════════════════════════════════════════════

class AnalystAgent(BaseAgent):
    """Analyst Agent chịu trách nhiệm bóc tách ngữ cảnh và phân tích lỗi vi phạm."""

    def __init__(self):
        super().__init__(
            model_name=settings.analyst_model,
            system_prompt=_ANALYST_SYSTEM_PROMPT,
        )
        logger.info(f"Khởi tạo AnalystAgent thành công sử dụng model '{settings.analyst_model}'.")

    async def __call__(self, state: AgentState) -> dict:
        """
        Thực thi phân tích pháp lý trên State hiện tại.
        
        Input: state["user_query"], state["retrieved_docs"], state["conversation_history"]
        Output: Cập nhật state["extracted_facts"] và state["legal_analysis"]
        """
        session_id = state.get("session_id", "N/A")
        user_query = state.get("user_query", "")
        retrieved_docs = state.get("retrieved_docs", [])
        errors = state.get("errors", [])
        
        # Lấy ngữ cảnh cũ từ state nếu có
        existing_facts = state.get("extracted_facts", {})
        existing_context = existing_facts.get("case_context", {})

        logger.info(f"[{session_id}] Analyst Agent bắt đầu xử lý tình huống...")

        # ── Dùng sub_queries[0] đã được Orchestrator clarify ───────────────────
        active_query = state.get("sub_queries", [user_query])[0]

        # ── Xây dựng prompt đầu vào cho LLM ──────────────────────────────────
        docs_formatted = []
        for i, doc in enumerate(retrieved_docs):
            meta = doc.get("metadata", {})
            source = meta.get("source", "N/A")
            docs_formatted.append(
                f"[Tài liệu #{i+1}] Source: {source}\n{doc.get('page_content', '')}"
            )
        docs_str = "\n\n".join(docs_formatted)

        input_prompt = f"""
CÂU HỎI CẦN PHÂN TÍCH:
{active_query}

NGỮ CẢNH VỤ VIỆC HIỆN TẠI (ĐÃ TRÍCH XUẤT TRƯỚC ĐÓ):
{existing_context}

DANH SÁCH TÀI LIỆU PHÁP LUẬT ĐÃ TÌM THẤY (RETRIEVED DOCUMENTS):
{docs_str}

LỖI PHÁT HIỆN TỪ LẦN CHẠY TRƯỚC (NẾU CÓ - DÙNG ĐỂ RETRY VÀ SỬA CHỮA):
{errors}

Hãy thực hiện quy trình phân tích và trả về khối JSON kết quả duy nhất nằm trong thẻ ```json ... ``` theo đúng định dạng yêu cầu.
"""

        try:
            # Sử dụng Native Structured Output từ LLM 
            structured_llm = self.llm.with_structured_output(AnalystOutput, method="json_mode")
            messages = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": input_prompt}
            ]
            output = await structured_llm.ainvoke(messages)

            # Cập nhật extracted_facts và legal_analysis
            extracted_facts = {
                "case_context": output.case_context,
                "four_elements": output.four_elements,
                "is_violation": output.is_violation,
                "legal_basis": output.legal_basis,
            }

            logger.info(
                f"[{session_id}] Analyst Agent hoàn thành phân tích. Vi phạm: {output.is_violation} | Căn cứ: {output.legal_basis}"
            )

            return {
                "extracted_facts": extracted_facts,
                "legal_analysis": output.cot_trace,
            }

        except Exception as e:
            logger.error(
                f"[{session_id}] Analyst Agent lỗi: {e}",
                exc_info=True
            )
            return {
                "errors": [f"analyst_error: {str(e)}"],
            }
