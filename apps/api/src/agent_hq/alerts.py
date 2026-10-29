"""Proactive alerts from Dixon (ADR-0016).

Alerts are notification-outbox rows. This module schedules the time-based ones (approval
reminders, the daily briefing), renders every alert from database facts (never from a
model) and delivers the in-app copy into each recipient's Alerts conversation.
"""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_hq.config import Settings
from agent_hq.domain import ApprovalStatus, KnowledgeTrust, TaskStatus
from agent_hq.models import (
    ApprovalRequest,
    Conversation,
    ConversationMessage,
    KnowledgeDocument,
    Notification,
    Task,
    TaskExecution,
    User,
    utcnow,
)

TEXT: dict[str, dict[str, str]] = {
    "en": {
        "approval_requested": "Approval needed",
        "task_completed": "Task completed",
        "task_failed": "Task failed",
        "approval_reminder": "Still waiting for your approval",
        "daily_brief": "Daily briefing",
        "reason": "Reason",
        "waiting": "Waiting {hours} h; expires in {left} h.",
        "thread": "Dixon · Alerts",
        "completed": "Completed in the last 24 h: {n}",
        "failed": "Failed in the last 24 h: {n}",
        "in_progress": "In progress: {n}",
        "pending": "Waiting for your approval: {n} (oldest {hours} h)",
        "unverified": "Brain entries awaiting your review: {n}",
        "usage": "Model usage in the last 24 h: {tokens} tokens{cost}",
        "approvals_link": "Approvals",
    },
    "es": {
        "approval_requested": "Necesito tu aprobación",
        "task_completed": "Tarea completada",
        "task_failed": "Tarea fallida",
        "approval_reminder": "Sigue esperando tu aprobación",
        "daily_brief": "Resumen diario",
        "reason": "Motivo",
        "waiting": "Lleva {hours} h esperando; vence en {left} h.",
        "thread": "Dixon · Alertas",
        "completed": "Completadas en las últimas 24 h: {n}",
        "failed": "Fallidas en las últimas 24 h: {n}",
        "in_progress": "En curso: {n}",
        "pending": "Esperan tu aprobación: {n} (la más antigua, {hours} h)",
        "unverified": "Entradas de The Brain por revisar: {n}",
        "usage": "Uso de modelos en las últimas 24 h: {tokens} tokens{cost}",
        "approvals_link": "Aprobaciones",
    },
}


def _t(settings: Settings, key: str, **values: Any) -> str:
    return TEXT[settings.alert_language][key].format(**values)


def render(settings: Settings, n: Notification, *, base_url: str = "") -> str:
    """Alert text from the outbox row's facts. `base_url` makes links absolute."""
    p = n.payload
    headline = TEXT[settings.alert_language].get(n.kind) or str(p.get("headline", n.kind))
    lines = [f"{headline}: {p['title']}" if p.get("title") else headline]
    if p.get("summary"):
        lines.append(str(p["summary"]))
    if p.get("reason"):
        lines.append(f"{_t(settings, 'reason')}: {p['reason']}")
    if n.kind == "approval_reminder":
        lines.append(_t(settings, "waiting", hours=p["waiting_hours"], left=p["expires_in_hours"]))
    lines.extend(str(line) for line in p.get("lines", []))
    if n.task_id:
        lines.append(f"{base_url}/tasks/{n.task_id}")
    return "\n".join(lines)


# --- scheduling (called from the worker's maintenance tick) ---
async def _exists(session: AsyncSession, kind: str, key: str, value: str) -> bool:
    found = await session.scalar(
        select(Notification.id)
        .where(Notification.kind == kind, Notification.payload[key].astext == value)
        .limit(1)
    )
    return found is not None


