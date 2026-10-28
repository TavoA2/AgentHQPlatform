import os
import subprocess

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from agent_hq.config import Settings
from agent_hq.integrations.github import is_secret_path
from agent_hq.sandbox.client import SandboxClient, SandboxError
from agent_hq.sandbox.contracts import (
    MAX_TOTAL_BYTES,
    RunRequest,
    RunResult,
    TestSummary,
    parse_pytest_summary,
    template_for,
)
from agent_hq.sandbox.runner import create_sandbox_app

TOKEN = "t" * 40


@pytest.mark.parametrize(
    "path", ["../x.py", "/etc/passwd", "a//b.py", "a/./b.py", "", "a b.py", "a;rm.py"]
)
def test_workspace_paths_are_validated(path: str) -> None:
    with pytest.raises(ValidationError):
        RunRequest(template="python-pytest", files={path: "x"})


def test_workspace_size_is_capped() -> None:
    with pytest.raises(ValidationError):
        RunRequest(template="python-pytest", files={"big.py": "x" * (MAX_TOTAL_BYTES + 1)})
    with pytest.raises(ValidationError):
        RunRequest(template="python-pytest", files={})


def test_only_allowlisted_templates_exist() -> None:
    with pytest.raises(ValidationError):
        RunRequest.model_validate({"template": "bash", "files": {"a.py": "x"}})
    with pytest.raises(ValueError, match="unknown"):
        template_for("bash", python_image="img")


def test_pytest_summary_parsing_and_success_rule() -> None:
    assert parse_pytest_summary("3 passed, 1 failed in 0.1s") == TestSummary(passed=3, failed=1)
    assert parse_pytest_summary("no tests ran") is None
    ok = RunResult(
        exit_code=0, timed_out=False, duration_ms=1, output="", summary=TestSummary(passed=1)
    )
    assert ok.succeeded
    assert not ok.model_copy(update={"timed_out": True}).succeeded
    assert not ok.model_copy(update={"summary": TestSummary(passed=0)}).succeeded


@pytest.mark.parametrize(
    ("path", "secret"),
    [
        (".env", True),
        ("config/.env.production", True),
        ("deploy/key.pem", True),
        (".git/config", True),
        ("src/app.py", False),
        ("README.md", False),
    ],
)
def test_secret_paths(path: str, secret: bool) -> None:
    assert is_secret_path(path) is secret


@pytest.mark.anyio
async def test_runner_requires_token() -> None:
    async def never(*_: object) -> RunResult:
        raise AssertionError("executor must not run without a valid token")

    settings = Settings(environment="test", sandbox_token=SecretStr(TOKEN))
    transport = httpx.ASGITransport(app=create_sandbox_app(settings, never))
    client = SandboxClient("http://sandbox.test", SecretStr("wrong"), transport=transport)
    with pytest.raises(SandboxError, match="401"):
        await client.run(RunRequest(template="python-pytest", files={"test_a.py": "x"}))
    await client.aclose()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _docker_image_available(image: str) -> bool:
    try:
        return (
            subprocess.run(  # noqa: S603
                ["docker", "image", "inspect", image],  # noqa: S607
                capture_output=True,
                timeout=20,
                check=False,
            ).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        return False


requires_docker = pytest.mark.skipif(
    os.environ.get("AGENT_HQ_DOCKER_TESTS") != "1"
    or not _docker_image_available("agent-hq-sandbox-python:local"),
    reason="set AGENT_HQ_DOCKER_TESTS=1 and build agent-hq-sandbox-python:local",
)


@requires_docker
def test_real_sandbox_isolation_and_timeout() -> None:
    from agent_hq.sandbox.runner import _run_in_docker

    template = template_for("python-pytest", python_image="agent-hq-sandbox-python:local")
    probe = _run_in_docker(
        template,
        {
            "test_probe.py": (
                "import os, socket\n"
                "def test_isolated():\n"
                "    assert os.getuid() == 65534\n"
                "    try:\n"
                "        socket.create_connection(('1.1.1.1', 53), timeout=3)\n"
                "        reachable = True\n"
                "    except OSError:\n"
                "        reachable = False\n"
                "    assert not reachable\n"
            )
        },
        60,
    )
    assert probe.succeeded, probe.output
    failing = _run_in_docker(template, {"test_f.py": "def test_f():\n    assert 1 == 2\n"}, 60)
    assert failing.exit_code == 1 and failing.summary == TestSummary(failed=1)
    hung = _run_in_docker(template, {"test_h.py": "def test_h():\n    while True: pass\n"}, 6)
    assert hung.timed_out and not hung.succeeded
