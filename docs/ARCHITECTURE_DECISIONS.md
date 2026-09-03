# Architecture Decision Notes

Short, opinionated records of the decisions that shape this vertical slice.

## ADR-1 — Global tenant isolation via `with_loader_criteria` + ContextVar

**Decision.** Tenant identity is resolved once per request
(`get_tenant_context` from headers), stored in a `contextvars.ContextVar`,
and a SQLAlchemy `do_orm_execute` session event applies
`with_loader_criteria(organization_id == tenant)` to every ORM SELECT on
`Skill`, `SkillVersion` and `AuditLog`.

**Why.** Manually threading `organization_id` into every query is the
classic source of cross-tenant leaks: one forgotten filter is one breach.
A query-global filter makes the secure path the only path. `ContextVar`
keeps it task-local, which is safe under asyncio concurrency.

**Consequences.** Cross-tenant access returns 404 (the row is invisible),
so the API never acts as an existence oracle. Filtered-away rows cannot be
lazy-loaded either, which hard-fails tests rather than leaking data.

## ADR-2 — Immutable versions, mutable draft; activation snapshots v1

**Decision.** `Skill` carries the editable working copy while `draft`.
Activation snapshots it into `SkillVersion` 1. While `active`, the skill row
and all its versions are immutable: changes are expressed as *new*
`SkillVersion` rows which must then be explicitly activated. `SkillVersion`
rows have no update/delete code paths anywhere in the service layer and a
unique `(skill_id, version_number)` constraint.

**Why.** "An active skill must never be modified in place" is enforced at
the API boundary (409 with an instructive message) *and* structurally
(history can only grow). Version hashes (SHA-256 over canonical JSON) give
activation events a tamper-evident anchor.

**Consequences.** Draft edits never rewrite history; reviewers can diff
versions; audit rows can point at an exact version + hash.

## ADR-3 — Idempotency by state comparison, not request dedup

**Decision.** Re-activating the already-active version (and re-disabling a
disabled skill) returns 200 with current state and writes **no** audit row.
State transitions are compared before acting, instead of relying on
idempotency keys.

**Why.** Retry-safety (network retries, double clicks) without key
management. Audit logs record real transitions only, so a replayed request
cannot inflate the trail.

## ADR-4 — Closed tool catalogue; requesting never grants

**Decision.** `requested_tools` must match `namespace.action`, must not
contain destructive fragments (`drop`, `exec`, `wipe`, ...), and must
belong to an explicit allowlist. Unknown or destructive entries fail 422
with field-level errors.

**Why.** "Requested tools must not grant permissions automatically" — the
registry records *intent*; a separate runtime would map approved tools to
actual scopes. A closed catalogue makes destructive intent unrepresentable.

## ADR-5 — PostgreSQL in production, SQLite only for the test DB

**Decision.** Production and Docker Compose run PostgreSQL 16 with Alembic
migrations. The test suite runs on SQLite in-memory via aiosqlite with a
dedicated engine/session override.

**Why.** The evaluation mandates automated tests and a reproducible local
start; tests must not require Docker. All behavior under test (tenant
filter, lifecycle constraints, immutability, audit) is dialect-neutral
ORM-level logic; dialect-specific schema is owned by Alembic and exercised
against PostgreSQL in Compose. This keeps `pytest` fast and hermetic while
production stays on the preferred database.

## ADR-6 — 404 instead of 403 for cross-tenant object access

**Decision.** A skill id that exists in another tenant is indistinguishable
from a nonexistent id (404). 403 is reserved for authenticated-but-forbidden
actions within the tenant (e.g. member attempting activation).

**Why.** 403 on foreign ids confirms existence and invites id enumeration;
uniform 404 denies information. The evaluation accepts either; this chooses
the stronger guarantee.

## ADR-7 — Strict input sanitization as defense in depth

**Decision.** All free text is trimmed and rejected when it matches classic
SQL-injection fragments (`--`, `/* */`, DDL/DML verbs, `or 1=1`, stacked
statements). SQLAlchemy bound parameters already make injection impossible;
the sanitizers exist to fail loudly on hostile input rather than to be the
primary defense.

**Consequence (accepted).** Legitimate text containing SQL comment
sequences is rejected — a documented strictness trade-off for a registry of
machine-consumed prompts.
