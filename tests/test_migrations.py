"""
Roadmap 1.4 — Alembic migrations are the only way the schema is built.
"""
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from src.db import models
from src.db.migrate import _ALEMBIC_INI, BASELINE_REVISION, _config, upgrade_to_head

# The latest revision, read from the migrations themselves (not hardcoded).
HEAD = ScriptDirectory.from_config(Config(str(_ALEMBIC_INI))).get_current_head()


def _engine(tmp_path, name="m.db"):
    return create_engine(f"sqlite:///{tmp_path / name}")


def _version(engine) -> str:
    with engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def test_empty_database_upgrades_to_exactly_the_models(tmp_path):
    engine = _engine(tmp_path)
    upgrade_to_head(engine)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), models.Base.metadata)
    # An empty diff = no model change is missing a migration (and vice versa).
    assert diff == []


def test_pre_alembic_database_is_adopted_and_upgraded(tmp_path):
    engine = _engine(tmp_path)
    # What the old app left behind: the baseline schema with no alembic_version.
    with engine.begin() as conn:
        command.upgrade(_config(conn), BASELINE_REVISION)
        conn.execute(text("DROP TABLE alembic_version"))
        conn.execute(text("INSERT INTO companies (id, name, llm_engine) VALUES ('c1', 'Old Co', 'nemotron-nano')"))

    upgrade_to_head(engine)

    columns = {c["name"] for c in inspect(engine).get_columns("companies")}
    assert not columns & {"llm_engine", "webhook_url", "mcp_server_url", "mcp_auth_token"}
    with engine.connect() as conn:
        assert conn.execute(text("SELECT name FROM companies WHERE id = 'c1'")).scalar_one() == "Old Co"
    assert _version(engine) == HEAD


def test_pre_alembic_database_without_its_indexes_gets_them(tmp_path):
    # The real Supabase database (restored copy, 2026-09-27): the old app
    # never created these, and adoption stamps it as the baseline anyway.
    engine = _engine(tmp_path)
    with engine.begin() as conn:
        command.upgrade(_config(conn), BASELINE_REVISION)
        conn.execute(text("DROP TABLE alembic_version"))
        conn.execute(text("DROP INDEX ix_companies_api_key_hash"))
        conn.execute(text("DROP INDEX ix_tickets_external_id"))

    upgrade_to_head(engine)

    insp = inspect(engine)
    assert "ix_companies_api_key_hash" in {i["name"] for i in insp.get_indexes("companies")}
    assert "ix_tickets_external_id" in {i["name"] for i in insp.get_indexes("tickets")}
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), models.Base.metadata)
    assert diff == []


def test_upgrade_is_idempotent(tmp_path):
    engine = _engine(tmp_path)
    upgrade_to_head(engine)
    upgrade_to_head(engine)
    assert _version(engine) == HEAD


def test_downgrade_restores_the_baseline(tmp_path):
    engine = _engine(tmp_path)
    upgrade_to_head(engine)
    with engine.begin() as conn:
        command.downgrade(_config(conn), BASELINE_REVISION)
    assert "llm_engine" in {c["name"] for c in inspect(engine).get_columns("companies")}


def test_database_built_by_create_all_is_adopted_as_head(tmp_path):
    engine = _engine(tmp_path)
    models.Base.metadata.create_all(engine)
    with engine.begin() as conn:  # library-owned tables never count as drift
        conn.execute(text("CREATE TABLE checkpoints (thread_id TEXT)"))
        conn.execute(text("CREATE TABLE langchain_pg_embedding (id TEXT)"))
    upgrade_to_head(engine)
    assert _version(engine) == HEAD


def test_unrecognized_unversioned_schema_is_refused(tmp_path):
    engine = _engine(tmp_path)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE companies (id TEXT PRIMARY KEY, something_else TEXT)"))
    with pytest.raises(RuntimeError, match="alembic stamp"):
        upgrade_to_head(engine)
