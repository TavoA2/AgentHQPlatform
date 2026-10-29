"""Deterministic default answers for the mock provider.

They make the full workflow runnable offline with plausible output derived from the real
files the agent read. They are not a substitute for a real model's analysis.
"""

import json
import re
from typing import Any, Literal

from pydantic import BaseModel

from agent_hq.llm.base import ModelRequest, ModelResponse, ToolCall
from agent_hq.llm.mock import estimate_usage
from agent_hq.orchestration.schemas import (
    CicdAnalysis,
    Finding,
    OutcomeSummary,
    Recommendation,
    Requirements,
)

_REPO_IN_TEXT = re.compile(r"\b([A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+)\b")
_MUTABLE_ACTION = re.compile(r"uses:\s*[\w./-]+@v?\d[\w.]*\s*$", re.MULTILINE)
_WRAPPED = re.compile(r"<untrusted_tool_output[^>]*>\n(.*)\n</untrusted_tool_output>", re.DOTALL)


def _respond(
    request: ModelRequest,
    parsed: BaseModel | None = None,
    tool_calls: list[ToolCall] | None = None,
) -> ModelResponse:
    content = parsed.model_dump_json() if parsed is not None else ""
    return ModelResponse(
        content=content,
        tool_calls=tool_calls or [],
        parsed=parsed,
        usage=estimate_usage(request, content),
    )


def _tool_results(request: ModelRequest) -> list[dict[str, Any]]:
    results = []
    for message in request.messages:
        if message.role != "tool":
            continue
        match = _WRAPPED.search(message.content)
        try:
            results.append(json.loads(match.group(1) if match else message.content))
        except json.JSONDecodeError:
            continue
    return results


def _analyze_files(files: list[dict[str, Any]]) -> CicdAnalysis:
    findings: list[Finding] = []
    recommendations: dict[str, Recommendation] = {}
    for f in files:
        path, content = f["path"], f.get("content", "")
        if path.startswith(".github/workflows/"):
            if "permissions:" not in content:
                findings.append(
                    Finding(
                        severity="high",
                        category="security",
                        file=path,
                        description="Workflow does not declare `permissions`, so GITHUB_TOKEN "
                        "gets the repository default (often write).",
                    )
                )
                recommendations["perms"] = Recommendation(
                    title="Declare least-privilege token permissions",
                    rationale="Limits the blast radius of a compromised step or dependency.",
                    proposed_change="permissions:\n  contents: read",
                    effort="small",
                    risk="low",
                )
            if _MUTABLE_ACTION.search(content):
                findings.append(
                    Finding(
                        severity="medium",
                        category="supply-chain",
                        file=path,
                        description="Third-party actions are referenced by mutable tags.",
                    )
                )
                recommendations["pin"] = Recommendation(
                    title="Pin actions to full commit SHAs",
                    rationale="A moved tag can inject code into CI; SHAs are immutable.",
                    proposed_change="uses: actions/checkout@<40-char-sha>  # v5",
                    effort="small",
                    risk="low",
                )
            if "timeout-minutes" not in content:
                findings.append(
                    Finding(
                        severity="low",
                        category="reliability",
                        file=path,
                        description="Jobs have no `timeout-minutes`; "
                        "a hung job can run for 6 hours.",
                    )
                )
                recommendations["timeout"] = Recommendation(
                    title="Set job timeouts",
                    rationale="Bounds wasted runner minutes and surfaces hangs quickly.",
                    proposed_change="timeout-minutes: 15",
                    effort="small",
                    risk="low",
                )
        elif "Dockerfile" in path:
            if not re.search(r"^USER\s+\S+", content, re.MULTILINE):
                findings.append(
                    Finding(
                        severity="medium",
                        category="security",
                        file=path,
                        description="Image runs as root (no USER instruction).",
                    )
                )
            if re.search(r"^FROM\s+\S+:latest\b", content, re.MULTILINE):
                findings.append(
                    Finding(
                        severity="medium",
                        category="reproducibility",
                        file=path,
                        description="Base image uses the mutable `latest` tag.",
                    )
                )
    limitations = ["Produced by the deterministic mock provider using fixed rules."]
    if not files:
        limitations.append("No files could be read.")
    return CicdAnalysis(
        findings=findings, recommendations=list(recommendations.values()), limitations=limitations
    )


_CODE_VERBS = re.compile(r"\b(implement|add|create|write|build|fix|refactor)\b", re.IGNORECASE)
_CI_TERMS = re.compile(r"\b(ci/cd|ci|cd|pipeline|workflows?|github actions)\b", re.IGNORECASE)

MOCK_MODULE = "agenthq_changes/text_tools.py"
MOCK_TEST = "tests/test_text_tools.py"
_MOCK_CODE = '''"""Proposed by the Agent HQ mock Software Engineer."""

import re


def slugify(text: str) -> str:
    """Lowercase words joined by single hyphens."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return "-".join(words)
'''
_MOCK_TESTS = """import os
import sys

sys.path.insert(0, os.getcwd())

from agenthq_changes.text_tools import slugify


def test_slugify_basic():
    assert slugify("Hello World") == "hello-world"


def test_slugify_collapses_symbols():
    assert slugify("  Agent -- HQ!! ") == "agent-hq"


def test_slugify_empty():
    assert slugify("") == ""
"""


