# ai/api/v1/chat.py
import json
import logging
import uuid
import asyncio
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, AIMessage

from ai.api.deps import get_compiled_graph
from ai.schemas.chat import ChatRequest, ChatResponse
from ai.agents.state import AgentState

logger = logging.getLogger("ai.api.chat")
router = APIRouter()


def convert_history_to_messages(history: list) -> list:
    """
    Chuyển đổi danh sách lịch sử tin nhắn dạng dict sang đối tượng BaseMessage của LangChain.
    """
    messages = []
    if not history:
        return messages
        
    for msg in history:
        role = msg.get("role", "").lower()
        content = msg.get("content", "")
        if role in ("user", "human"):
            messages.append(HumanMessage(content=content))
        elif role in ("assistant", "ai", "system_gen", "bot"):
            messages.append(AIMessage(content=content))
    return messages


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    request: ChatRequest,
    graph: Any = Depends(get_compiled_graph)
):
    """
    Endpoint giao tiếp với AI Agent.
    Hỗ trợ cả chế độ thường (non-stream) và Server-Sent Events (SSE) streaming.
    """
    session_id = request.session_id or f"session_{uuid.uuid4().hex[:12]}"
    
    # ── Tải lịch sử và tóm tắt hội thoại từ Memory ──
    conversation_summary = ""
    if not request.conversation_history:
        from ai.infrastructure.memory import memory
        conversation_summary, history_messages = await memory.load(session_id)
    else:
        history_messages = convert_history_to_messages(request.conversation_history)
    
    # ── Chuẩn bị State đầu vào cho Graph ──────────────────────────────────────
    inputs = {
        "user_query": request.query,
        "session_id": session_id,
        "conversation_history": history_messages,
        "conversation_summary": conversation_summary,
        "retry_count": 0,
        "max_retries": 3,
        "errors": []
    }
    
    # ── 1. Trường hợp sử dụng SSE Streaming ─────────────────────────────────
    if request.stream:
        from ai.agents.answer_generate import set_stream_queue
        
        async def event_generator():
            final_state: Dict[str, Any] = {}
            token_queue: asyncio.Queue = asyncio.Queue()
            set_stream_queue(token_queue)
            
            async def run_graph():
                try:
                    async for chunk in graph.astream(inputs, stream_mode="updates"):
                        for node_name, node_update in chunk.items():
                            for k, v in node_update.items():
                                if k == "retrieved_docs" and k in final_state:
                                    final_state[k] = list(final_state[k]) + list(v)
                                elif k == "errors" and k in final_state:
                                    final_state[k] = list(final_state[k]) + list(v)
                                else:
                                    final_state[k] = v
                                    
                            s_updates = {}
                            for k, v in node_update.items():
                                if k == "conversation_history":
                                    s_updates[k] = [{"role": "user" if isinstance(m, HumanMessage) else "assistant", "content": m.content} for m in v]
                                elif k == "retrieved_docs":
                                    s_updates[k] = [{"page_content": d.get("page_content", ""), "metadata": d.get("metadata", {}), "score": d.get("score", 0.0)} for d in v]
                                elif k == "final_response":
                                    pass
                                else:
                                    s_updates[k] = v
                            if s_updates:
                                await token_queue.put(f"event: node_update\ndata: {json.dumps({node_name: s_updates}, ensure_ascii=False)}\n\n")
                except Exception as e:
                    logger.error(f"[{session_id}] Graph error: {e}", exc_info=True)
                    await token_queue.put(f"event: error\ndata: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n")
                finally:
                    set_stream_queue(None)
                    await token_queue.put(None)
            
            graph_task = asyncio.create_task(run_graph())
            
            try:
                while True:
                    try:
                        item = await asyncio.wait_for(token_queue.get(), timeout=0.15)
                    except asyncio.TimeoutError:
                        continue  # Không có item mới, thử lại
                    
                    if item is None:
                        break
                    if isinstance(item, str):
                        yield item
                    elif isinstance(item, dict) and "token" in item:
                        yield f"data: {json.dumps({'token': item['token']}, ensure_ascii=False)}\n\n"
                
                await graph_task
                
                final_response = final_state.get("final_response", "Xin lỗi, hệ thống không thể xử lý yêu cầu.")
                response_data = ChatResponse(
                    final_response=final_response,
                    session_id=session_id,
                    primary_intent=final_state.get("primary_intent", "NONE"),
                    detailed_intent=final_state.get("detailed_intent", "NONE"),
                    is_compound=final_state.get("is_compound", False),
                    sub_queries=final_state.get("sub_queries", []),
                    retrieved_docs=final_state.get("retrieved_docs", []),
                    extracted_facts=final_state.get("extracted_facts"),
                    legal_analysis=final_state.get("legal_analysis"),
                    sanction_details=final_state.get("sanction_details"),
                    errors=final_state.get("errors", [])
                )
                yield f"event: done\ndata: {response_data.model_dump_json(by_alias=True)}\n\n"
                
                from ai.infrastructure.memory import memory
                new_history = history_messages + [
                    HumanMessage(content=request.query),
                    AIMessage(content=final_response)
                ]
                await memory.save(session_id, new_history)
                
            except asyncio.TimeoutError:
                logger.error(f"[{session_id}] SSE stream timeout")
            except Exception as e:
                logger.error(f"[{session_id}] SSE stream error: {e}", exc_info=True)
                yield f"event: error\ndata: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
 
        return StreamingResponse(event_generator(), media_type="text/event-stream")
        
    # ── 2. Trường hợp trả về JSON thông thường (Non-stream) ───────────────────
    else:
        try:
            result = await graph.ainvoke(inputs)
            final_response = result.get("final_response") or "Xin lỗi, không có câu trả lời nào được tạo ra."
            
            # Lưu lịch sử hội thoại mới vào Redis
            from ai.infrastructure.memory import memory
            new_history = history_messages + [
                HumanMessage(content=request.query),
                AIMessage(content=final_response)
            ]
            await memory.save(session_id, new_history)
            
            # Đảm bảo các thuộc tính mặc định không bị thiếu
            return ChatResponse(
                final_response=final_response,
                session_id=session_id,
                primary_intent=result.get("primary_intent", "NONE"),
                detailed_intent=result.get("detailed_intent", "NONE"),
                is_compound=result.get("is_compound", False),
                sub_queries=result.get("sub_queries", [request.query]),
                retrieved_docs=result.get("retrieved_docs", []),
                extracted_facts=result.get("extracted_facts"),
                legal_analysis=result.get("legal_analysis"),
                sanction_details=result.get("sanction_details"),
                errors=result.get("errors", [])
            )
        except Exception as e:
            logger.error(f"[{session_id}] REST API chat error: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Lỗi hệ thống: {str(e)}")


@router.delete("/sessions/{session_id}", status_code=200)
async def clear_session_endpoint(session_id: str):
    """
    Xóa cache memory (summary & history) của session_id trong Redis/RAM.
    """
    try:
        from ai.infrastructure.memory import memory
        await memory.clear(session_id)
        return {"status": "success", "message": f"Cleared memory cache for session {session_id}"}
    except Exception as e:
        logger.error(f"Error clearing session memory {session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
