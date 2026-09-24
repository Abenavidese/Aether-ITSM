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


# ── Fase 10.1: platform-log settings ─────────────────────────────────────────

def _add_user(company_id: str, email: str, role: str) -> None:
    db = SessionLocal()
    try:
        db.add(models.User(email=email, full_name=email, password_hash=get_password_hash("irrelevant"),
                           role=role, company_id=company_id))
        db.commit()
    finally:
        db.close()


_RENDER_SERVICE = {
    "name": "Backend", "url": "https://backend.example.com/health",
    "provider": "render", "service_id": "srv-abc123def456", "owner_id": "tea-xyz789uvw012",
}


def test_render_key_is_write_only_and_encrypted(seeded_company):
    company_id, _ = seeded_company
    _add_user(company_id, "admin@test.co", "admin")
    _login_as("admin@test.co")

    resp = client.put("/api/tenant/settings", json={
        "render_api_key": "rnd_supersecret", "monitored_services": [_RENDER_SERVICE],
    })
    assert resp.status_code == 200, resp.text

    settings = client.get("/api/tenant/settings").json()
    assert settings["render_api_key"] == "MASKED"
    assert settings["monitored_services"] == [_RENDER_SERVICE]

    db = SessionLocal()
    try:
        stored = db.query(models.Company).filter(models.Company.id == company_id).first().render_api_key
        assert stored and stored != "rnd_supersecret"  # encrypted at rest
    finally:
        db.close()

    # Sending the masked placeholder back keeps the key; "" clears it.
    client.put("/api/tenant/settings", json={"render_api_key": "MASKED"})
    assert client.get("/api/tenant/settings").json()["render_api_key"] == "MASKED"
    client.put("/api/tenant/settings", json={"render_api_key": ""})
    assert client.get("/api/tenant/settings").json()["render_api_key"] == ""


@pytest.mark.parametrize("bad_service", [
    {**_RENDER_SERVICE, "service_id": "srv-abc/../restart"},
    {**_RENDER_SERVICE, "service_id": "srv-abc123def456?x=1"},
    {**_RENDER_SERVICE, "owner_id": None},
    {**_RENDER_SERVICE, "provider": "heroku"},
    {"name": "X", "url": "https://x", "service_id": "srv-abc123def456"},
])
def test_log_source_ids_are_strictly_validated(seeded_company, bad_service):
    company_id, _ = seeded_company
    _add_user(company_id, "admin@test.co", "admin")
    _login_as("admin@test.co")
    resp = client.put("/api/tenant/settings", json={"monitored_services": [bad_service]})
    assert resp.status_code == 422, resp.text


def test_employee_cannot_configure_log_access(seeded_company):
    _login_as(load_test_tickets()[0]["user_email"])
    resp = client.put("/api/tenant/settings", json={"render_api_key": "rnd_x"})
    assert resp.status_code == 403


# ── Fase 10.6/10.7/10.9: platform logs in the chat ───────────────────────────

import httpx  # noqa: E402

_STACK_ERROR = ("TypeError: Cannot read properties of undefined (reading 'id') "
                "at getCart (/opt/render/project/src/backend/src/controllers/cartController.js:11:25) "
                "user=maria.lopez@acme.com")


class _RecordingLLM(_FakeStructuredLLM):
    def __init__(self, result):
        super().__init__(result)
        self.prompts: list[str] = []

    async def ainvoke(self, messages):
        self.prompts.append("\n".join(str(m.content) for m in messages))
        return await super().ainvoke(messages)


def _render_transport(requests: list, suspended: bool = False):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path == "/v1/logs":
            return httpx.Response(200, json={"hasMore": False, "logs": [{
                "message": _STACK_ERROR, "timestamp": "2026-09-23T11:55:00Z",
                "labels": [{"name": "level", "value": "error"}, {"name": "type", "value": "app"}],
            }]})
        if path.endswith("/deploys"):
            return httpx.Response(200, json=[{"deploy": {"status": "live"}}])
        return httpx.Response(200, json={"name": "backend", "suspended": "suspended" if suspended else "not_suspended"})
    return httpx.MockTransport(handler)


