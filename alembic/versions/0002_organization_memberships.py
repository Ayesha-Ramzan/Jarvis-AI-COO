"""Add organization memberships with server-side roles.

Memberships are the source of truth for role-based authorization: the
request headers identify the caller, but the role used for every
activation/disable decision is read from this table.

Enforces at the database level:
  * composite primary key (organization_id, user_id) - one membership row
    per user per organization;
  * role restricted to the owner/member vocabulary.

Revision ID: 0002_memberships
Revises: 0001_initial_schema
Create Date: 2026-09-04

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_memberships"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "memberships",
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "role IN ('owner', 'member')", name="ck_memberships_role"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("organization_id", "user_id"),
    )
    op.create_index("ix_memberships_user", "memberships", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_memberships_user", table_name="memberships")
    op.drop_table("memberships")
