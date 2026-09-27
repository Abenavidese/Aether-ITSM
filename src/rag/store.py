"""
Knowledge-chunk store (Fase 14.1-14.2): the only module that queries
knowledge_chunks for search.

Every search runs in a tenant-scoped session (src/db/tenant_scope.py): the
WHERE tenant_id filter is in the code AND, with RLS on, enforced by Postgres
itself — the old langchain store searched on its own engine, outside RLS.

Three candidate generators, fused later by src/rag/retrieval.py:
- dense_search: cosine distance over pgvector, one partial HNSW index per
  embedding model (vectors of different models are never compared);
- keyword_search: full-text candidates (GIN index) scored with BM25 in
  Python — ts_rank has no IDF, so a chunk repeating the generic "error"
  would outrank the one containing the rare "kube";
- entity_search: passages containing an exact identifier (ERR_VPN_809,
  VITE_API_URL, 10.20.3.15).

On a non-Postgres database (SQLite dev/tests) the same functions score in
Python over the tenant's chunks: slower, identical semantics, so the app
and the tests don't need Postgres to exercise retrieval.
"""
import hashlib
import json
import logging
import math
from dataclasses import dataclass, field
from typing import Callable, ContextManager, Iterable

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.db.tenant_scope import tenant_session

from .text import PREFIX_MIN_LEN, entity_in, fold, to_tsquery

logger = logging.getLogger(__name__)

# pgvector index limits: HNSW over `vector` up to 2000 dimensions, over
# `halfvec` (half precision) up to 4000. Larger models are searched exactly.
_VECTOR_INDEX_MAX_DIM = 2000
_HALFVEC_INDEX_MAX_DIM = 4000
_HNSW_EF_SEARCH = 100
_BM25_K1, _BM25_B = 1.2, 0.75
_KEYWORD_CANDIDATES = 200

_COLUMNS = ("id, document_id, version, filename, section, page, chunk_index, source_type, content, "
            "chunk_metadata")


@dataclass(frozen=True)
class StoredChunk:
    id: str
    document_id: str
    version: int
    filename: str
    section: str
    page: int | None
    chunk_index: int
    source_type: str
    content: str
    metadata: dict = field(default_factory=dict, compare=False, hash=False)

    @classmethod
    def from_row(cls, row) -> "StoredChunk":
        m = row._mapping
        return cls(m["id"], m["document_id"], m["version"], m["filename"], m["section"] or "", m["page"],
                   m["chunk_index"], m["source_type"], m["content"],
                   json.loads(m["chunk_metadata"]) if m["chunk_metadata"] else {})


SessionFactory = Callable[[str], ContextManager[Session]]   # tenant_id -> scoped Session


def _is_postgres(db: Session) -> bool:
    return db.get_bind().dialect.name == "postgresql"


def _vector_type(dim: int) -> str:
    return "vector" if dim <= _VECTOR_INDEX_MAX_DIM else "halfvec"


def _vector_literal(values: Iterable[float]) -> str:
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


def vector_index_name(model: str) -> str:
    return "ix_knowledge_chunks_hnsw_" + hashlib.sha1(model.encode()).hexdigest()[:12]


def ensure_vector_index(engine: Engine, model: str, dim: int) -> None:
    """
    One partial HNSW index per embedding model, over a cast to its
    dimension (the column itself is dimensionless). Needs table ownership,
    so it runs on the app's own connection, never in a tenant session.
    """
    if engine.dialect.name != "postgresql" or dim > _HALFVEC_INDEX_MAX_DIM:
        if dim > _HALFVEC_INDEX_MAX_DIM:
            logger.warning("Embedding dimension %d > %d: '%s' is searched without an index",
                           dim, _HALFVEC_INDEX_MAX_DIM, model)
        return
    vtype = _vector_type(dim)
    ops = "vector_cosine_ops" if vtype == "vector" else "halfvec_cosine_ops"
    model_literal = model.replace("'", "''")
    with engine.connect() as conn:
        conn.execute(text(
            f"CREATE INDEX IF NOT EXISTS {vector_index_name(model)} ON knowledge_chunks "
            f"USING hnsw ((embedding::{vtype}({dim})) {ops}) WHERE embedding_model = '{model_literal}'"
        ))
        conn.commit()


