"""
Fase 5 — lightweight "Concierge" chat graph.

Single node, no risk routing: tries to resolve the employee's chat message
in-turn using RAG + a safe subset of MCP tools before the caller (see
POST /api/chat in src/api/routes.py) falls back to creating a real Ticket
and running the full Supervisor -> Policy -> Execution/Draft Plan swarm.
"""
import difflib
from dataclasses import dataclass, field
import json
import logging
import re

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END

from .mcp_client import MCPToolClient
from .state import ConciergeResult, ConciergeState
from .structured_output import invoke_structured
from src.config import get_llms
from src.db.database import SessionLocal
from src.db.models import Company
from src.integrations.github import get_file_content, get_repo_tree, search_code
from src.integrations.logs.base import ServiceRef
from src.integrations.logs.diagnosis import DOWN
from src.integrations.logs.service import RAW_LOG_ROLES, ServiceDiagnosis, diagnose_service, get_log_services
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
    r"\b(list(a(me)?)?|archivos|files|folder|carpeta|directorio|directory|estructura|structure"
    r"|contenido|contents|hay en|inside|dentro de)\b",
    re.IGNORECASE,
)

# An explicit path ("/src/agents", "backend/src/", "src/agent") is the most
# precise thing a user can give us — and one the keyword heuristic alone used
# to throw away ("src" is a stopword), so "qué hay en /src/agents" never even
# fetched the tree and the model answered with no data at all.
_PATH_PATTERN = re.compile(r"(?<![\w.:/])/?([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+|(?<=/)[A-Za-z0-9_.-]+)/?")

_STOPWORDS = {
    "el", "la", "los", "las", "en", "de", "que", "hay", "todos", "todas", "un", "una",
    "list", "lista", "listame", "archivos", "files", "todo", "the", "and", "for",
    "project", "proyecto", "backend", "frontend", "source", "src", "carpeta",
    "folder", "directorio", "directory", "estructura", "structure", "hola", "por",
    # Chat filler that used to leak into folder matching — "repo" substring-
    # matched "repositories/" and the Concierge confidently listed the wrong
    # folder.
    "repo", "repositorio", "repository", "revisa", "dime", "muestra", "muestrame",
    "show", "what", "whats", "inside", "dentro", "contenido", "contents", "code", "codigo",
}


def _extract_keywords(text: str) -> set[str]:
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text.lower())
    return {w for w in words if w not in _STOPWORDS}


def _extract_paths(text: str) -> list[str]:
    # Windows-style "\src\agent" is the same request as "/src/agent" — a user
    # copying a path from their own machine types backslashes.
    text = text.replace("\\", "/")
    # rstrip("."): a path ending a sentence ("no existe /src/agent.") must not
    # carry the period.
    paths = (m.rstrip(".").strip("/") for m in _PATH_PATTERN.findall(text))
    return [p for p in paths if p]


# File names the model might state as facts ("agent.service.js"). Limited to
# code/config extensions so prose like "S.A.S." or "e.g." isn't checked.
_FILENAME_PATTERN = re.compile(
    r"\b[\w-]+(?:\.[\w-]+)*\.(?:js|jsx|ts|tsx|py|java|go|rb|php|cs|json|ya?ml|md|txt|sql|sh|css|html|toml|ini|env)\b",
    re.IGNORECASE,
)


def _ungrounded_repo_names(response: str, tree: list[dict], grounding_text: str) -> set[str]:
    """
    File names / paths the response states that exist neither in the real
    repo tree nor in the text the model was given (context + the user's own
    messages — so "there is no /src/agent" when the user asked about it is
    fine). The prompt already forbids inventing these, but a local 8B model
    still did ("backend/src/agents contains agent.service.js ..." for a folder
    that doesn't exist), so this is enforced in code, not left to the prompt.
    """
    known = {e["path"].lower() for e in tree} | {e["path"].rsplit("/", 1)[-1].lower() for e in tree}
    grounding = grounding_text.lower().replace("\\", "/")

    def grounded(name: str) -> bool:
        name = name.lower().strip("/")
        return (
            name in known
            or any(k.endswith("/" + name) for k in known)
            or name in grounding
        )

    candidates = set(_FILENAME_PATTERN.findall(response)) | set(_extract_paths(response))
    return {c for c in candidates if not grounded(c)}


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


