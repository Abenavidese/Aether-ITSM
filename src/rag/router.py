"""
Knowledge-base endpoints. Everything written here is later read by the
agents as prompt context, so uploads are validated (ingest_guard.py),
redacted and tagged (service.py), rate-limited and audited (Fase 11.5).
"""
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field

from src.api.errors import internal_error
from src.config import get_settings
from src.db.models import User
from src.rag.ingest_guard import SourceType, UploadRejected, discard, store_upload, validate_content
from src.rag.service import delete_file, get_uploaded_files, ingest_file, ingest_text, record_knowledge_event
from src.security.deps import get_current_user
from src.security.limiter import limiter, user_or_ip_key

logger = logging.getLogger(__name__)
settings = get_settings()

UPLOAD_DIR = "temp_uploads"


class FeedbackRequest(BaseModel):
    ticket_id: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    feedback_text: str = Field(..., min_length=1, max_length=2000)


router = APIRouter(prefix="/tenant/knowledge", tags=["knowledge"])


def _require_admin(user: User, message: str) -> None:
    if user.role not in ["admin", "superadmin"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)


@router.post("")
@limiter.limit(settings.knowledge_rate_limit, key_func=user_or_ip_key)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    source_type: SourceType = Form(...),
    current_user: User = Depends(get_current_user),
):
    """Uploads a PDF, TXT or MD file to the company's knowledge base."""
    _require_admin(current_user, "Only admins can modify knowledge base.")

    stored = None
    try:
        stored = await store_upload(file, UPLOAD_DIR, settings.knowledge_upload_max_bytes)
        validate_content(stored, settings.knowledge_upload_max_pdf_pages)
        report = ingest_file(
            tenant_id=current_user.company_id,
            file_path=stored.path,
            filename=stored.filename,
            source_type=source_type.value,
        )
    except UploadRejected as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        raise internal_error(logger, "Failed to process document", e)
    finally:
        if stored:
            discard(stored.path)

    record_knowledge_event(
        current_user.company_id, current_user.id, "upload", stored.filename, source_type=source_type.value,
        sha256=stored.sha256, size_bytes=stored.size_bytes, report=report,
    )
    return {
        "status": "success",
        "message": f"Successfully processed {stored.filename}",
        "chunks": report.chunks,
        # Surfaced to the admin who uploaded it: they know whether it's legit.
        "injection_flags": list(report.injection_flags),
    }


@router.post("/feedback")
@limiter.limit(settings.knowledge_rate_limit, key_func=user_or_ip_key)
def submit_ai_feedback(request: Request, req: FeedbackRequest, current_user: User = Depends(get_current_user)):
    """Saves human feedback to the RAG memory to teach the AI."""
    _require_admin(current_user, "Only admins can train AI.")

    try:
        # We prepend context to the feedback text
        contextual_feedback = f"Past correction on ticket {req.ticket_id}: {req.feedback_text}"
        report = ingest_text(
            tenant_id=current_user.company_id,
            text=contextual_feedback,
            source_id=req.ticket_id,
            source_type="ai_feedback"
        )
    except Exception as e:
        raise internal_error(logger, "Failed to store feedback", e)
    record_knowledge_event(current_user.company_id, current_user.id, "feedback", f"Feedback_{req.ticket_id}",
                           source_type="ai_feedback", report=report)
    return {"status": "success", "message": "Feedback ingested into AI memory."}


@router.get("")
def list_documents(current_user: User = Depends(get_current_user)):
    """Returns a list of documents in the company's knowledge base."""
    try:
        return get_uploaded_files(current_user.company_id)
    except Exception as e:
        raise internal_error(logger, "Failed to list documents", e)


@router.delete("/{filename}")
def remove_document(filename: str, current_user: User = Depends(get_current_user)):
    """Removes a document from the company's knowledge base."""
    _require_admin(current_user, "Only admins can modify knowledge base.")

    try:
        delete_file(current_user.company_id, filename)
    except Exception as e:
        raise internal_error(logger, "Failed to delete document", e)
    record_knowledge_event(current_user.company_id, current_user.id, "delete", filename[:200])
    return {"status": "success", "message": f"Deleted {filename}"}
