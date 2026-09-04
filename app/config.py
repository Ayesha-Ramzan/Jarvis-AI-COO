"""Application settings managed via pydantic-settings.

All configuration is sourced from environment variables (with an optional
``.env`` file). No secret value is hardcoded anywhere in the repository.
"""

from __future__ import annotations

import os

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# Hermetic tests: when the process runs with ENVIRONMENT=test (pytest.ini and
# tests/conftest.py both guarantee this before app modules import), Settings
# must not read an ambient .env file. Otherwise a developer who follows the
# README's "cp .env.example .env" quick start leaves real values (e.g.
# POSTGRES_USER=jarvis) in the working directory, and credential-isolation
# tests would fail depending on whatever happens to sit in the repo root -
# the suite would not be hermetic. In every non-test environment the .env
# file is honored exactly as documented.
_ENV_FILE = None if os.environ.get("ENVIRONMENT", "").lower() == "test" else ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
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

    # Credentials have NO defaults: they must come from the environment
    # (or DATABASE_URL). resolved_database_url raises if they are missing.
    postgres_user: str = ""
    postgres_password: str = ""
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "jarvis"

    # Idempotently upserts the two evaluation fixture organizations on startup.
    seed_fixture_organizations: bool = True

    # HMAC key for bearer-token auth (Authorization: Bearer). No default:
    # when unset, token issuance is disabled and bearer tokens are refused.
    auth_signing_key: str = ""

    # Simple in-process sliding-window rate limit per authenticated identity
    # (requests per minute). 0 disables limiting (tests disable it).
    rate_limit_per_minute: int = 120

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        if not self.postgres_user or not self.postgres_password:
            raise RuntimeError(
                "Database credentials are required: set DATABASE_URL, or set "
                "both POSTGRES_USER and POSTGRES_PASSWORD in the environment. "
                "No hardcoded defaults exist by design."
            )
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
