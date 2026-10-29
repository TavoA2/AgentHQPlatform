"""Public demo data (ADR-0013).

`seed_demo` runs the *real* workflows end to end — CIO graph, specialists, verification,
approvals, The Brain — against a bundled sample repository, the mock model provider and an
in-process sandbox, so the demo shows genuine pipeline output rather than fixtures.
It refuses to run unless the instance is in demo mode.
"""

import base64
import secrets
import uuid
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_hq.agents import CIO, seed_agents
from agent_hq.api.deps import DEMO_VIEWER_EMAIL
from agent_hq.config import Settings
from agent_hq.domain import ApprovalStatus, JobKind, KnowledgeScope, TaskStatus
from agent_hq.integrations.github import GitHubClient
from agent_hq.integrations.reports import MockReportPublisher
from agent_hq.jobs import enqueue
from agent_hq.knowledge import create_document
from agent_hq.llm.router import ModelRouter
from agent_hq.models import Agent, ApprovalRequest, Integration, Project, Task, User
from agent_hq.orchestration.mock_model import default_mock_responder
from agent_hq.runtime import Runtime
from agent_hq.sandbox.client import SandboxClient
from agent_hq.sandbox.contracts import RunResult, Template, TestSummary
from agent_hq.sandbox.runner import create_sandbox_app
from agent_hq.security.approvals import decide
from agent_hq.tasks import transition

DEMO_OWNER_EMAIL = "owner@demo.agent-hq.local"
UNUSABLE_PASSWORD = "!"  # noqa: S105 - not an Argon2 hash: nobody can log in as it

SAMPLE_REPOS: dict[str, dict[str, str]] = {
    "acme/shop": {
        ".github/workflows/ci.yml": (
            "name: CI\non: [push, pull_request]\njobs:\n  test:\n    runs-on: ubuntu-latest\n"
            "    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-node@v4\n"
            "      - run: npm ci\n      - run: npm test\n"
        ),
        "Dockerfile": (
            'FROM node:latest\nWORKDIR /app\nCOPY . .\nRUN npm ci\nCMD ["npm", "start"]\n'
        ),
        "package.json": (
            '{"name": "shop", "scripts": {"test": "jest", "start": "node server.js"}}\n'
        ),
        "server.js": "require('http').createServer((q, r) => r.end('ok')).listen(3000);\n",
        "README.md": "# Acme Shop\n\nSample e-commerce storefront used by the Agent HQ demo.\n",
    },
    "globex/portal": {
        ".github/workflows/deploy.yml": (
            "name: Deploy\non: [push]\npermissions:\n  contents: read\njobs:\n  deploy:\n"
            "    runs-on: ubuntu-latest\n    timeout-minutes: 15\n    steps:\n"
            "      - uses: actions/checkout@v4\n"
        ),
        "README.md": "# Globex Portal\n",
    },
    "globex/api": {"README.md": "# Globex API\n"},
}

KNOWLEDGE: list[dict[str, Any]] = [
    {
        "kind": "service",
        "title": "Services we offer",
        "content": "Custom web applications, cloud infrastructure and DevOps, AI-powered "
        "business automation, IT consulting and application maintenance.",
    },
    {
        "kind": "policy",
        "title": "CI/CD standards",
        "content": "Every pipeline declares least-privilege permissions, pins third-party "
        "actions to commit SHAs, sets job timeouts and caches dependencies.",
    },
    {
        "kind": "procedure",
        "title": "Change review procedure",
        "content": "Agent-proposed changes are opened as draft pull requests and merged only "
        "after human code review and passing CI.",
    },
]


def sample_github_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        parts = request.url.path.strip("/").split("/")
        if len(parts) < 3 or parts[0] != "repos":
            return httpx.Response(404, json={"message": "Not Found"})
        files = SAMPLE_REPOS.get(f"{parts[1]}/{parts[2]}")
        if files is None:
            return httpx.Response(404, json={"message": "Not Found"})
        rest = parts[3:]
        if not rest:
            return httpx.Response(200, json={"default_branch": "main"})
        if rest[:2] == ["git", "trees"]:
            tree = [
                {"path": p, "type": "blob", "sha": f"demo-{abs(hash(p)) % 10**8}", "size": len(c)}
                for p, c in files.items()
            ]
            return httpx.Response(200, json={"tree": tree})
        if rest[0] == "contents":
            path = "/".join(rest[1:])
            if path not in files:
                return httpx.Response(404, json={"message": "Not Found"})
            data = files[path].encode()
            return httpx.Response(
                200,
                json={
                    "type": "file",
                    "path": path,
                    "sha": f"demo-{abs(hash(path)) % 10**8}",
                    "size": len(data),
                    "encoding": "base64",
                    "content": base64.b64encode(data).decode(),
                },
            )
        if rest[:2] == ["actions", "runs"]:
            run = {"name": "CI", "status": "completed", "conclusion": "success", "event": "push"}
            return httpx.Response(200, json={"workflow_runs": [run]})
        return httpx.Response(404, json={"message": "Not Found"})

    return httpx.MockTransport(handler)


async def demo_sandbox_executor(
    template: Template, files: dict[str, str], seconds: int
) -> RunResult:
    """Stand-in for Docker in the demo: counts the proposed tests (no code is executed)."""
    tests = [c for p, c in files.items() if p.rsplit("/", 1)[-1].startswith("test_")]
    passed = sum(c.count("def test_") for c in tests)
    return RunResult(
        exit_code=0 if passed else 5,
        timed_out=False,
        duration_ms=840,
        output=f"{'.' * passed}\n{passed} passed in 0.42s (demo sandbox)",
        summary=TestSummary(passed=passed),
    )


