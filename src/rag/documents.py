"""
Knowledge-base document lifecycle (Fase 14.1 / 14.6): register, index,
review, re-index, delete. Synchronous DB work; async callers use
asyncio.to_thread.

    upload ──> register_upload ──(same text as before?)──> unchanged, nothing to do
                    │ new content: version+1, status=queued, INDEX_DOCUMENT job
                    │ (same transaction — never a document without its job)
                    v
               index_version (queue worker): chunk -> redact -> embed in batches
                    -> insert as INACTIVE chunks -> flip active version in one
                    transaction. Until then the previous version keeps answering.

    admin feedback ──> register_feedback (pending_review, never searched)
                    ──> review_feedback(approve) ──> queued -> indexed

A re-upload racing an index job is safe: the job checks it is still indexing
the latest version, and the flip only ever activates the version it built.
"""
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text

from src.db.models import KnowledgeChunk, KnowledgeDocument
from src.db.tenant_scope import tenant_session
from src.jobs.queue import JobKind, enqueue
from src.security.prompt_safety import find_injection_markers
from src.security.redaction import redact_document

from .chunking import CHUNKER_VERSION, chunk_document
from .parsing import ParsedDocument
from .text import search_text

logger = logging.getLogger(__name__)

EMBED_BATCH_SIZE = 32

QUEUED, INDEXING, READY, FAILED = "queued", "indexing", "ready", "failed"
PENDING_REVIEW, REJECTED = "pending_review", "rejected"


class DocumentNotFound(Exception):
    pass


@dataclass(frozen=True)
class RegisterOutcome:
    document_id: str
    version: int
    status: str
    unchanged: bool
    warnings: tuple[str, ...] = ()


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _enqueue_index(db, doc: KnowledgeDocument) -> None:
    enqueue(db, JobKind.INDEX_DOCUMENT,
            {"tenant_id": doc.tenant_id, "document_id": doc.id, "version": doc.latest_version},
            dedupe_key=f"rag-index:{doc.id}:{doc.latest_version}", max_attempts=4)


def register_upload(tenant_id: str, user_id: str | None, filename: str, source_type: str,
                    parsed: ParsedDocument, size_bytes: int | None = None) -> RegisterOutcome:
    """Records a new version of `filename` and queues its indexing — unless the text is identical."""
    digest = _sha256(parsed.text)
    with tenant_session(tenant_id) as db:
        doc = db.query(KnowledgeDocument).filter_by(tenant_id=tenant_id, filename=filename).first()
        if doc and doc.sha256 == digest and doc.source_type == source_type and doc.status in (QUEUED, INDEXING, READY):
            return RegisterOutcome(doc.id, doc.latest_version, doc.status, unchanged=True,
                                   warnings=tuple(json.loads(doc.warnings or "[]")))
        if doc is None:
            doc = KnowledgeDocument(tenant_id=tenant_id, filename=filename, latest_version=1, created_by=user_id)
            db.add(doc)
        else:
            doc.latest_version += 1
        doc.source_type = source_type
        doc.status = QUEUED
        doc.sha256 = digest
        doc.content = parsed.text
        doc.page_map = json.dumps(parsed.page_offsets) if parsed.page_offsets else None
        doc.size_bytes = size_bytes
        doc.pages = parsed.pages
        doc.warnings = json.dumps(parsed.warnings) if parsed.warnings else None
        doc.error = None
        db.flush()
        _enqueue_index(db, doc)
        db.commit()
        return RegisterOutcome(doc.id, doc.latest_version, doc.status, unchanged=False,
                               warnings=tuple(parsed.warnings))


def register_feedback(tenant_id: str, user_id: str, ticket_id: str, feedback_text: str) -> RegisterOutcome:
    """
    Admin correction for the agents. It is NOT searchable until another
    admin (or the same one, deliberately) approves it: unreviewed free text
    went straight into the execution prompt before (Fase 14.6).
    """
    content = f"Corrección sobre el ticket {ticket_id}:\n\n{feedback_text}"
    filename = f"Feedback_{ticket_id}"
    with tenant_session(tenant_id) as db:
        doc = db.query(KnowledgeDocument).filter_by(tenant_id=tenant_id, filename=filename).first()
        if doc is None:
            doc = KnowledgeDocument(tenant_id=tenant_id, filename=filename, latest_version=1)
            db.add(doc)
        else:
            doc.latest_version += 1
        doc.source_type = "ai_feedback"
        doc.status = PENDING_REVIEW
        doc.content = content
        doc.sha256 = _sha256(content)
        doc.created_by = user_id
        doc.reviewed_by = None
        doc.error = None
        db.commit()
        return RegisterOutcome(doc.id, doc.latest_version, doc.status, unchanged=False)


