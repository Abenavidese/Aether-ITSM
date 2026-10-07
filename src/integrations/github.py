"""
Thin GitHub REST API client.

Centralizes the one thing every caller needs — a Bearer-authenticated
request against api.github.com — so the connection test in
src/api/routers/tenant.py and the escalation issue-creation flow in
src/api/routers/tickets.py don't each hand-roll their own httpx headers/error
handling. Callers are responsible for decrypting the tenant's stored token
before calling in (see src/security/encryption.py); this module only ever
sees the raw token for the duration of a single request.
"""
import re

import httpx

from src.security.sensitive_files import SensitiveFileError, is_sensitive_path

GITHUB_API_BASE = "https://api.github.com"
# GitHub rejects longer code-search queries with a 400 (found live: a chat
# message with a screenshot's reading appended exceeded it).
MAX_CODE_SEARCH_QUERY_CHARS = 256


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}


async def get_repo_info(repo: str, token: str) -> dict:
    """Returns the repo's metadata (full_name, stargazers_count, open_issues_count, ...)."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{GITHUB_API_BASE}/repos/{repo}", headers=_headers(token))

    if response.status_code != 200:
        message = response.json().get("message", response.text)
        raise RuntimeError(f"GitHub API error ({response.status_code}): {message}")

    return response.json()


async def search_code(repo: str, token: str, query: str, max_results: int = 3) -> list[dict]:
    """
    Searches code in `repo` via GitHub's code search API.

    Deliberately NOT exposed as an MCP tool the LLM calls directly (unlike
    check_service_status/query_knowledge_base) — an MCP tool's declared
    parameters are shown to the LLM verbatim in its prompt catalog
    (src/tools/mcp_client.py), which would mean asking the model to supply
    `repo`/`token` itself. Real per-tenant secrets must never be something
    an LLM is asked to produce or could hallucinate; the same principle
    already used for GitHub issue creation on escalation (Fase 3). Callers
    fetch/decrypt the tenant's token server-side and inject only the
    `query` text into the agent's context.

    Limitations (Fase 6.3): GitHub's code search API is rate-limited to
    10 requests/minute per authenticated token, separate from the general
    API limit — callers must not retry aggressively. A private repo's
    token needs the `repo` (code read) scope or every search 404s.
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{GITHUB_API_BASE}/search/code",
            headers=_headers(token),
            params={"q": f"{_fit_search_query(query, len(repo))} repo:{repo}"},
        )

    if response.status_code != 200:
        message = response.json().get("message", response.text)
        raise RuntimeError(f"GitHub code search failed ({response.status_code}): {message}")

    items = response.json().get("items", [])[:max_results]
    return [{"path": item["path"], "url": item["html_url"]} for item in items]


def _fit_search_query(query: str, repo_len: int) -> str:
    """
    Plain search terms only, cut at a word boundary so the full `q` (plus
    " repo:<repo>") fits GitHub's limit. Search syntax is dropped, not
    escaped: qualifiers like "repo:other/private" would widen the search to
    any repo the tenant's token can read (several repo: qualifiers are OR'ed),
    and quotes/parentheses/tags from pasted errors made GitHub fail with
    "unable to parse query".
    """
    budget = MAX_CODE_SEARCH_QUERY_CHARS - len(" repo:") - repo_len
    terms = [t for t in _SEARCH_TERM.findall(query) if t.upper() not in _SEARCH_OPERATORS]
    query = " ".join(terms)
    if len(query) <= budget:
        return query
    cut = query[:budget]
    return cut.rsplit(" ", 1)[0] if " " in cut else cut


# A term never contains ":" (no qualifiers) nor quotes/parentheses.
_SEARCH_TERM = re.compile(r"[\w][\w.\-/]*")
_SEARCH_OPERATORS = {"AND", "OR", "NOT"}


async def get_repo_tree(repo: str, token: str) -> list[dict]:
    """
    Returns a flat listing of every file/directory path in `repo`'s default
    branch, via GitHub's recursive git-trees API (one call for the whole
    structure). This is a DIFFERENT capability from search_code: that one
    finds files whose CONTENT matches a text query, it cannot enumerate a
    directory — and unlike the plain Contents API (one call per exact path),
    a flat tree lets a caller find "the controllers folder" without already
    knowing its full path, which varies per repo.

    Before this existed, a "list the files in controllers/" request had no
    real tool behind it at all, and a local model answered anyway by
    fabricating plausible-looking filenames instead of saying it couldn't
    check — see concierge.py's anti-hallucination instruction, added
    specifically because of that failure mode.

    Same secrets-never-reach-the-LLM principle as search_code: repo/token
    are fetched/decrypted server-side, never something the agent supplies.
    """
    repo_info = await get_repo_info(repo, token)
    default_branch = repo_info.get("default_branch", "main")

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{GITHUB_API_BASE}/repos/{repo}/git/trees/{default_branch}",
            headers=_headers(token),
            params={"recursive": "1"},
        )

    if response.status_code != 200:
        message = response.json().get("message", response.text)
        raise RuntimeError(f"GitHub tree lookup failed ({response.status_code}): {message}")

    data = response.json()
    return [
        {"path": item["path"], "type": "dir" if item["type"] == "tree" else "file"}
        for item in data.get("tree", [])
    ]


