"""The Brain (ADR-0012): scoping, trust, provenance, versioning and agent access."""

import uuid
from typing import Any

import pytest
from sqlalchemy import func, select, text

from agent_hq.domain import ExecutionStatus
from agent_hq.llm.base import ModelRequest, ModelResponse, ToolCall, Usage
from agent_hq.models import Agent, AuditEvent, KnowledgeDocument, TaskExecution
from agent_hq.tools import ToolContext, execute_tool
from tests.conftest import Harness, requires_db

pytestmark = [pytest.mark.anyio, requires_db]


async def _doc(h: Harness, **body: Any) -> dict[str, Any]:
    payload = {"kind": "note", "scope": "company", **body}
    r = await h.client.post("/knowledge", json=payload)
    assert r.status_code == 201, r.text
    data: dict[str, Any] = r.json()
    return data


async def _projects(h: Harness) -> tuple[str, str]:
    await h.login()
    a = await h.create_project_with_repos(["acme/shop"], key="client-a")
    b = await h.create_project_with_repos(["acme/other"], key="client-b")
    return a, b


async def _ctx(h: Harness, project_id: str, agent: str = "devops") -> ToolContext:
    """A real task + execution, as the worker would have when an agent calls a tool."""
    task_id = uuid.UUID(await h.create_task(project_id, "context task"))
    async with h.app.state.sessionmaker() as session:
        agent_id = await session.scalar(select(Agent.id).where(Agent.key == agent))
        execution = TaskExecution(
            task_id=task_id,
            agent_id=agent_id,
            run_number=1,
            attempt=1,
            status=ExecutionStatus.RUNNING,
            graph_thread_id="test",
        )
        session.add(execution)
        await session.commit()
    return ToolContext(
        runtime=h.runtime,
        task_id=task_id,
        project_id=uuid.UUID(project_id),
        execution_id=execution.id,
        agent_key=agent,
        allowed_repos=frozenset(),
    )


async def test_human_documents_are_approved_versioned_and_audited(harness: Harness) -> None:
    await harness.login()
    doc = await _doc(
        harness, title="Servicios", content="Ofrecemos DevOps y automatización con IA."
    )
    assert doc["trust"] == "approved" and doc["version"] == 1
    r = await harness.client.put(
        f"/knowledge/{doc['id']}",
        json={"title": "Servicios", "content": "Ofrecemos DevOps, IA y soporte.", "note": "v2"},
    )
    assert r.json()["version"] == 2
    detail = (await harness.client.get(f"/knowledge/{doc['id']}")).json()
    assert [v["version"] for v in detail["versions"]] == [2, 1]
    assert detail["versions"][1]["content"] == "Ofrecemos DevOps y automatización con IA."
    async with harness.app.state.sessionmaker() as session:
        actions = set(
            await session.scalars(
                select(AuditEvent.action).where(AuditEvent.action.like("knowledge.%"))
            )
        )
        assert actions == {"knowledge.created", "knowledge.updated"}
        with pytest.raises(Exception, match="append-only"):
            await session.execute(text("UPDATE knowledge_document_versions SET content = 'x'"))


