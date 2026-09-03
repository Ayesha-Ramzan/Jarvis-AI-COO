# FINAL REPORT

Repository URL: (local repository — push target to be assigned by the candidate)
Start time: 2026-09-03
Finish time: 2026-09-04
Approximate hours: ~8 total across two sessions (build, then evidence-based audit + six finding fixes)
Final commit SHA: code-complete at `6ef1d3c`; docs/artifact commit follows (see `git log -1 --oneline`)

Goal achieved: Yes. The full workflow — authenticated organization → draft
create → review → owner activation → active retrieval → exact-version audit
record — works end-to-end for both fixture organizations, with cross-tenant
access denied in every code path and active versions immutable by
construction.

Architecture decisions:
- PostgreSQL 16 + SQLAlchemy 2.0 async sessions + Alembic migrations
  (0001-0004); SQLite in-memory only for the dedicated test database (ADR-5).
- Global tenant isolation: request-scoped `TenantContext` in a ContextVar,
  enforced by a SQLAlchemy `do_orm_execute` listener applying
  `with_loader_criteria(organization_id == tenant)` to every ORM SELECT on
  skills, versions and audit logs (ADR-1). Cross-tenant access returns 404 —
  no existence oracle (ADR-6).
- Header identity (`X-Organization-Id`, `X-User-Id`), with roles resolved
  server-side from a `memberships` table (composite PK, CHECK-constrained
  role); the `X-User-Role` header is never trusted for authorization.
- Immutable versioning: `draft` is editable; activation snapshots
  immutable version 1; while active, behavior changes only via new
  `SkillVersion` rows + explicit owner activation; version rows are
  append-only with SHA-256 version hashes (ADR-2).
- Lifecycle as a real state machine: enum-backed `SkillStatus` column
  (native ENUM on PostgreSQL) + explicit `TRANSITIONS` map in
  `app/lifecycle.py` consulted by activate/disable.
- Auditability: every state change writes organization, actor (id + role),
  event, version id + hash; idempotent replays write distinct
  `*_replayed` events without changing state (ADR-3).
- Closed tool catalogue with destructive-fragment and SQLi rejection at the
  Pydantic layer (ADR-4, ADR-7).
- DB credentials required from the environment (no hardcoded defaults);
  compose database is internal-network only.

Tests passed: 41/41 (10 mandatory spec tests + boundary, isolation,
immutability, idempotency, sanitization, lifecycle-state-machine and config
tests). Verified by live run 2026-09-04 (41 passed); output captured in README.

Security/isolation evidence:
- Live probes: cross-org read/update/activate → 404; member activation →
  403; member claiming `X-User-Role: owner` → 403; non-member user → 403;
  active-skill PATCH → 409; destructive tool → 422 — on both the SQLite
  dev server and the clean PostgreSQL Docker Compose stack.
- Full git-history secret scan clean; `.env.example` placeholders only.
- Compose verified starting from a clean state (fresh volume → migrations
  → fixture seeding → healthy API).

Known limitations:
- Header-based identity is an evaluation shortcut (no signed tokens); role
  authorization itself is fully server-side via memberships.
- No pagination, no rate limiting (edge concern), strict sanitizers reject
  SQL comment sequences in free text (documented trade-off).
- Tests run on SQLite by design; PostgreSQL is exercised via Alembic and
  the compose stack (rationale in ADR-5).

What I would implement next: signed-token authentication, pagination,
optimistic concurrency (ETags), Prometheus metrics, outbox-based audit
streaming.

AI tools used, if any: Kimi Code CLI (assistant pair-programming; an
earlier LLM-assisted audit pass produced AUDIT-REPORT.md findings F-1..F-6,
all fixed and re-verified).