async def _fetch_repo_tree(tenant_id: str) -> list[dict]:
    """
    Best-effort repo tree (see get_repo_tree's docstring for why this is a
    separate capability from code search) — never blocks the turn on
    failure; an empty list means "no repo data available".
    """
    github_config = _get_github_config(tenant_id)
    if not github_config:
        return []
    repo, token = github_config
    try:
        return await get_repo_tree(repo, token)
    except Exception as e:
        logger.warning("Repo tree fetch failed for tenant %s: %s", tenant_id, e)
        return []


def _children(tree: list[dict], dir_path: str) -> list[str]:
    return sorted(
        e["path"].rsplit("/", 1)[-1] + ("/" if e["type"] == "dir" else "")
        for e in tree
        if "/" in e["path"] and e["path"].rsplit("/", 1)[0] == dir_path
    )


def _format_listing(tree: list[dict], dir_path: str) -> str:
    children = _children(tree, dir_path)
    body = "\n".join(f"- {c}" for c in children) if children else "(empty)"
    return f"Real contents of '{dir_path}/' (from GitHub, just fetched):\n{body}"


def _top_level_listing(tree: list[dict]) -> str:
    top_level = sorted({e["path"].split("/")[0] for e in tree})
    return "Real top-level contents of the repo:\n" + "\n".join(f"- {t}" for t in top_level)


def _resolve_path(dirs: set[str], path: str) -> list[str]:
    """Dirs equal to `path` or ending in '/<path>' — users rarely type the
    full path from the repo root ("src/agents" for "backend/src/agents")."""
    target = path.lower()
    return sorted((d for d in dirs if d.lower() == target or d.lower().endswith("/" + target)), key=len)


@dataclass
class RepoView:
    """What the user's message resolved to in the real repo tree."""
    context: str = ""                                    # grounded text for the prompt
    listed_dirs: list[str] = field(default_factory=list)  # dirs whose contents were shown ("" = repo root)
    files: list[str] = field(default_factory=list)        # file paths worth reading
    # listed_dirs are only nearby alternatives (the requested path doesn't
    # exist) — show them, but never read their files as if they were asked for.
    fallback: bool = False


def _resolve_files(tree: list[dict], name: str) -> list[str]:
    target = name.lower().strip("/")
    return sorted(
        (e["path"] for e in tree if e["type"] == "file"
         and (e["path"].lower() == target or e["path"].lower().endswith("/" + target))),
        key=len,
    )


def _describe_explicit_path(tree: list[dict], dirs: set[str], path: str) -> RepoView:
    matches = _resolve_path(dirs, path)
    if matches:
        shown = matches[:3]
        return RepoView("\n\n".join(_format_listing(tree, d) for d in shown), listed_dirs=shown)

    files = _resolve_files(tree, path)
    if files:
        return RepoView(f"'{path}' is a FILE in the repository: {files[0]}", files=files[:1])

    # Deterministic negative answer plus the nearest real neighborhood, so the
    # model can say "doesn't exist, but here's what IS there" instead of
    # guessing or giving a bare "not found".
    view = RepoView(fallback=True)
    lines = [f"The path '{path}' does NOT exist in the repository (checked against the real GitHub tree)."]
    segments = path.split("/")
    for depth in range(len(segments) - 1, 0, -1):
        parents = _resolve_path(dirs, "/".join(segments[:depth]))
        if not parents:
            continue
        wanted = segments[depth].lower()
        for parent in parents[:3]:
            subdirs = [c.rstrip("/").lower() for c in _children(tree, parent) if c.endswith("/")]
            close = difflib.get_close_matches(wanted, subdirs, n=3, cutoff=0.75)
            if close:
                lines.append(f"Similar folder(s) in '{parent}/': " + ", ".join(close))
            lines.append(_format_listing(tree, parent))
            view.listed_dirs.append(parent)
        break
    else:
        lines.append(_top_level_listing(tree))
        view.listed_dirs.append("")
    view.context = "\n\n".join(lines)
    return view


