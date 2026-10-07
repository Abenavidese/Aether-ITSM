"""
Builds the GitHub issue for an escalated ticket (Fase 3) safely (Fase 11.8).

Everything in the issue is untrusted text — the employee's own words, or
LLM output (escalation reason, compliance notes) — going into a repo that
may be public and whose markdown GitHub renders and acts on:
- "@org/team" notifies people, "#123" / links / images are live, and an
  image URL is a tracking pixel for whoever reads the issue;
- emails, tokens or keys pasted into a ticket would be published.
So each untrusted field is redacted (secrets + PII) and rendered inside a
fenced code block (GitHub renders nothing inside one: no mentions, links or
images), with a fence longer than any backtick run in the text so the text
can't close it. Titles don't render markdown, but mentions/newlines are
still neutralized and the length bounded.
"""
import re

from src.security.redaction import redact

MAX_FIELD_CHARS = 4000
MAX_TITLE_CHARS = 120
_ZWSP = "​"


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def fenced(text: str | None) -> str:
    """Redacted, truncated, inert markdown block for untrusted text."""
    body = _truncate(redact((text or "").strip()) or "N/A", MAX_FIELD_CHARS)
    longest_run = max((len(m) for m in re.findall(r"`+", body)), default=0)
    fence = "`" * max(3, longest_run + 1)
    return f"{fence}text\n{body}\n{fence}"


def safe_title(title: str) -> str:
    one_line = " ".join(redact(title or "").split())
    return _truncate("[Aether] " + one_line.replace("@", "@" + _ZWSP), MAX_TITLE_CHARS)


def build_escalation_issue(external_id: str | None, title: str, description: str,
                           reason: str | None, compliance_notes: str | None) -> tuple[str, str]:
    body = (
        f"**Ticket:** `{re.sub(r'[^A-Za-z0-9._:-]', '', external_id or 'unknown')}`\n\n"
        "_Contenido generado a partir del ticket y del agente; se muestra como texto sin formato._\n\n"
        f"**Description:**\n{fenced(description)}\n\n"
        f"**Escalation reason:**\n{fenced(reason or 'Escalated by Aether ITSM')}\n\n"
        f"**Compliance notes:**\n{fenced(compliance_notes)}\n"
    )
    return safe_title(title), body


def build_fix_pull_request(external_id: str | None, service: str, path: str, line: int, evidence: list[str],
                           explanation: str, issue_url: str | None) -> tuple[str, str]:
    """
    Fase 16: the draft PR with Aether's proposed fix. Same rules as issues:
    the model's explanation is fenced; verdict evidence is code-generated;
    log lines are NEVER included (the repo may be public).
    """
    ref = re.sub(r"[^A-Za-z0-9._:-]", "", external_id or "unknown")
    safe_path = re.sub(r"[^\w./-]", "", path)
    issue = f"\n**Issue:** {issue_url}\n" if issue_url and issue_url.startswith("https://github.com/") else ""
    body = (
        "> ⚠️ **Propuesta automática de Aether — requiere revisión humana.** No se mergeó ni se desplegó nada; "
        "revisa el diff, pruébalo y decide.\n\n"
        f"**Ticket:** `{ref}`{issue}\n"
        f"**Servicio:** `{re.sub(r'[^A-Za-z0-9._ -]', '', service)}`\n"
        f"**Ubicación del error (stack trace):** `{safe_path}:{int(line)}`\n\n"
        f"**Diagnóstico (calculado por código):**\n{fenced(chr(10).join(evidence))}\n\n"
        f"**Explicación del modelo:**\n{fenced(explanation)}\n"
    )
    return safe_title(f"Fix {safe_path.rsplit('/', 1)[-1]}:{int(line)} ({ref})"), body
