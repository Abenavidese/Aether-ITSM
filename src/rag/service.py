"""
The knowledge base as the rest of the app sees it (Fase 14).

- retrieve(): the full pipeline (src/rag/retrieval.py) plus what a product
  needs around it — a trace span with stage timings and chunk ids/scores,
  a query-log row for the admin insights, and degradation: a retrieval
  failure returns an empty result (the agent answers without context and
  says so) instead of failing the chat turn.
- retrieve_context(): the same, flattened to prompt text, for the ticket
  graph's nodes.
- Document lifecycle lives in src/rag/documents.py; parsing in parsing.py.

The Retriever is built once per process (embedding client, reranker model
and query-embedding cache are reused), under a lock: the Concierge's first
turns run retrievals in parallel threads.
"""
import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from src.config import get_settings
from src.observability.tracing import current_trace, record_span

from .query import QueryPlan, llm_rewriter
from .rerank import get_reranker
from .retrieval import QueryEmbedder, RetrievalConfig, RetrievalResult, Retriever
from .store import KnowledgeStore

logger = logging.getLogger(__name__)

POLICY, TECHNICAL, FEEDBACK = "company_policy", "technical_repo", "ai_feedback"
_QUERY_LOG_CHARS = 300

_retriever: Retriever | None = None
_retriever_lock = threading.Lock()


def build_retriever(settings=None, *, store: KnowledgeStore | None = None, embeddings=None,
                    model_id: str | None = None, reranker=None) -> Retriever:
    from .embeddings import embedding_model_id, get_embeddings

    settings = settings or get_settings()
    config = RetrievalConfig(
        top_k=settings.rag_top_k, candidates=settings.rag_candidates, max_distance=settings.rag_max_distance,
        min_rerank_score=settings.rag_rerank_min_score, context_chars=settings.rag_context_chars,
        rewrite_mode=settings.rag_rewrite_mode,
    )
    rewriter = None
    if config.rewrite_mode == "llm":
        from src.config import get_llms
        rewriter = llm_rewriter(get_llms()[0])
    return Retriever(
        store or KnowledgeStore(),
        QueryEmbedder(embeddings or get_embeddings(), model_id or embedding_model_id()),
        reranker=reranker if reranker is not None else get_reranker(settings.rag_reranker),
        config=config, rewriter=rewriter,
    )


def get_retriever() -> Retriever:
    global _retriever
    if _retriever is None:
        with _retriever_lock:
            if _retriever is None:
                _retriever = build_retriever()
    return _retriever


def _span_attributes(result: RetrievalResult, origin: str) -> dict:
    return {
        "origin": origin,
        "rewritten": result.plan.rewritten, "rewrite_mode": result.plan.mode,
        "entities": len(result.plan.entities),
        "reranker": result.reranker, "rerank": result.rerank_reason,
        "embedding_model": result.embedding_model,
        "stages_ms": result.timings_ms,
        "candidates": [{"id": c.chunk.id, "score": c.score, "dense": c.distance is not None,
                        "keyword": c.keyword is not None, "entity": c.entity} for c in result.candidates[:10]],
        "passages": [{"n": p.n, "chunks": p.chunk_ids, "score": p.score} for p in result.passages],
        "empty": result.empty,
    }


def _log_query(tenant_id: str, query: str, result: RetrievalResult, origin: str, duration_ms: int) -> None:
    from src.db.models import RagQueryLog
    from src.db.tenant_scope import tenant_session
    from src.security.redaction import redact_document

    trace = current_trace()
    if trace is not None and trace.source == "eval":
        return  # eval runs use a synthetic tenant and must leave no rows behind
    with tenant_session(tenant_id) as db:
        db.add(RagQueryLog(
            tenant_id=tenant_id, trace_id=trace.trace_id if trace else None, origin=origin,
            query=redact_document(query)[:_QUERY_LOG_CHARS], rewritten=result.plan.rewritten,
            passages=len(result.passages), top_score=result.top_score,
            document_ids=json.dumps(sorted({p.document_id for p in result.passages})), duration_ms=duration_ms,
        ))
        db.commit()


def retrieve(tenant_id: str, query: str, *, sources: list[str], history: list[str] | None = None,
             origin: str = "chat", top_k: int | None = None, retriever: Retriever | None = None) -> RetrievalResult:
    started, started_at = time.perf_counter(), datetime.now(timezone.utc)
    status = "ok"
    try:
        result = (retriever or get_retriever()).retrieve(tenant_id, query, sources=sources, history=history,
                                                         top_k=top_k)
    except Exception as e:
        # Degrade, don't fail: the agent is told there's no context and says so.
        logger.error("Knowledge retrieval failed for tenant %s: %s", tenant_id, e, exc_info=True)
        status = "error"
        result = RetrievalResult(plan=QueryPlan(original=query, semantic=query, terms=[], entities=[]))
    duration_ms = int((time.perf_counter() - started) * 1000)
    record_span("retrieval", f"rag:{origin}", duration_ms, started_at, status=status,
                attributes=_span_attributes(result, origin))
    if status == "ok":
        try:
            _log_query(tenant_id, query, result, origin, duration_ms)
        except Exception:
            logger.warning("Could not write the RAG query log", exc_info=True)
    return result


def retrieve_context(tenant_id: str, query: str, source_type: str = POLICY, top_k: int | None = None) -> str:
    """Numbered passages as prompt text (ticket graph nodes)."""
    return retrieve(tenant_id, query, sources=[source_type], origin="ticket", top_k=top_k).to_prompt()


def purge_query_log(retention_days: int | None = None) -> int:
    """Deletes query-log rows older than the retention (called by the indexing job, cheap)."""
    from src.db.database import SessionLocal
    from src.db.models import RagQueryLog

    days = retention_days or get_settings().rag_query_log_retention_days
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    db = SessionLocal()
    try:
        deleted = db.query(RagQueryLog).filter(RagQueryLog.created_at < cutoff).delete()
        db.commit()
        return deleted
    finally:
        db.close()


def record_knowledge_event(tenant_id: str, user_id: str | None, action: str, filename: str, *,
                           source_type: str | None = None, sha256: str | None = None,
                           size_bytes: int | None = None, chunks: int | None = None,
                           injection_flags: str | None = None) -> None:
    """Audit trail for every change to what the agents will read (see KnowledgeAudit)."""
    from src.db.database import SessionLocal
    from src.db.models import KnowledgeAudit
    db = SessionLocal()
    try:
        db.add(KnowledgeAudit(
            tenant_id=tenant_id, user_id=user_id, action=action, filename=filename,
            source_type=source_type, sha256=sha256, size_bytes=size_bytes, chunks=chunks,
            injection_flags=injection_flags,
        ))
        db.commit()
    finally:
        db.close()
