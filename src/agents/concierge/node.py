"""
The Concierge chat graph (Fase 5, supervisor since Fase 16).

Tries to resolve the employee's chat message in-turn before the caller
(POST /api/chat, src/services/chat.py) falls back to creating a real Ticket
that runs through the full ticket flow.

A turn is a small LangGraph graph:

    START -> plan -> investigate -> [replan -> investigate] -> respond -> END

- plan: the deterministic floor (regex rules on the message) plus what the
  supervisor model adds from a closed menu of READ-ONLY checks (plan.py,
  supervisor.py). Parameters are validated against the tenant's config.
- investigate: the workers run the plan (workers.py), concurrently where
  independent: knowledge base, platform status/logs, code search, repo
  layout, and the files the findings point at.
- replan (at most once, within the time budget): when a failing service
  gave no code location, the supervisor may follow the lead.
- respond: the model answers from the evidence (_generate_grounded), the
  proposed safe tool runs if tool_policy allows it (_run_tool), and the
  rules no model output can override are applied (_apply_fixed_rules).

The evidence lives in a per-turn workspace, never in the checkpointed state
(only small investigation records are): it would bloat every checkpoint and
the context window of later turns. Blocking I/O runs in worker threads.
"""
import asyncio
import logging
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import cast

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from src.agents.concierge.state import ConciergeResult, ConciergeState
from src.agents.runtime.messages import latest_text, message_text
from src.core.config import get_settings
from src.integrations.monitoring import get_monitored_services
from src.integrations.platform_logs.diagnosis import DEGRADED, DOWN
from src.integrations.platform_logs.service import RAW_LOG_ROLES, diagnose_service, get_log_services
from src.llm.context_budget import build_prompt
from src.llm.factory import get_llms
from src.llm.structured_output import invoke_structured
from src.observability.tracing import record_span, traced_node
from src.prompts.concierge import build_system_prompt
from src.rag.citations import validate_citations
from src.rag.service import retrieve
from src.security.redaction import redact_code
from src.tools.mcp_client import MCPToolClient
from src.tools.tool_policy import (
    ToolCallContext,
    ToolPolicyViolation,
    allowed_tools,
    authorize,
    identity_params,
)
from src.utils.urls import normalize_url

from . import repo_access
from .plan import (
    MAX_FILES_PER_TURN,
    InvestigationRequest,
    TurnPlan,
    floor_plan,
    follow_up_candidates,
    follow_up_evidence,
    merge_follow_up,
    merge_supervisor_plan,
    needs_follow_up,
)
from .platform import _CLAIMED_SERVER_ACTION_PATTERN, _SERVER_MUTATION_PATTERN, _health_checker
from .reply import _compose_reply, _format_tool_output
from .repo_access import _code_search_context, _fetch_repo_tree, _file_contents_context
from .repo_view import _ungrounded_repo_names, _verified_listing_footer
from .supervisor import is_trivial, propose_follow_up, propose_investigations
from .turn import PLATFORM, REPO_SEARCH, TurnContext
from .workers import ConciergeSources, TurnInputs, run_first_round, run_follow_up

logger = logging.getLogger(__name__)

# The Concierge answers questions and checks status — it must never dispatch
# a state-changing action (that always goes through a real Ticket + the
# Supervisor's risk classification instead). It runs with a fixed risk
# ceiling of 0 in tool_policy: only risk-0 tools, and check_service_status
# only against the tenant's configured URLs (anything else is refused before
# a single request is made — the chat used to be an SSRF vector).
CONCIERGE_RISK_CEILING = 0

_TECHNICAL_ERROR_REPLY = "Sorry, I hit a technical error. I'm opening a ticket so a human can take a look."


# ── wiring ───────────────────────────────────────────────────────────────────

def _default_sources() -> ConciergeSources:
    """
    The real readers. Names are looked up at call time, so a test that
    patches e.g. node._fetch_repo_tree is honored.
    """
    return ConciergeSources(
        retrieve=retrieve, code_search=_code_search_context, fetch_tree=_fetch_repo_tree,
        read_files=_file_contents_context, log_services=get_log_services,
        monitored_services=get_monitored_services, diagnose=diagnose_service, health_checker=_health_checker,
        repo_connected=lambda tenant_id: repo_access._get_github_config(tenant_id) is not None,
    )


