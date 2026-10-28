"""Specialist step runners: DevOps review, implementation, test planning, test execution.

Each runner returns a JSON-able output. Evidence fields are filled by code from real tool
results, never taken from model text.
"""

import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from agent_hq.agents import DEVOPS, QA, SOFTWARE_ENGINEER
from agent_hq.llm.base import ChatMessage, ModelRequest
from agent_hq.orchestration import prompts
from agent_hq.orchestration.agent_loop import SpecialistError, new_context, run_agent_loop
from agent_hq.orchestration.schemas import (
    Changeset,
    CicdAnalysis,
    CicdRecommendation,
    FileEvidence,
    PlanStep,
    QaReport,
    TestPlan,
)
from agent_hq.orchestration.usage import record_model_call
from agent_hq.runtime import Runtime
from agent_hq.tools import ToolContext, execute_tool


@dataclass(frozen=True)
class StepContext:
    task_id: uuid.UUID  # parent task: events and tool calls are recorded here
    project_id: uuid.UUID
    execution_id: uuid.UUID
    step: PlanStep
    repository: str
    allowed_repos: frozenset[str]
    request: str
    acceptance_criteria: list[str]
    model_override: str | None
    prior: dict[str, dict[str, Any]]  # outputs of the steps this one depends on


def _tool_context(runtime: Runtime, sc: StepContext) -> ToolContext:
    return new_context(
        runtime,
        task_id=sc.task_id,
        project_id=sc.project_id,
        execution_id=sc.execution_id,
        agent_key=sc.step.agent_key,
        allowed_repos=sc.allowed_repos,
    )


async def _discover(ctx: ToolContext, repository: str) -> dict[str, Any]:
    discovery = await execute_tool(ctx, "github.list_tree", {"repository": repository})
    if not discovery.ok or discovery.output is None:
        raise SpecialistError("repository_discovery_failed", discovery.error or "no output")
    return discovery.output


def _latest(sc: StepContext, kind: str) -> dict[str, Any]:
    for step_id in reversed(sc.step.depends_on):
        output = sc.prior.get(step_id)
        if output is not None and output.get("_kind") == kind:
            return output
    raise SpecialistError("missing_dependency", f"step {sc.step.id} needs a {kind} result")


async def run_cicd_review(runtime: Runtime, sc: StepContext) -> dict[str, Any]:
    ctx = _tool_context(runtime, sc)
    tree = await _discover(ctx, sc.repository)
    candidates = [entry["path"] for entry in tree["ci_relevant"]]
    messages = [
        ChatMessage("system", prompts.DEVOPS_ANALYZE),
        ChatMessage(
            "user",
            json.dumps(
                {
                    "objective": sc.step.objective,
                    "repository": sc.repository,
                    "ci_relevant_files": candidates,
                    "total_files_in_repository": tree["total_files"],
                }
            ),
        ),
    ]
    analysis, observations = await run_agent_loop(
        runtime,
        ctx,
        agent=DEVOPS,
        purpose="devops.analyze",
        messages=messages,
        tool_names=["github.read_file", "github.list_workflow_runs", "knowledge.search"],
        output_schema=CicdAnalysis,
        hints={"repository": sc.repository, "candidates": candidates},
        model_override=sc.model_override,
    )
    evidence: dict[str, FileEvidence] = {}
    for obs in observations:
        if obs.name == "github.read_file" and obs.outcome.ok and obs.outcome.output:
            out = obs.outcome.output
            evidence[out["path"]] = FileEvidence(path=out["path"], sha=out["sha"], size=out["size"])
    recommendation = CicdRecommendation(
        **analysis.model_dump(),
        repository=sc.repository,
        files_inspected=list(evidence.values()),
    )
    return recommendation.model_dump(mode="json")


