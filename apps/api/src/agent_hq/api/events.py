"""Server-Sent Events backed by task_events + LISTEN/NOTIFY (ADR-0004)."""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated

import psycopg
from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_hq.api.deps import PrincipalDep
from agent_hq.api.schemas import EventOut
from agent_hq.events import NOTIFY_CHANNEL
from agent_hq.models import TaskEvent

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/events", tags=["events"])

KEEPALIVE_SECONDS = 15.0
BATCH = 200


class EventBroadcaster:
    """Holds one LISTEN connection and wakes up subscribers when new events are committed.

    Subscribers always read from the table (id > last seen), so replay after reconnect and
    live delivery share one code path and nothing is lost if a notification is missed.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._version = 0
        self._changed = asyncio.Condition()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="event-broadcaster")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def _run(self) -> None:
        backoff = 1.0
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(
                    self._dsn, autocommit=True, connect_timeout=5
                ) as conn:
                    await conn.execute(f"LISTEN {NOTIFY_CHANNEL}")
                    backoff = 1.0
                    async for _ in conn.notifies():
                        await self.notify()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("event listener disconnected; retrying", exc_info=True)
                await self.notify()  # let subscribers poll while disconnected
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def notify(self) -> None:
        async with self._changed:
            self._version += 1
            self._changed.notify_all()

    async def wait(self, seconds: float) -> None:
        async with self._changed:
            seen = self._version
            try:
                await asyncio.wait_for(
                    self._changed.wait_for(lambda: self._version != seen), seconds
                )
            except TimeoutError:
                pass


async def fetch_events(
    session: AsyncSession,
    *,
    after_id: int,
    project_id: uuid.UUID | None,
    task_id: uuid.UUID | None,
) -> list[TaskEvent]:
    query = select(TaskEvent).where(TaskEvent.id > after_id).order_by(TaskEvent.id).limit(BATCH)
    if project_id:
        query = query.where(TaskEvent.project_id == project_id)
    if task_id:
        query = query.where(TaskEvent.task_id == task_id)
    return list(await session.scalars(query))


def format_sse(event: TaskEvent) -> str:
    data = EventOut.model_validate(event).model_dump_json()
    return f"id: {event.id}\nevent: task_event\ndata: {data}\n\n"


async def event_stream(
    sessionmaker: async_sessionmaker[AsyncSession],
    broadcaster: EventBroadcaster,
    *,
    after_id: int,
    project_id: uuid.UUID | None,
    task_id: uuid.UUID | None,
    is_disconnected: Callable[[], Awaitable[bool]],
    keepalive: float = KEEPALIVE_SECONDS,
) -> AsyncIterator[str]:
    last_id = after_id
    yield f"retry: 3000\ndata: {json.dumps({'type': 'connected'})}\n\n"
    while not await is_disconnected():
        async with sessionmaker() as session:
            events = await fetch_events(
                session, after_id=last_id, project_id=project_id, task_id=task_id
            )
        for event in events:
            last_id = event.id
            yield format_sse(event)
        if len(events) < BATCH:
            await broadcaster.wait(keepalive)
            yield ": keepalive\n\n"


@router.get("/stream")
async def stream(
    request: Request,
    _: PrincipalDep,
    project_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    after: Annotated[int | None, Query(ge=0)] = None,
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    """Replays events after `Last-Event-ID` (or `after`), then streams live ones.

    Without either, only new events are streamed.
    """
    sessionmaker = request.app.state.sessionmaker
    if last_event_id and last_event_id.isdigit():
        start = int(last_event_id)
    elif after is not None:
        start = after
    else:
        async with sessionmaker() as session:
            start = await session.scalar(select(TaskEvent.id).order_by(TaskEvent.id.desc())) or 0
    return StreamingResponse(
        event_stream(
            sessionmaker,
            request.app.state.broadcaster,
            after_id=start,
            project_id=project_id,
            task_id=task_id,
            is_disconnected=request.is_disconnected,
        ),
        media_type="text/event-stream",
        # no-transform stops proxies (including the Next.js gzip layer) from buffering.
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
