"""Report publication. Sprint 1 ships only a mock adapter: no external effect."""

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


class MockReportPublisher:
    """Records the "publication" in the audit log so tests can count executions."""

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
