"""
Deterministic service diagnosis (Fase 10.5).

The verdict (DOWN / DEGRADED / UP / UNKNOWN) is computed here from concrete
signals and is NOT something the LLM decides — the model explains it, but
code states it (appended to the reply in concierge.py). Same principle as
the risk floor in src/agent/risk_policy.py.

It also turns stack traces in the logs into repo locations (file:line), so
the Concierge can read the exact code that failed with the file-reading
capability it already has.
"""
import re
from dataclasses import dataclass, field

from .base import LogEntry, ServiceState

DOWN, DEGRADED, UP, UNKNOWN = "CAÍDO", "DEGRADADO", "OPERATIVO", "DESCONOCIDO"

# 502/503/504 at the edge mean no healthy instance answered: the service is
# down. A 500 means the app is up but failing on that request: degraded.
_GATEWAY_DOWN_STATUSES = {502, 503, 504}


@dataclass
class Verdict:
    status: str
    evidence: list[str] = field(default_factory=list)


def compute_verdict(health: dict | None, state: ServiceState | None, error_count: int) -> Verdict:
    """
    health: the check_service_status tool result ({"available", "http_status"
    | "error"}) or None if no healthcheck ran. state: what the platform
    reports. error_count: error-level log entries in the window.
    """
    down, degraded, ok = [], [], []

    if state and state.suspended:
        down.append("la plataforma reporta el servicio SUSPENDIDO")
    if health is not None:
        if "error" in health and not health.get("available"):
            down.append(f"el healthcheck no pudo conectar ({str(health['error'])[:120]})")
        elif health.get("http_status") in _GATEWAY_DOWN_STATUSES:
            down.append(f"el healthcheck respondió HTTP {health['http_status']} (ninguna instancia responde)")
        elif isinstance(health.get("http_status"), int) and health["http_status"] >= 500:
            degraded.append(f"el healthcheck respondió HTTP {health['http_status']}")
        elif health.get("available"):
            ok.append(f"el healthcheck respondió HTTP {health.get('http_status')}")
    if state and state.last_deploy_status == "failed":
        degraded.append("el último deploy falló (sigue sirviendo la versión anterior)")
    if error_count:
        degraded.append(f"{error_count} entrada(s) de error en los logs recientes")

    if down:
        return Verdict(DOWN, down + degraded)
    if degraded:
        return Verdict(DEGRADED, degraded + ok)
    if ok:
        return Verdict(UP, ok + ["sin errores en los logs recientes"])
    return Verdict(UNKNOWN, ["no hubo señales suficientes (sin healthcheck ni datos de la plataforma)"])


# Node:   "at handler (/opt/render/project/src/backend/src/cart.js:42:13)"
#         "at /app/src/cart.js:42:13"
# Python: 'File "/app/src/cart.py", line 42, in handler'
_NODE_FRAME = re.compile(r"at (?:[^\s(]+ )?\(?((?:[A-Za-z]:)?[^\s():]+\.(?:js|mjs|cjs|ts|jsx|tsx)):(\d+)(?::\d+)?\)?")
_PY_FRAME = re.compile(r'File "([^"]+\.py)", line (\d+)')
_VENDOR = ("node_modules/", "site-packages/", "dist-packages/", "internal/", "node:")


@dataclass(frozen=True)
class CodeLocation:
    repo_path: str
    line: int


def extract_frames(text: str) -> list[tuple[str, int]]:
    frames = [(m.group(1), int(m.group(2))) for m in _NODE_FRAME.finditer(text)]
    frames += [(m.group(1), int(m.group(2))) for m in _PY_FRAME.finditer(text)]
    return [(p.replace("\\", "/"), n) for p, n in frames if not any(v in p for v in _VENDOR)]


def map_to_repo(frames: list[tuple[str, int]], tree: list[dict], limit: int = 3) -> list[CodeLocation]:
    """
    A deployed path ("/opt/render/project/src/backend/src/cart.js") maps to
    the repo file whose path it ENDS with ("backend/src/cart.js"); the
    longest such suffix wins. Frames with no repo match (vendor code,
    generated files) are dropped rather than guessed.
    """
    files = [e["path"] for e in tree if e["type"] == "file"]
    found: list[CodeLocation] = []
    for deployed, line in frames:
        deployed_lower = deployed.lower()
        matches = [f for f in files if deployed_lower == f.lower() or deployed_lower.endswith("/" + f.lower())]
        if not matches:
            continue
        location = CodeLocation(max(matches, key=len), line)
        if location not in found:
            found.append(location)
        if len(found) >= limit:
            break
    return found


def locations_from_logs(entries: list[LogEntry], tree: list[dict]) -> list[CodeLocation]:
    frames: list[tuple[str, int]] = []
    for entry in entries:
        if entry.level == "error":
            frames += extract_frames(entry.message)
    return map_to_repo(frames, tree)
