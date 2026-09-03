"""Migration revision IDs must fit alembic's version_num VARCHAR(32).

PostgreSQL enforces the length and aborts the whole migration transaction
when a revision ID overflows it (found live on the compose stack: the
38-char ID of the versions-organization-id migration failed with
'value too long for type character varying(32)'). SQLite ignores VARCHAR
lengths, so only a real PostgreSQL run - or this guard - catches it.
"""

from __future__ import annotations

import re
from pathlib import Path

ALEMBIC_VERSIONS = Path(__file__).resolve().parent.parent / "alembic" / "versions"

MAX_REVISION_ID_LENGTH = 32


def test_all_revision_ids_fit_alembic_version_column() -> None:
    revision_ids = []
    for migration_file in sorted(ALEMBIC_VERSIONS.glob("*.py")):
        match = re.search(
            r'^revision:\s*str\s*=\s*"([^"]+)"',
            migration_file.read_text(),
            re.MULTILINE,
        )
        assert match is not None, f"{migration_file.name} has no revision id"
        revision_ids.append(match.group(1))
    assert revision_ids, "no migrations found"
    for revision_id in revision_ids:
        assert len(revision_id) <= MAX_REVISION_ID_LENGTH, (
            f"revision id {revision_id!r} is {len(revision_id)} chars; "
            f"alembic version_num is VARCHAR({MAX_REVISION_ID_LENGTH})"
        )


def test_migration_chain_is_linear_and_grounded() -> None:
    revisions = {}
    for migration_file in sorted(ALEMBIC_VERSIONS.glob("*.py")):
        text = migration_file.read_text()
        rev = re.search(r'^revision:\s*str\s*=\s*"([^"]+)"', text, re.MULTILINE)
        down = re.search(
            r'^down_revision:\s*Union\[str,\s*None\]\s*=\s*(?:"([^"]+)"|None)',
            text,
            re.MULTILINE,
        )
        assert rev is not None, f"{migration_file.name} has no revision id"
        revisions[rev.group(1)] = down.group(1) if down else None

    roots = [r for r, d in revisions.items() if d is None]
    assert roots == ["0001_initial_schema"], f"expected one root, got {roots}"

    # walk the chain from the root to the head; every down_revision must
    # resolve. revisions maps revision -> its predecessor, so invert it.
    next_by_predecessor = {down: rev for rev, down in revisions.items()}
    seen = set()
    current: str | None = "0001_initial_schema"
    while current is not None:
        assert current not in seen, "migration chain has a cycle"
        seen.add(current)
        current = next_by_predecessor.get(current)
    assert seen == set(revisions), "down_revision references a missing migration"
