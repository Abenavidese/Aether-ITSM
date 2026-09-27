"""Everything one chat turn gathered before the model is called."""
from dataclasses import dataclass, field

from src.integrations.logs.service import ServiceDiagnosis
from src.rag.retrieval import RetrievalResult

from .repo_view import RepoView


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

    def grounding_text(self, user_text: str) -> str:
        """Only fetched data and what the USER wrote count as grounding —
        never earlier assistant turns, or one past hallucination would
        legitimize the next."""
        return "\n".join([
            self.knowledge_context, self.code_context, self.directory_context,
            self.file_context, self.diagnosis_context, user_text,
        ])
