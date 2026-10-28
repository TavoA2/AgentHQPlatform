"""Sprint 2 workflow: CIO → Software Engineer ∥ QA test plan → QA in sandbox → approval."""

from typing import Any

import pytest
from sqlalchemy import func, select

from agent_hq.llm.base import ModelRequest, ModelResponse, ToolCall, Usage
from agent_hq.models import AuditEvent
from agent_hq.orchestration.mock_model import MOCK_MODULE, MOCK_TEST
from agent_hq.orchestration.schemas import ChangedFile, Changeset, QaReport
from tests.conftest import Harness, requires_db

pytestmark = [pytest.mark.anyio, requires_db]

REQUEST = "Implement a slugify helper in acme/shop with tests."


async def _audit_count(h: Harness, action: str) -> int:
    async with h.app.state.sessionmaker() as session:
        return int(
            await session.scalar(
                select(func.count()).select_from(AuditEvent).where(AuditEvent.action == action)
            )
            or 0
        )


async def _run(h: Harness, request: str = REQUEST) -> tuple[str, dict[str, Any]]:
    await h.login()
    project = await h.create_project_with_repos(["acme/shop"])
    r = await h.client.post(
        "/tasks",
        json={
            "project_id": project,
            "title": "slugify",
            "request": request,
            "acceptance_criteria": ["slugify lowercases", "symbols collapse to one hyphen"],
        },
    )
    task_id: str = r.json()["id"]
    await h.client.post(f"/tasks/{task_id}/start")
    await h.run_worker()
    return task_id, await h.task(task_id)


def _calls(h: Harness) -> list[str]:
    return [c.purpose for c in h.runtime.models._providers["mock"].calls]


def _changeset(test_body: str) -> ModelResponse:
    cs = Changeset(
        summary="slugify",
        rationale="r",
        files=[
            ChangedFile(
                path=MOCK_MODULE, action="create", content="def slugify(t):\n    return t\n"
            )
        ],
        tests=[ChangedFile(path=MOCK_TEST, action="create", content=test_body)],
    )
    return ModelResponse(cs.model_dump_json(), [], cs, Usage(5, 5))


async def test_code_change_happy_path(harness: Harness) -> None:
    task_id, task = await _run(harness)
    assert task["status"] == "WAITING_APPROVAL", task.get("failure_detail")

    subtasks = {s["options"]["step_id"]: s for s in task["subtasks"]}
    assert set(subtasks) == {"implement", "test_plan", "run_tests"}
    assert all(s["status"] == "COMPLETED" for s in subtasks.values())
    assert subtasks["implement"]["assigned_agent_key"] == "software_engineer"
    assert subtasks["run_tests"]["assigned_agent_key"] == "qa"
    assert subtasks["run_tests"]["result"]["report"]["verdict"] == "ready"
    assert subtasks["run_tests"]["result"]["sandbox"]["exit_code"] == 0

    # Implementation and test planning ran in the same wave (overlapping executions).
    execs = {
        (e["agent_key"], e["input"]["id"]): e for e in task["executions"] if e["input"].get("id")
    }
    implement = execs[("software_engineer", "implement")]
    plan = execs[("qa", "test_plan")]
    assert implement["started_at"] < plan["finished_at"]
    assert plan["started_at"] < implement["finished_at"]

    # QA ran the proposed files in the sandbox, not on the host.
    assert set(harness.sandbox.runs[-1]) == {MOCK_MODULE, MOCK_TEST}

    [approval] = task["approvals"]
    assert approval["action_type"] == "changeset.propose"
    assert approval["target"] == "mock://pull-requests/acme/shop"
    assert approval["evidence"]["qa_verdict"] == "ready"
    assert approval["risk_level"] == "medium"
    await harness.client.post(f"/approvals/{approval['id']}/approve", json={})
    await harness.run_worker()

    task = await harness.task(task_id)
    assert task["status"] == "COMPLETED"
    assert task["result"]["workflow"] == "code_change"
    assert task["result"]["qa"]["report"]["verdict"] == "ready"
    assert await _audit_count(harness, "changeset.proposed") == 1

    agents = {a["key"]: a["status"] for a in (await harness.client.get("/agents")).json()}
    assert agents == {"cio": "IDLE", "devops": "IDLE", "software_engineer": "IDLE", "qa": "IDLE"}

    listed = (await harness.client.get("/tasks")).json()
    assert [t["id"] for t in listed] == [task_id]  # subtasks are not top-level tasks


async def test_failing_tests_trigger_one_rework_round(harness: Harness) -> None:
    attempts = {"implement": 0}

    def engineer(request: ModelRequest) -> ModelResponse | None:
        if request.purpose != "swe.implement":
            return None
        attempts["implement"] += 1
        if attempts["implement"] == 1:
            return _changeset("def test_x():\n    assert False\n")
        assert "QA" in request.messages[-1].content or request.hints.get("feedback")
        return _changeset("def test_x():\n    assert True\n")

    harness.use_script(engineer)
    _, task = await _run(harness)
    assert task["status"] == "WAITING_APPROVAL", task.get("failure_detail")
    steps = [s["options"]["step_id"] for s in task["subtasks"]]
    assert steps == ["implement", "test_plan", "run_tests", "implement_2", "run_tests_2"]
    assert attempts["implement"] == 2


