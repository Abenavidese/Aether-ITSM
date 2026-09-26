"""
Secret/PII redaction shared by every path where untrusted text is stored,
shown to an LLM, or sent somewhere else (Fase 10.4 logs, Fase 11 RAG
ingest, repo file contents, Concierge replies, GitHub issues).

Three profiles, because "redact everything that looks sensitive" breaks the
text it is applied to in different ways:
- redact(): logs. Credentials (loose key=value), then emails and card-like
  numbers. The strictest profile.
- redact_document(): knowledge-base documents. Credentials with loose
  key=value ("password: Hunter2" in a runbook is a leak), but emails stay —
  "escribe a soporte@acme.com" is exactly what a policy doc is for.
- redact_code(): source files and model replies about them. Only
  unambiguous secrets: known key formats and QUOTED literal assignments.
  The loose rule would turn `const token = jwt.sign(payload)` into
  `token = [REDACTED](payload)` and wreck the code review the user asked for.
"""
import re

_Rule = tuple[re.Pattern, str]

# Well-known token/key formats — safe to apply to any text.
_KEY_FORMATS: list[_Rule] = [
    # Authorization headers / bearer tokens, then any bare JWT.
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 [REDACTED]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}"), "[REDACTED_JWT]"),
    # GitHub, OpenAI-style, Stripe, Slack, AWS, Aether, Render.
    (re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"), "[REDACTED_KEY]"),
    (re.compile(r"\b(sk|pk|rk)[-_](live|test|proj)?[-_]?[A-Za-z0-9]{16,}"), "[REDACTED_KEY]"),
    (re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}"), "[REDACTED_KEY]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_KEY]"),
    (re.compile(r"\baeth_live_[A-Za-z0-9_-]{8,}"), "[REDACTED_KEY]"),
    (re.compile(r"\brnd_[A-Za-z0-9]{16,}"), "[REDACTED_KEY]"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(-----END [A-Z ]*PRIVATE KEY-----|$)"),
     "[REDACTED_PRIVATE_KEY]"),
    # Credentials inside connection strings / URLs: scheme://user:pass@host
    (re.compile(r"\b([a-z][a-z0-9+.-]*://)[^\s:/@]+:[^\s@/]+@"), r"\1[REDACTED]@"),
]

_SENSITIVE_KEY = r"(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|authorization|cookie|session)"

# key=value / "key": "value" for sensitive-sounding keys, quoted or not.
_LOOSE_ASSIGNMENT: _Rule = (
    re.compile(rf"(?i)\b{_SENSITIVE_KEY}(\"?\s*[:=]\s*\"?)([^\s\"&,;]+)"), r"\1\2[REDACTED]",
)
# Only a quoted literal of real length: `apiKey = "abc123..."`, not `token = jwt.sign(`.
_QUOTED_ASSIGNMENT: _Rule = (
    re.compile(rf"(?i)\b(\w*{_SENSITIVE_KEY}\w*)([\"']?\s*[:=]\s*)([\"'])[^\"'\s]{{8,}}\4"), r"\1\3\4[REDACTED]\4",
)

_PII: list[_Rule] = [
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[REDACTED_EMAIL]"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[REDACTED_NUMBER]"),
]


def _apply(text: str, rules: list[_Rule]) -> str:
    for pattern, replacement in rules:
        text = pattern.sub(replacement, text)
    return text


def redact(text: str) -> str:
    """Logs: credentials (loose) + PII."""
    return _apply(text, _KEY_FORMATS + [_LOOSE_ASSIGNMENT] + _PII)


def redact_document(text: str) -> str:
    """Knowledge-base documents: credentials (loose), emails kept."""
    return _apply(text, _KEY_FORMATS + [_LOOSE_ASSIGNMENT])


def redact_code(text: str) -> str:
    """Source code and replies about it: only unambiguous secrets."""
    return _apply(text, _KEY_FORMATS + [_QUOTED_ASSIGNMENT])
