"""
The RAG eval corpus and golden dataset (Fase 14.0).

corpus/main/   documents of the tenant every query runs as
corpus/other/  a second tenant with deliberately overlapping topics (its own
               VPN policy, its own meaning for PAY-4012): any passage from it
               in a result is a cross-tenant leak.
"""
import json
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CORPUS_DIR = ROOT / "corpus"
DATASET = ROOT / "dataset.jsonl"

MAIN_TENANT = "eval-rag-main"
OTHER_TENANT = "eval-rag-other"
_TENANT_DIRS = {MAIN_TENANT: "main", OTHER_TENANT: "other"}

# Policies vs technical docs, the same split the product's upload form uses.
_POLICY_PREFIXES = ("politica_", "security_")


@dataclass(frozen=True)
class CorpusDoc:
    tenant_id: str
    path: Path
    source_type: str

    @property
    def filename(self) -> str:
        return self.path.name


def source_type_for(filename: str) -> str:
    return "company_policy" if filename.startswith(_POLICY_PREFIXES) else "technical_repo"


def load_corpus() -> list[CorpusDoc]:
    docs = []
    for tenant_id, folder in _TENANT_DIRS.items():
        for path in sorted((CORPUS_DIR / folder).iterdir()):
            if path.suffix.lower() in {".md", ".txt", ".pdf"}:
                docs.append(CorpusDoc(tenant_id, path, source_type_for(path.name)))
    return docs


def load_dataset(path: Path = DATASET) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]
