"""
Best-effort reads from the tenant's GitHub repo for the Concierge (code
search, tree, file contents). Secrets never come from the model: the repo
and token are resolved server-side, and credential files are refused by
get_file_content itself (Fase 11.9).
"""
import logging

from src.db.database import SessionLocal
from src.db.models import Company
from src.integrations.github import get_file_content, get_repo_tree, search_code
from src.security.prompt_safety import find_injection_markers
from src.security.redaction import redact_code
from src.security.sensitive_files import SensitiveFileError

logger = logging.getLogger(__name__)


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
        except SensitiveFileError:
            parts.append(f"=== {path} === (NOT READ: this kind of file can hold credentials, "
                         "so the assistant is never allowed to open it)")
            continue
        except Exception as e:
            logger.warning("Reading %s failed for tenant %s: %s", path, tenant_id, e)
            parts.append(f"=== {path} === (could not be read from GitHub)")
            continue
        markers = find_injection_markers(content)
        if markers:
            # Observability only — the content is still fenced as data and
            # tool_policy bounds what any instruction in it could achieve.
            logger.warning("Possible prompt injection in repo file %s (tenant %s): %s", path, tenant_id, markers)
        parts.append(_format_file(path, redact_code(content), per_file))
    if len(files) > len(targets):
        parts.append(f"(Only the first {len(targets)} of {len(files)} files were read: "
                     + ", ".join(files[len(targets):]) + " were not.)")
    return "\n\n".join(parts)
