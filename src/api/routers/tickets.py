"""
Ticket endpoints: the ITSM/SDK webhook and the human approval of risk-3 plans.

Thin by design (roadmap 2.1/2.2): validation and HTTP mapping live here;
database work is in src/services/tickets.py (sync, run in worker threads so
it never blocks the event loop) and agent runs go through the durable job
queue (src/services/ticket_runs.py) instead of in-process BackgroundTasks.
"""
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from src.api.deps import get_current_user, require_admin
from src.api.schemas.tickets import ApprovalPayload, TicketPayload
from src.db.models import User
from src.security.limiter import limiter
from src.services import tickets as service
from src.services.ticket_runs import NotAwaitingApproval, resume_after_approval

logger = logging.getLogger(__name__)
router = APIRouter()


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
        raise HTTPException(status_code=401, detail="Invalid API Key") from None
    except service.UnknownEmployee as e:
        raise HTTPException(status_code=404, detail=(
            f"No Aether account found for '{e.email}' in this company. "
            "Add them under Settings > Users before creating tickets on their behalf."
        )) from e
    except service.TicketLimitReached as e:
        raise HTTPException(status_code=402, detail=f"Monthly ticket limit reached for your plan ({e.limit}).") from e

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
    """Endpoint for admins to approve or reject a Risk Level 3 ticket (see resume_after_approval)."""
    require_admin(current_user)
    try:
        await resume_after_approval(request.app.state.checkpointer, request.app.state.mcp_client,
                                    current_user.company_id, ticket_id, payload.approved)
    except NotAwaitingApproval:
        raise HTTPException(status_code=404, detail="Thread not found or not waiting for approval.") from None
    except Exception as e:
        logger.error("Resumption failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error during resumption.") from e

    if payload.approved:
        return {"status": "Resumed", "message": "Plan approved and executed."}
    return {"status": "Rejected", "message": "Execution cancelled by human; ticket escalated."}
