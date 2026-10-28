"""HTTP request/response contracts."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_hq.domain import AgentStatus, ApprovalStatus, ExecutionStatus, RiskLevel, TaskStatus
from agent_hq.llm.base import parse_model_ref
from agent_hq.security.policy import REPO_PATTERN


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- auth ---
class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class UserOut(Out):
    id: uuid.UUID
    email: str
    display_name: str
    role: str


class LoginOut(BaseModel):
    user: UserOut
    csrf_token: str


# --- projects ---
class ProjectIn(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    client_name: str | None = Field(default=None, max_length=200)


class GitHubIntegrationIn(BaseModel):
    allowed_repos: list[str] = Field(min_length=1, max_length=50)

    @field_validator("allowed_repos")
    @classmethod
    def _valid_repos(cls, repos: list[str]) -> list[str]:
        for repo in repos:
            if not REPO_PATTERN.match(repo):
                raise ValueError(f"invalid repository name {repo!r} (expected owner/name)")
        return sorted(set(repos))


class IntegrationOut(Out):
    id: uuid.UUID
    provider: str
    name: str
    config: dict[str, Any]
    secret_ref: str | None
    scopes: list[str]
    enabled: bool


class ProjectOut(Out):
    id: uuid.UUID
    key: str
    name: str
    description: str
    client_name: str | None
    status: str
    created_at: datetime


class ProjectDetailOut(ProjectOut):
    integrations: list[IntegrationOut]


# --- tasks ---
class TaskIn(BaseModel):
    project_id: uuid.UUID
    title: str = Field(min_length=1, max_length=200)
    request: str = Field(min_length=1, max_length=20000)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=50)
    model_override: str | None = Field(
        default=None, description="Optional 'provider:model' for every agent in this task"
    )

    @field_validator("model_override")
    @classmethod
    def _valid_model(cls, value: str | None) -> str | None:
        if value is not None:
            parse_model_ref(value)
        return value


class TaskOut(Out):
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    request: str
    status: TaskStatus
    assigned_agent_key: str | None = None
    acceptance_criteria: list[Any]
    options: dict[str, Any]
    result: dict[str, Any] | None
    failure_reason: str | None
    failure_detail: str | None
    run_number: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class ExecutionOut(Out):
    id: uuid.UUID
    agent_key: str
    run_number: int
    attempt: int
    status: ExecutionStatus
    input: dict[str, Any]
    output: dict[str, Any] | None
    error: dict[str, Any] | None
    model_provider: str | None
    model_name: str | None
    model_calls: int
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal | None
    started_at: datetime
    finished_at: datetime | None


class ApprovalOut(Out):
    id: uuid.UUID
    task_id: uuid.UUID
    project_id: uuid.UUID
    requested_by_agent_key: str
    action_type: str
    target: str
    parameters: dict[str, Any]
    action_hash: str
    justification: str
    expected_impact: str
    risk_level: RiskLevel
    evidence: dict[str, Any]
    status: ApprovalStatus
    decision_note: str | None
    decided_at: datetime | None
    expires_at: datetime
    consumed_at: datetime | None
    created_at: datetime


class TaskDetailOut(TaskOut):
    executions: list[ExecutionOut]
    approvals: list[ApprovalOut]


class EventOut(Out):
    id: int
    task_id: uuid.UUID
    project_id: uuid.UUID
    execution_id: uuid.UUID | None
    agent_key: str | None
    type: str
    payload: dict[str, Any]
    created_at: datetime


class DecisionIn(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


def execution_out(e: Any, agent_keys: dict[uuid.UUID, str]) -> ExecutionOut:
    fields = {f: getattr(e, f) for f in ExecutionOut.model_fields if f != "agent_key"}
    return ExecutionOut(**fields, agent_key=agent_keys[e.agent_id])


def approval_out(a: Any, agent_keys: dict[uuid.UUID, str]) -> ApprovalOut:
    fields = {f: getattr(a, f) for f in ApprovalOut.model_fields if f != "requested_by_agent_key"}
    return ApprovalOut(**fields, requested_by_agent_key=agent_keys[a.requested_by_agent_id])


# --- agents ---
class AgentOut(BaseModel):
    key: str
    display_name: str
    department: str
    description: str
    model_profile: str
    enabled: bool
    status: AgentStatus
    current_task_id: uuid.UUID | None
    last_execution: ExecutionOut | None
    allowed_tools: list[str]
