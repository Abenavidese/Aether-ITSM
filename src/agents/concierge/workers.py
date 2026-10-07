"""
Investigation workers (Fase 16.3): one deterministic, READ-ONLY function per
kind of check, executed for a TurnPlan. There is no write worker and no LLM
in here — the only model that decides anything is the supervisor (plan.py
validates what it asks for before a worker ever sees it).

I/O arrives through ConciergeSources (dependency injection): production
wiring is built in node.py from the real readers; tests and evals pass fakes
or patch those readers. Independent reads run concurrently.
"""
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from src.integrations.platform_logs.base import ServiceRef
from src.integrations.platform_logs.service import RAW_LOG_ROLES, ServiceDiagnosis
from src.rag.service import POLICY, TECHNICAL

from .plan import MAX_FILES_PER_TURN, InvestigationRequest, TurnPlan
from .repo_view import _children, _describe_directory
from .turn import FILE_READ, FOLLOWUP, KNOWLEDGE, PLATFORM, REGEX, REPO_SEARCH, REPO_TREE, SUPERVISOR, TurnContext


@dataclass(frozen=True)
class ConciergeSources:
    """Every read a chat turn can make. All of them are read-only."""
    retrieve: Callable[..., Any]                                   # knowledge base (blocking)
    code_search: Callable[[str, str], Awaitable[str]]              # (tenant, text) -> "- path (url)" lines
    fetch_tree: Callable[[str], Awaitable[list[dict]]]
    read_files: Callable[[str, list[str]], Awaitable[str]]         # (tenant, paths) -> numbered contents
    log_services: Callable[[str], list[ServiceRef]]                # blocking (DB)
    monitored_services: Callable[[str], list[dict]]                # blocking (DB)
    diagnose: Callable[..., Awaitable[ServiceDiagnosis]]
    health_checker: Callable[[Any], Callable[[str], Awaitable[dict | None]]]
    repo_connected: Callable[[str], bool]                          # blocking (DB)


@dataclass(frozen=True)
class TurnInputs:
    tenant_id: str
    user_id: str | None
    role: str | None
    history: list[str]          # the user's previous messages (follow-up retrieval)
    mcp_client: Any


async def _knowledge(turn: TurnContext, src: ConciergeSources, inputs: TurnInputs) -> None:
    async with turn.investigating(KNOWLEDGE, "company docs", REGEX) as inv:
        knowledge = await asyncio.to_thread(
            src.retrieve, inputs.tenant_id, turn.user_query, sources=[POLICY, TECHNICAL],
            history=inputs.history, origin="chat",
        )
        turn.knowledge, turn.knowledge_context = knowledge, knowledge.to_prompt()
        inv.found = f"{len(knowledge.passages)} passage(s)"


async def _repo_search(turn: TurnContext, src: ConciergeSources, inputs: TurnInputs,
                       request: InvestigationRequest) -> None:
    async with turn.investigating(REPO_SEARCH, request.target[:80], request.trigger) as inv:
        found = await src.code_search(inputs.tenant_id, request.target)
        existing = turn.code_context.splitlines()
        new = [line for line in found.splitlines() if line not in existing]
        turn.code_context = "\n".join(existing + new)
        inv.found = f"{len(new)} file(s)"


async def _repo_tree(turn: TurnContext, src: ConciergeSources, inputs: TurnInputs, trigger: str) -> None:
    async with turn.investigating(REPO_TREE, "repository", trigger) as inv:
        turn.repo_tree = await src.fetch_tree(inputs.tenant_id)
        inv.found = f"{len(turn.repo_tree)} entries"


async def _platform(turn: TurnContext, src: ConciergeSources, inputs: TurnInputs, ref: ServiceRef,
                    trigger: str) -> ServiceDiagnosis:
    async with turn.investigating(PLATFORM, ref.name, trigger) as inv:
        diagnosis = await src.diagnose(inputs.tenant_id, inputs.user_id, ref,
                                       src.health_checker(inputs.mcp_client), turn.repo_tree)
        inv.found = diagnosis.verdict.status
        return diagnosis


