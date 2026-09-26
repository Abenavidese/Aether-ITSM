"""
Agent-facing HTTP endpoints: ticket webhook, human approval, employee chat.

Thin by design (roadmap 2.1/2.2): validation and HTTP mapping live here;
database work is in src/tickets/service.py (sync, run in worker threads so
it never blocks the event loop) and agent runs for tickets go through the
durable job queue (src/tickets/jobs.py) instead of in-process BackgroundTasks.
"""
import asyncio
import logging
import re
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field, field_validator

from src.agent.concierge import get_concierge_workflow
from src.config import get_settings
from src.db.models import User
from src.security.deps import get_current_user
from src.security.limiter import limiter, user_or_ip_key
from src.tickets import service
from src.observability.tracing import trace_scope
from src.tickets.jobs import awaiting_approval, ticket_graph, ticket_thread_config, ticket_trace_id

logger = logging.getLogger(__name__)
router = APIRouter()


# Input limits (Fase 11.6): every field below ends up in an LLM prompt, a DB
# row and possibly a GitHub issue — unbounded input is unbounded cost and a
# way to push the system prompt out of the context window.
_IMAGE_DATA_URI = re.compile(r"^data:image/(png|jpeg|webp);base64,[A-Za-z0-9+/]+={0,2}$")
MAX_IMAGE_DATA_URI_CHARS = 7_000_000  # ~5 MB image


class TicketPayload(BaseModel):
    ticket_id: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    summary: str = Field(..., min_length=1, max_length=300)
    description: str = Field(..., max_length=10_000)
    user_email: str = Field(..., max_length=150)
    image_base64: str | None = Field(default=None, max_length=MAX_IMAGE_DATA_URI_CHARS)

    @field_validator("image_base64")
    @classmethod
    def _inline_image_only(cls, v):
        # Only an inline image. A plain URL here would be fetched by whatever
        # model provider receives it — i.e. an attacker-chosen URL requested
        # on our behalf.
        if v is not None and not _IMAGE_DATA_URI.fullmatch(v):
            raise ValueError("image_base64 must be a data:image/(png|jpeg|webp);base64 URI")
        return v


class ApprovalPayload(BaseModel):
    approved: bool
    approver_id: str


class ChatPayload(BaseModel):
    message: str = Field(..., min_length=1, max_length=get_settings().chat_message_max_chars)


@router.post("/webhook/ticket", status_code=202)
@limiter.limit("30/minute")
def receive_ticket_webhook(payload: TicketPayload, request: Request, x_api_key: str = Header(...)):
    """
    Receives a ticket from ITSM/SDK integrations. Answers 202 at once: the
    ticket and its agent-run job are committed together and a queue worker
    picks it up (ITSM platforms expect a reply within a few seconds, an
    agent run takes tens of seconds). A plain `def`: FastAPI runs it in a
    worker thread, since all it does is database work.
    """
    try:
        accepted = service.accept_webhook_ticket(
            x_api_key, payload.ticket_id, payload.summary, payload.description, payload.user_email,
            payload.image_base64,
        )
    except service.InvalidApiKey:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    except service.UnknownEmployee as e:
        raise HTTPException(status_code=404, detail=(
            f"No Aether account found for '{e.email}' in this company. "
            "Add them under Settings > Users before creating tickets on their behalf."
        ))
    except service.TicketLimitReached as e:
        raise HTTPException(status_code=402, detail=f"Monthly ticket limit reached for your plan ({e.limit}).")

    if accepted.duplicate:
        message = "Ticket already received; not reprocessing."
    elif accepted.routed_to_humans:
        message = "Monthly AI resolution limit reached; ticket routed to the human queue."
    else:
        message = "Aether is reviewing the ticket asynchronously."
    return {"status": "Accepted", "message": message, "ticket_id": payload.ticket_id}