class KnowledgeStore:
    def __init__(self, session_factory: SessionFactory = tenant_session):
        self._session = session_factory

    # ── dense ──────────────────────────────────────────────────────────────
    def dense_search(self, tenant_id: str, embedding: list[float], model: str, sources: list[str],
                     k: int) -> list[tuple[StoredChunk, float]]:
        with self._session(tenant_id) as db:
            if _is_postgres(db):
                return self._dense_postgres(db, tenant_id, embedding, model, sources, k)
            return self._dense_python(db, tenant_id, embedding, model, sources, k)

    def _dense_postgres(self, db, tenant_id, embedding, model, sources, k):
        dim = len(embedding)
        vtype = _vector_type(dim)
        # Filtered HNSW can return fewer than k rows; iterative scans
        # (pgvector >= 0.8) keep walking the graph until the filter is met.
        db.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
        db.execute(text(f"SET LOCAL hnsw.ef_search = {_HNSW_EF_SEARCH}"))
        distance = f"(embedding::{vtype}({dim}) <=> CAST(:q AS {vtype}({dim})))"
        rows = db.execute(text(
            f"SELECT {_COLUMNS}, {distance} AS distance FROM knowledge_chunks "
            "WHERE tenant_id = :tenant AND is_active AND embedding_model = :model AND source_type IN :sources "
            f"ORDER BY {distance} LIMIT :k"
        ).bindparams(bindparam("sources", expanding=True)),
            {"q": _vector_literal(embedding), "tenant": tenant_id, "model": model, "sources": list(sources), "k": k},
        ).fetchall()
        # relaxed_order may return rows slightly out of order.
        return sorted(((StoredChunk.from_row(r), float(r.distance)) for r in rows), key=lambda x: x[1])

    def _dense_python(self, db, tenant_id, embedding, model, sources, k):
        from src.db.models import KnowledgeChunk
        rows = (db.query(KnowledgeChunk)
                .filter(KnowledgeChunk.tenant_id == tenant_id, KnowledgeChunk.is_active.is_(True),
                        KnowledgeChunk.embedding_model == model, KnowledgeChunk.source_type.in_(list(sources)))
                .all())
        norm_q = math.sqrt(sum(x * x for x in embedding)) or 1.0
        scored = []
        for row in rows:
            vec = row.embedding or []
            if len(vec) != len(embedding):
                continue
            dot = sum(a * b for a, b in zip(vec, embedding, strict=True))
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            scored.append((_orm_chunk(row), 1.0 - dot / (norm * norm_q)))
        return sorted(scored, key=lambda x: x[1])[:k]

    # ── keyword (BM25) ─────────────────────────────────────────────────────
    def keyword_search(self, tenant_id: str, terms: list[str], sources: list[str],
                       k: int) -> list[tuple[StoredChunk, float]]:
        if not terms:
            return []
        with self._session(tenant_id) as db:
            if _is_postgres(db):
                candidates, df, total = self._keyword_candidates_postgres(db, tenant_id, terms, sources)
            else:
                candidates, df, total = self._keyword_candidates_python(db, tenant_id, terms, sources)
        return bm25_rank(candidates, terms, df, total)[:k]

    def _keyword_candidates_postgres(self, db, tenant_id, terms, sources):
        scope = ("tenant_id = :tenant AND is_active AND source_type IN :sources")
        params = {"tenant": tenant_id, "sources": list(sources), "tsq": to_tsquery(terms)}
        rows = db.execute(text(
            f"SELECT {_COLUMNS}, search_text FROM knowledge_chunks WHERE {scope} "
            "AND to_tsvector('simple', search_text) @@ to_tsquery('simple', :tsq) "
            "ORDER BY ts_rank_cd(to_tsvector('simple', search_text), to_tsquery('simple', :tsq)) DESC "
            f"LIMIT {_KEYWORD_CANDIDATES}"
        ).bindparams(bindparam("sources", expanding=True)), params).fetchall()
        # Document frequency per term over the tenant's active chunks, one query.
        counts = ", ".join(
            f"count(*) FILTER (WHERE to_tsvector('simple', search_text) @@ to_tsquery('simple', :t{i}))"
            for i in range(len(terms))
        )
        term_params = {f"t{i}": to_tsquery([t]) for i, t in enumerate(terms)}
        stats = db.execute(text(f"SELECT count(*), {counts} FROM knowledge_chunks WHERE {scope}")
                           .bindparams(bindparam("sources", expanding=True)), {**params, **term_params}).one()
        df = {t: int(stats[i + 1]) for i, t in enumerate(terms)}
        return [(StoredChunk.from_row(r), r.search_text) for r in rows], df, int(stats[0])

    def _keyword_candidates_python(self, db, tenant_id, terms, sources):
        from src.db.models import KnowledgeChunk
        rows = (db.query(KnowledgeChunk)
                .filter(KnowledgeChunk.tenant_id == tenant_id, KnowledgeChunk.is_active.is_(True),
                        KnowledgeChunk.source_type.in_(list(sources)))
                .all())
        docs = [(_orm_chunk(r), r.search_text) for r in rows]
        df = {t: sum(1 for _, st in docs if _term_tf(t, st.split())) for t in terms}
        return [d for d in docs if any(_term_tf(t, d[1].split()) for t in terms)], df, len(docs)

    # ── exact identifiers ──────────────────────────────────────────────────
    def entity_search(self, tenant_id: str, entities: list[str], sources: list[str],
                      k: int) -> list[StoredChunk]:
        if not entities:
            return []
        with self._session(tenant_id) as db:
            if _is_postgres(db):
                patterns = ["%" + e.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                            for e in entities]
                rows = db.execute(text(
                    f"SELECT {_COLUMNS} FROM knowledge_chunks WHERE tenant_id = :tenant AND is_active "
                    "AND source_type IN :sources AND content ILIKE ANY(:patterns) LIMIT 50"
                ).bindparams(bindparam("sources", expanding=True)),
                    {"tenant": tenant_id, "sources": list(sources), "patterns": patterns}).fetchall()
                chunks = [StoredChunk.from_row(r) for r in rows]
            else:
                from src.db.models import KnowledgeChunk
                chunks = [_orm_chunk(r) for r in db.query(KnowledgeChunk).filter(
                    KnowledgeChunk.tenant_id == tenant_id, KnowledgeChunk.is_active.is_(True),
                    KnowledgeChunk.source_type.in_(list(sources))).all()]
        # ILIKE is a prefilter; whole-token match decides ("e-12" is not in "e-125").
        matched = []
        for chunk in chunks:
            folded = fold(chunk.content)
            hits = sum(1 for e in entities if entity_in(e, folded))
            if hits:
                matched.append((hits, chunk))
        matched.sort(key=lambda x: -x[0])
        return [c for _, c in matched[:k]]

    # ── context expansion ──────────────────────────────────────────────────
    def neighbors(self, tenant_id: str, chunk: StoredChunk, radius: int = 1) -> list[StoredChunk]:
        """Chunks next to `chunk` in the same document version (small-to-big)."""
        with self._session(tenant_id) as db:
            rows = db.execute(text(
                f"SELECT {_COLUMNS} FROM knowledge_chunks WHERE tenant_id = :tenant AND document_id = :doc "
                "AND version = :version AND chunk_index BETWEEN :lo AND :hi ORDER BY chunk_index"
            ), {"tenant": tenant_id, "doc": chunk.document_id, "version": chunk.version,
                "lo": chunk.chunk_index - radius, "hi": chunk.chunk_index + radius}).fetchall()
        return [StoredChunk.from_row(r) for r in rows]


