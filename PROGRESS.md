# PROGRESS.md

Start time: 2026-09-03 (initial build); audit + fixes pass 2026-09-04
Last updated: 2026-09-04T06:10+05:00 (late-fixes pass)

## Phase status
- [x] Schema Schema & domain model (organizations, memberships, skills, skill_versions, audit_log — migrations 0001-0005) domain model (organizations, memberships, skills, skill_versions, tool_approvals, audit_log - migrations 0001-0006; PG trigger enforces version immutability)
- [x] Auth & tenant scoping (header identity + membership-resolved roles, ContextVar + global query filter)
- [x] Core lifecycle routes (draft create/update, list, read+versions, immutable versions, owner-only activate/disable, department runtime selection)
- [x] Tests (10 mandatory + boundary/sanitization/config suite: 66 tests + 1 PG-only trigger test, all green — run 2026-09-04)
- [x] Docker Compose / .env.example / README (compose verified live from clean state on PostgreSQL 16)
- [x] Architecture note / limitations / final report (7 ADRs, FINAL-REPORT.md, known limitations in README)

## Mandatory test checklist (from the spec — all actually green, `pytest -q`: 49 passed)
- [x] Same-organization create/read succeeds — test_same_org_create_and_read_succeeds
- [x] Cross-organization read is denied — test_cross_org_read_is_denied
- [x] Cross-organization update is denied — test_cross_org_update_is_denied
- [x] Non-owner activation is denied — test_non_owner_activation_is_denied (+ test_member_claiming_owner_in_header_is_still_denied)
- [x] Draft skill cannot execute/load as active — test_draft_skill_is_not_returned_by_department_runtime
- [x] Disabled skill is excluded from runtime selection — test_disabled_skill_is_excluded_from_runtime_selection
- [x] Active version is immutable — test_active_version_is_immutable_new_version_required (+ in-place 409 test)
- [x] Duplicate activation request is safe/idempotent — test_duplicate_activation_is_idempotent_and_safe (replays audited as skill.activation_replayed)
- [x] Invalid/destructive tool rejected — test_invalid_or_destructive_requested_tool_is_rejected (5 parametrized cases)
- [x] Audit record contains organization, actor, event, version — test_full_workflow_create_review_activate_retrieve_audit

## Decisions made
- Postgres 16 + SQLAlchemy 2.0 async + Alembic in production/compose; SQLite in-memory only for the dedicated test DB (ADR-5).
- Tenant isolation via ContextVar + `do_orm_execute`/`with_loader_criteria` global filter; cross-tenant ids return 404, never an existence oracle (ADR-1, ADR-6).
- Header identity (`X-Organization-Id`, `X-User-Id`) is the evaluation auth shortcut; roles are resolved server-side from the `memberships` table — the `X-User-Role` header is never trusted (F-3 fix).
- Immutable versioning: draft editable; activation snapshots v1; active skills only change via new SkillVersion + explicit activation; versions never updated (ADR-2).
- Lifecycle as a real state machine: enum-backed `SkillStatus` column (native ENUM on PG) + explicit TRANSITIONS map in app/lifecycle.py (F-2 fix).
- Idempotent replays change no state but write distinct `*_replayed` audit events (F-4 fix, ADR-3).
- Closed tool catalogue + destructive-fragment rejection + SQLi sanitizers as defense in depth (ADR-4, ADR-7).
- DB credentials required from the environment, no hardcoded defaults; compose db not published to host (F-6 fix).
- `skill_versions` carries denormalized `organization_id` alongside join-based isolation (F-1 fix).

## Open questions / risks
- None blocking. Honest residual: header-based identity is still a stand-in for signed-token auth (documented in Known limitations).
- On the shared dev machine, ports 8000/5432 belong to other projects; compose verification used remapped host ports. On a clean machine `cp .env.example .env && docker compose up --build` uses the standard ports.

## Late-fixes pass (2026-09-04, live-API review round)
- [x] Fix 1 (real bug): activating a NEW version of an already-active skill returned 409 —
  the unconditional `can_transition(ACTIVE, ACTIVE)` gate made the documented
  "switch active version" path unreachable. Fixed: the state-machine gate now governs
  only genuine status transitions (draft→active; disabled→active blocked); switching
  versions while active has its own explicit, audited path (`version_switch: true`,
  `previous_version_id` recorded). Verified live: curl 200 + correct `active_version_id`;
  disabled-skill reactivation still 409. New tests: switch success (v1 row untouched,
  runtime serves v2, audit logged), cross-org switch denied, foreign-org version denied.
- [x] Fix 2 (hermeticity): `Settings` no longer reads an ambient `.env` when
  `ENVIRONMENT=test` (pytest.ini/conftest guarantee it). Verified: `pytest -v` 52/52 both
  with `.env` present (README quick start leaves one) and without — outputs in README.
- [x] Fix 3 (artifact accuracy): FINAL-REPORT.md records the real, existing final commit
  SHA (previous value named a commit not present in history).
- Suite now 66 tests + 1 PG-only trigger test, all green on SQLite test DB; PostgreSQL remains the reported
  source of truth via the compose stack and its `test` service.


## 100/100 hardening pass (2026-09-04)
- [x] Signed bearer-token auth (HMAC-SHA256) — identity-only claims, role still server-resolved; 6 new tests.
- [x] DB-enforced version immutability — PostgreSQL trigger (migration 0006) rejects UPDATE/DELETE on `skill_versions`.
- [x] CI on both backends — `.github/workflows/tests.yml` runs the suite on SQLite and on a real PostgreSQL 16 service.
- [x] Pagination + rate limiting — `limit`/`offset` + `X-Total-Count` on all list endpoints; sliding-window per-identity 429 with `Retry-After`; 6 new tests.
- Test source of truth: 66 passing + 1 PG-only trigger test. PostgreSQL is exercised in CI; SQLite remains the fast default for local development.