def _match_dir_by_keyword(dirs: set[str], keywords: set[str]) -> str | None:
    dir_basenames = {d.rsplit("/", 1)[-1].lower(): d for d in dirs}

    matched_dir = next((dir_basenames[k] for k in keywords if k in dir_basenames), None)
    if matched_dir:
        return matched_dir

    # Typo tolerance ("ontrollers", "controlers") — a real user typing from
    # memory into a chat box will misspell a folder name, and falling back to
    # "nothing matched" every time that happens is unhelpful even though it's
    # honest. difflib needs no extra dependency and is good enough for short
    # identifier-like names.
    best_score, best_dir = 0.0, None
    for keyword in keywords:
        for basename, full_path in dir_basenames.items():
            shorter, longer = sorted((len(keyword), len(basename)))
            if (keyword in basename or basename in keyword) and shorter >= 0.8 * longer:
                # A near-complete substring hit (e.g. "ontrollers" missing the
                # leading 'c' of "controllers") is a stronger, more specific
                # signal than two same-length words that merely look alike
                # (e.g. "backjend" vs "backend") — score it above any
                # plausible SequenceMatcher ratio between two genuinely
                # different short words. The length guard stops a short word
                # from claiming a long folder ("repo" -> "repositories").
                score = 0.97
            else:
                score = difflib.SequenceMatcher(None, keyword, basename).ratio()
            if score > best_score:
                best_score, best_dir = score, full_path
    return best_dir if best_score >= 0.75 else None


def _mentioned_files(tree: list[dict], query: str) -> list[str]:
    """Real files named in the message by file name ("authController.js")."""
    found: list[str] = []
    for name in _FILENAME_PATTERN.findall(query.replace("\\", "/")):
        for path in _resolve_files(tree, name)[:1]:
            if path not in found:
                found.append(path)
    return found


def _describe_directory(tree: list[dict], query: str) -> RepoView:
    """
    Pure function (no I/O): real repo tree + user message -> what the message
    refers to, plus the grounded context the LLM gets. Precedence: explicit
    path in the message > folder name by keyword/typo match > top-level
    layout. Every branch returns real data, never an empty context, so the
    model always has something true to answer with rather than a reason to
    guess. Files named in the message are always collected for reading.
    """
    dirs = {e["path"] for e in tree if e["type"] == "dir"}
    mentioned = _mentioned_files(tree, query)

    paths = [p for p in _extract_paths(query) if not _FILENAME_PATTERN.fullmatch(p.rsplit("/", 1)[-1])]
    if paths:
        views = [_describe_explicit_path(tree, dirs, p) for p in paths[:2]]
        return RepoView(
            context="\n\n".join(v.context for v in views),
            listed_dirs=[d for v in views for d in v.listed_dirs],
            fallback=all(v.fallback for v in views),
            files=list(dict.fromkeys([f for v in views for f in v.files] + mentioned)),
        )

    if mentioned:
        return RepoView("\n".join(f"'{f}' is a FILE in the repository." for f in mentioned), files=mentioned)

    matched_dir = _match_dir_by_keyword(dirs, _extract_keywords(query))
    if matched_dir:
        return RepoView(_format_listing(tree, matched_dir), listed_dirs=[matched_dir])

    return RepoView("Couldn't match a specific folder name from the message. " + _top_level_listing(tree),
                    listed_dirs=[""])


# "Look inside" intent: reading a folder's files only makes sense when the
# user wants their contents reviewed/explained, not for a plain "list files".
_REVIEW_PATTERN = re.compile(
    r"\b(revisa(r|me)?|review|analiza(r)?|errore?s?|bugs?|falla(s|ndo)?|fallo|explica(me)?|explain"
    r"|qu[eé] hace|what does|lee(r)?|read|c[oó]digo de|code (of|in))\b",
    re.IGNORECASE,
)

# Budget for file contents in the prompt. OLLAMA_NUM_CTX is 8192 tokens and
# code tokenizes densely (~3 chars/token): ~6000 chars leaves room for the
# instructions, RAG context, history and the 1024-token reply.
_FILE_CONTEXT_BUDGET = 6000
_MAX_FILES_READ = 4


def _format_file(path: str, content: str, budget: int) -> str:
    lines = content.splitlines()
    shown, used = [], 0
    for number, line in enumerate(lines, start=1):
        numbered = f"{number:>4} | {line}"
        if used + len(numbered) + 1 > budget:
            break
        shown.append(numbered)
        used += len(numbered) + 1
    # State completeness explicitly either way: with only a conditional
    # "TRUNCATED" marker, a small model read the word in the instructions and
    # claimed a complete 16-line file was cut off.
    if len(shown) == len(lines):
        note = f"COMPLETE FILE, {len(lines)} lines"
    else:
        note = f"PARTIAL: only lines 1-{len(shown)} of {len(lines)} shown"
    return f"=== {path} ({note}) ===\n" + "\n".join(shown)


