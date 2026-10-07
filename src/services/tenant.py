"""
Tenant administration: settings, onboarding, integration checks, the log
access audit and the dashboard. No FastAPI here — failures are the domain
errors below, mapped to HTTP by src/api/routers/tenant.py.
"""
import asyncio
import json
import logging

from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from src.db.database import SessionLocal
from src.db.models import Company, LogAccessAudit, Ticket, User
from src.integrations.github import get_repo_info
from src.integrations.platform_logs import service as platform_logs
from src.integrations.platform_logs.readonly_http import PlatformAPIError
from src.llm.factory import active_models
from src.security.encryption import decrypt_token, encrypt_token

logger = logging.getLogger(__name__)


class TenantError(Exception):
    """A request the tenant's current state can't satisfy; the message is user-facing."""


class CompanyNotFound(TenantError):
    def __init__(self):
        super().__init__("Company not found.")


class NotConfigured(TenantError):
    pass


class ConnectionFailed(TenantError):
    pass


class ServiceNotFound(TenantError):
    def __init__(self):
        super().__init__("No log-enabled service with that name.")


def _company(db: Session, company_id: str) -> Company:
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise CompanyNotFound()
    return company


def _set_write_only_secret(company: Company, column: str, value: str | None) -> None:
    if value is None or value == "MASKED":
        return
    setattr(company, column, encrypt_token(value) if value else None)


# ── settings & onboarding ────────────────────────────────────────────────────

def complete_onboarding(db: Session, user: User, github_token: str, github_repo: str) -> None:
    company = _company(db, user.company_id)
    company.github_token = encrypt_token(github_token)
    company.github_repo = github_repo
    company.onboarding_completed = "true"
    db.commit()


def tenant_settings(db: Session, user: User) -> dict:
    company = _company(db, user.company_id)

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
        # Read-only: models are platform configuration (src/llm/factory.py),
        # not a per-tenant choice — shown so the admin knows what answers them.
        "llm_models": active_models(),
        "onboarding_completed": company.onboarding_completed == "true",
        "user_full_name": user.full_name,
        "user_job_title": user.job_title,
        "company_name": company.name,
        "monitored_services": json.loads(company.monitored_services) if company.monitored_services else [],
        "render_api_key": "MASKED" if company.render_api_key else "",
        "vercel_drain_secret": "MASKED" if company.vercel_drain_secret else "",
        "code_fix_prs_enabled": bool(company.code_fix_prs_enabled),
        # Relative to the API base; the frontend prefixes its own API URL.
        "vercel_drain_path": f"/integrations/vercel/drain/{company.id}",
    }


def update_settings(db: Session, user: User, changes: dict) -> None:
    """changes: only the fields to update (already validated by the API schema)."""
    company = _company(db, user.company_id)

    if "github_token" in changes and changes["github_token"] != "MASKED":
        company.github_token = encrypt_token(changes["github_token"])
    if "github_repo" in changes:
        company.github_repo = changes["github_repo"]
    if "company_name" in changes:
        company.name = changes["company_name"]
    if "user_full_name" in changes:
        user.full_name = changes["user_full_name"]
    if "monitored_services" in changes:
        company.monitored_services = json.dumps(changes["monitored_services"])
    if "code_fix_prs_enabled" in changes:
        company.code_fix_prs_enabled = bool(changes["code_fix_prs_enabled"])
    _set_write_only_secret(company, "render_api_key", changes.get("render_api_key"))
    _set_write_only_secret(company, "vercel_drain_secret", changes.get("vercel_drain_secret"))

    db.commit()


# ── integration checks ───────────────────────────────────────────────────────

def _github_credentials(company_id: str) -> tuple[str, str]:
    """(repo, token) — plain DB work, run in a thread."""
    db = SessionLocal()
    try:
        company = _company(db, company_id)
        if not company.github_token or not company.github_repo:
            raise NotConfigured("GitHub credentials not configured.")
        token = decrypt_token(company.github_token)
        if not token:
            raise NotConfigured("Invalid or old token. Please re-enter your GitHub token in Settings.")
        return company.github_repo, token
    finally:
        db.close()


async def check_github_connection(company_id: str) -> dict:
    # DB lookups run off the event loop (roadmap 2.1); the GitHub call is async.
    repo, token = await asyncio.to_thread(_github_credentials, company_id)
    try:
        repo_data = await get_repo_info(repo, token)
    except RuntimeError as e:
        logger.warning("GitHub connection test failed for company %s: %s", company_id, e)
        raise ConnectionFailed(f"Failed to connect: {e}") from e

    return {
        "status": "success",
        "message": f"Successfully connected to {repo_data['full_name']}!",
        "stars": repo_data.get("stargazers_count", 0),
        "open_issues": repo_data.get("open_issues_count", 0)
    }