async def _file_read(turn: TurnContext, src: ConciergeSources, inputs: TurnInputs, paths: list[str],
                     trigger: str) -> None:
    async with turn.investigating(FILE_READ, ", ".join(paths[:MAX_FILES_PER_TURN]), trigger) as inv:
        content = await src.read_files(inputs.tenant_id, paths)
        turn.file_context = f"{turn.file_context}\n\n{content}".strip() if turn.file_context else content
        turn.files_read += paths[:MAX_FILES_PER_TURN]
        inv.found = f"{min(len(paths), MAX_FILES_PER_TURN)} file(s)"


async def run_first_round(turn: TurnContext, plan: TurnPlan, src: ConciergeSources, inputs: TurnInputs) -> None:
    """
    Stage 1 (concurrent): knowledge base, code search, repo layout, the
    monitored-service list. Stage 2: the platform checks (they map stack
    traces onto the repo layout). Stage 3: the files the findings point at.
    """
    searches = plan.of(REPO_SEARCH)
    trees = plan.of(REPO_TREE)
    platform_refs = _resolve_services(plan)
    stage1: list[Awaitable[Any]] = [_knowledge(turn, src, inputs)]
    stage1 += [_repo_search(turn, src, inputs, r) for r in searches]
    if trees or platform_refs:
        # The platform check needs the layout to turn stack traces into files.
        stage1.append(_repo_tree(turn, src, inputs, trees[0].trigger if trees else FOLLOWUP))

    async def services() -> None:
        turn.monitored_services = await asyncio.to_thread(src.monitored_services, inputs.tenant_id)
    stage1.append(services())
    await asyncio.gather(*stage1)

    if plan.tree_if_search_empty and not turn.code_context and not turn.repo_tree:
        await _repo_tree(turn, src, inputs, REGEX)
    describe = plan.describe_directory or bool(trees) or (plan.tree_if_search_empty and not turn.code_context)
    if describe and turn.repo_tree:
        turn.repo_view = _describe_directory(turn.repo_tree, turn.user_query)
    turn.directory_context = turn.repo_view.context

    turn.outage_without_services = plan.outage_without_services
    diagnoses = await asyncio.gather(*(_platform(turn, src, inputs, ref, trigger) for ref, trigger in platform_refs))
    turn.diagnoses = list(diagnoses)
    turn.diagnosis_context = "\n\n".join(d.for_prompt(inputs.role in RAW_LOG_ROLES) for d in turn.diagnoses)

    # Names alone can't diagnose anything — read the actual code when the
    # user names a file, asks to review a folder, or a stack trace points at it.
    # Only the failing line's file: the callers in the trace just propagated it.
    located = [d.locations[0].repo_path for d in turn.diagnoses if d.locations]
    files = located + list(turn.repo_view.files)
    if plan.review_listed_dirs and not turn.repo_view.fallback:
        for d in turn.repo_view.listed_dirs:
            if d:  # never "read the whole repo root"
                files += [f"{d}/{c}" for c in _children(turn.repo_tree, d) if not c.endswith("/")]
    files += [r.target for r in plan.of(FILE_READ)]
    files = list(dict.fromkeys(files))
    if files:
        await _file_read(turn, src, inputs, files, FOLLOWUP if located else REGEX)


async def run_follow_up(turn: TurnContext, requests: list[InvestigationRequest], src: ConciergeSources,
                        inputs: TurnInputs) -> None:
    """Round 2 (Fase 16.5): one more code search and/or the files the supervisor picked."""
    for request in [r for r in requests if r.kind == REPO_SEARCH][:1]:
        await _repo_search(turn, src, inputs, request)
    files = [r.target for r in requests if r.kind == FILE_READ and r.target not in turn.files_read]
    if files:
        await _file_read(turn, src, inputs, files[: MAX_FILES_PER_TURN - len(turn.files_read)], SUPERVISOR)


def _resolve_services(plan: TurnPlan) -> list[tuple[ServiceRef, str]]:
    by_name = {s.name: s for s in plan.log_services}
    return [(by_name[r.target], r.trigger) for r in plan.of(PLATFORM) if r.target in by_name]
