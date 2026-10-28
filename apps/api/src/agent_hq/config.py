"""Environment-based configuration. The only place that reads environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENT_HQ_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["local", "test", "staging", "production"] = "local"
    brand_name: str = "Veltrix Labs"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    database_url: PostgresDsn = Field(
        default=PostgresDsn("postgresql+psycopg://agent_hq:agent_hq@127.0.0.1:5432/agent_hq")
    )

    # --- Auth (ADR-0007) ---
    session_secret: SecretStr = SecretStr("")
    allowed_origins: list[str] = ["http://localhost:3000"]
    session_idle_minutes: int = 12 * 60
    session_absolute_hours: int = 7 * 24

    # --- Model providers (ADR-0005, ADR-0010) ---
    # Profiles map to "provider:model". The default is the deterministic mock provider.
    model_profile_reasoning: str = "mock:mock-reasoning"
    model_profile_fast: str = "mock:mock-fast"
    # Per-agent overrides, e.g. {"devops": "openai:<model>"}.
    model_overrides: dict[str, str] = {}
    # USD per 1M tokens: {"<model>": [input, output]}. Unknown models record no cost.
    model_pricing: dict[str, tuple[float, float]] = {}
    model_timeout_seconds: float = 120
    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("AGENT_HQ_OPENAI_API_KEY", "OPENAI_API_KEY"),
    )

    # --- Loop guards (not budgets; ADR-0010) ---
    agent_max_steps: int = 12
    graph_recursion_limit: int = 50

    # --- GitHub, read-only (ADR-0008) ---
    github_token: SecretStr | None = None
    github_api_url: str = "https://api.github.com"

    # --- Approvals (ADR-0006) ---
    approval_ttl_hours: int = 24

    # --- Worker (ADR-0003) ---
    worker_concurrency: int = 2
    worker_poll_seconds: float = 1.0
    job_lease_seconds: int = 300
    job_max_attempts: int = 3

    @property
    def psycopg_dsn(self) -> str:
        """Plain libpq URL for psycopg/LangGraph (without the SQLAlchemy driver suffix)."""
        return str(self.database_url).replace("postgresql+psycopg://", "postgresql://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
