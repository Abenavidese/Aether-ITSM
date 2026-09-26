"""
Database-backed job queue (roadmap 2.2). Synchronous on purpose: every call
is short DB work, and async callers run it with asyncio.to_thread.

Protocol:
- enqueue() adds a row inside the CALLER's session/transaction (outbox): the
  job commits or rolls back together with the business change.
- claim_next() atomically moves one due job queued -> running. On Postgres
  the candidate row is locked with FOR UPDATE SKIP LOCKED so concurrent
  workers never wait on each other; on any backend the claim itself is a
  compare-and-set UPDATE (status must still be 'queued'), so two workers
  can never both win the same job.
- heartbeat() refreshes locked_at while a job runs; requeue_stale() returns
  jobs whose worker died (no heartbeat within the visibility timeout) to the
  queue — this is what makes a killed worker's ticket finish anyway.
- fail() schedules a retry with exponential backoff, or marks the job dead
  after max_attempts (the caller then runs the kind's dead-letter handler).

Delivery is at-least-once: a handler may run again after a crash, so
handlers must be idempotent (see src/tickets/jobs.py).
"""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from sqlalchemy.orm import Session

from src.db.models import Job

BACKOFF_BASE_SECONDS = 5
BACKOFF_CAP_SECONDS = 300
_MAX_ERROR_CHARS = 1000


class JobKind(str, Enum):
    RUN_TICKET = "run_ticket"
    CREATE_GITHUB_ISSUE = "create_github_issue"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    DEAD = "dead"


@dataclass(frozen=True)
class ClaimedJob:
    id: str
    kind: str
    payload: dict
    attempts: int
    max_attempts: int


def _now() -> datetime:
    return datetime.now(timezone.utc)


def enqueue(db: Session, kind: JobKind, payload: dict, *, dedupe_key: str | None = None,
            max_attempts: int = 3, delay_seconds: float = 0) -> Job | None:
    """
    Adds a job to the caller's session — the caller commits. Returns None if
    a job with the same dedupe_key already exists (idempotent enqueue).
    """
    if dedupe_key and db.query(Job.id).filter(Job.dedupe_key == dedupe_key).first():
        return None
    job = Job(
        kind=kind.value, payload=json.dumps(payload), status=JobStatus.QUEUED.value,
        max_attempts=max_attempts, run_after=_now() + timedelta(seconds=delay_seconds), dedupe_key=dedupe_key,
    )
    db.add(job)
    return job


def claim_next(db: Session, worker_id: str, now: datetime | None = None) -> ClaimedJob | None:
    now = now or _now()
    for _ in range(5):  # lost races are retried a few times, then we just poll again
        candidate = (
            db.query(Job)
            .filter(Job.status == JobStatus.QUEUED.value, Job.run_after <= now)
            .order_by(Job.run_after, Job.created_at)
            .with_for_update(skip_locked=True)
            .first()
        )
        if candidate is None:
            db.rollback()
            return None
        won = (
            db.query(Job)
            .filter(Job.id == candidate.id, Job.status == JobStatus.QUEUED.value)
            .update({
                Job.status: JobStatus.RUNNING.value, Job.locked_by: worker_id, Job.locked_at: now,
                Job.attempts: Job.attempts + 1,
            }, synchronize_session=False)
        )
        db.commit()
        if won:
            job = db.get(Job, candidate.id)
            db.refresh(job)
            return ClaimedJob(job.id, job.kind, json.loads(job.payload), job.attempts, job.max_attempts)
    return None


def heartbeat(db: Session, job_id: str, worker_id: str) -> None:
    db.query(Job).filter(Job.id == job_id, Job.locked_by == worker_id, Job.status == JobStatus.RUNNING.value) \
        .update({Job.locked_at: _now()}, synchronize_session=False)
    db.commit()


def complete(db: Session, job_id: str) -> None:
    db.query(Job).filter(Job.id == job_id).update(
        {Job.status: JobStatus.DONE.value, Job.finished_at: _now(), Job.locked_by: None, Job.last_error: None},
        synchronize_session=False,
    )
    db.commit()


def backoff_seconds(attempts: int) -> float:
    return min(BACKOFF_BASE_SECONDS * 2 ** max(attempts - 1, 0), BACKOFF_CAP_SECONDS)


def fail(db: Session, job_id: str, error: str, now: datetime | None = None) -> JobStatus:
    """Retry later (queued, with backoff) or give up (dead). Returns the new status."""
    now = now or _now()
    job = db.get(Job, job_id)
    if job is None:
        return JobStatus.DEAD
    job.last_error = error[:_MAX_ERROR_CHARS]
    job.locked_by = None
    if job.attempts >= job.max_attempts:
        job.status = JobStatus.DEAD.value
        job.finished_at = now
    else:
        job.status = JobStatus.QUEUED.value
        job.run_after = now + timedelta(seconds=backoff_seconds(job.attempts))
    db.commit()
    return JobStatus(job.status)


def requeue_stale(db: Session, visibility_timeout_seconds: float, now: datetime | None = None) -> int:
    """Running jobs with no heartbeat for too long: their worker is gone."""
    now = now or _now()
    cutoff = now - timedelta(seconds=visibility_timeout_seconds)
    count = (
        db.query(Job)
        .filter(Job.status == JobStatus.RUNNING.value, Job.locked_at < cutoff)
        .update({Job.status: JobStatus.QUEUED.value, Job.locked_by: None, Job.run_after: now,
                 Job.last_error: "worker stopped heartbeating (requeued)"}, synchronize_session=False)
    )
    db.commit()
    return count
