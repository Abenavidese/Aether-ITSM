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
from src.integrations.github import get_repo_tree, search_code
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

# Distinct from _CODE_QUESTION_PATTERN: "search code content" vs "enumerate a
# folder" are different GitHub API calls (search_code vs get_repo_tree) and
# need different trigger words — "list the files in X" rarely says "code".
_DIRECTORY_QUESTION_PATTERN = re.compile(
    r"\b(list(a(me)?)?|archivos|files|folder|carpeta|directorio|directory|estructura|structure)\b",
    re.IGNORECASE,
)

_STOPWORDS = {
    "el", "la", "los", "las", "en", "de", "que", "hay", "todos", "todas", "un", "una",
    "list", "lista", "listame", "archivos", "files", "todo", "the", "and", "for",
    "project", "proyecto", "backend", "frontend", "source", "src", "carpeta",
    "folder", "directorio", "directory", "estructura", "structure", "hola", "por",
}


def _extract_keywords(text: str) -> set[str]:
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text.lower())
    return {w for w in words if w not in _STOPWORDS}


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


async def _directory_listing_context(tenant_id: str, query: str) -> str:
    """
    Best-effort directory listing (see get_repo_tree's docstring for why
    this is a separate capability from code search) — never blocks the turn
    on failure.
    """
    github_config = _get_github_config(tenant_id)
    if not github_config:
        return ""
    repo, token = github_config
    try:
        tree = await get_repo_tree(repo, token)
    except Exception as e:
        logger.warning("Repo tree fetch failed for tenant %s: %s", tenant_id, e)
        return ""

    keywords = _extract_keywords(query)
    dir_basenames = {e["path"].rsplit("/", 1)[-1].lower(): e["path"] for e in tree if e["type"] == "dir"}

    matched_dir = next((dir_basenames[k] for k in keywords if k in dir_basenames), None)
    if not matched_dir:
        # Typo tolerance ("ontrollers", "controlers") — a real user typing
        # from memory into a chat box will misspell a folder name, and
        # falling back to "nothing matched" every time that happens is
        # unhelpful even though it's honest. difflib needs no extra
        # dependency and is good enough for short identifier-like names.
        import difflib
        best_score, best_dir = 0.0, None
        for keyword in keywords:
            for basename, full_path in dir_basenames.items():
                if keyword in basename or basename in keyword:
                    # A direct substring hit (e.g. "ontrollers" missing the
                    # leading 'c' of "controllers") is a stronger, more
                    # specific signal than two same-length words that merely
                    # look alike (e.g. "backjend" vs "backend") — score it
                    # above any plausible SequenceMatcher ratio between two
                    # genuinely different short words.
                    score = 0.97
                else:
                    score = difflib.SequenceMatcher(None, keyword, basename).ratio()
                if score > best_score:
                    best_score, best_dir = score, full_path
        if best_score >= 0.75:
            matched_dir = best_dir

    if matched_dir:
        children = sorted(
            e["path"].rsplit("/", 1)[-1]
            for e in tree
            if e["path"].rsplit("/", 1)[0] == matched_dir and e["path"] != matched_dir
        )
        if children:
            return f"Real contents of '{matched_dir}/' (from GitHub, just fetched):\n" + "\n".join(f"- {c}" for c in children)

    # No specific folder matched the message's keywords — surface the real
    # top-level layout instead of nothing, so the model has *something* true
    # to answer with rather than a reason to guess.
    top_level = sorted({e["path"].split("/")[0] for e in tree})
    return "Couldn't match a specific folder name from the message. Real top-level contents of the repo:\n" + "\n".join(
        f"- {t}" for t in top_level
    )


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

    # A short follow-up like "and in middleware?" carries no trigger word of
    # its own — it only makes sense after a prior "list the files in X"
    # message. Checking the last couple of messages (not just this one) for
    # the *trigger* catches that, while keyword extraction still runs on the
    # current message alone (it already contains "middleware").
    recent_text = " ".join(
        str(m.content) for m in state["messages"][-3:] if isinstance(getattr(m, "content", None), str)
    )

    code_context = ""
    if tenant_id and _CODE_QUESTION_PATTERN.search(user_query):
        code_context = await _code_search_context(tenant_id, user_query)

    directory_context = ""
    if tenant_id and _DIRECTORY_QUESTION_PATTERN.search(recent_text):
        directory_context = await _directory_listing_context(tenant_id, user_query)

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

    CRITICAL — never fabricate: only state facts that literally appear in a
    context section below or in a tool's actual output. You have NO general
    ability to "review the whole codebase for bugs" and NO memory of this
    repository beyond what's printed here. If a context section says "None
    found" or is missing for what the user asked (specific files, code
    content, whether something has errors), say plainly that you don't have
    that information / couldn't find it — do NOT invent file names, code, or
    a review verdict that isn't grounded in real data below.

    Company policy context:
    {policy_context or "None found."}

    Technical documentation context:
    {tech_context or "None found."}
    {f"Relevant code found in the company repository:\n{code_context}\n" if code_context else ""}
    {f"Repository directory listing:\n{directory_context}\n" if directory_context else ""}
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