def _sources(config: RunnableConfig) -> ConciergeSources:
    return config.get("configurable", {}).get("concierge_sources") or _default_sources()


def _supervisor_llm():
    settings = get_settings()
    if not settings.concierge_supervisor_enabled:
        return None
    nano, super_ = get_llms()
    return super_ if settings.concierge_supervisor_model == "super" else nano


@dataclass
class _TurnWork:
    turn: TurnContext
    plan: TurnPlan
    inputs: TurnInputs | None
    sources: ConciergeSources
    started: float = field(default_factory=time.perf_counter)
    follow_up: list[InvestigationRequest] = field(default_factory=list)


# One chat turn runs inside one request, so its workspace lives in this
# process between the graph's nodes; the bound only matters if turns crash
# mid-graph and never reach respond (which removes their entry).
_WORKSPACES: "OrderedDict[str, _TurnWork]" = OrderedDict()
_MAX_WORKSPACES = 512


def _keep(work: _TurnWork) -> str:
    turn_id = uuid.uuid4().hex
    _WORKSPACES[turn_id] = work
    while len(_WORKSPACES) > _MAX_WORKSPACES:
        _WORKSPACES.popitem(last=False)
    return turn_id


def _work(state: ConciergeState) -> _TurnWork:
    work = _WORKSPACES.get(state.get("turn_id") or "")
    if work is None:
        raise RuntimeError("Concierge turn workspace missing — the turn must start at the plan node")
    return work


async def _best_effort(lookup, tenant_id: str, default):
    """What the tenant has configured — a failed lookup means "nothing to choose from", never a failed turn."""
    try:
        return await asyncio.to_thread(lookup, tenant_id)
    except Exception as e:
        logger.warning("Concierge could not read the tenant's configuration (%s): %s", getattr(lookup, "__name__", lookup), e)
        return default


# ── nodes ────────────────────────────────────────────────────────────────────

async def plan_node(state: ConciergeState, config: RunnableConfig) -> dict:
    user_context = state.get("user_context", {})
    tenant_id = user_context.get("tenant_id")
    messages = state["messages"]
    user_query = latest_text(messages)
    # A short follow-up like "and in middleware?" carries no trigger word of
    # its own — it only makes sense after a prior "list the files in X"
    # message. Checking the last couple of messages for the *trigger* catches
    # that, while keyword extraction still runs on the current message alone.
    recent_text = " ".join(message_text(m) for m in messages[-3:])
    # Only the USER's words can ask for a listing: the listing footer this
    # graph appends ("📂 Contenido real...") contains a trigger word itself, so
    # counting assistant turns re-listed a folder on every later message.
    recent_user_text = " ".join(message_text(m) for m in messages[-3:] if isinstance(m, HumanMessage))
    turn = TurnContext(user_query=user_query, recent_text=recent_text)
    src = _sources(config)
    if not tenant_id:
        return {"turn_id": _keep(_TurnWork(turn, TurnPlan(), None, src)), "investigation_round": 1,
                "investigations": []}

    user_messages = [message_text(m) for m in messages if isinstance(m, HumanMessage)]
    inputs = TurnInputs(tenant_id=tenant_id, user_id=user_context.get("user_id"), role=user_context.get("role"),
                        history=user_messages[:-1][-3:], mcp_client=config["configurable"]["mcp_client"])
    log_services, repo_connected = await asyncio.gather(_best_effort(src.log_services, tenant_id, []),
                                                        _best_effort(src.repo_connected, tenant_id, False))
    plan = floor_plan(user_query, recent_text, recent_user_text, log_services)

    # The supervisor only runs when there is something to choose from, and
    # never for small talk (Fase 16.8): those turns cost what they did before.
    if (log_services or repo_connected) and not is_trivial(user_query):
        proposal = await propose_investigations(_supervisor_llm(), user_messages[-3:],
                                                [s.name for s in log_services], repo_connected)
        if proposal is not None:
            merge_supervisor_plan(plan, proposal, log_services, repo_connected)
            plan.reason = proposal.reason[:200]
    logger.info("Concierge plan: %s", [(r.kind, r.target[:40], r.trigger) for r in plan.requests])
    return {"turn_id": _keep(_TurnWork(turn, plan, inputs, src)), "investigation_round": 1, "investigations": []}


