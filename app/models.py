"""SQLAlchemy models for the organization-scoped skill registry.

Domain rules encoded at the schema level:
  * ``Skill.status`` is constrained to the draft -> active -> disabled
    lifecycle states.
  * ``SkillVersion`` rows are append-only snapshots: no update/delete paths
    exist in the service layer, and each (skill_id, version_number) pair is
    unique so a version is an immutable, addressable artifact.
  * Every tenant-owned row carries ``organization_id`` as its canonical
    ownership key.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_uuid() -> str:
    return str(uuid.uuid4())


class SkillStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    DISABLED = "disabled"


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    skills: Mapped[list["Skill"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )


class Membership(Base):
    """Organization membership with a role: the server-side source of truth
    for who holds which role in which organization.

    Composite primary key on (organization_id, user_id) makes membership a
    single, enforceable fact: the request headers may *identify* the caller,
    but the role used for every authorization decision is read from this row,
    never from a self-declared header.
    """

    __tablename__ = "memberships"
    __table_args__ = (
        CheckConstraint("role IN ('owner', 'member')", name="ck_memberships_role"),
        Index("ix_memberships_user", "user_id"),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    organization: Mapped[Organization] = relationship(back_populates="memberships")


class Skill(Base):
    __tablename__ = "skills"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'active', 'disabled')", name="ck_skills_status"
        ),
        Index("ix_skills_org_status", "organization_id", "status"),
        Index("ix_skills_org_department", "organization_id", "department"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    department: Mapped[str] = mapped_column(String(128), nullable=False)
    # Draft working copy of the skill definition. The authoritative runtime
    # definition is always the active SkillVersion snapshot.
    content: Mapped[str] = mapped_column(Text, nullable=False)
    requested_tools: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Backed by the SkillStatus enum at the database level (native ENUM on
    # PostgreSQL, VARCHAR + CHECK on SQLite); transitions are governed by
    # the explicit map in app.lifecycle, never set to arbitrary values.
    # values_callable persists the enum *values* ('draft', ...) rather
    # than the member names ('DRAFT', ...) and matches the labels created
    # by migration 0004 on PostgreSQL.
    status: Mapped[SkillStatus] = mapped_column(
        Enum(
            SkillStatus,
            name="skillstatus",
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
        default=SkillStatus.DRAFT,
    )
    # Points at the currently activated SkillVersion snapshot.
    active_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    organization: Mapped[Organization] = relationship(back_populates="skills")
    versions: Mapped[list["SkillVersion"]] = relationship(
        back_populates="skill",
        cascade="all, delete-orphan",
        order_by="SkillVersion.version_number",
        lazy="selectin",
    )


class SkillVersion(Base):
    __tablename__ = "skill_versions"
    __table_args__ = (
        UniqueConstraint("skill_id", "version_number", name="uq_skill_versions_number"),
        Index("ix_skill_versions_skill", "skill_id"),
        Index("ix_skill_versions_org", "organization_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        # Denormalized from the parent skill so that EVERY tenant-scoped
        # table carries the canonical ownership key directly, on top of
        # the join-based isolation filter (defense in depth).
    )
    skill_id: Mapped[str] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    department: Mapped[str] = mapped_column(String(128), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    requested_tools: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    version_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    skill: Mapped[Skill] = relationship(back_populates="versions")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_org_created", "organization_id", "created_at"),
        Index("ix_audit_logs_skill", "skill_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    skill_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    version_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
