"""Outbound notifications through a transactional outbox (ADR-0013).

Rows are written in the same transaction as the task transition that causes them, and the
worker delivers them with retries. Messages carry a title, a status and a dashboard link
only; nothing can be approved from a chat message.
"""

import logging
from datetime import timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_hq.config import Settings
from agent_hq.domain import TaskStatus
from agent_hq.models import Notification, Task, utcnow

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
NOTIFY_ON: dict[TaskStatus, tuple[str, str]] = {
    TaskStatus.WAITING_APPROVAL: ("approval_requested", "Approval needed"),
    TaskStatus.COMPLETED: ("task_completed", "Task completed"),
    TaskStatus.FAILED: ("task_failed", "Task failed"),
}


async def enqueue_for_transition(session: AsyncSession, task: Task, target: TaskStatus) -> None:
    """Queue a notification for top-level task milestones (not for internal subtasks)."""
    spec = NOTIFY_ON.get(target)
    if spec is None or task.parent_task_id is not None:
        return
    kind, headline = spec
    session.add(
        Notification(
            kind=kind,
            task_id=task.id,
            project_id=task.project_id,
            payload={
                "headline": headline,
                "title": task.title[:120],
                "reason": task.failure_reason if target == TaskStatus.FAILED else None,
            },
        )
    )
    await session.flush()


class Notifier:
    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None):
        self._settings = settings
        self._http = httpx.AsyncClient(timeout=10.0, transport=transport)

    async def aclose(self) -> None:
        await self._http.aclose()

    def channels(self) -> list[str]:
        s = self._settings
        configured = []
        if s.slack_webhook_url and s.slack_webhook_url.get_secret_value():
            configured.append("slack")
        if s.telegram_bot_token and s.telegram_bot_token.get_secret_value() and s.telegram_chat_id:
            configured.append("telegram")
        return configured

    def render(self, n: Notification) -> str:
        p = n.payload
        lines = [f"[{self._settings.brand_name} · Agent HQ] {p.get('headline')}: {p.get('title')}"]
        if p.get("reason"):
            lines.append(f"Reason: {p['reason']}")
        if n.task_id:
            lines.append(f"{self._settings.public_url.rstrip('/')}/tasks/{n.task_id}")
        return "\n".join(lines)

    async def _send(self, channel: str, text: str) -> None:
        s = self._settings
        if channel == "slack" and s.slack_webhook_url:
            url = s.slack_webhook_url.get_secret_value()
            body: dict[str, Any] = {"text": text}
        elif channel == "telegram" and s.telegram_bot_token:
            url = (
                f"https://api.telegram.org/bot{s.telegram_bot_token.get_secret_value()}/sendMessage"
            )
            body = {"chat_id": s.telegram_chat_id, "text": text, "disable_web_page_preview": True}
        else:
            raise RuntimeError(f"{channel}: not configured")
        try:
            response = await self._http.post(url, json=body)
        except httpx.TransportError as exc:
            # Never include the URL: it contains the secret.
            raise RuntimeError(f"{channel}: {type(exc).__name__}") from None
        if response.status_code >= 300:
            raise RuntimeError(f"{channel}: HTTP {response.status_code}")

    async def deliver_due(self, session: AsyncSession, limit: int = 20) -> int:
        rows = list(
            await session.scalars(
                select(Notification)
                .where(Notification.status == "pending", Notification.run_after <= utcnow())
                .order_by(Notification.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        channels = self.channels()
        for n in rows:
            if not channels:
                n.status = "skipped"
                continue
            text = self.render(n)
            delivered = list(n.delivered_channels)
            errors = []
            for channel in channels:
                if channel in delivered:
                    continue  # retries never duplicate a channel that already got it
                try:
                    await self._send(channel, text)
                    delivered.append(channel)
                except RuntimeError as exc:
                    errors.append(str(exc))
            n.delivered_channels = delivered
            if not errors:
                n.status = "sent"
                n.sent_at = utcnow()
                continue
            n.attempts += 1
            n.last_error = "; ".join(errors)[:500]
            if n.attempts >= MAX_ATTEMPTS:
                n.status = "failed"
                logger.warning("notification failed", extra={"notification_id": n.id})
            else:
                n.run_after = utcnow() + timedelta(seconds=min(300, 5 * 2**n.attempts))
        await session.flush()
        return len(rows)
