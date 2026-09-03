# JARVIS AI COO — Organization-Scoped Skill Registry (Vertical Slice)

A privacy-first, multi-tenant FastAPI backend where organizations create,
review, version, activate and disable custom AI COO skills with strict
organization-level isolation. Organization A can never read, modify or
activate Organization B's data.

- **Framework:** FastAPI (Python 3.12+)
- **Database:** PostgreSQL 16 via SQLAlchemy 2.0 async sessions + Alembic migrations
- **Tests:** pytest + pytest-asyncio + pytest-env (SQLite in-memory test DB)
- **Run:** production-grade multi-stage Dockerfile + docker-compose (app + managed PostgreSQL)

## Architecture in one paragraph

Every request resolves a `TenantContext` from headers (`X-Organization-Id`,
`X-User-Id`, `X-User-Role`) and stores it in a `contextvars.ContextVar`. A
SQLAlchemy `do_orm_execute` session event then transparently appends
`organization_id = <tenant>` criteria (`with_loader_criteria`) to **every**
ORM query for tenant-owned models, so no router hand-writes tenant filters
and cross-tenant rows are invisible by construction (404, never leakage).
Skills follow an immutable lifecycle: `draft` is editable; `active` can never
be modified in place — changes are new immutable `SkillVersion` snapshots
that must be explicitly activated by the organization owner; `disabled` is
terminal and excluded from runtime selection. Every real state transition
writes an `audit_logs` row with organization, actor, event, timestamp and
version hash. See [docs/ARCHITECTURE_DECISIONS.md](docs/ARCHITECTURE_DECISIONS.md)
for the reasoning and trade-offs.

## Quick start (Docker)

```bash
docker compose up --build
```

This starts PostgreSQL, runs `alembic upgrade head`, seeds the two fixture
organizations (idempotently) and serves the API on http://localhost:8000.
Interactive docs: http://localhost:8000/docs

## Local development (without Docker)

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # then edit values
alembic upgrade head            # create schema
uvicorn app.main:app --reload   # seeds fixtures on startup
```

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
| `X-User-Id`       | `alice`                                | actor identity (audit log)     |
| `X-User-Role`     | `owner` or `member`                    | only `owner` activates/disables |

Unknown organizations and unknown roles are rejected with 403 (deliberately
not distinguishable — no existence oracle is exposed).

Seeded fixture organizations (deterministic UUIDs, stable across restarts):

| Organization     | ID                                     |
|------------------|----------------------------------------|
| ABC Construction | `3de6e8a0-3623-5f2e-a708-9e338dcde4b2` |
| XYZ Builders     | `61fbdbb9-be48-51f7-a4fe-20e17b464faf` |

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
grants the permission by itself.

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
collecting ... collected 29 items

tests/test_skills.py::test_same_org_create_and_read_succeeds PASSED      [  3%]
tests/test_skills.py::test_same_org_list_only_shows_own_skills PASSED    [  6%]
tests/test_skills.py::test_draft_can_be_updated_in_place PASSED          [ 10%]
tests/test_skills.py::test_cross_org_read_is_denied PASSED               [ 13%]
tests/test_skills.py::test_cross_org_update_is_denied PASSED             [ 17%]
tests/test_skills.py::test_cross_org_activate_is_denied PASSED           [ 20%]
tests/test_skills.py::test_cross_org_version_creation_is_denied PASSED   [ 24%]
tests/test_skills.py::test_unknown_organization_is_rejected PASSED       [ 27%]
tests/test_skills.py::test_invalid_role_header_is_rejected PASSED        [ 31%]
tests/test_skills.py::test_non_owner_activation_is_denied PASSED         [ 34%]
tests/test_skills.py::test_non_owner_disable_is_denied PASSED            [ 37%]
tests/test_skills.py::test_draft_skill_is_not_returned_by_department_runtime PASSED [ 41%]
tests/test_skills.py::test_disabled_skill_is_excluded_from_runtime_selection PASSED [ 44%]
tests/test_skills.py::test_disabled_skill_cannot_be_reactivated PASSED   [ 48%]
tests/test_skills.py::test_disable_is_idempotent PASSED                  [ 51%]
tests/test_skills.py::test_active_skill_cannot_be_modified_in_place PASSED [ 55%]
tests/test_skills.py::test_active_version_is_immutable_new_version_required PASSED [ 58%]
tests/test_skills.py::test_draft_skill_cannot_accept_new_versions PASSED [ 62%]
tests/test_skills.py::test_activation_of_foreign_version_is_denied PASSED [ 65%]
tests/test_skills.py::test_duplicate_activation_is_idempotent_and_safe PASSED [ 68%]
tests/test_skills.py::test_invalid_or_destructive_requested_tool_is_rejected[shell.exec] PASSED [ 72%]
tests/test_skills.py::test_invalid_or_destructive_requested_tool_is_rejected[db.drop_table] PASSED [ 75%]
tests/test_skills.py::test_invalid_or_destructive_requested_tool_is_rejected[system.wipe] PASSED [ 79%]
tests/test_skills.py::test_invalid_or_destructive_requested_tool_is_rejected[teapot.brew] PASSED [ 82%]
tests/test_skills.py::test_invalid_or_destructive_requested_tool_is_rejected[Not A Tool!] PASSED [ 86%]
tests/test_skills.py::test_sql_injection_in_text_fields_is_rejected PASSED [ 89%]
tests/test_skills.py::test_trailing_whitespace_and_duplicates_are_normalized PASSED [ 93%]
tests/test_skills.py::test_full_workflow_create_review_activate_retrieve_audit PASSED [ 96%]
tests/test_skills.py::test_audit_trail_is_tenant_scoped PASSED           [100%]

============================== 29 passed in 5.27s ==============================
```

## Known limitations

- Header-based authentication is a deliberate evaluation shortcut; a real
  deployment would verify signed tokens and map them to organization + role.
- No pagination on list endpoints (fine for the slice's data volume).
- SQLite is used for the dedicated test database only; production is
  PostgreSQL. Rationale in `docs/ARCHITECTURE_DECISIONS.md`.
- Strict input sanitizers reject SQL-comment sequences (`--`, `/* */`) even
  inside free text — an intentional, documented strictness trade-off.
- No rate limiting / WAF; assumed to be handled by the edge in production.

## Final report

- **Repository URL:** (push target for this repo)
- **Start time:** 2026-09-03
- **Finish time:** 2026-09-03
- **Approximate hours:** (tracked by the developer)
- **Final commit SHA:** see `git log -1 --oneline`
- **Goal achieved:** yes — full lifecycle with tenant isolation, immutable
  versioning, owner-only activation, runtime selection, auditability
- **Tests passed:** 100% (see "Test output" above)
- **Security/isolation evidence:** cross-tenant requests return 404 with no
  existence oracle; non-owner mutation paths return 403; active versions are
  immutable (409 + versioned replacement); destructive tools rejected at 422
- **What I would implement next:** signed-token auth, pagination, optimistic
  concurrency (ETags), Prometheus metrics, outbox-based audit streaming
- **AI tools used:** Kimi Code CLI (assistant pair-programming)