def _classify(text: str) -> Literal["cicd_review", "code_change"]:
    if _CODE_VERBS.search(text) and not _CI_TERMS.search(text):
        return "code_change"
    return "cicd_review"


def _implement(request: ModelRequest) -> ModelResponse:
    from agent_hq.orchestration.schemas import ChangedFile, Changeset

    return _respond(
        request,
        Changeset(
            summary="Add a slugify helper with tests",
            rationale="Deterministic mock change; exercises the implement → test flow.",
            files=[ChangedFile(path=MOCK_MODULE, action="create", content=_MOCK_CODE)],
            tests=[ChangedFile(path=MOCK_TEST, action="create", content=_MOCK_TESTS)],
            risks=["Produced by the deterministic mock provider."],
        ),
    )


def _qa(request: ModelRequest) -> ModelResponse:
    from agent_hq.orchestration.schemas import QaReport

    results = _tool_results(request)
    runs = [r for r in results if "exit_code" in r]
    if not runs:
        call = ToolCall("run-1", "sandbox.run_tests", {"repository": request.hints["repository"]})
        return _respond(request, tool_calls=[call])
    run = runs[-1]
    summary = run.get("summary") or {}
    passed = (
        run.get("exit_code") == 0
        and not run.get("timed_out")
        and summary.get("failed", 0) == 0
        and summary.get("passed", 0) > 0
    )
    failures = [] if passed else [f"sandbox exit code {run.get('exit_code')}: {summary}"]
    return _respond(
        request,
        QaReport(
            verdict="ready" if passed else "not_ready",
            summary=f"Sandbox run: {summary or 'no summary'}",
            failures=failures,
        ),
    )


def default_mock_responder(request: ModelRequest) -> ModelResponse | None:
    if request.purpose == "cio.chat":
        from agent_hq.orchestration.mock_chat import respond_chat

        return respond_chat(request)
    if request.purpose == "cio.analyze":
        text = str(request.hints.get("request", ""))
        allowed = {r.lower() for r in request.hints.get("allowed_repos", [])}
        mentioned = _REPO_IN_TEXT.findall(text)
        # Prefer an authorized repository; "CI/CD" also looks like owner/name.
        repository = next((m for m in mentioned if m.lower() in allowed), None) or next(
            iter(mentioned), None
        )
        workflow = _classify(text)
        return _respond(
            request,
            Requirements(
                summary=text[:300],
                workflow=workflow,
                repository=repository,
                objectives=(
                    ["Assess CI/CD security, reliability and maintainability"]
                    if workflow == "cicd_review"
                    else [text[:200]]
                ),
            ),
        )
    if request.purpose == "swe.implement":
        return _implement(request)
    if request.purpose == "qa.test_plan":
        from agent_hq.orchestration.schemas import TestCase, TestPlan

        criteria = list(request.hints.get("acceptance_criteria") or ["The change works"])
        return _respond(
            request,
            TestPlan(
                cases=[
                    TestCase(name=f"case_{i + 1}", description=c, expected="passes")
                    for i, c in enumerate(criteria)
                ]
            ),
        )
    if request.purpose == "qa.run_tests":
        return _qa(request)
    if request.purpose == "devops.analyze":
        results = _tool_results(request)
        if not results:
            repo = request.hints["repository"]
            calls = [
                ToolCall(f"read-{i}", "github.read_file", {"repository": repo, "path": path})
                for i, path in enumerate(request.hints.get("candidates", [])[:8])
            ]
            calls.append(ToolCall("runs", "github.list_workflow_runs", {"repository": repo}))
            return _respond(request, tool_calls=calls)
        files = [r for r in results if "content" in r and "path" in r]
        return _respond(request, _analyze_files(files))
    if request.purpose == "cio.summary":
        return _respond(request, _summary(request.hints))
    return None


def _summary(hints: dict[str, Any]) -> OutcomeSummary:
    final = hints.get("final", {})
    repo = hints.get("repository")
    if "recommendation" in final:
        rec = final["recommendation"]
        return OutcomeSummary(
            outcome=(
                f"Reviewed {len(rec['files_inspected'])} CI/CD files in {repo}: "
                f"{len(rec['findings'])} findings, {len(rec['recommendations'])} recommendations."
            ),
            risks=[
                f["description"] for f in rec["findings"] if f["severity"] in ("high", "critical")
            ][:5],
            next_steps=[r["title"] for r in rec["recommendations"]][:5],
        )
    changeset = final.get("changeset", {})
    qa = final.get("qa", {})
    files = [f["path"] for f in [*changeset.get("files", []), *changeset.get("tests", [])]]
    return OutcomeSummary(
        outcome=(
            f"Proposed a change to {repo} ({len(files)} files). "
            f"QA verdict: {qa.get('report', {}).get('verdict')}."
        ),
        risks=list(changeset.get("risks", [])),
        next_steps=["Review the proposed pull request", "Merge after human code review"],
    )
