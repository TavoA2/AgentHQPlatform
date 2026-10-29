"""Tools Dixon can use in chat (ADR-0015). Read-only, plus task *proposals*.

Every call goes through `execute_chat_tool`: the tool must exist in this registry,
arguments must validate, the per-turn call limit applies and the conversation scope is
injected by code. No tool here changes tasks, approvals or anything outside Agent HQ:
`chat.propose_task` only returns a proposal the owner must confirm in the dashboard.
"""

import asyncio
import json
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_hq.api.agents import derive_agent_statuses
from agent_hq.domain import ApprovalStatus, TaskStatus
from agent_hq.knowledge import chat_search
from agent_hq.llm.base import ToolSchema
from agent_hq.models import ApprovalRequest, Project, Task
from agent_hq.runtime import Runtime
from agent_hq.security.policy import PolicyDenied

MAX_REQUEST_CHARS = 4000


@dataclass
class ChatContext:
    runtime: Runtime
    conversation_id: uuid.UUID
    user_id: uuid.UUID
    # None = company-wide conversation. Fixed at creation, never taken from the model.
    project_id: uuid.UUID | None
    call_counts: Counter[str] = field(default_factory=Counter)
    proposals: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ChatToolOutcome:
    ok: bool
    output: dict[str, Any] | None = None
    error: str | None = None
    denied: bool = False

    def for_model(self) -> str:
        if self.ok:
            return json.dumps(self.output, default=str)
        return json.dumps({"denied" if self.denied else "error": self.error})


Handler = Callable[[ChatContext, AsyncSession, Any], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class ChatToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    max_calls: int
    handler: Handler
    timeout_seconds: float = 15

    def schema(self) -> ToolSchema:
        return ToolSchema(self.name, self.description, self.args_model.model_json_schema())


# --- argument models ---
class NoArgs(BaseModel):
    pass


class ListTasksArgs(BaseModel):
    status: TaskStatus | None = None
    project_key: str | None = Field(default=None, max_length=64)
    limit: int = Field(default=10, ge=1, le=20)


class GetTaskArgs(BaseModel):
    task_id: uuid.UUID


class ListApprovalsArgs(BaseModel):
    limit: int = Field(default=10, ge=1, le=20)


class SearchKnowledgeArgs(BaseModel):
    query: str = Field(min_length=2, max_length=300)
    limit: int = Field(default=5, ge=1, le=8)


class ProposeTaskArgs(BaseModel):
    project_key: str = Field(max_length=64)
    title: str = Field(min_length=3, max_length=200)
    request: str = Field(min_length=10, max_length=MAX_REQUEST_CHARS)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=10)


# --- scope helpers ---
async def _projects(ctx: ChatContext, session: AsyncSession) -> list[Project]:
    query = select(Project).where(Project.status == "active").order_by(Project.created_at)
    if ctx.project_id is not None:
        query = query.where(Project.id == ctx.project_id)
    return list(await session.scalars(query))


async def _project_by_key(ctx: ChatContext, session: AsyncSession, key: str) -> Project:
    project = next((p for p in await _projects(ctx, session) if p.key == key), None)
    if project is None:
        raise PolicyDenied(f"project {key!r} is not available in this conversation")
    return project


def _in_scope(ctx: ChatContext, project_id: uuid.UUID) -> bool:
    return ctx.project_id is None or ctx.project_id == project_id


def _task_brief(task: Task, keys: dict[uuid.UUID, str]) -> dict[str, Any]:
    return {
        "id": str(task.id),
        "title": task.title,
        "status": task.status.value,
        "project": keys.get(task.project_id),
        "updated_at": task.updated_at.isoformat(),
        "failure_reason": task.failure_reason,
        "link": f"/tasks/{task.id}",
    }


async def _project_keys(session: AsyncSession) -> dict[uuid.UUID, str]:
    return {p.id: p.key for p in await session.scalars(select(Project))}


