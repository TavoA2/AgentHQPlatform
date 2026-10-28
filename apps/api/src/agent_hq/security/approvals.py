"""Action-bound, single-use human approvals (ADR-0006)."""

import hashlib
import json
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agent_hq.domain import ApprovalStatus, DomainError, RiskLevel
from agent_hq.events import record_audit, record_task_event, to_json
from agent_hq.models import ApprovalRequest, Task, User, utcnow


class ApprovalError(DomainError):
    pass


def canonical_action(action_type: str, target: str, parameters: dict[str, Any]) -> str:
    return json.dumps(
        {"action_type": action_type, "target": target, "parameters": parameters},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def action_hash(action_type: str, target: str, parameters: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_action(action_type, target, parameters).encode()).hexdigest()


async def request_approval(
    session: AsyncSession,
    *,
    task: Task,
    execution_id: uuid.UUID | None,
    agent_id: uuid.UUID,
    agent_key: str,
    action_type: str,
    target: str,
    parameters: dict[str, Any],
    justification: str,
    expected_impact: str,
    risk_level: RiskLevel,
    evidence: dict[str, Any],
    ttl: timedelta,
) -> ApprovalRequest:
    """Create an approval, or return the existing one for the same exact action.

    Idempotent across node re-execution: whatever its status, an approval for an identical
    action (same task, same hash) is returned instead of a new one. Actions that should get
    a fresh approval must differ in their parameters (e.g. the run number).
    """
    parameters = to_json(parameters)
    digest = action_hash(action_type, target, parameters)
    existing = await session.scalar(
        select(ApprovalRequest)
        .where(ApprovalRequest.task_id == task.id, ApprovalRequest.action_hash == digest)
        .order_by(ApprovalRequest.created_at.desc())
        .limit(1)
    )
    if existing is not None:
        return existing
    approval = ApprovalRequest(
        task_id=task.id,
        project_id=task.project_id,
        execution_id=execution_id,
        requested_by_agent_id=agent_id,
        action_type=action_type,
        target=target,
        parameters=parameters,
        action_hash=digest,
        justification=justification,
        expected_impact=expected_impact,
        risk_level=risk_level,
        evidence=to_json(evidence),
        status=ApprovalStatus.PENDING,
        expires_at=utcnow() + ttl,
    )
    session.add(approval)
    await session.flush()
    await record_task_event(
        session,
        task_id=task.id,
        project_id=task.project_id,
        execution_id=execution_id,
        agent_key=agent_key,
        type="approval_requested",
        payload={"approval_id": str(approval.id), "action_type": action_type, "target": target},
    )
    await record_audit(
        session,
        actor_type="agent",
        actor_id=agent_key,
        action="approval.requested",
        project_id=task.project_id,
        resource_type="approval",
        resource_id=approval.id,
        details={"action_type": action_type, "target": target, "action_hash": digest},
    )
    return approval


async def decide(
    session: AsyncSession, *, approval_id: uuid.UUID, user: User, approve: bool, note: str | None
) -> ApprovalRequest:
    """Record a human decision. Only users can call this; no agent tool maps to it."""
    approval = await session.get(
        ApprovalRequest, approval_id, with_for_update=True, populate_existing=True
    )
    if approval is None:
        raise ApprovalError("approval not found")
    if approval.status != ApprovalStatus.PENDING:
        raise ApprovalError(f"approval is {approval.status}, not pending")
    if approval.expires_at <= utcnow():
        raise ApprovalError("approval has expired")
    approval.status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
    approval.decided_by = user.id
    approval.decided_at = utcnow()
    approval.decision_note = note
    await session.flush()
    await _record_decision(session, approval, actor_type="user", actor_id=str(user.id))
    return approval


async def expire_due(session: AsyncSession) -> list[ApprovalRequest]:
    rows = await session.scalars(
        select(ApprovalRequest)
        .where(
            ApprovalRequest.status == ApprovalStatus.PENDING,
            ApprovalRequest.expires_at <= utcnow(),
        )
        .with_for_update(skip_locked=True)
    )
    expired = list(rows)
    for approval in expired:
        approval.status = ApprovalStatus.EXPIRED
        approval.decided_at = utcnow()
        await session.flush()
        await _record_decision(session, approval, actor_type="system", actor_id=None)
    return expired


async def cancel_open_for_task(session: AsyncSession, task_id: uuid.UUID) -> None:
    await session.execute(
        update(ApprovalRequest)
        .where(
            ApprovalRequest.task_id == task_id,
            ApprovalRequest.status == ApprovalStatus.PENDING,
        )
        .values(status=ApprovalStatus.CANCELLED, decided_at=utcnow())
    )


async def _record_decision(
    session: AsyncSession, approval: ApprovalRequest, *, actor_type: Any, actor_id: str | None
) -> None:
    payload = {"approval_id": str(approval.id), "status": approval.status.value}
    await record_task_event(
        session,
        task_id=approval.task_id,
        project_id=approval.project_id,
        type="approval_decided",
        payload=payload,
    )
    await record_audit(
        session,
        actor_type=actor_type,
        actor_id=actor_id,
        action=f"approval.{approval.status.value}",
        project_id=approval.project_id,
        resource_type="approval",
        resource_id=approval.id,
        details={"action_hash": approval.action_hash, "note": approval.decision_note},
    )


async def consume(
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
    action_type: str,
    target: str,
    parameters: dict[str, Any],
    agent_key: str,
) -> ApprovalRequest:
    """Atomically consume a matching approval right before executing the action.

    The hash is recomputed from the arguments actually being executed, so any parameter
    change after approval fails. The conditional UPDATE makes consumption single-use even
    under concurrency.
    """
    digest = action_hash(action_type, target, to_json(parameters))
    approval_id = await session.scalar(
        update(ApprovalRequest)
        .where(
            ApprovalRequest.task_id == task_id,
            ApprovalRequest.action_hash == digest,
            ApprovalRequest.status == ApprovalStatus.APPROVED,
            ApprovalRequest.consumed_at.is_(None),
            ApprovalRequest.expires_at > utcnow(),
        )
        .values(consumed_at=utcnow())
        .returning(ApprovalRequest.id)
    )
    if approval_id is None:
        raise ApprovalError("no unconsumed approval matches this exact action")
    approval = await session.get(ApprovalRequest, approval_id, populate_existing=True)
    if approval is None:
        raise RuntimeError("approval not found")
    await record_audit(
        session,
        actor_type="agent",
        actor_id=agent_key,
        action="approval.consumed",
        project_id=approval.project_id,
        resource_type="approval",
        resource_id=approval.id,
        details={"action_hash": digest},
    )
    return approval
