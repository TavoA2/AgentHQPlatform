"""AI CIO workflow: a fixed, checkpointed LangGraph graph (docs/architecture/agents.md).

Every node is safe to re-execute: LangGraph re-runs a node after a crash and re-runs the
approval node from its start on resume, so database effects are written idempotently
(status transitions are no-ops when already applied; approvals are looked up by hash).
"""

import hashlib
import json
import uuid
from datetime import timedelta
from typing import Any, Literal, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_hq.agents import CIO, DEVOPS
from agent_hq.domain import (
    ApprovalStatus,
    ExecutionStatus,
    RiskLevel,
    TaskCancelledError,
    TaskStatus,
)
from agent_hq.events import record_task_event
from agent_hq.llm.base import ChatMessage, ModelRequest
from agent_hq.models import (
    Agent,
    ApprovalRequest,
    Integration,
    Project,
    Task,
    TaskExecution,
    utcnow,
)
from agent_hq.orchestration import prompts
from agent_hq.orchestration.devops import DevOpsAssignment, SpecialistError, run_devops
from agent_hq.orchestration.schemas import (
    CicdRecommendation,
    OutcomeSummary,
    Requirements,
    VerificationResult,
)
from agent_hq.orchestration.usage import record_model_call
from agent_hq.orchestration.verify import verify_recommendation
from agent_hq.runtime import Runtime
from agent_hq.security.approvals import request_approval
from agent_hq.security.policy import PolicyDenied, authorize_delegation, authorize_repository
from agent_hq.tasks import transition
from agent_hq.tools import PublishReportArgs, ToolContext, approval_action, execute_tool

MAX_SPECIALIST_ATTEMPTS = 2


class CioState(TypedDict, total=False):
    task_id: str
    project_id: str
    run_number: int
    request: str
    acceptance_criteria: list[str]
    model_override: str | None
    cio_execution_id: str
    allowed_repos: list[str]
    requirements: dict[str, Any]
    plan: dict[str, Any]
    specialist_attempts: int
    specialist_result: dict[str, Any] | None
    verification: dict[str, Any]
    approval_id: str
    publish_args: dict[str, Any]
    publication: dict[str, Any]
    summary: dict[str, Any]
    error: dict[str, Any] | None


def initial_state(task: Task) -> CioState:
    return CioState(
        task_id=str(task.id),
        project_id=str(task.project_id),
        run_number=task.run_number,
        request=task.request,
        acceptance_criteria=[str(c) for c in task.acceptance_criteria],
        model_override=task.options.get("model_override"),
        specialist_attempts=0,
        error=None,
    )


def thread_id(task_id: uuid.UUID, run_number: int) -> str:
    return f"{task_id}:{run_number}"


def _ids(state: CioState) -> tuple[uuid.UUID, uuid.UUID]:
    return uuid.UUID(state["task_id"]), uuid.UUID(state["project_id"])


async def _locked_task(session: AsyncSession, task_id: uuid.UUID) -> Task:
    task = await session.get(Task, task_id, with_for_update=True, populate_existing=True)
    if task is None:
        raise TaskCancelledError("task no longer exists")
    if task.status == TaskStatus.CANCELLED:
        raise TaskCancelledError("task was cancelled")
    return task


async def _agent_id(session: AsyncSession, key: str) -> uuid.UUID:
    agent_id = await session.scalar(select(Agent.id).where(Agent.key == key))
    if agent_id is None:
        raise RuntimeError(f"agent {key!r} is not seeded")
    return agent_id


async def _step(session: AsyncSession, state: CioState, node: str, **payload: Any) -> None:
    task_id, project_id = _ids(state)
    await record_task_event(
        session,
        task_id=task_id,
        project_id=project_id,
        execution_id=uuid.UUID(state["cio_execution_id"]) if "cio_execution_id" in state else None,
        agent_key=CIO.key,
        type="step",
        payload={"node": node, **payload},
    )


