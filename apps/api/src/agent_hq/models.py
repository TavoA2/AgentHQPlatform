"""SQLAlchemy ORM models. See docs/architecture/data-model.md."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from agent_hq.domain import (
    ApprovalStatus,
    ExecutionStatus,
    JobKind,
    JobStatus,
    KnowledgeScope,
    KnowledgeTrust,
    RiskLevel,
    TaskStatus,
)
from agent_hq.ids import uuid7


def utcnow() -> datetime:
    return datetime.now(UTC)


def _enum(enum_cls: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda e: [m.value for m in e],
    )


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        datetime: DateTime(timezone=True),
        dict[str, Any]: JSONB,
        list[Any]: JSONB,
    }


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        default=utcnow, onupdate=utcnow, server_default=func.now()
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="admin")
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())
    last_login_at: Mapped[datetime | None]
    # TOTP 2FA (security/totp.py): encrypted secret, enrollment time, last used step.
    totp_secret_encrypted: Mapped[str | None] = mapped_column(Text)
    totp_enabled_at: Mapped[datetime | None]
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger)


class UserSession(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    client_name: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), default="active")
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))

    __table_args__ = (CheckConstraint("status IN ('active', 'archived')", name="status"),)


class Agent(TimestampMixin, Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    department: Mapped[str] = mapped_column(String(64))
    model_profile: Mapped[str] = mapped_column(String(64))
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    enabled: Mapped[bool] = mapped_column(default=True)


class Integration(TimestampMixin, Base):
    __tablename__ = "integrations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(120))
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    # Name of the secret (environment variable / secret manager key), never its value.
    secret_ref: Mapped[str | None] = mapped_column(String(120))
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)
    enabled: Mapped[bool] = mapped_column(default=True)

    __table_args__ = (UniqueConstraint("project_id", "provider", "name"),)


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    parent_task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id"))
    title: Mapped[str] = mapped_column(String(200))
    request: Mapped[str] = mapped_column(Text)
    status: Mapped[TaskStatus] = mapped_column(_enum(TaskStatus, "task_status"))
    assigned_agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id"))
    priority: Mapped[int] = mapped_column(default=0)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    acceptance_criteria: Mapped[list[Any]] = mapped_column(default=list)
    options: Mapped[dict[str, Any]] = mapped_column(default=dict)
    result: Mapped[dict[str, Any] | None]
    failure_reason: Mapped[str | None] = mapped_column(String(64))
    failure_detail: Mapped[str | None] = mapped_column(Text)
    run_number: Mapped[int] = mapped_column(default=0)
    version: Mapped[int] = mapped_column(default=1)
    completed_at: Mapped[datetime | None]

    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012
    __table_args__ = (
        Index("ix_tasks_project_status", "project_id", "status"),
        Index("ix_tasks_agent_status", "assigned_agent_id", "status"),
    )


class TaskExecution(Base):
    __tablename__ = "task_executions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id"))
    run_number: Mapped[int]
    attempt: Mapped[int]
    status: Mapped[ExecutionStatus] = mapped_column(_enum(ExecutionStatus, "execution_status"))
    graph_thread_id: Mapped[str] = mapped_column(String(80))
    input: Mapped[dict[str, Any]] = mapped_column(default=dict)
    output: Mapped[dict[str, Any] | None]
    error: Mapped[dict[str, Any] | None]
    model_provider: Mapped[str | None] = mapped_column(String(32))
    model_name: Mapped[str | None] = mapped_column(String(120))
    model_calls: Mapped[int] = mapped_column(default=0)
    tokens_in: Mapped[int] = mapped_column(BigInteger, default=0)
    tokens_out: Mapped[int] = mapped_column(BigInteger, default=0)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None]

    __table_args__ = (
        UniqueConstraint("task_id", "agent_id", "run_number", "attempt"),
        Index("ix_task_executions_agent_started", "agent_id", "started_at"),
    )


class TaskEvent(Base):
    """Append-only (enforced by trigger). The id orders events and backs SSE replay."""

    __tablename__ = "task_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    execution_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("task_executions.id"))
    agent_key: Mapped[str | None] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(48))
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (Index("ix_task_events_task_id", "task_id", "id"),)


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    execution_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("task_executions.id"))
    requested_by_agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id"))
    action_type: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(300))
    parameters: Mapped[dict[str, Any]]
    action_hash: Mapped[str] = mapped_column(String(64))
    justification: Mapped[str] = mapped_column(Text)
    expected_impact: Mapped[str] = mapped_column(Text)
    risk_level: Mapped[RiskLevel] = mapped_column(_enum(RiskLevel, "risk_level"))
    evidence: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[ApprovalStatus] = mapped_column(_enum(ApprovalStatus, "approval_status"))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decision_note: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None]
    expires_at: Mapped[datetime]
    consumed_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        CheckConstraint(
            "status NOT IN ('approved', 'rejected') OR decided_by IS NOT NULL",
            name="decided_by_required",
        ),
        CheckConstraint("consumed_at IS NULL OR status = 'approved'", name="consume_only_approved"),
        Index("ix_approval_requests_status", "status", "created_at"),
        Index("ix_approval_requests_task_hash", "task_id", "action_hash"),
    )


class AuditEvent(Base):
    """Append-only, hash-chained (enforced by trigger)."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    actor_type: Mapped[str] = mapped_column(String(16))
    actor_id: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    project_id: Mapped[uuid.UUID | None]
    resource_type: Mapped[str | None] = mapped_column(String(48))
    resource_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    prev_hash: Mapped[str | None] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime]

    __table_args__ = (
        CheckConstraint("actor_type IN ('user', 'agent', 'system')", name="actor_type"),
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    kind: Mapped[JobKind] = mapped_column(_enum(JobKind, "job_kind"))
    # Exactly one of task_id (agent work) or conversation_id (chat reply, ADR-0015).
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[JobStatus] = mapped_column(_enum(JobStatus, "job_status"))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    # Database clock: claims compare it with now() in SQL, so a host clock running ahead
    # of the database must not delay new jobs.
    run_after: Mapped[datetime] = mapped_column(server_default=func.now())
    locked_by: Mapped[str | None] = mapped_column(String(120))
    lease_expires_at: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("ix_jobs_status_run_after", "status", "run_after"),
        CheckConstraint("(task_id IS NULL) <> (conversation_id IS NULL)", name="one_target"),
    )


