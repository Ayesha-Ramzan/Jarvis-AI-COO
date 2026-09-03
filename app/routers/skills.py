"""Skill registry endpoints, all strictly organization-scoped.

Lifecycle rules enforced here (and mirrored by DB constraints):

  * draft  -> owner activates (snapshots an immutable SkillVersion)
  * active -> immutable; any change must be a NEW SkillVersion, then that
              version may be activated to become the runtime definition
  * active -> owner disables (terminal state; excluded from runtime)
  * every real state transition writes an audit row carrying the
    organization, actor, event, timestamp and version hash
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.audit import record_audit
from app.database import get_db
from app.dependencies import get_tenant_context, require_owner
from app.lifecycle import can_transition
from app.models import AuditLog, Skill, SkillStatus, SkillVersion
from app.schemas import (
    AuditLogOut,
    DepartmentSkillOut,
    SkillActivateIn,
    SkillDetailOut,
    SkillDraftCreateIn,
    SkillDraftUpdateIn,
    SkillStatusFilter,
    SkillSummaryOut,
    SkillVersionCreateIn,
    SkillVersionOut,
)
from app.tenant import TenantContext

router = APIRouter(tags=["skills"])


def compute_version_hash(payload: dict[str, Any]) -> str:
    """Deterministic SHA-256 over the canonical JSON of a version snapshot."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _get_skill_or_404(db: AsyncSession, skill_id: str) -> Skill:
    """Fetch a skill visible to the current tenant or raise 404.

    The global tenant filter in app.database guarantees that a skill owned
    by another organization is invisible here, so a cross-tenant access
    attempt can never observe existence (no existence oracle) and receives
    the same 404 as a truly missing id.
    """
    skill = await db.get(Skill, skill_id)
    if skill is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Skill not found in this organization",
        )
    return skill


async def _get_version_or_404(
    db: AsyncSession, version_id: str, *, skill_id: str
) -> SkillVersion:
    version = await db.get(SkillVersion, version_id)
    if version is None or version.skill_id != skill_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Version not found for this skill",
        )
    return version


def _skill_to_detail(skill: Skill) -> SkillDetailOut:
    return SkillDetailOut(
        id=skill.id,
        organization_id=skill.organization_id,
        name=skill.name,
        description=skill.description,
        department=skill.department,
        requested_tools=list(skill.requested_tools or []),
        status=skill.status,
        active_version_id=skill.active_version_id,
        created_by=skill.created_by,
        created_at=skill.created_at,
        updated_at=skill.updated_at,
        content=skill.content,
        versions=[SkillVersionOut.model_validate(v) for v in skill.versions],
    )


@router.post(
    "",
    response_model=SkillDetailOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a skill draft",
    description=(
        "Creates a new skill in `draft` state for the caller's organization. "
        "Drafts are working copies: they are not visible to runtime department "
        "selection until an owner activates them."
    ),
)
async def create_skill_draft(
    payload: SkillDraftCreateIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    context: Annotated[TenantContext, Depends(get_tenant_context)],
) -> SkillDetailOut:
    skill = Skill(
        organization_id=context.organization_id,
        name=payload.name,
        description=payload.description,
        department=payload.department,
        content=payload.content,
        requested_tools=payload.requested_tools,
        status=SkillStatus.DRAFT,
        created_by=context.user_id,
    )
    db.add(skill)
    await db.flush()
    await record_audit(
        db,
        tenant=context,
        event="skill.draft_created",
        skill_id=skill.id,
        detail={"name": skill.name, "department": skill.department},
    )
    await db.commit()
    await db.refresh(skill)
    return _skill_to_detail(skill)


