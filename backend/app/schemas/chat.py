import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class ChatSessionCreate(BaseModel):
    title: Optional[str] = Field(None, description="Tiêu đề phiên chat (Tự động sinh nếu trống)")


class ChatSessionResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ChatMessageResponse(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: str
    metadata_json: Optional[Dict[str, Any]] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ChatRequest(BaseModel):
    query: str = Field(..., description="Câu hỏi hoặc tình huống giao thông")
    session_id: Optional[uuid.UUID] = Field(None, description="ID phiên chat hiện tại. Nếu trống sẽ tự động tạo mới.")
    stream: bool = Field(False, description="Đặt True để nhận dữ liệu Server-Sent Events (SSE)")


class SessionDetailResponse(BaseModel):
    session: ChatSessionResponse
    messages: List[ChatMessageResponse]

    class Config:
        from_attributes = True
