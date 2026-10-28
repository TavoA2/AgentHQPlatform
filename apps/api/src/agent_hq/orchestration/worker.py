"""Job runner: claims jobs from PostgreSQL and drives the checkpointed CIO graph."""

import asyncio
import contextlib
import logging
import os
import socket
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.errors import GraphRecursionError
from langgraph.types import Command
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from agent_hq import jobs
from agent_hq.config import Settings
from agent_hq.domain import TERMINAL, DomainError, JobKind, TaskCancelledError
from agent_hq.integrations.github import GitHubClient
from agent_hq.integrations.reports import MockReportPublisher
from agent_hq.llm.base import ModelConfigError
from agent_hq.llm.router import ModelRouter
from agent_hq.models import Job, Task
from agent_hq.orchestration.cio import (
    build_cio_graph,
    cancel_executions,
    fail_task_outside_graph,
    initial_state,
    thread_id,
)
from agent_hq.orchestration.mock_model import default_mock_responder
from agent_hq.runtime import Runtime
from agent_hq.security.approvals import expire_due

logger = logging.getLogger(__name__)

MAINTENANCE_SECONDS = 10.0


def build_runtime(settings: Settings, sessionmaker: Any) -> Runtime:
    return Runtime(
        settings=settings,
        sessionmaker=sessionmaker,
        models=ModelRouter(settings, mock_default=default_mock_responder),
        github=GitHubClient(settings.github_token, base_url=settings.github_api_url),
        publisher=MockReportPublisher(),
    )


@contextlib.asynccontextmanager
async def open_checkpointer(settings: Settings) -> AsyncIterator[AsyncPostgresSaver]:
    pool = AsyncConnectionPool(
        settings.psycopg_dsn,
        min_size=1,
        max_size=max(2, settings.worker_concurrency),
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=False,
    )
    await pool.open()
    try:
        saver = AsyncPostgresSaver(conn=pool)  # type: ignore[arg-type]
        await saver.setup()  # idempotent (ADR-0010)
        yield saver
    finally:
        await pool.close()


class Worker:
    def __init__(self, runtime: Runtime, checkpointer: AsyncPostgresSaver) -> None:
        self.runtime = runtime
        self.graph = build_cio_graph(runtime, checkpointer)
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self._last_maintenance = 0.0

    @property
    def settings(self) -> Settings:
        return self.runtime.settings

    async def run_forever(self, stop: asyncio.Event) -> None:
        slots = asyncio.Semaphore(self.settings.worker_concurrency)
        running: set[asyncio.Task[None]] = set()
        logger.info("worker started", extra={"worker_id": self.worker_id})
        while not stop.is_set():
            await self.maintenance()
            await slots.acquire()
            job = await self.claim()
            if job is None:
                slots.release()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), self.settings.worker_poll_seconds)
                continue

            async def _run(j: Job = job) -> None:
                try:
                    await self.process(j)
                finally:
                    slots.release()

            task = asyncio.create_task(_run())
            running.add(task)
            task.add_done_callback(running.discard)
        await asyncio.gather(*running, return_exceptions=True)

    async def run_until_idle(self, max_jobs: int = 50) -> int:
        """Process jobs sequentially until none is claimable (used by tests and CLI)."""
        processed = 0
        await self.maintenance(force=True)
        while processed < max_jobs:
            job = await self.claim()
            if job is None:
                break
            await self.process(job)
            processed += 1
        return processed

    async def claim(self) -> Job | None:
        async with self.runtime.sessionmaker() as session:
            job = await jobs.claim(
                session, worker_id=self.worker_id, lease_seconds=self.settings.job_lease_seconds
            )
            await session.commit()
            return job

    async def maintenance(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_maintenance < MAINTENANCE_SECONDS:
            return
        self._last_maintenance = now
        async with self.runtime.sessionmaker() as session:
            requeued = await jobs.requeue_expired(session)
            for approval in await expire_due(session):
                await jobs.enqueue(
                    session,
                    kind=JobKind.RESUME,
                    task_id=approval.task_id,
                    payload={"approval_id": str(approval.id)},
                    max_attempts=self.settings.job_max_attempts,
                )
            await session.commit()
        if requeued:
            logger.warning("requeued jobs with expired leases", extra={"job_ids": requeued})

    async def _heartbeat(self, job_id: int) -> None:
        interval = max(1.0, self.settings.job_lease_seconds / 3)
        while True:
            await asyncio.sleep(interval)
            async with self.runtime.sessionmaker() as session:
                await jobs.heartbeat(session, job_id, lease_seconds=self.settings.job_lease_seconds)
                await session.commit()

    async def process(self, job: Job) -> None:
        log = {"job_id": job.id, "task_id": str(job.task_id), "kind": job.kind.value}
        logger.info("job started", extra=log)
        heartbeat = asyncio.create_task(self._heartbeat(job.id))
        try:
            await self._run_graph(job)
        except TaskCancelledError:
            async with self.runtime.sessionmaker() as session:
                await cancel_executions(session, job.task_id)
                await jobs.complete(session, job.id)
                await session.commit()
            logger.info("job stopped: task cancelled", extra=log)
        except GraphRecursionError:
            await self._fail(job, "max_steps_exceeded", "graph recursion limit reached")
        except (DomainError, ModelConfigError) as exc:
            await self._fail(job, type(exc).__name__, str(exc))
        except Exception as exc:
            logger.exception("job failed", extra=log)
            async with self.runtime.sessionmaker() as session:
                requeued = await jobs.fail(session, job.id, error=repr(exc), retry=True)
                if not requeued:
                    await fail_task_outside_graph(
                        session, job.task_id, reason="worker_error", detail=repr(exc)[:500]
                    )
                await session.commit()
        else:
            async with self.runtime.sessionmaker() as session:
                await jobs.complete(session, job.id)
                await session.commit()
            logger.info("job finished", extra=log)
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)

    async def _fail(self, job: Job, reason: str, detail: str) -> None:
        async with self.runtime.sessionmaker() as session:
            await jobs.fail(session, job.id, error=f"{reason}: {detail}", retry=False)
            await fail_task_outside_graph(session, job.task_id, reason=reason, detail=detail)
            await session.commit()

    async def _run_graph(self, job: Job) -> None:
        async with self.runtime.sessionmaker() as session:
            task = await session.get(Task, job.task_id)
        if task is None or task.status in TERMINAL:
            return
        config: Any = {
            "configurable": {"thread_id": thread_id(task.id, task.run_number)},
            "recursion_limit": self.settings.graph_recursion_limit,
        }
        snapshot = await self.graph.aget_state(config)
        graph_input: Any
        if job.kind == JobKind.START:
            # A thread with pending nodes was interrupted by a crash: continue from the
            # last checkpoint instead of starting over.
            graph_input = None if snapshot.next else initial_state(task)
        else:
            if not snapshot.next:
                return  # nothing paused on this thread (e.g. duplicate resume)
            graph_input = Command(resume=job.payload)
        await self.graph.ainvoke(graph_input, config)
