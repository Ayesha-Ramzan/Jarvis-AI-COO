"""Explicit tool-approval tests (opt-in permissions, never automatic).

A skill *requesting* a tool confers nothing: only an owner-only approval
endpoint grants runtime usability, one row per (version, tool), and every
approval (including idempotent replays) is audit-logged.
"""

from __future__ import annotations

import pytest

from tests.conftest import ABC_ORG_ID, activate, create_draft

SKILLS = "/api/v1/skills"


def approve_url(skill_id: str, version_id: str, tool: str) -> str:
    return f"{SKILLS}/{skill_id}/versions/{version_id}/tools/{tool}/approve"


async def activated_version(client, hdrs, **overrides) -> dict:
    """Create a draft, activate it, and return the skill detail."""
    skill = await create_draft(client, hdrs, **overrides)
    activated = await activate(client, hdrs, skill["id"])
    assert activated.status_code == 200, activated.text
    return activated.json()


@pytest.mark.asyncio
async def test_requested_tools_are_not_granted_automatically(client, abc_owner):
    """Nothing is approved until the owner explicitly approves it."""
    skill = await activated_version(client, abc_owner)
    runtime = await client.get(
        f"{SKILLS}/departments/finance/active-skills", headers=abc_owner
    )
    assert runtime.status_code == 200
    entry = next(e for e in runtime.json() if e["skill_id"] == skill["id"])
    assert entry["version"]["requested_tools"] == [
        "email.read",
        "email.send",
        "crm.read",
    ]
    assert entry["approved_tools"] == []


@pytest.mark.asyncio
async def test_owner_approval_grants_runtime_tool(client, abc_owner):
    skill = await activated_version(client, abc_owner)
    version_id = skill["active_version_id"]

    approved = await client.post(
        approve_url(skill["id"], version_id, "email.read"), headers=abc_owner
    )
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["tool"] == "email.read"
    assert body["organization_id"] == ABC_ORG_ID
    assert body["approved_by"] == "alice"
    assert body["version_id"] == version_id

    runtime = await client.get(
        f"{SKILLS}/departments/finance/active-skills", headers=abc_owner
    )
    entry = next(e for e in runtime.json() if e["skill_id"] == skill["id"])
    assert entry["approved_tools"] == ["email.read"]


@pytest.mark.asyncio
async def test_non_owner_approval_is_denied(client, abc_owner, abc_member):
    skill = await activated_version(client, abc_owner)
    response = await client.post(
        approve_url(skill["id"], skill["active_version_id"], "email.read"),
        headers=abc_member,
    )
    assert response.status_code in (401, 403)
    # Nothing was granted.
    runtime = await client.get(
        f"{SKILLS}/departments/finance/active-skills", headers=abc_owner
    )
    entry = next(e for e in runtime.json() if e["skill_id"] == skill["id"])
    assert entry["approved_tools"] == []


@pytest.mark.asyncio
async def test_cross_org_approval_is_denied_and_invisible(client, abc_owner, xyz_owner):
    skill = await activated_version(client, abc_owner)
    # Cross-tenant attempt: version is invisible to XYZ, never an existence oracle.
    response = await client.post(
        approve_url(skill["id"], skill["active_version_id"], "email.read"),
        headers=xyz_owner,
    )
    assert response.status_code in (403, 404)


@pytest.mark.asyncio
async def test_approving_tool_not_requested_by_version_is_rejected(
    client, abc_owner
):
    skill = await activated_version(client, abc_owner)
    # calendar.read is in the global catalogue but NOT requested by this version.
    response = await client.post(
        approve_url(skill["id"], skill["active_version_id"], "calendar.read"),
        headers=abc_owner,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_duplicate_approval_is_idempotent_and_audited(client, abc_owner):
    skill = await activated_version(client, abc_owner)
    url = approve_url(skill["id"], skill["active_version_id"], "email.send")

    first = await client.post(url, headers=abc_owner)
    assert first.status_code == 200

    replay = await client.post(url, headers=abc_owner)
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]

    audit = await client.get(f"{SKILLS}/{skill['id']}/audit", headers=abc_owner)
    events = [e["event"] for e in audit.json()]
    assert events.count("tool.approved") == 1
    assert events.count("tool.approval_replayed") == 1
    replay_event = next(
        e for e in audit.json() if e["event"] == "tool.approval_replayed"
    )
    assert replay_event["organization_id"] == ABC_ORG_ID
    assert replay_event["version_id"] == skill["active_version_id"]


@pytest.mark.asyncio
async def test_approvals_do_not_leak_across_orgs_runtime(client, abc_owner, xyz_owner):
    skill = await activated_version(client, abc_owner)
    await client.post(
        approve_url(skill["id"], skill["active_version_id"], "email.read"),
        headers=abc_owner,
    )
    # XYZ's own department listing must not include ABC's skill at all.
    runtime = await client.get(
        f"{SKILLS}/departments/finance/active-skills", headers=xyz_owner
    )
    assert all(e["skill_id"] != skill["id"] for e in runtime.json())