@router.get(
    "",
    response_model=list[SkillSummaryOut],
    summary="List the organization's skills",
    description=(
        "Returns every skill owned by the caller's organization, newest "
        "first. An optional `status` filter narrows the result."
    ),
)
async def list_skills(
    db: Annotated[AsyncSession, Depends(get_db)],
    context: Annotated[TenantContext, Depends(get_tenant_context)],
    skill_status: Annotated[SkillStatusFilter | None, Query(alias="status")] = None,
) -> list[SkillSummaryOut]:
    stmt = select(Skill).order_by(Skill.created_at.desc())
    if skill_status is not None:
        stmt = stmt.where(Skill.status == skill_status)
    result = await db.execute(stmt)
    skills = result.scalars().unique().all()
    return [SkillSummaryOut.model_validate(s) for s in skills]


@router.get(
    "/departments/{department}/active-skills",
    response_model=list[DepartmentSkillOut],
    summary="Runtime selection: active skills for a department",
    description=(
        "Returns ONLY skills in `active` state for the department, each "
        "bound to its immutable active version snapshot. Drafts and disabled "
        "skills are excluded by construction, so a draft can never load as "
        "active and a disabled skill is never selected at runtime."
    ),
)
async def get_active_skills_for_department(
    department: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    context: Annotated[TenantContext, Depends(get_tenant_context)],
) -> list[DepartmentSkillOut]:
    cleaned_department = department.strip()
    if not cleaned_department:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="department must be a non-empty string",
        )
    stmt = (
        select(Skill)
        .options(selectinload(Skill.versions))
        .where(
            Skill.status == SkillStatus.ACTIVE,
            Skill.department == cleaned_department,
        )
        .order_by(Skill.created_at.asc())
    )
    result = await db.execute(stmt)
    skills = result.scalars().unique().all()

    payload: list[DepartmentSkillOut] = []
    for skill in skills:
        if not skill.active_version_id:
            continue
        active = next(
            (v for v in skill.versions if v.id == skill.active_version_id), None
        )
        if active is None:
            continue
        payload.append(
            DepartmentSkillOut(
                skill_id=skill.id,
                name=skill.name,
                department=skill.department,
                version=SkillVersionOut.model_validate(active),
            )
        )
    return payload


@router.get(
    "/{skill_id}",
    response_model=SkillDetailOut,
    summary="Read one skill together with its versions",
)
async def get_skill(
    skill_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    context: Annotated[TenantContext, Depends(get_tenant_context)],
) -> SkillDetailOut:
    stmt = (
        select(Skill)
        .options(selectinload(Skill.versions))
        .where(Skill.id == skill_id)
    )
    result = await db.execute(stmt)
    skill = result.scalar_one_or_none()
    if skill is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Skill not found in this organization",
        )
    return _skill_to_detail(skill)


@router.patch(
    "/{skill_id}",
    response_model=SkillDetailOut,
    summary="Update a skill draft",
    description=(
        "Only `draft` skills may be edited in place. An `active` skill is "
        "immutable by design: attempting to modify it returns 409 and the "
        "change must instead be expressed as a new immutable SkillVersion."
    ),
)
async def update_skill_draft(
    skill_id: str,
    payload: SkillDraftUpdateIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    context: Annotated[TenantContext, Depends(get_tenant_context)],
) -> SkillDetailOut:
    skill = await _get_skill_or_404(db, skill_id)

    if skill.status == SkillStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "An active skill is immutable. Create a new immutable "
                "version and activate it instead."
            ),
        )
    if skill.status == SkillStatus.DISABLED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A disabled skill is immutable and cannot be updated.",
        )

    changes: dict[str, Any] = {}
    for field in ("name", "description", "department", "content", "requested_tools"):
        value = getattr(payload, field)
        if value is not None:
            setattr(skill, field, value)
            changes[field] = value

    if changes:
        await record_audit(
            db,
            tenant=context,
            event="skill.draft_updated",
            skill_id=skill.id,
            detail={"changed_fields": sorted(changes)},
        )
        await db.commit()
    await db.refresh(skill)
    return _skill_to_detail(skill)


