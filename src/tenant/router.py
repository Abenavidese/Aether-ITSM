from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.orm import Session
from pydantic import BaseModel, field_validator
from typing import Optional
from src.db.database import get_db
from src.db.models import User, Company, Ticket
from src.security.deps import get_current_user
from src.security.jwt import create_access_token
from src.security.encryption import encrypt_token, decrypt_token
from src.security.cookies import set_auth_cookie
import re

router = APIRouter(prefix="/tenant", tags=["tenant"])

# Only "owner/repo" — this value is interpolated straight into a GitHub API URL,
# so it must never contain path separators, "..", or scheme/host characters.
GITHUB_REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


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
        "company_name": company.name
    }

class UpdateSettingsPayload(BaseModel):
    github_token: Optional[str] = None
    github_repo: Optional[str] = None
    llm_engine: Optional[str] = None
    user_full_name: Optional[str] = None
    company_name: Optional[str] = None

    _validate_repo = field_validator("github_repo")(_validate_github_repo)

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
        
    db.commit()
    
    return {"status": "success", "message": "Settings updated"}

import httpx

@router.get("/test-github")
async def test_github_connection(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    print(f"--- TESTING GITHUB CONNECTION FOR USER {current_user.email} ---")
    if current_user.role not in ["superadmin", "admin"]:
        print("Error: User is not an admin.")
        raise HTTPException(status_code=403, detail="Not authorized.")
        
    company = db.query(Company).filter(Company.id == current_user.company_id).first()
    if not company:
        print("Error: Company not found.")
        raise HTTPException(status_code=404, detail="Company not found.")
        
    print(f"Company Token: {'SET' if company.github_token else 'MISSING'}")
    print(f"Company Repo: {company.github_repo or 'MISSING'}")
        
    if not company.github_token or not company.github_repo:
        raise HTTPException(status_code=400, detail="GitHub credentials not configured.")
        
    decrypted_token = decrypt_token(company.github_token)
    if not decrypted_token:
        print("Error: Could not decrypt token (maybe it's an old plaintext token?)")
        raise HTTPException(status_code=400, detail="Invalid or old token. Please re-enter your GitHub token in Settings.")

    headers = {
        "Authorization": f"Bearer {decrypted_token}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    url = f"https://api.github.com/repos/{company.github_repo}"
    print(f"Sending GET request to: {url}")
    
    # Try fetching the repo asynchronously
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
    
    print(f"GitHub API Response Status: {response.status_code}")
    
    if response.status_code == 200:
        repo_data = response.json()
        print("Success! Connection established.")
        return {
            "status": "success",
            "message": f"Successfully connected to {repo_data['full_name']}!",
            "stars": repo_data.get("stargazers_count", 0),
            "open_issues": repo_data.get("open_issues_count", 0)
        }
    else:
        error_msg = response.json().get('message', 'Unknown error')
        print(f"GitHub API Error: {error_msg}")
        raise HTTPException(status_code=400, detail=f"Failed to connect: {error_msg}")

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
            "title": t.title,
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
    }
