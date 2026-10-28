import uuid

import pytest

from agent_hq.api.events import EventBroadcaster, event_stream
from agent_hq.domain import TaskStatus
from agent_hq.events import record_task_event
from agent_hq.models import Project, Task, User
from tests.conftest import Harness, requires_db

pytestmark = [pytest.mark.anyio, requires_db]


async def _seed_events(h: Harness) -> tuple[uuid.UUID, uuid.UUID]:
    async with h.app.state.sessionmaker() as session:
        user = User(email="u@example.test", display_name="u", password_hash="x")
        session.add(user)
        await session.flush()
        project = Project(key="p", name="P", owner_id=user.id)
        session.add(project)
        await session.flush()
        tasks = []
        for title in ("a", "b"):
            task = Task(
                project_id=project.id,
                title=title,
                request="r",
                status=TaskStatus.DRAFT,
                created_by=user.id,
            )
            session.add(task)
            await session.flush()
            tasks.append(task)
        for i in range(3):
            for task in tasks:
                await record_task_event(
                    session,
                    task_id=task.id,
                    project_id=project.id,
                    type="step",
                    payload={"i": i},
                )
        await session.commit()
        return tasks[0].id, tasks[1].id


async def test_stream_replays_after_last_event_id_and_filters(harness: Harness) -> None:
    first, _ = await _seed_events(harness)
    disconnected = {"value": False}

    async def is_disconnected() -> bool:
        return disconnected["value"]

    chunks = []
    stream = event_stream(
        harness.app.state.sessionmaker,
        EventBroadcaster("unused"),
        after_id=1,
        project_id=None,
        task_id=first,
        is_disconnected=is_disconnected,
        keepalive=0.01,
    )
    async for chunk in stream:
        chunks.append(chunk)
        if chunk.startswith(": keepalive"):
            disconnected["value"] = True
    ids = [int(c.split("\n")[0][4:]) for c in chunks if c.startswith("id: ")]
    # Event 1 was already seen; events of the other task are filtered out.
    assert ids == [3, 5]
    assert chunks[0].startswith("retry:")