@router.post(
    "/{skill_id}/versions",
    response_model=SkillVersionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new immutable version",
    description=(
        "Snapshots a complete replacement definition as a new immutable "
        "SkillVersion. Only `active` skills accept new versions; the new "
        "version does not alter the runtime definition until an owner "
        "explicitly activates it."
    ),
)
async def create_skill_version(
    skill_id: str,
    payload: SkillVersionCreateIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    context: Annotated[TenantContext, Depends(get_tenant_context)],
) -> SkillVersionOut:
    skill = await _get_skill_or_404(db, skill_id)

    if skill.status != SkillStatus.ACTIVE:
        if skill.status == SkillStatus.DISABLED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A disabled skill cannot accept new versions.",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only active skills accept new immutable versions; edit the draft instead.",
        )

    max_version = await db.scalar(
        select(func.max(SkillVersion.version_number)).where(
            SkillVersion.skill_id == skill.id
        )
    )
    version_number = (max_version or 0) + 1
    version_hash = compute_version_hash(
        {
            "organization_id": skill.organization_id,
            "skill_id": skill.id,
            "version_number": version_number,
            "name": payload.name,
            "description": payload.description,
            "department": payload.department,
            "content": payload.content,
            "requested_tools": payload.requested_tools,
        }
    )
    version = SkillVersion(
        organization_id=skill.organization_id,
        skill_id=skill.id,
        version_number=version_number,
        name=payload.name,
        description=payload.description,
        department=payload.department,
        content=payload.content,
        requested_tools=payload.requested_tools,
        version_hash=version_hash,
        created_by=context.user_id,
    )
    db.add(version)
    await db.flush()
    await record_audit(
        db,
        tenant=context,
        event="skill.version_created",
        skill_id=skill.id,
        version_id=version.id,
        version_hash=version_hash,
        detail={"version_number": version_number},
    )
    await db.commit()
    await db.refresh(version)
    return SkillVersionOut.model_validate(version)


@router.post(
    "/{skill_id}/activate",
    response_model=SkillDetailOut,
    summary="Activate an approved version (owner only)",
    description=(
        "Transitions the skill to `active`. Owner role required. From "
        "`draft`, the draft's working copy is snapshotted as immutable "
        "version 1; from `active`, an explicit `version_id` switches the "
        "runtime definition. Re-sending an activation for the already-active "
        "version is a safe, idempotent no-op (200, state unchanged) that is "
        "recorded in the audit trail as `skill.activation_replayed`."
    ),
)
async def activate_skill(
    skill_id: str,
    payload: SkillActivateIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    context: Annotated[TenantContext, Depends(get_tenant_context)],
) -> SkillDetailOut:
    require_owner(context)
    skill = await _get_skill_or_404(db, skill_id)

    # Idempotency: re-activating the currently active version is a no-op
    # for state, but the replay is still recorded in the audit trail so
    # the request remains traceable (spec: idempotent operations must be
    # safe AND auditable).
    if skill.status == SkillStatus.ACTIVE and (
        payload.version_id is None or payload.version_id == skill.active_version_id
    ):
        active_version = (
            await db.get(SkillVersion, skill.active_version_id)
            if skill.active_version_id
            else None
        )
        await record_audit(
            db,
            tenant=context,
            event="skill.activation_replayed",
            skill_id=skill.id,
            version_id=skill.active_version_id,
            version_hash=active_version.version_hash if active_version else None,
            detail={"note": "idempotent replay; no state change"},
        )
        await db.commit()
        await db.refresh(skill)
        return _skill_to_detail(skill)

    # Explicit state machine gate (see app.lifecycle): from the terminal
    # 'disabled' state no transition to active exists.
    if not can_transition(skill.status, SkillStatus.ACTIVE):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A disabled skill cannot be reactivated.",
        )

    version: SkillVersion
    if skill.status == SkillStatus.DRAFT:
        if payload.version_id is not None:
            version = await _get_version_or_404(db, payload.version_id, skill_id=skill.id)
        else:
            version_hash = compute_version_hash(
                {
                    "organization_id": skill.organization_id,
                    "skill_id": skill.id,
                    "version_number": 1,
                    "name": skill.name,
                    "description": skill.description,
                    "department": skill.department,
                    "content": skill.content,
                    "requested_tools": list(skill.requested_tools or []),
                }
            )
            version = SkillVersion(
                organization_id=skill.organization_id,
                skill_id=skill.id,
                version_number=1,
                name=skill.name,
                description=skill.description,
                department=skill.department,
                content=skill.content,
                requested_tools=list(skill.requested_tools or []),
                version_hash=version_hash,
                created_by=context.user_id,
            )
            db.add(version)
            await db.flush()
            await record_audit(
                db,
                tenant=context,
                event="skill.version_created",
                skill_id=skill.id,
                version_id=version.id,
                version_hash=version.version_hash,
                detail={"version_number": 1, "source": "draft_activation"},
            )
    else:  # active, switching to a different version
        version = await _get_version_or_404(db, payload.version_id, skill_id=skill.id)

    previous_status = skill.status
    skill.status = SkillStatus.ACTIVE
    skill.active_version_id = version.id
    await record_audit(
        db,
        tenant=context,
        event="skill.activated",
        skill_id=skill.id,
        version_id=version.id,
        version_hash=version.version_hash,
        detail={
            "version_number": version.version_number,
            "previous_status": previous_status,
        },
    )
    await db.commit()
    await db.refresh(skill)
    return _skill_to_detail(skill)


