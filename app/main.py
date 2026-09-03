"""FastAPI application entrypoint.

Swagger/OpenAPI is customised with tagged groups so reviewers can navigate
the vertical slice quickly. Fixture organizations (ABC Construction, XYZ
Builders) are seeded idempotently on startup - controlled by
``SEED_FIXTURE_ORGANIZATIONS`` and disabled automatically under ``test``.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import Organization
from app.routers import skills

settings = get_settings()

FIXTURE_ORGANIZATIONS: tuple[tuple[str, str], ...] = (
    # Deterministic, name-derived UUIDs so seeding is idempotent.
    (str(uuid.uuid5(uuid.NAMESPACE_DNS, "jarvis-org:ABC Construction")), "ABC Construction"),
    (str(uuid.uuid5(uuid.NAMESPACE_DNS, "jarvis-org:XYZ Builders")), "XYZ Builders"),
)


async def seed_fixture_organizations() -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Organization.id))
        existing = set(result.scalars().all())
        for org_id, name in FIXTURE_ORGANIZATIONS:
            if org_id not in existing:
                session.add(Organization(id=org_id, name=name))
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
        "must send `X-Organization-Id`, `X-User-Id` and `X-User-Role` "
        "(`owner` or `member`)."
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
