"""Roadmap 2.4: traces, tokens/cost, node latency, correlated logs."""
import asyncio
import json
import logging
import uuid

import pytest
from fakes import RecordingMCP, ScriptedLLM
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from src.agent.state import ClassificationResult, ExecutionPlanResult, PolicyCheckResult
from src.db import models
from src.db.database import SessionLocal, engine
from src.jobs.worker import WorkerDeps
from src.observability import tracing
from src.observability.logging import ContextFilter, JsonFormatter
from src.observability.usage import percentile, usage_summary
from src.security.hashing import get_password_hash
from src.tickets import jobs as ticket_jobs
from src.tickets import service


@pytest.fixture(autouse=True)
def _schema():
    models.Base.metadata.create_all(bind=engine)


@pytest.fixture
def admin():
    """A tenant with an admin (for the API) and an employee (the requester)."""
    from src.security.api_keys import generate_api_key, hash_api_key
    db = SessionLocal()
    try:
        raw_key = generate_api_key()
        company = models.Company(name=f"Obs {uuid.uuid4().hex[:6]}", api_key_hash=hash_api_key(raw_key))
        db.add(company)
        db.flush()
        suffix = uuid.uuid4().hex[:6]
        admin_email, employee_email = f"admin.{suffix}@acme.com", f"emp.{suffix}@acme.com"
        for email, role in ((admin_email, "admin"), (employee_email, "employee")):
            db.add(models.User(email=email, full_name=email, password_hash=get_password_hash("Irrelevant123!"),
                               role=role, company_id=company.id))
        db.commit()
        return company.id, raw_key, admin_email, employee_email
    finally:
        db.close()


def _run_ticket(monkeypatch, tenant_id, api_key, employee, external_id):
    service.accept_webhook_ticket(api_key, external_id, "VPN", "mi VPN no conecta", employee)
    llms = (
        ScriptedLLM(ClassificationResult(intent="vpn", risk_level=2), input_tokens=50, output_tokens=10),
        ScriptedLLM(PolicyCheckResult(is_compliant=True, reason="ok"),
                    ExecutionPlanResult(resolution_summary="reset", tool_name="reset_vpn_session"),
                    input_tokens=400, output_tokens=40),
    )
    monkeypatch.setattr("src.agent.nodes.get_llms", lambda: llms)
    monkeypatch.setattr("src.agent.nodes.get_monitored_services", lambda t: [])
    monkeypatch.setattr("src.agent.nodes.retrieve_context", lambda *a, **kw: "")
    db = SessionLocal()
    try:
        ticket = db.query(models.Ticket).filter(models.Ticket.tenant_id == tenant_id,
                                                models.Ticket.external_id == external_id).first()
        payload = {"ticket_id": ticket.id}
    finally:
        db.close()
    asyncio.run(ticket_jobs.run_ticket(payload, WorkerDeps(MemorySaver(), RecordingMCP())))


def test_a_ticket_run_is_traced_node_by_node_with_tokens(admin, monkeypatch):
    tenant_id, api_key, _, employee = admin
    _run_ticket(monkeypatch, tenant_id, api_key, employee, "OBS-1")
    db = SessionLocal()
    try:
        spans = db.query(models.AgentSpan).filter(models.AgentSpan.tenant_id == tenant_id).all()
    finally:
        db.close()
    assert [s.name for s in sorted(spans, key=lambda s: s.started_at) if s.kind == "node"] == \
        ["supervisor", "policy", "execution"]
    llm = [s for s in spans if s.kind == "llm"]
    assert {s.name for s in llm} == {"ClassificationResult", "PolicyCheckResult", "ExecutionPlanResult"}
    assert sum(s.input_tokens for s in llm) == 50 + 400 + 400
    assert all(s.trace_id == "ticket:OBS-1" for s in spans)
    assert all(s.model == "scripted-model" for s in llm)


def test_usage_summary_prices_tokens_and_reports_percentiles(admin, monkeypatch):
    tenant_id, api_key, _, employee = admin
    _run_ticket(monkeypatch, tenant_id, api_key, employee, "OBS-2")
    from src.config import get_settings
    monkeypatch.setattr(get_settings(), "llm_prices_json", json.dumps({"scripted-model": [1.0, 2.0]}))
    summary = usage_summary(tenant_id)
    totals = summary["totals"]
    assert totals["llm_calls"] == 3 and totals["input_tokens"] == 850 and totals["output_tokens"] == 90
    assert totals["cost_usd"] == pytest.approx((850 * 1.0 + 90 * 2.0) / 1_000_000)
    assert {n["node"] for n in summary["nodes"]} == {"supervisor", "policy", "execution"}
    assert summary["by_source"][0]["runs"] == 1


def test_percentile_is_nearest_rank():
    assert percentile(list(range(1, 101)), 95) == 95
    assert percentile([10], 95) == 10 and percentile([], 95) == 0


def test_trace_and_usage_api_are_admin_only(admin, monkeypatch):
    from src.main import app
    tenant_id, api_key, admin_email, employee = admin
    _run_ticket(monkeypatch, tenant_id, api_key, employee, "OBS-3")
    client = TestClient(app)
    assert client.post("/api/auth/login", json={"email": admin_email, "password": "Irrelevant123!"}).status_code == 200
    trace = client.get("/api/tenant/tickets/OBS-3/trace")
    assert trace.status_code == 200
    kinds = [(s["kind"], s["name"]) for s in trace.json()["spans"]]
    assert ("node", "supervisor") in kinds and ("llm", "ExecutionPlanResult") in kinds
    assert client.get("/api/tenant/observability/usage").json()["totals"]["llm_calls"] == 3

    employee_client = TestClient(app)
    employee_client.post("/api/auth/login", json={"email": employee, "password": "Irrelevant123!"})
    assert employee_client.get("/api/tenant/observability/usage").status_code == 403


def test_tracing_failures_never_break_a_run(admin, monkeypatch):
    def broken_persist(trace):
        raise RuntimeError("database down")
    monkeypatch.setattr(tracing, "_persist", broken_persist)
    tenant_id, api_key, _, employee = admin
    _run_ticket(monkeypatch, tenant_id, api_key, employee, "OBS-4")  # must not raise
    db = SessionLocal()
    try:
        ticket = db.query(models.Ticket).filter(models.Ticket.tenant_id == tenant_id,
                                                models.Ticket.external_id == "OBS-4").first()
    finally:
        db.close()
    assert ticket.status == "resolved"


def test_requests_get_a_correlation_id():
    from src.main import app
    client = TestClient(app)
    generated = client.get("/health")
    assert len(generated.headers["x-request-id"]) == 16
    assert client.get("/health", headers={"X-Request-ID": "abc-123"}).headers["x-request-id"] == "abc-123"
    # Anything that could forge log lines is replaced, not echoed.
    assert client.get("/health", headers={"X-Request-ID": "bad\nid"}).headers["x-request-id"] != "bad\nid"


def test_json_logs_carry_trace_and_request_ids():
    record = logging.LogRecord("aether", logging.INFO, __file__, 1, "hello %s", ("world",), None)

    async def inside_trace():
        async with tracing.trace_scope("ticket:X-1", "ticket", None, persist=False):
            ContextFilter().filter(record)
    asyncio.run(inside_trace())
    entry = json.loads(JsonFormatter().format(record))
    assert entry["message"] == "hello world" and entry["trace_id"] == "ticket:X-1" and entry["request_id"] == "-"
