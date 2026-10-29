"""GitHub App authentication and the pull-request adapter (ADR-0013).

The only write operations implemented: create a *new* branch, one commit, a *draft* pull
request. No merge, no force push, no writes to existing branches.
"""

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import jwt

from agent_hq.integrations.github import GitHubError

TOKEN_REFRESH_MARGIN_SECONDS = 300


@dataclass
class _CachedToken:
    token: str
    expires_at: float


class GitHubAppAuth:
    """Exchanges a short-lived App JWT for one-hour, repository-scoped installation tokens."""

    def __init__(
        self,
        app_id: str,
        private_key_pem: str,
        *,
        base_url: str = "https://api.github.com",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._app_id = app_id
        self._key = private_key_pem
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
            timeout=20.0,
            transport=transport,
        )
        self._cache: dict[str, _CachedToken] = {}

    @classmethod
    def from_file(cls, app_id: str, key_file: str, **kwargs: Any) -> "GitHubAppAuth":
        return cls(app_id, Path(key_file).read_text(encoding="utf-8"), **kwargs)

    async def aclose(self) -> None:
        await self._http.aclose()

    def app_jwt(self) -> str:
        now = int(time.time())
        # Backdated iat tolerates clock drift; GitHub caps exp at 10 minutes.
        payload = {"iat": now - 60, "exp": now + 540, "iss": self._app_id}
        return jwt.encode(payload, self._key, algorithm="RS256")

    async def _app_request(self, method: str, url: str, **kwargs: Any) -> Any:
        response = await self._http.request(
            method, url, headers={"Authorization": f"Bearer {self.app_jwt()}"}, **kwargs
        )
        if response.status_code >= 400:
            raise GitHubError(
                f"GitHub App {response.status_code} on {url.split('?')[0]}",
                status=response.status_code,
                transient=response.status_code >= 500,
            )
        return response.json()

    async def installation_token(self, repo: str) -> str:
        """Token limited to this repository and to contents + pull requests."""
        cached = self._cache.get(repo)
        if cached and cached.expires_at - time.time() > TOKEN_REFRESH_MARGIN_SECONDS:
            return cached.token
        installation = await self._app_request("GET", f"/repos/{repo}/installation")
        data = await self._app_request(
            "POST",
            f"/app/installations/{installation['id']}/access_tokens",
            json={
                "repositories": [repo.split("/", 1)[1]],
                "permissions": {"contents": "write", "pull_requests": "write"},
            },
        )
        expires = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00")).timestamp()
        self._cache[repo] = _CachedToken(data["token"], expires)
        return str(data["token"])


@dataclass(frozen=True)
class PullRequest:
    url: str
    number: int
    branch: str


class GitHubPullRequestPublisher:
    def __init__(
        self,
        auth: GitHubAppAuth,
        *,
        base_url: str = "https://api.github.com",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._auth = auth
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
            timeout=30.0,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()
        await self._auth.aclose()

    async def _call(self, token: str, method: str, url: str, **kwargs: Any) -> Any:
        response = await self._http.request(
            method, url, headers={"Authorization": f"Bearer {token}"}, **kwargs
        )
        if response.status_code >= 400:
            raise GitHubError(
                f"GitHub {response.status_code} on {method} {url}",
                status=response.status_code,
                transient=response.status_code >= 500,
            )
        return response.json()

    async def open_draft_pr(
        self,
        repo: str,
        *,
        branch: str,
        title: str,
        body: str,
        files: dict[str, str],
    ) -> PullRequest:
        token = await self._auth.installation_token(repo)
        base = (await self._call(token, "GET", f"/repos/{repo}"))["default_branch"]
        head = await self._call(token, "GET", f"/repos/{repo}/git/ref/heads/{quote(base, safe='')}")
        base_sha = head["object"]["sha"]
        base_commit = await self._call(token, "GET", f"/repos/{repo}/git/commits/{base_sha}")
        tree = await self._call(
            token,
            "POST",
            f"/repos/{repo}/git/trees",
            json={
                "base_tree": base_commit["tree"]["sha"],
                "tree": [
                    {"path": path, "mode": "100644", "type": "blob", "content": content}
                    for path, content in sorted(files.items())
                ],
            },
        )
        commit = await self._call(
            token,
            "POST",
            f"/repos/{repo}/git/commits",
            json={"message": title, "tree": tree["sha"], "parents": [base_sha]},
        )
        # Creating (never updating) the ref: an existing branch makes this fail with 422.
        await self._call(
            token,
            "POST",
            f"/repos/{repo}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": commit["sha"]},
        )
        pr = await self._call(
            token,
            "POST",
            f"/repos/{repo}/pulls",
            json={"title": title, "head": branch, "base": base, "body": body, "draft": True},
        )
        return PullRequest(url=pr["html_url"], number=int(pr["number"]), branch=branch)
