"""Contracts shared by the sandbox runner service and its client (ADR-0011)."""

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, field_validator

MAX_FILES = 200
MAX_TOTAL_BYTES = 1_000_000
MAX_TIMEOUT_SECONDS = 300
MAX_OUTPUT_BYTES = 16_000

_SAFE_PATH = re.compile(r"^[A-Za-z0-9_.\-/]+$")

TemplateId = Literal["python-pytest"]


@dataclass(frozen=True)
class Template:
    image: str
    command: tuple[str, ...]


def template_for(template_id: str, *, python_image: str) -> Template:
    """Allowlisted templates: an image plus a fixed command. No free-form commands exist."""
    if template_id == "python-pytest":
        return Template(
            image=python_image,
            command=("python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--color=no"),
        )
    raise ValueError(f"unknown sandbox template {template_id!r}")


def validate_workspace_path(path: str) -> str:
    parts = path.split("/")
    if (
        not path
        or len(path) > 300
        or path.startswith("/")
        or not _SAFE_PATH.match(path)
        or any(p in ("", ".", "..") for p in parts)
    ):
        raise ValueError(f"invalid workspace path {path!r}")
    return path


class RunRequest(BaseModel):
    template: TemplateId
    files: dict[str, str] = Field(description="Workspace files: relative path -> text content")
    timeout_seconds: int = Field(default=120, ge=5, le=MAX_TIMEOUT_SECONDS)

    @field_validator("files")
    @classmethod
    def _limits(cls, files: dict[str, str]) -> dict[str, str]:
        if not files:
            raise ValueError("workspace is empty")
        if len(files) > MAX_FILES:
            raise ValueError(f"too many files (max {MAX_FILES})")
        total = sum(len(c.encode()) for c in files.values())
        if total > MAX_TOTAL_BYTES:
            raise ValueError(f"workspace too large (max {MAX_TOTAL_BYTES} bytes)")
        for path in files:
            validate_workspace_path(path)
        return files


class TestSummary(BaseModel):
    passed: int = 0
    failed: int = 0
    errors: int = 0


class RunResult(BaseModel):
    exit_code: int | None
    timed_out: bool
    duration_ms: int
    output: str = Field(description="Tail of combined stdout/stderr, redacted")
    summary: TestSummary | None = None

    @property
    def succeeded(self) -> bool:
        return (
            not self.timed_out
            and self.exit_code == 0
            and self.summary is not None
            and self.summary.failed == 0
            and self.summary.errors == 0
            and self.summary.passed > 0
        )


_COUNT = re.compile(r"(\d+) (passed|failed|errors?)")


def parse_pytest_summary(output: str) -> TestSummary | None:
    counts = {"passed": 0, "failed": 0, "errors": 0}
    found = False
    for number, label in _COUNT.findall(output):
        key = "errors" if label.startswith("error") else label
        counts[key] = int(number)
        found = True
    return TestSummary(**counts) if found else None
