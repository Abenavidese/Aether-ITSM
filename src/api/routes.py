import logging
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Depends, Header
from sqlalchemy.orm import Session
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from src.agent.concierge import get_concierge_workflow
from src.agent.graph import get_workflow
from src.db.database import get_db, SessionLocal
from src.db.models import Company, User, Ticket
from src.security.deps import get_current_user
from src.security.api_keys import hash_api_key
from src.security.encryption import encrypt_token, decrypt_token
from src.security.limiter import limiter
from src.integrations.github import create_issue

logger = logging.getLogger(__name__)
router = APIRouter()

# Placeholder ROI heuristic applied to every autonomously-resolved ticket.
# Real per-category handle-time/labor-rate figures belong in SubscriptionPlan
# or a tenant setting once we have data to back them — these keep the
# dashboard pipeline honest end-to-end without pretending to be precise.
AUTONOMOUS_RESOLUTION_MINUTES_SAVED = 15
AUTONOMOUS_RESOLUTION_COST_SAVED_USD = 12.50


class TicketPayload(BaseModel):
    ticket_id: str
    summary: str
    description: str
    user_email: str
    image_base64: str | None = None

class ApprovalPayload(BaseModel):
    approved: bool
    approver_id: str


def _month_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _is_escalated(values: dict) -> bool:
    """True for every state shape that routes to escalate_node (see graph.py)."""
    return (
        bool(values.get("technical_error"))
        or values.get("compliance_passed") is False
        or values.get("human_approved") is False
        or values.get("assessed_risk") == 4
    )


async def _create_escalation_issue(db: Session, ticket: Ticket, values: dict) -> str | None:
    """
    Creates a GitHub Issue for an escalated ticket so the engineering team
    gets a real, actionable artifact — not just a status flag nobody looks
    at. Deliberately NOT an LLM-decided action (no tool_name for this in
    ExecutionPlanResult): escalation always creates an issue when GitHub is
    configured, regardless of what any node "decided" to do.

    Returns None (never raises) whenever an issue can't be created — a
    tenant that hasn't connected GitHub yet, an expired/undecryptable
    token, or a GitHub API failure must never block the ticket from being
    marked escalated.
    """
    company = db.query(Company).filter(Company.id == ticket.tenant_id).first()
    if not company or not company.github_token or not company.github_repo:
        return None

    token = decrypt_token(company.github_token)
    if not token:
        logger.warning("Could not decrypt github_token for company %s; skipping issue creation", ticket.tenant_id)
        return None

    reason = values.get("final_resolution") or "Escalated by Aether ITSM"
    title = f"[Aether] {ticket.title}"
    body = (
        f"**Ticket:** {ticket.external_id}\n\n"
        f"**Description:**\n{ticket.description}\n\n"
        f"**Escalation reason:** {reason}\n"
        f"**Compliance notes:** {values.get('compliance_notes') or 'N/A'}\n"
    )

    try:
        return await create_issue(company.github_repo, token, title, body)
    except Exception as e:
        logger.error("Failed to create GitHub issue for ticket %s: %s", ticket.external_id, e, exc_info=True)
        return None


async def _sync_ticket_from_snapshot(db: Session, ticket: Ticket, snapshot) -> None:
    """Reflects the graph's final (or paused) state onto the persisted Ticket row."""
    if snapshot is None:
        return

    if snapshot.next:
        # Still paused (e.g. draft_plan waiting on human approval).
        ticket.status = "pending_human"
        ticket.resolution_path = None
        db.commit()
        return

    values = snapshot.values
    if _is_escalated(values):
        ticket.status = "escalated"
        ticket.resolution_path = None
        ticket.github_issue_url = await _create_escalation_issue(db, ticket, values)
    else:
        ticket.status = "resolved"
        ticket.resolution_path = "human" if values.get("human_approved") is True else "autonomous"
        ticket.resolved_at = datetime.now(timezone.utc)
        ticket.estimated_time_saved_minutes = AUTONOMOUS_RESOLUTION_MINUTES_SAVED
        ticket.cost_saved_usd = AUTONOMOUS_RESOLUTION_COST_SAVED_USD

    db.commit()


