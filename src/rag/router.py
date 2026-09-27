"""
Knowledge-base endpoints. Everything written here is later read by the
agents as prompt context, so uploads are validated (ingest_guard.py),
redacted and tagged (documents.py), rate-limited and audited (Fase 11.5).

Uploads return 202: parsing is quick and happens here (a bad file is
rejected immediately, with the reason), while chunking + embedding run in the
job queue (Fase 14.6) — the document's status goes queued -> indexing ->
ready/failed, and the previous version keeps answering meanwhile.
"""
import asyncio
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel, Field

from src.api.errors import internal_error
from src.config import get_settings
from src.db.models import User
from src.security.deps import get_current_user
from src.security.limiter import limiter, user_or_ip_key

from . import documents
from .embeddings import embedding_model_id
from .ingest_guard import SourceType, UploadRejected, discard, store_upload, validate_content
from .insights import knowledge_insights
from .parsing import DocumentParseError, parse_file
from .service import record_knowledge_event

logger = logging.getLogger(__name__)
settings = get_settings()

UPLOAD_DIR = "temp_uploads"
ADMIN_ROLES = ("admin", "superadmin")


class FeedbackRequest(BaseModel):
    ticket_id: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    feedback_text: str = Field(..., min_length=1, max_length=2000)


class ReviewRequest(BaseModel):
    approve: bool


class ReindexRequest(BaseModel):
    force: bool = False


router = APIRouter(prefix="/tenant/knowledge", tags=["knowledge"])


def _require_admin(user: User, message: str = "Only admins can modify the knowledge base.") -> None:
    if user.role not in ADMIN_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)


def _parse(path: str):
    try:
        return parse_file(path)
    except DocumentParseError as e:
        raise UploadRejected(422, str(e)) from e


@router.post("", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(settings.knowledge_rate_limit, key_func=user_or_ip_key)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    source_type: SourceType = Form(...),
    current_user: User = Depends(get_current_user),
):
    """Uploads a PDF, TXT or MD file; indexing continues in the background."""
    _require_admin(current_user)

    stored = None
    try:
        stored = await store_upload(file, UPLOAD_DIR, settings.knowledge_upload_max_bytes)
        # PDF parsing is blocking CPU work: worker thread, never the event loop.
        await asyncio.to_thread(validate_content, stored, settings.knowledge_upload_max_pdf_pages)
        parsed = await asyncio.to_thread(_parse, stored.path)
        outcome = await asyncio.to_thread(
            documents.register_upload, current_user.company_id, current_user.id, stored.filename,
            source_type.value, parsed, stored.size_bytes,
        )
    except UploadRejected as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e
    except Exception as e:
        raise internal_error(logger, "Failed to process document", e) from e
    finally:
        if stored:
            discard(stored.path)

    await asyncio.to_thread(
        record_knowledge_event, current_user.company_id, current_user.id, "upload", stored.filename,
        source_type=source_type.value, sha256=stored.sha256, size_bytes=stored.size_bytes,
    )
    return {
        "status": outcome.status,
        "document_id": outcome.document_id,
        "version": outcome.version,
        "unchanged": outcome.unchanged,
        "message": (f"{stored.filename} is unchanged — nothing to re-index." if outcome.unchanged
                    else f"{stored.filename} received; indexing in the background."),
        "warnings": list(outcome.warnings),
    }


@router.post("/feedback")
@limiter.limit(settings.knowledge_rate_limit, key_func=user_or_ip_key)
def submit_ai_feedback(request: Request, req: FeedbackRequest, current_user: User = Depends(get_current_user)):
    """Stores an admin correction for the agents — searchable only after review."""
    _require_admin(current_user, "Only admins can train AI.")
    try:
        outcome = documents.register_feedback(current_user.company_id, current_user.id, req.ticket_id,
                                              req.feedback_text)
    except Exception as e:
        raise internal_error(logger, "Failed to store feedback", e) from e
    record_knowledge_event(current_user.company_id, current_user.id, "feedback", f"Feedback_{req.ticket_id}",
                           source_type="ai_feedback")
    return {"status": outcome.status, "document_id": outcome.document_id,
            "message": "Feedback saved. It will be used by the AI once it is approved."}


@router.post("/{document_id}/review")
def review_feedback(document_id: str, req: ReviewRequest, current_user: User = Depends(get_current_user)):
    """Approves (-> indexed and searchable) or rejects a pending admin correction."""
    _require_admin(current_user)
    try:
        new_status = documents.review_feedback(current_user.company_id, document_id, current_user.id, req.approve)
    except documents.DocumentNotFound as e:
        raise HTTPException(status_code=404, detail="Feedback not found") from e
    record_knowledge_event(current_user.company_id, current_user.id, "approve" if req.approve else "reject",
                           document_id, source_type="ai_feedback")
    return {"status": new_status}


@router.post("/reindex")
def reindex(req: ReindexRequest, current_user: User = Depends(get_current_user)):
    """Re-indexes documents built with another embedding model/chunker (or all, with force)."""
    _require_admin(current_user)
    queued = documents.reindex_stale(current_user.company_id, embedding_model_id(), force=req.force)
    return {"queued": queued}


@router.get("/insights")
def insights(days: int = Query(30, ge=1, le=90), current_user: User = Depends(get_current_user)):
    """Searches, empty-result rate, most/never used documents, unanswered questions."""
    _require_admin(current_user, "Only admins can see knowledge insights.")
    try:
        return knowledge_insights(current_user.company_id, days, embedding_model_id())
    except Exception as e:
        raise internal_error(logger, "Failed to compute knowledge insights", e) from e


@router.get("")
def list_documents(current_user: User = Depends(get_current_user)):
    """Documents of the company's knowledge base, with their indexing status."""
    try:
        docs = documents.list_documents(current_user.company_id, embedding_model_id())
    except Exception as e:
        raise internal_error(logger, "Failed to list documents", e) from e
    if current_user.role not in ADMIN_ROLES:
        # Employees see what the assistant knows, not the admins' pending corrections.
        docs = [d for d in docs if d["source_type"] != "ai_feedback"]
    return docs


@router.delete("/{filename}")
def remove_document(filename: str, current_user: User = Depends(get_current_user)):
    """Removes a document (all versions and chunks) from the knowledge base."""
    _require_admin(current_user)
    try:
        deleted = documents.delete_document(current_user.company_id, filename)
    except Exception as e:
        raise internal_error(logger, "Failed to delete document", e) from e
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
    record_knowledge_event(current_user.company_id, current_user.id, "delete", filename[:200])
    return {"status": "success", "message": f"Deleted {filename}"}
