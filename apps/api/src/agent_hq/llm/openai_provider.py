"""OpenAI adapter (Chat Completions with tools and JSON-schema structured output)."""

import json
from typing import Any

import openai
from pydantic import SecretStr, ValidationError

from agent_hq.llm.base import (
    ChatMessage,
    ModelConfigError,
    ModelRequest,
    ModelResponse,
    ProviderError,
    ToolCall,
    Usage,
)

# OpenAI function names allow [a-zA-Z0-9_-]; internal tool names use dots.
_SEP = "__"


def _to_wire_name(name: str) -> str:
    return name.replace(".", _SEP)


def _from_wire_name(name: str) -> str:
    return name.replace(_SEP, ".")


def _message(m: ChatMessage) -> dict[str, Any]:
    if m.role == "tool":
        return {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content}
    msg: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.tool_calls:
        msg["tool_calls"] = [
            {
                "id": c.id,
                "type": "function",
                "function": {"name": _to_wire_name(c.name), "arguments": json.dumps(c.arguments)},
            }
            for c in m.tool_calls
        ]
    return msg


# 429 codes that no retry can fix: the account must be topped up or reconfigured.
_PERMANENT_429 = frozenset({"insufficient_quota", "credit_balance_exhausted", "billing_not_active"})


def classify_error(error: Exception) -> Exception:
    """Map SDK errors to retryable (ProviderError) or permanent (ModelConfigError)."""
    if isinstance(error, openai.RateLimitError):
        code = str(getattr(error, "code", "") or "")
        if code in _PERMANENT_429 or "credit" in str(error).lower():
            return ModelConfigError(f"OpenAI account cannot serve requests ({code or 'quota'})")
        return ProviderError("openai rate limited")
    if isinstance(error, (openai.APIConnectionError, openai.InternalServerError)):
        return ProviderError(f"openai transient error: {type(error).__name__}")
    if isinstance(error, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return ModelConfigError("OpenAI rejected the API key or its permissions")
    if isinstance(error, (openai.NotFoundError, openai.BadRequestError)):
        return ModelConfigError(f"OpenAI rejected the request: {type(error).__name__}")
    return ProviderError(f"openai error: {type(error).__name__}")


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: SecretStr, *, timeout: float) -> None:
        self._client = openai.AsyncOpenAI(
            api_key=api_key.get_secret_value(), timeout=timeout, max_retries=2
        )

    async def complete(self, request: ModelRequest) -> ModelResponse:
        kwargs: dict[str, Any] = {
            "model": request.model,
            "messages": [_message(m) for m in request.messages],
        }
        if request.tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": _to_wire_name(t.name),
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in request.tools
            ]
        if request.output_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": request.output_schema.__name__,
                    "schema": request.output_schema.model_json_schema(),
                    "strict": False,
                },
            }
        try:
            completion = await self._client.chat.completions.create(**kwargs)
        except openai.OpenAIError as e:
            raise classify_error(e) from e

        choice = completion.choices[0].message
        tool_calls = []
        for call in choice.tool_calls or []:
            fn = getattr(call, "function", None)
            if fn is None:
                continue
            try:
                arguments = json.loads(fn.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {"_invalid_json": fn.arguments}
            tool_calls.append(
                ToolCall(id=call.id, name=_from_wire_name(fn.name), arguments=arguments)
            )
        content = choice.content or ""
        parsed = None
        if request.output_schema is not None and content and not tool_calls:
            try:
                parsed = request.output_schema.model_validate_json(content)
            except ValidationError:
                parsed = None  # the caller treats a missing parse as a model error
        usage = completion.usage
        return ModelResponse(
            content=content,
            tool_calls=tool_calls,
            parsed=parsed,
            usage=Usage(
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
            ),
        )
