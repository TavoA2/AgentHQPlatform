"""Deterministic default answers for the mock provider.

They make the full workflow runnable offline with plausible output derived from the real
files the agent read. They are not a substitute for a real model's analysis.
"""

import json
import re
from typing import Any

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


def default_mock_responder(request: ModelRequest) -> ModelResponse | None:
    if request.purpose == "cio.analyze":
        text = str(request.hints.get("request", ""))
        match = _REPO_IN_TEXT.search(text)
        return _respond(
            request,
            Requirements(
                summary=text[:300],
                repository=match.group(1) if match else None,
                objectives=["Assess CI/CD security, reliability and maintainability"],
            ),
        )
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
        hints = request.hints
        return _respond(
            request,
            OutcomeSummary(
                outcome=(
                    f"Reviewed {hints.get('files', 0)} CI/CD files in {hints.get('repository')}: "
                    f"{hints.get('findings', 0)} findings, "
                    f"{hints.get('recommendations', 0)} recommendations."
                ),
                risks=list(hints.get("top_risks", [])),
                next_steps=list(hints.get("recommendation_titles", [])),
            ),
        )
    return None
