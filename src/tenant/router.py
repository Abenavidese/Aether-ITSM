import json
import logging
from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.orm import Session
from pydantic import BaseModel, field_validator, model_validator
from typing import Literal, Optional
from src.db.database import get_db
from src.db.models import User, Company, Ticket
from src.security.deps import get_current_user
from src.security.jwt import create_access_token
from src.security.encryption import encrypt_token, decrypt_token
from src.security.cookies import set_auth_cookie
from src.integrations.github import get_repo_info
import re

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tenant", tags=["tenant"])

# Only "owner/repo" — this value is interpolated straight into a GitHub API URL,
# so it must never contain path separators, "..", or scheme/host characters.
GITHUB_REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


LOG_SERVICE_ID_PATTERNS = {
    "render": re.compile(r"srv-[a-z0-9]{10,40}"),
    # The dashboard shows "prj_..." but drain payloads carry the bare id
    # (Vercel's own drain example: "gdufoJxB6b9b1fEqr1jUtFkyavUU"); accept
    # both — src/integrations/logs/vercel.py compares them normalized.
    "vercel": re.compile(r"(prj_)?[A-Za-z0-9]{10,40}"),
}
RENDER_OWNER_ID_PATTERN = re.compile(r"(tea|usr)-[a-z0-9]{10,40}")


def _set_write_only_secret(company: Company, column: str, value: Optional[str]) -> None:
    if value is None or value == "MASKED":
        return
    setattr(company, column, encrypt_token(value) if value else None)


def _validate_github_repo(v: Optional[str]) -> Optional[str]:
    if v and not GITHUB_REPO_PATTERN.match(v):
        raise ValueError("github_repo must be in the form 'owner/repo'")
    return v


class OnboardingPayload(BaseModel):
    llm_engine: str
    github_token: str
    github_repo: str

    _validate_repo = field_validator("github_repo")(_validate_github_repo)

