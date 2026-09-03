"""Tenant context propagation.

The tenant context is stored in a ``contextvars.ContextVar`` so that the
SQLAlchemy session event listener in ``app.database`` can transparently scope
every ORM query to the current organization without any query in the routers
needing to mention ``organization_id`` explicitly.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass

OWNER_ROLE = "owner"
MEMBER_ROLE = "member"


@dataclass(frozen=True, slots=True)
class TenantContext:
    organization_id: str
    user_id: str
    role: str

    @property
    def is_owner(self) -> bool:
        return self.role == OWNER_ROLE


tenant_context_var: contextvars.ContextVar[TenantContext | None] = contextvars.ContextVar(
    "tenant_context", default=None
)
