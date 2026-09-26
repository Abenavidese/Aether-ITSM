"""
Async worker that drains the job queue (roadmap 2.2).

Two ways to run it, same code:
- embedded in the API process (JOBS_EMBEDDED_WORKER=true, the dev default;
  started from the FastAPI lifespan), or
- standalone, so API and agent runs scale and restart independently:
      python -m src.jobs.worker

Concurrency is bounded (JOBS_CONCURRENCY): a burst of webhooks queues up
instead of launching dozens of simultaneous 8B-model runs. All DB work goes
through asyncio.to_thread, so the event loop never blocks on it.
"""
import asyncio
import logging
import os
import socket
import sys
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from src.db.database import SessionLocal

from . import queue
from .queue import ClaimedJob, JobStatus

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkerDeps:
    """Long-lived resources handlers need, injected (never module globals)."""
    checkpointer: Any
    mcp_client: Any


Handler = Callable[[dict, WorkerDeps], Awaitable[None]]
DeadHandler = Callable[[dict, WorkerDeps, str], Awaitable[None]]


class PermanentJobError(Exception):
    """Retrying can't help (bad payload, missing row): go straight to dead."""


def _in_session(fn, *args, **kwargs):
    db = SessionLocal()
    try:
        return fn(db, *args, **kwargs)
    finally:
        db.close()


class JobWorker:
    def __init__(self, deps: WorkerDeps, handlers: dict[str, Handler], *,
                 dead_handlers: dict[str, DeadHandler] | None = None, concurrency: int = 2,
                 poll_interval: float = 1.0, visibility_timeout: float = 600.0,
                 heartbeat_interval: float = 30.0, worker_id: str | None = None):
        self._deps = deps
        self._handlers = handlers
        self._dead_handlers = dead_handlers or {}
        self._concurrency = concurrency
        self._poll_interval = poll_interval
        self._visibility_timeout = visibility_timeout
        self._heartbeat_interval = heartbeat_interval
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"

    async def run_forever(self, stop: asyncio.Event) -> None:
        logger.info("Job worker %s started (concurrency=%d)", self.worker_id, self._concurrency)
        slots = asyncio.Semaphore(self._concurrency)
        running: set[asyncio.Task] = set()
        loop = asyncio.get_running_loop()
        next_reap = 0.0
        while not stop.is_set():
            if loop.time() >= next_reap:
                await self.requeue_stale()
                next_reap = loop.time() + max(self._visibility_timeout / 4, 1.0)
            await slots.acquire()
            job = await asyncio.to_thread(_in_session, queue.claim_next, self.worker_id)
            if job is None:
                slots.release()
                try:
                    await asyncio.wait_for(stop.wait(), timeout=self._poll_interval)
                except asyncio.TimeoutError:
                    pass
                continue
            task = asyncio.create_task(self.execute(job))
            running.add(task)
            task.add_done_callback(lambda t: (running.discard(t), slots.release()))
        # Let in-flight jobs finish their current step; anything cut short is
        # requeued by requeue_stale() on the next start (at-least-once).
        if running:
            await asyncio.wait(running, timeout=30)
        logger.info("Job worker %s stopped", self.worker_id)

    async def requeue_stale(self) -> int:
        count = await asyncio.to_thread(_in_session, queue.requeue_stale, self._visibility_timeout)
        if count:
            logger.warning("Requeued %d job(s) whose worker stopped heartbeating", count)
        return count

    async def run_once(self) -> ClaimedJob | None:
        """Claims and runs a single job (tests, and draining in scripts)."""
        job = await asyncio.to_thread(_in_session, queue.claim_next, self.worker_id)
        if job:
            await self.execute(job)
        return job

    async def _heartbeat(self, job: ClaimedJob) -> None:
        while True:
            await asyncio.sleep(self._heartbeat_interval)
            await asyncio.to_thread(_in_session, queue.heartbeat, job.id, self.worker_id)

    async def execute(self, job: ClaimedJob) -> None:
        handler = self._handlers.get(job.kind)
        beat = asyncio.create_task(self._heartbeat(job))
        try:
            if handler is None:
                raise PermanentJobError(f"no handler for job kind '{job.kind}'")
            await handler(job.payload, self._deps)
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            if isinstance(e, PermanentJobError):
                await asyncio.to_thread(_in_session, _mark_dead, job.id, error)
                status = JobStatus.DEAD
            else:
                status = await asyncio.to_thread(_in_session, queue.fail, job.id, error)
            logger.warning("Job %s (%s) attempt %d/%d failed -> %s: %s",
                           job.id, job.kind, job.attempts, job.max_attempts, status.value, error, exc_info=True)
            if status == JobStatus.DEAD and job.kind in self._dead_handlers:
                try:
                    await self._dead_handlers[job.kind](job.payload, self._deps, error)
                except Exception:
                    logger.error("Dead-letter handler for job %s failed", job.id, exc_info=True)
        else:
            await asyncio.to_thread(_in_session, queue.complete, job.id)
            logger.info("Job %s (%s) done", job.id, job.kind)
        finally:
            beat.cancel()


def _mark_dead(db, job_id: str, error: str) -> None:
    from src.db.models import Job
    job = db.get(Job, job_id)
    if job:
        job.attempts = job.max_attempts
    db.commit()
    queue.fail(db, job_id, error)


async def _main() -> None:
    from src.agent.checkpointer import open_checkpointer
    from src.agent.mcp_client import MCPToolClient
    from src.config import get_settings
    from src.tickets.jobs import build_worker

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
