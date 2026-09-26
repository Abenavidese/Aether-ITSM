from sqlalchemy import Column, String, ForeignKey, DateTime, Integer, Float, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from .database import Base
import uuid

class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"
    
    id = Column(String, primary_key=True)
    name = Column(String) # Free, Pro, Enterprise
    price_usd = Column(Float, default=0.0)
    
    max_users = Column(Integer, default=2)
    max_tickets_per_month = Column(Integer, default=100)
    max_ai_resolutions_per_month = Column(Integer, default=50)


class Company(Base):
    __tablename__ = "companies"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, index=True)
    company_size = Column(String, nullable=True)
    industry = Column(String, nullable=True)
    current_tool = Column(String, nullable=True)
    
    # Integration & Onboarding Settings
    onboarding_completed = Column(String, default="false") # SQLite boolean compatibility
    api_key = Column(String, unique=True, nullable=True)  # Fernet-encrypted — decrypted only for display in Settings
    api_key_hash = Column(String, unique=True, nullable=True, index=True)  # SHA-256 — used to verify webhook calls
    webhook_url = Column(String, nullable=True) # Kept for legacy
    github_token = Column(String, nullable=True)
    github_repo = Column(String, nullable=True)
    mcp_server_url = Column(String, nullable=True)
    mcp_auth_token = Column(String, nullable=True)
    llm_engine = Column(String, default="nemotron-nano")
    # JSON-encoded list of {"name": str, "url": str} — services the agent can
    # healthcheck via the check_service_status MCP tool (see src/tools/mcp_server.py).
    # Optional per-entry {"provider", "service_id", "owner_id"} link a service
    # to its hosting platform's logs (Fase 10, src/integrations/logs/).
    monitored_services = Column(String, nullable=True)
    # Fernet-encrypted, never returned by the API (always "MASKED"). A Render
    # API key has FULL account access (Render has no read-only key scope), so
    # read-only is enforced in code: src/integrations/logs/readonly_http.py.
    render_api_key = Column(String, nullable=True)
    # Fernet-encrypted shared secret Vercel signs Log Drain payloads with.
    vercel_drain_secret = Column(String, nullable=True)
    
    plan_id = Column(String, ForeignKey("subscription_plans.id"), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    plan = relationship("SubscriptionPlan")
    users = relationship("User", back_populates="company")

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, index=True)
    full_name = Column(String, nullable=False)
    job_title = Column(String, nullable=True)
    primary_goal = Column(String, nullable=True)
    password_hash = Column(String)
    role = Column(String, default="employee") # superadmin, admin, employee
    company_id = Column(String, ForeignKey("companies.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    company = relationship("Company", back_populates="users")
    tickets = relationship("Ticket", back_populates="user")


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_id", name="uq_ticket_tenant_external"),
    )

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, ForeignKey("companies.id"), nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    # The ITSM/SDK-side ticket identifier (e.g. "IT-101"). Distinct from `id`
    # (our internal PK) so a re-delivered webhook can be recognized and
    # skipped instead of reprocessing the same ticket twice.
    external_id = Column(String, nullable=True, index=True)
    
    title = Column(String, nullable=False)
    description = Column(String, nullable=False)
    
    # Classification
    urgency = Column(String, default="medium") # low, medium, high, critical
    category = Column(String, default="general") # software, hardware, access, network, general
    
    # Tracking
    status = Column(String, default="open") # open, resolved, escalated, escalated_github, pending_human
    resolution_path = Column(String, nullable=True) # autonomous, human, github
    
    # Deep Metrics & ROI
    estimated_time_saved_minutes = Column(Integer, default=0)
    cost_saved_usd = Column(Float, default=0.0)
    ai_confidence_score = Column(Float, nullable=True)
    
    # External Links
    github_issue_url = Column(String, nullable=True)
    # Risk-3 plan awaiting approval, incl. the exact action (Fase 11.2).
    proposed_plan = Column(String, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    company = relationship("Company")
    user = relationship("User", back_populates="tickets")


class LogAccessAudit(Base):
    """
    One row per platform-log read the agent performs (Fase 10.9). Records
    WHO triggered it and WHAT was read — never the log contents themselves,
    so the audit trail can't become a second copy of sensitive log data.
    """
    __tablename__ = "log_access_audit"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, ForeignKey("companies.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    service_name = Column(String, nullable=False)
    provider = Column(String, nullable=False)
    service_id = Column(String, nullable=False)
    window_start = Column(DateTime(timezone=True), nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)
    lines_returned = Column(Integer, default=0)
    verdict = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class PlatformLog(Base):
    """
    Log lines PUSHED to us by a platform (Vercel Log Drain, Fase 10.11) —
    Vercel's pull API only keeps 1h of logs on Hobby and its runtime-logs
    endpoint is streaming-only, so we keep a short-retention copy instead.
    Always queried by tenant_id; purged after settings.platform_log_retention_hours.
    """
    __tablename__ = "platform_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, ForeignKey("companies.id"), nullable=False, index=True)
    provider = Column(String, nullable=False)
    service_id = Column(String, nullable=False, index=True)   # Vercel projectId
    level = Column(String, nullable=True)
    message = Column(String, nullable=False)
    source = Column(String, nullable=True)
    status_code = Column(Integer, nullable=True)
    request_path = Column(String, nullable=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)


class KnowledgeAudit(Base):
    """
    One row per change to a tenant's knowledge base (Fase 11.5): upload,
    delete, or admin feedback. Whatever lands in the RAG is later read by the
    agents as context, so "who put this text there, and when" must be
    answerable. Never stores the content itself — only its hash and the
    injection heuristics it tripped.
    """
    __tablename__ = "knowledge_audit"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, ForeignKey("companies.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    action = Column(String, nullable=False)          # upload | delete | feedback
    filename = Column(String, nullable=False)
    source_type = Column(String, nullable=True)
    sha256 = Column(String, nullable=True)
    size_bytes = Column(Integer, nullable=True)
    chunks = Column(Integer, nullable=True)
    injection_flags = Column(String, nullable=True)  # comma-separated heuristic names
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
