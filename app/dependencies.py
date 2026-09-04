"""Authentication / tenant-context dependencies.

Requests are authenticated through headers (this is a back-end
evaluation slice; no JWT issuer is in scope):

  * ``X-Organization-Id`` must reference a real organization, otherwise the
    request is rejected with 403 (we intentionally do not distinguish
    "unknown org" from "forbidden" - no existence oracle is exposed).
  * ``X-User-Id`` is the actor identity, which must be a *member* of the
    organization according to the ``memberships`` table.
  * ``X-User-Role`` is accepted for backwards compatibility but is **never
    trusted**: the role used for every authorization decision is read
    server-side from the caller's ``memberships`` row. A member sending
    ``X-User-Role: owner`` is still a member.

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
from app.models import Membership, Organization
from app.tenant import TenantContext, tenant_context_var


async def get_tenant_context(
    db: Annotated[AsyncSession, Depends(get_db)],
    x_organization_id: Annotated[str | None, Header(alias="X-Organization-Id")] = None,
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
    x_user_role: Annotated[str | None, Header(alias="X-User-Role")] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> AsyncGenerator[TenantContext, None]:
    # Bearer-token identity takes precedence when presented and valid. The
    # token carries identity only - the role is still resolved from the
    # memberships table below, so a token can never elevate privileges.
    if authorization and authorization.lower().startswith("bearer "):
        from app.config import get_settings
        from app.tokens import TokenError, verify_token

        raw = authorization.split(" ", 1)[1].strip()
        try:
            claims = verify_token(raw, get_settings().auth_signing_key)
        except TokenError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Unknown organization or insufficient privileges",
            )
        organization_id, user_id = claims.organization_id, claims.user_id
    else:
        organization_id = (x_organization_id or "").strip()
        user_id = (x_user_id or "").strip()
        if not organization_id or not user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="X-Organization-Id and X-User-Id headers must be non-empty",
            )

    organization = await db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unknown organization or insufficient privileges",
        )

    # The role comes from the membership record, not from the request:
    # headers identify *who* is calling, never *what they may do*.
    membership = await db.get(Membership, (organization_id, user_id))
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unknown organization or insufficient privileges",
        )

    context = TenantContext(
        organization_id=organization_id, user_id=user_id, role=membership.role
    )
    token = tenant_context_var.set(context)
    try:
        yield context
    finally:
        tenant_context_var.reset(token)


def require_owner(context: TenantContext) -> None:
    """Raise 403 unless the current actor owns the organization.

    The role was resolved from the memberships table in
    ``get_tenant_context``, so this check is backed by a server-side
    record, not by anything the caller asserted.
    """
    if not context.is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action is restricted to the organization owner",
        )