async def test_persistent_failures_fail_the_task(harness: Harness) -> None:
    harness.use_script(
        lambda r: (
            _changeset("def test_x():\n    assert False\n")
            if r.purpose == "swe.implement"
            else None
        )
    )
    _, task = await _run(harness)
    assert task["status"] == "FAILED"
    assert task["failure_reason"] == "qa_not_ready"
    assert not task["approvals"]


async def test_qa_cannot_report_ready_when_tests_fail(harness: Harness) -> None:
    def lying_qa(request: ModelRequest) -> ModelResponse | None:
        if request.purpose == "swe.implement":
            return _changeset("def test_x():\n    assert False\n")
        if request.purpose == "qa.run_tests" and any(m.role == "tool" for m in request.messages):
            report = QaReport(verdict="ready", summary="all good")
            return ModelResponse(report.model_dump_json(), [], report, Usage(5, 5))
        return None

    harness.use_script(lying_qa)
    _, task = await _run(harness)
    assert task["status"] == "FAILED"
    assert task["failure_reason"] == "verification_failed"
    assert "sandbox run did not pass" in task["failure_detail"]


async def test_changeset_touching_secrets_is_rejected(harness: Harness) -> None:
    def leaky(request: ModelRequest) -> ModelResponse | None:
        if request.purpose != "swe.implement":
            return None
        cs = Changeset(
            summary="s",
            rationale="r",
            files=[ChangedFile(path=".env", action="modify", content="DEBUG=1\n")],
            tests=[
                ChangedFile(
                    path="tests/test_env.py", action="create", content="def test_a(): pass\n"
                )
            ],
        )
        return ModelResponse(cs.model_dump_json(), [], cs, Usage(1, 1))

    harness.use_script(leaky)
    _, task = await _run(harness)
    assert task["status"] == "FAILED"
    assert "protected path '.env'" in task["failure_detail"]
    assert not harness.sandbox.runs  # never reached the sandbox


async def test_agents_cannot_use_each_others_tools(harness: Harness) -> None:
    probed = {"done": False}

    def overreaching(request: ModelRequest) -> ModelResponse | None:
        if request.purpose == "swe.implement" and not probed["done"]:
            probed["done"] = True
            return ModelResponse(
                "",
                [
                    ToolCall("a", "sandbox.run_tests", {"repository": "acme/shop"}),
                    ToolCall(
                        "b", "github.read_source", {"repository": "acme/shop", "path": ".env"}
                    ),
                    ToolCall("c", "changeset.propose", {}),
                ],
                None,
                Usage(1, 1),
            )
        return None

    harness.use_script(overreaching)
    _, task = await _run(harness)
    assert task["status"] == "WAITING_APPROVAL"
    assert await _audit_count(harness, "tool.denied") == 3
    assert not any(p.endswith("/contents/.env") for p in harness.github.requests)


async def test_crash_in_parallel_wave_does_not_rerun_finished_steps(harness: Harness) -> None:
    crashed = {"done": False}

    def flaky_plan(request: ModelRequest) -> ModelResponse | None:
        if request.purpose == "qa.test_plan" and not crashed["done"]:
            crashed["done"] = True
            raise RuntimeError("simulated worker crash in the QA step")
        return None

    harness.use_script(flaky_plan)
    task_id, task = await _run(harness)
    assert task["status"] == "RUNNING"
    async with harness.app.state.sessionmaker() as session:
        from sqlalchemy import update

        from agent_hq.models import Job

        await session.execute(update(Job).values(run_after=func.now()))
        await session.commit()
    await harness.run_worker()
    task = await harness.task(task_id)
    assert task["status"] == "WAITING_APPROVAL", task.get("failure_detail")
    # The engineer's step had completed in the crashed wave and was reused.
    assert _calls(harness).count("swe.implement") == 1


async def test_cicd_requests_still_route_to_devops(harness: Harness) -> None:
    _, task = await _run(harness, "Review the CI/CD pipeline of acme/shop.")
    assert task["status"] == "WAITING_APPROVAL", (task["failure_reason"], task["failure_detail"])
    assert task["status"] == "WAITING_APPROVAL"
    assert [s["assigned_agent_key"] for s in task["subtasks"]] == ["devops"]
    assert task["approvals"][0]["action_type"] == "report.publish_external"


async def test_metrics_summary(harness: Harness) -> None:
    await _run(harness)
    m = (await harness.client.get("/metrics/summary")).json()
    assert m["tasks_by_status"] == {"WAITING_APPROVAL": 1}
    assert m["subtasks_by_status"] == {"COMPLETED": 3}
    assert m["approvals_pending"] == 1
    usage = {a["key"]: a for a in m["agents"]}
    assert usage["software_engineer"]["executions"] == 1
    assert usage["qa"]["tokens_in"] > 0
    assert usage["devops"]["executions"] == 0
