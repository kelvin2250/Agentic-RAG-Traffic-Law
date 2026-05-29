"""
Sanction Agent — "Legal Actuary" của hệ thống.

Nhiệm vụ:
  1. Bóc tách chính xác khung phạt tiền và chế tài bổ sung từ retrieved_docs dựa vào câu hỏi.
  2. Nếu câu hỏi thiếu loại phương tiện, tự động trích xuất tất cả phương tiện có trong tài liệu luật.
  3. Để Python tự động tính toán số học (fine_average, total_min, total_max), triệt tiêu overengineering.

Thiết kế: Tối giản, chạy Single-Turn/Multi-Turn mượt mà nhờ Structured Output.
Optimized: Gemini 2.0 Flash (fast structured output) + max_tokens=1024 + doc truncation.
"""
import logging
import json
import re
import hashlib
from typing import Optional

from ai.agents.base import BaseAgent
from ai.agents.state import AgentState
from ai.infrastructure.config import settings
from ai.schemas.sanction import ViolationDetail, SanctionOutput

logger = logging.getLogger(__name__)

# In-memory cache cho sanction results (tránh gọi LLM lại cho cùng input)
_sanction_cache: dict[str, dict] = {}
MAX_CACHE_SIZE = 128


def _parse_json_markdown(text: str) -> dict:
    """Trích xuất và parse JSON từ văn bản trả về của LLM."""
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        json_str = match.group(1)
    else:
        match_raw = re.search(r"(\{.*\})", text, re.DOTALL)
        if match_raw:
            json_str = match_raw.group(1)
        else:
            json_str = text.strip()
    return json.loads(json_str)


def _sanitize_sanction_data(data: dict) -> dict:
    """
    Làm sạch dữ liệu đầu ra từ LLM trước khi Pydantic validation.
    Xử lý các lỗi phổ biến của LLM:
      - "18,000,000" → 18000000 (strip commas, convert to int)
      - "" → 0 cho required int fields (fine_min, fine_max)
      - "" → None cho Optional[int] fields (license_suspension_months, impoundment_days)
      - "0" → 0 (string to int)
    """
    violations = data.get("violations", [])
    for v in violations:
        # Xử lý fine_min, fine_max: strip commas, empty → 0
        for field in ("fine_min", "fine_max"):
            val = v.get(field, 0)
            if isinstance(val, str):
                cleaned = val.replace(",", "").replace(".", "").strip()
                v[field] = int(cleaned) if cleaned else 0
        
        # Xử lý Optional[int] fields: empty string → None
        for field in ("license_suspension_months", "impoundment_days"):
            val = v.get(field)
            if isinstance(val, str):
                cleaned = val.replace(",", "").replace(".", "").strip()
                v[field] = int(cleaned) if cleaned else None
    
    return data




# ═══════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPT — Làm sạch, tập trung vào Exploratory Extraction
# ═══════════════════════════════════════════════════════════════════════════

