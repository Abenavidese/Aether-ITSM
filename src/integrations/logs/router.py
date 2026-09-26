"""
Inbound Vercel Log Drain endpoint (Fase 10.11).

Unauthenticated by session (Vercel calls it), so every request must prove
itself with the tenant's drain secret: HMAC-SHA1 over the RAW body,
compared in constant time. Unknown tenant, unconfigured secret and bad
signature all answer the same 403, so the endpoint doesn't reveal which
tenant ids exist or have a drain configured.
"""
import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request

from src.config import get_settings
from src.db.database import SessionLocal
from src.db.models import Company
from src.security.encryption import decrypt_token
from src.security.limiter import limiter

from .service import get_log_services
from .vercel import ingest, parse_payload, verify_signature

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations", tags=["integrations"])


def _drain_secret(tenant_id: str) -> str | None:
    db = SessionLocal()
    try:
        company = db.query(Company).filter(Company.id == tenant_id).first()
        return decrypt_token(company.vercel_drain_secret) if company and company.vercel_drain_secret else None
    finally:
        db.close()


def _ingest_drain(tenant_id: str, raw_body: bytes) -> int:
    project_ids = {s.service_id for s in get_log_services(tenant_id) if s.provider == "vercel" and s.service_id}
    return ingest(tenant_id, parse_payload(raw_body), project_ids)


@router.post("/vercel/drain/{tenant_id}")
@limiter.limit("600/minute")
async def vercel_log_drain(tenant_id: str, request: Request):
    settings = get_settings()
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.platform_log_max_body_bytes:
        raise HTTPException(status_code=413, detail="Payload too large.")
    raw_body = await request.body()
    if len(raw_body) > settings.platform_log_max_body_bytes:
        raise HTTPException(status_code=413, detail="Payload too large.")

    secret = await asyncio.to_thread(_drain_secret, tenant_id)
    if not secret or not verify_signature(raw_body, secret, request.headers.get("x-vercel-signature")):
        raise HTTPException(status_code=403, detail="invalid_signature")

    # DB work off the event loop (roadmap 2.1): this endpoint takes bursts.
    stored = await asyncio.to_thread(_ingest_drain, tenant_id, raw_body)
    return {"status": "ok", "stored": stored}
