"""
Agent runs for tickets: the queue job handlers (roadmap 2.2) and the
post-approval resume — the async half of the ticket lifecycle.

Handlers are idempotent because delivery is at-least-once:
- run_ticket inspects the LangGraph checkpoint before doing anything: no
  checkpoint -> start; interrupted mid-graph (worker killed) -> resume from
  the last completed node; paused for approval or finished -> only sync the
  ticket row. Known limit: a node that was mid-flight when the worker died
  runs again (a tool call inside it could repeat).
- create_github_issue does nothing if the ticket already has its issue URL.
  Known limit: a crash between GitHub's 201 and saving the URL can create a
  duplicate issue on retry.
- propose_code_fix (Fase 16) does nothing if the ticket already has its PR;
  on GitHub, an existing open PR for the ticket's aether/fix-* branch is
  reused instead of opening another.
"""
import asyncio
import logging

from langchain_core.messages import HumanMessage

from src.agents.code_fix import RejectedFix, propose_fix
from src.agents.runtime.vision import describe_attachment
from src.agents.ticket_flow.runner import awaiting_approval, ticket_graph, ticket_thread_config, ticket_trace_id
from src.core.config import get_settings
from src.integrations.github import create_fix_pull_request, create_issue, get_file_content
from src.integrations.issue_format import build_fix_pull_request
from src.jobs.queue import JobKind
from src.jobs.worker import PermanentJobError, WorkerDeps
from src.llm.factory import get_llms
from src.observability.tracing import trace_scope
from src.services import tickets as service
from src.services.tickets import TicketRun

logger = logging.getLogger(__name__)

_TERMINAL = ("resolved", "escalated")
_NOTHING_TO_RUN = object()  # paused for a human, or already finished


async def _initial_state(run: TicketRun, image_base64: str | None) -> dict:
    # The attached image is read by the vision model and joins the ticket as
    # text: every node (risk floor, RAG, policy) works on a plain string, and
    # the text-only models never get an image part they can't see.
    text = await describe_attachment(f"Title: {run.title}\n\nDescription: {run.description}", image_base64)
    return {
        "messages": [HumanMessage(content=text)],
        "ticket_id": run.external_id,
        "company_id": run.tenant_id,
        "user_context": {"email": run.requester_email, "tenant_id": run.tenant_id},
        "assessed_risk": 4,
        "intent": "unknown",
        # Fase 16: a failing service the chat diagnosed (set by code when the
        # ticket was opened) — routed to engineering deterministically.
        "incident": run.incident,
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
        graph_input = await _initial_state(run, payload.get("image_base64"))
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


async def propose_code_fix(payload: dict, deps: WorkerDeps) -> None:
    """
    Fase 16: a draft PR with one small fix for the failing line of a
    diagnosed incident. The model proposes, code validates
    (agents/code_fix), and github.create_fix_pull_request enforces where it
    may write. A rejected proposal is a normal outcome, not a retry.
    """
    target = await asyncio.to_thread(service.load_fix_target, payload["ticket_id"])
    if target is None:
        return
    located = [(s, loc) for s in target.incident.get("services", []) for loc in s.get("locations", [])]
    if not located:
        return
    svc, loc = located[0]
    path, line = str(loc["path"]), int(loc["line"])
    content = await get_file_content(target.repo, target.token, path)
    _, llm = get_llms()
    settings = get_settings()
    try:
        edit = await propose_fix(llm, path, content, line, list(svc.get("errors", [])),
                                 settings.code_fix_max_changed_lines)
    except RejectedFix as e:
        logger.info("No code fix proposed for ticket %s: %s", target.external_id, e)
        return
    title, body = build_fix_pull_request(target.external_id, svc.get("name", ""), path, line,
                                         list(svc.get("evidence", [])), edit.explanation, target.issue_url)
    branch = "aether/fix-" + "".join(c if c.isalnum() else "-" for c in target.external_id.lower()).strip("-")[:50]
    url = await create_fix_pull_request(target.repo, target.token, branch, path, edit.new_content,
                                        f"fix: {path.rsplit('/', 1)[-1]}:{line} (Aether {target.external_id})",
                                        title, body)
    logger.info("Proposed code fix for ticket %s: %s", target.external_id, url)
    await asyncio.to_thread(service.save_fix_pr_url, target.ticket_id, url)


HANDLERS = {
    JobKind.RUN_TICKET.value: run_ticket,
    JobKind.CREATE_GITHUB_ISSUE.value: create_github_issue,
    JobKind.PROPOSE_CODE_FIX.value: propose_code_fix,
}
DEAD_HANDLERS = {JobKind.RUN_TICKET.value: run_ticket_dead}


class NotAwaitingApproval(Exception):
    """No paused ticket with that id in the caller's tenant."""


async def resume_after_approval(checkpointer, mcp_client, tenant_id: str, external_id: str, approved: bool) -> None:
    """
    Records an admin's decision on a paused risk-3 ticket and resumes its graph.

    The thread is namespaced by the caller's own tenant, so a user can only
    ever address threads of their own company — another tenant's ticket id
    resolves to a thread that doesn't exist here. Resuming runs inline: after
    approval, execution is the frozen action (no LLM call, Fase 11.2) or an
    escalation, both fast.
    """
    app = ticket_graph(checkpointer)
    config = ticket_thread_config(tenant_id, external_id, mcp_client)

    state = await app.aget_state(config)
    # Defense in depth: even if the thread namespace were ever bypassed
    # (e.g. a future checkpointer migration), refuse cross-tenant resumption.
    if not state or not awaiting_approval(state) or state.values.get("company_id") != tenant_id:
        raise NotAwaitingApproval(external_id)

    logger.info("Resuming paused ticket %s with approval: %s", external_id, approved)
    # Record the human's decision in state *before* resuming — draft_plan's
    # outgoing edge (route_from_draft_plan) reads it to decide whether to run
    # the approved action or escalate a rejection.
    await app.aupdate_state(config, {"human_approved": approved})
    async with trace_scope(ticket_trace_id(external_id), "ticket", tenant_id):
        async for _ in app.astream(None, config=config):
            pass

    final = await app.aget_state(config)
    await asyncio.to_thread(service.apply_graph_outcome, tenant_id, external_id, final.values, awaiting_approval(final))
