"""
Ticket lifecycle — the synchronous, database-only half (roadmap 2.1/2.2).

Every function here is plain blocking SQLAlchemy work with its own short
session. Async callers (route handlers, queue jobs) run them through
asyncio.to_thread / run_in_threadpool, so a slow database round-trip (the
Supabase pooler is ~50-150 ms away) never freezes the event loop that every
other request shares. Before this, the async routes queried the DB inline.

Domain errors are exceptions the HTTP layer maps to status codes; nothing in
here knows about HTTP.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from src.db.database import SessionLocal
from src.db.models import Company, Ticket, User
from src.integrations.issue_format import build_escalation_issue
from src.jobs.queue import JobKind, enqueue
from src.security.api_keys import hash_api_key
from src.security.encryption import decrypt_token, encrypt_token

logger = logging.getLogger(__name__)

# Placeholder ROI heuristic applied to every autonomously-resolved ticket.
# Real per-category handle-time/labor-rate figures belong in SubscriptionPlan
# or a tenant setting once we have data to back them — these keep the
# dashboard pipeline honest end-to-end without pretending to be precise.
AUTONOMOUS_RESOLUTION_MINUTES_SAVED = 15
AUTONOMOUS_RESOLUTION_COST_SAVED_USD = 12.50

RUN_TICKET_MAX_ATTEMPTS = 3
GITHUB_ISSUE_MAX_ATTEMPTS = 8


class InvalidApiKey(Exception):
    pass


class UnknownEmployee(Exception):
    def __init__(self, email: str):
        super().__init__(email)
        self.email = email


class TicketLimitReached(Exception):
    def __init__(self, limit: int):
        super().__init__(limit)
        self.limit = limit


@dataclass(frozen=True)
class AcceptedTicket:
    external_id: str
    duplicate: bool = False           # already received: not reprocessed
    routed_to_humans: bool = False    # plan out of AI resolutions


@dataclass(frozen=True)
class TicketRun:
    """What a queue job needs to run the agent on a ticket (no live ORM objects)."""
    ticket_id: str
    tenant_id: str
    external_id: str
    title: str
    description: str
    requester_email: str
    status: str


def month_start() -> datetime:
    return datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def is_escalated(values: dict) -> bool:
    """True for every state shape that routes to escalate_node (see graph.py)."""
    return (
        bool(values.get("technical_error"))
        or bool(values.get("action_refused"))
        or values.get("compliance_passed") is False
        or values.get("human_approved") is False
        or values.get("assessed_risk") == 4
    )


def _company_for_api_key(db, api_key: str) -> Company | None:
    company = db.query(Company).filter(Company.api_key_hash == hash_api_key(api_key)).first()
    if company:
        return company
    # Legacy rows created before API keys were hashed still hold the raw key
    # in `api_key`. Fall back once, then migrate the row in place so this
    # branch is never needed again for that tenant.
    company = db.query(Company).filter(Company.api_key == api_key).first()
    if company:
        company.api_key_hash = hash_api_key(api_key)
        company.api_key = encrypt_token(api_key)
        db.commit()
    return company


def _monthly_ticket_limit_reached(db, company: Company) -> bool:
    plan = company.plan
    if not plan:
        return False
    count = db.query(Ticket).filter(Ticket.tenant_id == company.id, Ticket.created_at >= month_start()).count()
    return count >= plan.max_tickets_per_month


def _create_and_enqueue(db, company: Company, user: User, external_id: str, title: str, description: str,
                        image_base64: str | None = None) -> Ticket:
    """
    Persists the ticket AND its run_ticket job in one commit (transactional
    outbox) — shared by the webhook and the chat escalation path so both go
    through the same monthly AI-resolution limit and the same queue.
    """
    ticket = Ticket(tenant_id=company.id, user_id=user.id, external_id=external_id,
                    title=title, description=description, status="open")
    db.add(ticket)
    db.flush()

    plan = company.plan
    if plan:
        ai_resolutions = db.query(Ticket).filter(
            Ticket.tenant_id == company.id, Ticket.created_at >= month_start(), Ticket.resolution_path.isnot(None),
        ).count()
        if ai_resolutions >= plan.max_ai_resolutions_per_month:
            # Logged, but this plan is out of AI resolutions for the period:
            # straight to the human queue, the agent never runs.
            ticket.status = "pending_human"
            db.commit()
            return ticket

    payload = {"ticket_id": ticket.id}
    if image_base64:
        payload["image_base64"] = image_base64
    enqueue(db, JobKind.RUN_TICKET, payload, dedupe_key=f"run_ticket:{ticket.id}",
            max_attempts=RUN_TICKET_MAX_ATTEMPTS)
    db.commit()
    db.refresh(ticket)
    return ticket


def accept_webhook_ticket(api_key: str, external_id: str, title: str, description: str, user_email: str,
                          image_base64: str | None = None) -> AcceptedTicket:
    db = SessionLocal()
    try:
        company = _company_for_api_key(db, api_key)
        if not company:
            raise InvalidApiKey()

        # Idempotency: ITSM/webhook senders retry on timeouts. Re-delivering
        # the same ticket_id must not re-run (and potentially re-execute) the agent.
        if db.query(Ticket.id).filter(Ticket.tenant_id == company.id, Ticket.external_id == external_id).first():
            return AcceptedTicket(external_id, duplicate=True)

        # Every employee must have an Aether account — tickets are always
        # attributed to a real, provisioned User, never a bare email string.
        user = db.query(User).filter(User.email == user_email, User.company_id == company.id).first()
        if not user:
            raise UnknownEmployee(user_email)

        if _monthly_ticket_limit_reached(db, company):
            raise TicketLimitReached(company.plan.max_tickets_per_month)

        ticket = _create_and_enqueue(db, company, user, external_id, title, description, image_base64)
        return AcceptedTicket(external_id, routed_to_humans=ticket.status == "pending_human")
    finally:
        db.close()


def open_chat_ticket(user_id: str, external_id: str, title: str, description: str) -> str | None:
    """Ticket for a chat turn the Concierge couldn't resolve. None = monthly limit reached."""
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        company = db.get(Company, user.company_id) if user else None
        if not company or _monthly_ticket_limit_reached(db, company):
            return None
        return _create_and_enqueue(db, company, user, external_id, title, description).external_id
    finally:
        db.close()