# --- handlers ---
async def _overview(ctx: ChatContext, session: AsyncSession, _: NoArgs) -> dict[str, Any]:
    projects = await _projects(ctx, session)
    ids = [p.id for p in projects]
    counts = await session.execute(
        select(Task.status, func.count())
        .where(Task.parent_task_id.is_(None), Task.project_id.in_(ids))
        .group_by(Task.status)
    )
    pending = await session.scalar(
        select(func.count()).where(
            ApprovalRequest.status == ApprovalStatus.PENDING, ApprovalRequest.project_id.in_(ids)
        )
    )
    keys = {p.id: p.key for p in projects}
    failed = await session.scalars(
        select(Task)
        .where(
            Task.parent_task_id.is_(None),
            Task.project_id.in_(ids),
            Task.status == TaskStatus.FAILED,
        )
        .order_by(Task.updated_at.desc())
        .limit(5)
    )
    return {
        "scope": "project" if ctx.project_id else "company",
        "projects": [{"key": p.key, "name": p.name, "client": p.client_name} for p in projects],
        "tasks_by_status": {s.value: int(n) for s, n in counts},
        "approvals_pending": int(pending or 0),
        "recent_failures": [_task_brief(t, keys) for t in failed],
    }


async def _list_tasks(
    ctx: ChatContext, session: AsyncSession, args: ListTasksArgs
) -> dict[str, Any]:
    query = (
        select(Task)
        .where(Task.parent_task_id.is_(None))
        .order_by(Task.updated_at.desc())
        .limit(args.limit)
    )
    if args.project_key:
        query = query.where(
            Task.project_id == (await _project_by_key(ctx, session, args.project_key)).id
        )
    elif ctx.project_id is not None:
        query = query.where(Task.project_id == ctx.project_id)
    if args.status:
        query = query.where(Task.status == args.status)
    keys = await _project_keys(session)
    return {"tasks": [_task_brief(t, keys) for t in await session.scalars(query)]}


async def _get_task(ctx: ChatContext, session: AsyncSession, args: GetTaskArgs) -> dict[str, Any]:
    task = await session.get(Task, args.task_id)
    if task is None or not _in_scope(ctx, task.project_id):
        raise PolicyDenied("task not found in this conversation's scope")
    keys = await _project_keys(session)
    result = task.result or {}
    subtasks = await session.scalars(
        select(Task).where(Task.parent_task_id == task.id).order_by(Task.created_at)
    )
    approvals = await session.scalars(
        select(ApprovalRequest).where(
            ApprovalRequest.task_id == task.id, ApprovalRequest.status == ApprovalStatus.PENDING
        )
    )
    return {
        **_task_brief(task, keys),
        "request": task.request[:2000],
        "acceptance_criteria": task.acceptance_criteria,
        "workflow": result.get("workflow"),
        "summary": result.get("summary"),
        "verification": result.get("verification"),
        "failure_detail": (task.failure_detail or "")[:500] or None,
        "subtasks": [
            {"title": s.title, "status": s.status.value, "kind": s.options.get("kind")}
            for s in subtasks
        ],
        "pending_approvals": [
            {"action": a.action_type, "target": a.target, "risk": a.risk_level.value}
            for a in approvals
        ],
    }


async def _list_approvals(
    ctx: ChatContext, session: AsyncSession, args: ListApprovalsArgs
) -> dict[str, Any]:
    query = (
        select(ApprovalRequest, Task.title)
        .join(Task, Task.id == ApprovalRequest.task_id)
        .where(ApprovalRequest.status == ApprovalStatus.PENDING)
        .order_by(ApprovalRequest.created_at)
        .limit(args.limit)
    )
    if ctx.project_id is not None:
        query = query.where(ApprovalRequest.project_id == ctx.project_id)
    rows = await session.execute(query)
    return {
        "pending": [
            {
                "task": title,
                "task_link": f"/tasks/{a.task_id}",
                "action": a.action_type,
                "target": a.target,
                "risk": a.risk_level.value,
                "justification": a.justification[:500],
                "expires_at": a.expires_at.isoformat(),
            }
            for a, title in rows
        ],
        "note": "Only the owner can decide approvals, on the Approvals page.",
    }


