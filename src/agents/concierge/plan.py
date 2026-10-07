"""
What a chat turn will look at (Fase 16): the deterministic floor, the
supervisor model's proposal, and the code that merges and validates them.

Principles (docs/PLAN_IMPLEMENTACION.txt, Fase 16):
- The floor is what the regex rules triggered before Fase 16. The model can
  only ADD to it, never remove from it.
- The model picks from a closed menu. Every parameter is validated here
  against the tenant's real configuration and the real repo tree: service
  NAMES must be configured services, file paths must be offered candidates,
  search text is reduced to plain words. Anything else is dropped.
- Every investigation is read-only; there is no write worker at all.
"""
import logging
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from src.integrations.platform_logs.base import ServiceRef
from src.integrations.platform_logs.diagnosis import DEGRADED, DOWN
from src.security.sensitive_files import is_sensitive_path

from .platform import _OUTAGE_PATTERN, _pick_services
from .repo_view import (
    _CODE_QUESTION_PATTERN,
    _DIRECTORY_QUESTION_PATTERN,
    _FILENAME_PATTERN,
    _REVIEW_PATTERN,
    _extract_paths,
)
from .turn import FILE_READ, FOLLOWUP, PLATFORM, REGEX, REPO_SEARCH, REPO_TREE, SUPERVISOR, TurnContext

logger = logging.getLogger(__name__)

MAX_SERVICES = 3
MAX_FILES_PER_TURN = 4
_MAX_SEARCH_WORDS = 5
_MAX_FOLLOW_UP_FILES = 2


# ── what the supervisor model returns ────────────────────────────────────────

class InvestigationPlan(BaseModel):
    """Round 1: which read-only checks to run (Fase 16.4)."""
    checks: list[Literal["platform", "code_search", "repo_layout"]] = Field(
        default_factory=list, description="Checks to run before answering. Empty if none is useful.")
    services: list[str] = Field(default_factory=list,
                                description="Names of the services to check (platform only). Empty = all.")
    search_terms: str = Field(default="", description="At most 5 plain words to search the code (code_search only).")
    reason: str = Field(default="", description="One short sentence: why these checks.")


class FollowUpPlan(BaseModel):
    """Round 2: follow the lead the first round found (Fase 16.5)."""
    done: bool = Field(description="True if no further check would help.")
    read_files: list[str] = Field(default_factory=list,
                                  description="At most 2 exact paths from the offered list.")
    search_terms: str = Field(default="", description="At most 5 plain words for one more code search.")
    reason: str = Field(default="", description="One short sentence.")


_CHECK_KINDS = {"platform": PLATFORM, "code_search": REPO_SEARCH, "repo_layout": REPO_TREE}


# ── the plan the workers execute ─────────────────────────────────────────────

@dataclass(frozen=True)
class InvestigationRequest:
    kind: str
    target: str = ""      # service name | search text | file path ("" = the whole repo layout)
    trigger: str = REGEX


@dataclass
class TurnPlan:
    requests: list[InvestigationRequest] = field(default_factory=list)
    # Floor semantics kept from before Fase 16 (see _gather_context history):
    describe_directory: bool = False      # answer with the real listing of the folder asked about
    tree_if_search_empty: bool = False    # a code question whose search found nothing still gets the layout
    review_listed_dirs: bool = False      # "revisa la carpeta X" reads its files
    outage_without_services: bool = False
    reason: str = ""
    # The tenant's log-enabled services, resolved once: PLATFORM targets are names from this list.
    log_services: list[ServiceRef] = field(default_factory=list)

    def add(self, request: InvestigationRequest) -> bool:
        if any(r.kind == request.kind and r.target == request.target for r in self.requests):
            return False
        self.requests.append(request)
        return True

    def of(self, kind: str) -> list[InvestigationRequest]:
        return [r for r in self.requests if r.kind == kind]


def floor_plan(user_query: str, recent_text: str, recent_user_text: str, log_services: list[ServiceRef]) -> TurnPlan:
    """Exactly what the regex rules triggered before Fase 16 — the floor."""
    plan = TurnPlan(log_services=list(log_services))
    wants_code = bool(_CODE_QUESTION_PATTERN.search(user_query))
    wants_directory = bool(_DIRECTORY_QUESTION_PATTERN.search(recent_user_text) or _extract_paths(user_query))
    wants_files = bool(_FILENAME_PATTERN.search(user_query.replace("\\", "/")))
    if wants_code:
        plan.add(InvestigationRequest(REPO_SEARCH, user_query))
    if wants_directory or wants_files:
        plan.add(InvestigationRequest(REPO_TREE))
        plan.describe_directory = True
    plan.tree_if_search_empty = wants_code
    plan.review_listed_dirs = bool(_REVIEW_PATTERN.search(user_query))
    if _OUTAGE_PATTERN.search(user_query):
        targets = _pick_services(log_services, recent_text)
        plan.outage_without_services = not targets
        for ref in targets:
            plan.add(InvestigationRequest(PLATFORM, ref.name))
    return plan


def plain_words(text: str, max_words: int = _MAX_SEARCH_WORDS) -> str:
    """Search text from a model: words only (no qualifiers, quotes or paths' punctuation)."""
    words = [w for w in re.findall(r"[A-Za-zÀ-ÿ0-9_]{2,40}", text or "")][:max_words]
    return " ".join(words)