def review_feedback(tenant_id: str, document_id: str, reviewer_id: str, approve: bool) -> str:
    with tenant_session(tenant_id) as db:
        doc = db.query(KnowledgeDocument).filter_by(tenant_id=tenant_id, id=document_id,
                                                    source_type="ai_feedback").first()
        if doc is None:
            raise DocumentNotFound(document_id)
        if doc.status != PENDING_REVIEW:
            return doc.status
        doc.reviewed_by = reviewer_id
        if approve:
            doc.status = QUEUED
            _enqueue_index(db, doc)
        else:
            doc.status = REJECTED
        db.commit()
        return doc.status


def _chunk_metadata(doc: KnowledgeDocument, chunk_meta: dict, reviewer_name: str | None) -> dict:
    meta = {}
    if chunk_meta.get("injection_flags"):
        meta["injection_flags"] = chunk_meta["injection_flags"]
    if doc.source_type == "ai_feedback":
        date = (doc.updated_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
        meta["note"] = f"corrección aprobada por {reviewer_name or 'un admin'} el {date}"
    return meta


def index_version(tenant_id: str, document_id: str, version: int, embeddings, embedding_model: str,
                  engine=None) -> str:
    """
    Builds `version` of a document and makes it the searchable one. Returns
    the outcome ("ready", "superseded", "skipped"). Idempotent: a retry
    discards whatever a previous attempt of the same version inserted.
    Exceptions propagate (the queue retries, then marks the document failed).
    """
    from src.db.models import User
    from src.rag.store import ensure_vector_index

    with tenant_session(tenant_id) as db:
        doc = db.query(KnowledgeDocument).filter_by(tenant_id=tenant_id, id=document_id).first()
        if doc is None:
            return "skipped"
        if doc.latest_version != version:
            return "superseded"
        if doc.status in (PENDING_REVIEW, REJECTED):
            return "skipped"
        doc.status = INDEXING
        db.commit()
        content, filename, source_type = doc.content or "", doc.filename, doc.source_type
        page_offsets = [tuple(p) for p in json.loads(doc.page_map)] if doc.page_map else None
        reviewer = db.get(User, doc.reviewed_by) if doc.reviewed_by else None
        reviewer_name = reviewer.full_name if reviewer else None

    # Secrets out BEFORE embedding: once in the store, any question landing
    # near that chunk would hand the secret to the model.
    chunks = chunk_document(redact_document(content), filename, page_offsets=page_offsets,
                            base_metadata={"tenant_id": tenant_id, "source_type": source_type})
    flags: set[str] = set()
    for chunk in chunks:
        markers = find_injection_markers(chunk.page_content)
        if markers:
            chunk.metadata["injection_flags"] = ",".join(markers)
            flags.update(markers)
    if flags:
        logger.warning("Possible prompt injection in knowledge doc '%s' (tenant %s): %s",
                       filename, tenant_id, sorted(flags))

    vectors: list[list[float]] = []
    for start in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch = [c.page_content for c in chunks[start:start + EMBED_BATCH_SIZE]]
        vectors.extend(embeddings.embed_documents(batch))
    dim = len(vectors[0]) if vectors else None

    with tenant_session(tenant_id) as db:
        doc = db.query(KnowledgeDocument).filter_by(tenant_id=tenant_id, id=document_id).first()
        if doc is None:
            return "skipped"
        if doc.latest_version != version:
            return "superseded"
        db.query(KnowledgeChunk).filter_by(document_id=document_id, version=version).delete()
        meta_note = {c.metadata.get("chunk_index"): _chunk_metadata(doc, c.metadata, reviewer_name) for c in chunks}
        db.add_all([
            KnowledgeChunk(
                tenant_id=tenant_id, document_id=document_id, version=version, is_active=False,
                source_type=source_type, filename=filename, section=c.metadata.get("section") or None,
                page=c.metadata.get("page"), chunk_index=c.metadata["chunk_index"], content=c.page_content,
                search_text=search_text(c.page_content), embedding=vec, embedding_model=embedding_model,
                chunk_metadata=json.dumps(meta_note[c.metadata["chunk_index"]]) if meta_note[c.metadata["chunk_index"]] else None,
            )
            for c, vec in zip(chunks, vectors, strict=True)  # a provider returning fewer vectors fails loudly
        ])
        db.commit()

    if dim and engine is not None:
        ensure_vector_index(engine, embedding_model, dim)

    # The flip: one transaction activates this version and drops the others.
    with tenant_session(tenant_id) as db:
        doc = db.query(KnowledgeDocument).filter_by(tenant_id=tenant_id, id=document_id).with_for_update().first()
        if doc is None or doc.latest_version != version:
            db.query(KnowledgeChunk).filter_by(document_id=document_id, version=version).delete()
            db.commit()
            return "superseded"
        db.execute(text("UPDATE knowledge_chunks SET is_active = (version = :v) WHERE document_id = :d"),
                   {"v": version, "d": document_id})
        db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == document_id,
                                        KnowledgeChunk.version != version).delete()
        warnings = [w for w in json.loads(doc.warnings or "[]") if not w.startswith("Posible inyección")]
        if flags:
            warnings.append("Posible inyección de instrucciones detectada: " + ", ".join(sorted(flags)))
        doc.warnings = json.dumps(warnings) if warnings else None
        doc.active_version = version
        doc.status = READY
        doc.chunk_count = len(chunks)
        doc.embedding_model = embedding_model
        doc.embedding_dim = dim
        doc.chunker_version = CHUNKER_VERSION
        doc.indexed_at = datetime.now(timezone.utc)
        doc.error = None
        db.commit()
    return READY