def _orm_chunk(row) -> StoredChunk:
    return StoredChunk(row.id, row.document_id, row.version, row.filename, row.section or "", row.page,
                       row.chunk_index, row.source_type, row.content,
                       json.loads(row.chunk_metadata) if row.chunk_metadata else {})


def _term_tf(term: str, tokens: list[str]) -> int:
    if len(term) >= PREFIX_MIN_LEN:
        return sum(1 for tok in tokens if tok.startswith(term))
    return sum(1 for tok in tokens if tok == term)


def bm25_rank(candidates: list[tuple[StoredChunk, str]], terms: list[str], df: dict[str, int],
              total_docs: int) -> list[tuple[StoredChunk, float]]:
    """Okapi BM25 over the candidates' normalized text (same scorer for both dialects)."""
    if not candidates:
        return []
    lengths = [len(st.split()) for _, st in candidates]
    avg_len = sum(lengths) / len(lengths) or 1.0
    scored = []
    for (chunk, search_text), length in zip(candidates, lengths, strict=True):
        tokens = search_text.split()
        score = 0.0
        for term in terms:
            tf = _term_tf(term, tokens)
            if not tf:
                continue
            n = df.get(term, 0)
            idf = math.log(1 + (total_docs - n + 0.5) / (n + 0.5))
            score += idf * tf * (_BM25_K1 + 1) / (tf + _BM25_K1 * (1 - _BM25_B + _BM25_B * length / avg_len))
        if score > 0:
            scored.append((chunk, round(score, 4)))
    return sorted(scored, key=lambda x: -x[1])
