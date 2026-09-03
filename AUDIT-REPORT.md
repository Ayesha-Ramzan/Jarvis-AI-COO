# AUDIT-REPORT.md

Audited on: 2026-09-04T04:01:35+05:00
Repo / commit audited: `2f4e6b0` (final tree). Live evidence (suite, compose stack, probes) gathered at `8a81fa1`; commits after that are docs/tests/polish only, re-verified at `2f4e6b0` with 42/42 tests green.

This is the **second, post-fix audit**, run per `.kimi/skills/audit/SKILL.md` in full
after all six findings (F-1..F-6) from the first audit were fixed. It also caught and
fixed one additional real bug the first audit could not see (see note on migration
revision IDs in §1). All evidence below was produced this session with real commands.

## 1. Hard constraints (automatic-rejection level)

| Check | Result | Evidence |
|---|---|---|
| No committed secret / real data | PASS | Full-history scan: `git log --all -p` for credential patterns. Current tree: no `jarvis:jarvis`, no password literals — `app/config.py` defaults are empty strings and `resolved_database_url` raises without env credentials; docker-compose requires `POSTGRES_PASSWORD` via `${...:?}` interpolation. `.env.example` placeholders only (`CHANGE_ME`); `.env` gitignored; `*.db` gitignored; `git ls-files` shows no secret/db files. Honest note: historical commits b672b4e..ff2345e contained a hardcoded *default dev* password (`jarvis`), removed in fix(F-6) — never a real credential or customer data. |
| No cross-tenant leakage (live-tested, not just inspected) | PASS | Live probes against the clean PostgreSQL compose stack (2026-09-04): XYZ owner reads ABC's skill `28564413…` → **404**; ABC member bob activating (even claiming `X-User-Role: owner`) → **403**; non-member eve → **403**; cross-org audit read denied in suite (`test_audit_trail_is_tenant_scoped`). Global filter: `app/database.py` `do_orm_execute` + `with_loader_criteria` on Skill, SkillVersion (join + direct org column), AuditLog. |
| No fake tests (assertions actually depend on real behavior) | PASS | Re-read all 42 tests after the fixes: isolation tests assert real status codes AND re-fetch victims to assert untouched state; the F-3 tests prove the membership is the role source (member+owner-header → 403; owner+member-header → 200); migration tests parse the actual migration files; config tests instantiate real Settings. None would pass against the old broken behavior. |
| App actually starts (`docker compose up`, real output quoted) | PASS | Clean start this session, fresh volume: `Container jarvisaudit2-db-1 Healthy`, `Container jarvisaudit2-app-1 Started`, `curl localhost:18000/healthz` → `{"status":"ok",...}` → container `(healthy)`. App log: migrations 0001→0004 applied on `PostgresqlImpl`; native enum verified: `pg_enum` for `skillstatus` = draft/active/disabled; memberships seeded (alice/owner, bob/member, carol/owner, dave/member). NOTE: the first clean-start attempt exposed a real bug — revision id `0003_skill_versions_organization_id` (38 chars) overflowed alembic's `version_num VARCHAR(32)` on Postgres (`StringDataRightTruncationError`) and rolled the migration back; SQLite could not catch this. Fixed by shortening revision ids + a regression test (`tests/test_migrations.py`); re-verified clean-start afterwards. Ports remapped to 18000 on this shared machine only. |
| Active version never mutated in place | PASS | Live: PATCH on active skill → **409** `"An active skill is immutable…"`; suite: `test_active_skill_cannot_be_modified_in_place`, `test_active_version_is_immutable_new_version_required` (v1 hash/content unchanged after v2). No UPDATE path exists for SkillVersion rows. |
| No automatic activation on creation | PASS | Live create → `status` `draft`; only `POST /{id}/activate` (owner-gated via membership-resolved role) transitions to active. |

## 2. Domain model non-negotiables

