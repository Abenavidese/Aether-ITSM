"""Employee chat (Fase 5): session-cookie auth, one Concierge turn per request."""
from fastapi import APIRouter, Depends, Request

from src.api.deps import get_current_user
from src.api.schemas.tickets import ChatPayload
from src.core.config import get_settings
from src.db.models import User
from src.security.limiter import limiter, user_or_ip_key
from src.services.chat import run_chat_turn

router = APIRouter()


@router.post("/chat")
@limiter.limit(get_settings().chat_rate_limit, key_func=user_or_ip_key)
async def chat(
    payload: ChatPayload,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """
    Synchronous chat endpoint for the employee portal. Auth is the normal
    session cookie (the employee is already logged in), not the webhook's
    x-api-key. Unresolved turns come back with the ticket that was opened.
    """
    return await run_chat_turn(request.app.state.checkpointer, request.app.state.mcp_client,
                               current_user, payload.message, payload.image_base64)
