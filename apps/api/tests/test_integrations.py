"""Sprint 5: GitHub App pull requests, notification outbox, public demo mode (ADR-0013)."""

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr
from sqlalchemy import func, select, update

from agent_hq.config import Settings
from agent_hq.integrations.github_app import GitHubAppAuth, GitHubPullRequestPublisher
from agent_hq.main import create_app, init_state
from agent_hq.models import AuditEvent, Notification
from agent_hq.notifications import Notifier
from agent_hq.tools import execute_tool
from tests.conftest import Harness, requires_db
from tests.test_knowledge import _ctx as real_context

pytestmark = [pytest.mark.anyio, requires_db]

REQUEST = "Implement a slugify helper in acme/shop with tests."


def _rsa_pem() -> tuple[str, Any]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return pem, key.public_key()


@dataclass
class FakeGitHubWrites:
    public_key: Any
    app_id: str = "123456"
    calls: list[tuple[str, str, dict[str, Any] | None]] = field(default_factory=list)

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        path = request.url.path
        self.calls.append((request.method, path, body))
        auth = request.headers.get("authorization", "")
        if path.endswith("/installation") or path.startswith("/app/"):
            claims = jwt.decode(auth.removeprefix("Bearer "), self.public_key, algorithms=["RS256"])
            assert claims["iss"] == self.app_id
            if path.endswith("/installation"):
                return httpx.Response(200, json={"id": 42})
            return httpx.Response(
                201, json={"token": "ghs_installation", "expires_at": "2999-01-01T00:00:00Z"}
            )
        assert auth == "Bearer ghs_installation"
        routes: dict[tuple[str, str], tuple[int, dict[str, Any]]] = {
            ("GET", "/repos/acme/shop"): (200, {"default_branch": "main"}),
            ("GET", "/repos/acme/shop/git/ref/heads/main"): (200, {"object": {"sha": "base-sha"}}),
            ("GET", "/repos/acme/shop/git/commits/base-sha"): (200, {"tree": {"sha": "base-tree"}}),
            ("POST", "/repos/acme/shop/git/trees"): (201, {"sha": "new-tree"}),
            ("POST", "/repos/acme/shop/git/commits"): (201, {"sha": "new-commit"}),
            ("POST", "/repos/acme/shop/git/refs"): (201, {"ref": "x"}),
            ("POST", "/repos/acme/shop/pulls"): (
                201,
                {"html_url": "https://github.com/acme/shop/pull/7", "number": 7},
            ),
        }
        status, payload = routes.get((request.method, path), (404, {"message": "Not Found"}))
        return httpx.Response(status, json=payload)


def _publisher() -> tuple[GitHubPullRequestPublisher, FakeGitHubWrites]:
    pem, public = _rsa_pem()
    fake = FakeGitHubWrites(public)
    transport = httpx.MockTransport(fake.handler)
    auth = GitHubAppAuth(fake.app_id, pem, base_url="https://github.test", transport=transport)
    return GitHubPullRequestPublisher(
        auth, base_url="https://github.test", transport=transport
    ), fake


async def test_app_token_flow_and_draft_pr_only() -> None:
    publisher, fake = _publisher()
    pr = await publisher.open_draft_pr(
        "acme/shop", branch="agent-hq/abc-r1", title="t", body="b", files={"a.py": "x = 1\n"}
    )
    assert pr.url.endswith("/pull/7") and pr.branch == "agent-hq/abc-r1"
    methods = {(m, p) for m, p, _ in fake.calls}
    assert ("POST", "/app/installations/42/access_tokens") in methods
    token_request = next(b for m, p, b in fake.calls if p.endswith("/access_tokens"))
    assert token_request == {
        "repositories": ["shop"],
        "permissions": {"contents": "write", "pull_requests": "write"},
    }
    pull: dict[str, Any] = next(b for m, p, b in fake.calls if p.endswith("/pulls") and b)
    assert pull is not None and pull["draft"] is True and pull["base"] == "main"
    ref = next(b for m, p, b in fake.calls if p.endswith("/git/refs"))
    assert ref == {"ref": "refs/heads/agent-hq/abc-r1", "sha": "new-commit"}
    # Only creation calls: no PATCH/PUT/DELETE (no force push, no merge).
    assert {m for m, _, _ in fake.calls} <= {"GET", "POST"}
    assert not any("merge" in p for _, p, _ in fake.calls)
    # The installation token is cached.
    await publisher._auth.installation_token("acme/shop")
    assert sum(p.endswith("/access_tokens") for _, p, _ in fake.calls) == 1
    await publisher.aclose()