def _setup_platform_logs(monkeypatch, company_id, result, suspended=False, http_status=500):
    from src.integrations.logs import service as log_service
    from src.integrations.logs.render import RenderLogProvider, _cache

    _cache.clear()
    db = SessionLocal()
    try:
        company = db.query(models.Company).filter(models.Company.id == company_id).first()
        company.monitored_services = json.dumps([_RENDER_SERVICE])
        company.render_api_key = encrypt_token("rnd_testkey")
        db.commit()
    finally:
        db.close()

    requests: list[httpx.Request] = []
    monkeypatch.setattr(log_service, "build_provider",
                        lambda tenant_id, ref: RenderLogProvider("rnd_testkey", transport=_render_transport(requests, suspended)))

    async def fake_health(url):
        return {"status": "success", "available": http_status < 500, "http_status": http_status}
    monkeypatch.setattr("src.agent.concierge._health_checker", lambda mcp: fake_health)

    tree = [{"path": "backend/src/controllers/cartController.js", "type": "file"}]

    async def fake_tree(tenant_id):
        return tree
    read_files: list[str] = []

    async def fake_files(tenant_id, files):
        read_files.extend(files)
        return "\n".join(f"=== {f} (COMPLETE FILE, 1 lines) ===\n  11 | const id = req.user.id;" for f in files)
    monkeypatch.setattr("src.agent.concierge._fetch_repo_tree", fake_tree)
    monkeypatch.setattr("src.agent.concierge._file_contents_context", fake_files)
    monkeypatch.setattr("src.agent.concierge.retrieve_context", lambda *a, **kw: "")
    monkeypatch.setattr("src.api.routes.run_agent_background", lambda *a, **kw: None)

    llm = _RecordingLLM(result)
    monkeypatch.setattr("src.agent.concierge.get_llms", lambda: (None, llm))
    return requests, llm, read_files


def _audit_rows(company_id):
    db = SessionLocal()
    try:
        return db.query(models.LogAccessAudit).filter(models.LogAccessAudit.tenant_id == company_id).all()
    finally:
        db.close()


def test_admin_outage_report_reads_logs_and_failing_code(seeded_company, monkeypatch):
    from src.agent.state import ConciergeResult
    company_id, _ = seeded_company
    _add_user(company_id, "admin@test.co", "admin")
    _login_as("admin@test.co")
    requests, llm, read_files = _setup_platform_logs(
        monkeypatch, company_id, ConciergeResult(response_text="El carrito falla en cartController.js:11.", resolved=True))

    body = client.post("/api/chat", json={"message": "la tienda da error 500 en el carrito"}).json()

    assert "🟠 Estado de Backend: DEGRADADO" in body["reply"]          # verdict stated by code
    prompt = llm.prompts[0]
    assert "Cannot read properties of undefined" in prompt            # admin sees raw lines...
    assert "maria.lopez@acme.com" not in prompt                        # ...redacted
    assert "<platform_logs>" in prompt
    assert read_files == ["backend/src/controllers/cartController.js"]  # stack trace -> code read
    assert requests and {r.method for r in requests} == {"GET"}        # read-only on the wire
    rows = _audit_rows(company_id)
    assert len(rows) == 1 and rows[0].verdict == "DEGRADADO" and rows[0].service_id == "srv-abc123def456"


def test_employee_gets_verdict_but_never_raw_log_lines(seeded_company, monkeypatch):
    from src.agent.state import ConciergeResult
    company_id, _ = seeded_company
    _login_as(load_test_tickets()[0]["user_email"])
    _, llm, _ = _setup_platform_logs(
        monkeypatch, company_id, ConciergeResult(response_text="Hay errores en el backend.", resolved=True))

    body = client.post("/api/chat", json={"message": "la tienda no carga"}).json()

    assert "DEGRADADO" in body["reply"]
    assert "Cannot read properties of undefined" not in llm.prompts[0]
    assert "<platform_logs>" not in llm.prompts[0]


