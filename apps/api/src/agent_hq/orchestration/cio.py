"""AI CIO workflow: a fixed, checkpointed LangGraph graph (ADR-0003, ADR-0011).

intake → analyze → plan → execute_wave (repeats; parallel steps) → assess
       → request_approval (interrupt) → execute_approved_action → review → complete

Every node is safe to re-execute: LangGraph re-runs a node after a crash and re-runs the
approval node from its start on resume, so database effects are written idempotently
(status transitions are no-ops when already applied, approvals are looked up by hash,
completed plan steps are reused from their subtask rows).
"""

import asyncio
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

from agent_hq.agents import CIO
from agent_hq.domain import (
    ApprovalStatus,
    ExecutionStatus,
    KnowledgeScope,
    RiskLevel,
    TaskCancelledError,
    TaskStatus,
)
from agent_hq.events import record_task_event
from agent_hq.knowledge import KnowledgeError, agent_search, create_document
from agent_hq.llm.base import ChatMessage, ModelRequest
from agent_hq.models import (
    Agent,
    ApprovalRequest,
    Integration,
    KnowledgeDocument,
    Project,
    Task,
    TaskExecution,
    utcnow,
)
from agent_hq.orchestration import prompts
from agent_hq.orchestration.agent_loop import SpecialistError
from agent_hq.orchestration.plan import add_rework, build_plan, last_of_kind, ready_steps
from agent_hq.orchestration.schemas import (
    Changeset,
    CicdRecommendation,
    OutcomeSummary,
    PlanStep,
    Requirements,
)
from agent_hq.orchestration.specialists import RUNNERS, StepContext
from agent_hq.orchestration.usage import record_model_call
from agent_hq.orchestration.verify import verify_step
from agent_hq.runtime import Runtime
from agent_hq.security.approvals import request_approval
from agent_hq.security.policy import PolicyDenied, authorize_delegation, authorize_repository
from agent_hq.tasks import transition
from agent_hq.tools import (
    ProposeChangesetArgs,
    PublishReportArgs,
    ToolContext,
    approval_action,
    execute_tool,
)

MAX_STEP_ATTEMPTS = 2
MAX_REWORK_ROUNDS = 1


class CioState(TypedDict, total=False):
    task_id: str
    project_id: str
    run_number: int
    request: str
    acceptance_criteria: list[str]
    model_override: str | None
    cio_execution_id: str
    allowed_repos: list[str]
    pull_requests: bool
    requirements: dict[str, Any]
    workflow: str
    plan: list[dict[str, Any]]
    step_results: dict[str, dict[str, Any]]
    rework_rounds: int
    verification: dict[str, Any]
    approval_id: str
    action: dict[str, Any]
    publication: dict[str, Any]
    summary: dict[str, Any]
    error: dict[str, Any] | None


class StepFailed(Exception):
    def __init__(self, step_id: str, reason: str, detail: str) -> None:
        super().__init__(f"{step_id}: {reason}: {detail}")
        self.reason = reason
        self.detail = f"{step_id}: {detail}"


def initial_state(task: Task) -> CioState:
    return CioState(
        task_id=str(task.id),
        project_id=str(task.project_id),
        run_number=task.run_number,
        request=task.request,
        acceptance_criteria=[str(c) for c in task.acceptance_criteria],
        model_override=task.options.get("model_override"),
        step_results={},
        rework_rounds=0,
        error=None,
    )


def thread_id(task_id: uuid.UUID, run_number: int) -> str:
    return f"{task_id}:{run_number}"


def _ids(state: CioState) -> tuple[uuid.UUID, uuid.UUID]:
    return uuid.UUID(state["task_id"]), uuid.UUID(state["project_id"])


def _plan(state: CioState) -> list[PlanStep]:
    return [PlanStep.model_validate(s) for s in state.get("plan", [])]


def _sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


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