_SANCTION_SYSTEM_PROMPT = """\
Bạn là Sanction Agent (Chuyên viên Tra cứu Chế tài) trong hệ thống Pháp luật Giao thông Đường bộ Việt Nam.
Nhiệm vụ duy nhất: Bóc tách chính xác khung phạt từ tài liệu pháp luật (Retrieved Documents) dựa trên câu hỏi của người dùng.

══ QUY TẮC TRÍCH XUẤT THÔNG TIN ══

1. LUỒNG XỬ LÝ PHƯƠNG TIỆN:
   - Nếu câu hỏi chỉ đích danh loại xe (VD: "Ô tô...", "Xe máy..."): Chỉ trích xuất đúng khung phạt của loại xe đó.
   - Nếu câu hỏi KHÔNG nói rõ loại xe (VD: "Vượt đèn đỏ phạt bao nhiêu?"): Duyệt toàn bộ tài liệu luật được cung cấp, tạo ra MỖI OBJECT TRONG MẢNG "violations" CHO MỖI LOẠI PHƯƠNG TIỆN xuất hiện trong luật (Ô tô, xe máy, xe đạp, người đi bộ...). Tuyệt đối không được gộp chung hoặc chỉ chọn một phương tiện ngẫu nhiên.

2. TRA CỨU HÀNH VI (ĐA LỖI / COMPOUND QUERY):
   - Nếu câu hỏi chứa NHIỀU hành vi vi phạm khác nhau (VD: "xe máy chở 3 và vượt đèn đỏ"), bạn phải bóc tách và tạo ra các OBJECT RIÊNG BIỆT trong mảng "violations" cho từng hành vi vi phạm đó.
   - Tuyệt đối KHÔNG gộp chung nhiều hành vi khác nhau vào cùng một "violation_name". Mỗi hành vi phải tương ứng với một căn cứ pháp lý ("legal_basis") riêng biệt.

3. XỬ LÝ KỊCH BẢN TRỐNG:
   - Chỉ khi nào tài liệu luật được cung cấp hoàn toàn không chứa quy định nào liên quan đến hành vi được hỏi, mới để violations = [] và điền lý do vào unresolved_reason.

══ ĐẦU RA JSON MẪU (DẠNG ĐA HÀNH VI / ĐA PHƯƠNG TIỆN) ══
{
  "violations": [
    {
      "vehicle_type": "Xe máy",
      "violation_name": "Không chấp hành hiệu lệnh của đèn tín hiệu giao thông",
      "legal_basis": "Điểm g Khoản 4 Điều 7 Nghị định 168/2024/NĐ-CP",
      "fine_min": 800000,
      "fine_max": 1000000,
      "license_suspension_months": 2,
      "impoundment_days": null
    },
    {
      "vehicle_type": "Xe máy",
      "violation_name": "Chở theo từ 02 người trở lên trên xe",
      "legal_basis": "Điểm b Khoản 3 Điều 7 Nghị định 168/2024/NĐ-CP",
      "fine_min": 400000,
      "fine_max": 600000,
      "license_suspension_months": null,
      "impoundment_days": null
    }
  ],
  "unresolved_reason": null
}

LƯU Ý QUAN TRỌNG:
- fine_min, fine_max PHẢI là số nguyên (integer), KHÔNG có dấu phẩy, KHÔNG có dấu chấm phân cách hàng nghìn. Ví dụ: 18000000 chứ không phải "18,000,000" hay "18.000.000".
- license_suspension_months, impoundment_days: dùng null nếu không có quy định, KHÔNG dùng chuỗi rỗng "".
- Nếu luật không quy định phạt tiền cho hành vi này, đặt fine_min = 0, fine_max = 0.
"""


# ═══════════════════════════════════════════════════════════════════════════
# SANCTION AGENT CLASS — 100% Chế biến bằng Python
# ═══════════════════════════════════════════════════════════════════════════

