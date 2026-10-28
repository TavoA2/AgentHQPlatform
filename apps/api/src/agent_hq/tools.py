"""Tool registry and the single execution path for agent tool calls.

Order of checks for every call (all server-side, none depend on the prompt):
1. the tool exists; 2. the agent is permitted to use it; 3. arguments validate;
4. repository/path scope; 5. per-execution call limit; 6. approval (if required);
then execution under a timeout. Every call is recorded as a task event; every denial is
also written to the audit log.
"""

import asyncio
import json
import logging
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from agent_hq.domain import DomainError
from agent_hq.events import record_audit, record_task_event
from agent_hq.integrations.github import GitHubError, is_ci_relevant
from agent_hq.llm.base import ToolSchema
from agent_hq.runtime import Runtime
from agent_hq.security import approvals
from agent_hq.security.policy import PolicyDenied, authorize_repository, authorize_tool

logger = logging.getLogger(__name__)


class SideEffect(StrEnum):
    READ = "read"
    INTERNAL_WRITE = "internal_write"
    EXTERNAL_WRITE = "external_write"
    IRREVERSIBLE = "irreversible"


@dataclass
class ToolContext:
    runtime: Runtime
    task_id: uuid.UUID
    project_id: uuid.UUID
    execution_id: uuid.UUID
    agent_key: str
    allowed_repos: frozenset[str]
    call_counts: Counter[str] = field(default_factory=Counter)


@dataclass(frozen=True)
class ToolOutcome:
    ok: bool
    output: dict[str, Any] | None = None
    error: str | None = None
    denied: bool = False

    def for_model(self) -> str:
        if self.ok:
            return json.dumps(self.output)
        kind = "denied" if self.denied else "error"
        return json.dumps({kind: self.error})


Handler = Callable[[ToolContext, Any], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    side_effect: SideEffect
    idempotent: bool
    timeout_seconds: float
    max_calls: int
    handler: Handler
    requires_approval: bool = False

    def schema(self) -> ToolSchema:
        return ToolSchema(self.name, self.description, self.args_model.model_json_schema())


class ApprovalRequiredAction(BaseModel):
    """Exactly what a human approves; also the hash input (ADR-0006)."""

    action_type: str
    target: str
    parameters: dict[str, Any]


# --- argument models ---
class RepoArgs(BaseModel):
    repository: str = Field(description="owner/name of an authorized repository")


class ReadFileArgs(RepoArgs):
    path: str = Field(max_length=400, description="Path of a CI/CD-relevant file in the repo")


class WorkflowRunsArgs(RepoArgs):
    limit: int = Field(default=10, ge=1, le=20)


class PublishReportArgs(BaseModel):
    target: str = Field(max_length=300)
    task_id: str
    run_number: int
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


# --- handlers ---
def _repo(ctx: ToolContext, args: RepoArgs) -> str:
    return authorize_repository(args.repository, ctx.allowed_repos)


async def _list_tree(ctx: ToolContext, args: RepoArgs) -> dict[str, Any]:
    repo = _repo(ctx, args)
    entries = await ctx.runtime.github.list_tree(repo)
    relevant = [e for e in entries if is_ci_relevant(e.path)]
    return {
        "repository": repo,
        "total_files": len(entries),
        "ci_relevant": [{"path": e.path, "sha": e.sha, "size": e.size} for e in relevant[:50]],
    }


async def _read_file(ctx: ToolContext, args: ReadFileArgs) -> dict[str, Any]:
    repo = _repo(ctx, args)
    if not is_ci_relevant(args.path):
        raise PolicyDenied(f"path {args.path!r} is outside the CI/CD read scope")
    f = await ctx.runtime.github.read_file(repo, args.path)
    return {
        "repository": repo,
        "path": f.path,
        "sha": f.sha,
        "size": f.size,
        "truncated": f.truncated,
        "content": f.content,
    }


async def _list_workflow_runs(ctx: ToolContext, args: WorkflowRunsArgs) -> dict[str, Any]:
    repo = _repo(ctx, args)
    return {
        "repository": repo,
        "runs": await ctx.runtime.github.list_workflow_runs(repo, args.limit),
    }


async def _publish_report(ctx: ToolContext, args: PublishReportArgs) -> dict[str, Any]:
    async with ctx.runtime.sessionmaker() as session:
        result = await ctx.runtime.publisher.publish(
            session,
            target=args.target,
            project_id=ctx.project_id,
            task_id=ctx.task_id,
            report_sha256=args.report_sha256,
        )
        await session.commit()
    return result


TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        ToolSpec(
            "github.list_tree",
            "List CI/CD-relevant files of an authorized repository (default branch).",
            RepoArgs,
            SideEffect.READ,
            True,
            30,
            3,
            _list_tree,
        ),
        ToolSpec(
            "github.read_file",
            "Read one CI/CD-relevant file (workflows, Dockerfiles, compose, build manifests).",
            ReadFileArgs,
            SideEffect.READ,
            True,
            30,
            25,
            _read_file,
        ),
        ToolSpec(
            "github.list_workflow_runs",
            "List recent GitHub Actions runs of an authorized repository.",
            WorkflowRunsArgs,
            SideEffect.READ,
            True,
            30,
            3,
            _list_workflow_runs,
        ),
        ToolSpec(
            "report.publish_external",
            "Publish a verified report outside Agent HQ (mock adapter in Sprint 1).",
            PublishReportArgs,
            SideEffect.EXTERNAL_WRITE,
            False,
            30,
            1,
            _publish_report,
            requires_approval=True,
        ),
    )
}


