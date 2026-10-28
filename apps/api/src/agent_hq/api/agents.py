import uuid

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_hq.agents import REGISTRY
from agent_hq.api.deps import DbDep, PrincipalDep
from agent_hq.api.schemas import AgentOut, execution_out
from agent_hq.domain import AgentStatus, ExecutionStatus, TaskStatus
from agent_hq.models import Agent, Task, TaskExecution

router = APIRouter(prefix="/agents", tags=["agents"])


async def derive_agent_statuses(db: AsyncSession) -> list[AgentOut]:
    """Status comes only from recorded executions; nothing here is simulated."""
    agents = list(await db.scalars(select(Agent).order_by(Agent.created_at)))
    keys = {a.id: a.key for a in agents}
    latest = await db.execute(
        select(TaskExecution, Task.status)
        .join(Task, Task.id == TaskExecution.task_id)
        .distinct(TaskExecution.agent_id)
        .order_by(TaskExecution.agent_id, TaskExecution.started_at.desc())
    )
    by_agent: dict[uuid.UUID, tuple[TaskExecution, TaskStatus]] = {
        e.agent_id: (e, status) for e, status in latest
    }
    out = []
    for agent in agents:
        definition = REGISTRY.get(agent.key)
        execution, task_status = by_agent.get(agent.id, (None, None))
        status = AgentStatus.IDLE
        current_task = None
        if execution is not None:
            if execution.status == ExecutionStatus.RUNNING:
                status = (
                    AgentStatus.WAITING_APPROVAL
                    if task_status == TaskStatus.WAITING_APPROVAL
                    else AgentStatus.RUNNING
                )
                current_task = execution.task_id
            elif execution.status == ExecutionStatus.FAILED:
                status = AgentStatus.FAILED
                current_task = execution.task_id
        out.append(
            AgentOut(
                key=agent.key,
                display_name=agent.display_name,
                department=agent.department,
                description=str(agent.config.get("description", "")),
                model_profile=agent.model_profile,
                enabled=agent.enabled,
                status=status,
                current_task_id=current_task,
                last_execution=execution_out(execution, keys) if execution else None,
                allowed_tools=sorted(definition.allowed_tools) if definition else [],
            )
        )
    return out


@router.get("")
async def list_agents(_: PrincipalDep, db: DbDep) -> list[AgentOut]:
    return await derive_agent_statuses(db)
