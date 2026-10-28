"""Task status transitions: the only code path that changes `tasks.status`."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from agent_hq.domain import TaskStatus, check_transition
from agent_hq.events import ActorType, record_audit, record_task_event
from agent_hq.models import Task, utcnow


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