async def test_approved_changeset_opens_a_real_draft_pr(harness: Harness) -> None:
    publisher, fake = _publisher()
    harness.runtime.pull_requests = publisher
    await harness.login()
    project = await harness.create_project_with_repos(["acme/shop"])
    await harness.client.put(
        f"/projects/{project}/integrations/github",
        json={"allowed_repos": ["acme/shop"], "pull_requests": True},
    )
    task_id = await harness.create_task(project, REQUEST)
    await harness.client.post(f"/tasks/{task_id}/start")
    await harness.run_worker()
    task = await harness.task(task_id)
    [approval] = task["approvals"]
    assert approval["target"] == "github://acme/shop/pulls"
    assert "DRAFT pull request" in approval["expected_impact"]
    assert not any(p.endswith("/pulls") for _, p, _ in fake.calls)  # nothing before approval

    await harness.client.post(f"/approvals/{approval['id']}/approve", json={})
    await harness.run_worker()
    task = await harness.task(task_id)
    assert task["status"] == "COMPLETED"
    assert task["result"]["publication"]["location"] == "https://github.com/acme/shop/pull/7"
    tree: dict[str, Any] = next(b for m, p, b in fake.calls if p.endswith("/git/trees") and b)
    assert {e["path"] for e in tree["tree"]} == {
        "agenthq_changes/text_tools.py",
        "tests/test_text_tools.py",
    }
    pull: dict[str, Any] = next(b for m, p, b in fake.calls if p.endswith("/pulls") and b)
    assert "QA verdict:** ready" in pull["body"] and approval["id"] in pull["body"]
    async with harness.app.state.sessionmaker() as session:
        opened = await session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "changeset.pull_request_opened")
        )
    assert opened == 1
    await publisher.aclose()


async def test_pr_content_must_match_the_approved_hash(harness: Harness) -> None:
    publisher, fake = _publisher()
    harness.runtime.pull_requests = publisher
    await harness.login()
    project = await harness.create_project_with_repos(["acme/shop"])
    ctx = await real_context(harness, project, "cio")
    ctx.allowed_repos = frozenset({"acme/shop"})
    ctx.payload = {"changeset": {"summary": "evil", "files": [], "tests": []}}
    task_id = str(ctx.task_id)
    outcome = await execute_tool(
        ctx,
        "changeset.propose",
        {
            "target": "github://acme/shop/pulls",
            "task_id": task_id,
            "run_number": 1,
            "changeset_sha256": "0" * 64,
            "qa_report_sha256": "0" * 64,
        },
    )
    assert outcome.denied  # no approval exists, and the content would not match anyway
    assert fake.calls == []
    await publisher.aclose()


@dataclass
class FakeChat:
    fail_telegram_times: int = 0
    sent: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def handler(self, request: httpx.Request) -> httpx.Response:
        channel = "telegram" if request.url.host == "api.telegram.org" else "slack"
        if channel == "telegram" and self.fail_telegram_times > 0:
            self.fail_telegram_times -= 1
            return httpx.Response(502)
        self.sent.append((channel, json.loads(request.content)))
        return httpx.Response(200, json={"ok": True})