async def run_agent_background(payload: TicketPayload, company_id: str, ticket_id: str, checkpointer, mcp_client):
    """Async background task to execute the LangGraph agent."""
    logger.info("Starting ASYNC agent for ticket %s (tenant %s)", payload.ticket_id, company_id)

    text_content = f"Title: {payload.summary}\n\nDescription: {payload.description}"

    if payload.image_base64:
        content = [
            {"type": "text", "text": text_content},
            {"type": "image_url", "image_url": {"url": payload.image_base64}}
        ]
    else:
        content = text_content

    initial_state = {
        "messages": [HumanMessage(content=content)],
        "ticket_id": payload.ticket_id,
        "company_id": company_id,
        "user_context": {"email": payload.user_email, "tenant_id": company_id},
        "assessed_risk": 4,
        "intent": "unknown"
    }

    # Namespace the thread by tenant so ticket IDs can never collide or be
    # resumed across companies (see approve_ticket for the matching check).
    # mcp_client rides along in `configurable` — the same LangGraph mechanism
    # already used for thread_id — so execution_agent_node can dispatch real
    # tool calls without reaching into any module-level global.
    config = {"configurable": {"thread_id": f"{company_id}:{payload.ticket_id}", "mcp_client": mcp_client}}
    app = get_workflow().compile(
        checkpointer=checkpointer,
        interrupt_after=["draft_plan"]
    )

    db = SessionLocal()
    try:
        async for step in app.astream(initial_state, config=config):
            for node_name, state_update in step.items():
                logger.info("--- Node '%s' finished (ASYNC) ---", node_name)

        logger.info("Graph execution finished or paused for %s", payload.ticket_id)

        snapshot = await app.aget_state(config)
        ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if ticket:
            await _sync_ticket_from_snapshot(db, ticket, snapshot)

    except Exception as e:
        logger.error("Failed executing graph: %s", e, exc_info=True)
        try:
            ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
            if ticket:
                ticket.status = "escalated"
                db.commit()
        except Exception:
            logger.error("Also failed to mark ticket %s as escalated after a crash", ticket_id, exc_info=True)
    finally:
        db.close()

async def _create_and_dispatch_ticket(
    db: Session, company: Company, user: User, external_id: str, title: str, description: str,
    background_tasks: BackgroundTasks, checkpointer, mcp_client,
) -> Ticket:
    """
    Persists a new Ticket and dispatches the full agent swarm in the
    background — shared by the webhook (Fase 0) and the chat Concierge's
    escalation path (Fase 5) so both funnel every ticket through the same
    monthly AI-resolution plan limit and the same background execution.
    Callers own their own monthly TICKET-count limit check beforehand (their
    error handling differs: the webhook rejects with 402, chat just degrades
    to a plain reply) — this only owns what happens once a ticket may exist.
    """
    ticket = Ticket(
        tenant_id=company.id, user_id=user.id, external_id=external_id,
        title=title, description=description, status="open",
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    plan = company.plan
    if plan:
        ai_resolutions_this_month = db.query(Ticket).filter(
            Ticket.tenant_id == company.id,
            Ticket.created_at >= _month_start(),
            Ticket.resolution_path.isnot(None),
        ).count()
        if ai_resolutions_this_month >= plan.max_ai_resolutions_per_month:
            # Ticket is logged, but this plan is out of AI resolutions for the
            # period — route straight to the human queue instead of invoking
            # the agent at all.
            ticket.status = "pending_human"
            db.commit()
            return ticket

    payload = TicketPayload(ticket_id=external_id, summary=title, description=description, user_email=user.email)
    background_tasks.add_task(run_agent_background, payload, company.id, ticket.id, checkpointer, mcp_client)
    return ticket


@router.post("/webhook/ticket", status_code=202)
@limiter.limit("30/minute")
async def receive_ticket_webhook(
    payload: TicketPayload,
    background_tasks: BackgroundTasks,
    request: Request,
    x_api_key: str = Header(...),
    db: Session = Depends(get_db)
):
    """
    Receives a ticket from ITSM/SDK integrations.
    Uses FastAPI BackgroundTasks which will schedule our async function in the event loop.
    """
    company = db.query(Company).filter(Company.api_key_hash == hash_api_key(x_api_key)).first()
    if not company:
        # Legacy rows created before API keys were hashed still hold the raw
        # key in `api_key`. Fall back once, then migrate the row in place so
        # this branch is never needed again for that tenant.
        company = db.query(Company).filter(Company.api_key == x_api_key).first()
        if company:
            company.api_key_hash = hash_api_key(x_api_key)
            company.api_key = encrypt_token(x_api_key)
            db.commit()

    if not company:
        raise HTTPException(status_code=401, detail="Invalid API Key")

    # Idempotency: ITSM/webhook senders retry on timeouts. Re-delivering the
    # same ticket_id must not re-run (and potentially re-execute) the agent.
    existing_ticket = db.query(Ticket).filter(
        Ticket.tenant_id == company.id, Ticket.external_id == payload.ticket_id
    ).first()
    if existing_ticket:
        return {
            "status": "Accepted",
            "message": "Ticket already received; not reprocessing.",
            "ticket_id": payload.ticket_id
        }

    # Every employee must have an Aether account for the SDK integration —
    # tickets are always attributed to a real, provisioned User, never a
    # bare email string.
    user = db.query(User).filter(
        User.email == payload.user_email, User.company_id == company.id
    ).first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No Aether account found for '{payload.user_email}' in this company. "
                "Add them under Settings > Users before creating tickets on their behalf."
            ),
        )

    plan = company.plan
    month_start = _month_start()

    if plan:
        tickets_this_month = db.query(Ticket).filter(
            Ticket.tenant_id == company.id, Ticket.created_at >= month_start
        ).count()
        if tickets_this_month >= plan.max_tickets_per_month:
            raise HTTPException(
                status_code=402,
                detail=f"Monthly ticket limit reached for your plan ({plan.max_tickets_per_month}).",
            )

    ticket = await _create_and_dispatch_ticket(
        db, company, user, payload.ticket_id, payload.summary, payload.description,
        background_tasks, request.app.state.checkpointer, request.app.state.mcp_client,
    )
    if ticket.status == "pending_human":
        return {
            "status": "Accepted",
            "message": "Monthly AI resolution limit reached; ticket routed to the human queue.",
            "ticket_id": payload.ticket_id
        }

    return {
        "status": "Accepted",
        "message": "Aether is reviewing the ticket asynchronously.",
        "ticket_id": payload.ticket_id
    }

