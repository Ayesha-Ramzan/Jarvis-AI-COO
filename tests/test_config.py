"""F-6: database credentials must come from the environment.

These tests fail if hardcoded default credentials are reintroduced into
app/config.py.
"""

from __future__ import annotations

import pytest

from app.config import Settings


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("DATABASE_URL", "POSTGRES_USER", "POSTGRES_PASSWORD"):
        monkeypatch.delenv(var, raising=False)


def test_no_hardcoded_database_credentials(clean_env) -> None:
    settings = Settings()
    assert settings.postgres_user == ""
    assert settings.postgres_password == ""


def test_resolved_url_requires_credentials(clean_env) -> None:
    settings = Settings()
    with pytest.raises(RuntimeError, match="Database credentials are required"):
        _ = settings.resolved_database_url


def test_database_url_override_wins(clean_env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./override.db")
    settings = Settings()
    assert settings.resolved_database_url == "sqlite+aiosqlite:///./override.db"


def test_individual_parts_build_url(clean_env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_USER", "svc")
    monkeypatch.setenv("POSTGRES_PASSWORD", "s3cret-from-env")
    settings = Settings()
    assert (
        settings.resolved_database_url
        == "postgresql+asyncpg://svc:s3cret-from-env@localhost:5432/jarvis"
    )