class SanctionAgent(BaseAgent):
    """Sanction Agent — Trích xuất dữ liệu thô từ luật, Python gánh toán học."""

    def __init__(self):
        super().__init__(
            model_name=settings.sanction_model,
            system_prompt=_SANCTION_SYSTEM_PROMPT,
        )
        logger.info(f"Khởi tạo SanctionAgent thành công sử dụng model '{settings.sanction_model}'.")

    def _compute_cache_key(self, user_query: str, docs_str: str) -> str:
        """Tạo cache key từ hash của query + docs."""
        combined = f"{user_query}|||{docs_str}"
        return hashlib.sha256(combined.encode()).hexdigest()

    async def __call__(self, state: AgentState) -> dict:
        """
        Bóc tách khung phạt từ tất cả docs (đã tích lũy từ compound queries).
        """
        session_id = state.get("session_id", "N/A")
        user_query = state.get("user_query", "")
        sub_queries = state.get("sub_queries", [user_query])
        retrieved_docs = state.get("retrieved_docs", [])
        errors = state.get("errors", [])
        is_compound = state.get("is_compound", False)

        logger.info(
            f"[{session_id}] Sanction Agent bóc tách khung phạt "
            f"(compound={is_compound}, docs={len(retrieved_docs)})"
        )

        # ── Định dạng tài liệu luật (truncate mỗi doc xuống 600 ký tự) ────────
        docs_formatted = []
        for i, doc in enumerate(retrieved_docs):
            meta = doc.get("metadata", {})
            source = meta.get("source", "N/A")
            content = doc.get('page_content', '')
            # ⚡ Truncate để giảm token input, giữ đủ context pháp lý
            if len(content) > 600:
                content = content[:600] + "..."
            docs_formatted.append(
                f"[Tài liệu #{i+1}] Source: {source}\n{content}"
            )
        docs_str = "\n\n".join(docs_formatted) if docs_formatted else "[Không có tài liệu]"

        # ── Cache Check (bỏ qua nếu đang retry) ──────────────────────────────
        cache_key = self._compute_cache_key(user_query, docs_str)
        if not errors and cache_key in _sanction_cache:
            logger.info(f"[{session_id}] Sanction cache HIT → skip LLM call")
            return {"sanction_details": _sanction_cache[cache_key]}

        # ── Build prompt ──────────────────────────────────────────────────────
        sub_queries_str = ""
        active_query = sub_queries[0] if sub_queries else user_query
        if is_compound and len(sub_queries) > 1:
            sub_queries_str = "\n\nCâu hỏi đã được tách thành các sub-queries sau:\n"
            for idx, sq in enumerate(sub_queries, 1):
                sub_queries_str += f"{idx}. {sq}\n"
            sub_queries_str += "\nHãy bóc tách violations cho CẢ các sub-queries trên từ tài liệu luật."
        elif len(sub_queries) == 1 and sub_queries[0] != user_query:
            sub_queries_str = f"\n\nCâu hỏi đã được làm rõ ngữ cảnh hội thoại:\n{sub_queries[0]}\n"

        input_prompt = f"""\
CÂU HỎI GỐC CỦA NGƯỜI DÙNG:
{user_query}{sub_queries_str}

TÀI LIỆU PHÁP LUẬT:
{docs_str}

LỖI TRƯỚC ĐÓ (NẾU RETRY):
{errors if errors else "Không có"}

Hãy bóc tách violations theo đúng JSON Schema yêu cầu.
"""

        try:
            # Gọi LLM với max_tokens=1024 (chỉ cần JSON nhỏ, không cần dài)
            messages = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": input_prompt}
            ]
            response = await self.llm.ainvoke(messages)

            # Parse JSON thủ công
            parsed_data = _parse_json_markdown(response.content)
            
            # ⭐ SANITIZE: làm sạch dữ liệu LLM trước khi Pydantic validate
            parsed_data = _sanitize_sanction_data(parsed_data)
            
            output = SanctionOutput.model_validate(parsed_data)

            # ⭐ PYTHON TÍNH TOÁN TỔNG — 100% CHÍNH XÁC ⭐
            violations_dict = []
            total_fine_min = 0
            total_fine_max = 0

            for v in output.violations:
                v_data = v.model_dump()
                v_data["fine_average"] = int((v.fine_min + v.fine_max) / 2)
                violations_dict.append(v_data)
                
                total_fine_min += v.fine_min
                total_fine_max += v.fine_max

            max_suspension = max(
                [v.license_suspension_months for v in output.violations 
                 if v.license_suspension_months is not None],
                default=None
            )
            max_impoundment = max(
                [v.impoundment_days for v in output.violations 
                 if v.impoundment_days is not None],
                default=None
            )

            sanction_details = {
                "violations": violations_dict,
                "total_fine_min": total_fine_min,
                "total_fine_max": total_fine_max,
                "max_license_suspension_months": max_suspension,
                "max_impoundment_days": max_impoundment,
                "unresolved_reason": output.unresolved_reason
            }

            # Cache result (LRU-style: xóa oldest nếu đầy)
            if len(_sanction_cache) >= MAX_CACHE_SIZE:
                oldest_key = next(iter(_sanction_cache))
                del _sanction_cache[oldest_key]
            _sanction_cache[cache_key] = sanction_details

            logger.info(
                f"[{session_id}] Sanction Agent xong. "
                f"Violations: {len(violations_dict)} | "
                f"Tổng phạt: {total_fine_min:,} - {total_fine_max:,} VNĐ"
            )

            return {"sanction_details": sanction_details}

        except Exception as e:
            logger.error(f"[{session_id}] Sanction Agent lỗi: {e}", exc_info=True)
            return {
                "errors": [f"sanction_error: {str(e)}"],
            }