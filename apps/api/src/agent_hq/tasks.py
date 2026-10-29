"""Task creation and status transitions: the only code path that changes `tasks.status`."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_hq.agents import CIO
from agent_hq.domain import JobKind, TaskStatus, check_transition
from agent_hq.events import ActorType, record_audit, record_task_event
from agent_hq.jobs import enqueue
from agent_hq.models import Agent, Task, utcnow
from agent_hq.notifications import enqueue_for_transition


async def transition(
    session: AsyncSession,
    task: Task,
    target: TaskStatus,
    *,
    actor_type: ActorType,
    actor_id: str | None,
    reason: str | None = None,
    detail: str | None = None,
    execution_id: uuid.UUID | None = None,
    agent_key: str | None = None,
    extra: dict[str, Any] | None = None,
) -> bool:
    """Move a task to `target`, recording a task event and an audit event.

    Idempotent: a task already in `target` is left untouched and False is returned, so
    graph nodes can be safely re-executed after a crash or an interrupt.
    """
    current = TaskStatus(task.status)
    if current == target:
        return False
    check_transition(current, target)
    task.status = target
    if target == TaskStatus.FAILED:
        task.failure_reason = reason or "unspecified"
        task.failure_detail = detail
    elif target == TaskStatus.QUEUED:
        task.failure_reason = None
        task.failure_detail = None
    if target == TaskStatus.COMPLETED:
        task.completed_at = utcnow()
    await session.flush()
    # Same transaction as the transition: a notification is never lost or invented.
    await enqueue_for_transition(session, task, target)
    payload: dict[str, Any] = {"from": current.value, "to": target.value, **(extra or {})}
    if reason:
        payload["reason"] = reason
    await record_task_event(
        session,
        task_id=task.id,
        project_id=task.project_id,
        type="status_changed",
        payload=payload,
        execution_id=execution_id,
        agent_key=agent_key,
    )
    await record_audit(
        session,
        actor_type=actor_type,
        actor_id=actor_id,
        action="task.status_changed",
        project_id=task.project_id,
        resource_type="task",
        resource_id=task.id,
        details=payload,
    )
    return True


async def create_task(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    title: str,
    request: str,
    acceptance_criteria: list[str],
    created_by: uuid.UUID,
    options: dict[str, Any] | None = None,
    audit_details: dict[str, Any] | None = None,
) -> Task:
    """Create a DRAFT task assigned to the CIO. Callers check that the project exists."""
    cio_id = await session.scalar(select(Agent.id).where(Agent.key == CIO.key))
    task = Task(
        project_id=project_id,
        title=title,
        request=request,
        status=TaskStatus.DRAFT,
        assigned_agent_id=cio_id,
        created_by=created_by,
        acceptance_criteria=acceptance_criteria,
        options=options or {},
    )
    session.add(task)
    await session.flush()
    await record_audit(
        session,
        actor_type="user",
        actor_id=str(created_by),
        action="task.created",
        project_id=task.project_id,
        resource_type="task",
        resource_id=task.id,
        details={"title": task.title, **(audit_details or {})},
    )
    return task


async def start_task(
    session: AsyncSession, task: Task, *, actor_id: str, max_attempts: int
) -> None:
    """Queue a new run of a startable top-level task (the caller holds a row lock)."""
    task.run_number += 1
    await transition(
        session,
        task,
        TaskStatus.QUEUED,
        actor_type="user",
        actor_id=actor_id,
        extra={"run_number": task.run_number},
    )
    await enqueue(
        session,
        kind=JobKind.START,
        task_id=task.id,
        payload={"run_number": task.run_number},
        max_attempts=max_attempts,
    )
