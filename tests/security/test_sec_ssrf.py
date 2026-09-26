"""Fase 11.4: the healthcheck tool can't be turned into a request to our own network."""
import asyncio
import json

import httpx
import pytest
from langchain_core.messages import HumanMessage
from sec_fakes import ScriptedLLM

from src.agent.concierge import concierge_node
from src.agent.state import ConciergeResult
from src.security import url_guard
from src.security.url_guard import UnsafeURLError, validate_outbound_url
from src.tools import mcp_server


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",   # cloud metadata
    "http://127.0.0.1:8000/admin",
    "http://localhost/",
    "http://10.0.0.5/",
    "http://[::1]/",
    "http://[::ffff:127.0.0.1]/",                 # IPv4-mapped loopback
    "file:///etc/passwd",
    "gopher://example.com/",
    "http://user:pass@example.com/",
])
def test_unsafe_urls_are_refused(url, monkeypatch):
    monkeypatch.setattr(url_guard, "resolve_host", lambda h: ["127.0.0.1"])
    with pytest.raises(UnsafeURLError):
        validate_outbound_url(url)


def test_hostname_resolving_to_a_private_address_is_refused(monkeypatch):
    monkeypatch.setattr(url_guard, "resolve_host", lambda h: ["93.184.216.34", "192.168.1.10"])
    with pytest.raises(UnsafeURLError, match="non-public"):
        validate_outbound_url("https://looks-public.example.com/health")


def test_private_opt_in_never_includes_metadata(monkeypatch):
    assert validate_outbound_url("http://10.0.0.5/health", allow_private=True)
    with pytest.raises(UnsafeURLError):
        validate_outbound_url("http://169.254.169.254/", allow_private=True)


def test_public_url_is_allowed(monkeypatch):
    monkeypatch.setattr(url_guard, "resolve_host", lambda h: ["93.184.216.34"])
    assert validate_outbound_url("https://shop.example.com/health")


def test_tool_makes_no_request_to_an_unsafe_url(monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError("no HTTP request may be made")
    monkeypatch.setattr(httpx, "get", forbidden)
    result = json.loads(mcp_server.check_service_status("http://169.254.169.254/latest/meta-data/"))
    assert result["status"] == "error" and "refused" in result["message"]


def test_tool_does_not_follow_redirects(monkeypatch):
    monkeypatch.setattr(url_guard, "resolve_host", lambda h: ["93.184.216.34"])
    seen = {}

    def fake_get(url, timeout, follow_redirects):
        seen["follow_redirects"] = follow_redirects
        return httpx.Response(302, headers={"location": "http://127.0.0.1/"})
    monkeypatch.setattr(httpx, "get", fake_get)
    result = json.loads(mcp_server.check_service_status("https://shop.example.com/health"))
    assert seen["follow_redirects"] is False
    assert result["available"] is True and result["http_status"] == 302


def _chat_state(text):
    return {"messages": [HumanMessage(content=text)],
            "user_context": {"email": "ana@acme.com", "tenant_id": "t1", "role": "employee", "user_id": "u1"}}


def test_chat_cannot_healthcheck_an_unconfigured_url(monkeypatch, mcp, no_rag, monitored):
    llm = ScriptedLLM(ConciergeResult(response_text="Reviso eso", resolved=True, tool_name="check_service_status",
                                      tool_args={"service_url": "http://169.254.169.254/latest/meta-data/"}))
    monkeypatch.setattr("src.agent.concierge.get_llms", lambda: (None, llm))
    out = asyncio.run(concierge_node(_chat_state("revisa http://169.254.169.254/latest/meta-data/"),
                                     {"configurable": {"mcp_client": mcp}}))
    assert mcp.calls == []
    assert "169.254" not in out["final_response"].split("Reviso eso", 1)[1]


def test_chat_healthcheck_of_a_configured_service_is_summarized(monkeypatch, no_rag, monitored):
    from sec_fakes import RecordingMCP
    mcp = RecordingMCP(json.dumps({"status": "success", "service_url": monitored[0]["url"],
                                   "available": False, "http_status": 503, "internal": "x"}))
    llm = ScriptedLLM(ConciergeResult(response_text="Revisé la tienda.", resolved=True,
                                      tool_name="check_service_status",
                                      tool_args={"service_url": monitored[0]["url"] + "/"}))
    monkeypatch.setattr("src.agent.concierge.get_llms", lambda: (None, llm))
    out = asyncio.run(concierge_node(_chat_state("la tienda no carga?"), {"configurable": {"mcp_client": mcp}}))
    assert mcp.calls == [("check_service_status", {"service_url": monitored[0]["url"] + "/"})]
    assert "NO disponible (HTTP 503)" in out["final_response"]
    assert "internal" not in out["final_response"]  # raw tool JSON is never shown
