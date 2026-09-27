"""
Applies the Alembic migrations (roadmap 1.4) — replaces create_all() and the
hand-written ALTER TABLEs that ran on every startup.

    python -m src.db.migrate        # same as `alembic upgrade head`, plus adoption below

Adoption: a database with tables but no alembic_version row can't be
upgraded from zero ("table already exists"). It is stamped with the revision
its schema provably matches (see _unversioned_revision) and then upgraded.
"""
import logging
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

BASELINE_REVISION = "0001"
# Tables in the same database that libraries own and migrate themselves:
# LangGraph's Postgres checkpointer and langchain-postgres' pgvector store.
# Neither autogenerate nor adoption may treat them as drift.
EXTERNALLY_MANAGED_PREFIXES = ("checkpoint", "langchain_pg_")


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    if type_ == "table" and reflected and compare_to is None:
        return not name.startswith(EXTERNALLY_MANAGED_PREFIXES)
    return True


# Present in the baseline, dropped by 0002 — how a pre-Alembic database is recognized.
_BASELINE_ONLY_COLUMNS = {"llm_engine", "webhook_url", "mcp_server_url", "mcp_auth_token"}
_ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def _config(connection) -> Config:
    config = Config(str(_ALEMBIC_INI))
    config.attributes["connection"] = connection
    config.attributes["configure_logger"] = False
    return config


def _unversioned_revision(connection) -> str:
    """
    Which revision an existing database without alembic_version matches:
    the baseline (built by the pre-Alembic app — still has its unused Company
    columns) or head (built by create_all() from the current models, e.g. a
    test fixture). Anything else is refused rather than guessed at: stamping
    the wrong revision makes the next migration fail halfway or silently
    skip a change.
    """
    from src.db import models

    migration_ctx = MigrationContext.configure(connection, opts={"include_object": include_object})
    if not compare_metadata(migration_ctx, models.Base.metadata):
        return "head"
    columns = {c["name"] for c in inspect(connection).get_columns("companies")}
    if _BASELINE_ONLY_COLUMNS <= columns:
        return BASELINE_REVISION
    raise RuntimeError(
        "Database has tables but no alembic_version, and its schema matches neither the "
        f"pre-Alembic baseline ({BASELINE_REVISION}) nor the current models. Inspect it and "
        "`alembic stamp <revision>` by hand."
    )


def upgrade_to_head(engine: Engine) -> None:
    with engine.begin() as connection:
        config = _config(connection)
        tables = set(inspect(connection).get_table_names())
        if "alembic_version" not in tables and "companies" in tables:
            revision = _unversioned_revision(connection)
            logger.warning("Unversioned existing database: stamping %s before upgrading", revision)
            command.stamp(config, revision)
        command.upgrade(config, "head")


if __name__ == "__main__":
    from src.db.database import engine

    logging.basicConfig(level=logging.INFO)
    upgrade_to_head(engine)
