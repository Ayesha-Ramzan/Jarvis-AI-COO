"""Boundary tests for the organization-scoped skill registry.

Coverage maps 1:1 to the evaluation's mandatory test matrix:
same-org CRUD, cross-org denial, owner-only activation, draft-not-active
runtime exclusion, disabled runtime exclusion, version immutability,
idempotent activation, destructive-tool rejection and audit completeness.
"""

from __future__ import annotations

import pytest

from tests.conftest import (
    ABC_ORG_ID,
    XYZ_ORG_ID,
    activate,
    create_draft,
    headers,
    sample_skill_payload,
)

SKILLS = "/api/v1/skills"


# ---------------------------------------------------------------------------
# Same-organization happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_org_create_and_read_succeeds(client, abc_owner):
    created = await create_draft(client, abc_owner)
    assert created["status"] == "draft"
    assert created["organization_id"] == ABC_ORG_ID
    assert created["versions"] == []

    fetched = await client.get(f"{SKILLS}/{created['id']}", headers=abc_owner)
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["id"] == created["id"]
    assert body["name"] == "Invoice Chaser"
    assert body["requested_tools"] == ["email.read", "email.send", "crm.read"]


@pytest.mark.asyncio
async def test_same_org_list_only_shows_own_skills(
    client, abc_owner, abc_member, xyz_owner
):
    await create_draft(client, abc_owner, name="ABC Skill")
    await create_draft(client, xyz_owner, name="XYZ Skill")

    abc_list = await client.get(SKILLS, headers=abc_member)
    assert abc_list.status_code == 200
    names = [s["name"] for s in abc_list.json()]
    assert names == ["ABC Skill"]
    assert all(s["organization_id"] == ABC_ORG_ID for s in abc_list.json())


@pytest.mark.asyncio
async def test_draft_can_be_updated_in_place(client, abc_owner):
    skill = await create_draft(client, abc_owner)
    response = await client.patch(
        f"{SKILLS}/{skill['id']}",
        json={"description": "Updated description.", "content": "New content body."},
        headers=abc_owner,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["description"] == "Updated description."
    assert body["content"] == "New content body."


# ---------------------------------------------------------------------------
# Cross-organization isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_org_read_is_denied(client, abc_owner, xyz_owner):
    skill = await create_draft(client, abc_owner)
    response = await client.get(f"{SKILLS}/{skill['id']}", headers=xyz_owner)
    assert response.status_code in (403, 404)


@pytest.mark.asyncio
async def test_cross_org_update_is_denied(client, abc_owner, xyz_owner):
    skill = await create_draft(client, abc_owner)
    response = await client.patch(
        f"{SKILLS}/{skill['id']}",
        json={"description": "Malicious takeover."},
        headers=xyz_owner,
    )
    assert response.status_code in (403, 404)
    # The victim's skill must be untouched.
    fetched = await client.get(f"{SKILLS}/{skill['id']}", headers=abc_owner)
    assert fetched.json()["description"] == skill["description"]


@pytest.mark.asyncio
async def test_cross_org_activate_is_denied(client, abc_owner, xyz_owner):
    skill = await create_draft(client, abc_owner)
    response = await activate(client, xyz_owner, skill["id"])
    assert response.status_code in (403, 404)
    fetched = await client.get(f"{SKILLS}/{skill['id']}", headers=abc_owner)
    assert fetched.json()["status"] == "draft"


@pytest.mark.asyncio
async def test_cross_org_version_creation_is_denied(client, abc_owner, xyz_owner):
    skill = await create_draft(client, abc_owner)
    await activate(client, abc_owner, skill["id"])
    response = await client.post(
        f"{SKILLS}/{skill['id']}/versions",
        json=sample_skill_payload(name="Hijacked v2"),
        headers=xyz_owner,
    )
    assert response.status_code in (403, 404)
    fetched = await client.get(f"{SKILLS}/{skill['id']}", headers=abc_owner)
    assert len(fetched.json()["versions"]) == 1


@pytest.mark.asyncio
async def test_unknown_organization_is_rejected(client):
    forged = headers("00000000-0000-0000-0000-000000000000", "mallory", "owner")
    response = await client.get(SKILLS, headers=forged)
    assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Server-side role resolution from memberships (F-3)
#
# The old test_invalid_role_header_is_rejected asserted that a bogus
# X-User-Role header value returns 403. That expectation was wrong: it
# treated the header as the role's source of truth. The header is now
# advisory-only and ignored, so the test was replaced by the ones below,
# which prove the role actually comes from the memberships table.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_member_claiming_owner_in_header_is_still_denied(
    client, abc_owner, abc_member
):
    """A member sending X-User-Role: owner must NOT gain owner powers."""
    skill = await create_draft(client, abc_owner)
    forged = dict(abc_member)
    forged["X-User-Role"] = "owner"
    response = await activate(client, forged, skill["id"])
    assert response.status_code == 403
    fetched = await client.get(f"{SKILLS}/{skill['id']}", headers=abc_owner)
    assert fetched.json()["status"] == "draft"