async def _file_contents_context(tenant_id: str, files: list[str]) -> str:
    """Reads the given real repo files (best-effort) within the prompt budget."""
    github_config = _get_github_config(tenant_id)
    if not github_config or not files:
        return ""
    repo, token = github_config
    targets = files[:_MAX_FILES_READ]
    per_file = _FILE_CONTEXT_BUDGET // len(targets)
    parts = []
    for path in targets:
        try:
            content = await get_file_content(repo, token, path)
        except Exception as e:
            logger.warning("Reading %s failed for tenant %s: %s", path, tenant_id, e)
            parts.append(f"=== {path} === (could not be read from GitHub)")
            continue
        parts.append(_format_file(path, content, per_file))
    if len(files) > len(targets):
        parts.append(f"(Only the first {len(targets)} of {len(files)} files were read: "
                     + ", ".join(files[len(targets):]) + " were not.)")
    return "\n\n".join(parts)


# Outage/error reports and explicit log requests — what triggers a read-only
# look at the hosting platform (Fase 10.6).
_OUTAGE_PATTERN = re.compile(
    r"\b(ca[ií]d[oa]s?|se (cae|cay[oó])|down|no (carga|funciona|responde|abre|conecta|anda)"
    r"|error(es)? (5\d\d|del servidor|en (el )?servidor|interno)|5\d\d|timeouts?|crash\w*"
    r"|lent[oa]s?|logs?|registros)\b",
    re.IGNORECASE,
)

# Requests to CHANGE a server. The agent can't (no code path exists for it);
# this only guarantees the answer says so and routes it to humans.
_SERVER_MUTATION_PATTERN = re.compile(
    r"\b(reinici(a|e|ar|alo|a el)|restart|reboot|redespl(ie|e)g\w*|redeploy\w*|rollback|revert(ir|ar)?"
    r"|apag(a|ar|alo)|suspend(e|er)|escal(a|ar) (el|los) (servidor|servicio|instancia)s?"
    r"|haz (un )?(deploy|despliegue))\b",
    re.IGNORECASE,
)

# The model CLAIMING it changed a server ("listo, reinicié el servidor") —
# always false, since no code path for that exists. Seen with the local 8B.
_CLAIMED_SERVER_ACTION_PATTERN = re.compile(
    r"\b(reinici[eé]|he reiniciado|reiniciado|redesplegu[eé]|he redesplegado|redesplegado|restarted"
    r"|redeployed|rolled back|revert[ií]|apagu[eé]|suspend[ií]|escal[eé] (el|los) (servidor|servicio))\b",
    re.IGNORECASE,
)

_MAX_SERVICES_PER_TURN = 3


def _pick_services(services: list[ServiceRef], text: str) -> list[ServiceRef]:
    """Services named in the conversation; if none is named, all of them
    (capped) — "la tienda no carga" doesn't say which service is behind it."""
    lowered = text.lower()
    named = [s for s in services if s.name.lower() in lowered
             or any(len(w) >= 4 and w in lowered for w in re.findall(r"\w+", s.name.lower()))]
    return (named or services)[:_MAX_SERVICES_PER_TURN]


def _health_checker(mcp_client: MCPToolClient):
    """Reuses the existing check_service_status MCP tool (Fase 4)."""
    async def check(url: str) -> dict | None:
        raw = await mcp_client.call_tool("check_service_status", {"service_url": url})
        try:
            return json.loads(raw)
        except ValueError:
            return None
    return check


# Schema-ish junk a small model sometimes emits as a list item
# ("tool_used_check_service_status:false,").
_JUNK_DETAIL = re.compile(r"^[\w.-]+\s*:\s*(true|false|null|none|\d+)?\s*,?$", re.IGNORECASE)


def _compose_reply(result: ConciergeResult) -> str:
    items = [d.strip() for d in result.details if d and d.strip() and not _JUNK_DETAIL.match(d.strip())]
    if not items:
        return result.response_text
    return result.response_text.rstrip() + "\n\n" + "\n".join(f"- {item.lstrip('-• ')}" for item in items)


