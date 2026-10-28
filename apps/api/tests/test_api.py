import pytest
from sqlalchemy import func, select

from agent_hq.models import Job
from tests.conftest import ADMIN_EMAIL, Harness, requires_db

pytestmark = [pytest.mark.anyio, requires_db]


async def test_protected_endpoints_require_login(harness: Harness) -> None:
    for path in ("/projects", "/tasks", "/agents", "/approvals", "/auth/me"):
        assert (await harness.client.get(path)).status_code == 401


async def test_login_sets_httponly_session_and_csrf(harness: Harness) -> None:
    r = await harness.client.post(
        "/auth/login", json={"email": ADMIN_EMAIL, "password": "correct-horse-battery-staple"}
    )
    assert r.status_code == 200
    cookies = r.headers.get_list("set-cookie")
    session_cookie = next(c for c in cookies if c.startswith("agent_hq_session="))
    assert "HttpOnly" in session_cookie and "SameSite=lax" in session_cookie
    assert any(c.startswith("agent_hq_csrf=") for c in cookies)
    assert (await harness.client.get("/auth/me")).json()["user"]["email"] == ADMIN_EMAIL


async def test_wrong_password_and_rate_limit(harness: Harness) -> None:
    for _ in range(5):
        r = await harness.client.post(
            "/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong-password-123"}
        )
        assert r.status_code == 401
    r = await harness.client.post(
        "/auth/login", json={"email": ADMIN_EMAIL, "password": "correct-horse-battery-staple"}
    )
    assert r.status_code == 429


async def test_state_changes_require_csrf_and_same_origin(harness: Harness) -> None:
    await harness.login()
    del harness.client.headers["X-CSRF-Token"]
    r = await harness.client.post("/projects", json={"key": "p1", "name": "P1"})
    assert r.status_code == 403
    r = await harness.client.post(
        "/projects",
        json={"key": "p1", "name": "P1"},
        headers={"X-CSRF-Token": harness.csrf, "Origin": "https://evil.example"},
    )
    assert r.status_code == 403
    r = await harness.client.post(
        "/projects", json={"key": "p1", "name": "P1"}, headers={"X-CSRF-Token": harness.csrf}
    )
    assert r.status_code == 201


async def test_logout_revokes_session(harness: Harness) -> None:
    await harness.login()
    assert (await harness.client.post("/auth/logout")).status_code == 204
    harness.client.cookies.clear()
    assert (await harness.client.get("/auth/me")).status_code == 401


async def test_projects_tasks_and_filters(harness: Harness) -> None:
    await harness.login()
    project = await harness.create_project_with_repos(["acme/shop"])
    other = await harness.create_project_with_repos(["acme/other"], key="other")

    r = await harness.client.put(
        f"/projects/{project}/integrations/github", json={"allowed_repos": ["not a repo"]}
    )
    assert r.status_code == 422
    assert (
        await harness.client.post("/projects", json={"key": "shop", "name": "x"})
    ).status_code == 409

    t1 = await harness.create_task(project, "Review CI of acme/shop")
    await harness.create_task(other, "Review CI of acme/other")

    by_project = (await harness.client.get("/tasks", params={"project_id": project})).json()
    assert [t["id"] for t in by_project] == [t1]
    assert by_project[0]["status"] == "DRAFT"
    assert by_project[0]["assigned_agent_key"] == "cio"

    r = await harness.client.post(f"/tasks/{t1}/start")
    assert r.status_code == 200 and r.json()["status"] == "QUEUED"
    assert (await harness.client.post(f"/tasks/{t1}/start")).status_code == 409

    queued = (await harness.client.get("/tasks", params={"status": "QUEUED"})).json()
    assert [t["id"] for t in queued] == [t1]
    by_agent = (await harness.client.get("/tasks", params={"agent": "cio"})).json()
    assert len(by_agent) == 2

    async with harness.app.state.sessionmaker() as session:
        assert await session.scalar(select(func.count()).select_from(Job)) == 1

    r = await harness.client.post(f"/tasks/{t1}/cancel")
    assert r.json()["status"] == "CANCELLED"
    assert (await harness.client.post(f"/tasks/{t1}/cancel")).status_code == 409


async def test_invalid_model_override_rejected(harness: Harness) -> None:
    await harness.login()
    project = await harness.create_project_with_repos(["acme/shop"])
    r = await harness.client.post(
        "/tasks",
        json={"project_id": project, "title": "x", "request": "y", "model_override": "gpt"},
    )
    assert r.status_code == 422
