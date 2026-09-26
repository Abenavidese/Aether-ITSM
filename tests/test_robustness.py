"""
Roadmap 2.1 (no blocking I/O on the event loop) and 2.2 (durable job queue,
transactional outbox, crash-resume) — exercised against the real graph,
queue and database, with scripted models.
"""
import asyncio
import json
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fakes import RecordingMCP, ScriptedLLM
from langgraph.checkpoint.memory import MemorySaver

from src.agent.state import ClassificationResult, ConciergeResult, ExecutionPlanResult, PolicyCheckResult
from src.db import models
from src.db.database import SessionLocal, engine
from src.jobs import queue
from src.jobs.queue import JobKind, JobStatus
from src.jobs.worker import JobWorker, PermanentJobError, WorkerDeps
from src.security.api_keys import generate_api_key, hash_api_key
from src.security.encryption import encrypt_token
from src.security.hashing import get_password_hash
from src.tickets import jobs as ticket_jobs
from src.tickets import service

EMPLOYEE = "ana.robust@acme.com"


def _delete_jobs():
    db = SessionLocal()
    try:
        db.query(models.Job).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _clean_tables():
    # The sqlite test DB is shared across modules: start and end with an empty queue.
    models.Base.metadata.create_all(bind=engine)
    _delete_jobs()
    yield
    _delete_jobs()


@pytest.fixture
def tenant():
    db = SessionLocal()
    try:
        raw_key = generate_api_key()
        company = models.Company(name=f"Robust {uuid.uuid4().hex[:6]}", api_key_hash=hash_api_key(raw_key),
                                 api_key=encrypt_token(raw_key))
        db.add(company)
        db.flush()
        email = f"{uuid.uuid4().hex[:6]}.{EMPLOYEE}"
        db.add(models.User(email=email, full_name="Ana", password_hash=get_password_hash("Irrelevant123!"),
                           role="employee", company_id=company.id))
        db.commit()
        return company.id, raw_key, email
    finally:
        db.close()


def _jobs(kind: JobKind | None = None) -> list[models.Job]:
    db = SessionLocal()
    try:
        query = db.query(models.Job)
        if kind:
            query = query.filter(models.Job.kind == kind.value)
        return query.all()
    finally:
        db.close()


def _make_all_due():
    db = SessionLocal()
    try:
        db.query(models.Job).update({models.Job.run_after: datetime.now(timezone.utc) - timedelta(seconds=1)})
        db.commit()
    finally:
        db.close()


def _in_session(fn, *args, **kwargs):
    db = SessionLocal()
    try:
        return fn(db, *args, **kwargs)
    finally:
        db.close()


# ── 2.2 queue protocol ────────────────────────────────────────────────────────

def test_enqueue_is_idempotent_by_dedupe_key():
    def add(db):
        first = queue.enqueue(db, JobKind.RUN_TICKET, {"ticket_id": "t"}, dedupe_key="run_ticket:t")
        db.commit()
        second = queue.enqueue(db, JobKind.RUN_TICKET, {"ticket_id": "t"}, dedupe_key="run_ticket:t")
        db.commit()
        return first, second
    first, second = _in_session(add)
    assert first is not None and second is None and len(_jobs()) == 1


def test_a_job_is_claimed_once_and_only_when_due():
    def add(db):
        queue.enqueue(db, JobKind.RUN_TICKET, {"n": 1})
        queue.enqueue(db, JobKind.RUN_TICKET, {"n": 2}, delay_seconds=3600)
        db.commit()
    _in_session(add)
    claimed = _in_session(queue.claim_next, "w1")
    assert claimed.payload == {"n": 1} and claimed.attempts == 1
    assert _in_session(queue.claim_next, "w2") is None  # the other isn't due; the first is taken


def test_failures_back_off_then_go_dead():
    _in_session(lambda db: (queue.enqueue(db, JobKind.RUN_TICKET, {}, max_attempts=2), db.commit()))
    job = _in_session(queue.claim_next, "w")
    assert _in_session(queue.fail, job.id, "boom") == JobStatus.QUEUED
    retry_at = _jobs()[0].run_after
    assert retry_at.replace(tzinfo=retry_at.tzinfo or timezone.utc) > datetime.now(timezone.utc)
    _make_all_due()
    job = _in_session(queue.claim_next, "w")
    assert job.attempts == 2
    assert _in_session(queue.fail, job.id, "boom again") == JobStatus.DEAD
    assert queue.backoff_seconds(1) == 5 and queue.backoff_seconds(20) == queue.BACKOFF_CAP_SECONDS