@router.post("/approve/{ticket_id}")
async def approve_ticket(
    ticket_id: str,
    payload: ApprovalPayload,
    request: Request,
    current_user: User = Depends(get_current_user)
):
    """
    Endpoint for admins to approve or reject a Risk Level 3 ticket.

    The thread is namespaced by the caller's own company_id, so a user can
    only ever address threads belonging to their own tenant — a different
    tenant's ticket_id simply resolves to a thread that doesn't exist here.
    Resuming runs inline: after approval, execution is the frozen action
    (no LLM call, Fase 11.2) or an escalation, both fast.
    """
    if current_user.role not in ["superadmin", "admin"]:
        raise HTTPException(status_code=403, detail="Not authorized.")

    app = ticket_graph(request.app.state.checkpointer)
    config = ticket_thread_config(current_user.company_id, ticket_id, request.app.state.mcp_client)

    state = await app.aget_state(config)
    # Defense in depth: even if the thread namespace were ever bypassed
    # (e.g. a future checkpointer migration), refuse cross-tenant resumption.
    if not state or not awaiting_approval(state) or state.values.get("company_id") != current_user.company_id:
        raise HTTPException(status_code=404, detail="Thread not found or not waiting for approval.")

    logger.info("Resuming paused ticket %s with approval: %s", ticket_id, payload.approved)
    # Record the human's decision in state *before* resuming — draft_plan's
    # outgoing edge (route_from_draft_plan) reads it to decide whether to run
    # the approved action or escalate a rejection.
    await app.aupdate_state(config, {"human_approved": payload.approved})
    try:
        async with trace_scope(ticket_trace_id(ticket_id), "ticket", current_user.company_id):
            async for _ in app.astream(None, config=config):
                pass
    except Exception as e:
        logger.error("Resumption failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error during resumption.")

    final = await app.aget_state(config)
    await asyncio.to_thread(service.apply_graph_outcome, current_user.company_id, ticket_id,
                            final.values, awaiting_approval(final))

    if payload.approved:
        return {"status": "Resumed", "message": "Plan approved and executed."}
    return {"status": "Rejected", "message": "Execution cancelled by human; ticket escalated."}


@router.post("/chat")
@limiter.limit(get_settings().chat_rate_limit, key_func=user_or_ip_key)
async def chat(
    payload: ChatPayload,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """
    Fase 5 — synchronous chat endpoint for the employee portal. Auth is the
    normal session cookie (the employee is already logged in), not the
    webhook's x-api-key. One LangGraph thread per employee (not per ticket)
    so multi-turn context persists across messages; history lives only in
    the checkpointer (Fase 5.5 decision — no separate SQL transcript table).
    """
    config = {"configurable": {"thread_id": f"chat:{current_user.id}", "mcp_client": request.app.state.mcp_client}}
    concierge_app = get_concierge_workflow().compile(checkpointer=request.app.state.checkpointer)

    initial_state = {
        "messages": [HumanMessage(content=payload.message)],
        "user_context": {
            "email": current_user.email, "tenant_id": current_user.company_id,
            # role gates raw platform-log lines (Fase 10.6); user_id is
            # recorded in the log access audit (Fase 10.9).
            "role": current_user.role, "user_id": current_user.id,
        },
        "diagnosis_report": None,
    }
    async with trace_scope(f"chat:{uuid.uuid4().hex}", "chat", current_user.company_id):
        async for _ in concierge_app.astream(initial_state, config=config):
            pass

    values = (await concierge_app.aget_state(config)).values
    reply = values.get("final_response", "")
    if values.get("resolved", True):
        return {"reply": reply, "status": "resolved"}

    # Fase 5.3: the Concierge couldn't resolve it — create a real Ticket and
    # run it through the full swarm (via the queue), same as a webhook ticket.
    description = payload.message
    if values.get("diagnosis_report"):
        # Evidence travels with the ticket, so the engineer (and the GitHub
        # issue built from this description on escalation) starts from the
        # real verdict and failing code location, not just "it's broken".
        description = f"{payload.message}\n\n--- Diagnóstico automático (Aether) ---\n{values['diagnosis_report']}"
    external_id = await asyncio.to_thread(
        service.open_chat_ticket, current_user.id, f"chat-{uuid.uuid4().hex[:10]}",
        payload.message[:120], description,
    )
    if external_id is None:
        return {
            "reply": f"{reply}\n\n(Your organization has reached its monthly ticket limit — please contact an admin.)",
            "status": "resolved",
        }
    return {"reply": reply, "status": "investigating", "ticket_external_id": external_id}
