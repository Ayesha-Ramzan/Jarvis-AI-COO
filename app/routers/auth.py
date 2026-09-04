"""Bearer-token issuance: exchange authenticated identity for a token.

``POST /api/v1/auth/token`` is only reachable when ``AUTH_SIGNING_KEY`` is
configured; the caller must already be authenticated (headers), and the
minted token carries *identity only* - the role stays server-side in the
memberships table, so a token can never elevate privileges.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.config import get_settings
from app.dependencies import get_tenant_context
from app.tokens import TokenError, issue_token
from app.tenant import TenantContext

router = APIRouter(tags=["auth"])


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenRequestIn(BaseModel):
    ttl_seconds: int = 3600


@router.post(
    "/token",
    response_model=TokenOut,
    summary="Exchange authenticated identity for a short-lived bearer token",
    description=(
        "Requires a valid header-authenticated session. Returns an HMAC-SHA256 "
        "signed bearer token carrying identity only (organization, user, "
        "expiry) - never a role. Requires AUTH_SIGNING_KEY to be configured."
    ),
)
async def issue_access_token(
    payload: TokenRequestIn | None = None,
    context: Annotated[TenantContext, Depends(get_tenant_context)] = None,  # type: ignore[assignment]
) -> TokenOut:
    settings = get_settings()
    ttl = payload.ttl_seconds if payload and payload.ttl_seconds else 3600
    if ttl < 1 or ttl > 86400:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="ttl_seconds must be between 1 and 86400",
        )
    try:
        token = issue_token(context.organization_id, context.user_id, settings.auth_signing_key, ttl)
    except TokenError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Token issuance is disabled: AUTH_SIGNING_KEY is not configured",
        )
    return TokenOut(access_token=token, expires_in=ttl)
