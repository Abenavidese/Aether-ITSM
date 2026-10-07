"""
API composition root: settings, middleware, routers and the shared resources
(LangGraph checkpointer, MCP tool server, embedded job worker) opened once per
process in the lifespan. `uvicorn src.main:app`.
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from src.agents.runtime.checkpointer import open_checkpointer
from src.api.routers import auth, chat, integrations, knowledge, observability, tenant, tickets, users
from src.core.config import get_settings
from src.db import tenant_scope  # noqa: F401 — registers the RLS session listener (roadmap 2.5)
from src.db.database import engine
from src.db.migrate import upgrade_to_head
from src.jobs.worker import WorkerDeps
from src.observability.logging import RequestIdMiddleware, configure_logging
from src.security.limiter import limiter
from src.services.bootstrap import seed_database
from src.services.job_registry import build_worker
from src.tools.mcp_client import MCPToolClient

settings = get_settings()

# Every line carries request_id / trace_id (roadmap 2.4); LOG_FORMAT=json for log backends.
configure_logging(settings.log_format)
logger = logging.getLogger(__name__)

ROUTERS = (tickets, chat, auth, tenant, users, knowledge, integrations, observability)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for FastAPI to handle global resources."""
    # The LangGraph checkpointer (sqlite or Postgres, see
    # src/agents/runtime/checkpointer.py) is opened once for the whole app.
    # It's opened before the MCP subprocess so a misconfigured backend fails
    # fast without leaving an orphan tool server behind.
    async with open_checkpointer(settings) as checkpointer:
        logger.info("Starting MCP tool server subprocess")
        mcp_client = MCPToolClient()
        await mcp_client.connect()
        stop_worker = asyncio.Event()
        worker_task = None
        try:
            app.state.checkpointer = checkpointer
            app.state.mcp_client = mcp_client
            if settings.jobs_embedded_worker:
                # Same queue a standalone `python -m src.worker` drains;
                # embedded is just the zero-setup option for development.
                worker = build_worker(WorkerDeps(checkpointer, mcp_client), settings)
                worker_task = asyncio.create_task(worker.run_forever(stop_worker))
            yield
        finally:
            stop_worker.set()
            if worker_task:
                await worker_task
            await mcp_client.close()
    logger.info("Shut down checkpointer and MCP tool server")


def create_app() -> FastAPI:
    # Schema changes are Alembic migrations (migrations/, roadmap 1.4), applied
    # by `alembic upgrade head` / `python -m src.db.migrate` as a deploy step.
    # Only with DB_AUTO_MIGRATE=true (dev, tests) does startup apply them
    # itself — a shared database is never altered just because an API started.
    if settings.db_auto_migrate:
        upgrade_to_head(engine)
    seed_database()

    app = FastAPI(
        title="ITSM Agent API",
        description="API for the AI-powered IT Support Agent using Nebius Token Factory",
        version="1.0.0",
        lifespan=lifespan
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, lambda req, exc: Response(content="Rate limit exceeded", status_code=429))
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.get_cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for module in ROUTERS:
        app.include_router(module.router, prefix="/api")

    @app.get("/health")
    async def health_check():
        return {"status": "ok", "message": "ITSM Agent API is running"}

    return app


app = create_app()