@pytest.mark.asyncio
async def test_owner_with_member_header_role_still_activates(
    client, abc_owner
):
    """An owner sending X-User-Role: member keeps owner powers: the
    membership record wins over the header."""
    skill = await create_draft(client, abc_owner)
    downgraded = dict(abc_owner)
    downgraded["X-User-Role"] = "member"
    response = await activate(client, downgraded, skill["id"])
    assert response.status_code == 200
    assert response.json()["status"] == "active"


@pytest.mark.asyncio
async def test_bogus_role_header_is_ignored(client, abc_owner):
    """The advisory header is never consulted: even a nonsense value does
    not block (or elevate) a real member."""
    bad = dict(abc_owner)
    bad["X-User-Role"] = "superadmin"
    response = await client.get(SKILLS, headers=bad)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_non_member_user_is_rejected(client, abc_owner):
    """A user with no membership row at all is rejected outright."""
    outsider = headers(ABC_ORG_ID, "eve", "owner")
    response = await client.get(SKILLS, headers=outsider)
    assert response.status_code == 403
    skill = await create_draft(client, abc_owner)
    response = await activate(client, outsider, skill["id"])
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Owner-only activation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_owner_activation_is_denied(client, abc_owner, abc_member):
    skill = await create_draft(client, abc_owner)
    response = await activate(client, abc_member, skill["id"])
    assert response.status_code == 403
    fetched = await client.get(f"{SKILLS}/{skill['id']}", headers=abc_owner)
    assert fetched.json()["status"] == "draft"


@pytest.mark.asyncio
async def test_non_owner_disable_is_denied(client, abc_owner, abc_member):
    skill = await create_draft(client, abc_owner)
    await activate(client, abc_owner, skill["id"])
    response = await client.post(
        f"{SKILLS}/{skill['id']}/disable", headers=abc_member
    )
    assert response.status_code == 403
    fetched = await client.get(f"{SKILLS}/{skill['id']}", headers=abc_owner)
    assert fetched.json()["status"] == "active"


