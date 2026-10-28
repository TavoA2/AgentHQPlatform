"""Sandbox runner service: the only component allowed to talk to Docker (ADR-0011).

It exposes one operation — run an allowlisted template on a workspace — inside a fresh,
locked-down container that is always removed afterwards.
"""

import asyncio
import hmac
import io
import logging
import tarfile
import time
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, status

from agent_hq.config import Settings
from agent_hq.logging import configure_logging, redact_text
from agent_hq.sandbox.contracts import (
    MAX_OUTPUT_BYTES,
    RunRequest,
    RunResult,
    Template,
    parse_pytest_summary,
    template_for,
)

logger = logging.getLogger(__name__)

SANDBOX_UID = 65534  # "nobody"
WORKDIR = "/tmp/workspace"  # noqa: S108 - path inside the throwaway container

Executor = Callable[[Template, dict[str, str], int], Awaitable[RunResult]]


def _workspace_archive(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        root = tarfile.TarInfo("workspace")
        root.type = tarfile.DIRTYPE
        root.mode = 0o755
        root.uid = root.gid = SANDBOX_UID
        tar.addfile(root)
        directories: set[str] = set()
        for path, content in sorted(files.items()):
            parts = path.split("/")[:-1]
            for i in range(1, len(parts) + 1):
                directory = "/".join(parts[:i])
                if directory not in directories:
                    directories.add(directory)
                    info = tarfile.TarInfo(f"workspace/{directory}")
                    info.type = tarfile.DIRTYPE
                    info.mode = 0o755
                    info.uid = info.gid = SANDBOX_UID
                    tar.addfile(info)
            data = content.encode()
            info = tarfile.TarInfo(f"workspace/{path}")
            info.size = len(data)
            info.mode = 0o644
            info.uid = info.gid = SANDBOX_UID
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _run_in_docker(template: Template, files: dict[str, str], timeout: int) -> RunResult:
    import docker
    from requests.exceptions import ConnectionError as RequestsConnectionError
    from requests.exceptions import ReadTimeout

    client = docker.from_env(timeout=timeout + 30)
    started = time.monotonic()
    container: Any = client.containers.create(
        template.image,
        command=list(template.command),
        working_dir=WORKDIR,
        user=f"{SANDBOX_UID}:{SANDBOX_UID}",
        network_mode="none",
        cap_drop=["ALL"],
        security_opt=["no-new-privileges"],
        mem_limit="512m",
        memswap_limit="512m",
        nano_cpus=1_000_000_000,
        pids_limit=128,
        environment={"HOME": "/tmp", "PYTHONDONTWRITEBYTECODE": "1"},  # noqa: S108
        labels={"agent-hq": "sandbox"},
    )
    timed_out = False
    exit_code: int | None = None
    try:
        container.put_archive("/tmp", _workspace_archive(files))  # noqa: S108
        container.start()
        try:
            exit_code = int(container.wait(timeout=timeout)["StatusCode"])
        except (ReadTimeout, RequestsConnectionError):
            timed_out = True
            container.kill()
        raw = container.logs(stdout=True, stderr=True)[-MAX_OUTPUT_BYTES:]
    finally:
        container.remove(force=True)
        client.close()
    output = redact_text(raw.decode("utf-8", errors="replace"))
    return RunResult(
        exit_code=exit_code,
        timed_out=timed_out,
        duration_ms=int((time.monotonic() - started) * 1000),
        output=output,
        summary=parse_pytest_summary(output),
    )


async def docker_executor(template: Template, files: dict[str, str], seconds: int) -> RunResult:
    return await asyncio.to_thread(_run_in_docker, template, files, seconds)


def create_sandbox_app(settings: Settings, executor: Executor = docker_executor) -> FastAPI:
    configure_logging(settings.log_level)
    token = settings.sandbox_token.get_secret_value()
    if len(token) < 32 and settings.environment != "test":
        raise RuntimeError("AGENT_HQ_SANDBOX_TOKEN must be set (at least 32 characters)")
    slots = asyncio.Semaphore(settings.sandbox_max_concurrency)
    app = FastAPI(title="Agent HQ sandbox runner", docs_url=None, redoc_url=None)

    def authorize(authorization: Annotated[str | None, Header()] = None) -> None:
        presented = (authorization or "").removeprefix("Bearer ")
        if not token or not hmac.compare_digest(presented, token):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid sandbox token")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/runs", dependencies=[Depends(authorize)])
    async def run(body: RunRequest) -> RunResult:
        template = template_for(body.template, python_image=settings.sandbox_python_image)
        async with slots:
            logger.info(
                "sandbox run started",
                extra={"template": body.template, "files": len(body.files)},
            )
            result = await executor(template, body.files, body.timeout_seconds)
        logger.info(
            "sandbox run finished",
            extra={"exit_code": result.exit_code, "timed_out": result.timed_out},
        )
        return result

    return app
