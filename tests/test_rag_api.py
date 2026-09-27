"""
Fase 14 — the knowledge base through the HTTP API: asynchronous indexing via
the job queue, document states, feedback review, role checks, and the chat
answer carrying only the sources it actually cites.
"""
import asyncio
import uuid

import pytest
from fakes import RecordingMCP, ScriptedLLM
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver
from test_rag_retrieval import MODEL, BowEmbeddings

from src.agent.state import ConciergeResult
from src.db import models
from src.db.database import SessionLocal, engine
from src.jobs.worker import WorkerDeps
from src.security.hashing import get_password_hash

POLICY = b"""# Politica VPN

## Error ERR_VPN_809

ERR_VPN_809 significa que la red bloquea el puerto UDP 4500. Use el hotspot del celular.
"""


@pytest.fixture(autouse=True)
def _schema_and_queue(monkeypatch):
    models.Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    db.query(models.Job).delete()
    db.commit()
    db.close()
    # Indexing job and API use the bag-of-words fake instead of a real model.
    monkeypatch.setattr("src.rag.embeddings.get_embeddings", lambda: BowEmbeddings())
    monkeypatch.setattr("src.rag.embeddings.embedding_model_id", lambda: MODEL)
    monkeypatch.setattr("src.rag.router.embedding_model_id", lambda: MODEL)


@pytest.fixture
def admin():
    from src.main import app
    client = TestClient(app)
    email = f"kbapi-{uuid.uuid4().hex[:8]}@acme.com"
    assert client.post("/api/auth/register", json={"email": email, "password": "Irrelevant123!",
                                                   "full_name": "KB Admin", "company_name": "KB API Co"}).status_code in (200, 201)
    assert client.post("/api/auth/login", json={"email": email, "password": "Irrelevant123!"}).status_code == 200
    db = SessionLocal()
    tenant_id = db.query(models.User).filter_by(email=email).one().company_id
    db.close()
    return client, tenant_id


def _employee(tenant_id: str) -> TestClient:
    from src.main import app
    email = f"emp-{uuid.uuid4().hex[:8]}@acme.com"
    db = SessionLocal()
    db.add(models.User(email=email, full_name="Ana", password_hash=get_password_hash("Irrelevant123!"),
                       role="employee", company_id=tenant_id))
    db.commit()
    db.close()
    client = TestClient(app)
    assert client.post("/api/auth/login", json={"email": email, "password": "Irrelevant123!"}).status_code == 200
    return client


def _drain_queue():
    from src.config import get_settings
    from src.jobs.registry import build_worker
    worker = build_worker(WorkerDeps(None, None), get_settings())
    while asyncio.run(worker.run_once()):
        pass


def _docs(client):
    return {d["filename"]: d for d in client.get("/api/tenant/knowledge").json()}


def test_upload_is_indexed_by_the_queue(admin):
    client, _ = admin
    response = client.post("/api/tenant/knowledge", data={"source_type": "company_policy"},
                           files={"file": ("vpn.md", POLICY, "text/markdown")})
    assert response.status_code == 202 and response.json()["status"] == "queued"
    assert _docs(client)["vpn.md"]["status"] == "queued"      # not indexed inside the request

    _drain_queue()
    doc = _docs(client)["vpn.md"]
    assert doc["status"] == "ready" and doc["chunks"] >= 1 and doc["embedding_model"] == MODEL and not doc["stale"]

    again = client.post("/api/tenant/knowledge", data={"source_type": "company_policy"},
                        files={"file": ("vpn.md", POLICY, "text/markdown")})
    assert again.json()["unchanged"] is True


def test_unreadable_pdf_is_rejected_with_the_reason(admin):
    client, _ = admin
    blank = (b"%PDF-1.4\n1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
             b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
             b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >> endobj\n"
             b"trailer << /Root 1 0 R >>\n%%EOF\n")
    response = client.post("/api/tenant/knowledge", data={"source_type": "technical_repo"},
                           files={"file": ("escaneado.pdf", blank, "application/pdf")})
    assert response.status_code in (400, 422)


def test_feedback_waits_for_review_and_employees_cannot_see_it(admin):
    client, tenant_id = admin
    response = client.post("/api/tenant/knowledge/feedback",
                           json={"ticket_id": "IT-77", "feedback_text": "Para ERR_VPN_809 usar TCP 443."})
    assert response.json()["status"] == "pending_review"
    doc = _docs(client)["Feedback_IT-77"]
    assert doc["status"] == "pending_review" and "TCP 443" in doc["content"]

    employee = _employee(tenant_id)
    assert "Feedback_IT-77" not in _docs(employee)
    assert employee.post(f"/api/tenant/knowledge/{doc['id']}/review", json={"approve": True}).status_code == 403
    assert employee.get("/api/tenant/knowledge/insights").status_code == 403

    assert client.post(f"/api/tenant/knowledge/{doc['id']}/review", json={"approve": True}).json()["status"] == "queued"
    _drain_queue()
    assert _docs(client)["Feedback_IT-77"]["status"] == "ready"


def test_insights_list_unanswered_questions(admin):
    from src.rag import service
    client, tenant_id = admin
    retriever = service.build_retriever(embeddings=BowEmbeddings(), model_id=MODEL,
                                        reranker=service.get_reranker("none"))
    service.retrieve(tenant_id, "¿cuál es el menú del comedor?", sources=["company_policy"], retriever=retriever)
    insights = client.get("/api/tenant/knowledge/insights").json()
    assert insights["searches"] >= 1 and insights["empty_rate"] == 1.0
    assert insights["unanswered_questions"][0]["query"] == "¿cuál es el menú del comedor?"


def test_chat_returns_only_the_sources_it_cites(admin, monkeypatch):
    from src.main import app
    from src.rag import service

    client, _ = admin
    client.post("/api/tenant/knowledge", data={"source_type": "company_policy"},
                files={"file": ("vpn.md", POLICY, "text/markdown")})
    _drain_queue()
    retriever = service.build_retriever(embeddings=BowEmbeddings(), model_id=MODEL,
                                        reranker=service.get_reranker("none"))
    retriever.config.max_distance = 0.9
    monkeypatch.setattr(service, "_retriever", retriever)
    llm = ScriptedLLM(ConciergeResult(
        response_text="Es el puerto UDP 4500 bloqueado [1]; use el hotspot [3].", resolved=True))
    monkeypatch.setattr("src.agent.concierge.node.get_llms", lambda: (None, llm))
    monkeypatch.setattr("src.agent.concierge.node.get_monitored_services", lambda t: [])
    app.state.checkpointer = MemorySaver()
    app.state.mcp_client = RecordingMCP()

    reply = client.post("/api/chat", json={"message": "me sale ERR_VPN_809"}).json()
    assert reply["status"] == "resolved"
    assert "[1]" in reply["reply"] and "[3]" not in reply["reply"]       # invented citation removed
    assert [(s["n"], s["filename"], s["section"]) for s in reply["sources"]] == [(1, "vpn.md", "Error ERR_VPN_809")]
    # The model was shown the numbered passage it cited.
    assert "[1] vpn.md — Sección: Error ERR_VPN_809" in str(llm.prompts[0])
