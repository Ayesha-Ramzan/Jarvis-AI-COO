"""Application settings managed via pydantic-settings.

All configuration is sourced from environment variables (with an optional
``.env`` file). No secret value is hardcoded anywhere in the repository.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: str = "development"
    debug: bool = False

    app_name: str = "JARVIS AI COO - Organization-Scoped Skill Registry"
    app_version: str = "1.0.0"
    api_v1_prefix: str = "/api/v1"

    # When set (e.g. in Docker or CI), this URL wins over the individual parts.
    database_url: str = ""

    postgres_user: str = "jarvis"
    postgres_password: str = "jarvis"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "jarvis"

    # Idempotently upserts the two evaluation fixture organizations on startup.
    seed_fixture_organizations: bool = True

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def is_test(self) -> bool:
        return self.environment.lower() == "test"


@lru_cache
def get_settings() -> Settings:
    return Settings()