def tool_schemas(names: list[str]) -> list[ToolSchema]:
    return [TOOLS[n].schema() for n in names]


def approval_action(name: str, args: BaseModel) -> ApprovalRequiredAction:
    """Map a sensitive tool call to the action a human must approve."""
    if isinstance(args, PublishReportArgs):
        return ApprovalRequiredAction(
            action_type=name,
            target=args.target,
            parameters=args.model_dump(exclude={"target"}),
        )
    raise ValueError(f"tool {name!r} has no approval mapping")


async def _record_call(
    ctx: ToolContext, name: str, raw_args: dict[str, Any], outcome: ToolOutcome
) -> None:
    async with ctx.runtime.sessionmaker() as session:
        await record_task_event(
            session,
            task_id=ctx.task_id,
            project_id=ctx.project_id,
            execution_id=ctx.execution_id,
            agent_key=ctx.agent_key,
            type="tool_called",
            payload={
                "tool": name,
                "arguments": raw_args,
                "ok": outcome.ok,
                "denied": outcome.denied,
                "error": outcome.error,
            },
        )
        if outcome.denied:
            await record_audit(
                session,
                actor_type="agent",
                actor_id=ctx.agent_key,
                action="tool.denied",
                project_id=ctx.project_id,
                resource_type="task",
                resource_id=ctx.task_id,
                details={"tool": name, "arguments": raw_args, "reason": outcome.error},
            )
        await session.commit()


async def execute_tool(ctx: ToolContext, name: str, raw_args: dict[str, Any]) -> ToolOutcome:
    outcome = await _execute(ctx, name, raw_args)
    await _record_call(ctx, name, raw_args, outcome)
    return outcome


async def _execute(ctx: ToolContext, name: str, raw_args: dict[str, Any]) -> ToolOutcome:
    spec = TOOLS.get(name)
    try:
        if spec is None:
            raise PolicyDenied(f"unknown tool {name!r}")
        authorize_tool(ctx.agent_key, name)
        try:
            args = spec.args_model.model_validate(raw_args)
        except ValidationError as exc:
            return ToolOutcome(ok=False, error=f"invalid arguments: {exc.error_count()} errors")
        ctx.call_counts[name] += 1
        if ctx.call_counts[name] > spec.max_calls:
            raise PolicyDenied(f"call limit for {name!r} reached ({spec.max_calls})")
        if spec.requires_approval:
            action = approval_action(name, args)
            async with ctx.runtime.sessionmaker() as session:
                # Committed before the action runs: an approval is never reusable, even if
                # the action fails afterwards (non-idempotent actions are not retried).
                await approvals.consume(
                    session,
                    task_id=ctx.task_id,
                    action_type=action.action_type,
                    target=action.target,
                    parameters=action.parameters,
                    agent_key=ctx.agent_key,
                )
                await session.commit()
        output = await asyncio.wait_for(spec.handler(ctx, args), spec.timeout_seconds)
        return ToolOutcome(ok=True, output=output)
    except PolicyDenied as exc:
        return ToolOutcome(ok=False, error=exc.reason, denied=True)
    except approvals.ApprovalError as exc:
        return ToolOutcome(ok=False, error=str(exc), denied=True)
    except TimeoutError:
        return ToolOutcome(ok=False, error="tool timed out")
    except GitHubError as exc:
        return ToolOutcome(ok=False, error=str(exc))
    except DomainError as exc:
        return ToolOutcome(ok=False, error=str(exc))
