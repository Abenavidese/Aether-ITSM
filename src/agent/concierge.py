"""
Fase 5 — lightweight "Concierge" chat graph.

Single node, no risk routing: tries to resolve the employee's chat message
in-turn using RAG + a safe subset of MCP tools before the caller (see
POST /api/chat in src/api/routes.py) falls back to creating a real Ticket
and running the full Supervisor -> Policy -> Execution/Draft Plan swarm.
"""
import json
import logging
import re

from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END

from .mcp_client import MCPToolClient
from .state import ConciergeResult, ConciergeState
from .structured_output import invoke_structured
from src.config import get_llms
from src.db.database import SessionLocal
from src.db.models import Company
from src.integrations.github import search_code
from src.integrations.monitoring import get_monitored_services
from src.rag.service import retrieve_context

logger = logging.getLogger(__name__)

# The Concierge answers questions and checks status — it must never dispatch
# a state-changing action (that always goes through a real Ticket + the
# Supervisor's risk classification instead). Anything not in this allow-list
# is silently ignored even if the LLM hallucinates a tool_name.
CONCIERGE_ALLOWED_TOOLS = {"query_knowledge_base", "check_service_status"}

_CODE_QUESTION_PATTERN = re.compile(
    r"\b(code|repo(sitory)?|function|c[oó]digo|repositorio|funci[oó]n|commit|pull request|\bpr\b|bug in|error de compilaci[oó]n)\b",
    re.IGNORECASE,
)


def _get_github_config(tenant_id: str) -> tuple[str, str] | None:
    """Returns (repo, decrypted_token) for the tenant, or None if not configured/decryptable."""
    from src.security.encryption import decrypt_token

    db = SessionLocal()
    try:
        company = db.query(Company).filter(Company.id == tenant_id).first()
        if not company or not company.github_token or not company.github_repo:
            return None
        token = decrypt_token(company.github_token)
        return (company.github_repo, token) if token else None
    finally:
        db.close()


async def _code_search_context(tenant_id: str, query: str) -> str:
    """Best-effort on-demand code search (Fase 6) — never blocks the turn on failure."""
    github_config = _get_github_config(tenant_id)
    if not github_config:
        return ""
    repo, token = github_config
    try:
        results = await search_code(repo, token, query)
    except Exception as e:
        logger.warning("Code search failed for tenant %s: %s", tenant_id, e)
        return ""
    if not results:
        return ""
    return "\n".join(f"- {r['path']} ({r['url']})" for r in results)


async def concierge_node(state: ConciergeState, config: RunnableConfig) -> dict:
    logger.info("Concierge handling chat turn for tenant %s", state.get("user_context", {}).get("tenant_id"))

    _, llm_super = get_llms()
    mcp_client: MCPToolClient = config["configurable"]["mcp_client"]
    tenant_id = state.get("user_context", {}).get("tenant_id")
    user_query = state["messages"][-1].content if state["messages"] else ""
    if not isinstance(user_query, str):
        user_query = json.dumps(user_query)

    policy_context = retrieve_context(tenant_id, user_query, source_type="company_policy") if tenant_id else ""
    tech_context = retrieve_context(tenant_id, user_query, source_type="technical_repo") if tenant_id else ""

    code_context = ""
    if tenant_id and _CODE_QUESTION_PATTERN.search(user_query):
        code_context = await _code_search_context(tenant_id, user_query)

    monitored_services = get_monitored_services(tenant_id) if tenant_id else []
    services_note = ""
    if monitored_services:
        services_list = "\n".join(f"- {s['name']}: {s['url']}" for s in monitored_services)
        services_note = f"\nMonitored services (use check_service_status before blaming the user):\n{services_list}\n"

    prompt = f"""
    You are Aether Concierge, the first line of IT support chat for employees.
    Try to resolve the user's request in THIS turn using the context below and,
    if useful, exactly one of the two safe tools available (query_knowledge_base
    for documented fixes, check_service_status for connectivity/outage checks).

    Company policy context:
    {policy_context or "None found."}

    Technical documentation context:
    {tech_context or "None found."}
    {f"Relevant code found in the company repository:\n{code_context}\n" if code_context else ""}
    {services_note}
    Available tools:
    {mcp_client.prompt_catalog()}

    If you cannot fully resolve this in one turn (needs a real action like
    granting access, provisioning software, or a human decision), set
    resolved=false and write response_text telling the user you're opening a
    ticket and an engineer/the agent will follow up — a Ticket will be
    created automatically right after this reply, don't ask the user to file
    one themselves.
    """
    messages = [SystemMessage(content=prompt)] + state["messages"]

    try:
        result: ConciergeResult = await invoke_structured(llm_super, ConciergeResult, messages)
    except Exception as e:
        logger.error("Concierge failed: %s", e, exc_info=True)
        fallback = "Sorry, I hit a technical error. I'm opening a ticket so a human can take a look."
        return {"messages": [AIMessage(content=fallback)], "resolved": False, "final_response": fallback}

    response_text = result.response_text
    if result.tool_name in CONCIERGE_ALLOWED_TOOLS:
        try:
            tool_output = await mcp_client.call_tool(result.tool_name, result.tool_args)
            response_text = f"{response_text}\n\n{tool_output}"
        except Exception as e:
            logger.warning("Concierge tool call '%s' failed: %s", result.tool_name, e)

    return {
        "messages": [AIMessage(content=response_text)],
        "resolved": result.resolved,
        "final_response": response_text,
    }


def get_concierge_workflow() -> StateGraph:
    workflow = StateGraph(ConciergeState)
    workflow.add_node("concierge", concierge_node)
    workflow.add_edge(START, "concierge")
    workflow.add_edge("concierge", END)
    return workflow
