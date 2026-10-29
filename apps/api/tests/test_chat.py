"""Chat with Dixon (ADR-0015): grounded answers, proposals, scope and failure handling."""

import uuid
from typing import Any

import pytest
from sqlalchemy import func, select

from agent_hq.domain import JobStatus
from agent_hq.llm.base import ModelConfigError, ModelRequest, ModelResponse, ToolCall, Usage
from agent_hq.models import AuditEvent, Job, KnowledgeDocument, Task
from tests.conftest import Harness, requires_db

pytestmark = [pytest.mark.anyio, requires_db]


async def _conversation(h: Harness, project_id: str | None = None) -> str:
    r = await h.client.post("/conversations", json={"project_id": project_id})
    assert r.status_code == 201, r.text
    conversation_id: str = r.json()["id"]
    return conversation_id


async def _say(h: Harness, conversation_id: str, text: str) -> dict[str, Any]:
    r = await h.client.post(f"/conversations/{conversation_id}/messages", json={"content": text})
    assert r.status_code == 202, r.text
    assert r.json()["messages"][-1]["status"] == "pending"
    await h.run_worker()
    r = await h.client.get(f"/conversations/{conversation_id}")
    assert r.status_code == 200, r.text
    reply: dict[str, Any] = r.json()["messages"][-1]
    assert reply["role"] == "assistant"
    return reply


async def _count(h: Harness, model: Any, *where: Any) -> int:
    async with h.app.state.sessionmaker() as session:
        return int(await session.scalar(select(func.count()).select_from(model).where(*where)) or 0)


async def test_chat_answers_from_real_tasks(harness: Harness) -> None:
    await harness.login()
    project_id = await harness.create_project_with_repos(["acme/shop"])
    await harness.create_task(project_id, "Review CI/CD of acme/shop")
    conversation_id = await _conversation(harness)

    reply = await _say(harness, conversation_id, "¿Qué tareas hay y cómo está el equipo?")

    assert reply["status"] == "complete"
    assert "CI/CD review — DRAFT" in reply["content"]  # the real task, with its real status
    assert "DevOps Engineer" in reply["content"]
    assert [c["name"] for c in reply["tool_calls"]] == ["chat.team", "chat.list_tasks"]
    assert reply["model_provider"] == "mock" and reply["model_name"] == "mock-fast"
    assert reply["tokens_in"] > 0
    r = await harness.client.get("/conversations")
    assert r.json()[0]["title"] == "¿Qué tareas hay y cómo está el equipo?"


async def test_proposal_becomes_a_task_only_after_owner_confirmation(harness: Harness) -> None:
    await harness.login()
    project_id = await harness.create_project_with_repos(["acme/shop"])
    conversation_id = await _conversation(harness, project_id)

    reply = await _say(harness, conversation_id, "Revisa el CI/CD de acme/shop")

    [proposal] = reply["proposals"]
    assert proposal["status"] == "proposed" and proposal["project_key"] == "shop"
    assert "confírmala" in reply["content"]
    assert await _count(harness, Task) == 0  # nothing is created by the model

    url = (
        f"/conversations/{conversation_id}/messages/{reply['id']}/proposals/{proposal['id']}/accept"
    )
    r = await harness.client.post(url, json={"start": True})
    assert r.status_code == 200, r.text
    task = r.json()
    assert task["status"] == "QUEUED" and task["request"] == "Revisa el CI/CD de acme/shop"

    # Single use, and the conversation shows the result.
    assert (await harness.client.post(url, json={"start": True})).status_code == 409
    detail = (await harness.client.get(f"/conversations/{conversation_id}")).json()
    assert detail["messages"][-1]["proposals"][0] == {
        **proposal,
        "status": "accepted",
        "task_id": task["id"],
    }
    async with harness.app.state.sessionmaker() as session:
        audit = await session.scalar(select(AuditEvent).where(AuditEvent.action == "task.created"))
    assert audit is not None and audit.details["source"] == "chat"

    # The task runs through the normal workflow.
    await harness.run_worker()
    assert (await harness.task(task["id"]))["status"] == "WAITING_APPROVAL"