def test_down_service_always_opens_a_ticket_with_evidence_but_no_log_lines(seeded_company, monkeypatch):
    from src.agent.state import ConciergeResult
    company_id, _ = seeded_company
    _add_user(company_id, "admin@test.co", "admin")
    _login_as("admin@test.co")
    # The model claims it's resolved — the deterministic DOWN verdict overrides it.
    _setup_platform_logs(monkeypatch, company_id,
                         ConciergeResult(response_text="Todo bien.", resolved=True), suspended=True)

    body = client.post("/api/chat", json={"message": "el backend esta caido"}).json()

    assert body["status"] == "investigating"
    assert "🔴 Estado de Backend: CAÍDO" in body["reply"]
    db = SessionLocal()
    try:
        ticket = db.query(models.Ticket).filter(models.Ticket.external_id == body["ticket_external_id"]).first()
        assert "Diagnóstico automático" in ticket.description
        assert "SUSPENDIDO" in ticket.description
        assert "Cannot read properties" not in ticket.description  # log lines never reach ticket/issue
    finally:
        db.close()


def test_restart_request_is_refused_and_routed_to_humans(seeded_company, monkeypatch):
    from src.agent.state import ConciergeResult
    company_id, _ = seeded_company
    _add_user(company_id, "admin@test.co", "admin")
    _login_as("admin@test.co")
    requests, _, _ = _setup_platform_logs(
        monkeypatch, company_id, ConciergeResult(response_text="Listo, reinicié el servidor.", resolved=True))

    body = client.post("/api/chat", json={"message": "reinicia el servidor del backend que esta caido"}).json()

    assert "🔒 No puedo reiniciar" in body["reply"]
    assert "reinicié" not in body["reply"]   # the model's false claim never reaches the user
    assert body["status"] == "investigating"
    assert {r.method for r in requests} <= {"GET"}


def test_log_audit_is_visible_to_admin_only(seeded_company, monkeypatch):
    from src.agent.state import ConciergeResult
    company_id, _ = seeded_company
    _add_user(company_id, "admin@test.co", "admin")
    _login_as("admin@test.co")
    _setup_platform_logs(monkeypatch, company_id, ConciergeResult(response_text="ok", resolved=True))
    client.post("/api/chat", json={"message": "revisa los logs del backend"})

    audit = client.get("/api/tenant/log-audit").json()
    assert len(audit) == 1
    assert audit[0]["triggered_by"] == "admin@test.co" and audit[0]["service_name"] == "Backend"
    assert "message" not in audit[0]  # never log contents

    _login_as(load_test_tickets()[0]["user_email"])
    assert client.get("/api/tenant/log-audit").status_code == 403