def test_jobs_of_a_dead_worker_are_requeued():
    _in_session(lambda db: (queue.enqueue(db, JobKind.RUN_TICKET, {}), db.commit()))
    job = _in_session(queue.claim_next, "crashed-worker")
    later = datetime.now(timezone.utc) + timedelta(seconds=700)
    assert _in_session(queue.requeue_stale, 600, now=later) == 1
    assert _in_session(queue.claim_next, "new-worker", now=later).id == job.id


def test_worker_retries_then_runs_the_dead_letter_handler():
    calls, dead = [], []

    async def flaky(payload, deps):
        calls.append(payload)
        raise RuntimeError("model server down")

    async def on_dead(payload, deps, error):
        dead.append(error)

    _in_session(lambda db: (queue.enqueue(db, JobKind.RUN_TICKET, {"x": 1}, max_attempts=2), db.commit()))
    worker = JobWorker(WorkerDeps(None, None), {JobKind.RUN_TICKET.value: flaky},
                       dead_handlers={JobKind.RUN_TICKET.value: on_dead})
    asyncio.run(worker.run_once())
    assert _jobs()[0].status == JobStatus.QUEUED.value and dead == []
    _make_all_due()
    asyncio.run(worker.run_once())
    assert _jobs()[0].status == JobStatus.DEAD.value
    assert len(calls) == 2 and "model server down" in dead[0]


def test_permanent_errors_skip_retries():
    async def broken(payload, deps):
        raise PermanentJobError("bad payload")
    _in_session(lambda db: (queue.enqueue(db, JobKind.RUN_TICKET, {}, max_attempts=5), db.commit()))
    asyncio.run(JobWorker(WorkerDeps(None, None), {JobKind.RUN_TICKET.value: broken}).run_once())
    assert _jobs()[0].status == JobStatus.DEAD.value


# ── 2.2 outbox: ticket and job commit together ───────────────────────────────

def test_webhook_ticket_and_its_job_are_one_unit(tenant):
    _, api_key, email = tenant
    accepted = service.accept_webhook_ticket(api_key, "RB-1", "VPN", "no conecta", email)
    assert not accepted.duplicate
    again = service.accept_webhook_ticket(api_key, "RB-1", "VPN", "no conecta", email)
    assert again.duplicate
    run_jobs = _jobs(JobKind.RUN_TICKET)
    assert len(run_jobs) == 1 and json.loads(run_jobs[0].payload)["ticket_id"]


# ── 2.2 crash-resume on the real graph ────────────────────────────────────────

def test_interrupted_agent_run_resumes_from_its_checkpoint(tenant, monkeypatch):
    tenant_id, api_key, email = tenant
    service.accept_webhook_ticket(api_key, "RB-2", "VPN", "mi VPN no conecta", email)

    nano = ScriptedLLM(ClassificationResult(intent="vpn", risk_level=2))
    super_llm = ScriptedLLM(PolicyCheckResult(is_compliant=True, reason="ok"),
                            ExecutionPlanResult(resolution_summary="VPN reset", tool_name="reset_vpn_session"))
    monkeypatch.setattr("src.agent.nodes.get_llms", lambda: (nano, super_llm))
    monkeypatch.setattr("src.agent.nodes.get_monitored_services", lambda t: [])
    rag_calls = {"n": 0}

    def flaky_rag(*a, **kw):
        rag_calls["n"] += 1
        if rag_calls["n"] == 1:  # the policy node's first look-up dies mid-run
            raise ConnectionError("pgvector unreachable")
        return ""
    monkeypatch.setattr("src.agent.nodes.retrieve_context", flaky_rag)

    mcp = RecordingMCP()
    worker = ticket_jobs.build_worker(WorkerDeps(MemorySaver(), mcp), _settings())
    asyncio.run(worker.run_once())
    assert _jobs(JobKind.RUN_TICKET)[0].status == JobStatus.QUEUED.value  # will retry

    _make_all_due()
    asyncio.run(worker.run_once())
    assert _jobs(JobKind.RUN_TICKET)[0].status == JobStatus.DONE.value
    assert len(nano.prompts) == 1  # supervisor was NOT re-run: resumed from its checkpoint
    assert mcp.calls == [("reset_vpn_session", {"user_id": email})]
    ticket = _ticket(tenant_id, "RB-2")
    assert ticket.status == "resolved" and ticket.resolution_path == "autonomous"


def _settings():
    from src.config import get_settings
    return get_settings()


def _ticket(tenant_id, external_id) -> models.Ticket:
    db = SessionLocal()
    try:
        return db.query(models.Ticket).filter(models.Ticket.tenant_id == tenant_id,
                                              models.Ticket.external_id == external_id).first()
    finally:
        db.close()


