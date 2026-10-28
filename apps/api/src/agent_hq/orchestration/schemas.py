"""Typed contracts exchanged between graph nodes and agents."""

from typing import Literal

from pydantic import BaseModel, Field


class Requirements(BaseModel):
    summary: str = Field(description="One-paragraph restatement of what is being asked")
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


class OutcomeSummary(BaseModel):
    outcome: str
    risks: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
