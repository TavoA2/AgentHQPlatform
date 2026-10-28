"""Environment-based configuration. The only place that reads environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, SecretStr
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
        default=PostgresDsn("postgresql+psycopg://agent_hq:agent_hq@localhost:5432/agent_hq")
    )
    session_secret: SecretStr = SecretStr("")


@lru_cache
def get_settings() -> Settings:
    return Settings()
