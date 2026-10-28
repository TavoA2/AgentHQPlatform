"""Operational summary for the dashboard: computed from the database, never estimated."""

from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from agent_hq.api.deps import DbDep, PrincipalDep
from agent_hq.domain import ApprovalStatus, ExecutionStatus, JobStatus
from agent_hq.models import Agent, ApprovalRequest, Job, Task, TaskExecution, utcnow

router = APIRouter(prefix="/metrics", tags=["metrics"])

WINDOW = timedelta(hours=24)


class AgentUsage(BaseModel):
    key: str
    executions: int
    failed: int
    running: int
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal | None


class FailedJob(BaseModel):
    id: int
    task_id: str
    kind: str
    attempts: int
    last_error: str | None
    updated_at: datetime


class MetricsSummary(BaseModel):
    generated_at: datetime
    window_hours: int
    tasks_by_status: dict[str, int]
    subtasks_by_status: dict[str, int]
    jobs_by_status: dict[str, int]
    recent_failed_jobs: list[FailedJob]
    approvals_pending: int
    approval_median_seconds: float | None
    agents: list[AgentUsage]


@router.get("/summary")
async def summary(_: PrincipalDep, db: DbDep) -> MetricsSummary:
    since = utcnow() - WINDOW

    async def by_status(top_level: bool) -> dict[str, int]:
        condition = Task.parent_task_id.is_(None) if top_level else Task.parent_task_id.isnot(None)
        rows = await db.execute(
            select(Task.status, func.count()).where(condition).group_by(Task.status)
        )
        return {str(s.value): int(n) for s, n in rows}

    jobs = await db.execute(select(Job.status, func.count()).group_by(Job.status))
    failed_jobs = await db.scalars(
        select(Job).where(Job.status == JobStatus.FAILED).order_by(Job.updated_at.desc()).limit(10)
    )
    pending = await db.scalar(
        select(func.count()).where(ApprovalRequest.status == ApprovalStatus.PENDING)
    )
    median = await db.scalar(
        select(
            func.percentile_cont(0.5).within_group(
                func.extract("epoch", ApprovalRequest.decided_at - ApprovalRequest.created_at)
            )
        ).where(ApprovalRequest.decided_by.isnot(None), ApprovalRequest.decided_at >= since)
    )
    usage = await db.execute(
        select(
            Agent.key,
            func.count(TaskExecution.id),
            func.count().filter(TaskExecution.status == ExecutionStatus.FAILED),
            func.count().filter(TaskExecution.status == ExecutionStatus.RUNNING),
            func.coalesce(func.sum(TaskExecution.tokens_in), 0),
            func.coalesce(func.sum(TaskExecution.tokens_out), 0),
            func.sum(TaskExecution.cost_usd),
        )
        .select_from(Agent)
        .outerjoin(
            TaskExecution,
            (TaskExecution.agent_id == Agent.id) & (TaskExecution.started_at >= since),
        )
        .group_by(Agent.key)
        .order_by(Agent.key)
    )
    return MetricsSummary(
        generated_at=utcnow(),
        window_hours=int(WINDOW.total_seconds() // 3600),
        tasks_by_status=await by_status(True),
        subtasks_by_status=await by_status(False),
        jobs_by_status={str(s.value): int(n) for s, n in jobs},
        recent_failed_jobs=[
            FailedJob(
                id=j.id,
                task_id=str(j.task_id),
                kind=j.kind.value,
                attempts=j.attempts,
                last_error=(j.last_error or "")[:300] or None,
                updated_at=j.updated_at,
            )
            for j in failed_jobs
        ],
        approvals_pending=int(pending or 0),
        approval_median_seconds=float(median) if median is not None else None,
        agents=[
            AgentUsage(
                key=key,
                executions=int(n),
                failed=int(failed),
                running=int(running),
                tokens_in=int(tin),
                tokens_out=int(tout),
                cost_usd=cost,
            )
            for key, n, failed, running, tin, tout, cost in usage
        ],
    )
