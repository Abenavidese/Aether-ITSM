import pytest
from fastapi.testclient import TestClient
import json
import os
import sqlite3

# Test environment variables are set in tests/conftest.py (before any import).
from src.main import app
from src.db import models
from src.db.database import engine, SessionLocal
from src.security.api_keys import generate_api_key, hash_api_key
from src.security.encryption import encrypt_token
from src.security.hashing import get_password_hash

client = TestClient(app)


def _remove_checkpoints_db():
    if os.path.exists("test_checkpoints.db"):
        os.remove("test_checkpoints.db")


@pytest.fixture(scope="session", autouse=True)
def _run_lifespan():
    # FastAPI's lifespan (src/main.py) is what sets app.state.checkpointer
    # and app.state.mcp_client (spawns the MCP subprocess) — without entering
    # it, any endpoint that reaches into them (webhook, approve) raises
    # AttributeError instead of running. The AsyncSqliteSaver connection it
    # opens stays alive for the whole test session, so test_checkpoints.db
    # can only be reset once here, never per-test (see setup_teardown below).
    _remove_checkpoints_db()
    with client:
        yield
    _remove_checkpoints_db()

def load_test_tickets():
    """Loads the synthetic tickets from our JSON file."""
    with open("tests/data/tickets.json", "r") as f:
        return json.load(f)

def _remove_app_db():
    # engine.dispose() closes every pooled sqlite connection first — on
    # Windows the file stays locked by this same process (via the engine
    # created at `from src.main import app` above) until the pool is
    # released, so a bare os.remove() here always raised WinError 32.
    # A short retry absorbs the remaining race: webhook tests trigger a real
    # BackgroundTasks-run agent turn (Starlette runs it synchronously inside
    # the request), whose own short-lived SessionLocal() can still be a few
    # milliseconds from closing when this teardown fires.
    import time
    engine.dispose()
    for attempt in range(5):
        if not os.path.exists("test_app.db"):
            return
        try:
            os.remove("test_app.db")
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.2)

@pytest.fixture(autouse=True)
def setup_teardown():
    _remove_app_db()
    # create_all() already ran once at import time against the file we just
    # deleted; recreate the schema so this test starts from clean, existing
    # tables instead of a missing/empty database.
    models.Base.metadata.create_all(bind=engine)

    yield

    _remove_app_db()


@pytest.fixture
def seeded_company():
    """A company + plan + one User per tickets.json email, for webhook tests."""
    db = SessionLocal()
    try:
        plan = models.SubscriptionPlan(id="plan_free", name="Free", max_tickets_per_month=100, max_ai_resolutions_per_month=50)
        db.add(plan)
        raw_key = generate_api_key()
        company = models.Company(
            name="Test Co", api_key=encrypt_token(raw_key), api_key_hash=hash_api_key(raw_key), plan_id=plan.id
        )
        db.add(company)
        db.flush()
        for t in load_test_tickets():
            db.add(models.User(
                email=t["user_email"], full_name=t["user_email"],
                password_hash=get_password_hash("irrelevant"), role="employee", company_id=company.id,
            ))
        db.commit()
        yield company.id, raw_key
    finally:
        db.close()

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_webhook_receives_tickets(seeded_company, monkeypatch):
    # Starlette runs BackgroundTasks synchronously inside the request/response
    # cycle, so without this the webhook test would need a live Ollama server
    # to actually classify/execute each ticket — that live-model path is
    # scripts/e2e_ollama.py's job (Fase 1.3), not this fast pytest suite's.
    async def _noop_agent(*args, **kwargs):
        pass
    monkeypatch.setattr("src.api.routes.run_agent_background", _noop_agent)

    _, api_key = seeded_company
    tickets = load_test_tickets()

    for ticket in tickets:
        response = client.post("/api/webhook/ticket", json=ticket, headers={"x-api-key": api_key})
        assert response.status_code == 202
        assert response.json()["ticket_id"] == ticket["ticket_id"]
        assert response.json()["status"] == "Accepted"


def test_webhook_rejects_missing_api_key():
    response = client.post("/api/webhook/ticket", json=load_test_tickets()[0])
    assert response.status_code == 422


def test_webhook_rejects_unknown_user(seeded_company):
    _, api_key = seeded_company
    ticket = {**load_test_tickets()[0], "user_email": "not-provisioned@company.com"}
    response = client.post("/api/webhook/ticket", json=ticket, headers={"x-api-key": api_key})
    assert response.status_code == 404

class _FakeStructuredLLM:
    """Stands in for llm.with_structured_output(...).ainvoke(...) so chat
    tests exercise the real HTTP/graph/DB path without a live Ollama."""
    def __init__(self, result):
        self._result = result

    def with_structured_output(self, schema, include_raw=True):
        return self

    async def ainvoke(self, messages):
        return {"parsed": self._result, "parsing_error": None}


def _login_as(email: str, password: str = "irrelevant"):
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text


def test_chat_resolved_in_one_turn(seeded_company, monkeypatch):
    from src.agent.state import ConciergeResult

    _login_as(load_test_tickets()[0]["user_email"])
    fake_result = ConciergeResult(response_text="Cleared your VPN session.", resolved=True)
    monkeypatch.setattr(
        "src.agent.concierge.get_llms", lambda: (None, _FakeStructuredLLM(fake_result))
    )
    # RAG needs a real Postgres+pgvector store (see docs/architecture.md) —
    # out of scope for this sqlite-backed suite; retrieve_context is
    # exercised for real by scripts/e2e_ollama.py against Supabase.
    monkeypatch.setattr("src.agent.concierge.retrieve_context", lambda *a, **kw: "")

    response = client.post("/api/chat", json={"message": "my vpn is down"})
    assert response.status_code == 200
    assert response.json() == {"reply": "Cleared your VPN session.", "status": "resolved"}


def test_chat_escalates_to_ticket(seeded_company, monkeypatch):
    from src.agent.state import ConciergeResult

    _login_as(load_test_tickets()[1]["user_email"])
    fake_result = ConciergeResult(response_text="Opening a ticket for you.", resolved=False)
    monkeypatch.setattr(
        "src.agent.concierge.get_llms", lambda: (None, _FakeStructuredLLM(fake_result))
    )
    monkeypatch.setattr("src.agent.concierge.retrieve_context", lambda *a, **kw: "")
    monkeypatch.setattr("src.api.routes.run_agent_background", lambda *a, **kw: None)

    response = client.post("/api/chat", json={"message": "I need admin access to prod DB"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "investigating"
    assert body["ticket_external_id"].startswith("chat-")

    db = SessionLocal()
    try:
        ticket = db.query(models.Ticket).filter(models.Ticket.external_id == body["ticket_external_id"]).first()
        assert ticket is not None
        assert ticket.description == "I need admin access to prod DB"
    finally:
        db.close()


def test_approve_ticket_not_found():
    # approve_ticket requires an authenticated admin (Fase 0 IDOR fix), so
    # register+login for a real cookie first — an unauthenticated call would
    # 401 before ever reaching the "thread not found" check this asserts.
    register_payload = {
        "email": "approver@company.com", "password": "Irrelevant123!",
        "full_name": "Approver", "company_name": "Approve Co",
    }
    client.post("/api/auth/register", json=register_payload)
    client.post("/api/auth/login", json={"email": register_payload["email"], "password": register_payload["password"]})

    # No ticket/thread was ever created for "IT-103" under this fresh tenant,
    # and the graph never ran to reach the paused state — so the thread
    # simply doesn't exist yet.
    response = client.post("/api/approve/IT-103", json={"approved": True, "approver_id": "admin.smith"})
    assert response.status_code == 404
