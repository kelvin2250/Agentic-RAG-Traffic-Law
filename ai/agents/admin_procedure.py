"""
Admin Procedure Agent — "Bureaucratic Guide" của hệ thống.

Nhiệm vụ:
  1. Tra cứu và hướng dẫn chi tiết các thủ tục hành chính (đăng kiểm, bằng lái, giấy tờ...).
  2. Trích xuất từ retrieved_docs các step-by-step procedures.
  3. Tổng hợp hồ sơ cần chuẩn bị, lệ phí, thời gian giải quyết, cơ sở pháp lý.

Thiết kế: Structured Output — LLM trích xuất procedure details, Python không cần tính toán.
"""
import logging
from typing import List, Optional

from pydantic import BaseModel, Field

from ai.agents.base import BaseAgent
from ai.agents.state import AgentState
from ai.infrastructure.config import settings

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# PYDANTIC SCHEMA — Cấu trúc Procedure
# ═══════════════════════════════════════════════════════════════════════════

class ProcedureStep(BaseModel):
    """Một bước trong quy trình thủ tục."""
    step_number: int = Field(
        description="Số thứ tự bước (1, 2, 3...)"
    )
    step_title: str = Field(
        description="Tên/tiêu đề của bước (VD: 'Nộp hồ sơ tại Phòng Công an')"
    )
    step_description: str = Field(
        description="Mô tả chi tiết bước này (nơi nộp, cách thức, điều kiện...)"
    )


class AdminProcedureOutput(BaseModel):
    """Mô hình đầu ra cấu trúc cho thủ tục hành chính."""
    procedure_name: str = Field(
        description="Tên đầy đủ của thủ tục hành chính (VD: 'Đăng ký hợp thức xe ô tô')"
    )
    procedure_purpose: str = Field(
        description="Mục đích của thủ tục (tóm tắt 1-2 dòng)"
    )
    required_documents: List[str] = Field(
        default_factory=list,
        description="Danh sách giấy tờ cần chuẩn bị (VD: ['Giấy chứng thực đơn đăng ký', 'Chứng thực đơn chuyên dùng'...])"
    )
    steps: List[ProcedureStep] = Field(
        default_factory=list,
        description="Danh sách các bước thực hiện thủ tục, theo thứ tự"
    )
    fees: Optional[str] = Field(
        default=None,
        description="Các khoản lệ phí cần nộp (VD: '50.000 VNĐ cho đăng ký hợp thức; 25.000 VNĐ cho cấp biển số')"
    )
    processing_time: Optional[str] = Field(
        default=None,
        description="Thời gian trả kết quả bình thường (VD: '3 ngày làm việc')"
    )
    legal_basis: List[str] = Field(
        default_factory=list,
        description="Danh sách các Nghị định, Thông tư, Quyết định liên quan"
    )
    unresolved_reason: Optional[str] = Field(
        default=None,
        description="Lý do nếu không tìm được thủ tục (VD: 'Tài liệu không chứa quy định về thủ tục này')"
    )


# ═══════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPT — thêm yêu cầu wrap JSON trong ```json ... ```
# ═══════════════════════════════════════════════════════════════════════════

_ADMIN_PROCEDURE_SYSTEM_PROMPT = """\
Bạn là Admin Procedure Agent (Chuyên viên Hướng dẫn Thủ tục Hành chính) trong hệ thống Pháp luật Giao thông Đường bộ Việt Nam.
Nhiệm vụ duy nhất: Trích xuất và hướng dẫn chi tiết các quy trình thủ tục hành chính từ tài liệu pháp luật.

══ QUY TẮC TRÍCH XUẤT THỦ TỤC ══

1. **Xác định tên thủ tục**: 
   - Từ câu hỏi của người dùng, tìm ra tên chính xác của thủ tục.
   - Nếu câu hỏi không chỉ định rõ, duyệt tài liệu tìm các thủ tục liên quan.

2. **Trích xuất các bước (steps)**:
   - Liệt kê tuần tự từng bước của quy trình.
   - Mỗi bước gồm: step_number (int), step_title (str), step_description (str chi tiết).

3. **Hồ sơ cần chuẩn bị (required_documents)**:
   - Liệt kê tất cả giấy tờ dưới dạng mảng chuỗi.

4. **Lệ phí và thời gian**:
   - fees: Chuỗi mô tả phí (hoặc null nếu không rõ).
   - processing_time: Chuỗi thời gian xử lý (hoặc null nếu không rõ).

5. **Cơ sở pháp lý (legal_basis)**:
   - Mảng chuỗi các Nghị định, Thông tư liên quan.

6. **Nếu không tìm được**:
   - steps = [], required_documents = [], unresolved_reason = "Tài liệu không chứa quy định về thủ tục này".

══ ĐẦU RA BẮT BUỘC ══
Trả về DUY NHẤT một khối JSON nằm trong cú pháp ```json ... ```:

```json
{
  "procedure_name": "Tên thủ tục",
  "procedure_purpose": "Mục đích thủ tục",
  "required_documents": ["Giấy tờ 1", "Giấy tờ 2"],
  "steps": [
    {
      "step_number": 1,
      "step_title": "Tên bước",
      "step_description": "Mô tả chi tiết..."
    }
  ],
  "fees": "50.000 VNĐ hoặc null",
  "processing_time": "3 ngày làm việc hoặc null",
  "legal_basis": ["Thông tư số 73/2024/TT-BCA"],
  "unresolved_reason": null
}
```
"""


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN PROCEDURE AGENT CLASS
# ═══════════════════════════════════════════════════════════════════════════

