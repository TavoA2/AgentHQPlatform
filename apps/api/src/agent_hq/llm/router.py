"""Resolves agent model profiles to concrete providers (ADR-0005, ADR-0010)."""

from dataclasses import dataclass
from decimal import Decimal

from agent_hq.config import Settings
from agent_hq.llm.base import ChatModelProvider, ModelConfigError, Usage, parse_model_ref
from agent_hq.llm.mock import MockProvider, Responder
from agent_hq.llm.openai_provider import OpenAIProvider


@dataclass(frozen=True)
class ResolvedModel:
    provider: ChatModelProvider
    provider_name: str
    model: str


class ModelRouter:
    def __init__(self, settings: Settings, *, mock_default: Responder) -> None:
        self._settings = settings
        self._providers: dict[str, ChatModelProvider] = {}
        self._mock_default = mock_default

    def register(self, name: str, provider: ChatModelProvider) -> None:
        """Override a provider (tests inject scripted mocks here)."""
        self._providers[name] = provider

    def _provider(self, name: str) -> ChatModelProvider:
        if name not in self._providers:
            if name == "mock":
                self._providers[name] = MockProvider(self._mock_default)
            elif name == "openai":
                key = self._settings.openai_api_key
                if key is None or not key.get_secret_value():
                    raise ModelConfigError("OPENAI_API_KEY is not configured")
                self._providers[name] = OpenAIProvider(
                    key, timeout=self._settings.model_timeout_seconds
                )
            else:
                raise ModelConfigError(f"unknown provider {name!r}")
        return self._providers[name]

    def resolve(self, *, agent_key: str, profile: str, task_override: str | None) -> ResolvedModel:
        """Precedence: task override > per-agent override > profile mapping."""
        if task_override:
            ref = task_override
        elif agent_key in self._settings.model_overrides:
            ref = self._settings.model_overrides[agent_key]
        elif profile == "reasoning":
            ref = self._settings.model_profile_reasoning
        elif profile == "fast":
            ref = self._settings.model_profile_fast
        else:
            raise ModelConfigError(f"unknown model profile {profile!r}")
        provider_name, model = parse_model_ref(ref)
        return ResolvedModel(self._provider(provider_name), provider_name, model)

    def cost(self, model: str, usage: Usage) -> Decimal | None:
        prices = self._settings.model_pricing.get(model)
        if prices is None:
            return None
        per_input, per_output = (Decimal(str(p)) for p in prices)
        million = Decimal(1_000_000)
        return (usage.input_tokens * per_input + usage.output_tokens * per_output) / million
