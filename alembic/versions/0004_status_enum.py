"""Back skills.status with the native lifecycle enum.

Replaces the bare VARCHAR(32) + CHECK constraint with a real enum type so
the state machine is enforced by the database itself, alongside the
explicit transition map in app.lifecycle.

Revision ID: 0004_status_enum
Revises: 0003_skill_versions_organization_id
Create Date: 2026-09-04

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_status_enum"
down_revision: Union[str, None] = "0003_skill_versions_organization_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STATUS_VALUES = ("draft", "active", "disabled")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite has no native ENUM: batch-recreate the table with the
        # enum type (renders as VARCHAR + keeps the CHECK constraint).
        with op.batch_alter_table("skills") as batch_op:
            batch_op.alter_column(
                "status",
                existing_type=sa.String(length=32),
                type_=sa.Enum(*STATUS_VALUES, name="skillstatus"),
                existing_nullable=False,
            )
    else:
        op.execute(
            "CREATE TYPE skillstatus AS ENUM ('draft', 'active', 'disabled')"
        )
        op.alter_column(
            "skills",
            "status",
            existing_type=sa.String(length=32),
            type_=postgresql.ENUM(
                *STATUS_VALUES, name="skillstatus", create_type=False
            ),
            existing_nullable=False,
            postgresql_using="status::skillstatus",
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("skills") as batch_op:
            batch_op.alter_column(
                "status",
                existing_type=sa.Enum(*STATUS_VALUES, name="skillstatus"),
                type_=sa.String(length=32),
                existing_nullable=False,
            )
    else:
        op.alter_column(
            "skills",
            "status",
            existing_type=postgresql.ENUM(
                *STATUS_VALUES, name="skillstatus", create_type=False
            ),
            type_=sa.String(length=32),
            existing_nullable=False,
            postgresql_using="status::text",
        )
        op.execute("DROP TYPE skillstatus")
