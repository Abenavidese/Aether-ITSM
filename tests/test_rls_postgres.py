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
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
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
        for tenant in (a, b):  # Fase 14: the same VPN passage in both tenants' knowledge bases
            doc = models.KnowledgeDocument(tenant_id=tenant, filename="vpn.md", source_type="company_policy",
                                           status="ready", latest_version=1, active_version=1, chunk_count=1)
            db.add(doc)
            db.flush()
            db.add(models.KnowledgeChunk(
                tenant_id=tenant, document_id=doc.id, version=1, is_active=True, source_type="company_policy",
                filename="vpn.md", section="Error ERR_VPN_809", chunk_index=0,
                content=f"Documento: vpn.md\n\nERR_VPN_809 en {tenant}: puerto UDP 4500 bloqueado",
                search_text=f"err vpn 809 en {tenant} puerto udp 4500 bloqueado",
                embedding=[1.0, 0.0, 0.0], embedding_model="test:3d"))
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



def test_notifications_are_tenant_isolated(pg, two_tenants):
    """Fase 16: a requester's notifications stay inside their tenant."""
    _, factory = pg
    a, b = two_tenants
    with factory() as db:
        for tenant in (a, b):
            ticket = db.query(models.Ticket).filter(models.Ticket.tenant_id == tenant).first()
            db.add(models.Notification(tenant_id=tenant, user_id=ticket.user_id, ticket_id=ticket.id,
                                       kind="ticket_opened", title="t", body="b"))
        db.commit()
    with tenant_session(a, session_factory=factory, rls=True) as db:
        assert {n.tenant_id for n in db.query(models.Notification).all()} == {a}   # no WHERE tenant_id!
        user_id = db.query(models.User).first().id
        db.add(models.Notification(tenant_id=b, user_id=user_id, kind="x", title="x", body="x"))
        with pytest.raises(DBAPIError, match="row-level security"):
            db.flush()
        db.rollback()

# ── Fase 14: the knowledge store searches inside RLS ─────────────────────────

def _store(factory):
    from src.rag.store import KnowledgeStore
    return KnowledgeStore(lambda tenant: tenant_session(tenant, session_factory=factory, rls=True))


def test_knowledge_search_only_sees_own_chunks(pg, two_tenants):
    _, factory = pg
    a, b = two_tenants
    store = _store(factory)
    sources = ["company_policy"]
    dense = store.dense_search(a, [1.0, 0.0, 0.0], "test:3d", sources, 10)
    keyword = store.keyword_search(a, ["vpn", "809", "puerto"], sources, 10)
    entity = store.entity_search(a, ["err_vpn_809"], sources, 10)
    for found in ([c for c, _ in dense], [c for c, _ in keyword], entity):
        assert found and all(a in c.content and b not in c.content for c in found)
    with tenant_session(a, session_factory=factory, rls=True) as db:   # no WHERE tenant_id at all
        assert set(db.execute(text("SELECT tenant_id FROM knowledge_chunks")).scalars()) == {a}
        assert set(db.execute(text("SELECT tenant_id FROM knowledge_documents")).scalars()) == {a}


def test_dense_search_uses_the_models_hnsw_index(pg, two_tenants):
    from src.rag.store import ensure_vector_index, vector_index_name
    engine, factory = pg
    a, _ = two_tenants
    ensure_vector_index(engine, "test:3d", 3)
    ensure_vector_index(engine, "test:3d", 3)   # idempotent
    with factory() as db:
        db.execute(text("SET LOCAL enable_seqscan = off"))   # 2 rows: force the planner to show the index is usable
        plan = "\n".join(db.execute(text(
            "EXPLAIN SELECT id FROM knowledge_chunks WHERE tenant_id = :t AND is_active "
            "AND embedding_model = 'test:3d' AND source_type IN ('company_policy') "
            "ORDER BY embedding::vector(3) <=> CAST('[1,0,0]' AS vector(3)) LIMIT 5"), {"t": a}).scalars())
    assert vector_index_name("test:3d") in plan, plan
