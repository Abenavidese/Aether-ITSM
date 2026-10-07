"""
Systems under test for the RAG eval. Each one indexes the corpus into the
eval database and answers `search(query, history)` with the passages that
would reach the model (after its relevance gate) plus the ranked candidates
before the gate.

- LegacySystem: the pre-Fase-14 pipeline, reproduced as it ran in the
  Concierge (langchain PGVector, two dense searches of top 4 — policies and
  technical docs — cut at a fixed cosine distance, history ignored). Kept to
  measure the baseline; it goes away with langchain-postgres.
- CurrentSystem: the product's pipeline (src/rag), same code the app runs:
  parsing, versioned indexing, hybrid search, reranking, context assembly.
  Options switch parts off for ablations (keyword=off, entity=off, ...).

Both expect DATABASE_URL to already point at the eval database (run.py sets
it before anything imports src.*).
"""
import time
from contextlib import contextmanager
from dataclasses import dataclass

from .corpus import MAIN_TENANT, OTHER_TENANT, CorpusDoc
from .metrics import Hit


@dataclass
class SearchOutcome:
    passages: list[Hit]
    candidates: list[Hit]
    context_chars: int
    latency_ms: float


class LegacySystem:
    name = "legacy"
    SOURCES = ("company_policy", "technical_repo")

    def __init__(self, database_url: str, max_distance: float = 0.40, top_k: int = 4):
        from langchain_postgres import PGVector

        from src.rag.embeddings import get_embeddings

        self.store = PGVector(embeddings=get_embeddings(), collection_name="rag_eval_legacy",
                              connection=database_url, use_jsonb=True, pre_delete_collection=True)
        self.max_distance = max_distance
        self.top_k = top_k

    def index(self, docs: list[CorpusDoc]) -> None:
        from langchain_community.document_loaders import PyPDFLoader, TextLoader

        from src.rag.chunking import chunk_document
        from src.security.redaction import redact_document

        for doc in docs:
            if doc.path.suffix.lower() == ".pdf":
                pages = PyPDFLoader(str(doc.path)).load()
                offsets, parts, offset = [], [], 0
                for n, page in enumerate(pages, start=1):
                    offsets.append((offset, n))
                    parts.append(page.page_content)
                    offset += len(page.page_content) + 2
                text, page_offsets = "\n\n".join(parts), offsets
            else:
                text, page_offsets = TextLoader(str(doc.path), encoding="utf-8").load()[0].page_content, None
            chunks = chunk_document(redact_document(text), doc.filename, page_offsets=page_offsets,
                                    base_metadata={"tenant_id": doc.tenant_id, "source_type": doc.source_type})
            self.store.add_documents(chunks)

    def search(self, tenant_id: str, query: str, history: list[str]) -> SearchOutcome:
        started = time.perf_counter()
        passages, candidates, chars = [], [], 0
        for source in self.SOURCES:
            flt = {"tenant_id": tenant_id, "source_type": source}
            # One query of 10: its first top_k are exactly what a top_k query
            # returns (no vector index -> exact scan), so latency isn't doubled.
            ranked = self.store.similarity_search_with_score(query, k=10, filter=flt)
            candidates += [(distance, doc) for doc, distance in ranked]
            for doc, distance in ranked[:self.top_k]:
                if distance <= self.max_distance:
                    passages.append((distance, doc))
                    chars += len(doc.page_content)
        latency = (time.perf_counter() - started) * 1000

        def to_hits(scored):
            return [Hit(d.metadata.get("filename", ""), d.metadata.get("section", ""),
                        d.metadata.get("tenant_id", ""), round(dist, 4))
                    for dist, d in sorted(scored, key=lambda x: x[0])]

        return SearchOutcome(to_hits(passages), to_hits(candidates), chars, latency)


_FLOAT_OPTIONS = {"max_distance", "min_rerank_score", "entity_weight"}
_INT_OPTIONS = {"top_k", "candidates", "neighbor_radius", "context_chars", "rrf_k"}


class _AblatedStore:
    """Wraps KnowledgeStore to switch candidate generators off (ablation runs)."""

    def __init__(self, inner, keyword: bool, entity: bool, dense: bool):
        self._inner, self._keyword, self._entity, self._dense = inner, keyword, entity, dense

    def dense_search(self, *args, **kwargs):
        return self._inner.dense_search(*args, **kwargs) if self._dense else []

    def keyword_search(self, *args, **kwargs):
        return self._inner.keyword_search(*args, **kwargs) if self._keyword else []

    def entity_search(self, *args, **kwargs):
        return self._inner.entity_search(*args, **kwargs) if self._entity else []

    def neighbors(self, *args, **kwargs):
        return self._inner.neighbors(*args, **kwargs)


