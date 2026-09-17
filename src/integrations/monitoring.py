"""
Tenant-configured service healthcheck targets (Fase 4).

Deliberately not a real monitoring system — a simple {name, url} list per
tenant (Company.monitored_services, JSON-encoded) is enough for the agent to
tell "the VPN gateway is actually down" apart from a user-side problem via
the check_service_status MCP tool (src/tools/mcp_server.py).
"""
import json
from src.db.database import SessionLocal
from src.db.models import Company


def get_monitored_services(tenant_id: str) -> list[dict]:
    """Returns the tenant's configured healthcheck targets, or [] if none/invalid."""
    db = SessionLocal()
    try:
        company = db.query(Company).filter(Company.id == tenant_id).first()
        if not company or not company.monitored_services:
            return []
        try:
            services = json.loads(company.monitored_services)
        except (TypeError, ValueError):
            return []
        if not isinstance(services, list):
            return []
        return [s for s in services if isinstance(s, dict) and s.get("name") and s.get("url")]
    finally:
        db.close()
