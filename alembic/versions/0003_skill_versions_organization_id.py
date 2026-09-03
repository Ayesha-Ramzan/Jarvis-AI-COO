"""Add denormalized organization_id to skill_versions.

Every tenant-scoped table must carry the canonical ownership key
directly. The column is populated from the parent skill (defense in depth
on top of the join-based isolation filter) and backfilled for existing
rows before NOT NULL is enforced.

Revision ID: 0003_skill_versions_organization_id
Revises: 0002_organization_memberships
Create Date: 2026-09-04

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_skill_versions_organization_id"
down_revision: Union[str, None] = "0002_organization_memberships"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "skill_versions",
        sa.Column("organization_id", sa.String(length=36), nullable=True),
    )
    op.execute(
        "UPDATE skill_versions SET organization_id = "
        "(SELECT organization_id FROM skills WHERE skills.id = skill_versions.skill_id) "
        "WHERE organization_id IS NULL"
    )

    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("skill_versions") as batch_op:
            batch_op.alter_column(
                "organization_id",
                existing_type=sa.String(length=36),
                nullable=False,
            )
    else:
        op.alter_column(
            "skill_versions",
            "organization_id",
            existing_type=sa.String(length=36),
            nullable=False,
        )

    op.create_index("ix_skill_versions_org", "skill_versions", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_skill_versions_org", table_name="skill_versions")
    op.drop_column("skill_versions", "organization_id")
