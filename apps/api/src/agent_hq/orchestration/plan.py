"""Fixed plan templates per workflow (ADR-0011): the DAG comes from code, not the model."""

from agent_hq.agents import DEVOPS, QA, SOFTWARE_ENGINEER
from agent_hq.orchestration.schemas import PlanStep, Workflow


def build_plan(workflow: Workflow, *, repository: str, objectives: list[str]) -> list[PlanStep]:
    goal = "; ".join(objectives) or "complete the request"
    if workflow == "cicd_review":
        return [
            PlanStep(
                id="cicd_review",
                agent_key=DEVOPS.key,
                kind="cicd_review",
                objective=f"Analyze the CI/CD pipeline of {repository}: {goal}",
            )
        ]
    # Implementation and test planning are independent, so they run in parallel.
    return [
        PlanStep(
            id="implement",
            agent_key=SOFTWARE_ENGINEER.key,
            kind="implement",
            objective=f"Implement in {repository}: {goal}",
        ),
        PlanStep(
            id="test_plan",
            agent_key=QA.key,
            kind="test_plan",
            objective=f"Plan tests for: {goal}",
        ),
        PlanStep(
            id="run_tests",
            agent_key=QA.key,
            kind="run_tests",
            depends_on=["implement", "test_plan"],
            objective="Run the tests in the sandbox and report a verdict",
        ),
    ]


def add_rework(plan: list[PlanStep], *, round_: int, feedback: str) -> list[PlanStep]:
    """Append one implement → run_tests iteration that addresses QA feedback."""
    implement_id = f"implement_{round_}"
    return [
        *plan,
        PlanStep(
            id=implement_id,
            agent_key=SOFTWARE_ENGINEER.key,
            kind="implement",
            objective="Fix the failures reported by QA",
            feedback=feedback,
        ),
        PlanStep(
            id=f"run_tests_{round_}",
            agent_key=QA.key,
            kind="run_tests",
            depends_on=[implement_id, "test_plan"],
            objective="Re-run the tests on the revised changeset",
        ),
    ]


def ready_steps(plan: list[PlanStep], done: set[str]) -> list[PlanStep]:
    return [s for s in plan if s.id not in done and all(d in done for d in s.depends_on)]


def last_of_kind(plan: list[PlanStep], kind: str) -> PlanStep | None:
    matches = [s for s in plan if s.kind == kind]
    return matches[-1] if matches else None
