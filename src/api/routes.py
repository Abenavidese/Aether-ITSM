from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter()

class ChatRequest(BaseModel):
    message: str
    user_id: str
    thread_id: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    thread_id: str
    requires_approval: bool = False

@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    # TODO: Connect to LangGraph agent here
    return ChatResponse(
        response=f"Received: {request.message}. (Agent logic pending)",
        thread_id=request.thread_id or "new_thread_123"
    )

@router.post("/approve/{thread_id}")
async def approve_action(thread_id: str, approved: bool):
    # TODO: Resume LangGraph thread
    return {"status": "success", "thread_id": thread_id, "approved": approved}
