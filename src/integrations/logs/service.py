"""
Entry point the agent uses for platform logs (Fase 10.6 / 10.9): resolves
the tenant's log-enabled services, runs the read-only fetch + deterministic
diagnosis, writes the audit row, and renders what the LLM is allowed to see.

Everything here is best-effort: a platform outage, a revoked key or a rate
limit degrades to "no log data" plus a note — it never breaks a chat turn.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from src.db.database import SessionLocal
from src.db.models import Company, LogAccessAudit
from src.integrations.monitoring import get_monitored_services
from src.security.encryption import decrypt_token

from .base import LogEntry, LogProvider, ServiceRef, ServiceState
from .diagnosis import CodeLocation, Verdict, compute_verdict, locations_from_logs
from .readonly_http import PlatformAPIError, ReadOnlyViolation
from .sanitize import LOGS_ARE_DATA_NOTICE, compact, render_block

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_MINUTES = 30
# Only these roles may see raw log lines (they can contain other users'
# data). Everyone else gets the verdict, its evidence and code locations.
RAW_LOG_ROLES = {"admin", "superadmin"}

HealthCheck = Callable[[str], Awaitable[dict | None]]


@dataclass
class ServiceDiagnosis:
    service: ServiceRef
    verdict: Verdict
    log_lines: list[str] = field(default_factory=list)      # sanitized
    locations: list[CodeLocation] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def for_prompt(self, include_raw_logs: bool) -> str:
        parts = [f"Service '{self.service.name}' — deterministic status: {self.verdict.status}",
                 "Evidence: " + "; ".join(self.verdict.evidence)]
        if self.locations:
            parts.append("Code locations from the error stack traces: "
                         + ", ".join(f"{l.repo_path}:{l.line}" for l in self.locations))
        if self.notes:
            parts.append("Notes: " + "; ".join(self.notes))
        if include_raw_logs and self.log_lines:
            parts.append(LOGS_ARE_DATA_NOTICE + "\n" + render_block(self.log_lines))
        elif self.log_lines:
            parts.append("(Raw log lines exist but this user's role may not see them — "
                         "describe the problem without quoting log lines.)")
        return "\n".join(parts)

    def verdict_line(self) -> str:
        """Appended to the reply by code: the status is never the LLM's call."""
        icon = {"CAÍDO": "🔴", "DEGRADADO": "🟠", "OPERATIVO": "🟢"}.get(self.verdict.status, "⚪")
        return f"{icon} Estado de {self.service.name}: {self.verdict.status} — " + "; ".join(self.verdict.evidence)

    def for_ticket(self) -> str:
        """
        Verdict + evidence + code locations only — deliberately NO log lines:
        the ticket description becomes the body of a GitHub issue on
        escalation, and that repo may be public. Even redacted, raw logs
        stay inside Aether; engineers read them on the platform itself.
        """
        lines = [self.verdict_line()]
        if self.locations:
            lines.append("Ubicaciones en el código: " + ", ".join(f"{l.repo_path}:{l.line}" for l in self.locations))
        if self.log_lines:
            lines.append(f"({len(self.log_lines)} mensaje(s) distinto(s) de error/aviso en los logs recientes "
                         f"de la plataforma; consultarlos allí.)")
        return "\n".join(lines)


def get_log_services(tenant_id: str) -> list[ServiceRef]:
    refs = []
    for s in get_monitored_services(tenant_id):
        refs.append(ServiceRef(name=s["name"], url=s["url"], provider=s.get("provider"),
                               service_id=s.get("service_id"), owner_id=s.get("owner_id")))
    return [r for r in refs if r.has_logs]


def build_provider(tenant_id: str, ref: ServiceRef) -> LogProvider | None:
    db = SessionLocal()
    try:
        company = db.query(Company).filter(Company.id == tenant_id).first()
        if not company:
            return None
        if ref.provider == "render":
            key = decrypt_token(company.render_api_key) if company.render_api_key else None
            if not key:
                return None
            from .render import RenderLogProvider
            return RenderLogProvider(key)
        if ref.provider == "vercel":
            from .vercel import VercelDrainLogProvider
            return VercelDrainLogProvider(tenant_id)
        return None
    finally:
        db.close()


def _audit(tenant_id: str, user_id: str | None, ref: ServiceRef, since: datetime, until: datetime,
           lines: int, verdict: str) -> None:
    db = SessionLocal()
    try:
        db.add(LogAccessAudit(
            tenant_id=tenant_id, user_id=user_id, service_name=ref.name, provider=ref.provider or "",
            service_id=ref.service_id or "", window_start=since, window_end=until,
            lines_returned=lines, verdict=verdict,
        ))
        db.commit()
    except Exception as e:  # auditing must never break the chat turn, but must be visible
        logger.error("Could not write log access audit for tenant %s: %s", tenant_id, e)
        db.rollback()
    finally:
        db.close()


async def diagnose_service(tenant_id: str, user_id: str | None, ref: ServiceRef, health_check: HealthCheck | None,
                           tree: list[dict], window_minutes: int = DEFAULT_WINDOW_MINUTES,
                           provider: LogProvider | None = None) -> ServiceDiagnosis:
    until = datetime.now(timezone.utc)
    since = until - timedelta(minutes=window_minutes)
    notes: list[str] = []

    health = None
    if health_check and ref.url:
        try:
            health = await health_check(ref.url)
        except Exception as e:
            notes.append("el healthcheck no se pudo ejecutar")
            logger.warning("Healthcheck for %s failed: %s", ref.name, e)

    provider = provider or build_provider(tenant_id, ref)
    state: ServiceState | None = None
    entries: list[LogEntry] = []
    if provider is None:
        notes.append("no hay credenciales de la plataforma configuradas para leer logs")
    else:
        try:
            state = await provider.get_service_state(ref)
            # No server-side level filter: the platform's exact level values
            # aren't guaranteed (an unknown one could fail the whole query),
            # and failures often arrive unlabeled. Levels are inferred per
            # entry (base.infer_level); sanitize.compact puts errors first.
            entries = await provider.fetch_logs(ref, since, until, limit=300)
        except (PlatformAPIError, ReadOnlyViolation) as e:
            notes.append(f"no se pudieron leer los logs de la plataforma ({e})")
            logger.warning("Log fetch for %s failed: %s", ref.name, e)
        except Exception as e:
            notes.append("no se pudieron leer los logs de la plataforma")
            logger.warning("Unexpected log fetch failure for %s: %s", ref.name, e, exc_info=True)

    errors = [e for e in entries if e.level == "error"]
    verdict = compute_verdict(health, state, len(errors))
    diagnosis = ServiceDiagnosis(
        service=ref, verdict=verdict, log_lines=compact(entries),
        locations=locations_from_logs(entries, tree) if tree else [], notes=notes,
    )
    if provider is not None:
        _audit(tenant_id, user_id, ref, since, until, len(diagnosis.log_lines), verdict.status)
    return diagnosis