async def check_log_connection(company_id: str, service_name: str) -> dict:
    """
    Fase 10.8 "Probar conexión": one read through the SAME read-only client
    the agent uses (GET service state), so a green result proves exactly the
    path the agent will take — not a separate code path.
    """
    services = await asyncio.to_thread(platform_logs.get_log_services, company_id)
    ref = next((s for s in services if s.name == service_name), None)
    if ref is None:
        raise ServiceNotFound()
    provider = await asyncio.to_thread(platform_logs.build_provider, company_id, ref)
    if provider is None:
        raise NotConfigured(f"{ref.provider} credentials not configured.")

    try:
        state = await provider.get_service_state(ref)
    except PlatformAPIError as e:
        logger.warning("Log connection test failed for company %s: %s", company_id, e)
        detail = ("Invalid API key or no access to that service." if e.status_code in (401, 403, 404)
                  else f"platform API error ({e.status_code})")
        raise ConnectionFailed(f"Failed to connect: {detail}") from e

    return {
        "status": "success",
        "message": f"Connected to {ref.provider} service '{state.name or ref.service_id}'.",
        "suspended": state.suspended,
        "last_deploy_status": state.last_deploy_status,
    }


# ── read models ──────────────────────────────────────────────────────────────

def log_access_audit(db: Session, company_id: str, limit: int) -> list[dict]:
    """Fase 10.9: who made the agent read which service's logs, and when."""
    rows = (db.query(LogAccessAudit, User.email)
            .outerjoin(User, User.id == LogAccessAudit.user_id)
            .filter(LogAccessAudit.tenant_id == company_id)
            .order_by(LogAccessAudit.created_at.desc())
            .limit(max(1, min(limit, 200))).all())
    return [{
        "service_name": r.service_name, "provider": r.provider, "service_id": r.service_id,
        "triggered_by": email, "window_start": r.window_start, "window_end": r.window_end,
        "lines_returned": r.lines_returned, "verdict": r.verdict, "created_at": r.created_at,
    } for r, email in rows]


def dashboard_metrics(db: Session, company_id: str) -> dict:
    base_query = db.query(Ticket).filter(Ticket.tenant_id == company_id)

    total_tickets = base_query.count()
    resolved_tickets = base_query.filter(Ticket.status == "resolved").count()
    autonomous_tickets = base_query.filter(Ticket.resolution_path == "autonomous").count()
    pending_human = base_query.filter(Ticket.status == "pending_human").count()

    # Auto-deflection rate = (autonomous / total) * 100
    auto_deflection_rate = (autonomous_tickets / total_tickets) * 100 if total_tickets > 0 else 0

    savings = db.query(
        func.sum(Ticket.estimated_time_saved_minutes).label("time_saved"),
        func.sum(Ticket.cost_saved_usd).label("cost_saved")
    ).filter(Ticket.tenant_id == company_id).first()

    time_saved_hours = (savings.time_saved or 0) / 60
    cost_saved = savings.cost_saved or 0.0

    recent_tickets = base_query.order_by(Ticket.created_at.desc()).limit(10).all()
    ticket_stream = [{
        "id": t.id,
        "external_id": t.external_id,
        "title": t.title,
        "description": t.description,
        "status": t.status,
        "urgency": t.urgency,
        "category": t.category,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "resolution_path": t.resolution_path,
        "github_issue_url": t.github_issue_url,
        "fix_pr_url": t.fix_pr_url,
        "proposed_plan": t.proposed_plan,
    } for t in recent_tickets]

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


def ticket_by_external_id(db: Session, company_id: str, external_id: str) -> dict | None:
    ticket = db.query(Ticket).filter(Ticket.tenant_id == company_id, Ticket.external_id == external_id).first()
    if not ticket:
        return None
    return {
        "id": ticket.id,
        "external_id": ticket.external_id,
        "title": ticket.title,
        "status": ticket.status,
        "resolution_path": ticket.resolution_path,
        # Survives after the ticket leaves pending_human: shows what the
        # approval actually covered (Fase 11.2).
        "proposed_plan": ticket.proposed_plan,
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        "resolved_at": ticket.resolved_at.isoformat() if ticket.resolved_at else None,
        "estimated_time_saved_minutes": ticket.estimated_time_saved_minutes,
        "cost_saved_usd": ticket.cost_saved_usd,
        "github_issue_url": ticket.github_issue_url,
        "fix_pr_url": ticket.fix_pr_url,
    }
