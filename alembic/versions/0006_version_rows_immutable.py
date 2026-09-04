"""Enforce skill_versions immutability at the database level (PostgreSQL).

The application layer already has no UPDATE/DELETE path for version rows;
this trigger closes the gap for any future code path, manual SQL, or bug:
on PostgreSQL, UPDATE and DELETE against skill_versions raise an exception
(same transaction semantics as before - nothing is partially applied).

SQLite (test database) has no trigger equivalent wired here; immutability
there remains enforced at the application layer, as documented in ADR-2.

Revision ID: 0006_version_rows_immutable
Revises: 0005_tool_approvals
Create Date: 2026-09-04

"""

from typing import Sequence, Union

from alembic import op

revision: str = "0006_version_rows_immutable"
down_revision: Union[str, None] = "0005_tool_approvals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return  # trigger is PostgreSQL-only; see docstring
    op.execute("""
        CREATE OR REPLACE FUNCTION forbid_skill_version_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'skill_versions rows are immutable: % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER skill_versions_immutable
        BEFORE UPDATE OR DELETE ON skill_versions
        FOR EACH ROW EXECUTE FUNCTION forbid_skill_version_mutation();
    """)


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP TRIGGER IF EXISTS skill_versions_immutable ON skill_versions;")
    op.execute("DROP FUNCTION IF EXISTS forbid_skill_version_mutation();")
