"""Outbound notifications through a transactional outbox (ADR-0013).

Rows are written in the same transaction as the task transition that causes them (or by the
alert scheduler, ADR-0016), and the worker delivers them with retries: in-app as a Dixon
message, plus Slack/Telegram when configured. Messages carry a title, a status and a dashboard link
only; nothing can be approved from a chat message.
"""

import logging
from datetime import timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_hq.alerts import deliver_in_app
from agent_hq.alerts import render as render_alert
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
                "summary": _outcome(task) if target == TaskStatus.COMPLETED else None,
            },
        )
    )
    await session.flush()


def _outcome(task: Task) -> str | None:
    summary = (task.result or {}).get("summary") or {}
    outcome = summary.get("outcome") if isinstance(summary, dict) else None
    return str(outcome)[:400] if outcome else None


class Notifier:
    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None):
        self._settings = settings
        self._http = httpx.AsyncClient(timeout=10.0, transport=transport)

    async def aclose(self) -> None:
        await self._http.aclose()

    def channels(self) -> list[str]:
        """The in-app channel (Dixon's Alerts conversation, ADR-0016) is always on."""
        s = self._settings
        configured = ["app"]
        if s.slack_webhook_url and s.slack_webhook_url.get_secret_value():
            configured.append("slack")
        if s.telegram_bot_token and s.telegram_bot_token.get_secret_value() and s.telegram_chat_id:
            configured.append("telegram")
        return configured

    def render(self, n: Notification) -> str:
        base_url = self._settings.public_url.rstrip("/")
        text = render_alert(self._settings, n, base_url=base_url)
        return f"[{self._settings.brand_name} · Agent HQ] {text}"

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
            text = self.render(n)
            delivered = list(n.delivered_channels)
            errors = []
            for channel in channels:
                if channel in delivered:
                    continue  # retries never duplicate a channel that already got it
                if channel == "app":
                    await deliver_in_app(session, self._settings, n)
                    delivered.append(channel)
                    continue
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
