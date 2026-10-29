"""Chat with Dixon (ADR-0015): conversations, worker-run replies and task proposals."""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_hq.chat_tools import ChatContext, chat_tool_schemas, execute_chat_tool
from agent_hq.domain import DomainError, JobKind
from agent_hq.events import record_audit, to_json
from agent_hq.jobs import enqueue
from agent_hq.llm.base import ChatMessage, ModelRequest
from agent_hq.logging import redact_text
from agent_hq.models import Conversation, ConversationMessage, Project, Task, utcnow
from agent_hq.orchestration.prompts import CIO_CHAT, wrap_untrusted
from agent_hq.runtime import Runtime
from agent_hq.tasks import create_task, start_task

CHAT_AGENT_KEY = "cio_chat"  # model override key; actions are audited as the CIO
DEFAULT_TITLE = "New conversation"
PENDING, COMPLETE, FAILED = "pending", "complete", "failed"


class ChatError(DomainError):
    pass


def scope_description(project: Project | None) -> str:
    if project is None:
        return (
            "Scope: company-wide. You can see every project's tasks and approvals and the "
            "company knowledge, but not project knowledge."
        )
    return (
        f"Scope: project {project.key} ({project.name}). You can only see this project's "
        "tasks, approvals and knowledge, plus company knowledge."
    )


async def post_message(
    session: AsyncSession, conversation: Conversation, content: str, *, max_attempts: int
) -> tuple[ConversationMessage, ConversationMessage]:
    """Store the owner's message and a pending reply, and queue the reply job."""
    # Row lock: two concurrent sends cannot both see "no pending reply".
    await session.refresh(conversation, with_for_update=True)
    busy = await session.scalar(
        select(ConversationMessage.id).where(
            ConversationMessage.conversation_id == conversation.id,
            ConversationMessage.status == PENDING,
        )
    )
    if busy is not None:
        raise ChatError("Dixon is still answering the previous message")
    # Credentials pasted into the chat are never stored or sent to a model.
    text = redact_text(content.strip())
    user_message = ConversationMessage(
        conversation_id=conversation.id, role="user", content=text, status=COMPLETE
    )
    reply = ConversationMessage(conversation_id=conversation.id, role="assistant", status=PENDING)
    session.add_all([user_message, reply])
    await session.flush()
    await enqueue(
        session,
        kind=JobKind.CHAT,
        conversation_id=conversation.id,
        payload={"message_id": reply.id},
        max_attempts=max_attempts,
    )
    if conversation.title == DEFAULT_TITLE:
        conversation.title = text.splitlines()[0][:80] or DEFAULT_TITLE
    conversation.updated_at = utcnow()
    return user_message, reply


async def accept_proposal(
    session: AsyncSession,
    conversation: Conversation,
    *,
    message_id: int,
    proposal_id: str,
    user_id: uuid.UUID,
    start: bool,
    max_attempts: int,
) -> Task:
    """The owner's confirmation turns a proposal into a task; each proposal works once."""
    message = await session.get(
        ConversationMessage, message_id, with_for_update=True, populate_existing=True
    )
    if message is None or message.conversation_id != conversation.id:
        raise ChatError("message not found")
    proposals = [dict(p) for p in message.proposals]
    proposal = next((p for p in proposals if p.get("id") == proposal_id), None)
    if proposal is None:
        raise ChatError("proposal not found")
    if proposal.get("status") != "proposed":
        raise ChatError(f"proposal already {proposal.get('status')}")
    project = await session.get(Project, uuid.UUID(proposal["project_id"]))
    if (
        project is None
        or project.status != "active"
        or conversation.project_id not in (None, project.id)
    ):
        raise ChatError("the proposal's project is not available")
    task = await create_task(
        session,
        project_id=project.id,
        title=proposal["title"],
        request=proposal["request"],
        acceptance_criteria=list(proposal.get("acceptance_criteria") or []),
        created_by=user_id,
        audit_details={
            "source": "chat",
            "conversation_id": str(conversation.id),
            "proposal_id": proposal_id,
        },
    )
    if start:
        await start_task(session, task, actor_id=str(user_id), max_attempts=max_attempts)
    proposal.update(status="accepted", task_id=str(task.id))
    message.proposals = proposals  # reassigned so the JSONB change is persisted
    conversation.updated_at = utcnow()
    return task