def merge_supervisor_plan(plan: TurnPlan, proposal: InvestigationPlan, log_services: list[ServiceRef],
                          repo_connected: bool) -> list[str]:
    """
    Adds the model's validated checks to the floor (never removes). Returns
    what was dropped, for the log — a dropped item is the model asking for
    something that doesn't exist or isn't allowed.
    """
    dropped: list[str] = []
    by_name = {s.name.lower(): s for s in log_services}
    for check in dict.fromkeys(proposal.checks):
        kind = _CHECK_KINDS.get(check)
        if kind == PLATFORM:
            if not log_services:
                dropped.append("platform (no log-enabled service configured)")
                continue
            wanted = [by_name[n.strip().lower()] for n in proposal.services if n.strip().lower() in by_name]
            dropped += [f"service {n!r}" for n in proposal.services if n.strip().lower() not in by_name]
            for ref in (wanted or log_services)[:MAX_SERVICES]:
                if len(plan.of(PLATFORM)) < MAX_SERVICES:
                    plan.add(InvestigationRequest(PLATFORM, ref.name, SUPERVISOR))
            plan.outage_without_services = False
        elif kind in (REPO_SEARCH, REPO_TREE):
            if not repo_connected:
                dropped.append(f"{check} (no repository connected)")
                continue
            if kind == REPO_TREE:
                plan.add(InvestigationRequest(REPO_TREE, "", SUPERVISOR))
            elif not plan.of(REPO_SEARCH):    # one code search per round (GitHub: 10 searches/min)
                terms = plain_words(proposal.search_terms)
                if terms:
                    plan.add(InvestigationRequest(REPO_SEARCH, terms, SUPERVISOR))
                else:
                    dropped.append("code_search without search terms")
        else:
            dropped.append(f"unknown check {check!r}")
    if dropped:
        logger.warning("Concierge supervisor proposal partly dropped: %s", "; ".join(dropped))
    return dropped


# ── round 2: is there a lead worth following? ────────────────────────────────

_GENERIC_PATH_PARTS = {"api", "v1", "v2", "app", "index", "health", "static", "assets"}
_REQUEST_LINE = re.compile(r"\b(?:GET|POST|PUT|PATCH|DELETE)\s+(/[\w\-./]*)")


def _failing_path_words(turn: TurnContext) -> list[str]:
    words: list[str] = []
    for d in turn.diagnoses:
        for line in d.log_lines:
            if "ERROR" not in line:
                continue
            for path in _REQUEST_LINE.findall(line):
                words += [w.lower() for w in re.findall(r"[A-Za-z]{3,}", path) if w.lower() not in _GENERIC_PATH_PARTS]
    return list(dict.fromkeys(words))


def follow_up_candidates(turn: TurnContext) -> list[str]:
    """
    Real, readable, not-yet-read repo files related to what failed: files
    found by the code search, and files whose name matches a failing request
    path ("POST /api/cart/add 500" -> cartController.js, cartService.js...).
    """
    read = set(turn.files_read)
    files = [e["path"] for e in turn.repo_tree if e["type"] == "file"]
    existing = set(files)
    candidates = [line.split(" (", 1)[0].removeprefix("- ") for line in turn.code_context.splitlines()]
    for word in _failing_path_words(turn):
        candidates += [f for f in files if word in f.rsplit("/", 1)[-1].lower()
                       and not any(part in f for part in ("node_modules/", "/dist/", "test"))]
    return [c for c in dict.fromkeys(candidates)
            if c in existing and c not in read and not is_sensitive_path(c)][:8]


def needs_follow_up(turn: TurnContext) -> bool:
    """A failing service whose stack traces gave no code location, or code hits nobody read."""
    # Round 2 only reads into an empty file budget (the prompt is 8k tokens on the local model).
    if not turn.repo_tree or turn.file_context:
        return False
    unexplained = any(d.verdict.status in (DOWN, DEGRADED) and not d.locations for d in turn.diagnoses)
    unread_hits = bool(turn.code_context) and not turn.file_context
    return (unexplained or unread_hits) and bool(follow_up_candidates(turn))


def follow_up_evidence(turn: TurnContext) -> str:
    parts = []
    for d in turn.diagnoses:
        parts.append(f"Service {d.service.name}: {d.verdict.status} — " + "; ".join(d.verdict.evidence))
        if d.locations:
            parts.append("  stack trace points at: " + ", ".join(f"{x.repo_path}:{x.line}" for x in d.locations))
        parts += [f"  log: {line[:200]}" for line in d.log_lines[:3]]
    if turn.code_context:
        parts.append("Code search hits:\n" + turn.code_context)
    if turn.files_read:
        parts.append("Already read: " + ", ".join(turn.files_read))
    return "\n".join(parts)


def merge_follow_up(plan: TurnPlan, proposal: FollowUpPlan, candidates: list[str], can_search: bool,
                    files_left: int) -> list[str]:
    dropped: list[str] = []
    if proposal.done and not proposal.read_files and not proposal.search_terms:
        return dropped
    allowed = set(candidates)
    for path in proposal.read_files[:_MAX_FOLLOW_UP_FILES]:
        if path in allowed and files_left > 0:
            if plan.add(InvestigationRequest(FILE_READ, path, SUPERVISOR)):
                files_left -= 1
        else:
            dropped.append(f"file {path!r}")
    terms = plain_words(proposal.search_terms)
    if terms:
        if can_search:
            plan.add(InvestigationRequest(REPO_SEARCH, terms, SUPERVISOR))
        else:
            dropped.append("search (budget)")
    if dropped:
        logger.warning("Concierge follow-up proposal partly dropped: %s", "; ".join(dropped))
    return dropped


__all__ = ["FOLLOWUP", "InvestigationPlan", "FollowUpPlan", "InvestigationRequest", "TurnPlan", "floor_plan",
           "merge_supervisor_plan", "follow_up_candidates", "needs_follow_up", "follow_up_evidence",
           "merge_follow_up", "plain_words"]