@router.post("/onboarding")
def complete_onboarding(payload: OnboardingPayload, response: Response, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in ["superadmin", "admin"]:
        raise HTTPException(status_code=403, detail="Only superadmins can configure the tenant.")
    
    company = db.query(Company).filter(Company.id == current_user.company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")
        
    # Update settings
    company.llm_engine = payload.llm_engine
    company.github_token = encrypt_token(payload.github_token)
    company.github_repo = payload.github_repo
    company.onboarding_completed = "true"
    
    db.commit()
    
    # Generate a new token with the updated onboarding status
    token_data = {
        "sub": current_user.id,
        "email": current_user.email,
        "role": current_user.role,
        "tenant_id": current_user.company_id,
        "onboarding_completed": "true"
    }
    
    access_token = create_access_token(data=token_data)
    set_auth_cookie(response, access_token)

    return {
        "status": "success", 
        "message": "Tenant onboarding completed."
    }

@router.get("/settings")
def get_tenant_settings(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in ["superadmin", "admin"]:
        raise HTTPException(status_code=403, detail="Not authorized.")
        
    company = db.query(Company).filter(Company.id == current_user.company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")

    # api_key is stored encrypted (Fernet); decrypt only here, for the owning
    # tenant, to redisplay it. A None result means it's a pre-hardening row
    # that still holds the raw value — fall back to it as-is.
    displayed_api_key = None
    if company.api_key:
        displayed_api_key = decrypt_token(company.api_key)
        if displayed_api_key is None:
            displayed_api_key = company.api_key

    return {
        "github_token": "MASKED" if company.github_token else "",
        "github_repo": company.github_repo,
        "api_key": displayed_api_key,
        "webhook_url": company.webhook_url,
        "mcp_server_url": company.mcp_server_url,
        "llm_engine": company.llm_engine,
        "onboarding_completed": company.onboarding_completed == "true",
        "user_full_name": current_user.full_name,
        "user_job_title": current_user.job_title,
        "company_name": company.name,
        "monitored_services": json.loads(company.monitored_services) if company.monitored_services else [],
        "render_api_key": "MASKED" if company.render_api_key else "",
        "vercel_drain_secret": "MASKED" if company.vercel_drain_secret else "",
        # Relative to the API base; the frontend prefixes its own API URL.
        "vercel_drain_path": f"/integrations/vercel/drain/{company.id}",
    }

class MonitoredService(BaseModel):
    name: str
    url: str
    # Fase 10: optional link to the hosting platform's logs. These ids are
    # interpolated into platform API paths by the read-only client, so they
    # are validated to their exact documented shape here — never anything
    # that could smuggle "/", "..", "?" or "&" into a request.
    provider: Optional[Literal["render", "vercel"]] = None
    service_id: Optional[str] = None
    owner_id: Optional[str] = None

    @model_validator(mode="after")
    def _validate_log_source(self):
        if self.provider is None:
            if self.service_id or self.owner_id:
                raise ValueError("service_id/owner_id require a provider")
            return self
        pattern = LOG_SERVICE_ID_PATTERNS[self.provider]
        if not self.service_id or not pattern.fullmatch(self.service_id):
            raise ValueError(f"service_id for {self.provider} must match {pattern.pattern}")
        if self.provider == "render":
            if not self.owner_id or not RENDER_OWNER_ID_PATTERN.fullmatch(self.owner_id):
                raise ValueError(f"owner_id for render must match {RENDER_OWNER_ID_PATTERN.pattern}")
        elif self.owner_id:
            raise ValueError(f"owner_id is not used by {self.provider}")
        return self

class UpdateSettingsPayload(BaseModel):
    github_token: Optional[str] = None
    github_repo: Optional[str] = None
    llm_engine: Optional[str] = None
    user_full_name: Optional[str] = None
    company_name: Optional[str] = None
    monitored_services: Optional[list[MonitoredService]] = None
    # Write-only secrets: GET /settings returns "MASKED" for them, and
    # sending "MASKED" back (the frontend's untouched field) keeps the stored
    # value. An empty string clears it.
    render_api_key: Optional[str] = None
    vercel_drain_secret: Optional[str] = None

    _validate_repo = field_validator("github_repo")(_validate_github_repo)

    @field_validator("monitored_services")
    @classmethod
    def _unique_service_names(cls, v):
        # The agent resolves "which service?" by name, so names must be unique.
        if v is not None:
            names = [s.name.strip().lower() for s in v]
            if len(names) != len(set(names)):
                raise ValueError("monitored service names must be unique")
        return v

@router.put("/settings")
def update_tenant_settings(payload: UpdateSettingsPayload, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in ["superadmin", "admin"]:
        raise HTTPException(status_code=403, detail="Not authorized.")
        
    company = db.query(Company).filter(Company.id == current_user.company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")
        
    if payload.github_token is not None and payload.github_token != "MASKED":
        company.github_token = encrypt_token(payload.github_token)
    if payload.github_repo is not None:
        company.github_repo = payload.github_repo
    if payload.llm_engine is not None:
        company.llm_engine = payload.llm_engine
    if payload.company_name is not None:
        company.name = payload.company_name
        
    if payload.user_full_name is not None:
        current_user.full_name = payload.user_full_name
    if payload.monitored_services is not None:
        company.monitored_services = json.dumps(
            [s.model_dump(exclude_none=True) for s in payload.monitored_services]
        )
    _set_write_only_secret(company, "render_api_key", payload.render_api_key)
    _set_write_only_secret(company, "vercel_drain_secret", payload.vercel_drain_secret)

    db.commit()
    
    return {"status": "success", "message": "Settings updated"}

@router.get("/test-github")
async def test_github_connection(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in ["superadmin", "admin"]:
        raise HTTPException(status_code=403, detail="Not authorized.")

    company = db.query(Company).filter(Company.id == current_user.company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")

    if not company.github_token or not company.github_repo:
        raise HTTPException(status_code=400, detail="GitHub credentials not configured.")

    decrypted_token = decrypt_token(company.github_token)
    if not decrypted_token:
        raise HTTPException(status_code=400, detail="Invalid or old token. Please re-enter your GitHub token in Settings.")

    try:
        repo_data = await get_repo_info(company.github_repo, decrypted_token)
    except RuntimeError as e:
        logger.warning("GitHub connection test failed for company %s: %s", company.id, e)
        raise HTTPException(status_code=400, detail=f"Failed to connect: {e}")

    return {
        "status": "success",
        "message": f"Successfully connected to {repo_data['full_name']}!",
        "stars": repo_data.get("stargazers_count", 0),
        "open_issues": repo_data.get("open_issues_count", 0)
    }

@router.get("/test-logs")
async def test_log_connection(service_name: str, db: Session = Depends(get_db),
                              current_user: User = Depends(get_current_user)):
    """
    Fase 10.8 "Probar conexión": one read through the SAME read-only client
    the agent uses (GET service state), so a green result proves exactly the
    path the agent will take — not a separate code path.
    """
    if current_user.role not in ["superadmin", "admin"]:
        raise HTTPException(status_code=403, detail="Not authorized.")

    from src.integrations.logs.readonly_http import PlatformAPIError
    from src.integrations.logs.service import build_provider, get_log_services

    ref = next((s for s in get_log_services(current_user.company_id) if s.name == service_name), None)
    if ref is None:
        raise HTTPException(status_code=404, detail="No log-enabled service with that name.")
    provider = build_provider(current_user.company_id, ref)
    if provider is None:
        raise HTTPException(status_code=400, detail=f"{ref.provider} credentials not configured.")

    try:
        state = await provider.get_service_state(ref)
    except PlatformAPIError as e:
        logger.warning("Log connection test failed for company %s: %s", current_user.company_id, e)
        detail = "Invalid API key or no access to that service." if e.status_code in (401, 403, 404) else str(e)
        raise HTTPException(status_code=400, detail=f"Failed to connect: {detail}")

    return {
        "status": "success",
        "message": f"Connected to {ref.provider} service '{state.name or ref.service_id}'.",
        "suspended": state.suspended,
        "last_deploy_status": state.last_deploy_status,
    }


@router.get("/log-audit")
def get_log_access_audit(limit: int = 50, db: Session = Depends(get_db),
                         current_user: User = Depends(get_current_user)):
    """Fase 10.9: who made the agent read which service's logs, and when."""
    if current_user.role not in ["superadmin", "admin"]:
        raise HTTPException(status_code=403, detail="Not authorized.")
    from src.db.models import LogAccessAudit

    rows = (db.query(LogAccessAudit, User.email)
            .outerjoin(User, User.id == LogAccessAudit.user_id)
            .filter(LogAccessAudit.tenant_id == current_user.company_id)
            .order_by(LogAccessAudit.created_at.desc())
            .limit(max(1, min(limit, 200))).all())
    return [{
        "service_name": r.service_name, "provider": r.provider, "service_id": r.service_id,
        "triggered_by": email, "window_start": r.window_start, "window_end": r.window_end,
        "lines_returned": r.lines_returned, "verdict": r.verdict, "created_at": r.created_at,
    } for r, email in rows]


@router.get("/dashboard")
def get_dashboard_metrics(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in ["superadmin", "admin"]:
        raise HTTPException(status_code=403, detail="Not authorized.")
        
    company_id = current_user.company_id
    
    # Base query for all tickets in this tenant
    base_query = db.query(Ticket).filter(Ticket.tenant_id == company_id)
    
    total_tickets = base_query.count()
    resolved_tickets = base_query.filter(Ticket.status == "resolved").count()
    autonomous_tickets = base_query.filter(Ticket.resolution_path == "autonomous").count()
    pending_human = base_query.filter(Ticket.status == "pending_human").count()
    
    # Auto-deflection rate = (autonomous / total) * 100
    auto_deflection_rate = 0
    if total_tickets > 0:
        auto_deflection_rate = (autonomous_tickets / total_tickets) * 100
        
    # Calculate savings
    # Use SQLite compatible sum
    from sqlalchemy.sql import func
    savings = db.query(
        func.sum(Ticket.estimated_time_saved_minutes).label("time_saved"),
        func.sum(Ticket.cost_saved_usd).label("cost_saved")
    ).filter(Ticket.tenant_id == company_id).first()
    
    time_saved_hours = (savings.time_saved or 0) / 60
    cost_saved = savings.cost_saved or 0.0
    
    # Get recent tickets for stream
    recent_tickets = base_query.order_by(Ticket.created_at.desc()).limit(10).all()
    
    ticket_stream = []
    for t in recent_tickets:
        ticket_stream.append({
            "id": t.id,
            "external_id": t.external_id,
            "title": t.title,
            "description": t.description,
            "status": t.status,
            "urgency": t.urgency,
            "category": t.category,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "resolution_path": t.resolution_path,
            "github_issue_url": t.github_issue_url
        })
        
    return {
        "metrics": {
            "total_tickets": total_tickets,
            "resolved_tickets": resolved_tickets,
            "auto_deflection_rate": round(auto_deflection_rate, 1),
            "time_saved_hours": round(time_saved_hours, 1),
            "cost_saved_usd": round(cost_saved, 2),
            "pending_human": pending_human
        },
        "tickets": ticket_stream
    }


@router.get("/tickets/{external_id}")
def get_ticket_by_external_id(external_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Looks up a ticket by the ITSM/SDK-side identifier the webhook received it
    with (Ticket.external_id), not our internal UUID. Ticket processing is
    async (BackgroundTasks), so an SDK integration — or this project's own
    E2E test script — needs a way to poll for the outcome after a 202.
    """
    ticket = db.query(Ticket).filter(
        Ticket.tenant_id == current_user.company_id, Ticket.external_id == external_id
    ).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found.")

    return {
        "id": ticket.id,
        "external_id": ticket.external_id,
        "title": ticket.title,
        "status": ticket.status,
        "resolution_path": ticket.resolution_path,
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        "resolved_at": ticket.resolved_at.isoformat() if ticket.resolved_at else None,
        "estimated_time_saved_minutes": ticket.estimated_time_saved_minutes,
        "cost_saved_usd": ticket.cost_saved_usd,
        "github_issue_url": ticket.github_issue_url,
    }