def mark_failed(tenant_id: str, document_id: str, version: int, error: str) -> None:
    with tenant_session(tenant_id) as db:
        doc = db.query(KnowledgeDocument).filter_by(tenant_id=tenant_id, id=document_id).first()
        if doc is None or doc.latest_version != version:
            return
        doc.status = FAILED
        doc.error = error[:500]
        db.query(KnowledgeChunk).filter_by(document_id=document_id, version=version, is_active=False).delete()
        db.commit()


def document_view(doc: KnowledgeDocument, current_model: str) -> dict:
    stale = bool(doc.active_version) and (doc.embedding_model != current_model or
                                          doc.chunker_version != CHUNKER_VERSION)
    return {
        "id": doc.id, "filename": doc.filename, "source_type": doc.source_type, "status": doc.status,
        "version": doc.latest_version, "active_version": doc.active_version, "chunks": doc.chunk_count,
        "pages": doc.pages, "size_bytes": doc.size_bytes, "embedding_model": doc.embedding_model,
        "warnings": json.loads(doc.warnings or "[]"), "error": doc.error, "stale": stale,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "indexed_at": doc.indexed_at.isoformat() if doc.indexed_at else None,
        # Feedback shows its text so the reviewer knows what they approve.
        "content": doc.content if doc.source_type == "ai_feedback" else None,
    }


def list_documents(tenant_id: str, current_model: str) -> list[dict]:
    with tenant_session(tenant_id) as db:
        docs = (db.query(KnowledgeDocument).filter_by(tenant_id=tenant_id)
                .order_by(KnowledgeDocument.created_at.desc()).all())
        return [document_view(d, current_model) for d in docs]


def delete_document(tenant_id: str, filename: str) -> bool:
    with tenant_session(tenant_id) as db:
        doc = db.query(KnowledgeDocument).filter_by(tenant_id=tenant_id, filename=filename).first()
        if doc is None:
            return False
        db.query(KnowledgeChunk).filter_by(document_id=doc.id).delete()
        db.delete(doc)
        db.commit()
        return True


def reindex_stale(tenant_id: str, current_model: str, *, force: bool = False) -> int:
    """
    Queues a new version (same stored text) for every document indexed with
    another embedding model or chunker — or all ready documents with force.
    Until each finishes, its old version keeps answering (keyword search;
    dense search only compares same-model vectors).
    """
    queued = 0
    with tenant_session(tenant_id) as db:
        for doc in db.query(KnowledgeDocument).filter_by(tenant_id=tenant_id).all():
            if doc.status not in (READY, FAILED) or not doc.content:
                continue
            if not force and doc.active_version and doc.embedding_model == current_model \
                    and doc.chunker_version == CHUNKER_VERSION:
                continue
            doc.latest_version += 1
            doc.status = QUEUED
            db.flush()
            _enqueue_index(db, doc)
            queued += 1
        db.commit()
    return queued
