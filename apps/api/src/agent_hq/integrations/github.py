"""Read-only GitHub REST client (ADR-0008). No write endpoints are implemented."""

import base64
import fnmatch
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import SecretStr

MAX_FILE_BYTES = 100_000
MAX_TREE_ENTRIES = 5_000

# Only CI/CD-relevant files may be read in Sprint 1.
CI_PATH_PATTERNS = (
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
    ".github/dependabot.yml",
    ".github/actions/*/action.yml",
    ".gitlab-ci.yml",
    "*Dockerfile*",
    "*docker-compose*.yml",
    "*docker-compose*.yaml",
    "*compose.yml",
    "*compose.yaml",
    "*package.json",
    "*pyproject.toml",
    "*requirements*.txt",
    "*go.mod",
    "*pom.xml",
    "*build.gradle*",
    "Makefile",
    "*.dockerignore",
)


class GitHubError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, transient: bool = False):
        super().__init__(message)
        self.status = status
        self.transient = transient


SECRET_PATH_PATTERNS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa*",
    "id_ed25519*",
    "*credential*",
    "*secret*",
    ".npmrc",
    ".pypirc",
    ".netrc",
)


def is_secret_path(path: str) -> bool:
    """Files that may hold credentials are never readable or writable by agents."""
    parts = path.lower().split("/")
    if ".git" in parts[:-1] or parts[-1] == ".git":
        return True
    return any(fnmatch.fnmatchcase(parts[-1], pattern) for pattern in SECRET_PATH_PATTERNS)


def is_ci_relevant(path: str) -> bool:
    if path.startswith("/") or ".." in path.split("/"):
        return False
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in CI_PATH_PATTERNS)


@dataclass(frozen=True)
class TreeEntry:
    path: str
    sha: str
    size: int


@dataclass(frozen=True)
class FileContent:
    path: str
    sha: str
    size: int
    content: str
    truncated: bool


class GitHubClient:
    def __init__(
        self,
        token: SecretStr | None,
        *,
        base_url: str = "https://api.github.com",
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 20.0,
    ) -> None:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "agent-hq",
        }
        if token is not None and token.get_secret_value():
            headers["Authorization"] = f"Bearer {token.get_secret_value()}"
        self._http = httpx.AsyncClient(
            base_url=base_url, headers=headers, timeout=timeout, transport=transport
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _get(self, url: str, **params: Any) -> Any:
        try:
            response = await self._http.get(url, params=params or None)
        except httpx.TransportError as exc:
            raise GitHubError(f"GitHub unreachable: {type(exc).__name__}", transient=True) from exc
        if response.status_code >= 400:
            transient = response.status_code >= 500 or response.status_code == 429
            message = response.json().get("message", "") if response.content else ""
            raise GitHubError(
                f"GitHub {response.status_code}: {message[:200]}",
                status=response.status_code,
                transient=transient,
            )
        return response.json()

    async def default_branch(self, repo: str) -> str:
        data = await self._get(f"/repos/{repo}")
        return str(data["default_branch"])

    async def list_tree(self, repo: str) -> list[TreeEntry]:
        branch = await self.default_branch(repo)
        data = await self._get(f"/repos/{repo}/git/trees/{quote(branch, safe='')}", recursive="1")
        entries = [
            TreeEntry(path=item["path"], sha=item["sha"], size=int(item.get("size", 0)))
            for item in data.get("tree", [])[:MAX_TREE_ENTRIES]
            if item.get("type") == "blob"
        ]
        return entries

    async def read_file(self, repo: str, path: str) -> FileContent:
        data = await self._get(f"/repos/{repo}/contents/{quote(path)}")
        if not isinstance(data, dict) or data.get("type") != "file":
            raise GitHubError(f"{path} is not a file")
        raw = base64.b64decode(data.get("content", "")) if data.get("encoding") == "base64" else b""
        truncated = len(raw) > MAX_FILE_BYTES
        text = raw[:MAX_FILE_BYTES].decode("utf-8", errors="replace")
        return FileContent(
            path=data["path"],
            sha=data["sha"],
            size=int(data.get("size", len(raw))),
            content=text,
            truncated=truncated,
        )

    async def list_workflow_runs(self, repo: str, limit: int) -> list[dict[str, Any]]:
        data = await self._get(f"/repos/{repo}/actions/runs", per_page=str(limit))
        return [
            {
                "name": run.get("name"),
                "status": run.get("status"),
                "conclusion": run.get("conclusion"),
                "event": run.get("event"),
                "head_branch": run.get("head_branch"),
                "created_at": run.get("created_at"),
                "html_url": run.get("html_url"),
            }
            for run in data.get("workflow_runs", [])[:limit]
        ]