def test_run_ticket_job_is_idempotent_once_finished(tenant, monkeypatch):
    tenant_id, api_key, email = tenant
    service.accept_webhook_ticket(api_key, "RB-3", "Docs", "¿dónde está la guía?", email)
    nano = ScriptedLLM(ClassificationResult(intent="faq", risk_level=0))
    super_llm = ScriptedLLM(ExecutionPlanResult(resolution_summary="Está en la wiki"))
    monkeypatch.setattr("src.agent.nodes.get_llms", lambda: (nano, super_llm))
    monkeypatch.setattr("src.agent.nodes.get_monitored_services", lambda t: [])
    monkeypatch.setattr("src.agent.nodes.retrieve_context", lambda *a, **kw: "")
    deps = WorkerDeps(MemorySaver(), RecordingMCP())
    payload = json.loads(_jobs(JobKind.RUN_TICKET)[0].payload)
    asyncio.run(ticket_jobs.run_ticket(payload, deps))
    asyncio.run(ticket_jobs.run_ticket(payload, deps))  # redelivered: must not run the graph again
    assert len(nano.prompts) == 1 and _ticket(tenant_id, "RB-3").status == "resolved"


# ── 2.2 GitHub issue through the outbox, with retries ────────────────────────

def test_escalation_issue_survives_a_github_outage(tenant, monkeypatch):
    tenant_id, api_key, email = tenant
    db = SessionLocal()
    try:
        company = db.get(models.Company, tenant_id)
        company.github_repo, company.github_token = "acme/repo", encrypt_token("ghp_x")
        db.commit()
    finally:
        db.close()
    service.accept_webhook_ticket(api_key, "RB-4", "DB caída", "la base de datos de producción no responde", email)
    service.apply_graph_outcome(tenant_id, "RB-4", {"assessed_risk": 4, "final_resolution": "escalated"}, False)
    service.apply_graph_outcome(tenant_id, "RB-4", {"assessed_risk": 4, "final_resolution": "escalated"}, False)
    assert len(_jobs(JobKind.CREATE_GITHUB_ISSUE)) == 1  # deduplicated

    attempts = {"n": 0}

    async def flaky_create_issue(repo, token, title, body):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("GitHub 502")
        return "https://github.com/acme/repo/issues/7"
    monkeypatch.setattr(ticket_jobs, "create_issue", flaky_create_issue)

    worker = ticket_jobs.build_worker(WorkerDeps(None, None), _settings())
    db = SessionLocal()
    try:  # the run_ticket job isn't under test here
        db.query(models.Job).filter(models.Job.kind == JobKind.RUN_TICKET.value).delete()
        db.commit()
    finally:
        db.close()
    asyncio.run(worker.run_once())
    assert _ticket(tenant_id, "RB-4").github_issue_url is None
    _make_all_due()
    asyncio.run(worker.run_once())
    assert _ticket(tenant_id, "RB-4").github_issue_url == "https://github.com/acme/repo/issues/7"
    assert _ticket(tenant_id, "RB-4").status == "escalated"


# ── 2.1 a slow chat turn doesn't freeze the server ────────────────────────────

def test_health_stays_fast_while_a_chat_waits_on_blocking_io(tenant, monkeypatch):
    from src.main import app
    _, _, email = tenant
    monkeypatch.setattr("src.agent.concierge.node.get_llms",
                        lambda: (None, ScriptedLLM(ConciergeResult(response_text="ok", resolved=True))))
    monkeypatch.setattr("src.agent.concierge.node.get_monitored_services", lambda t: [])

    def slow_rag(*a, **kw):
        time.sleep(1.5)  # blocking, like an embedding call + pgvector round-trip
        return ""
    monkeypatch.setattr("src.agent.concierge.node.retrieve_context", slow_rag)
    app.state.checkpointer = MemorySaver()
    app.state.mcp_client = RecordingMCP()

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            login = await client.post("/api/auth/login", json={"email": email, "password": "Irrelevant123!"})
            assert login.status_code == 200
            # Measured from when /health was SCHEDULED to go out (0.3 s in):
            # if the chat blocks the loop, the request can't even start until
            # the block ends — timing only the request itself would miss that.
            due = time.perf_counter() + 0.3
            chat = asyncio.create_task(client.post("/api/chat", json={"message": "hola"}))
            await asyncio.sleep(0.3)
            health = await client.get("/health")
            health_seconds = time.perf_counter() - due
            reply = await chat
            return health.status_code, health_seconds, reply.status_code
    status, seconds, chat_status = asyncio.run(scenario())
    assert status == 200 and chat_status == 200
    assert seconds < 0.5, f"/health took {seconds:.2f}s while a chat turn was blocked on I/O"
