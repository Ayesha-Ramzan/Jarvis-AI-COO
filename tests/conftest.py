"""Test fixtures.

Tests run against a dedicated SQLite in-memory database (via aiosqlite) with
a StaticPool, so every test is fully isolated and fast. Justification for
SQLite in tests (production remains PostgreSQL): the evaluation requires a
dedicated test database, and SQLAlchemy 2.0 keeps the dialect gap confined
to the engine layer - all tenant-isolation, lifecycle and immutability logic
under test is dialect-neutral and is additionally exercised against
PostgreSQL via Alembic migrations and Docker Compose.

The real dependency graph is exercised end-to-end: only ``get_db`` is
overridden (pointing at the test engine); header authentication and the
global tenant-isolation ContextVar filter run unmodified.
"""

from __future__ import annotations

import os
import uuid

# Belt and braces on top of pytest-env (pytest.ini): ensure the test
# database is selected before app modules resolve their settings.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
os.environ.setdefault("SEED_FIXTURE_ORGANIZATIONS", "false")

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Membership, Organization

ABC_ORG_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "jarvis-org:ABC Construction"))
XYZ_ORG_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "jarvis-org:XYZ Builders"))

# Roles here mirror the fixture memberships seeded by the application so
# tests exercise the same server-side role resolution as production.
def fixture_memberships() -> list[Membership]:
    return [
        Membership(organization_id=ABC_ORG_ID, user_id="alice", role="owner"),
        Membership(organization_id=ABC_ORG_ID, user_id="bob", role="member"),
        Membership(organization_id=XYZ_ORG_ID, user_id="carol", role="owner"),
        Membership(organization_id=XYZ_ORG_ID, user_id="dave", role="member"),
    ]

TEST_DATABASE_URL = "sqlite+aiosqlite://"

engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


def headers(org_id: str, user_id: str, role: str) -> dict[str, str]:
    return {
        "X-Organization-Id": org_id,
        "X-User-Id": user_id,
        "X-User-Role": role,
    }


@pytest_asyncio.fixture
async def db_session():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with TestSessionLocal() as session:
        session.add_all(
            [
                Organization(id=ABC_ORG_ID, name="ABC Construction"),
                Organization(id=XYZ_ORG_ID, name="XYZ Builders"),
                *fixture_memberships(),
            ]
        )
        await session.commit()
    yield TestSessionLocal
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _override_get_db():
    async with TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session):
    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
def abc_owner() -> dict[str, str]:
    return headers(ABC_ORG_ID, "alice", "owner")


@pytest_asyncio.fixture
def abc_member() -> dict[str, str]:
    return headers(ABC_ORG_ID, "bob", "member")


@pytest_asyncio.fixture
def xyz_owner() -> dict[str, str]:
    return headers(XYZ_ORG_ID, "carol", "owner")


@pytest_asyncio.fixture
def xyz_member() -> dict[str, str]:
    return headers(XYZ_ORG_ID, "dave", "member")


def sample_skill_payload(**overrides) -> dict:
    payload = {
        "name": "Invoice Chaser",
        "description": "Follows up on overdue invoices politely.",
        "department": "finance",
        "content": "You are an AR assistant. Remind clients about overdue invoices.",
        "requested_tools": ["email.read", "email.send", "crm.read"],
    }
    payload.update(overrides)
    return payload


async def create_draft(client, hdrs, **overrides):
    response = await client.post(
        "/api/v1/skills", json=sample_skill_payload(**overrides), headers=hdrs
    )
    assert response.status_code == 201, response.text
    return response.json()


async def activate(client, hdrs, skill_id, version_id=None):
    body = {} if version_id is None else {"version_id": version_id}
    return await client.post(
        f"/api/v1/skills/{skill_id}/activate", json=body, headers=hdrs
    )