async def test_credentials_are_refused(harness: Harness) -> None:
    await harness.login()
    r = await harness.client.post(
        "/knowledge",
        json={
            "scope": "company",
            "kind": "note",
            "title": "token",
            "content": "use ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        },
    )
    assert r.status_code == 422
    assert "credentials" in r.json()["detail"]


async def test_scope_rules_are_enforced(harness: Harness) -> None:
    a, _ = await _projects(harness)
    bad = await harness.client.post(
        "/knowledge",
        json={"scope": "company", "project_id": a, "kind": "note", "title": "x", "content": "y"},
    )
    assert bad.status_code == 422
    bad = await harness.client.post(
        "/knowledge", json={"scope": "project", "kind": "note", "title": "x", "content": "y"}
    )
    assert bad.status_code == 422
    bad = await harness.client.post(
        "/knowledge",
        json={
            "scope": "company",
            "kind": "note",
            "title": "x",
            "content": "y",
            "audience": ["ceo"],
        },
    )
    assert bad.status_code == 422


async def test_agents_never_see_other_projects(harness: Harness) -> None:
    a, b = await _projects(harness)
    await _doc(harness, title="Pipeline policy", content="All pipelines must pin actions.")
    await _doc(
        harness,
        scope="project",
        project_id=a,
        title="Client A pipeline",
        content="Client A deploys pipeline nightly.",
    )
    await _doc(
        harness,
        scope="project",
        project_id=b,
        title="Client B pipeline",
        content="Client B pipeline secret roadmap.",
    )

    outcome = await execute_tool(await _ctx(harness, a), "knowledge.search", {"query": "pipeline"})
    titles = {r["title"] for r in outcome.output["results"]}  # type: ignore[index]
    assert titles == {"Pipeline policy", "Client A pipeline"}

    # Even an explicit attempt to point the tool at another project is ignored.
    outcome = await execute_tool(
        await _ctx(harness, a), "knowledge.search", {"query": "Client B roadmap", "project_id": b}
    )
    assert all("Client B" not in r["title"] for r in outcome.output["results"])  # type: ignore[index]


async def test_audience_and_trust_filter_agent_reads(harness: Harness) -> None:
    a, _ = await _projects(harness)
    await _doc(
        harness, title="Pricing", content="Hourly pricing table for proposals.", audience=["cio"]
    )
    rejected = await _doc(harness, title="Old pricing", content="Old hourly pricing table.")
    await harness.client.post(f"/knowledge/{rejected['id']}/reject", json={"note": "outdated"})

    as_devops = await execute_tool(
        await _ctx(harness, a, "devops"), "knowledge.search", {"query": "pricing"}
    )
    as_cio = await execute_tool(
        await _ctx(harness, a, "cio"), "knowledge.search", {"query": "pricing"}
    )
    assert as_devops.output["results"] == []  # type: ignore[index]
    assert [r["title"] for r in as_cio.output["results"]] == ["Pricing"]  # type: ignore[index]


async def test_agents_only_propose_unverified_project_knowledge(harness: Harness) -> None:
    a, _ = await _projects(harness)
    ctx = await _ctx(harness, a, "software_engineer")
    ok = await execute_tool(
        ctx,
        "knowledge.propose",
        {"title": "Use pytest", "content": "This project tests with pytest.", "kind": "decision"},
    )
    assert ok.ok and ok.output["trust"] == "unverified"  # type: ignore[index]
    # Agents cannot pick the scope, the trust level, or approve anything.
    sneaky = await execute_tool(
        ctx,
        "knowledge.propose",
        {
            "title": "Company fact",
            "content": "Approved company policy.",
            "scope": "company",
            "trust": "approved",
        },
    )
    assert sneaky.ok
    async with harness.app.state.sessionmaker() as session:
        docs = list(await session.scalars(select(KnowledgeDocument)))
    assert {d.scope.value for d in docs} == {"project"}
    assert {d.trust.value for d in docs} == {"unverified"}
    assert all(d.created_by_agent == "software_engineer" for d in docs)
    denied = await execute_tool(ctx, "knowledge.approve", {"id": str(docs[0].id)})
    assert denied.denied
    leaked = await execute_tool(
        ctx, "knowledge.propose", {"title": "key", "content": "token sk-abcdefghijklmnopqrstuvwxyz"}
    )
    assert leaked.denied and "credentials" in (leaked.error or "")


async def test_human_review_promotes_agent_knowledge(harness: Harness) -> None:
    a, _ = await _projects(harness)
    await execute_tool(
        await _ctx(harness, a, "qa"),
        "knowledge.propose",
        {"title": "Flaky test", "content": "test_checkout is flaky on Mondays.", "kind": "note"},
    )
    pending = (await harness.client.get("/knowledge", params={"trust": "unverified"})).json()
    assert [d["title"] for d in pending] == ["Flaky test"]
    approved = await harness.client.post(f"/knowledge/{pending[0]['id']}/approve", json={})
    assert approved.json()["trust"] == "approved"
    detail = (await harness.client.get(f"/knowledge/{pending[0]['id']}")).json()
    assert [(v["version"], v["trust"]) for v in detail["versions"]] == [
        (2, "approved"),
        (1, "unverified"),
    ]
    assert detail["versions"][1]["changed_by_agent"] == "qa"


async def test_search_ranks_spanish_and_english(harness: Harness) -> None:
    await harness.login()
    await _doc(
        harness,
        title="Política de despliegue",
        content="Los despliegues a producción requieren aprobación.",
    )
    await _doc(
        harness, title="Deployment policy", content="Production deployments require approval."
    )
    await _doc(harness, title="Brand", content="Colors and typography.")
    es = (await harness.client.get("/knowledge", params={"q": "despliegues producción"})).json()
    en = (await harness.client.get("/knowledge", params={"q": "production deployments"})).json()
    assert [d["title"] for d in es] == ["Política de despliegue"]
    assert [d["title"] for d in en] == ["Deployment policy"]
    assert "«" in es[0]["snippet"]


async def test_dixon_uses_knowledge_and_remembers_outcomes(harness: Harness) -> None:
    a, _ = await _projects(harness)
    await _doc(
        harness,
        scope="project",
        project_id=a,
        kind="constraint",
        title="CI constraint",
        content="Client A requires CI pipeline jobs to finish under ten minutes.",
    )
    await _doc(
        harness,
        scope="project",
        project_id=(await harness.create_project_with_repos(["x/y"], key="client-c")),
        title="Other client",
        content="Client C CI pipeline details.",
    )
    task_id = await harness.create_task(a, "Review the CI pipeline of acme/shop.")
    await harness.client.post(f"/tasks/{task_id}/start")
    await harness.run_worker()
    task = await harness.task(task_id)
    approval = task["approvals"][0]
    await harness.client.post(f"/approvals/{approval['id']}/approve", json={})
    await harness.run_worker()
    assert (await harness.task(task_id))["status"] == "COMPLETED"

    analyze = next(
        c for c in harness.runtime.models._providers["mock"].calls if c.purpose == "cio.analyze"
    )
    prompt = analyze.messages[-1].content
    assert "CI constraint" in prompt and '"trust": "approved"' in prompt
    assert "Other client" not in prompt
    assert "<untrusted_tool_output" in prompt

    memory = (await harness.client.get("/knowledge", params={"kind": "execution_summary"})).json()
    assert len(memory) == 1
    assert memory[0]["trust"] == "unverified"
    assert memory[0]["source_task_id"] == task_id
    assert memory[0]["project_id"] == a


async def test_specialists_can_search_knowledge(harness: Harness) -> None:
    a, _ = await _projects(harness)
    await _doc(harness, title="Standards", content="Workflows must declare timeout-minutes.")
    asked = {"done": False}

    def curious(request: ModelRequest) -> ModelResponse | None:
        if request.purpose == "devops.analyze" and not asked["done"]:
            asked["done"] = True
            return ModelResponse(
                "",
                [ToolCall("k", "knowledge.search", {"query": "timeout workflows"})],
                None,
                Usage(1, 1),
            )
        return None

    harness.use_script(curious)
    task_id = await harness.create_task(a, "Review the CI pipeline of acme/shop.")
    await harness.client.post(f"/tasks/{task_id}/start")
    await harness.run_worker()
    assert (await harness.task(task_id))["status"] == "WAITING_APPROVAL"
    async with harness.app.state.sessionmaker() as session:
        denied = await session.scalar(
            select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "tool.denied")
        )
    assert denied == 0


async def test_cio_is_presented_as_dixon(harness: Harness) -> None:
    await harness.login()
    agents = {a["key"]: a for a in (await harness.client.get("/agents")).json()}
    assert agents["cio"]["display_name"] == "Dixon"
