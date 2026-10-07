"""Everything one chat turn gathered before the model is called."""
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from src.integrations.platform_logs.service import ServiceDiagnosis
from src.observability.tracing import record_span
from src.rag.retrieval import RetrievalResult

from .repo_view import RepoView

# What a turn can look at (Fase 16). Every one of them is read-only.
KNOWLEDGE, REPO_SEARCH, REPO_TREE, PLATFORM, FILE_READ = "knowledge", "repo_search", "repo_tree", "platform", "file_read"
# Why it was looked at: a deterministic rule on the message, the supervisor
# model's plan, or a lead found by an earlier investigation (a stack trace
# pointing at a file).
REGEX, SUPERVISOR, FOLLOWUP = "regex", "supervisor", "followup"


@dataclass
class Investigation:
    """One read the turn made, for the trace, the evals and the "what I checked" line."""
    kind: str
    target: str
    trigger: str
    ms: int = 0
    ok: bool = True
    found: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TurnContext:
    user_query: str
    recent_text: str
    # Fase 14: one hybrid search over policies + technical docs, numbered
    # passages the model cites as [n].
    knowledge: RetrievalResult | None = None
    knowledge_context: str = ""
    code_context: str = ""
    directory_context: str = ""
    file_context: str = ""
    diagnosis_context: str = ""
    repo_tree: list[dict] = field(default_factory=list)
    repo_view: RepoView = field(default_factory=RepoView)
    diagnoses: list[ServiceDiagnosis] = field(default_factory=list)
    monitored_services: list[dict] = field(default_factory=list)
    # An outage was reported but the tenant has no log-enabled service: the
    # model is told so (no guessing at causes) and the reply says it plainly.
    outage_without_services: bool = False
    investigations: list[Investigation] = field(default_factory=list)
    files_read: list[str] = field(default_factory=list)   # repo paths whose content is in file_context

    def grounding_text(self, user_text: str) -> str:
        """Only fetched data and what the USER wrote count as grounding —
        never earlier assistant turns, or one past hallucination would
        legitimize the next."""
        return "\n".join([
            self.knowledge_context, self.code_context, self.directory_context,
            self.file_context, self.diagnosis_context, user_text,
        ])

    @asynccontextmanager
    async def investigating(self, kind: str, target: str, trigger: str):
        """
        Records one investigation (timing, outcome) on the turn and as an
        "investigation" span. The body sets `.found` to a short summary; an
        exception marks it failed and propagates.
        """
        record = Investigation(kind=kind, target=target, trigger=trigger)
        started, started_at = time.perf_counter(), datetime.now(timezone.utc)
        try:
            yield record
        except BaseException:
            record.ok = False
            raise
        finally:
            record.ms = int((time.perf_counter() - started) * 1000)
            self.investigations.append(record)
            record_span("investigation", kind, record.ms, started_at, status="ok" if record.ok else "error",
                        attributes={"target": target, "trigger": trigger, "found": record.found})