@router.post("/approve/{ticket_id}")
async def approve_ticket(
    ticket_id: str,
    payload: ApprovalPayload,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Endpoint for admins to approve or reject a Risk Level 3 ticket.

    The thread is namespaced by the caller's own company_id, so a user can
    only ever address threads belonging to their own tenant — a different
    tenant's ticket_id simply resolves to a thread that doesn't exist here.
    """
    if current_user.role not in ["superadmin", "admin"]:
        raise HTTPException(status_code=403, detail="Not authorized.")

    thread_id = f"{current_user.company_id}:{ticket_id}"
    config = {"configurable": {"thread_id": thread_id, "mcp_client": request.app.state.mcp_client}}
    checkpointer = request.app.state.checkpointer

    app = get_workflow().compile(
        checkpointer=checkpointer,
        interrupt_after=["draft_plan"]
    )

    # Check state asynchronously
    state = await app.aget_state(config)
    if not state or not state.next:
        raise HTTPException(status_code=404, detail="Thread not found or not waiting for approval.")

    # Defense in depth: even if the thread namespace were ever bypassed
    # (e.g. a future checkpointer migration), refuse cross-tenant resumption.
    if state.values.get("company_id") != current_user.company_id:
        raise HTTPException(status_code=404, detail="Thread not found or not waiting for approval.")

    logger.info("Resuming paused thread %s with approval: %s", thread_id, payload.approved)

    # Record the human's decision in state *before* resuming — draft_plan's
    # outgoing edge (route_from_draft_plan) reads it to decide whether to
    # actually execute the approved plan or escalate a rejection, instead of
    # the previous behavior where both outcomes silently dead-ended at END.
    await app.aupdate_state(config, {"human_approved": payload.approved})

    try:
        async for step in app.astream(None, config=config):
            logger.info("--- Node finished during resumption (ASYNC) ---")
    except Exception as e:
        logger.error("Resumption failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error during resumption.")

    final_snapshot = await app.aget_state(config)
    ticket = db.query(Ticket).filter(
        Ticket.tenant_id == current_user.company_id, Ticket.external_id == ticket_id
    ).first()
    if ticket:
        await _sync_ticket_from_snapshot(db, ticket, final_snapshot)

    if payload.approved:
        return {"status": "Resumed", "message": "Plan approved and executed."}
    return {"status": "Rejected", "message": "Execution cancelled by human; ticket escalated."}


class ChatPayload(BaseModel):
    message: str


@router.post("/chat")
async def chat(
    payload: ChatPayload,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Fase 5 — synchronous chat endpoint for the employee portal. Auth is the
    normal session cookie (the employee is already logged in), not the
    webhook's x-api-key. One LangGraph thread per employee (not per ticket)
    so multi-turn context persists across messages; history lives only in
    the checkpointer (Fase 5.5 decision — no separate SQL transcript table).
    """
    thread_id = f"chat:{current_user.id}"
    config = {"configurable": {"thread_id": thread_id, "mcp_client": request.app.state.mcp_client}}
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
    async for _ in concierge_app.astream(initial_state, config=config):
        pass

    snapshot = await concierge_app.aget_state(config)
    reply = snapshot.values.get("final_response", "")
    resolved = snapshot.values.get("resolved", True)
    diagnosis_report = snapshot.values.get("diagnosis_report")

    if resolved:
        return {"reply": reply, "status": "resolved"}

    # Fase 5.3: the Concierge couldn't resolve it — create a real Ticket and
    # run it through the full swarm, same as a webhook-originated ticket.
    company = db.query(Company).filter(Company.id == current_user.company_id).first()
    plan = company.plan if company else None
    if plan:
        tickets_this_month = db.query(Ticket).filter(
            Ticket.tenant_id == company.id, Ticket.created_at >= _month_start()
        ).count()
        if tickets_this_month >= plan.max_tickets_per_month:
            return {
                "reply": f"{reply}\n\n(Your organization has reached its monthly ticket limit — please contact an admin.)",
                "status": "resolved",
            }

    external_id = f"chat-{uuid.uuid4().hex[:10]}"
    description = payload.message
    if diagnosis_report:
        # Evidence travels with the ticket, so the engineer (and the GitHub
        # issue built from this description on escalation) starts from the
        # real verdict and failing code location, not just "it's broken".
        description = f"{payload.message}\n\n--- Diagnóstico automático (Aether) ---\n{diagnosis_report}"
    ticket = await _create_and_dispatch_ticket(
        db, company, current_user, external_id, payload.message[:120], description,
        background_tasks, request.app.state.checkpointer, request.app.state.mcp_client,
    )
    return {"reply": reply, "status": "investigating", "ticket_external_id": ticket.external_id}
