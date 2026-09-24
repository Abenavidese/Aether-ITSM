"""
Vercel via Log Drain (Fase 10.11).

Why a drain instead of Vercel's pull API: runtime logs are kept 1 hour on
Hobby / 1 day on Pro, and the runtime-logs REST endpoint is streaming-only
with community reports of it hanging. So Vercel PUSHES logs to us
(POST /api/integrations/vercel/drain/{tenant_id}), we keep a short-retention,
already-redacted copy in platform_logs, and VercelDrainLogProvider reads that
table — the agent uses the same LogProvider interface as Render.

Still read-only toward Vercel: we never call Vercel's API at all.
"""
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone

from src.config import get_settings
from src.db.database import SessionLocal
from src.db.models import PlatformLog

from .base import LogEntry, ServiceRef, ServiceState, infer_level
from .sanitize import redact

logger = logging.getLogger(__name__)

_MAX_ENTRIES_PER_DELIVERY = 2000
_MAX_MESSAGE_CHARS = 4000


def normalize_project_id(project_id: str | None) -> str:
    return (project_id or "").removeprefix("prj_")


def verify_signature(raw_body: bytes, secret: str, signature: str | None) -> bool:
    """HMAC-SHA1 hex of the raw body, as Vercel documents, compared in
    constant time (their docs call out timing attacks explicitly)."""
    if not signature or not secret:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha1).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


def parse_payload(raw_body: bytes) -> list[dict]:
    """Drains send either a JSON array or NDJSON (one object per line)."""
    text = raw_body.decode("utf-8", errors="replace").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
        items = data if isinstance(data, list) else [data]
    except ValueError:
        items = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except ValueError:
                continue
    return [i for i in items if isinstance(i, dict)][:_MAX_ENTRIES_PER_DELIVERY]


def ingest(tenant_id: str, items: list[dict], allowed_project_ids: set[str]) -> int:
    """
    Stores the entries of configured projects only (anything else a drain
    sends is dropped), redacted at rest — the table never holds a secret
    that leaked into a log line. Purges expired rows in the same transaction.
    """
    settings = get_settings()
    allowed = {normalize_project_id(p) for p in allowed_project_ids}
    rows = []
    for item in items:
        project_id = normalize_project_id(item.get("projectId"))
        timestamp = item.get("timestamp")
        if project_id not in allowed or not isinstance(timestamp, (int, float)):
            continue
        status = item.get("statusCode")
        status = status if isinstance(status, int) else None
        message = str(item.get("message") or "")
        if status == -1:  # Vercel: "no response returned and the lambda crashed"
            message = message or "Function crashed without returning a response"
            status = 500
        if not message and status is None:
            continue
        proxy = item.get("proxy") if isinstance(item.get("proxy"), dict) else {}
        rows.append(PlatformLog(
            tenant_id=tenant_id, provider="vercel", service_id=project_id,
            level=infer_level(item.get("level"), message, status),
            message=redact(message)[:_MAX_MESSAGE_CHARS],
            source=str(item.get("source") or "")[:32] or None,
            status_code=status,
            request_path=redact(str(item.get("path") or proxy.get("path") or ""))[:500] or None,
            timestamp=datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc),
        ))

    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.platform_log_retention_hours)
        db.query(PlatformLog).filter(PlatformLog.tenant_id == tenant_id, PlatformLog.timestamp < cutoff).delete()
        db.add_all(rows)
        db.commit()
    finally:
        db.close()
    return len(rows)


class VercelDrainLogProvider:
    provider_name = "vercel"

    def __init__(self, tenant_id: str):
        self._tenant_id = tenant_id

    async def fetch_logs(self, service: ServiceRef, since: datetime, until: datetime,
                         levels: list[str] | None = None, limit: int = 100) -> list[LogEntry]:
        db = SessionLocal()
        try:
            query = db.query(PlatformLog).filter(
                PlatformLog.tenant_id == self._tenant_id,        # never another tenant's rows
                PlatformLog.provider == "vercel",
                PlatformLog.service_id == normalize_project_id(service.service_id),
                PlatformLog.timestamp >= since, PlatformLog.timestamp <= until,
            )
            if levels:
                query = query.filter(PlatformLog.level.in_(levels))
            rows = query.order_by(PlatformLog.timestamp.desc()).limit(limit).all()
            return [LogEntry(timestamp=r.timestamp if r.timestamp.tzinfo else r.timestamp.replace(tzinfo=timezone.utc),
                             message=r.message, level=r.level or "info", kind=r.source or "app",
                             status_code=r.status_code, request_path=r.request_path) for r in rows]
        finally:
            db.close()

    async def get_service_state(self, service: ServiceRef) -> ServiceState:
        # A drain only carries log lines, not platform status: the verdict
        # for Vercel services relies on the healthcheck + error lines.
        return ServiceState(notes=["Vercel: estado de plataforma no disponible vía drain (solo logs)"])
