"""Authentication / tenant-context dependencies.

Requests are authenticated purely through headers (this is a back-end
evaluation slice; no JWT issuer is in scope):

  * ``X-Organization-Id`` must reference a real organization, otherwise the
    request is rejected with 403 (we intentionally do not distinguish
    "unknown org" from "forbidden" - no existence oracle is exposed).
  * ``X-User-Id`` is the actor identity recorded in audit logs.
  * ``X-User-Role`` must be ``owner`` or ``member``.

A successful resolution stores the tenant in a ``ContextVar`` (see
``app.tenant``) which the global SQLAlchemy filter in ``app.database`` uses
to scope every subsequent query to this organization.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Organization
from app.tenant import VALID_ROLES, TenantContext, tenant_context_var


async def get_tenant_context(
    db: Annotated[AsyncSession, Depends(get_db)],
    x_organization_id: Annotated[str, Header(alias="X-Organization-Id")],
    x_user_id: Annotated[str, Header(alias="X-User-Id")],
    x_user_role: Annotated[str, Header(alias="X-User-Role")],
) -> AsyncGenerator[TenantContext, None]:
    organization_id = x_organization_id.strip()
    user_id = x_user_id.strip()
    role = x_user_role.strip().lower()

    if not organization_id or not user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="X-Organization-Id and X-User-Id headers must be non-empty",
        )
    if role not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"X-User-Role must be one of {sorted(VALID_ROLES)}",
        )

    organization = await db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unknown organization or insufficient privileges",
        )

    context = TenantContext(
        organization_id=organization_id, user_id=user_id, role=role
    )
    token = tenant_context_var.set(context)
    try:
        yield context
    finally:
        tenant_context_var.reset(token)


def require_owner(context: TenantContext) -> None:
    """Raise 403 unless the current actor owns the organization."""
    if not context.is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action is restricted to the organization owner",
        )