async def _open_execution(
    session: AsyncSession,
    task: Task,
    agent_key: str,
    *,
    attempt: int | None = None,
    input: dict[str, Any] | None = None,
) -> TaskExecution:
    agent_id = await _agent_id(session, agent_key)
    if attempt is None:
        running = await session.scalar(
            select(TaskExecution).where(
                TaskExecution.task_id == task.id,
                TaskExecution.agent_id == agent_id,
                TaskExecution.run_number == task.run_number,
                TaskExecution.status == ExecutionStatus.RUNNING,
            )
        )
        if running is not None:
            return running
        previous = await session.scalar(
            select(func.count()).where(
                TaskExecution.task_id == task.id,
                TaskExecution.agent_id == agent_id,
                TaskExecution.run_number == task.run_number,
            )
        )
        attempt = (previous or 0) + 1
    execution = TaskExecution(
        task_id=task.id,
        agent_id=agent_id,
        run_number=task.run_number,
        attempt=attempt,
        status=ExecutionStatus.RUNNING,
        graph_thread_id=thread_id(task.id, task.run_number),
        input=input or {},
    )
    session.add(execution)
    await session.flush()
    await record_task_event(
        session,
        task_id=task.id,
        project_id=task.project_id,
        execution_id=execution.id,
        agent_key=agent_key,
        type="execution_started",
        payload={"attempt": attempt},
    )
    return execution


