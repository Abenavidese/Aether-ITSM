"""
Runs eval cases through the REAL agents (roadmap 2.3): the ticket graph and
the Concierge, with whatever models get_llms() returns (local Ollama by
default, Nebius via .env) — or a scripted model in CI.

Side-effect free by construction: an in-memory checkpointer, a synthetic
tenant id (nothing configured, nothing persisted), traces kept in memory
(persist=False) and read back for tokens. Tool calls go to the injected MCP
client — the real tool server only simulates its actions, and the eval
records every call to score it.
"""
import json
import time
import uuid
from pathlib import Path

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from src.agent.concierge import get_concierge_workflow
from src.observability.tracing import trace_scope
from src.tickets.jobs import awaiting_approval, ticket_graph
from src.tickets.service import is_escalated

from .metrics import ChatResult, TicketResult

EVAL_TENANT = "eval-tenant"
EVAL_REQUESTER = "eval.requester@example.com"


def load_cases(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


class RecordingMCPClient:
    """Wraps an MCP client (real or fake) and records every executed call."""

    def __init__(self, inner):
        self._inner = inner
        self.calls: list[tuple[str, dict]] = []

    def prompt_catalog(self, only=None, hidden_params=None):
        return self._inner.prompt_catalog(only=only, hidden_params=hidden_params)

    async def call_tool(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        return await self._inner.call_tool(name, arguments)


def _route(snapshot) -> str:
    if awaiting_approval(snapshot):
        return "approval"
    return "escalate" if is_escalated(snapshot.values) else "auto"


async def run_ticket_case(case: dict, mcp_client) -> TicketResult:
    result = TicketResult(case["id"], case.get("tags", []), case["expected"], requester=EVAL_REQUESTER)
    spy = RecordingMCPClient(mcp_client)
    app = ticket_graph(MemorySaver())
    config = {"configurable": {"thread_id": f"eval:{case['id']}:{uuid.uuid4().hex[:6]}", "mcp_client": spy}}
    state = {
        "messages": [HumanMessage(content=f"Title: {case['text'][:80]}\n\nDescription: {case['text']}")],
        "ticket_id": case["id"], "company_id": EVAL_TENANT,
        "user_context": {"email": EVAL_REQUESTER, "tenant_id": EVAL_TENANT},
        "assessed_risk": 4, "intent": "unknown",
    }
    started = time.perf_counter()
    try:
        async with trace_scope(f"eval:{case['id']}", "eval", None, persist=False) as trace:
            async for _ in app.astream(state, config=config):
                pass
        snapshot = await app.aget_state(config)
    except Exception as e:  # the harness must survive any single case
        result.error = f"{type(e).__name__}: {e}"
        return result
    result.latency_ms = int((time.perf_counter() - started) * 1000)
    result.route = _route(snapshot)
    result.risk = snapshot.values.get("assessed_risk")
    result.technical_error = bool(snapshot.values.get("technical_error"))
    result.tool_calls = spy.calls
    result.input_tokens, result.output_tokens = trace.llm_tokens()
    return result


async def run_chat_case(case: dict, mcp_client) -> ChatResult:
    result = ChatResult(case["id"], case.get("tags", []), case["expected"])
    spy = RecordingMCPClient(mcp_client)
    app = get_concierge_workflow().compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": f"eval-chat:{case['id']}:{uuid.uuid4().hex[:6]}", "mcp_client": spy}}
    state = {
        "messages": [HumanMessage(content=case["text"])], "diagnosis_report": None,
        "user_context": {"email": EVAL_REQUESTER, "tenant_id": EVAL_TENANT, "role": "employee", "user_id": None},
    }
    started = time.perf_counter()
    try:
        async with trace_scope(f"eval-chat:{case['id']}", "eval", None, persist=False) as trace:
            async for _ in app.astream(state, config=config):
                pass
        values = (await app.aget_state(config)).values
    except Exception as e:
        result.error = f"{type(e).__name__}: {e}"
        return result
    result.latency_ms = int((time.perf_counter() - started) * 1000)
    result.reply = values.get("final_response", "")
    result.resolved = values.get("resolved")
    result.tool_calls = spy.calls
    result.input_tokens, result.output_tokens = trace.llm_tokens()
    return result
