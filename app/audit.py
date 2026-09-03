"""Audit logging helper.

Every create, update, state mutation, version creation and activation event
is recorded with the organization, actor, event, timestamp and version hash.
Idempotent no-op replays (e.g. re-activating the already-active version) do
NOT write audit rows - the log reflects real state transitions only.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog
from app.tenant import TenantContext


async def record_audit(
    db: AsyncSession,
    *,
    tenant: TenantContext,
    event: str,
    skill_id: str | None = None,
    version_id: str | None = None,
    version_hash: str | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    entry = AuditLog(
        organization_id=tenant.organization_id,
        skill_id=skill_id,
        version_id=version_id,
        actor_id=tenant.user_id,
        actor_role=tenant.role,
        event=event,
        version_hash=version_hash,
        detail=detail or {},
    )
    db.add(entry)
    await db.flush()
    return entry
