"""
Fase 5 — lightweight "Concierge" chat graph.

Single node, no risk routing: tries to resolve the employee's chat message
in-turn using RAG + a safe subset of MCP tools before the caller (see
POST /api/chat in src/api/routes.py) falls back to creating a real Ticket
and running the full Supervisor -> Policy -> Execution/Draft Plan swarm.

A turn is four steps: gather context (_gather_context) -> ask the model
(_generate_grounded, with the grounding check) -> run the tool it proposed,
if tool_policy allows it (_run_tool) -> apply the deterministic rules that
no model output can override (_apply_fixed_rules).

Blocking I/O (DB lookups, embeddings + pgvector) runs in worker threads
(asyncio.to_thread) so one slow turn never stalls the event loop for every
other request (roadmap 2.1).
"""
import asyncio
import json
import logging

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from src.agent.context_budget import build_prompt
from src.agent.mcp_client import MCPToolClient
from src.agent.state import ConciergeResult, ConciergeState
from src.agent.structured_output import invoke_structured
from src.agent.tool_policy import (
    ToolCallContext, ToolPolicyViolation, allowed_tools, authorize, identity_params, normalize_url,
)
from src.config import get_llms
from src.integrations.logs.diagnosis import DOWN
from src.integrations.logs.service import RAW_LOG_ROLES, diagnose_service, get_log_services
from src.integrations.monitoring import get_monitored_services
from src.observability.tracing import traced_node
from src.rag.service import retrieve_context
from src.security.redaction import redact_code

from .platform import (
    _CLAIMED_SERVER_ACTION_PATTERN, _OUTAGE_PATTERN, _SERVER_MUTATION_PATTERN, _health_checker, _pick_services,
)
from .prompt import build_system_prompt
from .reply import _compose_reply, _format_tool_output
from .repo_access import _code_search_context, _fetch_repo_tree, _file_contents_context
from .repo_view import (
    _CODE_QUESTION_PATTERN, _DIRECTORY_QUESTION_PATTERN, _FILENAME_PATTERN, _REVIEW_PATTERN, _children,
    _describe_directory, _extract_paths, _ungrounded_repo_names, _verified_listing_footer,
)
from .turn import TurnContext

logger = logging.getLogger(__name__)

# The Concierge answers questions and checks status — it must never dispatch
# a state-changing action (that always goes through a real Ticket + the
# Supervisor's risk classification instead). It runs with a fixed risk
# ceiling of 0 in tool_policy: only risk-0 tools, and check_service_status
# only against the tenant's configured URLs (anything else is refused before
# a single request is made — the chat used to be an SSRF vector).
CONCIERGE_RISK_CEILING = 0

_TECHNICAL_ERROR_REPLY = "Sorry, I hit a technical error. I'm opening a ticket so a human can take a look."


async def _gather_context(state: ConciergeState, mcp_client: MCPToolClient) -> TurnContext:
    user_context = state.get("user_context", {})
    tenant_id = user_context.get("tenant_id")
    user_query = state["messages"][-1].content if state["messages"] else ""
    if not isinstance(user_query, str):
        user_query = json.dumps(user_query)

    # A short follow-up like "and in middleware?" carries no trigger word of
    # its own — it only makes sense after a prior "list the files in X"
    # message. Checking the last couple of messages (not just this one) for
    # the *trigger* catches that, while keyword extraction still runs on the
    # current message alone (it already contains "middleware").
    recent_text = " ".join(
        str(m.content) for m in state["messages"][-3:] if isinstance(getattr(m, "content", None), str)
    )
    turn = TurnContext(user_query=user_query, recent_text=recent_text)
    if not tenant_id:
        return turn

    turn.policy_context, turn.tech_context = await asyncio.gather(
        asyncio.to_thread(retrieve_context, tenant_id, user_query, source_type="company_policy"),
        asyncio.to_thread(retrieve_context, tenant_id, user_query, source_type="technical_repo"),
    )

    wants_code = bool(_CODE_QUESTION_PATTERN.search(user_query))
    wants_directory = bool(_DIRECTORY_QUESTION_PATTERN.search(recent_text) or _extract_paths(user_query))
    wants_files = bool(_FILENAME_PATTERN.search(user_query.replace("\\", "/")))

    if wants_code:
        turn.code_context = await _code_search_context(tenant_id, user_query)

    # A repo question whose code search came back empty ("revisa el repo y
    # dime qué hay") still gets the real repo layout, so the model answers
    # from real data instead of a bare "no information found".
    if wants_directory or wants_files or (wants_code and not turn.code_context):
        turn.repo_tree = await _fetch_repo_tree(tenant_id)
        if turn.repo_tree:
            turn.repo_view = _describe_directory(turn.repo_tree, user_query)
    turn.directory_context = turn.repo_view.context

    # Fase 10.6: an outage/error report (or an explicit "check the logs")
    # triggers a READ-ONLY look at the hosting platform: deterministic
    # verdict + redacted recent errors + the file:line they point to.
    if _OUTAGE_PATTERN.search(user_query):
        targets = _pick_services(await asyncio.to_thread(get_log_services, tenant_id), recent_text)
        if targets:
            if not turn.repo_tree:
                turn.repo_tree = await _fetch_repo_tree(tenant_id)
            health_check = _health_checker(mcp_client)
            for ref in targets:
                turn.diagnoses.append(await diagnose_service(
                    tenant_id, user_context.get("user_id"), ref, health_check, turn.repo_tree,
                ))
    include_raw_logs = user_context.get("role") in RAW_LOG_ROLES
    turn.diagnosis_context = "\n\n".join(d.for_prompt(include_raw_logs) for d in turn.diagnoses)

    # Names alone can't diagnose anything — read the actual code when the
    # user names a file, asks to review/explain a folder's contents, or a
    # stack trace in the logs points at it.
    files_to_read = [loc.repo_path for d in turn.diagnoses for loc in d.locations] + list(turn.repo_view.files)
    if _REVIEW_PATTERN.search(user_query) and not turn.repo_view.fallback:
        for d in turn.repo_view.listed_dirs:
            if d:  # never "read the whole repo root"
                files_to_read += [f"{d}/{c}" for c in _children(turn.repo_tree, d) if not c.endswith("/")]
    turn.file_context = await _file_contents_context(tenant_id, list(dict.fromkeys(files_to_read)))

    turn.monitored_services = await asyncio.to_thread(get_monitored_services, tenant_id)
    return turn


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