async def schedule_approval_reminders(
    session: AsyncSession, settings: Settings, now: datetime
) -> int:
    hours = settings.alert_approval_reminder_hours
    if hours <= 0:
        return 0
    rows = await session.execute(
        select(ApprovalRequest, Task.title)
        .join(Task, Task.id == ApprovalRequest.task_id)
        .where(
            ApprovalRequest.status == ApprovalStatus.PENDING,
            ApprovalRequest.created_at <= now - timedelta(hours=hours),
            ApprovalRequest.expires_at > now,
        )
    )
    created = 0
    for approval, title in rows:
        if await _exists(session, "approval_reminder", "approval_id", str(approval.id)):
            continue
        session.add(
            Notification(
                kind="approval_reminder",
                task_id=approval.task_id,
                project_id=approval.project_id,
                payload={
                    "approval_id": str(approval.id),
                    "title": title[:120],
                    "waiting_hours": int((now - approval.created_at).total_seconds() // 3600),
                    "expires_in_hours": int((approval.expires_at - now).total_seconds() // 3600),
                },
            )
        )
        created += 1
    await session.flush()
    return created


async def _brief_lines(session: AsyncSession, settings: Settings, now: datetime) -> list[str]:
    since = now - timedelta(hours=24)
    top = Task.parent_task_id.is_(None)
    completed = list(
        await session.scalars(
            select(Task)
            .where(top, Task.status == TaskStatus.COMPLETED, Task.completed_at >= since)
            .order_by(Task.completed_at.desc())
        )
    )
    failed = list(
        await session.scalars(
            select(Task)
            .where(top, Task.status == TaskStatus.FAILED, Task.updated_at >= since)
            .order_by(Task.updated_at.desc())
        )
    )
    in_progress = await session.scalar(
        select(func.count()).where(
            top,
            Task.status.in_([TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.IN_REVIEW]),
        )
    )
    pending = await session.execute(
        select(func.count(), func.min(ApprovalRequest.created_at)).where(
            ApprovalRequest.status == ApprovalStatus.PENDING
        )
    )
    pending_count, oldest = pending.one()
    unverified = await session.scalar(
        select(func.count()).where(KnowledgeDocument.trust == KnowledgeTrust.UNVERIFIED)
    )
    agent_usage = (
        await session.execute(
            select(
                func.coalesce(func.sum(TaskExecution.tokens_in + TaskExecution.tokens_out), 0),
                func.sum(TaskExecution.cost_usd),
            ).where(TaskExecution.started_at >= since)
        )
    ).one()
    chat_usage = (
        await session.execute(
            select(
                func.coalesce(
                    func.sum(ConversationMessage.tokens_in + ConversationMessage.tokens_out), 0
                ),
                func.sum(ConversationMessage.cost_usd),
            ).where(ConversationMessage.created_at >= since)
        )
    ).one()
    tokens = int(agent_usage[0]) + int(chat_usage[0])
    costs = [c for c in (agent_usage[1], chat_usage[1]) if c is not None]

    if not (completed or failed or in_progress or pending_count or unverified or tokens):
        return []
    lines: list[str] = []
    if completed:
        lines.append(_t(settings, "completed", n=len(completed)))
        lines += [f"  • {t.title} (/tasks/{t.id})" for t in completed[:3]]
    if failed:
        lines.append(_t(settings, "failed", n=len(failed)))
        lines += [f"  • {t.title} (/tasks/{t.id})" for t in failed[:3]]
    if in_progress:
        lines.append(_t(settings, "in_progress", n=in_progress))
    if pending_count:
        hours = int((now - oldest).total_seconds() // 3600)
        lines.append(_t(settings, "pending", n=pending_count, hours=hours) + " → /approvals")
    if unverified:
        lines.append(_t(settings, "unverified", n=unverified) + " → /knowledge")
    if tokens:
        cost = f" · ${sum(costs, Decimal(0)):.4f}" if costs else ""
        lines.append(_t(settings, "usage", tokens=f"{tokens:,}", cost=cost))
    return lines


async def schedule_daily_brief(session: AsyncSession, settings: Settings, now: datetime) -> bool:
    hour = settings.alert_daily_brief_hour_utc
    if hour < 0 or now.hour < hour:
        return False
    day = now.date().isoformat()
    if await _exists(session, "daily_brief", "date", day):
        return False
    lines = await _brief_lines(session, settings, now)
    # Recorded even when empty, so a quiet day is decided once and not re-checked all day.
    session.add(
        Notification(
            kind="daily_brief",
            payload={"date": day, "title": day, "lines": lines},
            status="pending" if lines else "skipped",
        )
    )
    await session.flush()
    return bool(lines)


async def schedule(session: AsyncSession, settings: Settings, now: datetime | None = None) -> None:
    now = now or utcnow()
    await schedule_approval_reminders(session, settings, now)
    await schedule_daily_brief(session, settings, now)


# --- in-app delivery ---
async def recipients(session: AsyncSession, settings: Settings) -> list[User]:
    roles = ["admin", "viewer"] if settings.demo_mode else ["admin"]
    return list(await session.scalars(select(User).where(User.is_active, User.role.in_(roles))))


async def alerts_conversation(
    session: AsyncSession, settings: Settings, user_id: uuid.UUID
) -> Conversation:
    conversation = await session.scalar(
        select(Conversation).where(Conversation.user_id == user_id, Conversation.kind == "alerts")
    )
    if conversation is None:
        conversation = Conversation(user_id=user_id, kind="alerts", title=_t(settings, "thread"))
        session.add(conversation)
        await session.flush()
    return conversation


async def deliver_in_app(session: AsyncSession, settings: Settings, n: Notification) -> None:
    text = render(settings, n)
    for user in await recipients(session, settings):
        conversation = await alerts_conversation(session, settings, user.id)
        session.add(
            ConversationMessage(
                conversation_id=conversation.id,
                role="assistant",
                content=text,
                status="complete",
                alert_kind=n.kind,
                completed_at=utcnow(),
            )
        )
        conversation.updated_at = utcnow()
    await session.flush()


async def unread_count(session: AsyncSession, conversation: Conversation) -> int:
    count = await session.scalar(
        select(func.count()).where(
            ConversationMessage.conversation_id == conversation.id,
            ConversationMessage.alert_kind.isnot(None),
            ConversationMessage.id > (conversation.last_read_message_id or 0),
        )
    )
    return int(count or 0)
