import uuid

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base
from .types import Embedding


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
    github_token = Column(String, nullable=True)
    github_repo = Column(String, nullable=True)
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


class Job(Base):
    """
    Durable work queue (roadmap 2.2) — replaces in-process BackgroundTasks,
    which lost every in-flight ticket on a restart/redeploy and had no
    retries or concurrency limit. Lives in the same database, so a ticket
    and its job are written in ONE transaction (transactional outbox): there
    is never a ticket nobody will process, nor a job for a ticket that
    doesn't exist. See src/jobs/queue.py for the claim/retry protocol.
    """
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    kind = Column(String, nullable=False, index=True)
    payload = Column(String, nullable=False)                   # JSON
    status = Column(String, nullable=False, default="queued", index=True)  # queued|running|done|dead
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    run_after = Column(DateTime(timezone=True), nullable=False, index=True)
    locked_by = Column(String, nullable=True)
    locked_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(String, nullable=True)
    # Same logical work enqueued twice (webhook retry, double escalation) is one job.
    dedupe_key = Column(String, nullable=True, unique=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True), nullable=True)


class AgentSpan(Base):
    """
    One timed step of an agent run (roadmap 2.4): a graph node, or a single
    LLM call with its token usage. trace_id groups a whole run ("ticket:<id>"
    or "chat:<turn id>"), so a ticket's full path — supervisor -> policy ->
    ... with each model call inside — can be replayed, and tokens/cost and
    per-node latency (p95) can be aggregated per tenant. Never stores prompt
    or completion text.
    """
    __tablename__ = "agent_spans"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, ForeignKey("companies.id"), nullable=True, index=True)
    trace_id = Column(String, nullable=False, index=True)
    source = Column(String, nullable=False)                  # ticket | chat | eval
    kind = Column(String, nullable=False)                    # node | llm
    name = Column(String, nullable=False)                    # node name, or output schema for llm
    model = Column(String, nullable=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    duration_ms = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="ok")    # ok | error
    started_at = Column(DateTime(timezone=True), nullable=False, index=True)
    # Small JSON of step details (e.g. a retrieval's stage timings and chunk
    # ids/scores, Fase 14.7). Same rule as the rest: never prompt text.
    attributes = Column(Text, nullable=True)


class KnowledgeDocument(Base):
    """
    One document of a tenant's knowledge base (Fase 14.1) — the registry the
    old store never had (the file list used to be a DISTINCT over chunks).

    Versioning: every upload with new content bumps latest_version and is
    indexed by a queue job; chunks of the version being built are inactive
    until the job flips them, so the previous version keeps answering until
    the new one is ready. `content` is the extracted text of latest_version,
    kept so a document can be re-indexed (new embedding model, new chunker)
    without the original file.
    """
    __tablename__ = "knowledge_documents"
    __table_args__ = (UniqueConstraint("tenant_id", "filename", name="uq_knowledge_document_tenant_filename"),)

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, ForeignKey("companies.id"), nullable=False, index=True)
    filename = Column(String, nullable=False)
    source_type = Column(String, nullable=False)       # company_policy | technical_repo | ai_feedback
    # queued | indexing | ready | failed | pending_review | rejected
    status = Column(String, nullable=False, default="queued")
    latest_version = Column(Integer, nullable=False, default=1)
    active_version = Column(Integer, nullable=True)    # the version search serves; None until first ready
    sha256 = Column(String, nullable=True)             # of latest_version's extracted text
    content = Column(Text, nullable=True)
    page_map = Column(Text, nullable=True)             # JSON [[char_offset, page], ...] of `content` (PDFs)
    size_bytes = Column(Integer, nullable=True)
    pages = Column(Integer, nullable=True)
    chunk_count = Column(Integer, nullable=False, default=0)
    embedding_model = Column(String, nullable=True)    # of the active version
    embedding_dim = Column(Integer, nullable=True)
    chunker_version = Column(String, nullable=True)
    warnings = Column(Text, nullable=True)             # JSON list: scanned pages, injection flags...
    error = Column(Text, nullable=True)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    reviewed_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    indexed_at = Column(DateTime(timezone=True), nullable=True)


class KnowledgeChunk(Base):
    """
    A searchable passage (Fase 14.1). tenant_id is a real column (the old
    store kept it inside JSON), so RLS can enforce it and every index can
    lead with it. filename/source_type are copied from the document so a
    search is one table scan with no join.

    The embedding column has no fixed dimension: vectors of different models
    coexist (never compared — every search filters by embedding_model), and
    each model gets its own partial HNSW index over a cast to its dimension
    (src/rag/store.py:ensure_vector_index).
    """
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        Index("ix_knowledge_chunks_search", "tenant_id", "is_active", "source_type"),
        Index("ix_knowledge_chunks_document", "document_id", "version"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, ForeignKey("companies.id"), nullable=False)
    document_id = Column(String, ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    is_active = Column(Boolean, nullable=False, default=False)
    source_type = Column(String, nullable=False)
    filename = Column(String, nullable=False)
    section = Column(String, nullable=True)
    page = Column(Integer, nullable=True)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)             # header + body, what the model reads
    search_text = Column(Text, nullable=False)         # normalized for full-text search (src/rag/text.py)
    embedding = Column(Embedding, nullable=True)
    embedding_model = Column(String, nullable=True)
    chunk_metadata = Column(Text, nullable=True)       # JSON: injection flags, feedback author/date
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class RagQueryLog(Base):
    """
    One row per knowledge-base search (Fase 14.7): what was asked (redacted,
    truncated), whether anything relevant came back, and which documents
    answered. Admin-only, tenant-scoped (RLS). Feeds "documents never used"
    and "questions with no answer" — i.e. what the company should document
    next. Purged after rag_query_log_retention_days.
    """
    __tablename__ = "rag_queries"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, ForeignKey("companies.id"), nullable=False, index=True)
    trace_id = Column(String, nullable=True)
    origin = Column(String, nullable=False)            # chat | ticket
    query = Column(String, nullable=False)
    rewritten = Column(Boolean, nullable=False, default=False)
    passages = Column(Integer, nullable=False, default=0)
    top_score = Column(Float, nullable=True)
    document_ids = Column(Text, nullable=True)         # JSON list of documents cited in the context
    duration_ms = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
