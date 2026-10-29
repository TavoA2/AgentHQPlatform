"""Chat with Dixon (ADR-0015). Every endpoint is scoped to the signed-in user."""

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from agent_hq.agents import CIO
from agent_hq.api.deps import DbDep, PrincipalDep, SettingsDep
from agent_hq.api.schemas import (
    AcceptProposalIn,
    ChatMessageIn,
    ChatMessageOut,
    ConversationDetailOut,
    ConversationIn,
    ConversationOut,
    TaskOut,
)
from agent_hq.chat import DEFAULT_TITLE, ChatError, accept_proposal, post_message
from agent_hq.models import Conversation, ConversationMessage, Project
from agent_hq.security.auth import Principal

router = APIRouter(prefix="/conversations", tags=["chat"])


async def _conversation(
    db: DbDep, principal: Principal, conversation_id: uuid.UUID
) -> Conversation:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != principal.user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    return conversation


async def _detail(db: DbDep, conversation: Conversation) -> ConversationDetailOut:
    messages = await db.scalars(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation.id)
        .order_by(ConversationMessage.id)
    )
    return ConversationDetailOut(
        **ConversationOut.model_validate(conversation).model_dump(),
        messages=[ChatMessageOut.model_validate(m) for m in messages],
    )


@router.get("")
async def list_conversations(
    principal: PrincipalDep, db: DbDep, limit: Annotated[int, Query(ge=1, le=100)] = 30
) -> list[ConversationOut]:
    rows = await db.scalars(
        select(Conversation)
        .where(Conversation.user_id == principal.user.id)
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
    )
    return [ConversationOut.model_validate(c) for c in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: ConversationIn, principal: PrincipalDep, db: DbDep
) -> ConversationOut:
    if body.project_id is not None:
        project = await db.get(Project, body.project_id)
        if project is None or project.status != "active":
            raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    conversation = Conversation(
        user_id=principal.user.id, project_id=body.project_id, title=body.title or DEFAULT_TITLE
    )
    db.add(conversation)
    await db.commit()
    return ConversationOut.model_validate(conversation)


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: uuid.UUID, principal: PrincipalDep, db: DbDep
) -> ConversationDetailOut:
    return await _detail(db, await _conversation(db, principal, conversation_id))


@router.post("/{conversation_id}/messages", status_code=status.HTTP_202_ACCEPTED)
async def send_message(
    conversation_id: uuid.UUID,
    body: ChatMessageIn,
    principal: PrincipalDep,
    db: DbDep,
    settings: SettingsDep,
) -> ConversationDetailOut:
    """Stores the message; Dixon's reply arrives as a pending message completed by the worker."""
    conversation = await _conversation(db, principal, conversation_id)
    try:
        await post_message(db, conversation, body.content, max_attempts=settings.job_max_attempts)
    except ChatError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await db.commit()
    return await _detail(db, conversation)


@router.post("/{conversation_id}/messages/{message_id}/proposals/{proposal_id}/accept")
async def accept(
    conversation_id: uuid.UUID,
    message_id: int,
    proposal_id: uuid.UUID,
    body: AcceptProposalIn,
    principal: PrincipalDep,
    db: DbDep,
    settings: SettingsDep,
) -> TaskOut:
    """The owner's confirmation is the only way a chat proposal becomes a task."""
    conversation = await _conversation(db, principal, conversation_id)
    try:
        task = await accept_proposal(
            db,
            conversation,
            message_id=message_id,
            proposal_id=str(proposal_id),
            user_id=principal.user.id,
            start=body.start,
            max_attempts=settings.job_max_attempts,
        )
    except ChatError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await db.commit()
    out = TaskOut.model_validate(task)
    out.assigned_agent_key = CIO.key
    return out