async def test_chat_scope_and_tool_policy_are_enforced_in_code(harness: Harness) -> None:
    await harness.login()
    project_a = await harness.create_project_with_repos(["acme/shop"], key="client-a")
    project_b = await harness.create_project_with_repos(["acme/other"], key="client-b")
    task_b = await harness.create_task(project_b, "Client B work")
    async with harness.app.state.sessionmaker() as session:
        session.add(
            KnowledgeDocument(
                scope="project",
                project_id=uuid.UUID(project_b),
                kind="note",
                title="Client B secret plan",
                content="Client B roadmap details",
                trust="approved",
                created_by_agent="devops",
            )
        )
        await session.commit()

    seen: list[str] = []

    def script(request: ModelRequest) -> ModelResponse | None:
        if request.purpose != "cio.chat":
            return None
        tool_messages = [m for m in request.messages if m.role == "tool"]
        if tool_messages:
            seen.extend(m.content for m in tool_messages)
            return ModelResponse("I checked.", [], None, Usage(10, 5))
        calls = [
            ToolCall("1", "chat.get_task", {"task_id": task_b}),
            ToolCall(
                "2",
                "chat.propose_task",
                {
                    "project_key": "client-b",
                    "title": "Work for B",
                    "request": "Do something for client B",
                },
            ),
            ToolCall("3", "tasks.start", {"task_id": task_b}),
            ToolCall("4", "approvals.decide", {"approve": True}),
            ToolCall("5", "chat.search_knowledge", {"query": "Client B roadmap"}),
        ]
        return ModelResponse("", calls, None, Usage(10, 5))

    harness.use_script(script)
    conversation_id = await _conversation(harness, project_a)
    reply = await _say(harness, conversation_id, "Show me everything about client B")

    outcomes = {c["name"]: c for c in reply["tool_calls"]}
    assert outcomes["chat.get_task"]["denied"]
    assert outcomes["chat.propose_task"]["denied"]
    assert outcomes["tasks.start"]["denied"] and "unknown tool" in outcomes["tasks.start"]["error"]
    assert outcomes["approvals.decide"]["denied"]
    assert outcomes["chat.search_knowledge"]["ok"]
    assert not any("Client B secret plan" in text for text in seen)
    assert reply["proposals"] == []
    assert await _count(harness, AuditEvent, AuditEvent.action == "chat.tool_denied") == 4
    assert (await harness.task(task_b))["status"] == "DRAFT"

    # Company-wide chats never see project knowledge either.
    harness.use_script(lambda r: None)
    company = await _conversation(harness)
    reply = await _say(harness, company, "¿Qué sabes de Client B roadmap en The Brain?")
    assert "Client B secret plan" not in reply["content"]
    assert reply["tool_calls"][0]["name"] == "chat.search_knowledge"


async def test_one_pending_reply_ownership_and_redaction(harness: Harness) -> None:
    await harness.login()
    conversation_id = await _conversation(harness)
    url = f"/conversations/{conversation_id}/messages"
    secret = "sk-proj-" + "a" * 32
    r = await harness.client.post(url, json={"content": f"my key is {secret}"})
    assert r.status_code == 202
    assert secret not in r.json()["messages"][0]["content"]
    # A second message while Dixon is answering is refused.
    assert (await harness.client.post(url, json={"content": "hello?"})).status_code == 409
    assert (await harness.client.get(f"/conversations/{uuid.uuid4()}")).status_code == 404
    # A conversation for a missing project cannot be created.
    r = await harness.client.post("/conversations", json={"project_id": str(uuid.uuid4())})
    assert r.status_code == 404
    # Sending requires the CSRF token like every other write.
    del harness.client.headers["X-CSRF-Token"]
    assert (await harness.client.post(url, json={"content": "hi"})).status_code == 403


async def test_model_configuration_errors_fail_the_reply_without_retry(harness: Harness) -> None:
    await harness.login()

    def script(request: ModelRequest) -> ModelResponse | None:
        raise ModelConfigError("OpenAI account cannot serve requests (insufficient_quota)")

    harness.use_script(script)
    conversation_id = await _conversation(harness)
    reply = await _say(harness, conversation_id, "hola")

    assert reply["status"] == "failed"
    assert "insufficient_quota" in reply["error"]
    async with harness.app.state.sessionmaker() as session:
        job = await session.scalar(select(Job))
    assert job is not None and job.status == JobStatus.FAILED and job.attempts == 1
    # After a failed reply the owner can send again.
    harness.use_script(lambda r: None)
    assert (await _say(harness, conversation_id, "hola de nuevo"))["status"] == "complete"
