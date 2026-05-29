# ai/schemas/chat.py
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
    query: str = Field(..., description="Câu hỏi hoặc tình huống cần tư vấn về luật giao thông.")
    session_id: Optional[str] = Field(None, description="ID phiên để tiếp tục lịch sử hội thoại.")
    stream: bool = Field(False, description="Đặt True để nhận phản hồi dạng Server-Sent Events (SSE).")
    # Lịch sử hội thoại có thể truyền lên dưới dạng mảng các dict {"role": "user"/"assistant", "content": "..."}
    conversation_history: Optional[List[Dict[str, str]]] = Field(
        default_factory=list,
        description="Lịch sử hội thoại gần nhất (dùng nếu không lưu trữ lịch sử phía server)."
    )

class ChatResponse(BaseModel):
    final_response: str = Field(..., description="Câu trả lời cuối cùng từ trợ lý AI.")
    session_id: str = Field(..., description="ID phiên hội thoại.")
    primary_intent: str = Field(..., description="Intent cấp 1 (LEGAL_CHAT, GENERAL_CHAT, OUT_OF_SCOPE).")
    detailed_intent: str = Field(..., description="Intent cấp 2 (BEHAVIOR_ANALYSIS, PENALTY_LOOKUP, ADMIN_PROCEDURE, NONE).")
    is_compound: bool = Field(..., description="Câu hỏi có phải dạng phức hợp nhiều vế không.")
    sub_queries: List[str] = Field(..., description="Danh sách các câu hỏi con sau khi bóc tách.")
    retrieved_docs: List[Dict[str, Any]] = Field(default_factory=list, description="Danh sách tài liệu luật tìm được từ RAG.")
    extracted_facts: Optional[Dict[str, Any]] = Field(None, description="Tóm tắt tình huống và 4 yếu tố lỗi từ Analyst Agent.")
    legal_analysis: Optional[str] = Field(None, description="Chi tiết lập luận phân tích lỗi của Analyst Agent.")
    sanction_details: Optional[Dict[str, Any]] = Field(None, description="Khung tiền phạt và chế tài xử phạt bổ sung từ Sanction Agent.")
    errors: Optional[List[str]] = Field(default_factory=list, description="Danh sách lỗi phát sinh trong luồng xử lý.")