async def _step_event(session: AsyncSession, state: CioState, node: str, **payload: Any) -> None:
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
    thread: str,
    parent_id: uuid.UUID,
    reuse_running: bool = False,
    input: dict[str, Any] | None = None,
) -> TaskExecution:
    agent_id = await _agent_id(session, agent_key)
    if reuse_running:
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
    execution = TaskExecution(
        task_id=task.id,
        agent_id=agent_id,
        run_number=task.run_number,
        attempt=(previous or 0) + 1,
        status=ExecutionStatus.RUNNING,
        graph_thread_id=thread,
        input=input or {},
    )
    session.add(execution)
    await session.flush()
    await record_task_event(
        session,
        task_id=parent_id,
        project_id=task.project_id,
        execution_id=execution.id,
        agent_key=agent_key,
        type="execution_started",
        payload={"attempt": execution.attempt, "task_id": str(task.id)},
    )
    return execution


async def _close_execution(
    session: AsyncSession,
    execution: TaskExecution,
    status: ExecutionStatus,
    *,
    agent_key: str,
    project_id: uuid.UUID,
    parent_id: uuid.UUID,
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
        task_id=parent_id,
        project_id=project_id,
        execution_id=execution.id,
        agent_key=agent_key,
        type="execution_finished",
        payload={"status": status.value, "task_id": str(execution.task_id)},
    )


async def close_running_executions(
    session: AsyncSession, task: Task, status: ExecutionStatus, error: dict[str, Any] | None
) -> None:
    """Close running executions of a task and of its subtasks."""
    keys = {a.id: a.key for a in await session.scalars(select(Agent))}
    task_ids = [
        task.id,
        *await session.scalars(select(Task.id).where(Task.parent_task_id == task.id)),
    ]
    running = await session.scalars(
        select(TaskExecution).where(
            TaskExecution.task_id.in_(task_ids), TaskExecution.status == ExecutionStatus.RUNNING
        )
    )
    for execution in running:
        await _close_execution(
            session,
            execution,
            status,
            agent_key=keys[execution.agent_id],
            project_id=task.project_id,
            parent_id=task.id,
            error=error,
        )


async def _subtask_for(session: AsyncSession, parent: Task, step: PlanStep) -> Task:
    """Find or create the subtask that represents a plan step (idempotent)."""
    existing = await session.scalar(
        select(Task)
        .where(
            Task.parent_task_id == parent.id,
            Task.run_number == parent.run_number,
            Task.options["step_id"].astext == step.id,
        )
        .with_for_update()
    )
    if existing is not None:
        return existing
    subtask = Task(
        project_id=parent.project_id,
        parent_task_id=parent.id,
        title=f"{step.kind}: {step.objective}"[:200],
        request=step.objective,
        status=TaskStatus.QUEUED,
        assigned_agent_id=await _agent_id(session, step.agent_key),
        created_by=parent.created_by,
        options={"step_id": step.id, "kind": step.kind, "depends_on": step.depends_on},
        run_number=parent.run_number,
    )
    session.add(subtask)
    await session.flush()
    await record_task_event(
        session,
        task_id=parent.id,
        project_id=parent.project_id,
        agent_key=CIO.key,
        type="subtask_created",
        payload={"subtask_id": str(subtask.id), "step_id": step.id, "agent": step.agent_key},
    )
    return subtask