async def investigate_node(state: ConciergeState, config: RunnableConfig) -> dict:
    work = _work(state)
    if work.inputs is not None:
        if (state.get("investigation_round") or 1) == 1:
            await run_first_round(work.turn, work.plan, work.sources, work.inputs)
        else:
            await run_follow_up(work.turn, work.follow_up, work.sources, work.inputs)
    return {"investigations": [i.to_dict() for i in work.turn.investigations]}


def route_after_investigation(state: ConciergeState) -> str:
    """A second round only to follow a real lead, within the rounds and time budget."""
    settings = get_settings()
    work = _WORKSPACES.get(state.get("turn_id") or "")
    if (work is None or work.inputs is None or (state.get("investigation_round") or 1) >= settings.concierge_max_rounds
            or not settings.concierge_supervisor_enabled):
        return "respond"
    if time.perf_counter() - work.started > settings.concierge_investigation_budget_seconds:
        logger.info("Concierge investigation budget spent — answering with round 1")
        return "respond"
    return "replan" if needs_follow_up(work.turn) else "respond"


async def replan_node(state: ConciergeState, config: RunnableConfig) -> dict:
    work = _work(state)
    candidates = follow_up_candidates(work.turn)
    searched = sum(1 for i in work.turn.investigations if i.kind == REPO_SEARCH)
    proposal = await propose_follow_up(_supervisor_llm(), follow_up_evidence(work.turn), candidates,
                                       can_search=searched < 2)
    follow = TurnPlan()
    if proposal is not None:
        merge_follow_up(follow, proposal, candidates, can_search=searched < 2,
                        files_left=MAX_FILES_PER_TURN - len(work.turn.files_read))
    work.follow_up = follow.requests
    return {"investigation_round": 2}


def route_after_replan(state: ConciergeState) -> str:
    work = _WORKSPACES.get(state.get("turn_id") or "")
    return "investigate" if work is not None and work.follow_up else "respond"


async def respond_node(state: ConciergeState, config: RunnableConfig) -> dict:
    work = _WORKSPACES.pop(state.get("turn_id") or "", None)
    if work is None:
        raise RuntimeError("Concierge turn workspace missing — the turn must start at the plan node")
    return await _respond(state, config, work.turn)


# ── respond ──────────────────────────────────────────────────────────────────

_INCIDENT_STATUSES = (DOWN, DEGRADED)


def _checked_line(turn: TurnContext) -> str:
    """
    Fase 16.7: what was checked, in plain words, built by code from the
    investigations that actually ran — a non-technical user learns the
    assistant looked, without stack traces (raw lines stay admin-only).
    """
    services = list(dict.fromkeys(i.target for i in turn.investigations if i.kind == PLATFORM and i.ok))
    if not services:
        return ""
    parts = [f"el estado y los registros recientes de {', '.join(services)}"]
    files = [f.rsplit("/", 1)[-1] for f in turn.files_read]
    if files:
        parts.append(f"el código relacionado ({', '.join(dict.fromkeys(files))})")
    return "🔍 Revisé " + " y ".join(parts) + "."


def incident_of(turn: TurnContext) -> dict | None:
    """
    A failing service found this turn, as structured data for the ticket —
    set by code from the diagnosis, never parsed back out of user-visible
    text (a user could type a fake "diagnosis" into their message).
    """
    failing = [d for d in turn.diagnoses if d.verdict.status in _INCIDENT_STATUSES]
    if not failing:
        return None
    return {"services": [{
        "name": d.service.name,
        "status": d.verdict.status,
        "evidence": d.verdict.evidence[:5],
        "locations": [{"path": loc.repo_path, "line": loc.line} for loc in d.locations],
        # Redacted, deduplicated error lines — kept inside Aether (they feed a
        # fix proposal), never written into a GitHub issue or pull request.
        "errors": [line[:400] for line in d.log_lines if "ERROR" in line][:3],
    } for d in failing]}


def _tool_context(user_context: dict, turn: TurnContext) -> ToolCallContext:
    return ToolCallContext(
        requester=user_context.get("email"),
        assessed_risk=CONCIERGE_RISK_CEILING,
        allowed_service_urls=frozenset(normalize_url(s["url"]) for s in turn.monitored_services),
    )


