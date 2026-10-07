"""
Render log provider (Fase 10.3), on top of the read-only client.

Endpoints used — all GET, and the only three the client allows:
- /v1/logs                         logs with level/type/time filters
- /v1/services/{srv-id}            name + suspended flag
- /v1/services/{srv-id}/deploys    latest deploy status

Response shapes follow Render's API reference; parsing is defensive (a
missing/renamed field degrades to "unknown", it never raises), and
PLAN_IMPLEMENTACION 10.0 includes checking them against a real curl.
"""
import hashlib
import logging
import re
import time
from dataclasses import replace
from datetime import datetime, timezone

import httpx

from .base import LogEntry, ServiceRef, ServiceState, infer_level
from .readonly_http import ReadOnlyHttpClient

logger = logging.getLogger(__name__)

RENDER_API_BASE = "https://api.render.com"
_SERVICE_ID = r"srv-[a-z0-9]{10,40}"
RENDER_ALLOWED_PATHS = [
    re.compile(r"/v1/logs"),
    re.compile(rf"/v1/services/{_SERVICE_ID}"),
    re.compile(rf"/v1/services/{_SERVICE_ID}/deploys"),
]

_MAX_PAGES = 3
_PAGE_SIZE = 100          # Render's max per page
_CACHE_TTL_SECONDS = 60

# Deploy statuses that mean "the latest deploy did not go live". On Render a
# failed deploy leaves the PREVIOUS version serving, so this alone is not
# "down" — diagnosis.py treats it as a degradation signal.
_FAILED_DEPLOY_STATUSES = {"build_failed", "update_failed", "pre_deploy_failed", "canceled"}

# key -> (expires_at, value). Saves rate limit when several employees report
# the same outage within a minute. Every key starts with a hash of the API
# key: keying on service_id alone would let a tenant that configures SOMEONE
# ELSE's srv-id read the other tenant's cached logs without ever holding a
# valid credential for them.
_cache: dict[tuple, tuple[float, object]] = {}


def _cached(key: tuple):
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    return None


def _store(key: tuple, value):
    _cache[key] = (time.monotonic() + _CACHE_TTL_SECONDS, value)
    return value


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _labels(entry: dict) -> dict[str, str]:
    labels = entry.get("labels") or []
    if isinstance(labels, dict):
        return {str(k): str(v) for k, v in labels.items()}
    return {str(label.get("name")): str(label.get("value")) for label in labels if isinstance(label, dict)}


# Build/deploy output carries terminal colors ("\x1b[34;1m==>\x1b[0;22m"):
# noise that eats the line budget and splits words the regexes look for.
_ANSI = re.compile(r"\x1b(?:\[[0-9;?]*[A-Za-z]|\([A-Z0-9])")

# Render stores every output line as its own record (verified against the
# real API, 2026-10-06): one console.error(err) becomes a "SyntaxError: ..."
# record plus one record per stack frame, ALL labeled level=info. A line that
# continues the previous one (indented, or a closing bracket) on the same
# instance within a second is folded back into it.
_CONTINUATION = re.compile(r"^(\s|[}\])])")
_CONTINUATION_WINDOW_SECONDS = 1.0


def _to_entry(raw: dict) -> LogEntry | None:
    message = raw.get("message")
    timestamp = _parse_time(raw.get("timestamp"))
    if not isinstance(message, str) or timestamp is None:
        return None
    message = _ANSI.sub("", message)
    if not message.strip():   # npm prints blank lines around its output; they only eat the line budget
        return None
    labels = _labels(raw)
    status = labels.get("statusCode")
    status_code = int(status) if status and status.isdigit() else None
    return LogEntry(
        timestamp=timestamp,
        message=message,
        level=infer_level(labels.get("level"), message, status_code),
        kind=labels.get("type", "app"),
        status_code=status_code,
        request_path=labels.get("path"),
    )


def _merge_records(raws: list[dict]) -> list[LogEntry]:
    """One entry per logged event, oldest first: continuation records are
    appended to the record they follow, so infer_level sees the "...Error"
    header and locations_from_logs finds the frames in the same entry."""
    parsed = [(_labels(raw).get("instance"), entry) for raw in raws if (entry := _to_entry(raw))]
    parsed.sort(key=lambda pair: pair[1].timestamp)
    merged: list[tuple[str | None, LogEntry]] = []
    for instance, entry in parsed:
        if merged:
            prev_instance, prev = merged[-1]
            if (instance == prev_instance and _CONTINUATION.match(entry.message)
                    and (entry.timestamp - prev.timestamp).total_seconds() <= _CONTINUATION_WINDOW_SECONDS):
                level = "error" if "error" in (prev.level, entry.level) else prev.level
                merged[-1] = (instance, replace(prev, message=f"{prev.message}\n{entry.message}", level=level))
                continue
        merged.append((instance, entry))
    return [entry for _, entry in merged]


class RenderLogProvider:
    provider_name = "render"

    def __init__(self, api_key: str, transport: httpx.AsyncBaseTransport | None = None):
        self._client = ReadOnlyHttpClient(RENDER_API_BASE, api_key, RENDER_ALLOWED_PATHS, transport=transport)
        self._credential_id = hashlib.sha256(api_key.encode()).hexdigest()[:16]

    async def fetch_logs(self, service: ServiceRef, since: datetime, until: datetime,
                         levels: list[str] | None = None, limit: int = 100) -> list[LogEntry]:
        key = (self._credential_id, "logs", service.service_id, since.isoformat(timespec="minutes"),
               until.isoformat(timespec="minutes"), tuple(levels or ()), limit)
        cached = _cached(key)
        if cached is not None:
            return cached

        params: dict = {
            "ownerId": service.owner_id,
            "resource": [service.service_id],
            "startTime": since.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "endTime": until.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "direction": "backward",
            "limit": min(_PAGE_SIZE, limit),
        }
        if levels:
            params["level"] = levels

        raws: list[dict] = []
        for _ in range(_MAX_PAGES):
            data = await self._client.get("/v1/logs", params=params)
            raws += [raw for raw in (data or {}).get("logs") or [] if isinstance(raw, dict)]
            if len(raws) >= limit or not (data or {}).get("hasMore"):
                break
            params["startTime"] = data.get("nextStartTime") or params["startTime"]
            params["endTime"] = data.get("nextEndTime") or params["endTime"]
        # Newest events first, then cut: `limit` counts events, not raw lines.
        return _store(key, _merge_records(raws)[::-1][:limit])

    async def get_service_state(self, service: ServiceRef) -> ServiceState:
        key = (self._credential_id, "state", service.service_id, int(time.time() // _CACHE_TTL_SECONDS))
        cached = _cached(key)
        if cached is not None:
            return cached

        state = ServiceState()
        info = await self._client.get(f"/v1/services/{service.service_id}")
        if isinstance(info, dict):
            state.name = info.get("name")
            suspended = info.get("suspended")
            if isinstance(suspended, str):
                state.suspended = suspended == "suspended"

        deploys = await self._client.get(f"/v1/services/{service.service_id}/deploys", params={"limit": 1})
        if isinstance(deploys, list) and deploys:
            deploy = deploys[0].get("deploy", deploys[0]) if isinstance(deploys[0], dict) else {}
            status = deploy.get("status")
            if status:
                state.last_deploy_status = "failed" if status in _FAILED_DEPLOY_STATUSES else status
                if status in _FAILED_DEPLOY_STATUSES:
                    state.notes.append(f"latest deploy status: {status}")
            state.last_deploy_at = _parse_time(deploy.get("finishedAt") or deploy.get("createdAt"))
        return _store(key, state)
