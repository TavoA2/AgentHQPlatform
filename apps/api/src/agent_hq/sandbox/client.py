"""Worker-side client for the sandbox runner. The worker never touches Docker itself."""

import httpx
from pydantic import SecretStr

from agent_hq.sandbox.contracts import RunRequest, RunResult


class SandboxError(RuntimeError):
    pass


class SandboxClient:
    def __init__(
        self,
        url: str,
        token: SecretStr,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=url,
            headers={"Authorization": f"Bearer {token.get_secret_value()}"},
            # Runs are bounded by the runner's own timeout; allow for container start-up.
            timeout=httpx.Timeout(400.0, connect=5.0),
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def run(self, request: RunRequest) -> RunResult:
        try:
            response = await self._http.post("/runs", json=request.model_dump())
        except httpx.TransportError as exc:
            raise SandboxError(f"sandbox unreachable: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise SandboxError(f"sandbox returned {response.status_code}")
        return RunResult.model_validate(response.json())
