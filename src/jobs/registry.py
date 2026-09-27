"""
Every job kind's handler, in one place, so the embedded worker (src/main.py)
and the standalone one (python -m src.jobs.worker) always drain the same set.
"""
from src.config import Settings

from .queue import JobKind
from .worker import JobWorker, WorkerDeps


def handlers():
    from src.rag import jobs as rag_jobs
    from src.tickets import jobs as ticket_jobs

    all_handlers = {**ticket_jobs.HANDLERS, **rag_jobs.HANDLERS}
    dead = {**ticket_jobs.DEAD_HANDLERS, **rag_jobs.DEAD_HANDLERS}
    missing = {k.value for k in JobKind} - set(all_handlers)
    if missing:
        raise RuntimeError(f"Job kinds without a handler: {sorted(missing)}")
    return all_handlers, dead


def build_worker(deps: WorkerDeps, settings: Settings) -> JobWorker:
    all_handlers, dead = handlers()
    return JobWorker(
        deps, all_handlers, dead_handlers=dead,
        concurrency=settings.jobs_concurrency, poll_interval=settings.jobs_poll_seconds,
        visibility_timeout=settings.jobs_visibility_timeout_seconds,
    )
