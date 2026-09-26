"""Admin read API for agent traces, tokens and cost (roadmap 2.4)."""
from fastapi import APIRouter, Depends, HTTPException, Query

from src.db.models import User
from src.security.deps import get_current_user
from src.tickets.jobs import ticket_trace_id

from .usage import ticket_trace, usage_summary

router = APIRouter(prefix="/tenant", tags=["observability"])


def _require_admin(user: User) -> None:
    if user.role not in ["admin", "superadmin"]:
        raise HTTPException(status_code=403, detail="Not authorized.")


@router.get("/observability/usage")
def get_usage(days: int = Query(30, ge=1, le=365), current_user: User = Depends(get_current_user)):
    """Tokens, cost (per LLM_PRICES_JSON) and node latency for the caller's tenant."""
    _require_admin(current_user)
    return usage_summary(current_user.company_id, days)


@router.get("/tickets/{external_id}/trace")
def get_ticket_trace(external_id: str, current_user: User = Depends(get_current_user)):
    """Every node and LLM call of one ticket's agent run, in order."""
    _require_admin(current_user)
    spans = ticket_trace(current_user.company_id, ticket_trace_id(external_id))
    if not spans:
        raise HTTPException(status_code=404, detail="No trace recorded for that ticket.")
    return {"ticket_external_id": external_id, "spans": spans}