async def _generate_grounded(llm, messages: list, turn: TurnContext, user_text: str) -> ConciergeResult:
    """
    Model answer whose repo names are all real. The prompt already forbids
    inventing files, but a local 8B model still did, so this is enforced in
    code: one corrective retry, then a deterministic answer from real data.
    Raises only if the first model call fails.
    """
    result: ConciergeResult = await invoke_structured(llm, ConciergeResult, messages)
    grounding = turn.grounding_text(user_text)
    ungrounded = _ungrounded_repo_names(_compose_reply(result), turn.repo_tree, grounding)
    if not ungrounded:
        return result

    logger.warning("Concierge response named non-existent repo items %s — retrying once", sorted(ungrounded))
    correction = (
        f"Your previous answer mentioned {', '.join(sorted(ungrounded))}, which do NOT exist in the "
        "repository data you were given. Answer again using ONLY names that literally appear in the "
        "context sections. If what the user asked for doesn't exist, say so and list what does exist."
    )
    try:
        result = await invoke_structured(
            llm, ConciergeResult,
            messages + [AIMessage(content=_compose_reply(result)), HumanMessage(content=correction)],
        )
        ungrounded = _ungrounded_repo_names(_compose_reply(result), turn.repo_tree, grounding)
    except Exception as e:
        logger.warning("Concierge grounding retry failed: %s", e)
    if not ungrounded:
        return result

    # Still inventing: answer with the verified data itself instead of
    # passing a fabrication on to the user.
    logger.warning("Concierge still ungrounded after retry %s — using deterministic answer", sorted(ungrounded))
    verified = turn.directory_context or turn.code_context
    text = (
        f"No pude generar una respuesta verificada. Estos son los datos reales del repositorio:\n\n{verified}"
        if verified else
        "No tengo datos verificados sobre esos archivos del repositorio."
    )
    return ConciergeResult(response_text=text, resolved=True)


async def _run_tool(result: ConciergeResult, tool_ctx: ToolCallContext, mcp_client: MCPToolClient,
                    turn: TurnContext | None = None) -> str:
    """The tool the model proposed, only if tool_policy allows it; "" otherwise."""
    if not result.tool_name:
        return ""
    if result.tool_name == "check_service_status" and turn is not None and turn.diagnoses:
        # The diagnosis already ran this healthcheck; a second one only shows
        # the user a raw URL (seen in the Fase 16 live test).
        return ""
    try:
        call = authorize(result.tool_name, result.tool_args, tool_ctx)
        return _format_tool_output(call.name, await mcp_client.call_tool(call.name, call.args))
    except ToolPolicyViolation as e:
        logger.warning("Concierge tool call refused: %s", e)
    except Exception as e:
        logger.warning("Concierge tool call '%s' failed: %s", result.tool_name, e)
    return ""


def _apply_fixed_rules(response_text: str, resolved: bool, turn: TurnContext,
                       can_configure: bool = False) -> tuple[str, bool]:
    """
    Deterministic, whatever the model wrote: no secret reaches the screen,
    the service verdict is stated by code, a failing (DOWN or DEGRADED)
    service always becomes a ticket for engineering — the user can't fix the
    company's app and must not be told to — and a request to change a server
    always gets the read-only answer (and goes to humans as a ticket).
    """
    response_text = redact_code(response_text)
    if _CLAIMED_SERVER_ACTION_PATTERN.search(response_text):
        logger.warning("Concierge claimed a server action it cannot perform — discarding its reply")
        response_text = "No realicé ninguna acción sobre los servidores."
    if turn.diagnoses:
        checked = _checked_line(turn)
        response_text += "\n\n" + (f"{checked}\n" if checked else "") + "\n".join(
            d.verdict_line() for d in turn.diagnoses)
        if any(d.verdict.status in _INCIDENT_STATUSES for d in turn.diagnoses):
            resolved = False
            response_text += ("\n\n🛠️ Es un fallo de la aplicación, no de tu equipo ni de tu cuenta: no necesitas "
                              "hacer nada más. Lo paso al equipo de ingeniería con este diagnóstico.")
    elif turn.outage_without_services and can_configure:
        # Admins only: they can fix it, and the outage pattern is broad
        # ("my vpn is down") — an employee would just see noise.
        response_text += ("\n\nℹ️ No hay servicios monitoreados con acceso a logs configurados, así que no pude "
                          "revisar el estado ni los logs del servidor. Un administrador puede añadirlos en "
                          "Integraciones.")
    if _SERVER_MUTATION_PATTERN.search(turn.user_query):
        response_text += ("\n\n🔒 No puedo reiniciar, redesplegar ni modificar servidores: mi acceso es de "
                          "solo lectura (estado y logs). Lo derivo al equipo de ingeniería con un ticket.")
        resolved = False
    return response_text, resolved


