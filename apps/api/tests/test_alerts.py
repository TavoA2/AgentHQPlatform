"""Proactive alerts from Dixon (ADR-0016): in-app channel, reminders, daily briefing."""

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select, update

from agent_hq import alerts
from agent_hq.models import ApprovalRequest, Notification, utcnow
from agent_hq.notifications import Notifier
from tests.conftest import Harness, requires_db

pytestmark = [pytest.mark.anyio, requires_db]


async def _waiting_task(h: Harness) -> str:
    await h.login()
    project = await h.create_project_with_repos(["acme/shop"])
    task_id = await h.create_task(project, "Review the CI pipeline of acme/shop.")
    assert (await h.client.post(f"/tasks/{task_id}/start")).status_code == 200
    await h.run_worker()
    assert (await h.task(task_id))["status"] == "WAITING_APPROVAL"
    return task_id


async def _alert_messages(h: Harness) -> list[dict[str, Any]]:
    status = (await h.client.get("/conversations/alerts")).json()
    detail = (await h.client.get(f"/conversations/{status['conversation_id']}")).json()
    assert detail["kind"] == "alerts"
    return [m for m in detail["messages"] if m["alert_kind"]]


async def test_milestones_reach_the_alerts_thread_and_read_state(harness: Harness) -> None:
    task_id = await _waiting_task(harness)

    status = (await harness.client.get("/conversations/alerts")).json()
    assert status["unread"] == 1
    [alert] = await _alert_messages(harness)
    assert alert["alert_kind"] == "approval_requested" and alert["role"] == "assistant"
    assert alert["content"] == f"Approval needed: CI/CD review\n/tasks/{task_id}"
    assert alert["tokens_in"] == 0  # written by code, not by a model

    r = await harness.client.post(f"/conversations/{status['conversation_id']}/read")
    assert r.status_code == 200
    assert (await harness.client.get("/conversations/alerts")).json()["unread"] == 0

    # Approving in the dashboard completes the task; Dixon reports the verified outcome.
    approval = (await harness.task(task_id))["approvals"][0]
    r = await harness.client.post(f"/approvals/{approval['id']}/approve", json={})
    assert r.status_code == 200, r.text
    await harness.run_worker()
    assert (await harness.task(task_id))["status"] == "COMPLETED"
    latest = (await _alert_messages(harness))[-1]
    assert latest["alert_kind"] == "task_completed"
    assert latest["content"].startswith("Task completed: CI/CD review\n")
    assert (await harness.client.get("/conversations/alerts")).json()["unread"] == 1

    # The owner can reply in the thread and Dixon answers with the chat tools.
    r = await harness.client.post(
        f"/conversations/{status['conversation_id']}/messages",
        json={"content": "What tasks are there?"},
    )
    assert r.status_code == 202
    await harness.run_worker()
    reply = (await harness.client.get(f"/conversations/{status['conversation_id']}")).json()
    assert reply["messages"][-1]["status"] == "complete"
    assert "CI/CD review — COMPLETED" in reply["messages"][-1]["content"]


async def test_approval_reminder_is_sent_once(harness: Harness) -> None:
    task_id = await _waiting_task(harness)
    settings = harness.settings.model_copy(update={"alert_approval_reminder_hours": 4})
    async with harness.app.state.sessionmaker() as session:
        now = utcnow()
        assert await alerts.schedule_approval_reminders(session, settings, now) == 0  # too early
        await session.execute(
            update(ApprovalRequest).values(
                created_at=ApprovalRequest.created_at - timedelta(hours=5)
            )
        )
        assert await alerts.schedule_approval_reminders(session, settings, now) == 1
        assert await alerts.schedule_approval_reminders(session, settings, now) == 0  # once
        await session.commit()

    await harness.worker.deliver_notifications()
    latest = (await _alert_messages(harness))[-1]
    assert latest["alert_kind"] == "approval_reminder"
    assert latest["content"] == (
        f"Still waiting for your approval: CI/CD review\nWaiting 5 h; expires in 23 h.\n"
        f"/tasks/{task_id}"
    )


async def test_daily_brief_is_built_from_facts_once_per_day(harness: Harness) -> None:
    settings = harness.settings.model_copy(
        update={"alert_daily_brief_hour_utc": 0, "alert_language": "es"}
    )
    async with harness.app.state.sessionmaker() as session:
        # Nothing happened: the day is decided as quiet, once.
        assert not await alerts.schedule_daily_brief(session, settings, utcnow())
        assert not await alerts.schedule_daily_brief(session, settings, utcnow())
        rows = list(await session.scalars(select(Notification)))
        assert [(r.kind, r.status) for r in rows] == [("daily_brief", "skipped")]
        await session.rollback()

    task_id = await _waiting_task(harness)
    async with harness.app.state.sessionmaker() as session:
        early = utcnow().replace(hour=0, minute=0)
        late_settings = settings.model_copy(update={"alert_daily_brief_hour_utc": 23})
        if early.hour < 23:
            assert not await alerts.schedule_daily_brief(session, late_settings, early)
        assert await alerts.schedule_daily_brief(session, settings, utcnow())
        assert not await alerts.schedule_daily_brief(session, settings, utcnow())
        await session.commit()

    harness.worker.notifier = Notifier(settings)  # one language for the whole instance
    await harness.worker.deliver_notifications()
    brief = (await _alert_messages(harness))[-1]
    assert brief["alert_kind"] == "daily_brief"
    lines = brief["content"].splitlines()
    assert lines[0].startswith("Resumen diario: ")
    assert "Esperan tu aprobación: 1 (la más antigua, 0 h) → /approvals" in lines
    assert any(line.startswith("Uso de modelos en las últimas 24 h: ") for line in lines)
    assert f"/tasks/{task_id}" not in brief["content"]  # nothing completed or failed yet
    # Alerts are never actionable: still exactly one pending approval, undecided.
    async with harness.app.state.sessionmaker() as session:
        statuses = list(await session.scalars(select(ApprovalRequest.status)))
    assert [s.value for s in statuses] == ["pending"]
