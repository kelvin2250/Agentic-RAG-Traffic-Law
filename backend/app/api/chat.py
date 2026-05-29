import json
import logging
import uuid
import asyncio
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import httpx

from app.core.config import settings
from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.chat import ChatSession, ChatMessage
from app.schemas.chat import ChatRequest, ChatSessionResponse, ChatMessageResponse, ChatSessionCreate, SessionDetailResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/sessions", response_model=ChatSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    session_in: ChatSessionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Tạo mới một phiên hội thoại cho người dùng.
    """
    title = session_in.title or "Cuộc hội thoại mới"
    new_session = ChatSession(
        user_id=current_user.id,
        title=title
    )
    db.add(new_session)
    await db.commit()
    await db.refresh(new_session)
    return new_session


@router.get("/sessions", response_model=List[ChatSessionResponse])
async def list_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Lấy danh sách toàn bộ các phiên hội thoại của người dùng hiện tại.
    """
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == current_user.id)
        .order_by(ChatSession.updated_at.desc())
    )
    return result.scalars().all()


@router.get("/sessions/{session_id}", response_model=SessionDetailResponse)
async def get_session_details(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Lấy chi tiết của một phiên hội thoại và toàn bộ tin nhắn thuộc phiên đó.
    """
    # Xác minh xem session có thuộc quyền sở hữu của user không
    session_res = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id
        )
    )
    session = session_res.scalars().first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy phiên hội thoại hoặc bạn không có quyền truy cập."
        )

    # Lấy danh sách tin nhắn xếp theo thời gian tăng dần
    msg_res = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
    )
    messages = msg_res.scalars().all()

    return {
        "session": session,
        "messages": messages
    }


@router.delete("/sessions/{session_id}", status_code=status.HTTP_200_OK)
async def delete_session(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Xóa phiên hội thoại của người dùng khỏi Postgres và dọn dẹp cache memory trong AI service.
    """
    session_res = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id
        )
    )
    session = session_res.scalars().first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy phiên hội thoại hoặc bạn không có quyền truy cập."
        )

    await db.delete(session)
    await db.commit()

    # Dọn dẹp cache hội thoại ngắn hạn tại AI service bất đồng bộ (tránh block luồng chính)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.delete(f"{settings.ai_service_url}/api/v1/chat/sessions/{session_id}")
    except Exception as e:
        logger.warning(f"Không thể xóa cache session {session_id} trên AI Service: {e}")

    return {"status": "success", "message": "Đã xóa phiên hội thoại thành công."}


# from fastapi_limiter.depends import RateLimiter