def load_ticket_run(ticket_id: str) -> TicketRun | None:
    db = SessionLocal()
    try:
        ticket = db.get(Ticket, ticket_id)
        if not ticket:
            return None
        return TicketRun(ticket.id, ticket.tenant_id, ticket.external_id, ticket.title, ticket.description,
                         ticket.user.email, ticket.status)
    finally:
        db.close()


def _enqueue_issue(db, ticket: Ticket, reason: str | None, compliance_notes: str | None) -> None:
    enqueue(db, JobKind.CREATE_GITHUB_ISSUE,
            {"ticket_id": ticket.id, "reason": reason, "compliance_notes": compliance_notes},
            dedupe_key=f"github_issue:{ticket.id}", max_attempts=GITHUB_ISSUE_MAX_ATTEMPTS)


def apply_graph_outcome(tenant_id: str, external_id: str, values: dict, awaiting_approval: bool) -> None:
    """
    Reflects the graph's final (or paused) state onto the Ticket row. An
    escalation enqueues its GitHub issue in the SAME commit (outbox): the
    issue is created by a retried job, so a GitHub outage can't lose it and
    can't block the ticket's status.
    """
    db = SessionLocal()
    try:
        ticket = db.query(Ticket).filter(Ticket.tenant_id == tenant_id, Ticket.external_id == external_id).first()
        if not ticket:
            return
        if awaiting_approval:
            ticket.status = "pending_human"
            ticket.resolution_path = None
            # What the admin approves must be visible to them (Fase 11.2):
            # the plan text ends with the exact action that will run.
            ticket.proposed_plan = values.get("proposed_plan")
        elif is_escalated(values):
            ticket.status = "escalated"
            ticket.resolution_path = None
            _enqueue_issue(db, ticket, values.get("final_resolution"), values.get("compliance_notes"))
        else:
            ticket.status = "resolved"
            ticket.resolution_path = "human" if values.get("human_approved") is True else "autonomous"
            ticket.resolved_at = datetime.now(timezone.utc)
            ticket.estimated_time_saved_minutes = AUTONOMOUS_RESOLUTION_MINUTES_SAVED
            ticket.cost_saved_usd = AUTONOMOUS_RESOLUTION_COST_SAVED_USD
        db.commit()
    finally:
        db.close()


def escalate_after_failure(ticket_id: str, error: str) -> None:
    """Dead-letter path: the agent run failed every retry — a human takes it."""
    db = SessionLocal()
    try:
        ticket = db.get(Ticket, ticket_id)
        if not ticket or ticket.status in ("resolved", "escalated"):
            return
        ticket.status = "escalated"
        ticket.resolution_path = None
        _enqueue_issue(db, ticket, "Technical failure in Aether after retries. Manual intervention required.", None)
        db.commit()
    finally:
        db.close()


@dataclass(frozen=True)
class IssueTarget:
    repo: str
    token: str
    title: str
    body: str


def load_issue_target(ticket_id: str, reason: str | None, compliance_notes: str | None) -> IssueTarget | None:
    """
    None when there is nothing to do: GitHub not connected, token not
    decryptable, or the issue already exists (a retried job after a crash).
    """
    db = SessionLocal()
    try:
        ticket = db.get(Ticket, ticket_id)
        if not ticket or ticket.github_issue_url:
            return None
        company = db.get(Company, ticket.tenant_id)
        if not company or not company.github_token or not company.github_repo:
            return None
        token = decrypt_token(company.github_token)
        if not token:
            logger.warning("Could not decrypt github_token for company %s; skipping issue creation", company.id)
            return None
        # Untrusted user text + LLM output, going to a possibly public repo:
        # redacted and rendered inert (see issue_format.py).
        title, body = build_escalation_issue(ticket.external_id, ticket.title, ticket.description,
                                             reason, compliance_notes)
        return IssueTarget(company.github_repo, token, title, body)
    finally:
        db.close()


def save_issue_url(ticket_id: str, url: str) -> None:
    db = SessionLocal()
    try:
        ticket = db.get(Ticket, ticket_id)
        if ticket:
            ticket.github_issue_url = url
            db.commit()
    finally:
        db.close()
