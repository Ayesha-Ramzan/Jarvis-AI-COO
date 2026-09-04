"""Add explicit per-version tool approvals.

A skill requesting a tool never grants it automatically: this table holds
the separate, deliberate owner approval for one tool on one immutable
version. One row per (version_id, tool), which makes re-approval a
natural idempotent no-op, and every approval is audit-logged.

Revision ID: 0005_tool_approvals
Revises: 0004_status_enum
Create Date: 2026-09-04

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_tool_approvals"
down_revision: Union[str, None] = "0004_status_enum"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tool_approvals",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "skill_id",
            sa.String(length=36),
            sa.ForeignKey("skills.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "version_id",
            sa.String(length=36),
            sa.ForeignKey("skill_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool", sa.String(length=128), nullable=False),
        sa.Column("approved_by", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.UniqueConstraint("version_id", "tool", name="uq_tool_approvals_tool"),
    )
    op.create_index(
        "ix_tool_approvals_org", "tool_approvals", ["organization_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_tool_approvals_org", table_name="tool_approvals")
    op.drop_table("tool_approvals")
