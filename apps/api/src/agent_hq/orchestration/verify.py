"""Deterministic verification of specialist output. No model is involved."""

from agent_hq.logging import contains_credential
from agent_hq.orchestration.schemas import CicdRecommendation, VerificationResult


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
