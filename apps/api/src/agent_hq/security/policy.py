"""Server-side authorization for agent actions. See docs/security/permission-matrix.md.

Every check here is independent of prompts and model output.
"""

import re
from collections.abc import Iterable

from agent_hq.agents import REGISTRY
from agent_hq.domain import DomainError

REPO_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")


class PolicyDenied(DomainError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def authorize_tool(agent_key: str, tool_name: str) -> None:
    agent = REGISTRY.get(agent_key)
    if agent is None:
        raise PolicyDenied(f"unknown agent {agent_key!r}")
    if tool_name not in agent.allowed_tools:
        raise PolicyDenied(f"agent {agent_key!r} is not permitted to use {tool_name!r}")


def authorize_delegation(from_agent: str, to_agent: str) -> None:
    source = REGISTRY.get(from_agent)
    if source is None or to_agent not in source.can_delegate_to or to_agent not in REGISTRY:
        raise PolicyDenied(f"agent {from_agent!r} may not delegate to {to_agent!r}")


def authorize_repository(repository: str, allowed: Iterable[str]) -> str:
    """Return the canonical repository name if it is on the project's allowlist."""
    if not REPO_PATTERN.match(repository):
        raise PolicyDenied("malformed repository name")
    allowed_map = {r.lower(): r for r in allowed}
    canonical = allowed_map.get(repository.lower())
    if canonical is None:
        raise PolicyDenied(f"repository {repository!r} is not authorized for this project")
    return canonical
