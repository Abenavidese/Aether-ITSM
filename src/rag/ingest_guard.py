"""
Validation for knowledge-base uploads before anything is parsed or embedded
(Fase 11.5). Everything here is a pure check on the upload itself; the
router decides what HTTP status each rejection becomes.

Found in the Fase 11 audit: the upload path was built with
os.path.join(UPLOAD_DIR, file.filename) — the client's filename — so
"../src/main.py" overwrote that file and the cleanup step then DELETED it.
Now the bytes land under a random name and the original name is only
metadata, after sanitize_filename().
"""
import hashlib
import os
import re
import uuid
from dataclasses import dataclass
from enum import Enum

ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md"}
_MAX_FILENAME_CHARS = 120
_CHUNK_BYTES = 64 * 1024


class SourceType(str, Enum):
    """What an admin may upload as. "ai_feedback" is written only by /feedback."""
    COMPANY_POLICY = "company_policy"
    TECHNICAL_REPO = "technical_repo"


class UploadRejected(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class StoredUpload:
    path: str        # server-side temp path (random name)
    filename: str    # sanitized original name, metadata only
    extension: str
    sha256: str
    size_bytes: int


def sanitize_filename(raw: str | None) -> str:
    """Basename only, conservative charset, bounded length, allowed extension."""
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[^\w .()-]", "_", name).strip(" .")
    stem, ext = os.path.splitext(name)
    ext = ext.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise UploadRejected(400, f"Only {', '.join(sorted(ALLOWED_EXTENSIONS))} files are supported.")
    stem = stem[: _MAX_FILENAME_CHARS - len(ext)] or "document"
    return stem + ext


async def store_upload(upload, dest_dir: str, max_bytes: int) -> StoredUpload:
    """
    Streams the upload to `dest_dir` under a random name, enforcing the size
    limit WHILE reading (never trusting a Content-Length header).
    """
    filename = sanitize_filename(upload.filename)
    extension = os.path.splitext(filename)[1]
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, f"{uuid.uuid4().hex}{extension}")
    digest, size = hashlib.sha256(), 0
    try:
        with open(path, "wb") as out:
            while chunk := await upload.read(_CHUNK_BYTES):
                size += len(chunk)
                if size > max_bytes:
                    raise UploadRejected(413, f"File exceeds the {max_bytes // (1024 * 1024)} MB limit.")
                digest.update(chunk)
                out.write(chunk)
    except BaseException:
        discard(path)
        raise
    if size == 0:
        discard(path)
        raise UploadRejected(400, "The file is empty.")
    return StoredUpload(path, filename, extension, digest.hexdigest(), size)


def validate_content(stored: StoredUpload, max_pdf_pages: int) -> None:
    """The bytes must really be what the extension claims."""
    with open(stored.path, "rb") as f:
        head = f.read(1024)
    if stored.extension == ".pdf":
        if not head.startswith(b"%PDF-"):
            raise UploadRejected(400, "The file is not a valid PDF.")
        from pypdf import PdfReader
        try:
            reader = PdfReader(stored.path)
            if reader.is_encrypted:
                raise UploadRejected(400, "Encrypted PDFs are not supported.")
            pages = len(reader.pages)
        except UploadRejected:
            raise
        except Exception as e:
            raise UploadRejected(400, "The PDF could not be parsed.") from e
        if pages > max_pdf_pages:
            raise UploadRejected(413, f"The PDF has {pages} pages; the limit is {max_pdf_pages}.")
        return
    with open(stored.path, "rb") as f:
        data = f.read()
    if b"\x00" in data:
        raise UploadRejected(400, "Text files must not contain binary data.")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise UploadRejected(400, "Text files must be UTF-8.") from e


def discard(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
