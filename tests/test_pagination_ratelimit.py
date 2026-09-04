"""Pagination (limit/offset + X-Total-Count) and the rate limiter."""

from __future__ import annotations

import pytest

from app.ratelimit import SlidingWindowLimiter
from tests.conftest import activate, create_draft

SKILLS = "/api/v1/skills"


# ---------------------------------------------------------------------------
# Rate limiter logic (unit)
# ---------------------------------------------------------------------------


def test_limiter_allows_up_to_limit_then_blocks() -> None:
    limiter = SlidingWindowLimiter(limit=3)
    assert [limiter.check("k", now=t) for t in (1.0, 2.0, 3.0)] == [True, True, True]
    assert limiter.check("k", now=4.0) is False


def test_limiter_window_slides() -> None:
    limiter = SlidingWindowLimiter(limit=2, window_seconds=10)
    assert limiter.check("k", now=1.0)
    assert limiter.check("k", now=2.0)
    assert limiter.check("k", now=5.0) is False
    # Both events aged out of the window.
    assert limiter.check("k", now=12.5) is True


def test_limiter_keys_are_independent_and_zero_disables() -> None:
    limiter = SlidingWindowLimiter(limit=1)
    assert limiter.check("a", now=1.0)
    assert limiter.check("b", now=1.0)
    off = SlidingWindowLimiter(limit=0)
    assert all(off.check("a", now=t) for t in range(500))


# ---------------------------------------------------------------------------
# Pagination over HTTP
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_skills_pagination_and_total_count(client, abc_owner):
    for i in range(5):
        await create_draft(client, abc_owner, name=f"Skill {i}")

    full = await client.get(SKILLS, headers=abc_owner)
    assert full.status_code == 200
    assert full.headers["X-Total-Count"] == "5"
    assert len(full.json()) == 5

    page = await client.get(
        f"{SKILLS}?limit=2&offset=3", headers=abc_owner
    )
    assert page.status_code == 200
    assert page.headers["X-Total-Count"] == "5"
    assert len(page.json()) == 2
    names = {s["name"] for s in page.json()}
    assert names == {"Skill 1", "Skill 0"}  # newest-first ordering

    out_of_range = await client.get(
        f"{SKILLS}?limit=2&offset=10", headers=abc_owner
    )
    assert out_of_range.status_code == 200
    assert out_of_range.json() == []
    assert out_of_range.headers["X-Total-Count"] == "5"

    bad = await client.get(f"{SKILLS}?limit=0", headers=abc_owner)
    assert bad.status_code == 422
    bad = await client.get(f"{SKILLS}?offset=-1", headers=abc_owner)
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_audit_trail_pagination_and_total_count(client, abc_owner):
    skill = await create_draft(client, abc_owner)
    await activate(client, abc_owner, skill["id"])

    audit = await client.get(
        f"{SKILLS}/{skill['id']}/audit?limit=2", headers=abc_owner
    )
    assert audit.status_code == 200
    total = int(audit.headers["X-Total-Count"])
    assert total >= 2  # draft_created, version_created, activated
    assert len(audit.json()) == 2

    second_page = await client.get(
        f"{SKILLS}/{skill['id']}/audit?limit=2&offset=2", headers=abc_owner
    )
    assert second_page.status_code == 200
    assert second_page.headers["X-Total-Count"] == str(total)


@pytest.mark.asyncio
async def test_department_runtime_pagination(client, abc_owner):
    for i in range(3):
        skill = await create_draft(client, abc_owner, name=f"Dept {i}")
        await activate(client, abc_owner, skill["id"])

    runtime = await client.get(
        f"{SKILLS}/departments/finance/active-skills?limit=2&offset=1",
        headers=abc_owner,
    )
    assert runtime.status_code == 200
    assert runtime.headers["X-Total-Count"] == "3"
    assert len(runtime.json()) == 2