class CurrentSystem:
    name = "current"
    SOURCES = ["company_policy", "technical_repo"]

    def __init__(self, database_url: str, **options: str):
        from src.db.database import SessionLocal, engine
        from src.rag.rerank import get_reranker
        from src.rag.retrieval import RetrievalConfig
        from src.rag.service import build_retriever
        from src.rag.store import KnowledgeStore

        self.engine = engine
        if str(engine.url.render_as_string(hide_password=False)) != database_url.replace("postgres://", "postgresql://", 1):
            raise RuntimeError("DATABASE_URL must point at the eval database before src is imported")

        @contextmanager
        def plain_session(tenant_id: str):
            db = SessionLocal()
            try:
                yield db
            finally:
                db.close()

        on = lambda key: options.get(key, "on") != "off"  # noqa: E731
        store = _AblatedStore(KnowledgeStore(plain_session), on("keyword"), on("entity"), on("dense"))
        retriever = build_retriever(store=store, reranker=get_reranker(options.get("reranker", "none")))
        config: RetrievalConfig = retriever.config
        config.rewrite_mode = options.get("rewrite", config.rewrite_mode)
        for key, value in options.items():
            if key in _FLOAT_OPTIONS:
                setattr(config, key, float(value))
            elif key in _INT_OPTIONS:
                setattr(config, key, int(value))
        if config.rewrite_mode == "llm" and retriever.rewriter is None:
            from src.llm.factory import get_llms
            from src.rag.query import llm_rewriter
            retriever.rewriter = llm_rewriter(get_llms()[0])
        self.retriever = retriever
        self.doc_tenant: dict[str, str] = {}

    def index(self, docs: list[CorpusDoc]) -> None:
        from sqlalchemy import text

        from src.db.database import SessionLocal
        from src.db.migrate import upgrade_to_head
        from src.db.models import Company, Job, KnowledgeChunk, KnowledgeDocument
        from src.rag.documents import index_version, register_upload
        from src.rag.parsing import parse_file

        upgrade_to_head(self.engine)
        db = SessionLocal()
        try:
            for tenant_id in (MAIN_TENANT, OTHER_TENANT):
                if db.get(Company, tenant_id) is None:
                    db.add(Company(id=tenant_id, name=tenant_id))
            db.commit()
            for tenant_id in (MAIN_TENANT, OTHER_TENANT):
                db.query(KnowledgeChunk).filter_by(tenant_id=tenant_id).delete()
                db.query(KnowledgeDocument).filter_by(tenant_id=tenant_id).delete()
            db.query(Job).filter(Job.kind == "index_document").delete()
            db.commit()
        finally:
            db.close()

        embeddings = self.retriever.embedder._embeddings
        model_id = self.retriever.embedder.model_id
        for doc in docs:
            parsed = parse_file(doc.path)
            outcome = register_upload(doc.tenant_id, None, doc.filename, doc.source_type, parsed)
            index_version(doc.tenant_id, outcome.document_id, outcome.version, embeddings, model_id, self.engine)
            self.doc_tenant[outcome.document_id] = doc.tenant_id
        with self.engine.connect() as conn:
            conn.execute(text("DELETE FROM jobs WHERE kind = 'index_document'"))
            conn.commit()

    def _load_doc_tenants(self) -> None:
        from sqlalchemy import text
        with self.engine.connect() as conn:
            self.doc_tenant = dict(conn.execute(text("SELECT id, tenant_id FROM knowledge_documents")).fetchall())

    def search(self, tenant_id: str, query: str, history: list[str]) -> SearchOutcome:
        if not self.doc_tenant:
            self._load_doc_tenants()
        started = time.perf_counter()
        result = self.retriever.retrieve(tenant_id, query, sources=self.SOURCES, history=history)
        latency = (time.perf_counter() - started) * 1000
        passages = [Hit(p.filename, p.section, self.doc_tenant.get(p.document_id, "?"), p.score)
                    for p in result.passages]
        candidates = [Hit(c.chunk.filename, c.chunk.section, self.doc_tenant.get(c.chunk.document_id, "?"), c.score)
                      for c in result.candidates]
        return SearchOutcome(passages, candidates, sum(len(p.text) for p in result.passages), latency)
