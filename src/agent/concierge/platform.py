"""
Read-only hosting-platform side of the Concierge (Fase 10.6): when a message
reports an outage, which services to diagnose, and the fixed patterns that
keep the agent from ever claiming (or being asked to perform) a server change.
"""
import json
import re

from src.agent.mcp_client import MCPToolClient
from src.integrations.logs.base import ServiceRef

# Outage/error reports and explicit log requests — what triggers a read-only
# look at the hosting platform (Fase 10.6).
_OUTAGE_PATTERN = re.compile(
    r"\b(ca[ií]d[oa]s?|se (cae|cay[oó])|down|no (carga|funciona|responde|abre|conecta|anda)"
    r"|error(es)? (5\d\d|del servidor|en (el )?servidor|interno)|5\d\d|timeouts?|crash\w*"
    r"|lent[oa]s?|logs?|registros)\b",
    re.IGNORECASE,
)

# Requests to CHANGE a server. The agent can't (no code path exists for it);
# this only guarantees the answer says so and routes it to humans.
_SERVER_MUTATION_PATTERN = re.compile(
    r"\b(reinici(a|e|ar|alo|a el)|restart|reboot|redespl(ie|e)g\w*|redeploy\w*|rollback|revert(ir|ar)?"
    r"|apag(a|ar|alo)|suspend(e|er)|escal(a|ar) (el|los) (servidor|servicio|instancia)s?"
    r"|haz (un )?(deploy|despliegue))\b",
    re.IGNORECASE,
)

# The model CLAIMING it changed a server ("listo, reinicié el servidor") —
# always false, since no code path for that exists. Seen with the local 8B.
_CLAIMED_SERVER_ACTION_PATTERN = re.compile(
    r"\b(reinici[eé]|he reiniciado|reiniciado|redesplegu[eé]|he redesplegado|redesplegado|restarted"
    r"|redeployed|rolled back|revert[ií]|apagu[eé]|suspend[ií]|escal[eé] (el|los) (servidor|servicio))\b",
    re.IGNORECASE,
)

_MAX_SERVICES_PER_TURN = 3


def _pick_services(services: list[ServiceRef], text: str) -> list[ServiceRef]:
    """Services named in the conversation; if none is named, all of them
    (capped) — "la tienda no carga" doesn't say which service is behind it."""
    lowered = text.lower()
    named = [s for s in services if s.name.lower() in lowered
             or any(len(w) >= 4 and w in lowered for w in re.findall(r"\w+", s.name.lower()))]
    return (named or services)[:_MAX_SERVICES_PER_TURN]


def _health_checker(mcp_client: MCPToolClient):
    """Reuses the existing check_service_status MCP tool (Fase 4)."""
    async def check(url: str) -> dict | None:
        raw = await mcp_client.call_tool("check_service_status", {"service_url": url})
        try:
            return json.loads(raw)
        except ValueError:
            return None
    return check
