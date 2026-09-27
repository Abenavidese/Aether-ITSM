"""
What the knowledge base is (not) answering — for the admin dashboard (Fase 14.7).

Read from rag_queries (one row per search, src/rag/service.py) and
knowledge_documents, always in a tenant-scoped session.
"""
import json
from collections import Counter
from datetime import datetime, timedelta, timezone

from src.db.models import KnowledgeDocument, RagQueryLog
from src.db.tenant_scope import tenant_session


def knowledge_insights(tenant_id: str, days: int = 30, current_model: str | None = None) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    with tenant_session(tenant_id) as db:
        rows = (db.query(RagQueryLog)
                .filter(RagQueryLog.tenant_id == tenant_id, RagQueryLog.created_at >= since)
                .order_by(RagQueryLog.created_at.desc()).all())
        docs = db.query(KnowledgeDocument).filter(KnowledgeDocument.tenant_id == tenant_id).all()

        uses: Counter[str] = Counter()
        for row in rows:
            uses.update(json.loads(row.document_ids or "[]"))
        by_id = {d.id: d for d in docs}
        searchable = [d for d in docs if d.active_version]
        empty = [r for r in rows if r.passages == 0]
        durations = sorted(r.duration_ms for r in rows)
        return {
            "days": days,
            "searches": len(rows),
            "empty_rate": round(len(empty) / len(rows), 3) if rows else None,
            "latency_p50_ms": durations[len(durations) // 2] if durations else None,
            "top_documents": [
                {"id": doc_id, "filename": by_id[doc_id].filename, "uses": n}
                for doc_id, n in uses.most_common(5) if doc_id in by_id
            ],
            "unused_documents": [
                {"id": d.id, "filename": d.filename} for d in searchable if d.id not in uses
            ],
            # What people asked that the documentation doesn't cover: what to write next.
            "unanswered_questions": [
                {"query": r.query, "origin": r.origin, "at": r.created_at.isoformat() if r.created_at else None}
                for r in empty[:20]
            ],
            "documents": {
                "total": len(docs),
                "ready": sum(1 for d in docs if d.status == "ready"),
                "indexing": sum(1 for d in docs if d.status in ("queued", "indexing")),
                "failed": sum(1 for d in docs if d.status == "failed"),
                "pending_review": sum(1 for d in docs if d.status == "pending_review"),
                "stale": sum(1 for d in searchable if current_model and d.embedding_model != current_model),
            },
        }
