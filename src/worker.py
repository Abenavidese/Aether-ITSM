"""
Standalone queue worker (composition root, like src/main.py for the API):
`python -m src.worker`. Production runs it as its own process with
JOBS_EMBEDDED_WORKER=False on the API, so the two scale and restart apart.
"""
import asyncio
import logging
import sys

from src.agents.runtime.checkpointer import open_checkpointer
from src.core.config import get_settings
from src.jobs.worker import WorkerDeps
from src.services.job_registry import build_worker
from src.tools.mcp_client import MCPToolClient


async def _main() -> None:
    settings = get_settings()
    stop = asyncio.Event()
    async with open_checkpointer(settings) as checkpointer:
        mcp_client = MCPToolClient()
        await mcp_client.connect()
        try:
            worker = build_worker(WorkerDeps(checkpointer, mcp_client), settings)
            await worker.run_forever(stop)
        finally:
            await mcp_client.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    # psycopg's async driver (Postgres checkpointer) can't run on Windows'
    # default Proactor loop; MCP's stdio client works on either.
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    try:
        asyncio.run(_main(), loop_factory=loop_factory)
    except KeyboardInterrupt:
        pass
