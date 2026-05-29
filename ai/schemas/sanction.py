# ai/schemas/sanction.py
"""
Pydantic output schemas cho Sanction Agent.
Tách ra khỏi agent module để tái sử dụng và giữ code clean.
"""
from typing import List, Optional
from pydantic import BaseModel, Field


class ViolationDetail(BaseModel):
    """Chi tiết lỗi vi phạm trích xuất trực tiếp từ văn bản pháp luật."""

    vehicle_type: str = Field(
        description="Loại xe áp dụng cho mức phạt này (ô tô, xe máy, xe đạp...)"
    )
    violation_name: str = Field(
        description="Tên lỗi vi phạm rõ ràng bằng tiếng Việt theo luật"
    )
    legal_basis: str = Field(
        description="Điều, Khoản, Điểm, Nghị định (VD: Điểm đ Khoản 5 Điều 5 Nghị định 100/2019/NĐ-CP)"
    )
    fine_min: int = Field(
        description="Mức phạt tiền tối thiểu (VNĐ). Điền 0 nếu không phạt tiền."
    )
    fine_max: int = Field(
        description="Mức phạt tiền tối đa (VNĐ). Điền 0 nếu không phạt tiền."
    )
    license_suspension_months: Optional[int] = Field(
        default=None,
        description="Thời gian tước GPLX tối đa nếu luật quy định (tháng)"
    )
    impoundment_days: Optional[int] = Field(
        default=None,
        description="Thời gian tạm giữ phương tiện/giam xe nếu luật quy định (ngày)"
    )


class SanctionOutput(BaseModel):
    """Mô hình dữ liệu đầu ra cấu trúc gọn nhẹ từ Sanction Agent."""

    violations: List[ViolationDetail] = Field(
        default_factory=list,
        description=(
            "Danh sách lỗi phạt trích xuất được. "
            "Nếu câu hỏi chung chung không rõ loại xe, hãy liệt kê toàn bộ phương tiện "
            "tìm thấy trong tài liệu luật đối với hành vi đó."
        )
    )
    unresolved_reason: Optional[str] = Field(
        default=None,
        description="Chịu trách nhiệm từ chối khi TÀI LIỆU HOÀN TOÀN KHÔNG có thông tin về hành vi này."
    )
