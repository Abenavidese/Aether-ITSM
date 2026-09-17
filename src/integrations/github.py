"""
Thin GitHub REST API client.

Centralizes the one thing every caller needs — a Bearer-authenticated
request against api.github.com — so the connection test in
src/tenant/router.py and the escalation issue-creation flow in
src/api/routes.py don't each hand-roll their own httpx headers/error
handling. Callers are responsible for decrypting the tenant's stored token
before calling in (see src/security/encryption.py); this module only ever
sees the raw token for the duration of a single request.
"""
import httpx

GITHUB_API_BASE = "https://api.github.com"


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
    (src/agent/mcp_client.py), which would mean asking the model to supply
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
            params={"q": f"{query} repo:{repo}"},
        )

    if response.status_code != 200:
        message = response.json().get("message", response.text)
        raise RuntimeError(f"GitHub code search failed ({response.status_code}): {message}")

    items = response.json().get("items", [])[:max_results]
    return [{"path": item["path"], "url": item["html_url"]} for item in items]


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
