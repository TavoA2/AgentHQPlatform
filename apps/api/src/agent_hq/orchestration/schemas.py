"""Typed contracts exchanged between graph nodes and agents."""

from typing import Literal

from pydantic import BaseModel, Field

Workflow = Literal["cicd_review", "code_change"]
StepKind = Literal["cicd_review", "implement", "test_plan", "run_tests"]


class Requirements(BaseModel):
    summary: str = Field(description="One-paragraph restatement of what is being asked")
    workflow: Workflow = Field(
        default="cicd_review",
        description="cicd_review: analyze CI/CD and recommend; code_change: implement a "
        "change with tests",
    )
    repository: str | None = Field(
        default=None, description="owner/name of the repository to analyze, if stated"
    )
    objectives: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(
        default_factory=list, description="Questions that must be answered before work starts"
    )


class Finding(BaseModel):
    severity: Literal["low", "medium", "high", "critical"]
    category: str = Field(description="e.g. security, reliability, performance, maintainability")
    file: str = Field(description="Path of an inspected file this finding is based on")
    line_start: int | None = None
    line_end: int | None = None
    description: str


class Recommendation(BaseModel):
    title: str
    rationale: str
    proposed_change: str = Field(description="Suggested change (text or diff); never applied")
    effort: Literal["small", "medium", "large"]
    risk: Literal["low", "medium", "high"]


class CicdAnalysis(BaseModel):
    """What the DevOps model returns."""

    findings: list[Finding] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class FileEvidence(BaseModel):
    path: str
    sha: str
    size: int


class CicdRecommendation(CicdAnalysis):
    """The DevOps result. Evidence fields are filled by code from real tool results."""

    repository: str
    files_inspected: list[FileEvidence]


class VerificationResult(BaseModel):
    passed: bool
    problems: list[str] = Field(default_factory=list)


class ChangedFile(BaseModel):
    path: str = Field(description="Repository-relative path")
    action: Literal["create", "modify"]
    content: str = Field(description="Complete new content of the file")


class Changeset(BaseModel):
    """What the Software Engineer proposes. Never applied to the repository by Agent HQ."""

    summary: str
    rationale: str
    files: list[ChangedFile] = Field(description="Production code changes")
    tests: list[ChangedFile] = Field(description="Test files covering the change")
    risks: list[str] = Field(default_factory=list)


class TestCase(BaseModel):
    name: str
    description: str
    expected: str


class TestPlan(BaseModel):
    cases: list[TestCase]
    notes: str = ""


class QaReport(BaseModel):
    verdict: Literal["ready", "not_ready"]
    summary: str
    failures: list[str] = Field(default_factory=list)
    criteria_covered: list[str] = Field(default_factory=list)


class PlanStep(BaseModel):
    id: str
    agent_key: str
    kind: StepKind
    depends_on: list[str] = Field(default_factory=list)
    objective: str
    feedback: str | None = None


class OutcomeSummary(BaseModel):
    outcome: str
    risks: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
