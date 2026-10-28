"""Domain enums, the task state machine and domain errors."""

from enum import StrEnum


class TaskStatus(StrEnum):
    DRAFT = "DRAFT"
    PLANNED = "PLANNED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    IN_REVIEW = "IN_REVIEW"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ExecutionStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class JobKind(StrEnum):
    START = "start"
    RESUME = "resume"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class AgentStatus(StrEnum):
    """Visual status derived from real executions (never simulated)."""

    IDLE = "IDLE"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    FAILED = "FAILED"


_T = TaskStatus

TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    _T.DRAFT: frozenset({_T.PLANNED, _T.QUEUED, _T.CANCELLED}),
    _T.PLANNED: frozenset({_T.QUEUED, _T.CANCELLED}),
    _T.QUEUED: frozenset({_T.RUNNING, _T.CANCELLED, _T.FAILED}),
    _T.RUNNING: frozenset({_T.WAITING_APPROVAL, _T.IN_REVIEW, _T.FAILED, _T.CANCELLED}),
    _T.WAITING_APPROVAL: frozenset({_T.RUNNING, _T.FAILED, _T.CANCELLED}),
    _T.IN_REVIEW: frozenset({_T.COMPLETED, _T.RUNNING, _T.FAILED}),
    _T.FAILED: frozenset({_T.QUEUED}),
    _T.COMPLETED: frozenset(),
    _T.CANCELLED: frozenset(),
}

TERMINAL = frozenset({_T.COMPLETED, _T.CANCELLED})
STARTABLE = frozenset({_T.DRAFT, _T.PLANNED, _T.FAILED})
CANCELLABLE = frozenset(s for s, targets in TRANSITIONS.items() if _T.CANCELLED in targets)


class DomainError(Exception):
    """Base class for errors that must not be retried automatically."""


class InvalidTransitionError(DomainError):
    def __init__(self, current: TaskStatus, target: TaskStatus) -> None:
        super().__init__(f"invalid task transition {current} -> {target}")
        self.current = current
        self.target = target


class TaskCancelledError(DomainError):
    pass


def check_transition(current: TaskStatus, target: TaskStatus) -> None:
    if target not in TRANSITIONS[current]:
        raise InvalidTransitionError(current, target)
