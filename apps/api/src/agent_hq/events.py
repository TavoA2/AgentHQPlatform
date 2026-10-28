"""Task events (live feed + history) and the hash-chained audit log."""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from agent_hq.logging import redact
from agent_hq.models import AuditEvent, TaskEvent, utcnow

NOTIFY_CHANNEL = "task_events"
_AUDIT_LOCK_KEY = 0x41554449  # "AUDI": serializes appends so the hash chain stays linear

ActorType = Literal["user", "agent", "system"]


def to_json(value: Any) -> Any:
    """Round-trip through JSON so JSONB columns only ever receive plain JSON values."""
    return json.loads(json.dumps(value, default=str))


async def record_task_event(
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
    project_id: uuid.UUID,
    type: str,
    payload: dict[str, Any] | None = None,
    execution_id: uuid.UUID | None = None,
    agent_key: str | None = None,
) -> TaskEvent:
    event = TaskEvent(
        task_id=task_id,
        project_id=project_id,
        execution_id=execution_id,
        agent_key=agent_key,
        type=type,
        payload=to_json(redact(payload or {})),
    )
    session.add(event)
    await session.flush()
    # Delivered on commit, together with the row, so listeners never see phantom events.
    await session.execute(
        text("SELECT pg_notify(:channel, :id)"), {"channel": NOTIFY_CHANNEL, "id": str(event.id)}
    )
    return event


def _audit_hash(prev_hash: str | None, fields: dict[str, Any]) -> str:
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{prev_hash or ''}|{canonical}".encode()).hexdigest()


def _audit_fields(
    *,
    actor_type: str,
    actor_id: str | None,
    action: str,
    project_id: uuid.UUID | None,
    resource_type: str | None,
    resource_id: str | None,
    details: dict[str, Any],
    created_at: datetime,
) -> dict[str, Any]:
    return {
        "actor_type": actor_type,
        "actor_id": actor_id,
        "action": action,
        "project_id": str(project_id) if project_id else None,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "details": details,
        # Normalized to UTC: the session time zone must not change the hash.
        "created_at": created_at.astimezone(UTC).isoformat(),
    }


async def record_audit(
    session: AsyncSession,
    *,
    actor_type: ActorType,
    actor_id: str | None,
    action: str,
    project_id: uuid.UUID | None = None,
    resource_type: str | None = None,
    resource_id: str | uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    await session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _AUDIT_LOCK_KEY})
    prev_hash = await session.scalar(
        select(AuditEvent.hash).order_by(AuditEvent.id.desc()).limit(1)
    )
    created_at = utcnow()
    safe_details = to_json(redact(details or {}))
    rid = str(resource_id) if resource_id is not None else None
    fields = _audit_fields(
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        project_id=project_id,
        resource_type=resource_type,
        resource_id=rid,
        details=safe_details,
        created_at=created_at,
    )
    event = AuditEvent(
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        project_id=project_id,
        resource_type=resource_type,
        resource_id=rid,
        details=safe_details,
        prev_hash=prev_hash,
        hash=_audit_hash(prev_hash, fields),
        created_at=created_at,
    )
    session.add(event)
    await session.flush()
    return event


async def verify_audit_chain(session: AsyncSession) -> tuple[bool, int | None]:
    """Recompute the chain. Returns (ok, id of the first broken row)."""
    prev_hash: str | None = None
    result = await session.stream_scalars(select(AuditEvent).order_by(AuditEvent.id))
    async for event in result:
        fields = _audit_fields(
            actor_type=event.actor_type,
            actor_id=event.actor_id,
            action=event.action,
            project_id=event.project_id,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            details=event.details,
            created_at=event.created_at,
        )
        if event.prev_hash != prev_hash or event.hash != _audit_hash(prev_hash, fields):
            return False, event.id
        prev_hash = event.hash
    return True, None
