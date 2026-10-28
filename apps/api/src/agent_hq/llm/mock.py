"""Deterministic provider for tests and offline development. Never calls the network."""

from collections.abc import Callable

from agent_hq.llm.base import ModelRequest, ModelResponse, Usage

Responder = Callable[[ModelRequest], ModelResponse | None]


def estimate_usage(request: ModelRequest, response_text: str) -> Usage:
    prompt_chars = sum(len(m.content) for m in request.messages)
    return Usage(input_tokens=prompt_chars // 4, output_tokens=len(response_text) // 4)


class MockProvider:
    """Answers with `script` when it returns a response, otherwise with `default`.

    Tests pass a script to simulate specific model behaviour (malicious tool calls, crashes);
    the default responder produces plausible, deterministic output for local runs.
    """

    name = "mock"

    def __init__(self, default: Responder, script: Responder | None = None) -> None:
        self._default = default
        self._script = script
        self.calls: list[ModelRequest] = []

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.calls.append(request)
        response = self._script(request) if self._script else None
        if response is None:
            response = self._default(request)
        if response is None:
            raise RuntimeError(f"mock provider has no response for purpose {request.purpose!r}")
        return response
