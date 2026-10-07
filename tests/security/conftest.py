"""Fixtures for the Fase 11 security suite (fakes live in tests/fakes.py)."""
import pytest
from fakes import RecordingMCP, empty_retrieval


@pytest.fixture
def mcp():
    return RecordingMCP()


@pytest.fixture
def no_rag(monkeypatch):
    monkeypatch.setattr("src.agents.ticket_flow.nodes.common.retrieve_context", lambda *a, **kw: "")
    monkeypatch.setattr("src.agents.concierge.node.retrieve", empty_retrieval)


@pytest.fixture
def monitored(monkeypatch):
    """One configured healthcheck target for every tenant."""
    services = [{"name": "Tienda", "url": "https://shop.example.com/health"}]
    for target in ("src.agents.ticket_flow.nodes.common.get_monitored_services", "src.agents.concierge.node.get_monitored_services"):
        monkeypatch.setattr(target, lambda tenant_id: services)
    return services


@pytest.fixture(autouse=True)
def _schema():
    # Nodes look tenants up in the DB (github config, log services); an
    # unknown tenant just yields "nothing configured", but the tables must
    # exist. test_flow.py deletes the sqlite file between its own tests.
    from src.db import models
    from src.db.database import engine
    models.Base.metadata.create_all(bind=engine)
