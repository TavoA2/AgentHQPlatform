"""Bounded tool-use loop shared by specialist agents."""

import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from agent_hq.agents import AgentDefinition
from agent_hq.llm.base import ChatMessage, ModelRequest
from agent_hq.orchestration.prompts import wrap_untrusted
from agent_hq.orchestration.usage import record_model_call
from agent_hq.runtime import Runtime
from agent_hq.tools import ToolContext, ToolOutcome, execute_tool, tool_schemas


class SpecialistError(Exception):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class ToolObservation:
    name: str
    arguments: dict[str, Any]
    outcome: ToolOutcome


async def run_agent_loop[T: BaseModel](
    runtime: Runtime,
    ctx: ToolContext,
    *,
    agent: AgentDefinition,
    purpose: str,
    messages: list[ChatMessage],
    tool_names: list[str],
    output_schema: type[T],
    hints: dict[str, Any],
    model_override: str | None,
) -> tuple[T, list[ToolObservation]]:
    """Let the model call tools (each policy-checked) until it returns `output_schema`."""
    resolved = runtime.models.resolve(
        agent_key=agent.key, profile=agent.model_profile, task_override=model_override
    )
    observations: list[ToolObservation] = []
    messages = list(messages)
    for _ in range(runtime.settings.agent_max_steps):
        request = ModelRequest(
            purpose=purpose,
            model=resolved.model,
            messages=messages,
            tools=tool_schemas(tool_names),
            output_schema=output_schema,
            hints=hints,
        )
        response = await resolved.provider.complete(request)
        await record_model_call(
            runtime,
            execution_id=ctx.execution_id,
            task_id=ctx.task_id,
            project_id=ctx.project_id,
            agent_key=agent.key,
            purpose=purpose,
            resolved=resolved,
            usage=response.usage,
        )
        if response.tool_calls:
            messages.append(
                ChatMessage("assistant", response.content, tool_calls=tuple(response.tool_calls))
            )
            for call in response.tool_calls:
                # Any tool name the model produces goes through the same policy checks.
                outcome = await execute_tool(ctx, call.name, call.arguments)
                observations.append(ToolObservation(call.name, call.arguments, outcome))
                messages.append(
                    ChatMessage(
                        "tool", wrap_untrusted(call.name, outcome.for_model()), tool_call_id=call.id
                    )
                )
            continue

        parsed = response.parsed
        if not isinstance(parsed, output_schema):
            try:
                parsed = output_schema.model_validate_json(response.content)
            except ValidationError:
                messages.append(ChatMessage("assistant", response.content))
                messages.append(
                    ChatMessage("user", "Return only the final JSON answer matching the schema.")
                )
                continue
        return parsed, observations

    raise SpecialistError(
        "max_steps_exceeded", f"no final answer after {runtime.settings.agent_max_steps} steps"
    )


def new_context(
    runtime: Runtime,
    *,
    task_id: uuid.UUID,
    project_id: uuid.UUID,
    execution_id: uuid.UUID,
    agent_key: str,
    allowed_repos: frozenset[str],
) -> ToolContext:
    return ToolContext(
        runtime=runtime,
        task_id=task_id,
        project_id=project_id,
        execution_id=execution_id,
        agent_key=agent_key,
        allowed_repos=allowed_repos,
    )
