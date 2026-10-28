"""Deterministic verification of specialist output. No model is involved."""

from typing import Any

from pydantic import ValidationError

from agent_hq.integrations.github import is_secret_path
from agent_hq.logging import contains_credential
from agent_hq.orchestration.schemas import (
    Changeset,
    CicdRecommendation,
    QaReport,
    TestPlan,
    VerificationResult,
)
from agent_hq.sandbox.contracts import RunResult, validate_workspace_path

MAX_CHANGESET_FILES = 20
MAX_CHANGESET_BYTES = 200_000


def verify_recommendation(
    rec: CicdRecommendation, *, allowed_repos: frozenset[str]
) -> VerificationResult:
    problems: list[str] = []
    if rec.repository not in allowed_repos:
        problems.append(f"repository {rec.repository!r} is not authorized")
    inspected = {f.path for f in rec.files_inspected}
    if not inspected:
        problems.append("no files were inspected; the result has no evidence")
    for i, finding in enumerate(rec.findings):
        if finding.file not in inspected:
            problems.append(f"finding {i} references {finding.file!r}, which was not read")
    if not rec.findings and not rec.recommendations and not rec.limitations:
        problems.append("empty result: no findings, recommendations or stated limitations")
    for i, recommendation in enumerate(rec.recommendations):
        if not recommendation.title.strip() or not recommendation.rationale.strip():
            problems.append(f"recommendation {i} lacks a title or rationale")
    if contains_credential(rec.model_dump_json()):
        problems.append("output contains credential-like strings")
    return VerificationResult(passed=not problems, problems=problems)


def verify_changeset(cs: Changeset) -> VerificationResult:
    problems: list[str] = []
    everything = [*cs.files, *cs.tests]
    if not cs.files:
        problems.append("changeset has no production files")
    if not cs.tests:
        problems.append("changeset has no tests")
    if len(everything) > MAX_CHANGESET_FILES:
        problems.append(f"changeset has more than {MAX_CHANGESET_FILES} files")
    if sum(len(f.content.encode()) for f in everything) > MAX_CHANGESET_BYTES:
        problems.append(f"changeset exceeds {MAX_CHANGESET_BYTES} bytes")
    paths = [f.path for f in everything]
    if len(paths) != len(set(paths)):
        problems.append("changeset contains duplicate paths")
    for path in paths:
        try:
            validate_workspace_path(path)
        except ValueError:
            problems.append(f"invalid path {path!r}")
        if is_secret_path(path):
            problems.append(f"changeset touches a protected path {path!r}")
    for test in cs.tests:
        if "test" not in test.path.rsplit("/", 1)[-1]:
            problems.append(f"test file {test.path!r} is not named as a test")
    if contains_credential(cs.model_dump_json()):
        problems.append("changeset contains credential-like strings")
    return VerificationResult(passed=not problems, problems=problems)


def verify_test_plan(plan: TestPlan) -> VerificationResult:
    if not plan.cases:
        return VerificationResult(passed=False, problems=["test plan has no cases"])
    return VerificationResult(passed=True)


def verify_qa(report: QaReport, sandbox: RunResult | None) -> VerificationResult:
    """A QA verdict must agree with what the sandbox actually observed."""
    problems: list[str] = []
    if sandbox is None:
        problems.append("QA did not run the tests in the sandbox")
    elif report.verdict == "ready" and not sandbox.succeeded:
        problems.append("QA reported ready but the sandbox run did not pass")
    if report.verdict == "not_ready" and not report.failures:
        problems.append("QA reported not_ready without listing failures")
    return VerificationResult(passed=not problems, problems=problems)


def verify_step(
    kind: str, output: dict[str, Any], *, allowed_repos: frozenset[str]
) -> VerificationResult:
    try:
        if kind == "cicd_review":
            return verify_recommendation(
                CicdRecommendation.model_validate(output), allowed_repos=allowed_repos
            )
        if kind == "implement":
            return verify_changeset(Changeset.model_validate(output))
        if kind == "test_plan":
            return verify_test_plan(TestPlan.model_validate(output))
        if kind == "run_tests":
            sandbox = output.get("sandbox")
            return verify_qa(
                QaReport.model_validate(output["report"]),
                RunResult.model_validate(sandbox) if sandbox else None,
            )
    except (ValidationError, KeyError) as exc:
        return VerificationResult(passed=False, problems=[f"malformed output: {exc}"[:300]])
    return VerificationResult(passed=False, problems=[f"unknown step kind {kind!r}"])
