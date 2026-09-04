"""Bearer-token auth: issuance, identity-only claims, tamper/expiry rejection.

The signing key under pytest is a dummy test value (pytest.ini). Tokens carry
identity only - the role is always re-resolved from the memberships table.
"""

from __future__ import annotations

import pytest

from app.tokens import TokenError, issue_token, verify_token
from tests.conftest import ABC_ORG_ID, XYZ_ORG_ID, create_draft, headers

SKILLS = "/api/v1/skills"
AUTH = "/api/v1/auth"
KEY = "test-only-signing-key-not-a-secret"


# ---------------------------------------------------------------------------
# Token primitive (pure logic)
# ---------------------------------------------------------------------------


def test_token_roundtrip_and_identity_only_claims() -> None:
    token = issue_token(ABC_ORG_ID, "alice", KEY, ttl_seconds=60)
    claims = verify_token(token, KEY)
    assert claims.organization_id == ABC_ORG_ID
    assert claims.user_id == "alice"
    # No role in the payload: authorization stays server-side.
    assert "role" not in claims.model_dump()


def test_tampered_token_is_rejected() -> None:
    token = issue_token(ABC_ORG_ID, "alice", KEY)
    payload, _ = token.split(".", 1)
    forged = f"{payload}.eyJmYWtlIjp0cnVlfQ"
    with pytest.raises(TokenError):
        verify_token(forged, KEY)
    with pytest.raises(TokenError):
        verify_token(token, "wrong-key")


def test_expired_token_is_rejected() -> None:
    from app.tokens import TokenClaims, _b64encode
    import hashlib, hmac as hmac_mod, json

    claims = TokenClaims(organization_id=ABC_ORG_ID, user_id="alice", exp=1)
    payload = _b64encode(claims.model_dump_json().encode())
    sig = hmac_mod.new(KEY.encode(), payload.encode(), hashlib.sha256).digest()
    expired = f"{payload}.{_b64encode(sig)}"
    with pytest.raises(TokenError, match="expired"):
        verify_token(expired, KEY)


# ---------------------------------------------------------------------------
# HTTP behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_header_session_can_exchange_for_bearer_token(client, abc_owner):
    issued = await client.post(f"{AUTH}/token", json={}, headers=abc_owner)
    assert issued.status_code == 200, issued.text
    body = issued.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 3600

    # Bearer-only request (no identity headers) succeeds.
    listed = await client.get(
        SKILLS, headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert listed.status_code == 200


@pytest.mark.asyncio
async def test_bearer_token_role_is_still_server_resolved(client, abc_owner, abc_member):
    """A member's token cannot activate: role comes from memberships, not token."""
    member_token = (
        await client.post(f"{AUTH}/token", json={}, headers=abc_member)
    ).json()["access_token"]
    skill = await create_draft(client, abc_owner)
    denied = await client.post(
        f"{SKILLS}/{skill['id']}/activate",
        json={},
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_cross_org_bearer_token_is_isolated(client, abc_owner, xyz_owner):
    abc_token = (
        await client.post(f"{AUTH}/token", json={}, headers=abc_owner)
    ).json()["access_token"]
    skill = await create_draft(client, xyz_owner)
    denied = await client.get(
        f"{SKILLS}/{skill['id']}", headers={"Authorization": f"Bearer {abc_token}"}
    )
    assert denied.status_code == 404
    listed = await client.get(
        SKILLS, headers={"Authorization": f"Bearer {abc_token}"}
    )
    assert all(s["organization_id"] == ABC_ORG_ID for s in listed.json())


@pytest.mark.asyncio
async def test_tampered_and_expired_bearer_tokens_rejected_over_http(client):
    forged = "eyJmYWtlIjp0cnVlfQ.zm9yZ2Vk"
    denied = await client.get(
        SKILLS, headers={"Authorization": f"Bearer {forged}"}
    )
    assert denied.status_code == 403

    from app.tokens import TokenClaims, _b64encode
    import hashlib, hmac as hmac_mod

    claims = TokenClaims(organization_id=ABC_ORG_ID, user_id="alice", exp=1)
    payload = _b64encode(claims.model_dump_json().encode())
    sig = hmac_mod.new(KEY.encode(), payload.encode(), hashlib.sha256).digest()
    expired = await client.get(
        SKILLS, headers={"Authorization": f"Bearer {payload}.{_b64encode(sig)}"}
    )
    assert expired.status_code == 403
