import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from agent_hq.agents import REGISTRY
from agent_hq.api.deps import DbDep, PrincipalDep
from agent_hq.domain import KNOWLEDGE_KINDS, KnowledgeScope, KnowledgeTrust
from agent_hq.knowledge import (
    KnowledgeError,
    create_document,
    human_search,
    set_trust,
    update_document,
)
from agent_hq.models import KnowledgeDocument, KnowledgeDocumentVersion, Project

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class KnowledgeIn(BaseModel):
    scope: KnowledgeScope
    project_id: uuid.UUID | None = None
    kind: str = Field(description=f"One of: {', '.join(KNOWLEDGE_KINDS)}")
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=50_000)
    audience: list[str] = Field(default_factory=list, description="Agent keys; empty = all")
    tags: list[str] = Field(default_factory=list, max_length=20)
    note: str | None = Field(default=None, max_length=1000)


class KnowledgeUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=50_000)
    audience: list[str] | None = None
    tags: list[str] | None = Field(default=None, max_length=20)
    note: str | None = Field(default=None, max_length=1000)


class ReviewIn(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class KnowledgeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    scope: KnowledgeScope
    project_id: uuid.UUID | None
    kind: str
    title: str
    content: str
    trust: KnowledgeTrust
    audience: list[str]
    tags: list[str]
    version: int
    created_by_user_id: uuid.UUID | None
    created_by_agent: str | None
    source_task_id: uuid.UUID | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class KnowledgeHitOut(KnowledgeOut):
    rank: float
    snippet: str


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int
    title: str
    content: str
    trust: KnowledgeTrust
    changed_by_user_id: uuid.UUID | None
    changed_by_agent: str | None
    source_task_id: uuid.UUID | None
    note: str | None
    created_at: datetime


class KnowledgeDetailOut(KnowledgeOut):
    versions: list[VersionOut]


def _check_audience(audience: list[str] | None) -> None:
    unknown = sorted(set(audience or []) - set(REGISTRY))
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"unknown agents: {unknown}")


async def _get(db: DbDep, doc_id: uuid.UUID) -> KnowledgeDocument:
    doc = await db.get(KnowledgeDocument, doc_id, with_for_update=True)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "knowledge document not found")
    return doc


@router.get("")
async def search(
    _: PrincipalDep,
    db: DbDep,
    q: str | None = None,
    scope: KnowledgeScope | None = None,
    project_id: uuid.UUID | None = None,
    trust: KnowledgeTrust | None = None,
    kind: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[KnowledgeHitOut]:
    hits = await human_search(
        db, text=q, scope=scope, project_id=project_id, trust=trust, kind=kind, limit=limit
    )
    return [
        KnowledgeHitOut(
            **KnowledgeOut.model_validate(h.document).model_dump(), rank=h.rank, snippet=h.snippet
        )
        for h in hits
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create(body: KnowledgeIn, principal: PrincipalDep, db: DbDep) -> KnowledgeOut:
    _check_audience(body.audience)
    if body.project_id and await db.get(Project, body.project_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    try:
        doc = await create_document(
            db,
            scope=body.scope,
            project_id=body.project_id,
            kind=body.kind,
            title=body.title,
            content=body.content,
            user_id=principal.user.id,
            audience=body.audience,
            tags=body.tags,
            note=body.note,
        )
    except KnowledgeError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await db.commit()
    return KnowledgeOut.model_validate(doc)


@router.get("/{doc_id}")
async def detail(doc_id: uuid.UUID, _: PrincipalDep, db: DbDep) -> KnowledgeDetailOut:
    doc = await db.get(KnowledgeDocument, doc_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "knowledge document not found")
    versions = await db.scalars(
        select(KnowledgeDocumentVersion)
        .where(KnowledgeDocumentVersion.document_id == doc.id)
        .order_by(KnowledgeDocumentVersion.version.desc())
    )
    return KnowledgeDetailOut(
        **KnowledgeOut.model_validate(doc).model_dump(),
        versions=[VersionOut.model_validate(v) for v in versions],
    )


@router.put("/{doc_id}")
async def update(
    doc_id: uuid.UUID, body: KnowledgeUpdate, principal: PrincipalDep, db: DbDep
) -> KnowledgeOut:
    _check_audience(body.audience)
    doc = await _get(db, doc_id)
    try:
        await update_document(
            db,
            doc,
            user_id=principal.user.id,
            title=body.title,
            content=body.content,
            audience=body.audience,
            tags=body.tags,
            note=body.note,
        )
    except KnowledgeError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await db.commit()
    return KnowledgeOut.model_validate(doc)


async def _review(
    doc_id: uuid.UUID, body: ReviewIn, principal: PrincipalDep, db: DbDep, trust: KnowledgeTrust
) -> KnowledgeOut:
    doc = await _get(db, doc_id)
    await set_trust(db, doc, trust, user_id=principal.user.id, note=body.note)
    await db.commit()
    return KnowledgeOut.model_validate(doc)


@router.post("/{doc_id}/approve")
async def approve(
    doc_id: uuid.UUID, body: ReviewIn, principal: PrincipalDep, db: DbDep
) -> KnowledgeOut:
    return await _review(doc_id, body, principal, db, KnowledgeTrust.APPROVED)


@router.post("/{doc_id}/reject")
async def reject(
    doc_id: uuid.UUID, body: ReviewIn, principal: PrincipalDep, db: DbDep
) -> KnowledgeOut:
    return await _review(doc_id, body, principal, db, KnowledgeTrust.REJECTED)


@router.post("/{doc_id}/archive")
async def archive(
    doc_id: uuid.UUID, body: ReviewIn, principal: PrincipalDep, db: DbDep
) -> KnowledgeOut:
    return await _review(doc_id, body, principal, db, KnowledgeTrust.ARCHIVED)
