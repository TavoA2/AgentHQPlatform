import asyncio
import base64
import json
import os
import sys
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest
from pydantic import PostgresDsn, SecretStr
from sqlalchemy.engine import make_url

# Psycopg's async mode cannot run on Windows' default ProactorEventLoop; the server uses
# the same workaround in agent_hq.cli.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from agent_hq.config import Settings

API_ROOT = Path(__file__).resolve().parents[1]
APP_TABLES = (
    "conversation_messages, conversations, "
    "notifications, knowledge_document_versions, knowledge_documents, audit_events, "
    "task_events, "
    "approval_requests, jobs, task_executions, tasks, "
    "integrations, sessions, projects, agents, users"
)
CHECKPOINT_TABLES = "checkpoints, checkpoint_blobs, checkpoint_writes"
ADMIN_EMAIL = "owner@example.test"
ADMIN_PASSWORD = "correct-horse-battery-staple"


def _test_database_url() -> str | None:
    explicit = os.environ.get("AGENT_HQ_TEST_DATABASE_URL")
    if explicit:
        return explicit
    base = os.environ.get("AGENT_HQ_DATABASE_URL")
    if not base:
        return None
    return (
        make_url(base)
        .set(database=f"{make_url(base).database}_test")
        .render_as_string(hide_password=False)
    )


TEST_DB_URL = _test_database_url()
requires_db = pytest.mark.skipif(TEST_DB_URL is None, reason="requires a running PostgreSQL")


def _libpq(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
def database() -> Iterator[str]:
    """Create a fresh test database, migrate it and set up the checkpointer tables."""
    if TEST_DB_URL is None:
        pytest.skip("requires a running PostgreSQL")
    url = make_url(TEST_DB_URL)
    admin_url = _libpq(url.set(database="postgres").render_as_string(hide_password=False))
    with psycopg.connect(admin_url, autocommit=True, connect_timeout=5) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{url.database}"')

    from alembic import command
    from alembic.config import Config
    from langgraph.checkpoint.postgres import PostgresSaver

    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", TEST_DB_URL.replace("%", "%%"))
    command.upgrade(config, "head")
    with PostgresSaver.from_conn_string(_libpq(TEST_DB_URL)) as saver:
        saver.setup()
    yield TEST_DB_URL


@pytest.fixture
def clean_db(database: str) -> str:
    with psycopg.connect(_libpq(database), autocommit=True) as conn:
        conn.execute(f"TRUNCATE {APP_TABLES}, {CHECKPOINT_TABLES} RESTART IDENTITY CASCADE")
    return database


@pytest.fixture
def settings(clean_db: str) -> Settings:
    return Settings(
        environment="test",
        database_url=PostgresDsn(clean_db),
        session_secret=SecretStr("s" * 48),
        model_profile_reasoning="mock:mock-reasoning",
        model_profile_fast="mock:mock-fast",
        model_overrides={},
        model_pricing={"mock-reasoning": (2.0, 10.0)},
        github_token=SecretStr("test-token"),
        github_api_url="https://github.test",
        sandbox_url="http://sandbox.test",
        sandbox_token=SecretStr("t" * 40),
        max_parallel_steps=2,
        job_lease_seconds=60,
        approval_ttl_hours=24,
        # Time-based alerts depend on the wall clock; tests enable them explicitly.
        alert_approval_reminder_hours=0,
        alert_daily_brief_hour_utc=-1,
    )


# --- fake GitHub -------------------------------------------------------------------------

WORKFLOW = """name: CI
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: make test
"""
DOCKERFILE = 'FROM python:latest\nCOPY . /app\nCMD ["python", "app.py"]\n'


@dataclass
class FakeGitHub:
    repos: dict[str, dict[str, str]] = field(
        default_factory=lambda: {
            "acme/shop": {
                ".github/workflows/ci.yml": WORKFLOW,
                "Dockerfile": DOCKERFILE,
                "README.md": "# shop\n",
                "src/app.py": "print('hi')\n",
            },
            "acme/other": {".github/workflows/ci.yml": WORKFLOW},
        }
    )
    requests: list[str] = field(default_factory=list)

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append(path)
        parts = path.strip("/").split("/")
        if len(parts) < 3 or parts[0] != "repos":
            return httpx.Response(404, json={"message": "Not Found"})
        repo = f"{parts[1]}/{parts[2]}"
        files = self.repos.get(repo)
        if files is None:
            return httpx.Response(404, json={"message": "Not Found"})
        rest = parts[3:]
        if not rest:
            return httpx.Response(200, json={"default_branch": "main"})
        if rest[:2] == ["git", "trees"]:
            tree = [
                {"path": p, "type": "blob", "sha": f"sha-{p}", "size": len(c)}
                for p, c in files.items()
            ]
            return httpx.Response(200, json={"tree": tree})
        if rest[0] == "contents":
            file_path = "/".join(rest[1:])
            if file_path not in files:
                return httpx.Response(404, json={"message": "Not Found"})
            content = files[file_path].encode()
            return httpx.Response(
                200,
                json={
                    "type": "file",
                    "path": file_path,
                    "sha": f"sha-{file_path}",
                    "size": len(content),
                    "encoding": "base64",
                    "content": base64.b64encode(content).decode(),
                },
            )
        if rest[:2] == ["actions", "runs"]:
            return httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {"name": "CI", "status": "completed", "conclusion": "success"}
                    ]
                },
            )
        return httpx.Response(404, json={"message": "Not Found"})