def test_connection_test_uses_the_read_only_client(seeded_company, monkeypatch):
    from src.agent.state import ConciergeResult
    company_id, _ = seeded_company
    _add_user(company_id, "admin@test.co", "admin")
    _login_as("admin@test.co")
    requests, _, _ = _setup_platform_logs(monkeypatch, company_id, ConciergeResult(response_text="", resolved=True))

    resp = client.get("/api/tenant/test-logs", params={"service_name": "Backend"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["suspended"] is False
    assert {r.method for r in requests} == {"GET"}
    assert client.get("/api/tenant/test-logs", params={"service_name": "Nope"}).status_code == 404


# ── Fase 10.11: Vercel Log Drain ─────────────────────────────────────────────

import hashlib  # noqa: E402
import hmac  # noqa: E402
import time as _time  # noqa: E402

_VERCEL_SERVICE = {"name": "Storefront", "url": "https://shop.example.com", "provider": "vercel",
                   "service_id": "prj_abcdefghij12345"}


def _configure_vercel(company_id, secret="drain-secret"):
    db = SessionLocal()
    try:
        company = db.query(models.Company).filter(models.Company.id == company_id).first()
        company.monitored_services = json.dumps([_VERCEL_SERVICE])
        company.vercel_drain_secret = encrypt_token(secret)
        db.commit()
    finally:
        db.close()


def _post_drain(company_id, body: bytes, secret="drain-secret", signature=None):
    sig = signature if signature is not None else hmac.new(secret.encode(), body, hashlib.sha1).hexdigest()
    return client.post(f"/api/integrations/vercel/drain/{company_id}", content=body,
                        headers={"x-vercel-signature": sig, "content-type": "application/json"})


def _drain_item(message, project="abcdefghij12345", level="error", status=None, age_s=10):
    item = {"id": "1", "deploymentId": "dpl_x", "source": "lambda", "host": "shop.example.com",
            "timestamp": int((_time.time() - age_s) * 1000), "projectId": project, "level": level,
            "message": message, "path": "/api/cart"}
    if status is not None:
        item["statusCode"] = status
    return item


def _stored_logs(company_id):
    db = SessionLocal()
    try:
        return db.query(models.PlatformLog).filter(models.PlatformLog.tenant_id == company_id).all()
    finally:
        db.close()


def test_drain_rejects_unsigned_forged_and_unknown_tenant(seeded_company):
    company_id, _ = seeded_company
    _configure_vercel(company_id)
    body = json.dumps([_drain_item("x")]).encode()
    assert _post_drain(company_id, body, signature="").status_code == 403
    assert _post_drain(company_id, body, secret="wrong-secret").status_code == 403
    assert _post_drain("not-a-tenant", body).status_code == 403
    assert _stored_logs(company_id) == []


def test_drain_stores_only_configured_projects_redacted(seeded_company):
    company_id, _ = seeded_company
    _configure_vercel(company_id)
    body = json.dumps([
        _drain_item("TypeError: boom for maria@acme.com token=abc123secret"),
        _drain_item("other project's log", project="someoneElsesProject99"),
        _drain_item("", status=-1),  # lambda crashed with no response
    ]).encode()
    resp = _post_drain(company_id, body)
    assert resp.status_code == 200 and resp.json()["stored"] == 2

    rows = _stored_logs(company_id)
    messages = " ".join(r.message for r in rows)
    assert "maria@acme.com" not in messages and "abc123secret" not in messages   # redacted AT REST
    assert "other project's log" not in messages
    assert all(r.level == "error" for r in rows)


def test_drain_accepts_ndjson(seeded_company):
    company_id, _ = seeded_company
    _configure_vercel(company_id)
    body = "\n".join(json.dumps(_drain_item(f"Error {i}")) for i in range(3)).encode()
    assert _post_drain(company_id, body).json()["stored"] == 3


def test_expired_drain_rows_are_purged_on_ingest(seeded_company):
    company_id, _ = seeded_company
    _configure_vercel(company_id)
    old = _drain_item("ancient Error", age_s=4 * 24 * 3600)
    _post_drain(company_id, json.dumps([old]).encode())
    _post_drain(company_id, json.dumps([_drain_item("fresh Error")]).encode())
    assert [r.message for r in _stored_logs(company_id)] == ["fresh Error"]


def test_chat_diagnoses_a_vercel_service_from_drained_logs(seeded_company, monkeypatch):
    from src.agent.state import ConciergeResult
    company_id, _ = seeded_company
    _add_user(company_id, "admin@test.co", "admin")
    _login_as("admin@test.co")
    _configure_vercel(company_id)
    _post_drain(company_id, json.dumps([_drain_item("TypeError: cart is undefined")]).encode())

    async def fake_health(url):
        return {"status": "success", "available": True, "http_status": 200}
    monkeypatch.setattr("src.agent.concierge._health_checker", lambda mcp: fake_health)
    async def no_tree(tenant_id):
        return []
    monkeypatch.setattr("src.agent.concierge._fetch_repo_tree", no_tree)
    monkeypatch.setattr("src.agent.concierge.retrieve_context", lambda *a, **kw: "")
    llm = _RecordingLLM(ConciergeResult(response_text="El carrito falla.", resolved=True))
    monkeypatch.setattr("src.agent.concierge.get_llms", lambda: (None, llm))

    body = client.post("/api/chat", json={"message": "la tienda no carga el carrito"}).json()
    assert "🟠 Estado de Storefront: DEGRADADO" in body["reply"]
    assert "TypeError: cart is undefined" in llm.prompts[0]
