"""
Postgres Row-Level Security as a second tenant-isolation layer (roadmap 2.5).

Today every query filters by tenant_id in code. RLS makes the DATABASE
enforce it too, so a forgotten filter (the classic multi-tenant leak)
returns nothing instead of another company's rows.

How a session becomes tenant-scoped:
    with tenant_session(tenant_id) as db: ...        # service code
    db: Session = Depends(get_tenant_db)             # route handlers
Either way the tenant id rides in Session.info (not a ContextVar: sync DB
work runs in worker threads, where context changes don't flow back). On
every transaction begin, the listener below runs, for Postgres only:
    SET LOCAL ROLE aether_tenant                     -- subject to RLS
    SELECT set_config('app.tenant_id', <id>, true)   -- read by the policies
Both are transaction-local, so a pooled connection never leaks a tenant to
the next user of that connection.

Sessions WITHOUT a tenant (login, webhook API-key lookup, the job queue,
seeding) keep the connection's own role — cross-tenant by design, and the
reason RLS here is defense in depth, not the only check. The SQL that
creates the role and policies is src/db/rls/enable.sql (rollback:
disable.sql, applied with scripts/apply_rls.py). Until it is applied,
DB_RLS_ENABLED stays false and this listener does nothing.
"""
from contextlib import contextmanager
from typing import Generator

from fastapi import Depends
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from src.config import get_settings
from src.security.deps import get_current_user

from .database import SessionLocal

TENANT_ROLE = "aether_tenant"
TENANT_SETTING = "app.tenant_id"


@event.listens_for(Session, "after_begin")
def _apply_tenant_scope(session: Session, transaction, connection) -> None:
    tenant_id = session.info.get("tenant_id")
    enabled = session.info.get("rls", get_settings().db_rls_enabled)
    if not tenant_id or not enabled or connection.dialect.name != "postgresql":
        return
    connection.execute(text(f"SET LOCAL ROLE {TENANT_ROLE}"))
    connection.execute(text("SELECT set_config(:key, :tenant, true)"), {"key": TENANT_SETTING, "tenant": tenant_id})


def new_tenant_session(tenant_id: str, *, session_factory=SessionLocal, rls: bool | None = None) -> Session:
    info = {"tenant_id": tenant_id}
    if rls is not None:
        info["rls"] = rls
    return session_factory(info=info)


@contextmanager
def tenant_session(tenant_id: str, **kwargs) -> Generator[Session, None, None]:
    db = new_tenant_session(tenant_id, **kwargs)
    try:
        yield db
    finally:
        db.close()


def get_tenant_db(current_user=Depends(get_current_user)) -> Generator[Session, None, None]:
    """FastAPI dependency: a session scoped to the caller's tenant."""
    with tenant_session(current_user.company_id) as db:
        yield db