async def _close_execution(
    session: AsyncSession,
    execution: TaskExecution,
    status: ExecutionStatus,
    *,
    agent_key: str,
    project_id: uuid.UUID,
    output: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> None:
    execution.status = status
    execution.finished_at = utcnow()
    execution.output = output
    execution.error = error
    await session.flush()
    await record_task_event(
        session,
        task_id=execution.task_id,
        project_id=project_id,
        execution_id=execution.id,
        agent_key=agent_key,
        type="execution_finished",
        payload={"status": status.value},
    )


async def close_running_executions(
    session: AsyncSession, task: Task, status: ExecutionStatus, error: dict[str, Any] | None
) -> None:
    keys = {a.id: a.key for a in await session.scalars(select(Agent))}
    running = await session.scalars(
        select(TaskExecution).where(
            TaskExecution.task_id == task.id, TaskExecution.status == ExecutionStatus.RUNNING
        )
    )
    for execution in running:
        await _close_execution(
            session,
            execution,
            status,
            agent_key=keys[execution.agent_id],
            project_id=task.project_id,
            error=error,
        )


def build_cio_graph(
    runtime: Runtime, checkpointer: BaseCheckpointSaver[Any]
) -> CompiledStateGraph[CioState, None, CioState, CioState]:
    sm = runtime.sessionmaker

    async def intake(state: CioState) -> CioState:
        task_id, _ = _ids(state)
        async with sm() as session:
            task = await _locked_task(session, task_id)
            await transition(
                session,
                task,
                TaskStatus.RUNNING,
                actor_type="agent",
                actor_id=CIO.key,
                agent_key=CIO.key,
            )
            execution = await _open_execution(
                session, task, CIO.key, input={"request": state["request"]}
            )
            integration = await session.scalar(
                select(Integration).where(
                    Integration.project_id == task.project_id,
                    Integration.provider == "github",
                    Integration.enabled.is_(True),
                )
            )
            allowed = list(integration.config.get("allowed_repos", [])) if integration else []
            state = {**state, "cio_execution_id": str(execution.id)}
            await _step(session, state, "intake", authorized_repositories=allowed)
            await session.commit()
        return {"cio_execution_id": str(execution.id), "allowed_repos": allowed}

    async def analyze(state: CioState) -> CioState:
        task_id, project_id = _ids(state)
        allowed = state.get("allowed_repos", [])
        resolved = runtime.models.resolve(
            agent_key=CIO.key, profile=CIO.model_profile, task_override=state.get("model_override")
        )
        request = ModelRequest(
            purpose="cio.analyze",
            model=resolved.model,
            messages=[
                ChatMessage(
                    "system", prompts.CIO_ANALYZE.format(brand=runtime.settings.brand_name)
                ),
                ChatMessage(
                    "user",
                    json.dumps(
                        {
                            "request": state["request"],
                            "acceptance_criteria": state.get("acceptance_criteria", []),
                            "authorized_repositories": allowed,
                        }
                    ),
                ),
            ],
            output_schema=Requirements,
            hints={"request": state["request"], "allowed_repos": allowed},
        )
        response = await resolved.provider.complete(request)
        await record_model_call(
            runtime,
            execution_id=uuid.UUID(state["cio_execution_id"]),
            task_id=task_id,
            project_id=project_id,
            agent_key=CIO.key,
            purpose=request.purpose,
            resolved=resolved,
            usage=response.usage,
        )
        parsed = response.parsed
        if not isinstance(parsed, Requirements):
            return {
                "error": {"reason": "model_output_invalid", "detail": "requirements not parsed"}
            }
        requirements = parsed
        missing = list(requirements.missing_information)
        repository: str | None = None
        if not allowed:
            missing.append("No GitHub repository is authorized for this project.")
        elif requirements.repository:
            try:
                repository = authorize_repository(requirements.repository, allowed)
            except PolicyDenied as exc:
                missing.append(f"{exc.reason}. Authorized: {', '.join(allowed)}.")
        elif len(allowed) == 1:
            repository = allowed[0]
        else:
            missing.append(f"Which repository should be analyzed? Options: {', '.join(allowed)}.")
        result = {
            **requirements.model_dump(),
            "repository": repository,
            "missing_information": missing,
        }
        async with sm() as session:
            await _locked_task(session, task_id)
            await _step(session, state, "analyze", requirements=result)
            await session.commit()
        if missing:
            return {
                "requirements": result,
                "error": {"reason": "clarification_required", "detail": " ".join(missing)},
            }
        return {"requirements": result}

    async def plan(state: CioState) -> CioState:
        task_id, _ = _ids(state)
        authorize_delegation(CIO.key, DEVOPS.key)
        requirements = state["requirements"]
        objectives = "; ".join(requirements.get("objectives") or ["Review CI/CD"])
        the_plan = {
            "steps": [
                {
                    "agent_key": DEVOPS.key,
                    "objective": f"Analyze the CI/CD pipeline of {requirements['repository']}: "
                    f"{objectives}",
                    "repository": requirements["repository"],
                }
            ],
            "verification": "deterministic evidence checks",
            "sensitive_actions": ["report.publish_external (requires human approval)"],
        }
        async with sm() as session:
            await _locked_task(session, task_id)
            await _step(session, state, "plan", plan=the_plan)
            await record_task_event(
                session,
                task_id=task_id,
                project_id=uuid.UUID(state["project_id"]),
                agent_key=CIO.key,
                type="agent_selected",
                payload={"agent": DEVOPS.key},
            )
            await session.commit()
        return {"plan": the_plan}

    async def execute_specialist(state: CioState) -> CioState:
        task_id, project_id = _ids(state)
        step = state["plan"]["steps"][0]
        attempts = state.get("specialist_attempts", 0) + 1
        async with sm() as session:
            task = await _locked_task(session, task_id)
            devops_id = await _agent_id(session, DEVOPS.key)
            # A specialist execution left running by a crashed worker is closed first.
            stale = await session.scalars(
                select(TaskExecution).where(
                    TaskExecution.task_id == task_id,
                    TaskExecution.agent_id == devops_id,
                    TaskExecution.status == ExecutionStatus.RUNNING,
                )
            )
            for execution in stale:
                await _close_execution(
                    session,
                    execution,
                    ExecutionStatus.FAILED,
                    agent_key=DEVOPS.key,
                    project_id=project_id,
                    error={"reason": "interrupted"},
                )
            previous = await session.scalar(
                select(func.count()).where(
                    TaskExecution.task_id == task_id,
                    TaskExecution.agent_id == devops_id,
                    TaskExecution.run_number == task.run_number,
                )
            )
            execution = await _open_execution(
                session, task, DEVOPS.key, attempt=(previous or 0) + 1, input=step
            )
            await session.commit()
        try:
            recommendation = await run_devops(
                runtime,
                DevOpsAssignment(
                    task_id=task_id,
                    project_id=project_id,
                    execution_id=execution.id,
                    repository=step["repository"],
                    objective=step["objective"],
                    allowed_repos=frozenset(state.get("allowed_repos", [])),
                    model_override=state.get("model_override"),
                ),
            )
        except SpecialistError as exc:
            async with sm() as session:
                row = await session.get(TaskExecution, execution.id)
                if row is None:
                    raise RuntimeError("row not found") from exc
                await _close_execution(
                    session,
                    row,
                    ExecutionStatus.FAILED,
                    agent_key=DEVOPS.key,
                    project_id=project_id,
                    error={"reason": exc.reason, "detail": exc.detail},
                )
                await session.commit()
            return {
                "specialist_attempts": attempts,
                "specialist_result": None,
                "error": {"reason": exc.reason, "detail": exc.detail},
            }
        result = recommendation.model_dump(mode="json")
        async with sm() as session:
            row = await session.get(TaskExecution, execution.id)
            if row is None:
                raise RuntimeError("row not found")
            await _close_execution(
                session,
                row,
                ExecutionStatus.SUCCEEDED,
                agent_key=DEVOPS.key,
                project_id=project_id,
                output=result,
            )
            await session.commit()
        return {"specialist_attempts": attempts, "specialist_result": result, "error": None}

    async def verify(state: CioState) -> CioState:
        task_id, _ = _ids(state)
        if state.get("error"):
            return {}
        recommendation = CicdRecommendation.model_validate(state["specialist_result"])
        result = verify_recommendation(
            recommendation, allowed_repos=frozenset(state.get("allowed_repos", []))
        )
        async with sm() as session:
            await _locked_task(session, task_id)
            await _step(session, state, "verify", **result.model_dump())
            await session.commit()
        update_: CioState = {"verification": result.model_dump()}
        if not result.passed and state.get("specialist_attempts", 0) >= MAX_SPECIALIST_ATTEMPTS:
            update_["error"] = {
                "reason": "verification_failed",
                "detail": "; ".join(result.problems),
            }
        return update_

    def after_verify(state: CioState) -> Literal["fail", "execute_specialist", "request_approval"]:
        if state.get("error"):
            return "fail"
        if VerificationResult.model_validate(state["verification"]).passed:
            return "request_approval"
        return "execute_specialist"

    async def approval_gate(state: CioState) -> CioState:
        task_id, project_id = _ids(state)
        report_json = json.dumps(state["specialist_result"], sort_keys=True)
        async with sm() as session:
            task = await _locked_task(session, task_id)
            project = await session.get(Project, project_id)
            if project is None:
                raise RuntimeError("project not found")
            args = PublishReportArgs(
                target=f"mock://reports/{project.key}",
                task_id=str(task_id),
                run_number=state["run_number"],
                report_sha256=hashlib.sha256(report_json.encode()).hexdigest(),
            )
            action = approval_action("report.publish_external", args)
            recommendation = CicdRecommendation.model_validate(state["specialist_result"])
            approval = await request_approval(
                session,
                task=task,
                execution_id=uuid.UUID(state["cio_execution_id"]),
                agent_id=await _agent_id(session, CIO.key),
                agent_key=CIO.key,
                action_type=action.action_type,
                target=action.target,
                parameters=action.parameters,
                justification=(
                    "Share the verified CI/CD review of "
                    f"{recommendation.repository} with stakeholders."
                ),
                expected_impact=(
                    f"Publishes a report with {len(recommendation.findings)} findings and "
                    f"{len(recommendation.recommendations)} recommendations. Mock adapter: no "
                    "external system is contacted in Sprint 1."
                ),
                risk_level=RiskLevel.LOW,
                evidence={
                    "files_inspected": [f.model_dump() for f in recommendation.files_inspected],
                    "verification": state["verification"],
                    "report_sha256": args.report_sha256,
                },
                ttl=timedelta(hours=runtime.settings.approval_ttl_hours),
            )
            pending = approval.status == ApprovalStatus.PENDING
            if pending:
                await transition(
                    session,
                    task,
                    TaskStatus.WAITING_APPROVAL,
                    actor_type="agent",
                    actor_id=CIO.key,
                    agent_key=CIO.key,
                    extra={"approval_id": str(approval.id)},
                )
            await session.commit()
            approval_id = approval.id

        if pending:
            # Pauses the graph; the worker resumes it after a human decision. On resume this
            # node re-runs from the top, finds the decided approval and skips the interrupt.
            interrupt({"approval_id": str(approval_id)})

        async with sm() as session:
            task = await _locked_task(session, task_id)
            decided = await session.get(ApprovalRequest, approval_id, populate_existing=True)
            if decided is None:
                raise RuntimeError("decided not found")
            if decided.status != ApprovalStatus.APPROVED:
                return {
                    "approval_id": str(approval_id),
                    "error": {"reason": f"approval_{decided.status.value}", "detail": None},
                }
            await transition(
                session,
                task,
                TaskStatus.RUNNING,
                actor_type="agent",
                actor_id=CIO.key,
                agent_key=CIO.key,
            )
            await session.commit()
        return {"approval_id": str(approval_id), "publish_args": args.model_dump()}

    async def execute_approved_action(state: CioState) -> CioState:
        task_id, project_id = _ids(state)
        ctx = ToolContext(
            runtime=runtime,
            task_id=task_id,
            project_id=project_id,
            execution_id=uuid.UUID(state["cio_execution_id"]),
            agent_key=CIO.key,
            allowed_repos=frozenset(state.get("allowed_repos", [])),
        )
        outcome = await execute_tool(ctx, "report.publish_external", state["publish_args"])
        if not outcome.ok:
            # Non-idempotent: never retried automatically (ADR-0003).
            return {
                "error": {
                    "reason": "approved_action_failed",
                    "detail": outcome.error,
                    "needs_human_review": True,
                }
            }
        return {"publication": outcome.output or {}}

    async def review(state: CioState) -> CioState:
        task_id, project_id = _ids(state)
        recommendation = CicdRecommendation.model_validate(state["specialist_result"])
        resolved = runtime.models.resolve(
            agent_key=CIO.key, profile="fast", task_override=state.get("model_override")
        )
        request = ModelRequest(
            purpose="cio.summary",
            model=resolved.model,
            messages=[
                ChatMessage("system", prompts.CIO_SUMMARY),
                ChatMessage("user", recommendation.model_dump_json()),
            ],
            output_schema=OutcomeSummary,
            hints={
                "repository": recommendation.repository,
                "files": len(recommendation.files_inspected),
                "findings": len(recommendation.findings),
                "recommendations": len(recommendation.recommendations),
                "top_risks": [
                    f.description
                    for f in recommendation.findings
                    if f.severity in ("high", "critical")
                ][:5],
                "recommendation_titles": [r.title for r in recommendation.recommendations][:5],
            },
        )
        response = await resolved.provider.complete(request)
        await record_model_call(
            runtime,
            execution_id=uuid.UUID(state["cio_execution_id"]),
            task_id=task_id,
            project_id=project_id,
            agent_key=CIO.key,
            purpose=request.purpose,
            resolved=resolved,
            usage=response.usage,
        )
        summary = (
            response.parsed
            if isinstance(response.parsed, OutcomeSummary)
            else OutcomeSummary(outcome="Summary unavailable: model output could not be parsed.")
        )
        async with sm() as session:
            task = await _locked_task(session, task_id)
            await transition(
                session,
                task,
                TaskStatus.IN_REVIEW,
                actor_type="agent",
                actor_id=CIO.key,
                agent_key=CIO.key,
            )
            task.result = {
                "summary": summary.model_dump(),
                "recommendation": state["specialist_result"],
                "verification": state["verification"],
                "publication": state.get("publication"),
                "approval_id": state.get("approval_id"),
                "prompt_version": prompts.PROMPT_VERSION,
            }
            await _step(session, state, "review")
            await session.commit()
        return {"summary": summary.model_dump()}

    async def complete(state: CioState) -> CioState:
        task_id, project_id = _ids(state)
        if not VerificationResult.model_validate(state["verification"]).passed:
            raise RuntimeError("refusing to complete a task without passing verification")
        async with sm() as session:
            task = await _locked_task(session, task_id)
            await transition(
                session,
                task,
                TaskStatus.COMPLETED,
                actor_type="agent",
                actor_id=CIO.key,
                agent_key=CIO.key,
            )
            execution = await session.get(TaskExecution, uuid.UUID(state["cio_execution_id"]))
            if execution is None:
                raise RuntimeError("execution not found")
            await _close_execution(
                session,
                execution,
                ExecutionStatus.SUCCEEDED,
                agent_key=CIO.key,
                project_id=project_id,
                output={"summary": state.get("summary")},
            )
            await session.commit()
        return {}

    async def fail(state: CioState) -> CioState:
        task_id, _ = _ids(state)
        error = state.get("error") or {"reason": "unspecified"}
        async with sm() as session:
            task = await _locked_task(session, task_id)
            await close_running_executions(session, task, ExecutionStatus.FAILED, error)
            await transition(
                session,
                task,
                TaskStatus.FAILED,
                actor_type="agent",
                actor_id=CIO.key,
                agent_key=CIO.key,
                reason=str(error.get("reason")),
                detail=str(error.get("detail") or "") or None,
            )
            await session.commit()
        return {}

    def route_error(next_node: str) -> Any:
        def _route(state: CioState) -> str:
            return "fail" if state.get("error") else next_node

        return _route

    graph = StateGraph(CioState)
    graph.add_node("intake", intake)
    graph.add_node("analyze", analyze)
    graph.add_node("plan", plan)
    graph.add_node("execute_specialist", execute_specialist)
    graph.add_node("verify", verify)
    graph.add_node("request_approval", approval_gate)
    graph.add_node("execute_approved_action", execute_approved_action)
    graph.add_node("review", review)
    graph.add_node("complete", complete)
    graph.add_node("fail", fail)

    graph.add_edge(START, "intake")
    graph.add_edge("intake", "analyze")
    graph.add_conditional_edges("analyze", route_error("plan"), ["plan", "fail"])
    graph.add_edge("plan", "execute_specialist")
    graph.add_edge("execute_specialist", "verify")
    graph.add_conditional_edges(
        "verify", after_verify, ["fail", "execute_specialist", "request_approval"]
    )
    graph.add_conditional_edges(
        "request_approval",
        route_error("execute_approved_action"),
        ["execute_approved_action", "fail"],
    )
    graph.add_conditional_edges(
        "execute_approved_action", route_error("review"), ["review", "fail"]
    )
    graph.add_edge("review", "complete")
    graph.add_edge("complete", END)
    graph.add_edge("fail", END)
    return graph.compile(checkpointer=checkpointer)


async def fail_task_outside_graph(
    session: AsyncSession, task_id: uuid.UUID, *, reason: str, detail: str | None
) -> None:
    """Used by the worker when the graph itself cannot continue."""
    task = await session.get(Task, task_id, with_for_update=True, populate_existing=True)
    if task is None or task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
        return
    await close_running_executions(
        session, task, ExecutionStatus.FAILED, {"reason": reason, "detail": detail}
    )
    if task.status != TaskStatus.FAILED:
        await transition(
            session,
            task,
            TaskStatus.FAILED,
            actor_type="system",
            actor_id="worker",
            reason=reason,
            detail=detail,
        )


async def cancel_executions(session: AsyncSession, task_id: uuid.UUID) -> None:
    task = await session.get(Task, task_id)
    if task is not None:
        await close_running_executions(
            session, task, ExecutionStatus.CANCELLED, {"reason": "task_cancelled"}
        )
