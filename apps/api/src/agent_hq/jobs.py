"""Durable job queue on PostgreSQL (ADR-0003)."""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from agent_hq.domain import JobKind, JobStatus
from agent_hq.models import Job, utcnow


async def enqueue(
    session: AsyncSession,
    *,
    kind: JobKind,
    task_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
    max_attempts: int = 3,
) -> Job:
    job = Job(
        kind=kind,
        task_id=task_id,
        conversation_id=conversation_id,
        payload=payload or {},
        status=JobStatus.QUEUED,
        max_attempts=max_attempts,
    )
    session.add(job)
    await session.flush()
    return job


_CLAIM_SQL = text(
    """
    UPDATE jobs
       SET status = 'running', locked_by = :worker, attempts = attempts + 1,
           lease_expires_at = now() + make_interval(secs => :lease), updated_at = now()
     WHERE id = (
        SELECT j.id FROM jobs j
         WHERE j.status = 'queued' AND j.run_after <= now()
           -- one job per task at a time: a resume never overlaps the run it resumes
           AND NOT EXISTS (
               SELECT 1 FROM jobs r WHERE r.task_id = j.task_id AND r.status = 'running'
           )
         ORDER BY j.id
         FOR UPDATE SKIP LOCKED
         LIMIT 1)
    RETURNING id
    """
)


async def claim(session: AsyncSession, *, worker_id: str, lease_seconds: int) -> Job | None:
    job_id = await session.scalar(_CLAIM_SQL, {"worker": worker_id, "lease": lease_seconds})
    if job_id is None:
        return None
    return await session.get(Job, job_id, populate_existing=True)


async def heartbeat(session: AsyncSession, job_id: int, *, lease_seconds: int) -> None:
    await session.execute(
        update(Job)
        .where(Job.id == job_id, Job.status == JobStatus.RUNNING)
        .values(lease_expires_at=utcnow() + timedelta(seconds=lease_seconds))
    )


async def complete(session: AsyncSession, job_id: int) -> None:
    await session.execute(
        update(Job).where(Job.id == job_id).values(status=JobStatus.DONE, lease_expires_at=None)
    )


async def fail(session: AsyncSession, job_id: int, *, error: str, retry: bool) -> bool:
    """Record a failure. Returns True when the job was requeued for another attempt."""
    job = await session.get(Job, job_id, with_for_update=True, populate_existing=True)
    if job is None:
        return False
    job.last_error = error[:4000]
    job.lease_expires_at = None
    job.locked_by = None
    if retry and job.attempts < job.max_attempts:
        job.status = JobStatus.QUEUED
        job.run_after = utcnow() + timedelta(seconds=min(60, 2**job.attempts))
        return True
    job.status = JobStatus.FAILED
    return False


async def requeue_expired(session: AsyncSession) -> list[int]:
    """Return jobs whose worker died (lease expired) to the queue."""
    result = await session.scalars(
        update(Job)
        .where(Job.status == JobStatus.RUNNING, Job.lease_expires_at < utcnow())
        .values(status=JobStatus.QUEUED, locked_by=None, lease_expires_at=None)
        .returning(Job.id)
    )
    return list(result)


async def pending_jobs(session: AsyncSession, task_id: uuid.UUID) -> list[Job]:
    result = await session.scalars(
        select(Job).where(
            Job.task_id == task_id, Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING])
        )
    )
    return list(result)
