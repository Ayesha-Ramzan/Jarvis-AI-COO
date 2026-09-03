"""FastAPI application entrypoint.

Swagger/OpenAPI is customised with tagged groups so reviewers can navigate
the vertical slice quickly. Fixture organizations (ABC Construction, XYZ
Builders) and their memberships (one owner + one member each) are seeded
idempotently on startup - controlled by ``SEED_FIXTURE_ORGANIZATIONS`` and
disabled automatically under ``test``.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import Membership, Organization
from app.routers import skills

settings = get_settings()

ABC_ORG_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "jarvis-org:ABC Construction"))
XYZ_ORG_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "jarvis-org:XYZ Builders"))

FIXTURE_ORGANIZATIONS: tuple[tuple[str, str], ...] = (
    # Deterministic, name-derived UUIDs so seeding is idempotent.
    (ABC_ORG_ID, "ABC Construction"),
    (XYZ_ORG_ID, "XYZ Builders"),
)

# Memberships back the server-side role check: one owner and one member per
# fixture organization. Roles are resolved from these rows on every request,
# never from the X-User-Role header.
FIXTURE_MEMBERSHIPS: tuple[tuple[str, str, str], ...] = (
    (ABC_ORG_ID, "alice", "owner"),
    (ABC_ORG_ID, "bob", "member"),
    (XYZ_ORG_ID, "carol", "owner"),
    (XYZ_ORG_ID, "dave", "member"),
)


async def seed_fixture_organizations() -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Organization.id))
        existing = set(result.scalars().all())
        for org_id, name in FIXTURE_ORGANIZATIONS:
            if org_id not in existing:
                session.add(Organization(id=org_id, name=name))

        result = await session.execute(
            select(Membership.organization_id, Membership.user_id)
        )
        existing_members = set(result.all())
        for org_id, user_id, role in FIXTURE_MEMBERSHIPS:
            if (org_id, user_id) not in existing_members:
                session.add(
                    Membership(organization_id=org_id, user_id=user_id, role=role)
                )
        await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.seed_fixture_organizations and not settings.is_test:
        await seed_fixture_organizations()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Vertical slice of the JARVIS AI COO multi-tenant platform: an "
        "organization-scoped skill registry with strict tenant isolation, "
        "an immutable draft -> active -> disabled lifecycle, versioned "
        "skill definitions and full auditability.\n\n"
        "Authentication is header-based for this evaluation: every request "
        "must send `X-Organization-Id` and `X-User-Id`. The actor's role "
        "(owner/member) is resolved server-side from the organization's "
        "membership records - the optional `X-User-Role` header is never "
        "trusted for authorization."
    ),
    lifespan=lifespan,
    openapi_tags=[
        {
            "name": "skills",
            "description": (
                "Organization-scoped skill lifecycle: draft creation and "
                "editing, immutable versioning, owner-only activation and "
                "disabling, runtime department selection and audit trail."
            ),
        },
        {
            "name": "system",
            "description": "Operational endpoints (liveness/readiness probe).",
        },
    ],
)

app.include_router(skills.router, prefix=f"{settings.api_v1_prefix}/skills")


@app.get(
    "/healthz",
    tags=["system"],
    summary="Liveness/readiness probe",
)
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name, "version": settings.app_version}
