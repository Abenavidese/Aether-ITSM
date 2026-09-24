"""
Platform-agnostic types for reading hosting-platform logs (Fase 10).

The agent only ever sees these — never a Render/Vercel response shape — so
adding a platform means writing one LogProvider, without touching the
Concierge, the diagnosis rules or the sanitizer.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class ServiceRef:
    """A tenant-configured service (Company.monitored_services entry)."""
    name: str
    url: str
    provider: str | None = None
    service_id: str | None = None
    owner_id: str | None = None

    @property
    def has_logs(self) -> bool:
        return bool(self.provider and self.service_id)


@dataclass(frozen=True)
class LogEntry:
    timestamp: datetime
    message: str
    level: str = "info"          # normalized: debug | info | warning | error
    kind: str = "app"            # app | request | build
    status_code: int | None = None
    request_path: str | None = None


@dataclass
class ServiceState:
    """What the platform itself says about the service (not our healthcheck)."""
    name: str | None = None
    suspended: bool | None = None
    last_deploy_status: str | None = None     # platform-normalized, e.g. "live", "failed"
    last_deploy_at: datetime | None = None
    notes: list[str] = field(default_factory=list)


class LogProvider(Protocol):
    provider_name: str

    async def fetch_logs(self, service: ServiceRef, since: datetime, until: datetime,
                         levels: list[str] | None = None, limit: int = 100) -> list[LogEntry]: ...

    async def get_service_state(self, service: ServiceRef) -> ServiceState: ...


def normalize_level(raw: str | None) -> str:
    value = (raw or "").lower()
    if value in ("error", "err", "fatal", "critical", "crit", "emerg", "alert"):
        return "error"
    if value in ("warn", "warning"):
        return "warning"
    if value in ("debug", "trace"):
        return "debug"
    return "info"


# stderr/console.error isn't always labeled "error" by the platform, so an
# info-labeled line that plainly reports a failure is promoted.
_ERROR_TEXT = re.compile(r"\b(\w*Error|\w*Exception|Traceback|FATAL|Unhandled(Promise)?Rejection|panic)\b")


def infer_level(raw_level: str | None, message: str, status_code: int | None = None) -> str:
    level = normalize_level(raw_level)
    if level in ("error", "warning"):
        return level
    if status_code is not None and status_code >= 500:
        return "error"
    if _ERROR_TEXT.search(message):
        return "error"
    return level