class AdminProcedureAgent(BaseAgent):
    """Admin Procedure Agent — Hướng dẫn chi tiết thủ tục hành chính."""

    def __init__(self):
        super().__init__(
            model_name=settings.deepseek_model_default,
            system_prompt=_ADMIN_PROCEDURE_SYSTEM_PROMPT,
        )
        logger.info(
            f"Khởi tạo AdminProcedureAgent thành công sử dụng model '{settings.deepseek_model_default}'."
        )

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_json(text: str) -> dict:
        """Trích xuất JSON từ response text, hỗ trợ nhiều format DeepSeek có thể trả về."""
        import json, re

        # Ưu tiên: lấy từ ```json ... ```
        match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            return json.loads(match.group(1))

        # Fallback: lấy JSON object đầu tiên trong text
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())

        raise ValueError("Không tìm thấy JSON block hợp lệ trong response của model.")

    @staticmethod
    def _normalize(raw: dict) -> AdminProcedureOutput:
        """
        Normalize raw dict → AdminProcedureOutput.
        Xử lý các trường hợp model trả về kiểu sai.
        """
        # legal_basis: str → list
        legal_basis = raw.get("legal_basis", [])
        if isinstance(legal_basis, str):
            stripped = legal_basis.strip()
            if not stripped or stripped.lower() in ("null", "none", ""):
                legal_basis = []
            elif ";" in stripped:
                legal_basis = [x.strip() for x in stripped.split(";") if x.strip()]
            elif "," in stripped:
                legal_basis = [x.strip() for x in stripped.split(",") if x.strip()]
            else:
                legal_basis = [stripped]
        raw["legal_basis"] = legal_basis

        # required_documents: str → list
        req_docs = raw.get("required_documents", [])
        if isinstance(req_docs, str):
            raw["required_documents"] = [req_docs] if req_docs.strip() else []

        # steps: validate từng step có đủ fields
        steps = raw.get("steps", [])
        normalized_steps = []
        for i, step in enumerate(steps):
            if isinstance(step, dict):
                normalized_steps.append({
                    "step_number": step.get("step_number", i + 1),
                    "step_title": step.get("step_title", f"Bước {i + 1}"),
                    "step_description": step.get("step_description", ""),
                })
        raw["steps"] = normalized_steps

        # fees / processing_time: null-safe
        for field in ("fees", "processing_time", "unresolved_reason"):
            val = raw.get(field)
            if isinstance(val, str) and val.strip().lower() in ("null", "none", ""):
                raw[field] = None

        return AdminProcedureOutput.model_validate(raw)

    # ── Main ─────────────────────────────────────────────────────────────────

    async def __call__(self, state: AgentState) -> dict:
        session_id = state.get("session_id", "N/A")
        logger.info(f"[{session_id}] Admin Procedure Agent bắt đầu hướng dẫn thủ tục...")

        try:
            user_query = state.get("user_query", "")
            retrieved_docs = state.get("retrieved_docs", [])
            errors = state.get("errors", [])

            # ── Dùng sub_queries[0] đã được Orchestrator clarify ───────────────────
            active_query = state.get("sub_queries", [user_query])[0]

            docs_formatted = []
            for i, doc in enumerate(retrieved_docs):
                meta = doc.get("metadata", {})
                source = meta.get("source", "N/A")
                docs_formatted.append(
                    f"[Tài liệu #{i+1}] Source: {source}\n{doc.get('page_content', '')}"
                )
            docs_str = "\n\n".join(docs_formatted) if docs_formatted else "[Không có tài liệu]"

            input_prompt = f"""
    CÂU HỎI CẦN HƯỚNG DẪN:
    {active_query}

    TÀI LIỆU PHÁP LUẬT:
    {docs_str}

    LỖI TRƯỚC ĐÓ (RETRY):
    {errors if errors else "Không có"}

    Hãy trích xuất thủ tục hành chính và trả về DUY NHẤT một khối JSON trong thẻ ```json ... ```.
    """
            messages = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": input_prompt},
            ]

            # ── Gọi LLM thô ───────────────────────────────────────────────────
            logger.info(f"[{session_id}] Đang gọi LLM...")
            raw_response = await self.llm.ainvoke(messages)

            # Guard: kiểm tra response hợp lệ
            if raw_response is None or not hasattr(raw_response, "content"):
                raise ValueError(f"LLM trả về response không hợp lệ: {raw_response}")

            raw_text = raw_response.content
            logger.info(f"[{session_id}] LLM response nhậ nđược ({len(raw_text)} chars)")

            # ── Parse JSON ────────────────────────────────────────────────────
            raw_dict = self._extract_json(raw_text)
            logger.info(f"[{session_id}] Parse JSON thành công")

            # ── Normalize + Validate ──────────────────────────────────────────
            output = self._normalize(raw_dict)

            admin_procedure_details = {
                "procedure_name": output.procedure_name,
                "procedure_purpose": output.procedure_purpose,
                "required_documents": output.required_documents,
                "steps": [s.model_dump() for s in output.steps],
                "fees": output.fees,
                "processing_time": output.processing_time,
                "legal_basis": output.legal_basis,
                "unresolved_reason": output.unresolved_reason,
            }

            logger.info(
                f"[{session_id}] Admin Procedure Agent hoàn thành. "
                f"Thủ tục: {output.procedure_name} | "
                f"Bước: {len(output.steps)} | "
                f"Giấy tờ: {len(output.required_documents)}"
            )
            return {"admin_procedure_details": admin_procedure_details}

        except Exception as e:
            # KHÔNG để exception nào thoát ra ngoài — luôn return dict
            logger.error(f"[{session_id}] Admin Procedure Agent lỗi: {e}", exc_info=True)
            return {"errors": [f"admin_procedure_error: {str(e)}"]}