| Check | Result | Evidence |
|---|---|---|
| `organization_id` on every tenant-scoped table | PASS (F-1 fixed) | `skills`, `skill_versions` (added in 0003, backfilled, NOT NULL, indexed — migration verified on populated SQLite), `audit_logs`, plus `memberships` all carry `organization_id`. Query isolation uses both the join-based loader criteria and the direct column (defense in depth). Test: `test_version_rows_carry_organization_id`. |
| Lifecycle is an enforced state machine, not a free-text field | PASS (F-2 fixed) | `Skill.status` is `Mapped[SkillStatus]` backed by `sqlalchemy.Enum` (native `skillstatus` ENUM on Postgres — confirmed in `pg_enum`; VARCHAR+CHECK on SQLite). Explicit `TRANSITIONS` map in `app/lifecycle.py` (draft→{active,disabled}, active→{disabled}, disabled→∅) consulted by activate/disable. Tests: `test_status_column_is_enum_backed`, `test_transition_map_is_explicit_and_terminal`, live 409 on reactivating a disabled skill. |
| Owner-only activation checked server-side | PASS (F-3 fixed) | Real membership model: `memberships` table (composite PK `(organization_id, user_id)`, role CHECK), migration 0002, seeded one owner + one member per fixture org. `get_tenant_context` resolves role from the membership row; the `X-User-Role` header is accepted but never consulted. Live: bob+`X-User-Role: owner` → 403; alice+`X-User-Role: member` → 200. Tests: `test_member_claiming_owner_in_header_is_still_denied`, `test_owner_with_member_header_role_still_activates`, `test_non_member_user_is_rejected`. |
| Requested tools validated against an allow-list | PASS | `app/schemas.py` closed 12-entry `ALLOWED_TOOLS`, `namespace.action` shape, destructive-fragment blocklist, dedup, cap 16. Live: `["shell.exec"]` → **422**; 5 parametrized rejection tests. |
| Audit log has organization, actor, event, version on write | PASS (F-4 fixed) | `record_audit` writes org, actor id+role, event, version id, version hash, timestamp. Live audit trail on Postgres: `skill.draft_created`, `skill.version_created` (hash fcdb…), `skill.activated` (same hash), `skill.activation_replayed` (same hash) — idempotent replays now leave a distinct trace without changing state. Test: `test_duplicate_activation_is_idempotent_and_safe` asserts exactly one real activation + one replay event bound to the active version. |

## 3. Minimum API capabilities

All under `/api/v1/skills` (`app/routers/skills.py`); reachability confirmed live on the Postgres stack and by the suite.

| Capability | Route/method | Reachable? |
|---|---|---|
| Create skill draft | `POST /api/v1/skills` | Yes — live 201 (status `draft`) |
| List skills for current org | `GET /api/v1/skills?status=…` | Yes — tenant-scoped live + suite |
| Read one skill with versions | `GET /api/v1/skills/{id}` | Yes — live 200 with `versions` |
| Create new immutable version | `POST /api/v1/skills/{id}/versions` | Yes — suite 201 v2 |
| Activate approved version | `POST /api/v1/skills/{id}/activate` | Yes — live 200 (owner-only 403) |
| Disable a skill | `POST /api/v1/skills/{id}/disable` | Yes — live 200 → `disabled` |
| Retrieve active skills for a department | `GET /api/v1/skills/departments/{dept}/active-skills` | Yes — live returned active-only; `[]` after disable |

## 4. Mandatory tests — real suite run

Command run: `.venv/bin/python -m pytest -v`
Result summary (actual output): `collected 42 items … 42 passed in 11.85s` (full listing captured in README "Test output").

| # | Spec requirement | Test function | Result |
|---|---|---|---|
| 1 | Same-org create/read succeeds | `test_same_org_create_and_read_succeeds` | PASS |
| 2 | Cross-org read denied | `test_cross_org_read_is_denied` | PASS |
| 3 | Cross-org update denied | `test_cross_org_update_is_denied` | PASS |
| 4 | Non-owner activation denied | `test_non_owner_activation_is_denied` + `test_member_claiming_owner_in_header_is_still_denied` | PASS |
| 5 | Draft cannot execute/load as active | `test_draft_skill_is_not_returned_by_department_runtime` | PASS |
| 6 | Disabled skill excluded from runtime selection | `test_disabled_skill_is_excluded_from_runtime_selection` | PASS |
| 7 | Active version immutable | `test_active_version_is_immutable_new_version_required` | PASS |
| 8 | Duplicate activation idempotent | `test_duplicate_activation_is_idempotent_and_safe` | PASS |
| 9 | Invalid/destructive tool rejected | `test_invalid_or_destructive_requested_tool_is_rejected[…]` (5 params) | PASS |
| 10 | Audit record has org, actor, event, version | `test_full_workflow_create_review_activate_retrieve_audit` | PASS |

