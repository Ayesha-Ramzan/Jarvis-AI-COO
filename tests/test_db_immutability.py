"""Database-level immutability of skill_versions rows.

The PostgreSQL trigger (migration 0006) raises on UPDATE/DELETE so the
guarantee is enforced even outside the application. SQLite has no
trigger, so the test is a no-op pass there - immutability on SQLite is
enforced at the application layer (ADR-2).
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text

POSTGRES = bool(os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql"))


@pytest.mark.skipif(not POSTGRES, reason="DB-level immutability is PostgreSQL-only")
@pytest.mark.asyncio
async def test_postgres_trigger_blocks_update_and_delete(db_session):
    # Build a minimal row directly to test the trigger in isolation.
    from sqlalchemy import text
    from app.database import engine
    from app.models import Organization, Skill, SkillVersion, SkillStatus, new_uuid
    from datetime import datetime, timezone

    org_id = "00000000-0000-0000-0000-000000000001"
    skill_id = new_uuid()
    version_id = new_uuid()

    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO organizations (id, name) VALUES (:i, 't')"),
            {"i": org_id},
        )
        await conn.execute(
            text(
                "INSERT INTO skills (id, organization_id, name, description, "
                "department, content, requested_tools, status, created_by, "
                "created_at, updated_at) "
                "VALUES (:i, :o, 'n', '', 'd', 'c', '[]', 'draft', 'u', now(), now())"
            ),
            {"i": skill_id, "o": org_id},
        )
        await conn.execute(
            text(
                "INSERT INTO skill_versions (id, organization_id, skill_id, "
                "version_number, name, description, department, content, "
                "requested_tools, version_hash, created_by, created_at) "
                "VALUES (:i, :o, :s, 1, 'n', '', 'd', 'c', '[]', 'h', 'u', now())"
            ),
            {"i": version_id, "o": org_id, "s": skill_id},
        )

    async with engine.begin() as conn:
        with pytest.raises(Exception, match="immutable"):
            await conn.execute(
                text("UPDATE skill_versions SET content='mutated' WHERE id=:i"),
                {"i": version_id},
            )

    async with engine.begin() as conn:
        with pytest.raises(Exception, match="immutable"):
            await conn.execute(
                text("DELETE FROM skill_versions WHERE id=:i"), {"i": version_id}
            )

    # Cleanup: drop the trigger temporarily for tidiness, then re-add it.
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE skill_versions DISABLE TRIGGER skill_versions_immutable"))
        await conn.execute(text("DELETE FROM skill_versions WHERE id=:i"), {"i": version_id})
        await conn.execute(text("DELETE FROM skills WHERE id=:i"), {"i": skill_id})
        await conn.execute(text("DELETE FROM organizations WHERE id=:i"), {"i": org_id})
        await conn.execute(text("ALTER TABLE skill_versions ENABLE TRIGGER skill_versions_immutable"))


@pytest.mark.asyncio
async def test_immutability_guarantee_placeholder_on_sqlite():
    """On SQLite the application layer is the contract (ADR-2). This test
    documents that; it always passes."""
    assert True
