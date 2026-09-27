"""
Roadmap 1.2 — every tenant setting has a real effect: the fields nothing used
(llm_engine, webhook_url, mcp_server_url, mcp_auth_token) are gone, and the
models actually answering are shown read-only.
"""
import asyncio
import uuid

import httpx
import pytest

from src.db import models
from src.db.database import SessionLocal, engine
from src.security.hashing import get_password_hash

PASSWORD = "Irrelevant123!"


@pytest.fixture
def admin_email():
    models.Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        company = models.Company(name=f"Settings {uuid.uuid4().hex[:6]}")
        db.add(company)
        db.flush()
        email = f"{uuid.uuid4().hex[:6]}.admin@acme.com"
        db.add(models.User(email=email, full_name="Admin", password_hash=get_password_hash(PASSWORD),
                           role="admin", company_id=company.id))
        db.commit()
        return email
    finally:
        db.close()


def _as_admin(email: str, calls):
    from src.main import app

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.post("/api/auth/login", json={"email": email, "password": PASSWORD})).status_code == 200
            return [await call(client) for call in calls]
    return asyncio.run(scenario())


def test_settings_show_real_models_and_no_dead_fields(admin_email):
    [response] = _as_admin(admin_email, [lambda c: c.get("/api/tenant/settings")])
    body = response.json()
    assert not {"llm_engine", "webhook_url", "mcp_server_url"} & body.keys()
    assert body["llm_models"]["provider"] == "ollama"
    assert body["llm_models"]["super"]  # the configured model id, not a tenant choice


def test_onboarding_needs_no_engine_choice(admin_email):
    [response] = _as_admin(admin_email, [lambda c: c.post("/api/tenant/onboarding", json={
        "github_token": "ghp_" + "x" * 36, "github_repo": "acme/api",
    })])
    assert response.status_code == 200, response.text
    assert not hasattr(models.Company, "llm_engine")
