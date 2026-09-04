"""Pydantic validation layer.

Every inbound payload passes through aggressive, explicit sanitizers:

  * free-text fields are trimmed of leading/trailing whitespace and rejected
    if they contain classic SQL-injection fragments (defense in depth on top
    of SQLAlchemy's bound-parameter statements);
  * requested tools must match a strict ``namespace.action`` shape, must not
    carry destructive fragments, and must belong to an explicit allowlist -
    a requested tool never grants a permission by itself;
  * collection payloads are deduplicated and bounded.

Validation failures raise ``ValueError`` which FastAPI renders as a 422 with
a precise, field-level error message.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Sanitization primitives
# ---------------------------------------------------------------------------

_SQLI_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"(--|/\*|\*/)",  # SQL comment sequences
        r"\bunion\b\s+(all\s+)?\bselect\b",  # UNION-based extraction
        r"\bselect\b.+\bfrom\b",  # inline SELECT statements
        r"\b(insert|update|delete|drop|truncate|alter|grant|revoke)\b",  # DDL/DML verbs
        r"\b(or|and)\b\s+[\w'\"]+\s*=\s*[\w'\"]+",  # boolean tautologies (or 1=1)
        r"\b(exec(ute)?|xp_\w+|sp_\w+)\b",  # stored procedure execution
        r";\s*\S",  # statement stacking
    )
)

_TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(\.[a-z][a-z0-9_]*)+$")
_DANGEROUS_TOOL_FRAGMENTS: tuple[str, ...] = (
    "delete",
    "drop",
    "truncate",
    "exec",
    "shell",
    "admin",
    "root",
    "sudo",
    "wipe",
    "destroy",
    "grant",
    "revoke",
    "backup",
    "restore",
    "migrate",
    "database",
)

# The complete, closed catalogue of tools a skill may request. Granting is a
# separate, explicit runtime decision; a request alone confers nothing.
ALLOWED_TOOLS: frozenset[str] = frozenset(
    {
        "calendar.read",
        "calendar.write",
        "email.read",
        "email.send",
        "tasks.read",
        "tasks.write",
        "contacts.read",
        "documents.read",
        "documents.write",
        "crm.read",
        "meetings.read",
        "meetings.write",
    }
)

MAX_TOOLS_PER_SKILL = 16


def sanitize_text(value: str, field_name: str, *, allow_empty: bool = False) -> str:
    cleaned = value.strip()
    if not cleaned and not allow_empty:
        raise ValueError(f"{field_name} must not be empty")
    for pattern in _SQLI_PATTERNS:
        if pattern.search(cleaned):
            raise ValueError(
                f"{field_name} contains forbidden content matching "
                f"{pattern.pattern!r}"
            )
    return cleaned


def sanitize_tools(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in values:
        tool = raw.strip().lower()
        if not _TOOL_NAME_RE.match(tool):
            raise ValueError(
                f"requested tool {raw!r} must use lowercase 'namespace.action' form"
            )
        for fragment in _DANGEROUS_TOOL_FRAGMENTS:
            if fragment in tool:
                raise ValueError(
                    f"requested tool {raw!r} is destructive "
                    f"('{fragment}' is not permitted)"
                )
        if tool not in ALLOWED_TOOLS:
            raise ValueError(
                f"requested tool {raw!r} is not in the approved tool catalogue"
            )
        if tool not in seen:
            seen.add(tool)
            cleaned.append(tool)
    if len(cleaned) > MAX_TOOLS_PER_SKILL:
        raise ValueError(
            f"a skill may request at most {MAX_TOOLS_PER_SKILL} tools"
        )
    return cleaned


# ---------------------------------------------------------------------------
# Inbound payloads
# ---------------------------------------------------------------------------


class SkillDraftCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=4000)
    department: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=50000)
    requested_tools: list[str] = Field(default_factory=list)

    _clean_name = field_validator("name")(lambda cls, v: sanitize_text(v, "name"))
    _clean_department = field_validator("department")(
        lambda cls, v: sanitize_text(v, "department")
    )
    _clean_description = field_validator("description")(
        lambda cls, v: sanitize_text(v, "description", allow_empty=True)
    )
    _clean_content = field_validator("content")(
        lambda cls, v: sanitize_text(v, "content")
    )
    _clean_tools = field_validator("requested_tools")(sanitize_tools)


class SkillDraftUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    department: str | None = Field(default=None, min_length=1, max_length=128)
    content: str | None = Field(default=None, min_length=1, max_length=50000)
    requested_tools: list[str] | None = None

    _clean_name = field_validator("name")(lambda cls, v: sanitize_text(v, "name") if v is not None else v)
    _clean_department = field_validator("department")(
        lambda cls, v: sanitize_text(v, "department") if v is not None else v
    )
    _clean_description = field_validator("description")(
        lambda cls, v: sanitize_text(v, "description", allow_empty=True) if v is not None else v
    )
    _clean_content = field_validator("content")(
        lambda cls, v: sanitize_text(v, "content") if v is not None else v
    )
    _clean_tools = field_validator("requested_tools")(
        lambda cls, v: sanitize_tools(v) if v is not None else v
    )


class SkillVersionCreateIn(BaseModel):
    """Full replacement snapshot for a new immutable version."""

    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=4000)
    department: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=50000)
    requested_tools: list[str] = Field(default_factory=list)

    _clean_name = field_validator("name")(lambda cls, v: sanitize_text(v, "name"))
    _clean_department = field_validator("department")(
        lambda cls, v: sanitize_text(v, "department")
    )
    _clean_description = field_validator("description")(
        lambda cls, v: sanitize_text(v, "description", allow_empty=True)
    )
    _clean_content = field_validator("content")(
        lambda cls, v: sanitize_text(v, "content")
    )
    _clean_tools = field_validator("requested_tools")(sanitize_tools)


class SkillActivateIn(BaseModel):
    """Optional explicit version to activate.

    When a draft is activated without a ``version_id`` the draft's current
    working copy is snapshotted as immutable version 1 and activated
    atomically. When supplied, the version must belong to this skill.
    """

    version_id: str | None = None


# ---------------------------------------------------------------------------
# Outbound payloads
# ---------------------------------------------------------------------------


class SkillVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    skill_id: str
    version_number: int
    name: str
    description: str
    department: str
    content: str
    requested_tools: list[str]
    version_hash: str
    created_by: str
    created_at: datetime


class SkillSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    name: str
    description: str
    department: str
    requested_tools: list[str]
    status: str
    active_version_id: str | None
    created_by: str
    created_at: datetime
    updated_at: datetime


class SkillDetailOut(SkillSummaryOut):
    content: str
    versions: list[SkillVersionOut] = Field(default_factory=list)


class DepartmentSkillOut(BaseModel):
    """Runtime payload: an active skill bound to its active version snapshot.

    ``approved_tools`` is the intersection of the version's requested tools
    and the owner-granted approvals for that version: a requested-but-
    unapproved tool never appears here, so it can never be invoked at
    runtime.
    """

    skill_id: str
    name: str
    department: str
    version: SkillVersionOut
    approved_tools: list[str] = Field(default_factory=list)


class ToolApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    skill_id: str
    version_id: str
    tool: str
    approved_by: str
    created_at: datetime


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    skill_id: str | None
    version_id: str | None
    actor_id: str
    actor_role: str
    event: str
    version_hash: str | None
    detail: dict
    created_at: datetime


SkillStatusFilter = Literal["draft", "active", "disabled"]