async def test_notifications_are_delivered_once_with_retries(harness: Harness) -> None:
    chat = FakeChat(fail_telegram_times=1)
    configured = harness.settings.model_copy(
        update={
            "slack_webhook_url": SecretStr("https://hooks.slack.test/T/B/secret"),
            "telegram_bot_token": SecretStr("123:secret"),
            "telegram_chat_id": "42",
            "public_url": "https://hq.example.test",
        }
    )
    harness.worker.notifier = Notifier(configured, transport=httpx.MockTransport(chat.handler))
    await harness.login()
    project = await harness.create_project_with_repos(["acme/shop"])
    task_id = await harness.create_task(project, "Review the CI pipeline of acme/shop.")
    await harness.client.post(f"/tasks/{task_id}/start")
    await harness.run_worker()

    async with harness.app.state.sessionmaker() as session:
        rows = list(await session.scalars(select(Notification)))
    # Only the top-level milestone; the DevOps subtask's completion is not announced.
    assert [r.kind for r in rows] == ["approval_requested"]
    assert rows[0].delivered_channels == ["slack"] and rows[0].attempts == 1

    async with harness.app.state.sessionmaker() as session:
        await session.execute(update(Notification).values(run_after=func.now()))
        await session.commit()
    await harness.worker.deliver_notifications()
    async with harness.app.state.sessionmaker() as session:
        row = await session.scalar(select(Notification))
    assert row is not None and row.status == "sent"
    assert [c for c, _ in chat.sent] == ["slack", "telegram"]  # no duplicate Slack message
    text = chat.sent[0][1]["text"]
    assert f"https://hq.example.test/tasks/{task_id}" in text
    assert "secret" not in json.dumps(chat.sent)


async def test_notifications_skip_when_no_channel(harness: Harness) -> None:
    await harness.login()
    project = await harness.create_project_with_repos(["acme/shop"])
    task_id = await harness.create_task(project, "Review the CI pipeline of acme/shop.")
    await harness.client.post(f"/tasks/{task_id}/start")
    await harness.run_worker()
    async with harness.app.state.sessionmaker() as session:
        statuses = list(await session.scalars(select(Notification.status)))
    assert statuses == ["skipped"]


def test_demo_refuses_real_credentials(settings: Settings) -> None:
    with pytest.raises(RuntimeError, match="real credentials"):
        create_app(settings.model_copy(update={"demo_mode": True}))
    with pytest.raises(RuntimeError, match="mock model provider"):
        create_app(
            settings.model_copy(
                update={
                    "demo_mode": True,
                    "github_token": None,
                    "model_profile_reasoning": "openai:x",
                }
            )
        )


async def test_demo_seed_and_read_only_access(harness: Harness) -> None:
    from agent_hq.demo import seed_demo
    from agent_hq.orchestration.worker import Worker, open_checkpointer
    from agent_hq.runtime import Runtime

    demo = harness.settings.model_copy(update={"demo_mode": True, "github_token": None})

    async def run_worker(runtime: Runtime) -> None:
        async with open_checkpointer(demo) as checkpointer:
            await Worker(runtime, checkpointer).run_until_idle()
        await runtime.github.aclose()
        await runtime.sandbox.aclose()

    assert await seed_demo(demo, harness.app.state.sessionmaker, run_worker) == "demo data seeded"
    assert (
        await seed_demo(demo, harness.app.state.sessionmaker, run_worker)
        == "demo data already present"
    )

    app = create_app(demo, start_background=False)
    await init_state(app, demo, start_background=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://demo"
    ) as visitor:
        me = (await visitor.get("/auth/me")).json()
        assert me["user"]["role"] == "viewer"
        tasks = (await visitor.get("/tasks")).json()
        assert sorted(t["status"] for t in tasks) == [
            "COMPLETED", "COMPLETED", "FAILED", "WAITING_APPROVAL"
        ]  # fmt: skip
        assert len((await visitor.get("/knowledge")).json()) >= 4
        approval = (await visitor.get("/approvals", params={"status": "pending"})).json()[0]
        [conversation] = (await visitor.get("/conversations")).json()
        chat = (await visitor.get(f"/conversations/{conversation['id']}")).json()
        assert [m["status"] for m in chat["messages"]] == ["complete"] * 4
        assert "Pending approvals:" in chat["messages"][1]["content"]
        assert "QA Engineer" in chat["messages"][1]["content"]
        assert chat["messages"][3]["proposals"][0]["project_key"] == "acme-shop"
        for method, path in [
            ("POST", f"/conversations/{conversation['id']}/messages"),
            ("POST", f"/approvals/{approval['id']}/approve"),
            ("POST", "/projects"),
            ("POST", "/auth/login"),
            ("PUT", f"/knowledge/{uuid.uuid4()}"),
        ]:
            r = await visitor.request(method, path, json={})
            assert r.status_code == 403, (method, path)
    await app.state.engine.dispose()

    with pytest.raises(RuntimeError, match="DEMO_MODE"):
        await seed_demo(harness.settings, harness.app.state.sessionmaker, run_worker)
