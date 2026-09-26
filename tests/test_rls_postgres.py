"""
Roadmap 2.5 — Row-Level Security, proven against a REAL Postgres.

Skipped unless RLS_TEST_DATABASE_URL points at a disposable Postgres (it
creates and drops every Aether table there). Validated on a throwaway Neon
project; see docs/PLAN_IMPLEMENTACION.txt.
"""
import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from src.db import models
from src.db.tenant_scope import tenant_session

DB_URL = os.environ.get("RLS_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="RLS_TEST_DATABASE_URL not set (needs a disposable Postgres)")


@pytest.fixture(scope="module")
def pg():
    from scripts.apply_rls import apply
    # pool_size=1: every session reuses ONE connection, so a leaked SET ROLE /
    # tenant setting would show up in the next session.
    engine = create_engine(DB_URL, pool_size=1, max_overflow=0)
    models.Base.metadata.drop_all(engine)
    models.Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS langchain_pg_embedding"))
        conn.execute(text("CREATE TABLE langchain_pg_embedding (id varchar PRIMARY KEY, cmetadata jsonb)"))
    apply(DB_URL)
    apply(DB_URL)  # idempotent
    factory = sessionmaker(bind=engine)
    yield engine, factory
    apply(DB_URL, rollback=True)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS langchain_pg_embedding"))
    models.Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(scope="module")
def two_tenants(pg):
    _, factory = pg
    a, b = f"tenant-a-{uuid.uuid4().hex[:6]}", f"tenant-b-{uuid.uuid4().hex[:6]}"
    with factory() as db:  # the app's own role: cross-tenant, like seeding / the job queue
        for tenant in (a, b):
            db.add(models.Company(id=tenant, name=tenant))
            db.flush()
            user = models.User(email=f"u@{tenant}.com", full_name="u", password_hash="x", company_id=tenant)
            db.add(user)
            db.flush()
            db.add(models.Ticket(tenant_id=tenant, user_id=user.id, external_id=f"T-{tenant}", title="t",
                                 description="d"))
        db.execute(text("INSERT INTO langchain_pg_embedding VALUES (:i1, CAST(:m1 AS jsonb)), (:i2, CAST(:m2 AS jsonb))"),
                   {"i1": "c1", "m1": f'{{"tenant_id": "{a}"}}', "i2": "c2", "m2": f'{{"tenant_id": "{b}"}}'})
        db.commit()
    return a, b


def test_a_forgotten_tenant_filter_still_only_sees_own_rows(pg, two_tenants):
    _, factory = pg
    a, b = two_tenants
    with tenant_session(a, session_factory=factory, rls=True) as db:
        assert {t.tenant_id for t in db.query(models.Ticket).all()} == {a}   # no WHERE tenant_id!
        assert [c.id for c in db.query(models.Company).all()] == [a]
        assert {u.company_id for u in db.query(models.User).all()} == {a}
        chunks = db.execute(text("SELECT id FROM langchain_pg_embedding")).scalars().all()
        assert chunks == ["c1"]


def test_writing_into_another_tenant_is_rejected(pg, two_tenants):
    _, factory = pg
    a, b = two_tenants
    with tenant_session(a, session_factory=factory, rls=True) as db:
        user_id = db.query(models.User).first().id
        db.add(models.Ticket(tenant_id=b, user_id=user_id, external_id="SMUGGLED", title="x", description="x"))
        with pytest.raises(DBAPIError, match="row-level security"):
            db.flush()
        db.rollback()


def test_updates_cannot_touch_another_tenants_rows(pg, two_tenants):
    _, factory = pg
    a, b = two_tenants
    with tenant_session(a, session_factory=factory, rls=True) as db:
        changed = db.query(models.Ticket).filter(models.Ticket.tenant_id == b).update({"title": "pwned"})
        db.commit()
    assert changed == 0


def test_scope_does_not_leak_to_the_next_user_of_the_connection(pg, two_tenants):
    _, factory = pg
    a, b = two_tenants
    with tenant_session(a, session_factory=factory, rls=True) as db:
        db.query(models.Ticket).all()
        db.commit()
    with factory() as db:  # same pooled connection, no tenant: the app role again
        assert {t.tenant_id for t in db.query(models.Ticket).all()} >= {a, b}
        assert db.execute(text("SELECT current_setting('app.tenant_id', true)")).scalar() in (None, "")


def test_disabled_flag_keeps_the_app_role(pg, two_tenants):
    _, factory = pg
    a, b = two_tenants
    with tenant_session(a, session_factory=factory, rls=False) as db:
        assert {t.tenant_id for t in db.query(models.Ticket).all()} >= {a, b}