def demo_runtime(settings: Settings, sessionmaker: async_sessionmaker[AsyncSession]) -> Runtime:
    # No worker runs in a demo, so the waiting approval must not visibly expire.
    settings = settings.model_copy(update={"approval_ttl_hours": 24 * 365 * 5})
    sandbox_settings = settings.model_copy(
        update={"sandbox_token": SecretStr(secrets.token_urlsafe(40)), "environment": "test"}
    )
    sandbox_app = create_sandbox_app(sandbox_settings, demo_sandbox_executor)
    return Runtime(
        settings=settings,
        sessionmaker=sessionmaker,
        models=ModelRouter(settings, mock_default=default_mock_responder),
        github=GitHubClient(
            None, base_url="https://github.demo", transport=sample_github_transport()
        ),
        publisher=MockReportPublisher(),
        sandbox=SandboxClient(
            "http://sandbox.demo",
            sandbox_settings.sandbox_token,
            transport=httpx.ASGITransport(app=sandbox_app),
        ),
    )


async def _project(
    session: AsyncSession, owner: User, key: str, name: str, repos: list[str]
) -> Project:
    project = Project(key=key, name=name, client_name=f"{name} (sample client)", owner_id=owner.id)
    session.add(project)
    await session.flush()
    session.add(
        Integration(
            project_id=project.id,
            provider="github",
            name="default",
            config={"allowed_repos": repos, "pull_requests": False},
            secret_ref=None,
            scopes=["contents:read", "metadata:read"],
        )
    )
    await session.flush()
    return project


async def _start(
    session: AsyncSession,
    owner: User,
    project: Project,
    title: str,
    request: str,
    criteria: list[str] | None = None,
) -> uuid.UUID:
    cio_id = await session.scalar(select(Agent.id).where(Agent.key == CIO.key))
    task = Task(
        project_id=project.id,
        title=title,
        request=request,
        status=TaskStatus.DRAFT,
        assigned_agent_id=cio_id,
        created_by=owner.id,
        acceptance_criteria=criteria or [],
    )
    session.add(task)
    await session.flush()
    task.run_number = 1
    await transition(session, task, TaskStatus.QUEUED, actor_type="user", actor_id=str(owner.id))
    await enqueue(session, kind=JobKind.START, task_id=task.id, payload={"run_number": 1})
    return task.id


async def seed_demo(
    settings: Settings,
    sessionmaker: async_sessionmaker[AsyncSession],
    run_worker: Callable[[Runtime], Any],
) -> str:
    if not settings.demo_mode:
        raise RuntimeError("seed-demo only runs with AGENT_HQ_DEMO_MODE=true")
    async with sessionmaker() as session:
        if await session.scalar(select(User.id).where(User.email == DEMO_VIEWER_EMAIL)):
            return "demo data already present"
        await seed_agents(session)
        viewer = User(
            email=DEMO_VIEWER_EMAIL,
            display_name="Demo visitor",
            password_hash=UNUSABLE_PASSWORD,
            role="viewer",
        )
        owner = User(
            email=DEMO_OWNER_EMAIL,
            display_name="Demo owner",
            password_hash=UNUSABLE_PASSWORD,
            is_active=False,
        )
        session.add_all([viewer, owner])
        await session.flush()
        shop = await _project(session, owner, "acme-shop", "Acme Shop", ["acme/shop"])
        globex = await _project(session, owner, "globex", "Globex", ["globex/portal", "globex/api"])
        for doc in KNOWLEDGE:
            await create_document(
                session, scope=KnowledgeScope.COMPANY, project_id=None, user_id=owner.id, **doc
            )
        await create_document(
            session,
            scope=KnowledgeScope.PROJECT,
            project_id=shop.id,
            kind="constraint",
            title="Acme release window",
            content="Acme deploys on Tuesdays; CI must finish in under ten minutes.",
            user_id=owner.id,
        )
        # Order matters for the office view: the waiting task is started last, so Dixon's
        # most recent execution shows the approval indicator rather than the failed one.
        await _start(session, owner, globex, "Pipeline review", "Please review our pipelines.")
        approve_later = [
            await _start(
                session,
                owner,
                shop,
                "CI/CD review",
                "Review the CI/CD pipeline of acme/shop and propose improvements.",
            ),
            await _start(
                session,
                owner,
                shop,
                "Slugify helper",
                "Implement a slugify helper in acme/shop with tests.",
                ["lowercases text", "collapses symbols to one hyphen"],
            ),
        ]
        await _start(
            session,
            owner,
            shop,
            "Pre-release pipeline check",
            "Review the CI pipeline of acme/shop before the release.",
        )
        await session.commit()
        owner_id = owner.id

    await run_worker(demo_runtime(settings, sessionmaker))

    # Approve the first two (as the demo owner) to show completed work; the third stays
    # waiting so the approvals queue is not empty.
    async with sessionmaker() as session:
        approver = await session.get(User, owner_id)
        if approver is None:
            raise RuntimeError("demo owner missing")
        pending = await session.scalars(
            select(ApprovalRequest).where(
                ApprovalRequest.task_id.in_(approve_later),
                ApprovalRequest.status == ApprovalStatus.PENDING,
            )
        )
        for approval in pending:
            await decide(session, approval_id=approval.id, user=approver, approve=True, note="demo")
            await enqueue(
                session,
                kind=JobKind.RESUME,
                task_id=approval.task_id,
                payload={"approval_id": str(approval.id)},
            )
        await session.commit()
    await run_worker(demo_runtime(settings, sessionmaker))
    return "demo data seeded"
