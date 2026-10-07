"""
Fixes found by the first real Render/Concierge run (2026-10-06): cold-start
healthchecks, secrets in config errors, the self-retriggering repo listing,
outage reports with nothing configured, and the E2E script's remote-DB guard.
"""
import asyncio
import json

import httpx
import pytest
from fakes import ScriptedLLM
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import ValidationError

from scripts.e2e_ollama import database_is_local
from src.agents.concierge import concierge_node
from src.agents.concierge.state import ConciergeResult
from src.core.config import Settings
from src.integrations.platform_logs.diagnosis import UP, compute_verdict
from src.security import url_guard
from src.tools import mcp_server


def _chat_state(text, history=()):
    return {"messages": [*history, HumanMessage(content=text)],
            "user_context": {"email": "ana@acme.com", "tenant_id": "t1", "role": "admin", "user_id": "u1"}}


# ── healthcheck vs. a sleeping free-tier instance ────────────────────────────

def _fake_get(outcomes, seen):
    def fake_get(url, timeout, follow_redirects):
        seen.append(timeout)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return httpx.Response(outcome)
    return fake_get


def test_timeout_is_retried_once_with_the_wake_timeout(monkeypatch):
    monkeypatch.setattr(url_guard, "resolve_host", lambda h: ["93.184.216.34"])
    seen = []
    monkeypatch.setattr(httpx, "get", _fake_get([httpx.ReadTimeout("slow"), 200], seen))
    result = json.loads(mcp_server.check_service_status("https://shop.example.com/health"))
    assert result["available"] is True and result["http_status"] == 200 and result["slow_start"] is True
    assert seen[1] > seen[0]


def test_refused_connection_is_down_without_a_retry(monkeypatch):
    monkeypatch.setattr(url_guard, "resolve_host", lambda h: ["93.184.216.34"])
    seen = []
    monkeypatch.setattr(httpx, "get", _fake_get([httpx.ConnectError("refused")], seen))
    result = json.loads(mcp_server.check_service_status("https://shop.example.com/health"))
    assert result["available"] is False and result["error"] == "ConnectError"
    assert len(seen) == 1


def test_cold_start_is_up_with_an_explanation_not_down():
    verdict = compute_verdict({"available": True, "http_status": 200, "slow_start": True}, None, 0)
    assert verdict.status == UP
    assert any("arranque en frío" in e for e in verdict.evidence)


# ── config errors must not echo values ───────────────────────────────────────

def test_rejected_setting_does_not_print_its_value():
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None, render_api_key="rnd_TOPSECRET123")
    assert "TOPSECRET" not in str(exc.value)


# ── Concierge: repo listing and outage without services ──────────────────────

def test_listing_footer_in_history_does_not_retrigger_a_listing(monkeypatch, mcp, no_rag, monitored):
    fetched = []

    async def fake_tree(tenant_id):
        fetched.append(tenant_id)
        return [{"path": "frontend/src/api", "type": "dir"}, {"path": "frontend/src/api/client.js", "type": "file"}]
    monkeypatch.setattr("src.agents.concierge.node._fetch_repo_tree", fake_tree)
    llm = ScriptedLLM(ConciergeResult(response_text="Entendido.", resolved=True))
    monkeypatch.setattr("src.agents.concierge.node.get_llms", lambda: (None, llm))
    history = [HumanMessage(content="hola"),
               AIMessage(content="Hola.\n\n📂 Contenido real (GitHub) de `frontend/src/api/`:\n- client.js")]
    out = asyncio.run(concierge_node(_chat_state("gracias por la ayuda con la api", history),
                                     {"configurable": {"mcp_client": mcp}}))
    assert fetched == []
    assert "📂" not in out["final_response"]


def test_user_follow_up_still_triggers_a_listing(monkeypatch, mcp, no_rag, monitored):
    fetched = []

    async def fake_tree(tenant_id):
        fetched.append(tenant_id)
        return [{"path": "backend/src/middleware", "type": "dir"},
                {"path": "backend/src/middleware/auth.js", "type": "file"}]
    monkeypatch.setattr("src.agents.concierge.node._fetch_repo_tree", fake_tree)
    llm = ScriptedLLM(ConciergeResult(response_text="Ahí está.", resolved=True))
    monkeypatch.setattr("src.agents.concierge.node.get_llms", lambda: (None, llm))
    history = [HumanMessage(content="lista los archivos de controllers"), AIMessage(content="...")]
    asyncio.run(concierge_node(_chat_state("y en middleware?", history), {"configurable": {"mcp_client": mcp}}))
    assert fetched == ["t1"]


def test_outage_with_no_log_service_says_so(monkeypatch, mcp, no_rag, monitored):
    llm = ScriptedLLM(ConciergeResult(response_text="Lo reviso.", resolved=True))
    monkeypatch.setattr("src.agents.concierge.node.get_llms", lambda: (None, llm))
    out = asyncio.run(concierge_node(_chat_state("la tienda no carga"), {"configurable": {"mcp_client": mcp}}))
    assert "No hay servicios monitoreados con acceso a logs" in out["final_response"]
    assert "Service diagnosis: NOT AVAILABLE" in llm.prompts[0]


def test_ordinary_message_gets_no_services_note(monkeypatch, mcp, no_rag, monitored):
    llm = ScriptedLLM(ConciergeResult(response_text="Claro.", resolved=True))
    monkeypatch.setattr("src.agents.concierge.node.get_llms", lambda: (None, llm))
    out = asyncio.run(concierge_node(_chat_state("cómo cambio mi contraseña"), {"configurable": {"mcp_client": mcp}}))
    assert "No hay servicios monitoreados" not in out["final_response"]


def test_employee_is_not_shown_the_configuration_note(monkeypatch, mcp, no_rag, monitored):
    # "my vpn is down" matches the outage pattern but isn't a server problem.
    llm = ScriptedLLM(ConciergeResult(response_text="Reinicia la VPN.", resolved=True))
    monkeypatch.setattr("src.agents.concierge.node.get_llms", lambda: (None, llm))
    state = _chat_state("my vpn is down")
    state["user_context"]["role"] = "employee"
    out = asyncio.run(concierge_node(state, {"configurable": {"mcp_client": mcp}}))
    assert out["final_response"] == "Reinicia la VPN."


# ── E2E script guard ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("url, local", [
    ("sqlite:///./app.db", True),
    ("postgresql://postgres:aether@localhost:55432/aether", True),
    ("postgresql+psycopg://u:p@127.0.0.1/db", True),
    ("postgresql://postgres.abc:pw@aws-0-us-east-2.pooler.supabase.com:6543/postgres", False),
    ("postgresql://u:p@ep-x.us-east-2.aws.neon.tech/db", False),
])
def test_e2e_script_only_treats_this_machine_as_local(url, local):
    assert database_is_local(url) is local