async def _team(ctx: ChatContext, session: AsyncSession, _: NoArgs) -> dict[str, Any]:
    agents = await derive_agent_statuses(session)
    return {
        "agents": [
            {
                "key": a.key,
                "name": a.display_name,
                "department": a.department,
                "role": a.description,
                "status": a.status.value,
                "current_task_link": f"/tasks/{a.current_task_id}" if a.current_task_id else None,
                "tools": a.allowed_tools,
            }
            for a in agents
            if a.enabled
        ]
    }


async def _search_knowledge(
    ctx: ChatContext, session: AsyncSession, args: SearchKnowledgeArgs
) -> dict[str, Any]:
    hits = await chat_search(session, project_id=ctx.project_id, text=args.query, limit=args.limit)
    return {
        "results": [h.for_agent() for h in hits],
        "note": "unverified entries are agent-written and not confirmed facts",
    }


async def _propose_task(
    ctx: ChatContext, session: AsyncSession, args: ProposeTaskArgs
) -> dict[str, Any]:
    project = await _project_by_key(ctx, session, args.project_key)
    proposal = {
        "id": str(uuid.uuid4()),
        "project_id": str(project.id),
        "project_key": project.key,
        "title": args.title,
        "request": args.request,
        "acceptance_criteria": [c[:300] for c in args.acceptance_criteria],
        "status": "proposed",
        "task_id": None,
    }
    ctx.proposals.append(proposal)
    return {"proposal_id": proposal["id"], "status": "awaiting_owner_confirmation"}


CHAT_TOOLS: dict[str, ChatToolSpec] = {
    spec.name: spec
    for spec in (
        ChatToolSpec(
            "chat.overview",
            "Projects in scope, task counts by status, pending approvals and recent failures.",
            NoArgs,
            2,
            _overview,
        ),
        ChatToolSpec(
            "chat.list_tasks",
            "List recent top-level tasks, optionally filtered by status or project key.",
            ListTasksArgs,
            3,
            _list_tasks,
        ),
        ChatToolSpec(
            "chat.get_task",
            "Details of one task: request, status, outcome summary, subtasks, approvals.",
            GetTaskArgs,
            3,
            _get_task,
        ),
        ChatToolSpec(
            "chat.list_approvals",
            "Pending approval requests. Read-only: only the owner can decide them.",
            ListApprovalsArgs,
            2,
            _list_approvals,
        ),
        ChatToolSpec(
            "chat.team",
            "The agent team: roles, permitted tools and current status (from real runs).",
            NoArgs,
            2,
            _team,
        ),
        ChatToolSpec(
            "chat.search_knowledge",
            "Search The Brain (company knowledge, plus project knowledge in a project chat).",
            SearchKnowledgeArgs,
            3,
            _search_knowledge,
        ),
        ChatToolSpec(
            "chat.propose_task",
            "Propose a new task for the agents. It is NOT created: the owner must confirm the "
            "proposal card in the dashboard.",
            ProposeTaskArgs,
            2,
            _propose_task,
        ),
    )
}


def chat_tool_schemas() -> list[ToolSchema]:
    return [spec.schema() for spec in CHAT_TOOLS.values()]


async def execute_chat_tool(
    ctx: ChatContext, name: str, raw_args: dict[str, Any]
) -> ChatToolOutcome:
    spec = CHAT_TOOLS.get(name)
    try:
        if spec is None:
            raise PolicyDenied(f"unknown tool {name!r}")
        try:
            args = spec.args_model.model_validate(raw_args)
        except ValidationError as exc:
            return ChatToolOutcome(ok=False, error=f"invalid arguments: {exc.error_count()} errors")
        ctx.call_counts[name] += 1
        if ctx.call_counts[name] > spec.max_calls:
            raise PolicyDenied(f"call limit for {name!r} reached ({spec.max_calls})")
        async with ctx.runtime.sessionmaker() as session:
            output = await asyncio.wait_for(spec.handler(ctx, session, args), spec.timeout_seconds)
        return ChatToolOutcome(ok=True, output=output)
    except PolicyDenied as exc:
        return ChatToolOutcome(ok=False, error=exc.reason, denied=True)
    except TimeoutError:
        return ChatToolOutcome(ok=False, error="tool timed out")
