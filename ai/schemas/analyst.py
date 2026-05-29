# ai/schemas/analyst.py
"""
Pydantic output schema cho Analyst Agent.
Tách ra khỏi agent module để tái sử dụng và giữ code clean.
"""
from pydantic import BaseModel, Field, field_validator
from typing import Any, Dict, List, Optional, Union

class AnalystOutput(BaseModel):
    """Kết quả phân tích pháp lý từ Legal Analyst Agent."""

    case_context: Dict[str, Any] = Field(
        description="Bộ nhớ ngữ cảnh vụ việc (Case Context Memory): loại xe, địa điểm, camera, tình tiết đặc biệt"
    )
    four_elements: Dict[str, Any] = Field(
        description="Phân tích 4 yếu tố cấu thành vi phạm hành chính: Chủ thể, Khách thể, Mặt chủ quan, Mặt khách quan"
    )
    is_violation: bool = Field(
        description="True nếu hành vi đủ 4 yếu tố cấu thành lỗi vi phạm. False nếu có bất khả kháng/tình thế cấp thiết."
    )
    legal_basis: Optional[List[str]] = Field(
        default=None,
        description="Danh sách các Điều, Khoản áp dụng trong retrieved_docs (VD: ['Điều 5 Nghị định 100/2019/NĐ-CP'])"
    )
    cot_trace: str = Field(
        description="Lập luận phân tích chi tiết từng bước (Chain-of-Thought) dẫn đến kết luận."
    )
    @field_validator("legal_basis", mode="before")
    @classmethod
    def coerce_to_list(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            return [s] if s else None
        if isinstance(v, list):
            return v or None
        return [str(v)]
