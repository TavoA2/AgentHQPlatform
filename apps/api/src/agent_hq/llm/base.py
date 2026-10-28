"""Provider-neutral model interface (ADR-0005)."""

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel

PROVIDERS = frozenset({"mock", "openai"})


class ModelConfigError(ValueError):
    pass


class ProviderError(RuntimeError):
    """Transient provider failure (network, rate limit, 5xx). Safe to retry."""


def parse_model_ref(ref: str) -> tuple[str, str]:
    provider, sep, model = ref.partition(":")
    if not sep or not model or provider not in PROVIDERS:
        raise ModelConfigError(
            f"invalid model reference {ref!r}; expected '<provider>:<model>' with provider in "
            f"{sorted(PROVIDERS)}"
        )
    return provider, model


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None


@dataclass(frozen=True)
class ToolSchema:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class ModelRequest:
    purpose: str  # e.g. "cio.analyze"; used for logging and deterministic mocks
    model: str
    messages: list[ChatMessage]
    tools: list[ToolSchema] = field(default_factory=list)
    output_schema: type[BaseModel] | None = None
    # Structured, non-prompt context for deterministic providers (the mock). Real providers
    # ignore it; everything a real model needs must be in `messages`.
    hints: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelResponse:
    content: str
    tool_calls: list[ToolCall]
    parsed: BaseModel | None
    usage: Usage


class ChatModelProvider(Protocol):
    name: str

    async def complete(self, request: ModelRequest) -> ModelResponse: ...