async def get_file_content(repo: str, token: str, path: str) -> str:
    """
    Returns the raw text of one file on `repo`'s default branch (Contents API
    with the raw media type — no base64 round-trip). The directory tree alone
    only tells the agent a file EXISTS; diagnosing anything ("why does login
    fail", "is there a bug in authController.js") needs what's inside it.

    Same secrets-never-reach-the-LLM principle as search_code/get_repo_tree:
    `path` comes from matching the user's message against the real tree
    server-side, never from the model. The Contents API serves files up to
    1 MB; callers are expected to budget what they put in a prompt.

    Files that can hold credentials (.env, keys, ...) are refused before any
    request is made (Fase 11.9) — this is the one choke point every reader
    goes through.
    """
    if is_sensitive_path(path):
        raise SensitiveFileError(f"'{path}' can hold credentials and is never read by the agent.")
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{GITHUB_API_BASE}/repos/{repo}/contents/{path}",
            headers={**_headers(token), "Accept": "application/vnd.github.raw+json"},
        )

    if response.status_code != 200:
        try:
            message = response.json().get("message", response.text)
        except ValueError:
            message = response.text
        raise RuntimeError(f"GitHub file fetch failed for '{path}' ({response.status_code}): {message}")

    return response.text


async def create_issue(repo: str, token: str, title: str, body: str) -> str:
    """Creates an issue in `repo` (format 'owner/repo') and returns its HTML URL."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{GITHUB_API_BASE}/repos/{repo}/issues",
            headers=_headers(token),
            json={"title": title, "body": body},
        )

    if response.status_code != 201:
        message = response.json().get("message", response.text)
        raise RuntimeError(f"GitHub issue creation failed ({response.status_code}): {message}")

    return response.json()["html_url"]


# ── Fase 16: draft pull requests with a proposed fix ─────────────────────────
#
# The only write path to a repository besides issues. Guard rails live HERE,
# at the one choke point, not in the caller:
# - only branches named aether/fix-*, created fresh from the default branch;
# - the default branch is never written, and nothing is ever merged;
# - credential files and CI configuration (.github/) are never written;
# - the pull request is always a draft, for a human to review.

_FIX_BRANCH = re.compile(r"^aether/fix-[a-z0-9][a-z0-9-]{0,60}$")
_NEVER_WRITE_PREFIXES = (".github/",)


class UnsafeRepoWrite(Exception):
    """A write the guard rails above refuse — raised before any request."""


def _check_fix_write(branch: str, path: str) -> None:
    if not _FIX_BRANCH.match(branch):
        raise UnsafeRepoWrite(f"branch {branch!r} is not an aether/fix-* branch")
    normalized = path.replace("\\", "/").lstrip("/")
    if is_sensitive_path(normalized) or normalized.startswith(_NEVER_WRITE_PREFIXES) or ".." in normalized.split("/"):
        raise UnsafeRepoWrite(f"'{path}' is never written by the agent")


async def _github(client: httpx.AsyncClient, method: str, url: str, token: str, expected: tuple[int, ...],
                  **kwargs) -> httpx.Response:
    response = await client.request(method, f"{GITHUB_API_BASE}{url}", headers=_headers(token), **kwargs)
    if response.status_code not in expected:
        try:
            message = response.json().get("message", response.text)
        except ValueError:
            message = response.text
        raise RuntimeError(f"GitHub {method} {url.split('?')[0]} failed ({response.status_code}): {message}")
    return response


async def create_fix_pull_request(repo: str, token: str, branch: str, path: str, new_content: str,
                                  commit_message: str, title: str, body: str) -> str:
    """
    Commits `new_content` to `path` on a NEW branch `branch` (from the
    default branch's head) and opens a DRAFT pull request. Idempotent: if
    the branch already has an open pull request, returns its URL.
    """
    import base64

    _check_fix_write(branch, path)
    owner = repo.split("/", 1)[0]
    async with httpx.AsyncClient(timeout=30) as client:
        info = (await _github(client, "GET", f"/repos/{repo}", token, (200,))).json()
        default_branch = info.get("default_branch", "main")
        if branch == default_branch:
            raise UnsafeRepoWrite("the default branch is never written")

        existing = (await _github(client, "GET", f"/repos/{repo}/pulls", token, (200,),
                                  params={"head": f"{owner}:{branch}", "state": "open"})).json()
        if existing:
            return existing[0]["html_url"]

        head = (await _github(client, "GET", f"/repos/{repo}/git/ref/heads/{default_branch}", token, (200,))).json()
        created = await _github(client, "POST", f"/repos/{repo}/git/refs", token, (201, 422),
                                json={"ref": f"refs/heads/{branch}", "sha": head["object"]["sha"]})
        if created.status_code == 422:
            # The branch exists without an open PR (a retried job): only reuse
            # it if it is still exactly the default branch's head.
            current = (await _github(client, "GET", f"/repos/{repo}/git/ref/heads/{branch}", token, (200,))).json()
            if current["object"]["sha"] != head["object"]["sha"]:
                raise UnsafeRepoWrite(f"branch {branch} already exists with other commits")

        current_file = (await _github(client, "GET", f"/repos/{repo}/contents/{path}", token, (200,),
                                      params={"ref": branch})).json()
        await _github(client, "PUT", f"/repos/{repo}/contents/{path}", token, (200, 201), json={
            "message": commit_message, "branch": branch, "sha": current_file["sha"],
            "content": base64.b64encode(new_content.encode("utf-8")).decode("ascii"),
        })
        request = {"title": title, "head": branch, "base": default_branch, "body": body, "draft": True}
        pull = await _github(client, "POST", f"/repos/{repo}/pulls", token, (201, 422), json=request)
        if pull.status_code == 422 and "draft" in pull.text.lower():
            # Draft PRs need a paid plan on private repos: open a normal one
            # whose title says it is a proposal — merging stays a human act.
            request.update(draft=False, title=f"[PROPUESTA — revisar antes de mergear] {title}")
            pull = await _github(client, "POST", f"/repos/{repo}/pulls", token, (201,), json=request)
        elif pull.status_code == 422:
            raise RuntimeError(f"GitHub pull request creation failed (422): {pull.text[:200]}")
        return pull.json()["html_url"]