@dataclass
class FakeSandbox:
    """Stands in for Docker behind the real runner app (auth + contract are exercised).

    A test file "fails" when it contains `assert False`; otherwise each `def test_` passes.
    """

    runs: list[dict[str, str]] = field(default_factory=list)

    async def execute(self, template: Any, files: dict[str, str], seconds: int) -> Any:
        from agent_hq.sandbox.contracts import RunResult, TestSummary

        self.runs.append(dict(files))
        tests = [c for p, c in files.items() if p.rsplit("/", 1)[-1].startswith("test_")]
        failed = sum(c.count("assert False") for c in tests)
        passed = sum(c.count("def test_") for c in tests) - failed
        output = f"{passed} passed" + (f", {failed} failed" if failed else "")
        return RunResult(
            exit_code=1 if failed else (0 if passed else 5),
            timed_out=False,
            duration_ms=10,
            output=output,
            summary=TestSummary(passed=passed, failed=failed),
        )


@pytest.fixture
def fake_sandbox() -> FakeSandbox:
    return FakeSandbox()


@pytest.fixture
def fake_github() -> FakeGitHub:
    return FakeGitHub()


# --- application, client, worker -------------------------------------------------------


@dataclass
class Harness:
    client: httpx.AsyncClient
    app: Any
    settings: Settings
    worker: Any
    runtime: Any
    github: FakeGitHub
    sandbox: FakeSandbox
    csrf: str = ""

    def use_script(self, script: Callable[..., Any]) -> None:
        from agent_hq.llm.mock import MockProvider
        from agent_hq.orchestration.mock_model import default_mock_responder

        self.runtime.models.register("mock", MockProvider(default_mock_responder, script))

    async def login(self) -> None:
        response = await self.client.post(
            "/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
        )
        assert response.status_code == 200, response.text
        self.csrf = response.json()["csrf_token"]
        self.client.headers["X-CSRF-Token"] = self.csrf

    async def run_worker(self) -> int:
        processed: int = await self.worker.run_until_idle()
        return processed

    async def create_project_with_repos(self, repos: list[str], key: str = "shop") -> str:
        r = await self.client.post("/projects", json={"key": key, "name": key.title()})
        assert r.status_code == 201, r.text
        project_id: str = r.json()["id"]
        r = await self.client.put(
            f"/projects/{project_id}/integrations/github", json={"allowed_repos": repos}
        )
        assert r.status_code == 200, r.text
        return project_id

    async def create_task(self, project_id: str, request: str) -> str:
        r = await self.client.post(
            "/tasks", json={"project_id": project_id, "title": "CI/CD review", "request": request}
        )
        assert r.status_code == 201, r.text
        task_id: str = r.json()["id"]
        return task_id

    async def task(self, task_id: str) -> dict[str, Any]:
        r = await self.client.get(f"/tasks/{task_id}")
        assert r.status_code == 200, r.text
        data: dict[str, Any] = r.json()
        return data


@pytest.fixture
async def harness(
    settings: Settings, fake_github: FakeGitHub, fake_sandbox: FakeSandbox
) -> AsyncIterator[Harness]:
    from agent_hq.agents import seed_agents
    from agent_hq.integrations.github import GitHubClient
    from agent_hq.main import create_app, init_state
    from agent_hq.models import User
    from agent_hq.orchestration.worker import Worker, build_runtime, open_checkpointer
    from agent_hq.security.auth import hash_password

    app = create_app(settings, start_background=False)
    await init_state(app, settings, start_background=False)
    async with app.state.sessionmaker() as session:
        await seed_agents(session)
        session.add(
            User(
                email=ADMIN_EMAIL, display_name="Owner", password_hash=hash_password(ADMIN_PASSWORD)
            )
        )
        await session.commit()

    runtime = build_runtime(settings, app.state.sessionmaker)
    runtime.github = GitHubClient(
        settings.github_token,
        base_url=settings.github_api_url,
        transport=httpx.MockTransport(fake_github.handler),
    )
    from agent_hq.sandbox.client import SandboxClient
    from agent_hq.sandbox.runner import create_sandbox_app

    runtime.sandbox = SandboxClient(
        settings.sandbox_url,
        settings.sandbox_token,
        transport=httpx.ASGITransport(app=create_sandbox_app(settings, fake_sandbox.execute)),
    )
    transport = httpx.ASGITransport(app=app)
    async with (
        open_checkpointer(settings) as checkpointer,
        httpx.AsyncClient(transport=transport, base_url="http://testserver") as client,
    ):
        yield Harness(
            client=client,
            app=app,
            settings=settings,
            worker=Worker(runtime, checkpointer),
            runtime=runtime,
            github=fake_github,
            sandbox=fake_sandbox,
        )
    await runtime.github.aclose()
    await runtime.sandbox.aclose()
    await app.state.engine.dispose()


def tool_results_text(request: Any) -> str:
    return "\n".join(m.content for m in request.messages if m.role == "tool")


def dumps(value: Any) -> str:
    return json.dumps(value)
