"""Outbound publication of results. Only mock adapters exist until Sprint 5."""

import uuid
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from agent_hq.events import record_audit


class ReportPublisher(Protocol):
    async def publish(
        self,
        session: AsyncSession,
        *,
        target: str,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        report_sha256: str,
    ) -> dict[str, Any]: ...

    async def propose_changeset(
        self,
        session: AsyncSession,
        *,
        target: str,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        changeset_sha256: str,
    ) -> dict[str, Any]: ...


class MockReportPublisher:
    """Records each "publication" in the audit log so tests can count executions."""

    async def publish(
        self,
        session: AsyncSession,
        *,
        target: str,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        report_sha256: str,
    ) -> dict[str, Any]:
        location = f"{target}/{task_id}"
        await record_audit(
            session,
            actor_type="system",
            actor_id="mock-report-publisher",
            action="report.published",
            project_id=project_id,
            resource_type="task",
            resource_id=task_id,
            details={"location": location, "report_sha256": report_sha256, "mock": True},
        )
        return {"published": True, "location": location, "mock": True}

    async def propose_changeset(
        self,
        session: AsyncSession,
        *,
        target: str,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        changeset_sha256: str,
    ) -> dict[str, Any]:
        location = f"{target}/{task_id}"
        await record_audit(
            session,
            actor_type="system",
            actor_id="mock-report-publisher",
            action="changeset.proposed",
            project_id=project_id,
            resource_type="task",
            resource_id=task_id,
            details={"location": location, "changeset_sha256": changeset_sha256, "mock": True},
        )
        return {"published": True, "location": location, "mock": True}
