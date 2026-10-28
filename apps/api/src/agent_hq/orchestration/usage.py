"""Records model calls on executions (tokens, cost) and as task events."""

import uuid
from decimal import Decimal

from agent_hq.events import record_task_event
from agent_hq.llm.base import Usage
from agent_hq.llm.router import ResolvedModel
from agent_hq.models import TaskExecution
from agent_hq.runtime import Runtime


async def record_model_call(
    runtime: Runtime,
    *,
    execution_id: uuid.UUID,
    task_id: uuid.UUID,
    project_id: uuid.UUID,
    agent_key: str,
    purpose: str,
    resolved: ResolvedModel,
    usage: Usage,
) -> None:
    cost = runtime.models.cost(resolved.model, usage)
    async with runtime.sessionmaker() as session:
        execution = await session.get(TaskExecution, execution_id, with_for_update=True)
        if execution is not None:
            execution.model_provider = resolved.provider_name
            execution.model_name = resolved.model
            execution.model_calls += 1
            execution.tokens_in += usage.input_tokens
            execution.tokens_out += usage.output_tokens
            if cost is not None:
                execution.cost_usd = (execution.cost_usd or Decimal(0)) + cost
        await record_task_event(
            session,
            task_id=task_id,
            project_id=project_id,
            execution_id=execution_id,
            agent_key=agent_key,
            type="model_called",
            payload={
                "purpose": purpose,
                "provider": resolved.provider_name,
                "model": resolved.model,
                "tokens_in": usage.input_tokens,
                "tokens_out": usage.output_tokens,
                "cost_usd": str(cost) if cost is not None else None,
            },
        )
        await session.commit()
