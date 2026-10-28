import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import exists, select, update

from agent_hq.agents import CIO
from agent_hq.api.deps import DbDep, PrincipalDep, SettingsDep
from agent_hq.api.schemas import (
    EventOut,
    TaskDetailOut,
    TaskIn,
    TaskOut,
    approval_out,
    execution_out,
)
from agent_hq.domain import CANCELLABLE, STARTABLE, JobKind, JobStatus, TaskStatus
from agent_hq.events import record_audit
from agent_hq.jobs import enqueue
from agent_hq.models import (
    Agent,
    ApprovalRequest,
    Job,
    Project,
    Task,
    TaskEvent,
    TaskExecution,
)
from agent_hq.security.approvals import cancel_open_for_task
from agent_hq.tasks import transition

router = APIRouter(prefix="/tasks", tags=["tasks"])


async def _agent_keys(db: DbDep) -> dict[uuid.UUID, str]:
    return {a.id: a.key for a in await db.scalars(select(Agent))}


def _task_out(task: Task, keys: dict[uuid.UUID, str]) -> TaskOut:
    out = TaskOut.model_validate(task)
    out.assigned_agent_key = keys.get(task.assigned_agent_id) if task.assigned_agent_id else None
    return out


async def _get_task(db: DbDep, task_id: uuid.UUID, *, lock: bool = False) -> Task:
    task = await db.get(Task, task_id, with_for_update=lock, populate_existing=lock)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    return task


@router.get("")
async def list_tasks(
    _: PrincipalDep,
    db: DbDep,
    project_id: uuid.UUID | None = None,
    status_: Annotated[list[TaskStatus] | None, Query(alias="status")] = None,
    agent: str | None = None,
    include_subtasks: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TaskOut]:
    query = select(Task).order_by(Task.created_at.desc()).limit(limit).offset(offset)
    if not include_subtasks:
        query = query.where(Task.parent_task_id.is_(None))
    if project_id:
        query = query.where(Task.project_id == project_id)
    if status_:
        query = query.where(Task.status.in_(status_))
    if agent:
        agent_id = select(Agent.id).where(Agent.key == agent).scalar_subquery()
        query = query.where(
            (Task.assigned_agent_id == agent_id)
            | exists().where(TaskExecution.task_id == Task.id, TaskExecution.agent_id == agent_id)
        )
    keys = await _agent_keys(db)
    return [_task_out(t, keys) for t in await db.scalars(query)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_task(body: TaskIn, principal: PrincipalDep, db: DbDep) -> TaskOut:
    if await db.get(Project, body.project_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    cio_id = await db.scalar(select(Agent.id).where(Agent.key == CIO.key))
    task = Task(
        project_id=body.project_id,
        title=body.title,
        request=body.request,
        status=TaskStatus.DRAFT,
        assigned_agent_id=cio_id,
        created_by=principal.user.id,
        acceptance_criteria=body.acceptance_criteria,
        options={"model_override": body.model_override} if body.model_override else {},
    )
    db.add(task)
    await db.flush()
    await record_audit(
        db,
        actor_type="user",
        actor_id=str(principal.user.id),
        action="task.created",
        project_id=task.project_id,
        resource_type="task",
        resource_id=task.id,
        details={"title": task.title},
    )
    await db.commit()
    return _task_out(task, await _agent_keys(db))


@router.get("/{task_id}")
async def get_task(task_id: uuid.UUID, _: PrincipalDep, db: DbDep) -> TaskDetailOut:
    task = await _get_task(db, task_id)
    keys = await _agent_keys(db)
    subtasks = list(
        await db.scalars(
            select(Task).where(Task.parent_task_id == task.id).order_by(Task.created_at)
        )
    )
    executions = await db.scalars(
        select(TaskExecution)
        .where(TaskExecution.task_id.in_([task.id, *(s.id for s in subtasks)]))
        .order_by(TaskExecution.started_at)
    )
    approvals = await db.scalars(
        select(ApprovalRequest)
        .where(ApprovalRequest.task_id == task.id)
        .order_by(ApprovalRequest.created_at)
    )
    return TaskDetailOut(
        **_task_out(task, keys).model_dump(),
        executions=[execution_out(e, keys) for e in executions],
        approvals=[approval_out(a, keys) for a in approvals],
        subtasks=[_task_out(s, keys) for s in subtasks],
    )


@router.get("/{task_id}/events")
async def task_events(
    task_id: uuid.UUID,
    _: PrincipalDep,
    db: DbDep,
    after_id: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
) -> list[EventOut]:
    await _get_task(db, task_id)
    children = select(Task.id).where(Task.parent_task_id == task_id)
    rows = await db.scalars(
        select(TaskEvent)
        .where(
            (TaskEvent.task_id == task_id) | TaskEvent.task_id.in_(children),
            TaskEvent.id > after_id,
        )
        .order_by(TaskEvent.id)
        .limit(limit)
    )
    return [EventOut.model_validate(e) for e in rows]


@router.post("/{task_id}/start")
async def start_task(
    task_id: uuid.UUID, principal: PrincipalDep, db: DbDep, settings: SettingsDep
) -> TaskOut:
    task = await _get_task(db, task_id, lock=True)
    if task.parent_task_id is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "subtasks are run by their parent task")
    if task.status not in STARTABLE:
        raise HTTPException(status.HTTP_409_CONFLICT, f"task cannot be started from {task.status}")
    task.run_number += 1
    await transition(
        db,
        task,
        TaskStatus.QUEUED,
        actor_type="user",
        actor_id=str(principal.user.id),
        extra={"run_number": task.run_number},
    )
    await enqueue(
        db,
        kind=JobKind.START,
        task_id=task.id,
        payload={"run_number": task.run_number},
        max_attempts=settings.job_max_attempts,
    )
    await db.commit()
    return _task_out(task, await _agent_keys(db))


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: uuid.UUID, principal: PrincipalDep, db: DbDep) -> TaskOut:
    task = await _get_task(db, task_id, lock=True)
    if task.status not in CANCELLABLE:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"task cannot be cancelled from {task.status}"
        )
    await transition(
        db,
        task,
        TaskStatus.CANCELLED,
        actor_type="user",
        actor_id=str(principal.user.id),
        reason="cancelled_by_user",
    )
    await cancel_open_for_task(db, task.id)
    subtasks = await db.scalars(
        select(Task).where(Task.parent_task_id == task.id).with_for_update()
    )
    for subtask in subtasks:
        if subtask.status in CANCELLABLE:
            await transition(
                db,
                subtask,
                TaskStatus.CANCELLED,
                actor_type="user",
                actor_id=str(principal.user.id),
                reason="parent_cancelled",
            )
    # A running graph notices the cancellation at its next step; queued work is dropped.
    await db.execute(
        update(Job)
        .where(Job.task_id == task.id, Job.status == JobStatus.QUEUED)
        .values(status=JobStatus.FAILED, last_error="task cancelled")
    )
    await db.commit()
    return _task_out(task, await _agent_keys(db))