@router.post(
    "/{skill_id}/disable",
    response_model=SkillDetailOut,
    summary="Disable a skill (owner only)",
    description=(
        "Moves an `active` (or `draft`) skill to the terminal `disabled` "
        "state, excluding it from all runtime selection. Re-disabling an "
        "already disabled skill is a safe, idempotent no-op (200, state "
        "unchanged) recorded as `skill.disable_replayed` in the audit trail."
    ),
)
async def disable_skill(
    skill_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    context: Annotated[TenantContext, Depends(get_tenant_context)],
) -> SkillDetailOut:
    require_owner(context)
    skill = await _get_skill_or_404(db, skill_id)

    if skill.status == SkillStatus.DISABLED:
        active_version = (
            await db.get(SkillVersion, skill.active_version_id)
            if skill.active_version_id
            else None
        )
        await record_audit(
            db,
            tenant=context,
            event="skill.disable_replayed",
            skill_id=skill.id,
            version_id=skill.active_version_id,
            version_hash=active_version.version_hash if active_version else None,
            detail={"note": "idempotent replay; no state change"},
        )
        await db.commit()
        await db.refresh(skill)
        return _skill_to_detail(skill)

    # Explicit state machine gate (see app.lifecycle).
    if not can_transition(skill.status, SkillStatus.DISABLED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot disable a skill in {skill.status.value!r} state.",
        )

    previous_status = skill.status
    skill.status = SkillStatus.DISABLED
    await record_audit(
        db,
        tenant=context,
        event="skill.disabled",
        skill_id=skill.id,
        version_id=skill.active_version_id,
        detail={"previous_status": previous_status},
    )
    await db.commit()
    await db.refresh(skill)
    return _skill_to_detail(skill)


@router.get(
    "/{skill_id}/audit",
    response_model=list[AuditLogOut],
    summary="Audit trail for one skill",
    description=(
        "Returns every audit event recorded for this skill within the "
        "caller's organization: organization, actor, event, timestamp and "
        "version hash."
    ),
)
async def get_skill_audit_trail(
    skill_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    context: Annotated[TenantContext, Depends(get_tenant_context)],
) -> list[AuditLogOut]:
    await _get_skill_or_404(db, skill_id)
    stmt = (
        select(AuditLog)
        .where(AuditLog.skill_id == skill_id)
        .order_by(AuditLog.created_at.asc())
    )
    result = await db.execute(stmt)
    return [AuditLogOut.model_validate(row) for row in result.scalars().all()]
