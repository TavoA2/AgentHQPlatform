from typing import Any

import openai
import pytest

from agent_hq.llm.base import ModelConfigError, ProviderError
from agent_hq.llm.openai_provider import classify_error


def _error(cls: type[openai.APIStatusError], code: str | None, message: str = "x") -> Any:
    # Bypass the SDK constructor (it requires a real HTTP response object).
    err = cls.__new__(cls)
    Exception.__init__(err, message)
    err.code = code
    return err


@pytest.mark.parametrize("code", ["insufficient_quota", "credit_balance_exhausted"])
def test_exhausted_credit_is_permanent(code: str) -> None:
    assert isinstance(classify_error(_error(openai.RateLimitError, code)), ModelConfigError)


def test_plain_rate_limit_is_retryable() -> None:
    assert isinstance(
        classify_error(_error(openai.RateLimitError, "rate_limit_exceeded")), ProviderError
    )


def test_bad_key_is_permanent() -> None:
    assert isinstance(classify_error(_error(openai.AuthenticationError, None)), ModelConfigError)
