import itertools

import pytest

from agent_hq.domain import TRANSITIONS, InvalidTransitionError, TaskStatus, check_transition
from agent_hq.integrations.github import is_ci_relevant
from agent_hq.security.approvals import action_hash
from agent_hq.security.policy import PolicyDenied, authorize_repository, authorize_tool

T = TaskStatus

ALLOWED = {
    (T.DRAFT, T.PLANNED), (T.DRAFT, T.QUEUED), (T.DRAFT, T.CANCELLED),
    (T.PLANNED, T.QUEUED), (T.PLANNED, T.CANCELLED),
    (T.QUEUED, T.RUNNING), (T.QUEUED, T.CANCELLED), (T.QUEUED, T.FAILED),
    (T.RUNNING, T.WAITING_APPROVAL), (T.RUNNING, T.IN_REVIEW), (T.RUNNING, T.FAILED),
    (T.RUNNING, T.CANCELLED),
    (T.WAITING_APPROVAL, T.RUNNING), (T.WAITING_APPROVAL, T.FAILED),
    (T.WAITING_APPROVAL, T.CANCELLED),
    (T.IN_REVIEW, T.COMPLETED), (T.IN_REVIEW, T.RUNNING), (T.IN_REVIEW, T.FAILED),
    (T.FAILED, T.QUEUED),
}  # fmt: skip


@pytest.mark.parametrize(("current", "target"), list(itertools.product(T, T)))
def test_every_transition_pair(current: TaskStatus, target: TaskStatus) -> None:
    if (current, target) in ALLOWED:
        check_transition(current, target)
    else:
        with pytest.raises(InvalidTransitionError):
            check_transition(current, target)


def test_table_matches_documented_machine() -> None:
    assert {(c, t) for c, targets in TRANSITIONS.items() for t in targets} == ALLOWED


def test_completed_only_reachable_from_review() -> None:
    sources = {c for c, targets in TRANSITIONS.items() if T.COMPLETED in targets}
    assert sources == {T.IN_REVIEW}


def test_action_hash_is_canonical_and_parameter_sensitive() -> None:
    a = action_hash("report.publish_external", "mock://x", {"a": 1, "b": [1, 2]})
    b = action_hash("report.publish_external", "mock://x", {"b": [1, 2], "a": 1})
    c = action_hash("report.publish_external", "mock://x", {"a": 2, "b": [1, 2]})
    d = action_hash("report.publish_external", "mock://y", {"a": 1, "b": [1, 2]})
    assert a == b
    assert len({a, c, d}) == 3


def test_agents_cannot_use_tools_outside_their_role() -> None:
    authorize_tool("devops", "github.read_file")
    with pytest.raises(PolicyDenied):
        authorize_tool("devops", "report.publish_external")
    with pytest.raises(PolicyDenied):
        authorize_tool("cio", "github.read_file")
    with pytest.raises(PolicyDenied):
        authorize_tool("unknown", "github.read_file")


@pytest.mark.parametrize("repo", ["evil/repo", "acme/shop2", "acme", "../acme/shop", "acme/shop/x"])
def test_repository_allowlist(repo: str) -> None:
    assert authorize_repository("ACME/Shop", ["acme/shop"]) == "acme/shop"
    with pytest.raises(PolicyDenied):
        authorize_repository(repo, ["acme/shop"])


@pytest.mark.parametrize(
    ("path", "ok"),
    [
        (".github/workflows/ci.yml", True),
        ("services/api/Dockerfile", True),
        ("docker-compose.yml", True),
        ("package.json", True),
        ("src/app.py", False),
        (".env", False),
        ("../.github/workflows/ci.yml", False),
        ("/etc/passwd", False),
    ],
)
def test_ci_path_scope(path: str, ok: bool) -> None:
    assert is_ci_relevant(path) is ok
