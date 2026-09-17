import logging
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Depends, Header
from sqlalchemy.orm import Session
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from src.agent.graph import get_workflow
from src.db.database import get_db
from src.db.models import Company, User
from src.security.deps import get_current_user
from src.security.api_keys import hash_api_key
from src.security.encryption import encrypt_token
from src.security.limiter import limiter

logger = logging.getLogger(__name__)
router = APIRouter()

class TicketPayload(BaseModel):
    ticket_id: str
    summary: str
    description: str
    user_id: str
    image_base64: str | None = None

class ApprovalPayload(BaseModel):
    approved: bool
    approver_id: str

async def run_agent_background(payload: TicketPayload, company_id: str, checkpointer):
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
        "user_context": {"email": payload.user_id, "tenant_id": company_id},
        "assessed_risk": 4,
        "intent": "unknown"
    }

    # Namespace the thread by tenant so ticket IDs can never collide or be
    # resumed across companies (see approve_ticket for the matching check).
    config = {"configurable": {"thread_id": f"{company_id}:{payload.ticket_id}"}}
    
    try:
        app = get_workflow().compile(
            checkpointer=checkpointer,
            interrupt_after=["draft_plan"]
        )
        
        # ASYNC STREAMING
        async for step in app.astream(initial_state, config=config):
            for node_name, state_update in step.items():
                logger.info("--- Node '%s' finished (ASYNC) ---", node_name)
                
        logger.info("Graph execution finished or paused for %s", payload.ticket_id)
            
    except Exception as e:
        logger.error("Failed executing graph: %s", e, exc_info=True)

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
    Receives a ticket from ITSM.
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

    checkpointer = request.app.state.checkpointer
    background_tasks.add_task(run_agent_background, payload, company.id, checkpointer)
    
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
    current_user: User = Depends(get_current_user)
):
    """
    Endpoint for IT Agents to approve a Risk Level 3 ticket.

    The thread is namespaced by the caller's own company_id, so a user can
    only ever address threads belonging to their own tenant — a different
    tenant's ticket_id simply resolves to a thread that doesn't exist here.
    """
    if current_user.role not in ["superadmin", "admin", "employee"]:
        raise HTTPException(status_code=403, detail="Not authorized.")

    thread_id = f"{current_user.company_id}:{ticket_id}"
    config = {"configurable": {"thread_id": thread_id}}
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
    
    if payload.approved:
        try:
            async for step in app.astream(None, config=config):
                logger.info("--- Node finished during resumption (ASYNC) ---")
            return {"status": "Resumed", "message": "Ticket execution resumed."}
        except Exception as e:
            logger.error("Resumption failed: %s", e, exc_info=True)
            raise HTTPException(status_code=500, detail="Internal server error during resumption.")
    else:
        return {"status": "Rejected", "message": "Execution cancelled by human."}
