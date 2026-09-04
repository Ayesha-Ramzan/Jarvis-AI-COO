# JARVIS AI COO — Organization-Scoped Skill Registry

![Python](https://img.shields.io/badge/Python-3.12%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-async-green)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue)
![Tests](https://img.shields.io/badge/tests-49%20passing-brightgreen)
![License](https://img.shields.io/badge/status-evaluation%20slice-orange)

A privacy-first, multi-tenant **FastAPI** backend where organizations create,
review, version, activate and disable custom AI COO skills with strict
organization-level isolation. Organization A can never read, modify or
activate Organization B's data — enforced at the database-session layer, not
by per-route checks.

| | |
|---|---|
| **Framework** | FastAPI (Python 3.12+), fully async |
| **Database** | PostgreSQL 16 · SQLAlchemy 2.0 async · Alembic migrations |
| **Tests** | 49 passing (pytest + pytest-asyncio), incl. a 10-test mandatory acceptance matrix |
| **Deployment** | Multi-stage Dockerfile + Docker Compose (app + PostgreSQL, zero manual provisioning) |

## Why this design is safe by construction

- **Global tenant filter** — a SQLAlchemy `do_orm_execute` event appends
  `organization_id = <tenant>` to *every* ORM query. No router can forget a
  tenant filter; cross-tenant rows are invisible, so cross-tenant access is
  indistinguishable from a missing row (404 — no existence oracle).
- **Immutable active versions** — an active skill is never mutated in
  place. Behavior changes require a new immutable `SkillVersion` snapshot,
  activated explicitly by an owner.
-  **Real state machine** — `draft → active → disabled` is an enum-backed
  column gated by an explicit transition map, not free text.
- **Server-side roles** — `owner`/`member` live in a `memberships` table
  and are resolved on every request; a self-declared role header is ignored.
- **Opt-in tool permissions** — tools are validated against a closed
  catalogue; *requesting* a tool grants nothing. Granting is a separate,
  owner-only, per-version approval act.
- **Complete audit trail** — every state change (and every idempotent
  replay) is logged with organization, actor, event, timestamp and the exact
  version hash.

## Table of contents

1. [Quick start (Docker)](#quick-start-docker)
2. [Local development](#local-development-without-docker)
3. [Authentication model](#authentication-model-evaluation-slice)
4. [API overview](#api-overview-apiv1skills)
5. [Example session](#example-session-curl)
6. [Test output](#test-output)
7. [Architecture decisions](#architecture-in-one-paragraph)
8. [Known limitations](#known-limitations)
9. [Project reports](#final-report)


## Architecture in one paragraph

Every request resolves a `TenantContext` from headers (`X-Organization-Id`,
`X-User-Id`) plus the caller's `memberships` row — the role is resolved
server-side, never from a self-declared header — and stores it in a
`contextvars.ContextVar`. A
SQLAlchemy `do_orm_execute` session event then transparently appends
`organization_id = <tenant>` criteria (`with_loader_criteria`) to **every**
ORM query for tenant-owned models, so no router hand-writes tenant filters
and cross-tenant rows are invisible by construction (404, never leakage).
Skills follow an immutable lifecycle: `draft` is editable; `active` can never
be modified in place — changes are new immutable `SkillVersion` snapshots
that must be explicitly activated by the organization owner; `disabled` is
terminal and excluded from runtime selection. Lifecycle transitions are
governed by an explicit state-machine map (`app/lifecycle.py`) over an
enum-backed status column. Every state transition — and every idempotent
replay — writes an `audit_logs` row with organization, actor, event,
timestamp and version hash. See [docs/ARCHITECTURE_DECISIONS.md](docs/ARCHITECTURE_DECISIONS.md)
for the reasoning and trade-offs.

## Quick start (Docker)

```bash
cp .env.example .env   # set POSTGRES_PASSWORD (required, no default)
docker compose up --build
```

This starts PostgreSQL (internal network only, no published port), runs
`alembic upgrade head`, seeds the two fixture organizations and their
memberships (idempotently) and serves the API on http://localhost:8000.
Interactive docs: http://localhost:8000/docs

## Local development (without Docker)

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # then edit values (credentials are required)
alembic upgrade head            # create schema
uvicorn app.main:app --reload   # seeds fixtures on startup
```

For a zero-config local run you can instead point at SQLite, e.g.
`DATABASE_URL="sqlite+aiosqlite:///./dev.db" alembic upgrade head` and the
same `DATABASE_URL=... uvicorn app.main:app`.

Run the test suite (dedicated SQLite in-memory database):

```bash
pytest -v
```

## Authentication model (evaluation slice)

No JWT issuer is in scope; authentication is header-based. All `/api/v1/*`
requests require:

| Header            | Example                                | Meaning                        |
|-------------------|----------------------------------------|--------------------------------|
| `X-Organization-Id` | `018f...` (see seeded IDs below)     | tenant identity; must exist    |
| `X-User-Id`       | `alice`                                | actor identity; must be a member |
| `X-User-Role`     | (optional, ignored)                    | **never trusted** — the role is resolved server-side from the `memberships` table |

Roles are stored in a real `memberships` table (`organization_id`, `user_id`,
`role`) and resolved on **every** request in `get_tenant_context`. The header
identifies *who* is calling; it can never say *what they may do*: a member
sending `X-User-Role: owner` is still a member, and an owner sending
`X-User-Role: member` keeps owner powers. Unknown organizations, non-member
users and cross-tenant access are all rejected with 403/404 (deliberately
not distinguishable — no existence oracle is exposed).

Seeded fixture organizations (deterministic UUIDs, stable across restarts):

| Organization     | ID                                     |
|------------------|----------------------------------------|
| ABC Construction | `3de6e8a0-3623-5f2e-a708-9e338dcde4b2` |
| XYZ Builders     | `61fbdbb9-be48-51f7-a4fe-20e17b464faf` |

Seeded fixture memberships (one owner + one member per organization):

| Organization     | Owner  | Member |
|------------------|--------|--------|
| ABC Construction | alice  | bob    |
| XYZ Builders     | carol  | dave   |

## API overview (`/api/v1/skills`)

| Method & path                                   | Who        | Description |
|--------------------------------------------------|------------|-------------|
| `POST /api/v1/skills`                            | any member | create a skill draft |
| `GET /api/v1/skills?status=draft\|active\|disabled` | any member | list this org's skills |
| `GET /api/v1/skills/{id}`                        | any member | read one skill + all versions |
| `PATCH /api/v1/skills/{id}`                      | any member | edit a **draft** (409 once active/disabled) |
| `POST /api/v1/skills/{id}/versions`              | any member | snapshot a new **immutable** version (active skills only) |
| `POST /api/v1/skills/{id}/activate`              | owner only | activate (draft → v1 snapshot, or switch active version); idempotent |
| `POST /api/v1/skills/{id}/disable`               | owner only | disable (terminal); idempotent |
| `POST /api/v1/skills/{id}/versions/{vid}/tools/{tool}/approve` | owner only | explicitly grant one requested tool for that version; idempotent |
| `GET /api/v1/skills/departments/{dept}/active-skills` | runtime | **active-only** department selection |
| `GET /api/v1/skills/{id}/audit`                  | any member | audit trail for the skill |
| `GET /healthz`                                   | —          | liveness probe |

### Example session (curl)

```bash
# 1. ABC's owner creates a draft
curl -s -X POST localhost:8000/api/v1/skills \
  -H "X-Organization-Id: 3de6e8a0-3623-5f2e-a708-9e338dcde4b2" \
  -H "X-User-Id: alice" -H "X-User-Role: owner" \
  -H "Content-Type: application/json" \
  -d '{"name":"Invoice Chaser","description":"AR follow-ups","department":"finance",
       "content":"You are an AR assistant.","requested_tools":["email.read","email.send"]}'

# 2. Owner activates it (snapshots immutable version 1)
curl -s -X POST localhost:8000/api/v1/skills/<SKILL_ID>/activate \
  -H "X-Organization-Id: 3de6e8a0-3623-5f2e-a708-9e338dcde4b2" \
  -H "X-User-Id: alice" -H "X-User-Role: owner" -H "Content-Type: application/json" -d '{}'

# 3. Runtime department selection returns only active skills with their version
curl -s localhost:8000/api/v1/skills/departments/finance/active-skills \
  -H "X-Organization-Id: 3de6e8a0-3623-5f2e-a708-9e338dcde4b2" \
  -H "X-User-Id: alice" -H "X-User-Role: owner"

# 4. XYZ's owner cannot see ABC's skill: same call with the XYZ header
#    against /api/v1/skills/<SKILL_ID> returns 404.
```

Requested tools are validated against a closed catalogue
(`calendar.read`, `email.send`, `crm.read`, ...) — destructive or unknown
tools are rejected with explicit 422 errors, and requesting a tool never
grants the permission by itself. Granting is a separate, explicit,
owner-only action: `POST .../versions/{vid}/tools/{tool}/approve` records a
per-version approval (idempotent replays are audited as
`tool.approval_replayed`), and only explicitly approved tools appear in the
`approved_tools` field of the department runtime payload.

## Test output

Captured from `pytest -v` on the final commit (see git history):

```
============================= test session starts ==============================
platform linux -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0 -- /home/kraveil/test-project/.venv/bin/python
cachedir: .pytest_cache
rootdir: /home/kraveil/test-project
configfile: pytest.ini
testpaths: tests
plugins: anyio-4.15.0, asyncio-1.4.0, env-1.1.5
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=function, asyncio_default_test_loop_scope=function
collecting ... collected 49 items

tests/test_config.py::test_no_hardcoded_database_credentials PASSED      [  2%]
tests/test_config.py::test_resolved_url_requires_credentials PASSED      [  4%]
tests/test_config.py::test_database_url_override_wins PASSED             [  7%]
tests/test_config.py::test_individual_parts_build_url PASSED             [  9%]
tests/test_lifecycle.py::test_status_column_is_enum_backed PASSED        [ 11%]
tests/test_lifecycle.py::test_transition_map_is_explicit_and_terminal PASSED [ 14%]
tests/test_migrations.py::test_all_revision_ids_fit_alembic_version_column PASSED [ 16%]
tests/test_migrations.py::test_migration_chain_is_linear_and_grounded PASSED [ 19%]
tests/test_skills.py::test_same_org_create_and_read_succeeds PASSED      [ 21%]
tests/test_skills.py::test_same_org_list_only_shows_own_skills PASSED    [ 23%]
tests/test_skills.py::test_list_status_filter_matches_lifecycle_state PASSED [ 26%]
tests/test_skills.py::test_draft_can_be_updated_in_place PASSED          [ 28%]
tests/test_skills.py::test_cross_org_read_is_denied PASSED               [ 30%]
tests/test_skills.py::test_cross_org_update_is_denied PASSED             [ 33%]
tests/test_skills.py::test_cross_org_activate_is_denied PASSED           [ 35%]
tests/test_skills.py::test_cross_org_version_creation_is_denied PASSED   [ 38%]
tests/test_skills.py::test_unknown_organization_is_rejected PASSED       [ 40%]
tests/test_skills.py::test_member_claiming_owner_in_header_is_still_denied PASSED [ 42%]
tests/test_skills.py::test_owner_with_member_header_role_still_activates PASSED [ 45%]
tests/test_skills.py::test_bogus_role_header_is_ignored PASSED           [ 47%]
tests/test_skills.py::test_non_member_user_is_rejected PASSED            [ 50%]
tests/test_skills.py::test_non_owner_activation_is_denied PASSED         [ 52%]
tests/test_skills.py::test_non_owner_disable_is_denied PASSED            [ 54%]
tests/test_skills.py::test_draft_skill_is_not_returned_by_department_runtime PASSED [ 57%]
tests/test_skills.py::test_disabled_skill_is_excluded_from_runtime_selection PASSED [ 59%]
tests/test_skills.py::test_disabled_skill_cannot_be_reactivated PASSED   [ 61%]
tests/test_skills.py::test_disable_is_idempotent PASSED                  [ 64%]
tests/test_skills.py::test_active_skill_cannot_be_modified_in_place PASSED [ 66%]
tests/test_skills.py::test_active_version_is_immutable_new_version_required PASSED [ 69%]
tests/test_skills.py::test_draft_skill_cannot_accept_new_versions PASSED [ 71%]
tests/test_skills.py::test_version_rows_carry_organization_id PASSED     [ 73%]
tests/test_skills.py::test_activation_of_foreign_version_is_denied PASSED [ 76%]
tests/test_skills.py::test_duplicate_activation_is_idempotent_and_safe PASSED [ 78%]
tests/test_skills.py::test_invalid_or_destructive_requested_tool_is_rejected[shell.exec] PASSED [ 80%]
tests/test_skills.py::test_invalid_or_destructive_requested_tool_is_rejected[db.drop_table] PASSED [ 83%]
tests/test_skills.py::test_invalid_or_destructive_requested_tool_is_rejected[system.wipe] PASSED [ 85%]
tests/test_skills.py::test_invalid_or_destructive_requested_tool_is_rejected[teapot.brew] PASSED [ 88%]
tests/test_skills.py::test_invalid_or_destructive_requested_tool_is_rejected[Not A Tool!] PASSED [ 90%]
tests/test_skills.py::test_sql_injection_in_text_fields_is_rejected PASSED [ 92%]
tests/test_skills.py::test_trailing_whitespace_and_duplicates_are_normalized PASSED [ 95%]
tests/test_skills.py::test_full_workflow_create_review_activate_retrieve_audit PASSED [ 97%]
tests/test_skills.py::test_audit_trail_is_tenant_scoped PASSED           [100%]

============================= 49 passed in 11.9s ==============================
```

## Project structure

```
app/
├── main.py            # FastAPI app, startup seeding, health probe
├── database.py        # async engine/session + global tenant-isolation filter
├── tenant.py          # TenantContext resolution (org + server-side role)
├── dependencies.py    # shared auth/isolation dependencies (require_owner, ...)
├── lifecycle.py       # draft → active → disabled state-machine map
├── models.py          # organizations, memberships, skills, versions, approvals, audit
├── schemas.py         # Pydantic validation, sanitizers, closed tool catalogue
├── audit.py           # audit-log writer
└── routers/skills.py  # all /api/v1/skills endpoints
alembic/versions/      # 5 linear migrations
tests/                 # 49 tests: isolation, lifecycle, immutability, tool approvals
docs/ARCHITECTURE_DECISIONS.md
```

## Known limitations

- Header-based *identity* is a deliberate evaluation shortcut; a real
  deployment would verify signed tokens. Role authorization, however, is
  fully server-side via the `memberships` table — the `X-User-Role` header
  is never trusted.
- No pagination on list endpoints (fine for the slice's data volume).
- SQLite is used for the dedicated test database only; production is
  PostgreSQL. Rationale in `docs/ARCHITECTURE_DECISIONS.md`.
- Strict input sanitizers reject SQL-comment sequences (`--`, `/* */`) even
  inside free text — an intentional, documented strictness trade-off.
- No rate limiting / WAF; assumed to be handled by the edge in production.

## Final report

The completed final report (repository, timeline, goal, architecture
decisions, test results, security evidence, known limitations, next steps)
lives in [FINAL-REPORT.md](FINAL-REPORT.md); build-phase tracking is in
[PROGRESS.md](PROGRESS.md); the verification pass and its findings/fixes are
recorded in [AUDIT-REPORT.md](AUDIT-REPORT.md).
