"""Tenant administration endpoints (admins only): settings, onboarding, integration checks, dashboard."""
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from src.api.deps import get_current_user, get_tenant_db, require_admin
from src.api.schemas.tenant import OnboardingPayload, UpdateSettingsPayload
from src.db.database import get_db
from src.db.models import User
from src.security.cookies import set_auth_cookie
from src.services import tenant as service
from src.services.auth import session_token

router = APIRouter(prefix="/tenant", tags=["tenant"])


def _http(error: service.TenantError) -> HTTPException:
    status = 404 if isinstance(error, (service.CompanyNotFound, service.ServiceNotFound)) else 400
    return HTTPException(status_code=status, detail=str(error))


@router.post("/onboarding")
def complete_onboarding(payload: OnboardingPayload, response: Response, db: Session = Depends(get_db),
                        current_user: User = Depends(get_current_user)):
    require_admin(current_user, "Only superadmins can configure the tenant.")
    try:
        service.complete_onboarding(db, current_user, payload.github_token, payload.github_repo)
    except service.TenantError as e:
        raise _http(e) from None

    # A new token with the updated onboarding status.
    set_auth_cookie(response, session_token(current_user, onboarding_completed="true"))
    return {"status": "success", "message": "Tenant onboarding completed."}


@router.get("/settings")
def get_tenant_settings(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    try:
        return service.tenant_settings(db, current_user)
    except service.TenantError as e:
        raise _http(e) from None


@router.put("/settings")
def update_tenant_settings(payload: UpdateSettingsPayload, db: Session = Depends(get_db),
                           current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    try:
        service.update_settings(db, current_user, payload.changes())
    except service.TenantError as e:
        raise _http(e) from None
    return {"status": "success", "message": "Settings updated"}


@router.get("/test-github")
async def test_github_connection(current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    try:
        return await service.check_github_connection(current_user.company_id)
    except service.TenantError as e:
        raise _http(e) from e


@router.get("/test-logs")
async def test_log_connection(service_name: str, current_user: User = Depends(get_current_user)):
    """Fase 10.8 "Probar conexión" through the agent's own read-only client."""
    require_admin(current_user)
    try:
        return await service.check_log_connection(current_user.company_id, service_name)
    except service.TenantError as e:
        raise _http(e) from e


@router.get("/log-audit")
def get_log_access_audit(limit: int = 50, db: Session = Depends(get_tenant_db),
                         current_user: User = Depends(get_current_user)):
    """Fase 10.9: who made the agent read which service's logs, and when."""
    require_admin(current_user)
    return service.log_access_audit(db, current_user.company_id, limit)


@router.get("/dashboard")
def get_dashboard_metrics(db: Session = Depends(get_tenant_db), current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    return service.dashboard_metrics(db, current_user.company_id)


@router.get("/tickets/{external_id}")
def get_ticket_by_external_id(external_id: str, db: Session = Depends(get_tenant_db),
                              current_user: User = Depends(get_current_user)):
    """
    Looks up a ticket by the ITSM/SDK-side identifier the webhook received it
    with (Ticket.external_id), not our internal UUID. Ticket processing is
    async (job queue), so an SDK integration — or this project's own E2E test
    script — needs a way to poll for the outcome after a 202.
    """
    ticket = service.ticket_by_external_id(db, current_user.company_id, external_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    return ticket
