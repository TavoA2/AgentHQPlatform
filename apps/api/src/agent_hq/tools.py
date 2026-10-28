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
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from agent_hq.domain import DomainError
from agent_hq.events import record_audit, record_task_event
from agent_hq.integrations.github import GitHubError, is_ci_relevant, is_secret_path
from agent_hq.llm.base import ToolSchema
from agent_hq.runtime import Runtime
from agent_hq.sandbox.client import SandboxError
from agent_hq.sandbox.contracts import RunRequest, RunResult
from agent_hq.security import approvals
from agent_hq.security.policy import PolicyDenied, authorize_repository, authorize_tool

logger = logging.getLogger(__name__)

MAX_SOURCE_LISTING = 300
MAX_TEST_REPO_FILES = 30


class SideEffect(StrEnum):
    READ = "read"
    ISOLATED_EXECUTION = "isolated_execution"
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
    # Files proposed by another agent (e.g. a changeset) layered over repository files
    # when building a sandbox workspace. Set by code, never by the model.
    workspace_overlay: dict[str, str] = field(default_factory=dict)
    # Raw sandbox results observed by code, used to validate what the model reports.
    sandbox_results: list[RunResult] = field(default_factory=list)


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
    path: str = Field(max_length=400, description="Path of a file in the repository")


class WorkflowRunsArgs(RepoArgs):
    limit: int = Field(default=10, ge=1, le=20)


class RunTestsArgs(RepoArgs):
    template: Literal["python-pytest"] = "python-pytest"
    repo_paths: list[str] = Field(
        default_factory=list,
        max_length=MAX_TEST_REPO_FILES,
        description="Existing repository files to include next to the proposed changes",
    )


class PublishReportArgs(BaseModel):
    target: str = Field(max_length=300)
    task_id: str
    run_number: int
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ProposeChangesetArgs(BaseModel):
    target: str = Field(max_length=300)
    task_id: str
    run_number: int
    changeset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    qa_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


# --- handlers ---
def _repo(ctx: ToolContext, args: RepoArgs) -> str:
    return authorize_repository(args.repository, ctx.allowed_repos)


def _check_source_path(path: str) -> None:
    if path.startswith("/") or ".." in path.split("/") or is_secret_path(path):
        raise PolicyDenied(f"path {path!r} is outside the source read scope")


async def _list_tree(ctx: ToolContext, args: RepoArgs) -> dict[str, Any]:
    repo = _repo(ctx, args)
    entries = await ctx.runtime.github.list_tree(repo)
    relevant = [e for e in entries if is_ci_relevant(e.path)]
    source = [e.path for e in entries if not is_secret_path(e.path)]
    return {
        "repository": repo,
        "total_files": len(entries),
        "ci_relevant": [{"path": e.path, "sha": e.sha, "size": e.size} for e in relevant[:50]],
        "source_files": source[:MAX_SOURCE_LISTING],
    }


async def _read(ctx: ToolContext, repo: str, path: str) -> dict[str, Any]:
    f = await ctx.runtime.github.read_file(repo, path)
    return {
        "repository": repo,
        "path": f.path,
        "sha": f.sha,
        "size": f.size,
        "truncated": f.truncated,
        "content": f.content,
    }


async def _read_file(ctx: ToolContext, args: ReadFileArgs) -> dict[str, Any]:
    repo = _repo(ctx, args)
    if not is_ci_relevant(args.path):
        raise PolicyDenied(f"path {args.path!r} is outside the CI/CD read scope")
    return await _read(ctx, repo, args.path)


async def _read_source(ctx: ToolContext, args: ReadFileArgs) -> dict[str, Any]:
    repo = _repo(ctx, args)
    _check_source_path(args.path)
    return await _read(ctx, repo, args.path)


async def _list_workflow_runs(ctx: ToolContext, args: WorkflowRunsArgs) -> dict[str, Any]:
    repo = _repo(ctx, args)
    return {
        "repository": repo,
        "runs": await ctx.runtime.github.list_workflow_runs(repo, args.limit),
    }


async def _run_tests(ctx: ToolContext, args: RunTestsArgs) -> dict[str, Any]:
    repo = _repo(ctx, args)
    files: dict[str, str] = {}
    for path in args.repo_paths:
        _check_source_path(path)
        files[path] = (await ctx.runtime.github.read_file(repo, path)).content
    files.update(ctx.workspace_overlay)  # proposed changes win over repository versions
    request = RunRequest(
        template=args.template,
        files=files,
        timeout_seconds=ctx.runtime.settings.sandbox_timeout_seconds,
    )
    result = await ctx.runtime.sandbox.run(request)
    ctx.sandbox_results.append(result)
    return {"workspace_files": sorted(files), **result.model_dump()}


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


async def _propose_changeset(ctx: ToolContext, args: ProposeChangesetArgs) -> dict[str, Any]:
    async with ctx.runtime.sessionmaker() as session:
        result = await ctx.runtime.publisher.propose_changeset(
            session,
            target=args.target,
            project_id=ctx.project_id,
            task_id=ctx.task_id,
            changeset_sha256=args.changeset_sha256,
        )
        await session.commit()
    return result


TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        ToolSpec(
            "github.list_tree",
            "List files of an authorized repository (default branch).",
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
            "github.read_source",
            "Read one source file of an authorized repository (secrets are never readable).",
            ReadFileArgs,
            SideEffect.READ,
            True,
            30,
            30,
            _read_source,
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
            "sandbox.run_tests",
            "Run the test suite in an isolated, offline sandbox on the proposed changes plus "
            "the listed repository files. Returns exit code, counts and output tail.",
            RunTestsArgs,
            SideEffect.ISOLATED_EXECUTION,
            True,
            420,
            3,
            _run_tests,
        ),
        ToolSpec(
            "report.publish_external",
            "Publish a verified report outside Agent HQ (mock adapter).",
            PublishReportArgs,
            SideEffect.EXTERNAL_WRITE,
            False,
            30,
            1,
            _publish_report,
            requires_approval=True,
        ),
        ToolSpec(
            "changeset.propose",
            "Propose a verified changeset as a pull request (mock adapter until Sprint 5).",
            ProposeChangesetArgs,
            SideEffect.EXTERNAL_WRITE,
            False,
            30,
            1,
            _propose_changeset,
            requires_approval=True,
        ),
    )
}


def tool_schemas(names: list[str]) -> list[ToolSchema]:
    return [TOOLS[n].schema() for n in names]


def approval_action(name: str, args: BaseModel) -> ApprovalRequiredAction:
    """Map a sensitive tool call to the action a human must approve."""
    if isinstance(args, PublishReportArgs | ProposeChangesetArgs):
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
    except (GitHubError, SandboxError, ValueError) as exc:
        return ToolOutcome(ok=False, error=str(exc)[:500])
    except DomainError as exc:
        return ToolOutcome(ok=False, error=str(exc))
