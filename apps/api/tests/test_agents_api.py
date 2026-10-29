import pytest

from tests.conftest import Harness, requires_db

pytestmark = [pytest.mark.anyio, requires_db]


async def test_agent_detail_reflects_real_activity(harness: Harness) -> None:
    await harness.login()
    idle = (await harness.client.get("/agents/qa")).json()
    assert idle["status"] == "IDLE"
    assert idle["recent_activity"] == [] and idle["pending_approvals"] == 0

    project = await harness.create_project_with_repos(["acme/shop"])
    task_id = await harness.create_task(project, "Review the CI pipeline of acme/shop.")
    await harness.client.post(f"/tasks/{task_id}/start")
    await harness.run_worker()

    cio = (await harness.client.get("/agents/cio")).json()
    assert cio["display_name"] == "Dixon"
    assert cio["status"] == "WAITING_APPROVAL"
    assert cio["current_task_id"] == task_id
    assert cio["pending_approvals"] == 1
    assert [a["task_id"] for a in cio["recent_activity"]] == [task_id]

    devops = (await harness.client.get("/agents/devops")).json()
    [activity] = devops["recent_activity"]
    assert activity["parent_task_id"] == task_id  # its work is a delegated subtask
    assert activity["task_status"] == "COMPLETED"
    assert activity["execution"]["status"] == "succeeded"
    assert activity["execution"]["agent_key"] == "devops"

    assert (await harness.client.get("/agents/ceo")).status_code == 404
