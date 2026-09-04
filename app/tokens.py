"""Signed bearer tokens for API authentication.

An alternative to header identity: an authenticated caller can exchange
their credentials for a short-lived, HMAC-SHA256-signed token and then call
the API with ``Authorization: Bearer <token>``. Design points:

* the signing key comes from the environment (``AUTH_SIGNING_KEY``); no
  default exists, and tokens are refused unless a key is configured;
* the token carries only *identity* (organization, user, expiry) — never a
  role. The role is still resolved server-side from the ``memberships``
  table on every request, exactly as with header identity, so a token can
  never elevate privileges;
* verification is constant-time (``hmac.compare_digest``); expired or
  tampered tokens are rejected with 403 (deliberately indistinguishable
  from other auth failures — no oracle);
* the format is ``base64url(json payload).base64url(hmac-sha256(payload))``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from pydantic import BaseModel

_TOKEN_VERSION = "v1"
_DEFAULT_TTL_SECONDS = 3600


class TokenError(Exception):
    """Raised when a bearer token is missing a key, malformed, tampered or expired."""


class TokenClaims(BaseModel):
    organization_id: str
    user_id: str
    exp: int
    ver: str = _TOKEN_VERSION


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _mac(signing_key: str, payload: bytes) -> bytes:
    return hmac.new(signing_key.encode("utf-8"), payload, hashlib.sha256).digest()


def issue_token(
    organization_id: str, user_id: str, signing_key: str, ttl_seconds: int = _DEFAULT_TTL_SECONDS
) -> str:
    """Mint a short-lived bearer token for an already-authenticated identity."""
    if not signing_key:
        raise TokenError("AUTH_SIGNING_KEY is not configured; token issuance is disabled")
    claims = TokenClaims(
        organization_id=organization_id,
        user_id=user_id,
        exp=int(time.time()) + ttl_seconds,
    )
    payload = _b64encode(claims.model_dump_json().encode("utf-8"))
    return f"{payload}.{_b64encode(_mac(signing_key, payload.encode('ascii')))}"


def verify_token(token: str, signing_key: str) -> TokenClaims:
    """Verify signature and expiry; raise TokenError on any failure.

    The role is deliberately absent from the claims: authorization always
    re-resolves the membership server-side.
    """
    if not signing_key:
        raise TokenError("AUTH_SIGNING_KEY is not configured; bearer auth is disabled")
    try:
        payload_b64, signature_b64 = token.split(".", 1)
    except ValueError as exc:
        raise TokenError("malformed token") from exc
    expected = _mac(signing_key, payload_b64.encode("ascii"))
    try:
        supplied = _b64decode(signature_b64)
    except Exception as exc:  # noqa: BLE001 - any decode failure is a bad token
        raise TokenError("malformed token") from exc
    if not hmac.compare_digest(expected, supplied):
        raise TokenError("signature verification failed")
    try:
        claims = TokenClaims.model_validate(json.loads(_b64decode(payload_b64)))
    except Exception as exc:  # noqa: BLE001
        raise TokenError("malformed token claims") from exc
    if claims.ver != _TOKEN_VERSION:
        raise TokenError("unsupported token version")
    if claims.exp < int(time.time()):
        raise TokenError("token expired")
    return claims
