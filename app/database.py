"""Async database engine, session factory and the global tenant isolation filter.

The tenant isolation filter is implemented with SQLAlchemy's
``with_loader_criteria``: a ``do_orm_execute`` session event transparently
appends ``organization_id = <current tenant>`` criteria to every ORM SELECT
for the tenant-owned models (Skill, SkillVersion, AuditLog). Routers never
hand-write tenant filters; cross-tenant rows are invisible by construction
and therefore surface as 404, never as data leakage.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, with_loader_criteria

from app.config import get_settings
from app.tenant import tenant_context_var


class Base(DeclarativeBase):
    pass


settings = get_settings()

engine = create_async_engine(
    settings.resolved_database_url,
    echo=settings.debug,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


@event.listens_for(Session, "do_orm_execute")
def _apply_tenant_isolation(execute_state) -> None:
    tenant = tenant_context_var.get()
    if tenant is None or not execute_state.is_select:
        return

    # Imported here to avoid a circular import with app.models.
    from app import models

    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            models.Skill,
            models.Skill.organization_id == tenant.organization_id,
            include_aliases=True,
        ),
        with_loader_criteria(
            models.SkillVersion,
            models.SkillVersion.skill.has(
                models.Skill.organization_id == tenant.organization_id
            ),
            include_aliases=True,
        ),
        with_loader_criteria(
            models.AuditLog,
            models.AuditLog.organization_id == tenant.organization_id,
            include_aliases=True,
        ),
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an async database session."""
    async with AsyncSessionLocal() as session:
        yield session