## 5. Submission requirements

| Item | Present? | Notes |
|---|---|---|
| Source code | Yes | `app/` (10 modules + routers), `tests/` (4 files, 42 tests) |
| Schema / migrations | Yes | Alembic 0001-0004, chain verified linear by test; applied live on fresh SQLite and fresh Postgres (including enum type) |
| Automated tests | Yes | 42 passing, run quoted above |
| Docker Compose startup | Yes | Verified live from clean state this session (twice — second after the revision-id fix) |
| `.env.example` (placeholders only) | Yes | `CHANGE_ME` only; documents that compose requires the password |
| README with real, working API examples | Yes | Examples re-validated against the live stack; curl payloads match the current API |
| Architecture decision note (substantive, not filler) | Yes | `docs/ARCHITECTURE_DECISIONS.md`, 7 ADRs incl. updated ADR-3 (replay auditing) |
| Captured test output file | Yes | README §"Test output" = verbatim fresh `pytest -v` run (42 tests) |
| Known limitations, stated honestly | Yes | README §"Known limitations" (5 items) |
| Meaningful commit history | Yes | incremental commits across build, audit, per-finding fixes (F-3, F-1, F-2, F-4, F-6, F-5) and the migration-id fix — see git log |
| PROGRESS.md / FINAL-REPORT.md | Yes (F-5 fixed) | Filled with real state; FINAL-REPORT.md follows the template |

## 6. Restrictions check

| Check | Result |
|---|---|
| No frontend code | PASS — `find` for `*.html/*.js/*.ts/*.tsx`: none |
| No external AI/model API calls | PASS — grep over `app/` + `alembic/`: 0 matches |
| No cross-tenant admin bypass | PASS — role vocabulary is exactly `{owner, member}` enforced by membership rows; no admin route exists |

## 7. Score estimate vs. real rubric

| Category | Max | Estimate | Why |
|---|---|---|---|
| Tenant isolation and authorization | 30 | 29 | Global query filter + no-oracle 404s, live-proven on two stacks; membership-backed server-side role resolution with a test proving the header is not trusted; denormalized org key on all tenant tables. Residual: header identity is still a stand-in for signed tokens (acknowledged limitation). |
| Correct domain/version lifecycle | 20 | 20 | Enum-backed state machine with an explicit transition map; immutable append-only versions with hashes; owner-only activation; disabled terminal and excluded from runtime; idempotent replays safe AND audited. All live-verified. |
| Tests and failure handling | 20 | 19 | 42 real tests covering all 10 mandatory items plus boundary, sanitization, lifecycle-machine, migration-chain and config cases; the suite once caught a Postgres-only migration bug the code review missed. Minor: tests run on SQLite (justified, and Postgres exercised via compose). |
| Code architecture/readability | 15 | 14 | Clean vertical slice; single-responsibility modules; isolation, lifecycle and auditing each live in one place. Minor: transition knowledge now centralized but route code still carries message wording per branch. |
| Setup and documentation | 10 | 9 | Compose verified clean-start twice; README examples work; `.env.example` clean; ADRs substantive; captured output fresh. Minor: on this shared machine the documented ports needed remapping (environment, not project). |
| Git discipline and final report | 5 | 5 | 16 meaningful commits including per-finding fixes referencing F-1..F-6; PROGRESS.md, FINAL-REPORT.md, AUDIT-REPORT.md all present and current. |
| **Total** | **100** | **96** | |

## 8. Overall verdict

**Ready to submit** after the docs/report commit. All six findings from the first
audit are closed with dedicated tests and per-finding commits, and the re-audit found
no remaining automatic-rejection trigger: no secrets (current tree; the old default
dev password exists only in superseded history), no cross-tenant leakage (live-probed),
no fake tests, the app starts clean from Docker Compose on PostgreSQL, active versions
are immutable, and activation is owner-only backed by a real membership table. The
re-audit additionally caught a genuine PostgreSQL-only migration failure (revision ID
longer than alembic's `version_num VARCHAR(32)`) that the SQLite test suite could not
detect — fixed, regression-tested, and re-verified with a clean compose start.

Residual honest items (documented in README Known limitations, none blocking):
header-based identity is an evaluation shortcut (roles, however, are server-side);
tests run on SQLite with PostgreSQL covered by migrations + compose; no pagination or
rate limiting.
