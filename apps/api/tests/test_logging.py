import json
import logging

import pytest

from agent_hq.logging import REDACTED, JsonFormatter, redact, redact_text


@pytest.mark.parametrize(
    "secret",
    [
        "sk-proj-abcdefghijklmnopqrstuvwxyz123456",
        "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        "github_pat_11ABCDEFG0123456789_abcdefghijklmnop",
        "AKIAABCDEFGHIJKLMNOP",
    ],
)
def test_known_token_shapes_are_redacted(secret: str) -> None:
    out = redact_text(f"calling provider with {secret} now")
    assert secret not in out
    assert REDACTED in out


def test_key_value_pairs_are_redacted() -> None:
    assert redact_text("password=hunter2 user=bob") == f"password={REDACTED} user=bob"
    assert "abc.def.ghi" not in redact_text("Authorization: Bearer abc.def.ghi.jkl")


def test_sensitive_keys_are_redacted_recursively() -> None:
    data = {"user": "bob", "nested": {"api_key": "x", "items": [{"token": "y"}]}}
    assert redact(data) == {
        "user": "bob",
        "nested": {"api_key": REDACTED, "items": [{"token": REDACTED}]},
    }


def test_formatter_emits_redacted_json() -> None:
    record = logging.makeLogRecord(
        {"name": "t", "levelname": "INFO", "msg": "key sk-abcdefghijklmnopqrstu", "args": ()}
    )
    record.authorization = "Bearer secret-value-123"
    record.task_id = "t-1"
    line = json.loads(JsonFormatter().format(record))
    assert line["msg"] == f"key {REDACTED}"
    assert line["authorization"] == REDACTED
    assert line["task_id"] == "t-1"
