import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from agent_hq.api.deps import DbDep, PrincipalDep, SettingsDep
from agent_hq.api.schemas import ApprovalOut, DecisionIn, approval_out
from agent_hq.domain import ApprovalStatus, JobKind
from agent_hq.jobs import enqueue
from agent_hq.models import Agent, ApprovalRequest
from agent_hq.security.approvals import ApprovalError, decide

router = APIRouter(prefix="/approvals", tags=["approvals"])


async def _keys(db: DbDep) -> dict[uuid.UUID, str]:
    return {a.id: a.key for a in await db.scalars(select(Agent))}


@router.get("")
async def list_approvals(
    _: PrincipalDep,
    db: DbDep,
    status_: Annotated[ApprovalStatus | None, Query(alias="status")] = None,
    project_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ApprovalOut]:
    query = select(ApprovalRequest).order_by(ApprovalRequest.created_at.desc()).limit(limit)
    if status_:
        query = query.where(ApprovalRequest.status == status_)
    if project_id:
        query = query.where(ApprovalRequest.project_id == project_id)
    keys = await _keys(db)
    return [approval_out(a, keys) for a in await db.scalars(query)]


@router.get("/{approval_id}")
async def get_approval(approval_id: uuid.UUID, _: PrincipalDep, db: DbDep) -> ApprovalOut:
    approval = await db.get(ApprovalRequest, approval_id)
    if approval is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "approval not found")
    return approval_out(approval, await _keys(db))


async def _decide(
    approval_id: uuid.UUID,
    body: DecisionIn,
    principal: PrincipalDep,
    db: DbDep,
    max_attempts: int,
    *,
    approve: bool,
) -> ApprovalOut:
    try:
        approval = await decide(
            db, approval_id=approval_id, user=principal.user, approve=approve, note=body.note
        )
    except ApprovalError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    # The worker resumes the paused workflow, which re-reads the decision from the database.
    await enqueue(
        db,
        kind=JobKind.RESUME,
        task_id=approval.task_id,
        payload={"approval_id": str(approval.id)},
        max_attempts=max_attempts,
    )
    await db.commit()
    return approval_out(approval, await _keys(db))


@router.post("/{approval_id}/approve")
async def approve(
    approval_id: uuid.UUID,
    body: DecisionIn,
    principal: PrincipalDep,
    db: DbDep,
    settings: SettingsDep,
) -> ApprovalOut:
    return await _decide(approval_id, body, principal, db, settings.job_max_attempts, approve=True)


@router.post("/{approval_id}/reject")
async def reject(
    approval_id: uuid.UUID,
    body: DecisionIn,
    principal: PrincipalDep,
    db: DbDep,
    settings: SettingsDep,
) -> ApprovalOut:
    return await _decide(approval_id, body, principal, db, settings.job_max_attempts, approve=False)
