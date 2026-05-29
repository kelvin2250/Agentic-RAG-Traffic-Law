# services/agent-service/schemas/orchestrator.py
from typing import Literal, Optional, List
from pydantic import BaseModel, Field

class OrchestratorJSONOutput(BaseModel):
    primary_intent: Literal["GENERAL_CHAT", "OUT_OF_SCOPE", "LEGAL_CHAT"] = Field(
        description="Phân loại lớp đầu: GENERAL_CHAT (chào hỏi/cảm ơn/hỏi AI là ai), OUT_OF_SCOPE (không liên quan luật giao thông VN), LEGAL_CHAT (liên quan trực tiếp luật/thủ tục giao thông)."
    )
    detailed_intents: List[Literal["BEHAVIOR_ANALYSIS", "PENALTY_LOOKUP", "ADMIN_PROCEDURE"]] = Field(
        default_factory=list,
        description="Danh sách các phân loại intent chi tiết cần xử lý. Bắt buộc chứa ít nhất 1 phần tử nếu primary_intent là LEGAL_CHAT."
    )
    is_compound: bool = Field(
        description="Điền True nếu câu hỏi phức hợp (chứa >= 2 hành vi vi phạm khác nhau, hoặc chứa nhiều vế câu hỏi cần tra cứu độc lập). Điền False nếu câu hỏi đơn lẻ chỉ hỏi 1 ý."
    )
    sub_queries: List[str] = Field(
        description="Danh sách các câu hỏi đơn lẻ sau khi bẻ gãy từ query gốc. Nếu is_compound=False, danh sách này chỉ chứa duy nhất 1 phần tử là câu query gốc của user."
    )
    confidence_score: float = Field(
        description="Độ tin tưởng của việc phân tích ý định từ 0.0 đến 1.0"
    )
    reasoning_trace: str = Field(
        description="Chain-of-thought giải thích ngắn gọn lý do phân loại và bẻ sub-query bằng 1 câu."
    )