def build_cio_graph(
    runtime: Runtime, checkpointer: BaseCheckpointSaver[Any]
) -> CompiledStateGraph[CioState, None, CioState, CioState]:
    sm = runtime.sessionmaker
    settings = runtime.settings

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
                session,
                task,
                CIO.key,
                thread=thread_id(task.id, task.run_number),
                parent_id=task.id,
                reuse_running=True,
                input={"request": state["request"]},
            )
            integration = await session.scalar(
                select(Integration).where(
                    Integration.project_id == task.project_id,
                    Integration.provider == "github",
                    Integration.enabled.is_(True),
                )
            )
            allowed = list(integration.config.get("allowed_repos", [])) if integration else []
            # Real pull requests need both an App and the owner's per-project opt-in.
            pull_requests = bool(
                integration
                and integration.config.get("pull_requests") is True
                and runtime.pull_requests is not None
            )
            state = {**state, "cio_execution_id": str(execution.id)}
            await _step_event(session, state, "intake", authorized_repositories=allowed)
            await session.commit()
        return {
            "cio_execution_id": str(execution.id),
            "allowed_repos": allowed,
            "pull_requests": pull_requests,
        }

    async def analyze(state: CioState) -> CioState:
        task_id, project_id = _ids(state)
        allowed = state.get("allowed_repos", [])
        resolved = runtime.models.resolve(
            agent_key=CIO.key, profile=CIO.model_profile, task_override=state.get("model_override")
        )
        # The Brain: company + this project's knowledge relevant to the request.
        async with sm() as session:
            hits = await agent_search(
                session, project_id=project_id, agent_key=CIO.key, text=state["request"], limit=5
            )
        knowledge = [h.for_agent() for h in hits]
        request = ModelRequest(
            purpose="cio.analyze",
            model=resolved.model,
            messages=[
                ChatMessage("system", prompts.CIO_ANALYZE.format(brand=settings.brand_name)),
                ChatMessage(
                    "user",
                    json.dumps(
                        {
                            "request": state["request"],
                            "acceptance_criteria": state.get("acceptance_criteria", []),
                            "authorized_repositories": allowed,
                        }
                    )
                    + "\n\nRelevant knowledge:\n"
                    + prompts.wrap_untrusted("knowledge.search", json.dumps(knowledge)),
                ),
            ],
            output_schema=Requirements,
            hints={"request": state["request"], "allowed_repos": allowed, "knowledge": knowledge},
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
        if not isinstance(response.parsed, Requirements):
            return {
                "error": {"reason": "model_output_invalid", "detail": "requirements not parsed"}
            }
        requirements = response.parsed
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
            missing.append(f"Which repository should be used? Options: {', '.join(allowed)}.")
        result = {
            **requirements.model_dump(),
            "repository": repository,
            "missing_information": missing,
        }
        async with sm() as session:
            await _locked_task(session, task_id)
            await _step_event(
                session,
                state,
                "analyze",
                requirements=result,
                knowledge_used=[k["id"] for k in knowledge],
            )
            await session.commit()
        if missing:
            return {
                "requirements": result,
                "error": {"reason": "clarification_required", "detail": " ".join(missing)},
            }
        return {"requirements": result, "workflow": requirements.workflow}

    async def plan(state: CioState) -> CioState:
        task_id, _ = _ids(state)
        requirements = state["requirements"]
        steps = build_plan(
            state["workflow"],  # type: ignore[arg-type]
            repository=requirements["repository"],
            objectives=requirements.get("objectives") or [],
        )
        for step in steps:
            authorize_delegation(CIO.key, step.agent_key)
        async with sm() as session:
            await _locked_task(session, task_id)
            await _step_event(
                session,
                state,
                "plan",
                workflow=state["workflow"],
                steps=[s.model_dump() for s in steps],
            )
            await session.commit()
        return {"plan": [s.model_dump() for s in steps]}

    async def run_step(state: CioState, step: PlanStep) -> dict[str, Any]:
        """Run one plan step as a subtask, with code validation and one retry."""
        parent_id, project_id = _ids(state)
        allowed = frozenset(state.get("allowed_repos", []))
        thread = thread_id(parent_id, state["run_number"])
        async with sm() as session:
            parent = await _locked_task(session, parent_id)
            subtask = await _subtask_for(session, parent, step)
            if subtask.status == TaskStatus.COMPLETED and subtask.result is not None:
                await session.commit()
                return subtask.result  # finished before a crash: never re-run
            if subtask.status in (TaskStatus.RUNNING, TaskStatus.IN_REVIEW):
                # Left behind by a crashed worker.
                await close_running_executions(
                    session, subtask, ExecutionStatus.FAILED, {"reason": "interrupted"}
                )
                await transition(
                    session,
                    subtask,
                    TaskStatus.FAILED,
                    actor_type="system",
                    actor_id="worker",
                    reason="interrupted",
                )
            if subtask.status == TaskStatus.FAILED:
                await transition(
                    session, subtask, TaskStatus.QUEUED, actor_type="agent", actor_id=CIO.key
                )
            subtask_id = subtask.id
            await session.commit()

        prior = {
            dep: {**state.get("step_results", {})[dep], "_kind": _kind_of(state, dep)}
            for dep in step.depends_on
        }
        problems: list[str] = []
        for _attempt in range(MAX_STEP_ATTEMPTS):
            async with sm() as session:
                subtask = await _locked_task(session, subtask_id)
                await transition(
                    session,
                    subtask,
                    TaskStatus.RUNNING,
                    actor_type="agent",
                    actor_id=CIO.key,
                    agent_key=step.agent_key,
                )
                execution = await _open_execution(
                    session,
                    subtask,
                    step.agent_key,
                    thread=thread,
                    parent_id=parent_id,
                    input=step.model_dump(),
                )
                await session.commit()
            context = StepContext(
                task_id=parent_id,
                project_id=project_id,
                execution_id=execution.id,
                step=step,
                repository=state["requirements"]["repository"],
                allowed_repos=allowed,
                request=state["request"],
                acceptance_criteria=state.get("acceptance_criteria", []),
                model_override=state.get("model_override"),
                prior=prior,
            )
            try:
                output = await RUNNERS[step.kind](runtime, context)
            except SpecialistError as exc:
                async with sm() as session:
                    subtask = await _locked_task(session, subtask_id)
                    row = await session.get(TaskExecution, execution.id)
                    if row is None:
                        raise RuntimeError("execution not found") from exc
                    await _close_execution(
                        session,
                        row,
                        ExecutionStatus.FAILED,
                        agent_key=step.agent_key,
                        project_id=project_id,
                        parent_id=parent_id,
                        error={"reason": exc.reason, "detail": exc.detail},
                    )
                    await transition(
                        session,
                        subtask,
                        TaskStatus.FAILED,
                        actor_type="agent",
                        actor_id=step.agent_key,
                        reason=exc.reason,
                        detail=exc.detail,
                    )
                    await session.commit()
                raise StepFailed(step.id, exc.reason, exc.detail) from exc

            verdict = verify_step(step.kind, output, allowed_repos=allowed)
            problems = verdict.problems
            async with sm() as session:
                subtask = await _locked_task(session, subtask_id)
                row = await session.get(TaskExecution, execution.id)
                if row is None:
                    raise RuntimeError("execution not found")
                await _close_execution(
                    session,
                    row,
                    ExecutionStatus.SUCCEEDED,
                    agent_key=step.agent_key,
                    project_id=project_id,
                    parent_id=parent_id,
                    output=output,
                )
                await transition(
                    session,
                    subtask,
                    TaskStatus.IN_REVIEW,
                    actor_type="agent",
                    actor_id=step.agent_key,
                    agent_key=step.agent_key,
                )
                await record_task_event(
                    session,
                    task_id=parent_id,
                    project_id=project_id,
                    agent_key=CIO.key,
                    type="step_verified",
                    payload={"step_id": step.id, **verdict.model_dump()},
                )
                if verdict.passed:
                    subtask.result = output
                    await transition(
                        session,
                        subtask,
                        TaskStatus.COMPLETED,
                        actor_type="agent",
                        actor_id=CIO.key,
                    )
                    await session.commit()
                    return output
                await session.commit()

        async with sm() as session:
            subtask = await _locked_task(session, subtask_id)
            await transition(
                session,
                subtask,
                TaskStatus.FAILED,
                actor_type="agent",
                actor_id=CIO.key,
                reason="verification_failed",
                detail="; ".join(problems),
            )
            await session.commit()
        raise StepFailed(step.id, "verification_failed", "; ".join(problems))

    async def execute_wave(state: CioState) -> CioState:
        steps = _plan(state)
        results = dict(state.get("step_results", {}))
        ready = ready_steps(steps, set(results))
        if not ready:
            return {"error": {"reason": "plan_stalled", "detail": "no runnable step"}}
        slots = asyncio.Semaphore(max(1, settings.max_parallel_steps))

        async def bounded(step: PlanStep) -> dict[str, Any]:
            async with slots:
                return await run_step(state, step)

        outcomes = await asyncio.gather(*(bounded(s) for s in ready), return_exceptions=True)
        failure: StepFailed | None = None
        for step, outcome in zip(ready, outcomes, strict=True):
            if isinstance(outcome, StepFailed):
                failure = failure or outcome
            elif isinstance(outcome, BaseException):
                # A crash: completed siblings are already persisted on their subtasks and
                # will be reused when the job is retried from this checkpoint.
                raise outcome
            else:
                results[step.id] = outcome
        if failure is not None:
            return {
                "step_results": results,
                "error": {"reason": failure.reason, "detail": failure.detail},
            }
        return {"step_results": results}

    def after_wave(state: CioState) -> Literal["fail", "execute_wave", "assess"]:
        if state.get("error"):
            return "fail"
        done = set(state.get("step_results", {}))
        return "assess" if all(s.id in done for s in _plan(state)) else "execute_wave"

    async def assess(state: CioState) -> CioState:
        """Decide whether the plan's outcome is acceptable, or needs one rework round."""
        task_id, _ = _ids(state)
        steps = _plan(state)
        update: CioState = {"verification": {"passed": True, "problems": []}}
        last_tests = last_of_kind(steps, "run_tests")
        if last_tests is not None:
            qa = state["step_results"][last_tests.id]
            if qa["report"]["verdict"] != "ready":
                rounds = state.get("rework_rounds", 0)
                failures = "; ".join(qa["report"]["failures"]) or "tests failed"
                tail = ((qa.get("sandbox") or {}).get("output") or "")[-2000:]
                if rounds < MAX_REWORK_ROUNDS:
                    new_plan = add_rework(
                        steps, round_=rounds + 2, feedback=f"{failures}\n\nTest output:\n{tail}"
                    )
                    update = {
                        "plan": [s.model_dump() for s in new_plan],
                        "rework_rounds": rounds + 1,
                    }
                else:
                    update = {"error": {"reason": "qa_not_ready", "detail": failures}}
        async with sm() as session:
            await _locked_task(session, task_id)
            await _step_event(
                session,
                state,
                "assess",
                rework=update.get("rework_rounds") is not None,
                error=update.get("error"),
            )
            await session.commit()
        return update

    def after_assess(state: CioState) -> Literal["fail", "execute_wave", "request_approval"]:
        if state.get("error"):
            return "fail"
        done = set(state.get("step_results", {}))
        if not all(s.id in done for s in _plan(state)):
            return "execute_wave"
        return "request_approval"

    def _action(state: CioState, project_key: str) -> tuple[str, Any, dict[str, Any]]:
        steps = _plan(state)
        results = state["step_results"]
        task_id = state["task_id"]
        if state["workflow"] == "code_change":
            implement = last_of_kind(steps, "implement")
            run_tests = last_of_kind(steps, "run_tests")
            assert implement is not None and run_tests is not None  # noqa: S101 - plan invariant
            changeset = results[implement.id]
            qa = results[run_tests.id]
            args: Any = ProposeChangesetArgs(
                target=(
                    f"github://{state['requirements']['repository']}/pulls"
                    if state.get("pull_requests")
                    else f"mock://pull-requests/{state['requirements']['repository']}"
                ),
                task_id=task_id,
                run_number=state["run_number"],
                changeset_sha256=_sha256(changeset),
                qa_report_sha256=_sha256(qa),
            )
            cs = Changeset.model_validate(changeset)
            evidence = {
                "files_changed": [f.path for f in [*cs.files, *cs.tests]],
                "qa_verdict": qa["report"]["verdict"],
                "sandbox": {
                    k: (qa.get("sandbox") or {}).get(k)
                    for k in ("exit_code", "summary", "timed_out", "duration_ms")
                },
            }
            return "changeset.propose", args, evidence
        review = last_of_kind(steps, "cicd_review")
        assert review is not None  # noqa: S101 - plan invariant
        rec = CicdRecommendation.model_validate(results[review.id])
        args = PublishReportArgs(
            target=f"mock://reports/{project_key}",
            task_id=task_id,
            run_number=state["run_number"],
            report_sha256=_sha256(results[review.id]),
        )
        evidence = {
            "files_inspected": [f.model_dump() for f in rec.files_inspected],
            "findings": len(rec.findings),
            "recommendations": len(rec.recommendations),
        }
        return "report.publish_external", args, evidence

    async def approval_gate(state: CioState) -> CioState:
        task_id, project_id = _ids(state)
        async with sm() as session:
            task = await _locked_task(session, task_id)
            project = await session.get(Project, project_id)
            if project is None:
                raise RuntimeError("project not found")
            tool_name, args, evidence = _action(state, project.key)
            action = approval_action(tool_name, args)
            is_change = tool_name == "changeset.propose"
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
                    "Propose the verified, tested changeset for human review as a pull request."
                    if is_change
                    else "Share the verified CI/CD review with stakeholders."
                ),
                expected_impact=(
                    (
                        "Creates a new branch with one commit and opens a DRAFT pull request "
                        "on GitHub. Nothing is merged; existing branches are not touched."
                    )
                    if is_change and action.target.startswith("github://")
                    else (
                        "Mock adapter: records a proposed pull request. Nothing is pushed or "
                        "merged."
                    )
                    if is_change
                    else "Mock adapter: records a published report. No external system is "
                    "contacted."
                ),
                risk_level=RiskLevel.MEDIUM if is_change else RiskLevel.LOW,
                evidence={**evidence, "verification": state["verification"]},
                ttl=timedelta(hours=settings.approval_ttl_hours),
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
                raise RuntimeError("approval not found")
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
        return {
            "approval_id": str(approval_id),
            "action": {"tool": tool_name, "arguments": args.model_dump()},
        }

    async def execute_approved_action(state: CioState) -> CioState:
        task_id, project_id = _ids(state)
        ctx = ToolContext(
            runtime=runtime,
            task_id=task_id,
            project_id=project_id,
            execution_id=uuid.UUID(state["cio_execution_id"]),
            agent_key=CIO.key,
            allowed_repos=frozenset(state.get("allowed_repos", [])),
            payload=_action_payload(state),
        )
        action = state["action"]
        outcome = await execute_tool(ctx, action["tool"], action["arguments"])
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

    def _final_results(state: CioState) -> dict[str, Any]:
        steps = _plan(state)
        results = state["step_results"]
        out: dict[str, Any] = {"workflow": state["workflow"]}
        for kind, key in (
            ("cicd_review", "recommendation"),
            ("implement", "changeset"),
            ("test_plan", "test_plan"),
            ("run_tests", "qa"),
        ):
            step = last_of_kind(steps, kind)
            if step is not None:
                out[key] = results[step.id]
        return out

    async def review(state: CioState) -> CioState:
        task_id, project_id = _ids(state)
        final = _final_results(state)
        resolved = runtime.models.resolve(
            agent_key=CIO.key, profile="fast", task_override=state.get("model_override")
        )
        request = ModelRequest(
            purpose="cio.summary",
            model=resolved.model,
            messages=[
                ChatMessage("system", prompts.CIO_SUMMARY),
                ChatMessage("user", json.dumps(final)[:60000]),
            ],
            output_schema=OutcomeSummary,
            hints={"final": final, "repository": state["requirements"]["repository"]},
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
                **final,
                "summary": summary.model_dump(),
                "verification": state["verification"],
                "plan": state["plan"],
                "publication": state.get("publication"),
                "approval_id": state.get("approval_id"),
                "prompt_version": prompts.PROMPT_VERSION,
            }
            await _step_event(session, state, "review")
            await session.commit()
        return {"summary": summary.model_dump()}

    async def complete(state: CioState) -> CioState:
        task_id, project_id = _ids(state)
        if not state.get("verification", {}).get("passed"):
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
                parent_id=task_id,
                output={"summary": state.get("summary")},
            )
            await _remember_outcome(session, task, state)
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
    graph.add_node("execute_wave", execute_wave)
    graph.add_node("assess", assess)
    graph.add_node("request_approval", approval_gate)
    graph.add_node("execute_approved_action", execute_approved_action)
    graph.add_node("review", review)
    graph.add_node("complete", complete)
    graph.add_node("fail", fail)

    graph.add_edge(START, "intake")
    graph.add_edge("intake", "analyze")
    graph.add_conditional_edges("analyze", route_error("plan"), ["plan", "fail"])
    graph.add_edge("plan", "execute_wave")
    graph.add_conditional_edges("execute_wave", after_wave, ["fail", "execute_wave", "assess"])
    graph.add_conditional_edges(
        "assess", after_assess, ["fail", "execute_wave", "request_approval"]
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


async def _remember_outcome(session: AsyncSession, task: Task, state: CioState) -> None:
    """Agent execution memory: an unverified project note a human can promote to fact."""
    run_tag = f"run-{task.run_number}"
    existing = await session.scalar(
        select(KnowledgeDocument.id).where(
            KnowledgeDocument.source_task_id == task.id,
            KnowledgeDocument.kind == "execution_summary",
            KnowledgeDocument.tags.contains([run_tag]),
        )
    )
    if existing is not None:
        return
    summary = state.get("summary") or {}
    lines = [
        f"Request: {task.request}",
        f"Workflow: {state.get('workflow')} on {state['requirements']['repository']}",
        f"Outcome: {summary.get('outcome', '')}",
        *(f"Risk: {r}" for r in summary.get("risks", [])),
        *(f"Next step: {n}" for n in summary.get("next_steps", [])),
    ]
    try:
        await create_document(
            session,
            scope=KnowledgeScope.PROJECT,
            project_id=task.project_id,
            kind="execution_summary",
            title=f"Outcome: {task.title}",
            content="\n".join(lines),
            agent_key=CIO.key,
            source_task_id=task.id,
            tags=[str(state.get("workflow")), run_tag],
        )
    except KnowledgeError:
        # Memory is best-effort: an unrecordable summary must not undo a verified result.
        return


def _action_payload(state: CioState) -> dict[str, Any]:
    """Content for the approved action; the adapter re-hashes it against the approval."""
    steps = [PlanStep.model_validate(s) for s in state.get("plan", [])]
    implement = last_of_kind(steps, "implement")
    run_tests = last_of_kind(steps, "run_tests")
    if implement is None or run_tests is None:
        return {}
    changeset = state["step_results"][implement.id]
    qa = state["step_results"][run_tests.id]
    sandbox = qa.get("sandbox") or {}
    files = "\n".join(
        f"- `{f['path']}` ({f['action']})" for f in [*changeset["files"], *changeset["tests"]]
    )
    body = "\n\n".join(
        [
            changeset["summary"],
            changeset["rationale"],
            f"**Files**\n{files}",
            f"**QA verdict:** {qa['report']['verdict']}: sandbox exit "
            f"{sandbox.get('exit_code')}, {sandbox.get('summary')}",
            f"Proposed by Agent HQ (task {state['task_id']}, run {state['run_number']}) after "
            f"human approval {state.get('approval_id')}. Review before merging; Agent HQ "
            "never merges.",
        ]
    )
    return {"changeset": changeset, "body": body}


def _kind_of(state: CioState, step_id: str) -> str:
    for step in state.get("plan", []):
        if step["id"] == step_id:
            return str(step["kind"])
    raise KeyError(step_id)


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
