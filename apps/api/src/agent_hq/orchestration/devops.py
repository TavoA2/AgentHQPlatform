"""DevOps specialist: read-only CI/CD review of one authorized repository."""

import json
import uuid
from dataclasses import dataclass

from pydantic import ValidationError

from agent_hq.agents import DEVOPS
from agent_hq.llm.base import ChatMessage, ModelRequest
from agent_hq.orchestration.prompts import DEVOPS_ANALYZE, wrap_untrusted
from agent_hq.orchestration.schemas import CicdAnalysis, CicdRecommendation, FileEvidence
from agent_hq.orchestration.usage import record_model_call
from agent_hq.runtime import Runtime
from agent_hq.tools import ToolContext, execute_tool, tool_schemas

MODEL_TOOLS = ["github.read_file", "github.list_workflow_runs"]


class SpecialistError(Exception):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class DevOpsAssignment:
    task_id: uuid.UUID
    project_id: uuid.UUID
    execution_id: uuid.UUID
    repository: str
    objective: str
    allowed_repos: frozenset[str]
    model_override: str | None


async def run_devops(runtime: Runtime, job: DevOpsAssignment) -> CicdRecommendation:
    ctx = ToolContext(
        runtime=runtime,
        task_id=job.task_id,
        project_id=job.project_id,
        execution_id=job.execution_id,
        agent_key=DEVOPS.key,
        allowed_repos=job.allowed_repos,
    )
    discovery = await execute_tool(ctx, "github.list_tree", {"repository": job.repository})
    if not discovery.ok or discovery.output is None:
        raise SpecialistError("repository_discovery_failed", discovery.error or "no output")
    candidates = [entry["path"] for entry in discovery.output["ci_relevant"]]

    resolved = runtime.models.resolve(
        agent_key=DEVOPS.key, profile=DEVOPS.model_profile, task_override=job.model_override
    )
    messages = [
        ChatMessage("system", DEVOPS_ANALYZE),
        ChatMessage(
            "user",
            json.dumps(
                {
                    "objective": job.objective,
                    "repository": job.repository,
                    "ci_relevant_files": candidates,
                    "total_files_in_repository": discovery.output["total_files"],
                }
            ),
        ),
    ]
    evidence: dict[str, FileEvidence] = {}

    for _ in range(runtime.settings.agent_max_steps):
        request = ModelRequest(
            purpose="devops.analyze",
            model=resolved.model,
            messages=messages,
            tools=tool_schemas(MODEL_TOOLS),
            output_schema=CicdAnalysis,
            hints={"repository": job.repository, "candidates": candidates},
        )
        response = await resolved.provider.complete(request)
        await record_model_call(
            runtime,
            execution_id=job.execution_id,
            task_id=job.task_id,
            project_id=job.project_id,
            agent_key=DEVOPS.key,
            purpose=request.purpose,
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
                if outcome.ok and call.name == "github.read_file" and outcome.output:
                    out = outcome.output
                    evidence[out["path"]] = FileEvidence(
                        path=out["path"], sha=out["sha"], size=out["size"]
                    )
                messages.append(
                    ChatMessage(
                        "tool",
                        wrap_untrusted(call.name, outcome.for_model()),
                        tool_call_id=call.id,
                    )
                )
            continue

        analysis = response.parsed
        if analysis is None:
            try:
                analysis = CicdAnalysis.model_validate_json(response.content)
            except ValidationError:
                messages.append(ChatMessage("assistant", response.content))
                messages.append(
                    ChatMessage("user", "Return only the final JSON analysis matching the schema.")
                )
                continue
        if not isinstance(analysis, CicdAnalysis):
            raise SpecialistError("model_output_invalid", "unexpected analysis type")
        return CicdRecommendation(
            **analysis.model_dump(),
            repository=job.repository,
            files_inspected=list(evidence.values()),
        )

    raise SpecialistError(
        "max_steps_exceeded", f"no final answer after {runtime.settings.agent_max_steps} steps"
    )
