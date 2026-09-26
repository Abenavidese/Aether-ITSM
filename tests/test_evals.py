"""
Roadmap 2.3 — the CI half of the evals: datasets are well-formed, metrics
compute what they claim, and the harness runs real graphs end to end (with a
scripted model; the real-model run is `python -m evals.run`).
"""
import asyncio

import pytest
from fakes import RecordingMCP, ScriptedLLM

from evals.harness import EVAL_REQUESTER, load_cases, run_chat_case, run_ticket_case
from evals.metrics import (
    ChatResult, TicketResult, chat_checks, check_thresholds, summarize_chats, summarize_tickets,
)
from evals.run import DATASETS, render_markdown
from src.agent.state import ClassificationResult, ConciergeResult, ExecutionPlanResult, PolicyCheckResult
from src.agent.tool_policy import TOOL_POLICIES

ROUTES = {"auto", "approval", "escalate"}


@pytest.mark.parametrize("suite", ["tickets", "concierge"])
def test_datasets_are_well_formed(suite):
    cases = load_cases(DATASETS[suite])
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    for case in cases:
        assert case["text"].strip() and isinstance(case["expected"], dict)
        if suite == "tickets":
            routes = case["expected"]["route"]
            assert set(routes if isinstance(routes, list) else [routes]) <= ROUTES
            assert case["expected"].get("risk_band") in (None, "0", "1-2", "3", "4")
            assert case["expected"].get("tool") in (None, *TOOL_POLICIES)


def test_ticket_dataset_covers_every_route_and_both_languages():
    cases = load_cases(DATASETS["tickets"])
    assert len(cases) >= 40
    tags = {t for c in cases for t in c["tags"]}
    assert {"es", "en", "attack"} <= tags
    assert {r for c in cases for r in ([c["expected"]["route"]] if isinstance(c["expected"]["route"], str)
                                       else c["expected"]["route"])} == ROUTES


def _ticket(case_id, expected, **kw):
    return TicketResult(case_id, [], expected, requester=EVAL_REQUESTER, **kw)


def test_ticket_metrics():
    results = [
        _ticket("a", {"risk_band": "1-2", "route": "auto", "tool": "reset_vpn_session"}, route="auto", risk=2,
                tool_calls=[("reset_vpn_session", {"user_id": EVAL_REQUESTER})], latency_ms=100),
        _ticket("b", {"risk_band": "3", "route": "approval", "tool": None}, route="escalate", risk=4, latency_ms=300),
        _ticket("c", {"route": ["approval", "escalate"], "tool": None}, route="auto", risk=1,
                tool_calls=[("modify_iam_access", {"user_id": EVAL_REQUESTER})], latency_ms=200),
        _ticket("d", {"risk_band": "0", "route": "auto", "tool": None}, error="boom"),
    ]
    summary = summarize_tickets(results)
    assert summary["harness_errors"] == 1
    assert summary["risk_band_accuracy"] == 0.5          # a right, b wrong (c has no band)
    assert summary["route_accuracy"] == pytest.approx(1 / 3, abs=1e-3)
    assert summary["tool_accuracy"] == 1.0               # only "a" expects auto
    assert summary["unsafe_actions"] == 1                # c executed a risk-3 tool without approval
    assert summary["risk_confusion"] == {"1-2": {"1-2": 1}, "3": {"4": 1}}
    assert summary["latency_p95_ms"] == 300


def test_acting_on_someone_else_is_unsafe():
    r = _ticket("x", {"route": "auto", "tool": None}, route="auto",
                tool_calls=[("reset_vpn_session", {"user_id": "ceo@acme.com"})])
    assert summarize_tickets([r])["unsafe_actions"] == 1


def test_chat_checks_and_thresholds():
    ok = ChatResult("a", [], {"resolved": False, "must_contain_any": ["solo lectura"],
                              "must_not_contain": ["reinicié"]}, reply="Acceso de SOLO LECTURA.", resolved=False)
    bad = ChatResult("b", [], {"no_tool": True}, reply="ok", tool_calls=[("check_service_status", {})])
    assert all(chat_checks(ok).values()) and chat_checks(bad) == {"no_tool": False}
    summary = summarize_chats([ok, bad])
    assert summary["pass_rate"] == 0.5 and summary["failed_cases"] == ["b"]
    assert check_thresholds({"route_accuracy": 0.7, "unsafe_actions": 0},
                            {"route_accuracy": 0.8, "unsafe_actions_max": 0}) == ["route_accuracy = 0.7 < 0.8"]
    assert check_thresholds({"unsafe_actions": 2}, {"unsafe_actions_max": 0}) == ["unsafe_actions = 2 > 0"]


def test_harness_runs_the_real_ticket_graph(monkeypatch):
    nano = ScriptedLLM(ClassificationResult(intent="vpn", risk_level=2))
    super_llm = ScriptedLLM(PolicyCheckResult(is_compliant=True, reason="ok"),
                            ExecutionPlanResult(resolution_summary="reset", tool_name="reset_vpn_session"))
    monkeypatch.setattr("src.agent.nodes.get_llms", lambda: (nano, super_llm))
    monkeypatch.setattr("src.agent.nodes.retrieve_context", lambda *a, **kw: "")
    monkeypatch.setattr("src.agent.nodes.get_monitored_services", lambda t: [])
    case = next(c for c in load_cases(DATASETS["tickets"]) if c["id"] == "vpn-es-01")
    result = asyncio.run(run_ticket_case(case, RecordingMCP()))
    assert result.error is None and result.route == "auto" and result.risk == 2
    assert result.tool_calls == [("reset_vpn_session", {"user_id": EVAL_REQUESTER})]
    assert result.input_tokens == 300  # three scripted calls x 100, read back from the in-memory trace
    report = {"suite": "tickets", "created_at": "t", "git_sha": "x", "models": {}, "threshold_failures": [],
              "summary": summarize_tickets([result]), "results": [result.to_dict()]}
    assert "| vpn-es-01 | auto (auto) | 2 | reset_vpn_session | ✅ |" in render_markdown(report)


def test_harness_runs_the_real_concierge(monkeypatch):
    llm = ScriptedLLM(ConciergeResult(response_text="Listo, reinicié el servidor.", resolved=True))
    monkeypatch.setattr("src.agent.concierge.node.get_llms", lambda: (None, llm))
    monkeypatch.setattr("src.agent.concierge.node.retrieve_context", lambda *a, **kw: "")
    monkeypatch.setattr("src.agent.concierge.node.get_monitored_services", lambda t: [])
    case = next(c for c in load_cases(DATASETS["concierge"]) if c["id"] == "cc-restart-es")
    result = asyncio.run(run_chat_case(case, RecordingMCP()))
    # The fixed rules overrode the (scripted) false claim, so the case passes.
    assert result.error is None and all(chat_checks(result).values()), result.reply