class KnowledgeDocument(Base):
    """The Brain (ADR-0012). Current content lives here for search; history in versions."""

    __tablename__ = "knowledge_documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    scope: Mapped[KnowledgeScope] = mapped_column(_enum(KnowledgeScope, "knowledge_scope"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    trust: Mapped[KnowledgeTrust] = mapped_column(_enum(KnowledgeTrust, "knowledge_trust"))
    # Agent keys allowed to read this document; empty = every agent.
    audience: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)
    version: Mapped[int] = mapped_column(default=1)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_by_agent: Mapped[str | None] = mapped_column(String(64))
    source_task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL")
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('simple', coalesce(title, '')), 'A') || "
            "setweight(to_tsvector('simple', coalesce(content, '')), 'B')",
            persisted=True,
        ),
    )

    __table_args__ = (
        CheckConstraint(
            "(scope = 'company' AND project_id IS NULL) OR "
            "(scope = 'project' AND project_id IS NOT NULL)",
            name="scope_project",
        ),
        CheckConstraint(
            "created_by_user_id IS NOT NULL OR created_by_agent IS NOT NULL", name="has_author"
        ),
        Index("ix_knowledge_documents_search", "search_vector", postgresql_using="gin"),
        Index("ix_knowledge_documents_scope", "scope", "project_id", "trust"),
    )


class KnowledgeDocumentVersion(Base):
    """Immutable history of a knowledge document (append-only, enforced by trigger)."""

    __tablename__ = "knowledge_document_versions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE")
    )
    version: Mapped[int]
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    trust: Mapped[KnowledgeTrust] = mapped_column(_enum(KnowledgeTrust, "knowledge_trust"))
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    changed_by_agent: Mapped[str | None] = mapped_column(String(64))
    source_task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (UniqueConstraint("document_id", "version"),)


class Notification(Base):
    """Transactional outbox for outbound notifications (ADR-0013)."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    kind: Mapped[str] = mapped_column(String(48))
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    delivered_channels: Mapped[list[str]] = mapped_column(ARRAY(String(32)), default=list)
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    run_after: Mapped[datetime] = mapped_column(default=utcnow)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    sent_at: Mapped[datetime | None]

    __table_args__ = (
        CheckConstraint("status IN ('pending', 'sent', 'skipped', 'failed')", name="status"),
        Index("ix_notifications_pending", "status", "run_after"),
    )


class Conversation(Base):
    """A chat with Dixon (ADR-0015). The scope (company-wide or one project) is fixed."""

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(200))
    # "chat", or "alerts": the one per-user thread where Dixon posts alerts (ADR-0016).
    kind: Mapped[str] = mapped_column(String(16), default="chat")
    last_read_message_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        CheckConstraint("kind IN ('chat', 'alerts')", name="kind"),
        Index("ix_conversations_user_updated", "user_id", "updated_at"),
        Index(
            "uq_conversations_user_alerts",
            "user_id",
            unique=True,
            postgresql_where=text("kind = 'alerts'"),
        ),
    )


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text, default="")
    alert_kind: Mapped[str | None] = mapped_column(String(48))  # set on Dixon's alerts
    status: Mapped[str] = mapped_column(String(16), default="complete")
    # Tools the reply used ({name, arguments, ok, error}) and task proposals awaiting the
    # owner's confirmation ({id, project_id, title, request, ..., task_id once accepted}).
    tool_calls: Mapped[list[Any]] = mapped_column(default=list)
    proposals: Mapped[list[Any]] = mapped_column(default=list)
    error: Mapped[str | None] = mapped_column(Text)
    model_provider: Mapped[str | None] = mapped_column(String(32))
    model_name: Mapped[str | None] = mapped_column(String(120))
    tokens_in: Mapped[int] = mapped_column(BigInteger, default=0)
    tokens_out: Mapped[int] = mapped_column(BigInteger, default=0)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    completed_at: Mapped[datetime | None]

    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="role"),
        CheckConstraint("status IN ('pending', 'complete', 'failed')", name="status"),
        Index("ix_conversation_messages_conversation", "conversation_id", "id"),
    )