async def _respond(state: ConciergeState, config: RunnableConfig, turn: TurnContext) -> dict:
    user_context = state.get("user_context", {})
    _, llm_super = get_llms()
    mcp_client: MCPToolClient = config["configurable"]["mcp_client"]
    tool_ctx = _tool_context(user_context, turn)
    investigations = [i.to_dict() for i in turn.investigations]

    catalog = mcp_client.prompt_catalog(only=allowed_tools(tool_ctx), hidden_params=identity_params())
    # The chat thread only grows; build_prompt keeps it inside the context
    # window so the system prompt is never the part that gets cut.
    messages = build_prompt(build_system_prompt(turn, catalog), state["messages"])

    user_text = " ".join(message_text(m) for m in state["messages"] if isinstance(m, HumanMessage))
    try:
        result = await _generate_grounded(llm_super, messages, turn, user_text)
    except Exception as e:
        logger.error("Concierge failed: %s", e, exc_info=True)
        return {"messages": [AIMessage(content=_TECHNICAL_ERROR_REPLY)], "resolved": False,
                "final_response": _TECHNICAL_ERROR_REPLY, "investigations": investigations,
                "diagnosis_report": "\n\n".join(d.for_ticket() for d in turn.diagnoses) or None,
                "incident": incident_of(turn)}

    response_text = _compose_reply(result)
    if turn.repo_view.listed_dirs:
        footer = _verified_listing_footer(turn.repo_tree, turn.repo_view.listed_dirs, response_text)
        if footer:
            response_text = f"{response_text}\n\n{footer}"
    tool_text = await _run_tool(result, tool_ctx, mcp_client, turn)
    if tool_text:
        response_text = f"{response_text}\n\n{tool_text}"

    response_text, resolved = _apply_fixed_rules(response_text, result.resolved, turn,
                                                 can_configure=user_context.get("role") in RAW_LOG_ROLES)
    passages = turn.knowledge.passages if turn.knowledge else []
    citations = validate_citations(response_text, passages, declared=result.cited_passages, question=turn.user_query)
    if citations.removed:
        logger.warning("Concierge cited non-existent passages %s — removed", citations.removed)
    record_span("citations", "concierge", 0, datetime.now(timezone.utc), attributes=citations.stats(len(passages)))
    return {
        "messages": [AIMessage(content=citations.text)],
        "resolved": resolved,
        "final_response": citations.text,
        "diagnosis_report": "\n\n".join(d.for_ticket() for d in turn.diagnoses) or None,
        "incident": incident_of(turn),
        "sources": citations.sources,
        "investigations": investigations,
    }


async def concierge_node(state: ConciergeState, config: RunnableConfig) -> dict:
    """
    One whole turn in-process (plan -> investigate -> [replan -> investigate]
    -> respond), returning respond's update — the same nodes the graph runs,
    for callers that want a single step.
    """
    current = cast(ConciergeState, dict(state))
    current.update(await plan_node(current, config))  # type: ignore[typeddict-item]
    current.update(await investigate_node(current, config))  # type: ignore[typeddict-item]
    if route_after_investigation(current) == "replan":
        current.update(await replan_node(current, config))  # type: ignore[typeddict-item]
        if route_after_replan(current) == "investigate":
            current.update(await investigate_node(current, config))  # type: ignore[typeddict-item]
    return await respond_node(current, config)


def get_concierge_workflow() -> StateGraph:
    workflow = StateGraph(ConciergeState)
    workflow.add_node("plan", traced_node("concierge.plan", plan_node))
    workflow.add_node("investigate", traced_node("concierge.investigate", investigate_node))
    workflow.add_node("replan", traced_node("concierge.replan", replan_node))
    workflow.add_node("respond", traced_node("concierge.respond", respond_node))
    workflow.add_edge(START, "plan")
    workflow.add_edge("plan", "investigate")
    workflow.add_conditional_edges("investigate", route_after_investigation,
                                   {"replan": "replan", "respond": "respond"})
    workflow.add_conditional_edges("replan", route_after_replan, {"investigate": "investigate", "respond": "respond"})
    workflow.add_edge("respond", END)
    return workflow