async def _history(
    session: AsyncSession, conversation_id: uuid.UUID, before_id: int, limit: int
) -> list[ConversationMessage]:
    rows = await session.scalars(
        select(ConversationMessage)
        .where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.id < before_id,
            ConversationMessage.status == COMPLETE,
        )
        .order_by(ConversationMessage.id.desc())
        .limit(limit)
    )
    return list(reversed(list(rows)))


async def run_turn(runtime: Runtime, message_id: int) -> None:
    """Answer one pending message. Safe to re-run: chat tools have no side effects."""
    settings = runtime.settings
    async with runtime.sessionmaker() as session:
        reply = await session.get(ConversationMessage, message_id)
        if reply is None or reply.status != PENDING:
            return
        conversation = await session.get(Conversation, reply.conversation_id)
        if conversation is None:
            return
        project = (
            await session.get(Project, conversation.project_id) if conversation.project_id else None
        )
        history = await _history(
            session, conversation.id, message_id, settings.chat_history_messages
        )
        scope_projects = list(
            await session.scalars(
                select(Project).where(
                    Project.status == "active",
                    *([Project.id == project.id] if project else []),
                )
            )
        )

    ctx = ChatContext(
        runtime=runtime,
        conversation_id=conversation.id,
        user_id=conversation.user_id,
        project_id=conversation.project_id,
    )
    system = CIO_CHAT.format(brand=settings.brand_name, scope=scope_description(project))
    messages = [ChatMessage("system", system)]
    messages += [
        ChatMessage("user" if m.role == "user" else "assistant", m.content) for m in history
    ]
    resolved = runtime.models.resolve(
        agent_key=CHAT_AGENT_KEY, profile=settings.chat_model_profile, task_override=None
    )
    hints: dict[str, Any] = {
        "projects": [{"key": p.key, "name": p.name} for p in scope_projects],
        "scope_project_key": project.key if project else None,
    }
    tool_log: list[dict[str, Any]] = []
    tokens_in = tokens_out = 0
    cost: Decimal | None = None
    answer: str | None = None
    for _ in range(settings.agent_max_steps):
        response = await resolved.provider.complete(
            ModelRequest(
                purpose="cio.chat",
                model=resolved.model,
                messages=messages,
                tools=chat_tool_schemas(),
                hints=hints,
            )
        )
        tokens_in += response.usage.input_tokens
        tokens_out += response.usage.output_tokens
        call_cost = runtime.models.cost(resolved.model, response.usage)
        if call_cost is not None:
            cost = (cost or Decimal(0)) + call_cost
        if not response.tool_calls:
            answer = response.content.strip()
            break
        messages.append(
            ChatMessage("assistant", response.content, tool_calls=tuple(response.tool_calls))
        )
        for call in response.tool_calls:
            outcome = await execute_chat_tool(ctx, call.name, call.arguments)
            tool_log.append(
                {
                    "name": call.name,
                    "arguments": call.arguments,
                    "ok": outcome.ok,
                    "denied": outcome.denied,
                    "error": outcome.error,
                }
            )
            messages.append(
                ChatMessage(
                    "tool", wrap_untrusted(call.name, outcome.for_model()), tool_call_id=call.id
                )
            )

    async with runtime.sessionmaker() as session:
        reply = await session.get(ConversationMessage, message_id, with_for_update=True)
        if reply is None or reply.status != PENDING:
            return
        reply.tool_calls = to_json(tool_log)
        reply.proposals = to_json(ctx.proposals)
        reply.model_provider = resolved.provider_name
        reply.model_name = resolved.model
        reply.tokens_in, reply.tokens_out, reply.cost_usd = tokens_in, tokens_out, cost
        reply.completed_at = utcnow()
        if answer:
            reply.content = redact_text(answer)
            reply.status = COMPLETE
        else:
            reply.status = FAILED
            reply.error = f"no answer after {settings.agent_max_steps} steps"
        for entry in tool_log:
            if entry["denied"]:
                await record_audit(
                    session,
                    actor_type="agent",
                    actor_id="cio",
                    action="chat.tool_denied",
                    resource_type="conversation",
                    resource_id=conversation.id,
                    details=entry,
                )
        await session.commit()


async def fail_turn(runtime: Runtime, message_id: int, error: str) -> None:
    async with runtime.sessionmaker() as session:
        reply = await session.get(ConversationMessage, message_id, with_for_update=True)
        if reply is not None and reply.status == PENDING:
            reply.status = FAILED
            reply.error = error[:500]
            reply.completed_at = utcnow()
            await session.commit()