# @router.post("/chat", dependencies=[Depends(RateLimiter(times=15, seconds=60))])
@router.post("/chat")
async def chat_with_agent(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    API gửi truy vấn tới AI Agent:
    1. Kiểm tra/Tạo phiên hội thoại mới.
    2. Lưu tin nhắn người dùng vào Postgres.
    3. Forward yêu cầu tới AI Service.
    4. Trả về kết quả (Hỗ trợ SSE streaming hoặc JSON).
    5. Lưu kết quả phản hồi của AI vào Postgres.
    """
    session_id = request.session_id
    history_payload = []

    # 1. Nếu không truyền session_id, tự động tạo mới
    if not session_id:
        new_session = ChatSession(
            user_id=current_user.id,
            title=request.query[:30] + "..." if len(request.query) > 30 else request.query
        )
        db.add(new_session)
        await db.commit()
        await db.refresh(new_session)
        session_id = new_session.id
    else:
        # Xác minh xem session có thuộc quyền sở hữu của user không
        session_res = await db.execute(
            select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.user_id == current_user.id
            )
        )
        session = session_res.scalars().first()
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Phiên hội thoại không hợp lệ hoặc bạn không có quyền truy cập."
            )
        # Cập nhật thời gian update phiên
        from datetime import datetime, timezone
        session.updated_at = datetime.now(timezone.utc)
        await db.commit()

        # Lấy tối đa 5 tin nhắn gần nhất của phiên này từ Postgres để làm context khôi phục (nếu Redis cache hết hạn)
        msg_res = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(5)
        )
        recent_messages = list(reversed(msg_res.scalars().all()))
        history_payload = [
            {"role": msg.role, "content": msg.content}
            for msg in recent_messages
        ]

    # 2. Lưu câu hỏi của người dùng vào Postgres
    user_message = ChatMessage(
        session_id=session_id,
        role="user",
        content=request.query
    )
    db.add(user_message)
    await db.commit()

    # Chuẩn bị payload gửi sang AI service
    # AI service sẽ tự quản lý short-term memory dựa trên Redis session_id
    ai_payload = {
        "query": request.query,
        "session_id": str(session_id),
        "stream": request.stream,
        "conversation_history": history_payload
    }
    logger.info(f"[{session_id}] Sending payload to AI service. History length: {len(history_payload)}. Content: {history_payload}")

    # 3. Luồng SSE Streaming (Nếu stream = True)
    if request.stream:
        async def sse_proxy_generator():
            event_type = None
            final_response_data = None
            last_error = None
            
            # Retry loop cho SSE streaming (xử lý AI service chưa sẵn sàng)
            for attempt in range(3):
                try:
                    async with httpx.AsyncClient(timeout=300.0) as client:
                        async with client.stream(
                            "POST",
                            f"{settings.ai_service_url}/api/v1/chat",
                            json=ai_payload
                        ) as response:
                            response.raise_for_status()
                            async for line in response.aiter_lines():
                                if not line:
                                    continue
                                
                                yield line + "\n"

                                if line.startswith("event: "):
                                    event_type = line[len("event: "):].strip()
                                elif line.startswith("data: ") and event_type == "done":
                                    try:
                                        final_response_data = json.loads(line[len("data: "):].strip())
                                    except Exception as e:
                                        logger.error(f"Lỗi parse dữ liệu done trong SSE: {e}")
                    
                    # Stream thành công, thoát retry loop
                    break
                    
                except httpx.ConnectError as e:
                    last_error = e
                    if attempt < 2:
                        wait = 2 ** attempt
                        logger.warning(f"⚠️ AI service chưa sẵn sàng, SSE retry sau {wait}s (lần {attempt + 1}/3)...")
                        yield f"event: status\ndata: {json.dumps({'status': 'connecting', 'message': f'Đang kết nối đến AI service (lần {attempt + 2})...'}, ensure_ascii=False)}\n\n"
                        await asyncio.sleep(wait)
                    else:
                        logger.error(f"❌ AI service không khả dụng sau 3 lần retry: {e}")
                        yield f"event: error\ndata: {json.dumps({'error': 'AI service hiện không khả dụng, vui lòng thử lại sau.'}, ensure_ascii=False)}\n\n"
                        return

            # Khi stream kết thúc, lưu câu trả lời cuối cùng vào PostgreSQL
            if final_response_data:
                assistant_content = final_response_data.get("final_response", "Lỗi sinh câu trả lời.")
                assistant_message = ChatMessage(
                    session_id=session_id,
                    role="assistant",
                    content=assistant_content,
                    metadata_json=final_response_data
                )
                async with db.begin_nested():
                    db.add(assistant_message)
                await db.commit()
                logger.info(f"[{session_id}] Đã lưu tin nhắn Assistant từ SSE vào DB.")

        return StreamingResponse(sse_proxy_generator(), media_type="text/event-stream")

    # 5. Luồng REST thông thường (Non-streaming)
    else:
        last_error = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=300.0) as client:
                    response = await client.post(
                        f"{settings.ai_service_url}/api/v1/chat",
                        json=ai_payload
                    )
                    response.raise_for_status()
                    data = response.json()
                break  # Thành công, thoát retry loop
            except httpx.ConnectError as e:
                last_error = e
                if attempt < 2:
                    wait = 2 ** attempt
                    logger.warning(f"⚠️ AI service REST retry sau {wait}s (lần {attempt + 1}/3)...")
                    await asyncio.sleep(wait)
                else:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="AI service hiện không khả dụng, vui lòng thử lại sau."
                    )
            except Exception as e:
                logger.error(f"Lỗi gọi AI service ở chế độ REST: {e}", exc_info=True)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Lỗi đồng bộ AI Service: {str(e)}"
                )

        # Lưu câu trả lời từ AI service vào Postgres
        assistant_content = data.get("final_response", "Xin lỗi, hệ thống không tạo được câu trả lời.")
        assistant_message = ChatMessage(
            session_id=session_id,
            role="assistant",
            content=assistant_content,
            metadata_json=data
        )
        db.add(assistant_message)
        await db.commit()

        return {
            "session_id": session_id,
            "role": "assistant",
            "content": assistant_content,
            "metadata": data
        }
