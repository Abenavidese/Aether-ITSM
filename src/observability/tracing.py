"""
Lightweight tracing for agent runs (roadmap 2.4).

A run (a ticket through the graph, one chat turn, one eval case) opens a
trace_scope(); everything inside it — graph nodes via traced_node(), LLM
calls via record_llm_call() in structured_output.py — appends Span records
to a collector held in a ContextVar. ContextVars follow the run into asyncio
tasks and asyncio.to_thread, so no function signature has to carry it.

At scope exit the spans are written in ONE insert (off the event loop), or
not at all (persist=False, used by the eval harness, which reads them
directly). Tracing must never break a run: persistence errors are logged
and swallowed, and code outside any scope simply records nothing.

Deliberately not OpenTelemetry: one table answers the questions this
product needs (tokens/cost per tenant, p95 per node, a ticket's path)
without an extra collector to deploy. The Span shape maps 1:1 to OTel
spans if an exporter is ever added.
"""
import asyncio
import functools
import logging
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class Span:
    kind: str                 # node | llm
    name: str
    duration_ms: int
    started_at: datetime
    status: str = "ok"
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass
class Trace:
    trace_id: str
    source: str
    tenant_id: str | None
    spans: list[Span] = field(default_factory=list)

    def llm_tokens(self) -> tuple[int, int]:
        llm = [s for s in self.spans if s.kind == "llm"]
        return sum(s.input_tokens or 0 for s in llm), sum(s.output_tokens or 0 for s in llm)


_current: ContextVar[Trace | None] = ContextVar("aether_trace", default=None)


def current_trace() -> Trace | None:
    return _current.get()


def _persist(trace: Trace) -> None:
    from src.db.database import SessionLocal
    from src.db.models import AgentSpan
    db = SessionLocal()
    try:
        db.add_all([
            AgentSpan(tenant_id=trace.tenant_id, trace_id=trace.trace_id, source=trace.source, kind=s.kind,
                      name=s.name, model=s.model, input_tokens=s.input_tokens, output_tokens=s.output_tokens,
                      duration_ms=s.duration_ms, status=s.status, started_at=s.started_at)
            for s in trace.spans
        ])
        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def trace_scope(trace_id: str, source: str, tenant_id: str | None, *, persist: bool = True):
    trace = Trace(trace_id=trace_id, source=source, tenant_id=tenant_id)
    token = _current.set(trace)
    try:
        yield trace
    finally:
        _current.reset(token)
        if persist and trace.spans:
            try:
                await asyncio.to_thread(_persist, trace)
            except Exception:
                logger.warning("Could not persist %d span(s) for trace %s", len(trace.spans), trace_id,
                               exc_info=True)


def _record(span: Span) -> None:
    trace = _current.get()
    if trace is not None:
        trace.spans.append(span)


def record_llm_call(name: str, model: str | None, started: float, started_at: datetime,
                    usage: dict | None, ok: bool) -> None:
    usage = usage or {}
    _record(Span(kind="llm", name=name, model=model, started_at=started_at,
                 duration_ms=int((time.perf_counter() - started) * 1000), status="ok" if ok else "error",
                 input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens")))


def traced_node(name: str, fn):
    """
    Wraps a LangGraph node so its duration and outcome become a span.
    functools.wraps keeps the signature visible (LangGraph inspects it to
    decide whether to pass `config`).
    """
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        started, started_at = time.perf_counter(), datetime.now(timezone.utc)
        status = "ok"
        try:
            result = await fn(*args, **kwargs)
            if isinstance(result, dict) and (result.get("technical_error") or result.get("action_refused")):
                status = "error"
            return result
        except BaseException:
            status = "error"
            raise
        finally:
            _record(Span(kind="node", name=name, started_at=started_at, status=status,
                         duration_ms=int((time.perf_counter() - started) * 1000)))
    return wrapper
