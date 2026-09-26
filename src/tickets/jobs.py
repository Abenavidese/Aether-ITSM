"""
Queue job handlers for the ticket lifecycle (roadmap 2.2) — the async half.

Handlers are idempotent because delivery is at-least-once:
- run_ticket inspects the LangGraph checkpoint before doing anything: no
  checkpoint -> start; interrupted mid-graph (worker killed) -> resume from
  the last completed node; paused for approval or finished -> only sync the
  ticket row. Known limit: a node that was mid-flight when the worker died
  runs again (a tool call inside it could repeat).
- create_github_issue does nothing if the ticket already has its issue URL.
  Known limit: a crash between GitHub's 201 and saving the URL can create a
  duplicate issue on retry.
"""
import asyncio
import logging

from langchain_core.messages import HumanMessage

from src.agent.graph import get_workflow
from src.config import Settings
from src.integrations.github import create_issue
from src.jobs.queue import JobKind
from src.jobs.worker import JobWorker, PermanentJobError, WorkerDeps
from src.observability.tracing import trace_scope

from . import service
from .service import TicketRun

logger = logging.getLogger(__name__)

_TERMINAL = ("resolved", "escalated")
_NOTHING_TO_RUN = object()  # paused for a human, or already finished


def ticket_graph(checkpointer):
    return get_workflow().compile(checkpointer=checkpointer, interrupt_after=["draft_plan"])


def ticket_thread_config(tenant_id: str, external_id: str, mcp_client) -> dict:
    # Namespaced by tenant so ticket IDs can never collide or be resumed across
    # companies (see approve_ticket for the matching check). mcp_client rides
    # along in `configurable` so nodes get it injected, never as a global.
    return {"configurable": {"thread_id": f"{tenant_id}:{external_id}", "mcp_client": mcp_client}}


def ticket_trace_id(external_id: str) -> str:
    # One trace per ticket: the first run and the post-approval resume append
    # to the same trace, so GET /tenant/tickets/{id}/trace shows the whole path.
    return f"ticket:{external_id}"


def awaiting_approval(snapshot) -> bool:
    values = snapshot.values or {}
    return bool(snapshot.next) and values.get("proposed_plan") is not None and values.get("human_approved") is None


def _initial_state(run: TicketRun, image_base64: str | None) -> dict:
    text = f"Title: {run.title}\n\nDescription: {run.description}"
    content = (
        [{"type": "text", "text": text}, {"type": "image_url", "image_url": {"url": image_base64}}]
        if image_base64 else text
    )
    return {
        "messages": [HumanMessage(content=content)],
        "ticket_id": run.external_id,
        "company_id": run.tenant_id,
        "user_context": {"email": run.requester_email, "tenant_id": run.tenant_id},
        "assessed_risk": 4,
        "intent": "unknown",
    }


async def run_ticket(payload: dict, deps: WorkerDeps) -> None:
    run = await asyncio.to_thread(service.load_ticket_run, payload["ticket_id"])
    if run is None:
        raise PermanentJobError(f"ticket {payload['ticket_id']} does not exist")
    if run.status in _TERMINAL:
        return

    app = ticket_graph(deps.checkpointer)
    config = ticket_thread_config(run.tenant_id, run.external_id, deps.mcp_client)
    snapshot = await app.aget_state(config)

    if not snapshot.values:
        graph_input = _initial_state(run, payload.get("image_base64"))
    elif snapshot.next and not awaiting_approval(snapshot):
        logger.warning("Resuming interrupted agent run for ticket %s from its last checkpoint", run.external_id)
        graph_input = None
    else:
        graph_input = _NOTHING_TO_RUN

    if graph_input is not _NOTHING_TO_RUN:
        logger.info("Agent run started for ticket %s (tenant %s)", run.external_id, run.tenant_id)
        async with trace_scope(ticket_trace_id(run.external_id), "ticket", run.tenant_id):
            async for step in app.astream(graph_input, config=config):
                for node_name in step:
                    logger.info("--- Node '%s' finished for ticket %s ---", node_name, run.external_id)
        snapshot = await app.aget_state(config)

    await asyncio.to_thread(service.apply_graph_outcome, run.tenant_id, run.external_id,
                            snapshot.values, awaiting_approval(snapshot))


async def run_ticket_dead(payload: dict, deps: WorkerDeps, error: str) -> None:
    await asyncio.to_thread(service.escalate_after_failure, payload["ticket_id"], error)


async def create_github_issue(payload: dict, deps: WorkerDeps) -> None:
    target = await asyncio.to_thread(service.load_issue_target, payload["ticket_id"],
                                     payload.get("reason"), payload.get("compliance_notes"))
    if target is None:
        return
    url = await create_issue(target.repo, target.token, target.title, target.body)
    await asyncio.to_thread(service.save_issue_url, payload["ticket_id"], url)


HANDLERS = {
    JobKind.RUN_TICKET.value: run_ticket,
    JobKind.CREATE_GITHUB_ISSUE.value: create_github_issue,
}
DEAD_HANDLERS = {JobKind.RUN_TICKET.value: run_ticket_dead}


def build_worker(deps: WorkerDeps, settings: Settings) -> JobWorker:
    return JobWorker(
        deps, HANDLERS, dead_handlers=DEAD_HANDLERS,
        concurrency=settings.jobs_concurrency, poll_interval=settings.jobs_poll_seconds,
        visibility_timeout=settings.jobs_visibility_timeout_seconds,
    )