def _verified_listing_footer(tree: list[dict], listed_dirs: list[str], response: str) -> str:
    """
    The real listing, appended in code when the model's reply left out
    entries it was given — so "what's in X / what does exist" never depends
    on a small model copying a list correctly (it often answers just "X
    doesn't exist" and drops the useful part).
    """
    blocks = []
    for d in listed_dirs:
        entries = _children(tree, d) if d else sorted(
            e["path"] + ("/" if e["type"] == "dir" else "") for e in tree if "/" not in e["path"]
        )
        if not entries or all(e.rstrip("/").lower() in response.lower() for e in entries):
            continue
        title = f"`{d}/`" if d else "la raíz del repositorio"
        blocks.append(f"📂 Contenido real (GitHub) de {title}:\n" + "\n".join(f"- {e}" for e in entries))
    return "\n\n".join(blocks)


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

    wants_code = bool(tenant_id and _CODE_QUESTION_PATTERN.search(user_query))
    wants_directory = bool(
        tenant_id and (_DIRECTORY_QUESTION_PATTERN.search(recent_text) or _extract_paths(user_query))
    )
    wants_files = bool(tenant_id and _FILENAME_PATTERN.search(user_query.replace("\\", "/")))

    code_context = await _code_search_context(tenant_id, user_query) if wants_code else ""

    # A repo question whose code search came back empty ("revisa el repo y
    # dime qué hay") still gets the real repo layout, so the model answers
    # from real data instead of a bare "no information found".
    repo_tree: list[dict] = []
    repo_view = RepoView()
    if wants_directory or wants_files or (wants_code and not code_context):
        repo_tree = await _fetch_repo_tree(tenant_id)
        if repo_tree:
            repo_view = _describe_directory(repo_tree, user_query)
    directory_context = repo_view.context

    # Fase 10.6: an outage/error report (or an explicit "check the logs")
    # triggers a READ-ONLY look at the hosting platform: deterministic
    # verdict + redacted recent errors + the file:line they point to.
    user_context = state.get("user_context", {})
    diagnoses: list[ServiceDiagnosis] = []
    if tenant_id and _OUTAGE_PATTERN.search(user_query):
        targets = _pick_services(get_log_services(tenant_id), recent_text)
        if targets:
            if not repo_tree:
                repo_tree = await _fetch_repo_tree(tenant_id)
            health_check = _health_checker(mcp_client)
            for ref in targets:
                diagnoses.append(await diagnose_service(
                    tenant_id, user_context.get("user_id"), ref, health_check, repo_tree,
                ))
    include_raw_logs = user_context.get("role") in RAW_LOG_ROLES
    diagnosis_context = "\n\n".join(d.for_prompt(include_raw_logs) for d in diagnoses)

    # Names alone can't diagnose anything — read the actual code when the
    # user names a file, asks to review/explain a folder's contents, or a
    # stack trace in the logs points at it.
    files_to_read = [l.repo_path for d in diagnoses for l in d.locations] + list(repo_view.files)
    if _REVIEW_PATTERN.search(user_query) and not repo_view.fallback:
        for d in repo_view.listed_dirs:
            if d:  # never "read the whole repo root"
                files_to_read += [f"{d}/{c}" for c in _children(repo_tree, d) if not c.endswith("/")]
    file_context = await _file_contents_context(tenant_id, list(dict.fromkeys(files_to_read)))

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
    context section below or in a tool's actual output. You have NO memory of
    this repository beyond what's printed here. If a context section says
    "None found" or is missing for what the user asked (specific files, code
    content, whether something has errors), say plainly that you don't have
    that information / couldn't find it — do NOT invent file names, code, or
    a review verdict that isn't grounded in real data below.

    When "Real file contents" are provided below, you CAN and SHOULD read
    them to answer: explain what the code does or point out concrete
    problems, citing the file and line number (e.g. authController.js:42).
    Each file header says whether it is a COMPLETE FILE or PARTIAL; only for
    PARTIAL files mention that the remaining lines weren't reviewed. Don't
    describe the file's size or metadata — talk about its code.

    When asked to review a file or look for errors, always give a verdict:
    either each concrete problem found (file:line + why it's a problem), or
    say explicitly that you found no evident errors in the code shown and
    summarize what it does. A review/explanation answered from the file
    contents IS resolved=true.

    When the answer is a list (one item per file, step, or finding), put a
    short intro in response_text and each item in the details field.

    Company policy context:
    {policy_context or "None found."}

    Technical documentation context:
    {tech_context or "None found."}
    {f"Relevant code found in the company repository:\n{code_context}\n" if code_context else ""}
    {f"Repository directory listing:\n{directory_context}\n" if directory_context else ""}
    {f"Real file contents (fetched from GitHub just now, with line numbers):\n{file_context}\n" if file_context else ""}
    {f"Service diagnosis (computed by code from real platform data — the status is authoritative, don't contradict it):\n{diagnosis_context}\n" if diagnosis_context else ""}
    {services_note}
    You have READ-ONLY access to servers: you can see status and logs, but you
    can NOT restart, redeploy, scale, roll back, suspend or change any server
    or its settings, and no tool can. If asked to, say plainly that you can't
    and that a ticket will go to the engineering team. Never claim you did it.

    When a service diagnosis is present: explain in plain words what is
    failing, and if code locations are given, read those lines in the file
    contents and say what in that code causes the error.
    Available tools:
    {mcp_client.prompt_catalog()}

    Always reply in the same language the user wrote in.

    An informational question you answered from the context above (including
    a definitive "that folder/file doesn't exist, here's what does") IS
    resolved=true — don't open a ticket just because the answer was negative.

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

    # Only the data we fetched and what the USER wrote count as grounding —
    # never earlier assistant turns, or one past hallucination would
    # legitimize the next.
    user_text = " ".join(
        str(m.content) for m in state["messages"]
        if isinstance(m, HumanMessage) and isinstance(m.content, str)
    )
    grounding_text = "\n".join([
        policy_context, tech_context, code_context, directory_context, file_context, diagnosis_context, user_text,
    ])
    ungrounded = _ungrounded_repo_names(_compose_reply(result), repo_tree, grounding_text)
    if ungrounded:
        logger.warning("Concierge response named non-existent repo items %s — retrying once", sorted(ungrounded))
        correction = (
            f"Your previous answer mentioned {', '.join(sorted(ungrounded))}, which do NOT exist in the "
            "repository data you were given. Answer again using ONLY names that literally appear in the "
            "context sections. If what the user asked for doesn't exist, say so and list what does exist."
        )
        try:
            result = await invoke_structured(
                llm_super, ConciergeResult,
                messages + [AIMessage(content=_compose_reply(result)), HumanMessage(content=correction)],
            )
            ungrounded = _ungrounded_repo_names(_compose_reply(result), repo_tree, grounding_text)
        except Exception as e:
            logger.warning("Concierge grounding retry failed: %s", e)
        if ungrounded:
            # Still inventing: answer with the verified data itself instead
            # of passing a fabrication on to the user.
            logger.warning("Concierge still ungrounded after retry %s — using deterministic answer", sorted(ungrounded))
            verified = directory_context or code_context
            text = (
                f"No pude generar una respuesta verificada. Estos son los datos reales del repositorio:\n\n{verified}"
                if verified else
                "No tengo datos verificados sobre esos archivos del repositorio."
            )
            result = ConciergeResult(response_text=text, resolved=True)

    response_text = _compose_reply(result)
    if repo_view.listed_dirs:
        footer = _verified_listing_footer(repo_tree, repo_view.listed_dirs, response_text)
        if footer:
            response_text = f"{response_text}\n\n{footer}"
    if result.tool_name in CONCIERGE_ALLOWED_TOOLS:
        try:
            tool_output = await mcp_client.call_tool(result.tool_name, result.tool_args)
            response_text = f"{response_text}\n\n{tool_output}"
        except Exception as e:
            logger.warning("Concierge tool call '%s' failed: %s", result.tool_name, e)

    resolved = result.resolved
    # Deterministic, whatever the model wrote: the verdict is stated by code,
    # a DOWN service always becomes a ticket, and a request to change a server
    # always gets the read-only answer (and goes to humans as a ticket).
    if _CLAIMED_SERVER_ACTION_PATTERN.search(response_text):
        logger.warning("Concierge claimed a server action it cannot perform — discarding its reply")
        response_text = "No realicé ninguna acción sobre los servidores."
    if diagnoses:
        response_text += "\n\n" + "\n".join(d.verdict_line() for d in diagnoses)
        if any(d.verdict.status == DOWN for d in diagnoses):
            resolved = False
    if _SERVER_MUTATION_PATTERN.search(user_query):
        response_text += ("\n\n🔒 No puedo reiniciar, redesplegar ni modificar servidores: mi acceso es de "
                          "solo lectura (estado y logs). Lo derivo al equipo de ingeniería con un ticket.")
        resolved = False

    return {
        "messages": [AIMessage(content=response_text)],
        "resolved": resolved,
        "final_response": response_text,
        "diagnosis_report": "\n\n".join(d.for_ticket() for d in diagnoses) or None,
    }


def get_concierge_workflow() -> StateGraph:
    workflow = StateGraph(ConciergeState)
    workflow.add_node("concierge", concierge_node)
    workflow.add_edge(START, "concierge")
    workflow.add_edge("concierge", END)
    return workflow