async def _run_tool(result: ConciergeResult, tool_ctx: ToolCallContext, mcp_client: MCPToolClient) -> str:
    """The tool the model proposed, only if tool_policy allows it; "" otherwise."""
    if not result.tool_name:
        return ""
    try:
        call = authorize(result.tool_name, result.tool_args, tool_ctx)
        return _format_tool_output(call.name, await mcp_client.call_tool(call.name, call.args))
    except ToolPolicyViolation as e:
        logger.warning("Concierge tool call refused: %s", e)
    except Exception as e:
        logger.warning("Concierge tool call '%s' failed: %s", result.tool_name, e)
    return ""


def _apply_fixed_rules(response_text: str, resolved: bool, turn: TurnContext) -> tuple[str, bool]:
    """
    Deterministic, whatever the model wrote: no secret reaches the screen,
    the service verdict is stated by code, a DOWN service always becomes a
    ticket, and a request to change a server always gets the read-only
    answer (and goes to humans as a ticket).
    """
    response_text = redact_code(response_text)
    if _CLAIMED_SERVER_ACTION_PATTERN.search(response_text):
        logger.warning("Concierge claimed a server action it cannot perform — discarding its reply")
        response_text = "No realicé ninguna acción sobre los servidores."
    if turn.diagnoses:
        response_text += "\n\n" + "\n".join(d.verdict_line() for d in turn.diagnoses)
        if any(d.verdict.status == DOWN for d in turn.diagnoses):
            resolved = False
    if _SERVER_MUTATION_PATTERN.search(turn.user_query):
        response_text += ("\n\n🔒 No puedo reiniciar, redesplegar ni modificar servidores: mi acceso es de "
                          "solo lectura (estado y logs). Lo derivo al equipo de ingeniería con un ticket.")
        resolved = False
    return response_text, resolved


async def concierge_node(state: ConciergeState, config: RunnableConfig) -> dict:
    user_context = state.get("user_context", {})
    logger.info("Concierge handling chat turn for tenant %s", user_context.get("tenant_id"))

    _, llm_super = get_llms()
    mcp_client: MCPToolClient = config["configurable"]["mcp_client"]
    turn = await _gather_context(state, mcp_client)
    tool_ctx = _tool_context(user_context, turn)

    catalog = mcp_client.prompt_catalog(only=allowed_tools(tool_ctx), hidden_params=identity_params())
    # The chat thread only grows; build_prompt keeps it inside the context
    # window so the system prompt is never the part that gets cut.
    messages = build_prompt(build_system_prompt(turn, catalog), state["messages"])

    user_text = " ".join(
        str(m.content) for m in state["messages"] if isinstance(m, HumanMessage) and isinstance(m.content, str)
    )
    try:
        result = await _generate_grounded(llm_super, messages, turn, user_text)
    except Exception as e:
        logger.error("Concierge failed: %s", e, exc_info=True)
        return {"messages": [AIMessage(content=_TECHNICAL_ERROR_REPLY)], "resolved": False,
                "final_response": _TECHNICAL_ERROR_REPLY}

    response_text = _compose_reply(result)
    if turn.repo_view.listed_dirs:
        footer = _verified_listing_footer(turn.repo_tree, turn.repo_view.listed_dirs, response_text)
        if footer:
            response_text = f"{response_text}\n\n{footer}"
    tool_text = await _run_tool(result, tool_ctx, mcp_client)
    if tool_text:
        response_text = f"{response_text}\n\n{tool_text}"

    response_text, resolved = _apply_fixed_rules(response_text, result.resolved, turn)
    return {
        "messages": [AIMessage(content=response_text)],
        "resolved": resolved,
        "final_response": response_text,
        "diagnosis_report": "\n\n".join(d.for_ticket() for d in turn.diagnoses) or None,
    }


def get_concierge_workflow() -> StateGraph:
    workflow = StateGraph(ConciergeState)
    workflow.add_node("concierge", traced_node("concierge", concierge_node))
    workflow.add_edge(START, "concierge")
    workflow.add_edge("concierge", END)
    return workflow