async def run_implement(runtime: Runtime, sc: StepContext) -> dict[str, Any]:
    ctx = _tool_context(runtime, sc)
    tree = await _discover(ctx, sc.repository)
    payload: dict[str, Any] = {
        "objective": sc.step.objective,
        "request": sc.request,
        "acceptance_criteria": sc.acceptance_criteria,
        "repository": sc.repository,
        "source_files": tree["source_files"],
    }
    if sc.step.feedback:
        payload["qa_feedback"] = sc.step.feedback
    changeset, observations = await run_agent_loop(
        runtime,
        ctx,
        agent=SOFTWARE_ENGINEER,
        purpose="swe.implement",
        messages=[
            ChatMessage("system", prompts.SWE_IMPLEMENT),
            ChatMessage("user", json.dumps(payload)),
        ],
        tool_names=["github.read_source", "knowledge.search", "knowledge.propose"],
        output_schema=Changeset,
        hints={
            "repository": sc.repository,
            "request": sc.request,
            "feedback": sc.step.feedback,
            "source_files": tree["source_files"],
        },
        model_override=sc.model_override,
    )
    files_read = sorted(
        obs.outcome.output["path"]
        for obs in observations
        if obs.name == "github.read_source" and obs.outcome.ok and obs.outcome.output
    )
    return {
        **changeset.model_dump(mode="json"),
        "repository": sc.repository,
        "files_read": files_read,
    }


async def run_test_plan(runtime: Runtime, sc: StepContext) -> dict[str, Any]:
    resolved = runtime.models.resolve(
        agent_key=QA.key, profile=QA.model_profile, task_override=sc.model_override
    )
    request = ModelRequest(
        purpose="qa.test_plan",
        model=resolved.model,
        messages=[
            ChatMessage("system", prompts.QA_TEST_PLAN),
            ChatMessage(
                "user",
                json.dumps({"request": sc.request, "acceptance_criteria": sc.acceptance_criteria}),
            ),
        ],
        output_schema=TestPlan,
        hints={"request": sc.request, "acceptance_criteria": sc.acceptance_criteria},
    )
    response = await resolved.provider.complete(request)
    await record_model_call(
        runtime,
        execution_id=sc.execution_id,
        task_id=sc.task_id,
        project_id=sc.project_id,
        agent_key=QA.key,
        purpose=request.purpose,
        resolved=resolved,
        usage=response.usage,
    )
    if not isinstance(response.parsed, TestPlan):
        raise SpecialistError("model_output_invalid", "test plan could not be parsed")
    return response.parsed.model_dump(mode="json")


async def run_tests(runtime: Runtime, sc: StepContext) -> dict[str, Any]:
    changeset = Changeset.model_validate(_latest(sc, "implement"))
    plan = TestPlan.model_validate(_latest(sc, "test_plan"))
    ctx = _tool_context(runtime, sc)
    ctx.workspace_overlay = {f.path: f.content for f in [*changeset.files, *changeset.tests]}
    report, _ = await run_agent_loop(
        runtime,
        ctx,
        agent=QA,
        purpose="qa.run_tests",
        messages=[
            ChatMessage("system", prompts.QA_RUN),
            ChatMessage(
                "user",
                json.dumps(
                    {
                        "repository": sc.repository,
                        "test_plan": plan.model_dump(),
                        "changeset_summary": changeset.summary,
                        "proposed_files": sorted(ctx.workspace_overlay),
                    }
                ),
            ),
        ],
        tool_names=["sandbox.run_tests", "github.read_source", "knowledge.search"],
        output_schema=QaReport,
        hints={"repository": sc.repository},
        model_override=sc.model_override,
    )
    # The sandbox result recorded by code is the source of truth, not the model's words.
    sandbox = ctx.sandbox_results[-1].model_dump() if ctx.sandbox_results else None
    return {"report": report.model_dump(mode="json"), "sandbox": sandbox}


StepRunner = Callable[[Runtime, StepContext], Awaitable[dict[str, Any]]]

RUNNERS: dict[str, StepRunner] = {
    "cicd_review": run_cicd_review,
    "implement": run_implement,
    "test_plan": run_test_plan,
    "run_tests": run_tests,
}