# ---------------------------------------------------------------------------
# Lifecycle: draft cannot load as active; disabled excluded from runtime
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_draft_skill_is_not_returned_by_department_runtime(client, abc_owner):
    await create_draft(client, abc_owner, department="finance")
    response = await client.get(
        f"{SKILLS}/departments/finance/active-skills", headers=abc_owner
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_disabled_skill_is_excluded_from_runtime_selection(
    client, abc_owner
):
    active_skill = await create_draft(client, abc_owner, name="Active Skill")
    await activate(client, abc_owner, active_skill["id"])

    disabled_skill = await create_draft(client, abc_owner, name="Disabled Skill")
    await activate(client, abc_owner, disabled_skill["id"])
    response = await client.post(
        f"{SKILLS}/{disabled_skill['id']}/disable", headers=abc_owner
    )
    assert response.status_code == 200

    runtime = await client.get(
        f"{SKILLS}/departments/finance/active-skills", headers=abc_owner
    )
    payload = runtime.json()
    assert [entry["name"] for entry in payload] == ["Active Skill"]
    # The runtime payload is bound to an immutable version snapshot.
    assert payload[0]["version"]["version_number"] == 1
    assert payload[0]["version"]["version_hash"]


@pytest.mark.asyncio
async def test_disabled_skill_cannot_be_reactivated(client, abc_owner):
    skill = await create_draft(client, abc_owner)
    await activate(client, abc_owner, skill["id"])
    await client.post(f"{SKILLS}/{skill['id']}/disable", headers=abc_owner)

    response = await activate(client, abc_owner, skill["id"])
    assert response.status_code == 409

    runtime = await client.get(
        f"{SKILLS}/departments/finance/active-skills", headers=abc_owner
    )
    assert runtime.json() == []


@pytest.mark.asyncio
async def test_disable_is_idempotent(client, abc_owner):
    skill = await create_draft(client, abc_owner)
    await activate(client, abc_owner, skill["id"])
    first = await client.post(f"{SKILLS}/{skill['id']}/disable", headers=abc_owner)
    second = await client.post(f"{SKILLS}/{skill['id']}/disable", headers=abc_owner)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "disabled"

    audit = await client.get(f"{SKILLS}/{skill['id']}/audit", headers=abc_owner)
    disable_events = [e for e in audit.json() if e["event"] == "skill.disabled"]
    assert len(disable_events) == 1


# ---------------------------------------------------------------------------
# Immutability of active skills and versions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_skill_cannot_be_modified_in_place(client, abc_owner):
    skill = await create_draft(client, abc_owner)
    await activate(client, abc_owner, skill["id"])

    response = await client.patch(
        f"{SKILLS}/{skill['id']}",
        json={"description": "Silent mutation attempt."},
        headers=abc_owner,
    )
    assert response.status_code == 409
    assert "immutable" in response.json()["detail"].lower()

    fetched = await client.get(f"{SKILLS}/{skill['id']}", headers=abc_owner)
    assert fetched.json()["description"] == skill["description"]


@pytest.mark.asyncio
async def test_active_version_is_immutable_new_version_required(client, abc_owner):
    skill = await create_draft(client, abc_owner)
    await activate(client, abc_owner, skill["id"])
    original = await client.get(f"{SKILLS}/{skill['id']}", headers=abc_owner)
    v1 = original.json()["versions"][0]
    v1_hash = v1["version_hash"]

    # Change must go through a NEW immutable version.
    response = await client.post(
        f"{SKILLS}/{skill['id']}/versions",
        json=sample_skill_payload(
            name="Invoice Chaser v2",
            content="You are an AR assistant with an escalated tone.",
        ),
        headers=abc_owner,
    )
    assert response.status_code == 201
    v2 = response.json()
    assert v2["version_number"] == 2
    assert v2["version_hash"] != v1_hash

    # Version 1 is untouched: same hash, same content.
    refreshed = await client.get(f"{SKILLS}/{skill['id']}", headers=abc_owner)
    versions = {v["version_number"]: v for v in refreshed.json()["versions"]}
    assert versions[1]["version_hash"] == v1_hash
    assert versions[1]["content"] == skill["content"]
    assert versions[2]["name"] == "Invoice Chaser v2"

    # The runtime definition still points at v1 until v2 is activated.
    assert refreshed.json()["active_version_id"] == v1["id"]


@pytest.mark.asyncio
async def test_draft_skill_cannot_accept_new_versions(client, abc_owner):
    skill = await create_draft(client, abc_owner)
    response = await client.post(
        f"{SKILLS}/{skill['id']}/versions",
        json=sample_skill_payload(),
        headers=abc_owner,
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_version_rows_carry_organization_id(client, abc_owner):
    """F-1: every tenant-scoped row carries the ownership key directly."""
    skill = await create_draft(client, abc_owner)
    await activate(client, abc_owner, skill["id"])

    v2 = await client.post(
        f"{SKILLS}/{skill['id']}/versions",
        json=sample_skill_payload(name="Invoice Chaser v2"),
        headers=abc_owner,
    )
    assert v2.status_code == 201

    fetched = await client.get(f"{SKILLS}/{skill['id']}", headers=abc_owner)
    versions = fetched.json()["versions"]
    assert {v["version_number"] for v in versions} == {1, 2}
    assert all(v["organization_id"] == ABC_ORG_ID for v in versions)


@pytest.mark.asyncio
async def test_activation_of_foreign_version_is_denied(client, abc_owner):
    first = await create_draft(client, abc_owner, name="Skill One")
    second = await create_draft(client, abc_owner, name="Skill Two")
    await activate(client, abc_owner, second["id"])
    foreign = await client.get(f"{SKILLS}/{second['id']}", headers=abc_owner)
    foreign_version_id = foreign.json()["versions"][0]["id"]

    response = await activate(client, abc_owner, first["id"], foreign_version_id)
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Idempotent activation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_activation_is_idempotent_and_safe(client, abc_owner):
    skill = await create_draft(client, abc_owner)
    first = await activate(client, abc_owner, skill["id"])
    assert first.status_code == 200
    assert first.json()["status"] == "active"

    second = await activate(client, abc_owner, skill["id"])
    assert second.status_code == 200
    assert second.json()["status"] == "active"
    assert second.json()["active_version_id"] == first.json()["active_version_id"]

    # Exactly one activation transition was recorded - the replay was a no-op.
    audit = await client.get(f"{SKILLS}/{skill['id']}/audit", headers=abc_owner)
    events = [e["event"] for e in audit.json()]
    assert events.count("skill.activated") == 1
    assert events.count("skill.version_created") == 1


# ---------------------------------------------------------------------------
# Tool catalogue and input sanitization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_tool",
    [
        "shell.exec",  # destructive fragment
        "db.drop_table",  # destructive fragment
        "system.wipe",  # destructive fragment
        "teapot.brew",  # well-formed but not in the approved catalogue
        "Not A Tool!",  # malformed
    ],
)
async def test_invalid_or_destructive_requested_tool_is_rejected(
    client, abc_owner, bad_tool
):
    response = await client.post(
        SKILLS,
        json=sample_skill_payload(requested_tools=["email.read", bad_tool]),
        headers=abc_owner,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_sql_injection_in_text_fields_is_rejected(client, abc_owner):
    response = await client.post(
        SKILLS,
        json=sample_skill_payload(name="x'; DROP TABLE skills;--"),
        headers=abc_owner,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_trailing_whitespace_and_duplicates_are_normalized(client, abc_owner):
    response = await client.post(
        SKILLS,
        json=sample_skill_payload(
            name="  Invoice Chaser   ",
            department=" finance ",
            requested_tools=["email.read", " email.read ", "EMAIL.SEND"],
        ),
        headers=abc_owner,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Invoice Chaser"
    assert body["department"] == "finance"
    assert body["requested_tools"] == ["email.read", "email.send"]


# ---------------------------------------------------------------------------
# End-to-end workflow + audit completeness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_workflow_create_review_activate_retrieve_audit(client, abc_owner):
    created = await create_draft(client, abc_owner)
    skill_id = created["id"]

    # Draft review: owner reads the draft.
    review = await client.get(f"{SKILLS}/{skill_id}", headers=abc_owner)
    assert review.status_code == 200

    # Owner activation snapshots immutable version 1.
    activated = await activate(client, abc_owner, skill_id)
    assert activated.json()["status"] == "active"

    # Active skill is retrievable at runtime.
    runtime = await client.get(
        f"{SKILLS}/departments/finance/active-skills", headers=abc_owner
    )
    assert [entry["skill_id"] for entry in runtime.json()] == [skill_id]

    # Exact version audit record: organization, actor, event, version, hash.
    audit = await client.get(f"{SKILLS}/{skill_id}/audit", headers=abc_owner)
    assert audit.status_code == 200
    records = audit.json()
    activation = next(e for e in records if e["event"] == "skill.activated")
    assert activation["organization_id"] == ABC_ORG_ID
    assert activation["actor_id"] == "alice"
    assert activation["actor_role"] == "owner"
    assert activation["version_id"] == activated.json()["active_version_id"]
    assert activation["version_hash"]
    version_event = next(e for e in records if e["event"] == "skill.version_created")
    assert version_event["version_hash"] == activation["version_hash"]


@pytest.mark.asyncio
async def test_audit_trail_is_tenant_scoped(client, abc_owner, xyz_owner):
    skill = await create_draft(client, abc_owner)
    await activate(client, abc_owner, skill["id"])

    denied = await client.get(f"{SKILLS}/{skill['id']}/audit", headers=xyz_owner)
    assert denied.status_code in (403, 404)

    audit = await client.get(f"{SKILLS}/{skill['id']}/audit", headers=abc_owner)
    assert all(e["organization_id"] == ABC_ORG_ID for e in audit.json())
    assert XYZ_ORG_ID not in {e["organization_id"] for e in audit.json()}
