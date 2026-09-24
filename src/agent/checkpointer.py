"""
LangGraph checkpointer factory: the one place that decides WHERE graph state
(ticket threads, paused Risk-3 plans, chat history) is persisted.

Design notes:
- Backend follows DATABASE_URL by default ("auto"): a Postgres DATABASE_URL
  gets AsyncPostgresSaver on that same database, anything else (the pytest
  suite's sqlite URL) keeps the AsyncSqliteSaver file at CHECKPOINT_DB_PATH.
  CHECKPOINT_BACKEND=sqlite|postgres overrides it explicitly.
- Postgres uses a connection POOL, not a single connection: a single
  AsyncConnection serializes every checkpoint read/write behind one lock,
  which is exactly the concurrency problem (webhook + chat + approvals at the
  same time) this migration exists to fix (PLAN_IMPLEMENTACION 8.3).
- prepare_threshold=0 because Supabase's pooler (pgbouncer/supavisor) doesn't
  support server-side prepared statements reliably; autocommit + dict_row are
  what AsyncPostgresSaver requires.
- Windows: psycopg's async mode cannot run on the ProactorEventLoop, which is
  what uvicorn picks on win32 unless --reload/--workers is used. We fail fast
  with the exact fix instead of a psycopg traceback deep in the first request.
  (The MCP stdio subprocess still works on the SelectorEventLoop — the mcp SDK
  falls back to a Popen-backed process there.)
"""
import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

from langgraph.checkpoint.base import BaseCheckpointSaver

from src.config import Settings

logger = logging.getLogger(__name__)


def resolve_backend(settings: Settings) -> str:
    backend = settings.checkpoint_backend.lower()
    if backend in ("sqlite", "postgres"):
        return backend
    if backend != "auto":
        raise ValueError(f"CHECKPOINT_BACKEND must be auto|sqlite|postgres, got {backend!r}")
    url = settings.database_url
    return "postgres" if url.startswith(("postgresql://", "postgres://")) else "sqlite"


def _postgres_conninfo(database_url: str) -> str:
    # psycopg wants a plain libpq URI: no SQLAlchemy "+driver" suffix, and
    # Supabase's legacy "postgres://" scheme normalized like src/db/database.py.
    scheme, rest = database_url.split("://", 1)
    return f"postgresql://{rest}" if scheme.startswith("postgres") else database_url


def _assert_psycopg_compatible_loop() -> None:
    if sys.platform != "win32":
        return
    loop = asyncio.get_running_loop()
    if isinstance(loop, asyncio.ProactorEventLoop):
        raise RuntimeError(
            "The Postgres checkpointer (psycopg async) can't run on Windows' "
            "ProactorEventLoop. Start the server with "
            "`uvicorn src.main:app --reload` or "
            "`uvicorn src.main:app --loop asyncio:SelectorEventLoop`, "
            "or set CHECKPOINT_BACKEND=sqlite."
        )


@asynccontextmanager
async def open_checkpointer(settings: Settings) -> AsyncIterator[BaseCheckpointSaver]:
    """Opens the configured checkpointer for the lifetime of the app."""
    backend = resolve_backend(settings)

    if backend == "sqlite":
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        logger.info("Checkpointer: AsyncSqliteSaver at %s", settings.checkpoint_db_path)
        async with AsyncSqliteSaver.from_conn_string(settings.checkpoint_db_path) as saver:
            yield saver
        return

    _assert_psycopg_compatible_loop()

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    logger.info("Checkpointer: AsyncPostgresSaver (pool max_size=%d)", settings.checkpoint_pool_max_size)
    async with AsyncConnectionPool(
        conninfo=_postgres_conninfo(settings.database_url),
        max_size=settings.checkpoint_pool_max_size,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=False,
    ) as pool:
        saver = AsyncPostgresSaver(pool)
        # Idempotent: creates/migrates the checkpoint tables on first run only.
        await saver.setup()
        yield saver
