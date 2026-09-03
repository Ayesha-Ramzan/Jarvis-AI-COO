# AUDIT-REPORT.md

Audited on: 2026-09-04T00:16:39+05:00
Repo / commit audited: local repo (no remote), `ff2345e7111d60e000836568fd4398401136a0dd` (2026-09-03 22:44:17 +0500)

Audit method: `.kimi/skills/audit/SKILL.md` followed step by step. All evidence below was
produced this session by actually running commands — the suite, a live server, and a clean
`docker compose up` — not by reading code and assuming behavior.

## 1. Hard constraints (automatic-rejection level)

| Check | Result | Evidence |
|---|---|---|
| No committed secret / real data | PASS (one low-severity flag, see findings F-6) | `git log --all -p` scanned full history: only credential-like match is `.env.example:10` → `POSTGRES_PASSWORD=CHANGE_ME` (placeholder). File-by-file secret-word scan across all 6 commits touches only `app/config.py`, `docker-compose.yml`, `.env.example`, `app/dependencies.py`, `README.md`. `.gitignore` includes `.env`; `git ls-files` shows no `.env`/secret/credential file tracked. `dev.db` is untracked and contains only fixture orgs. Flag: default `jarvis:jarvis` DB password hardcoded in `app/config.py:32-36` and `docker-compose.yml:5-6` — default dev credentials committed, not a real secret. |
| No cross-tenant leakage (live-tested, not just inspected) | PASS | Live server probes (SQLite, port 8001): XYZ owner GET/PATCH/activate of ABC's skill `be7f6df4…` → **404/404/404**; XYZ list → `[]`; XYZ read of ABC's audit trail → **404**. Repeated against the clean Docker Compose stack on PostgreSQL (port 18000): XYZ read of ABC's skill `45cfa59c…` → **404**. Tenant filter: `app/database.py:47-74` `do_orm_execute` listener applies `with_loader_criteria(organization_id == tenant)` to `Skill`, `SkillVersion` (via `SkillVersion.skill.has(Skill.organization_id == …)`), and `AuditLog` on every ORM SELECT. |
| No fake tests (assertions actually depend on real behavior) | PASS | Read `tests/test_skills.py` in full: every isolation test asserts a real status code (`assert response.status_code in (403, 404)` or `== 403`) AND re-fetches the victim resource to assert it is unchanged (e.g. lines 95-96, 104-105, 147-148). Immutability test asserts 409 + unchanged content (250-251). Idempotency test asserts identical `active_version_id` and exactly one `skill.activated` audit event (325-330). No assertion would pass against a broken implementation. |
| App actually starts (`docker compose up`, real output quoted) | PASS | Clean-start verified this session. Fresh project `jarvisaudit`, fresh volume: `Container jarvisaudit-db-1 Healthy`, `Container jarvisaudit-app-1 Started` → `curl localhost:18000/healthz` → `{"status":"ok","service":"JARVIS AI COO - Organization-Scoped Skill Registry","version":"1.0.0"}`, container `Up (healthy)`. App log: `Running upgrade -> 0001_initial_schema` (`Context impl PostgresqlImpl`) then `Uvicorn running on http://0.0.0.0:8000`. NOTE: on this shared machine ports 8000/5432 are occupied by other projects, so the audit run used an identical compose file with only the host ports remapped (15432/18000); no project file was modified. README documents `docker compose up --build`. |
| Active version never mutated in place | PASS | `PATCH /{id}` on an active skill → live **409** `"An active skill is immutable…"` (`app/routers/skills.py:257-263`). Test `test_active_skill_cannot_be_modified_in_place` and `test_active_version_is_immutable_new_version_required` (asserts v1 hash/content unchanged after v2 created). Grep of `app/`: no update path touches `SkillVersion` rows; only INSERTs (`routers/skills.py:340-351, 418-430`). |
| No automatic activation on creation | PASS | `create_skill_draft` sets `status="draft"` (`app/routers/skills.py:121`); live create returned `"status":"draft"`. Activation only via explicit `POST /{id}/activate`, guarded by `require_owner` (`skills.py:385`). |

## 2. Domain model non-negotiables

| Check | Result | Evidence |
|---|---|---|
| `organization_id` on every tenant-scoped table | PARTIAL (see F-1) | `skills` and `audit_logs` carry `organization_id` (migration `0001_initial_schema.py:43,98`; models `app/models.py:74,143`). `skill_versions` has **no** `organization_id` column (migration lines 70-92) — its tenancy derives from `skill_id → skills.organization_id`. Query-level isolation is still enforced for it: `with_loader_criteria(SkillVersion.skill.has(Skill.organization_id == tenant))` (`app/database.py:62-68`). Isolation holds (live 404s above); the literal column the spec names is absent on one of three tables. |
| Lifecycle is an enforced state machine, not a free-text field | PARTIAL (see F-2) | Values are bounded: `SkillStatus` enum exists (`app/models.py:43-46`) + DB `CHECK status IN ('draft','active','disabled')` (models 66-68; migration 54-56). Transitions are enforced in code per-route: draft→active / draft→disabled / active→version-switch / active→disabled / disabled→nothing (skills.py:257-269, 311-320, 388-392, 481-483). Grep shows status is only ever assigned the three literals. BUT: the ORM column is `String(32)` (not the enum type), the `SkillStatus` enum is never actually used at runtime, and there is no centralized explicit allowed-transition map — transition knowledge is implicit across route handlers. Behavior is correct; the "enum + explicit allowed transitions" letter is only half met. |
| Owner-only activation checked server-side | PARTIAL (see F-3) | The server-side check itself is real: `require_owner` (`app/dependencies.py:68-74`) raises 403 on every activate/disable call (skills.py:385, 478); live member-activation probe → **403** on both SQLite and Postgres stacks. BUT there is no organization *membership* model: role is self-asserted via the `X-User-Role` header (dependencies.py:32-49) and never verified against any membership record — any caller can claim `owner`. The spec explicitly requires "model organization membership with a role … and check the role server-side". Check: yes; membership model: missing. |
| Requested tools validated against an allow-list | PASS | `app/schemas.py:64-79` closed `ALLOWED_TOOLS` catalogue (12 entries); `sanitize_tools` (97-123) enforces `namespace.action` shape, rejects destructive fragments (43-60), rejects non-catalogue tools, dedups, caps at 16. Live: `["shell.exec"]` → **422**. Parametrized test over 5 bad tools (`test_invalid_or_destructive_requested_tool_is_rejected`). |
| Audit log has organization, actor, event, version on write | PARTIAL (see F-4) | `record_audit` (`app/audit.py:19-41`) writes `organization_id`, `actor_id`, `actor_role`, `event`, `version_id`, `version_hash`, `created_at`. Live Postgres row: `skill.draft_created | alice | owner | has_hash=f`; activation rows carry version_id + hash (test `test_full_workflow_create_review_activate_retrieve_audit` asserts all fields). GAP: idempotent replays write **no** audit row — `app/audit.py:5-7` docstring states this explicitly, and the activate/disable no-op paths (skills.py:394-399, 481-483) return without auditing. AGENTS.md: idempotent ops "should still be traceable in the audit trail". Deliberate ADR-3 documents the choice, but it contradicts the spec text. |

## 3. Minimum API capabilities

All routes under `/api/v1/skills` (`app/routers/skills.py`, mounted in `app/main.py:77`). Reachability confirmed both by the 29-test suite and live probes this session.

| Capability | Route/method | Reachable? |
|---|---|---|
| Create skill draft | `POST /api/v1/skills` | Yes — live 201 |
| List skills for current org | `GET /api/v1/skills?status=…` | Yes — live `[]` / `["ABC Skill"]` |
| Read one skill with versions | `GET /api/v1/skills/{id}` | Yes — live 200, `versions` included |
| Create new immutable version | `POST /api/v1/skills/{id}/versions` | Yes — test 201 v2 |
| Activate approved version | `POST /api/v1/skills/{id}/activate` | Yes — live 200, owner-only 403 |
| Disable a skill | `POST /api/v1/skills/{id}/disable` | Yes — live 200 → `disabled` |
| Retrieve active skills for a department | `GET /api/v1/skills/departments/{dept}/active-skills` | Yes — live returned active-only entries, disabled excluded |

## 4. Mandatory tests — real suite run

Command run: `.venv/bin/python -m pytest -v` (project venv, Python 3.14.7)
Result summary (actual output): `collected 29 items … 29 passed in 6.51s` (full `-v` listing matches README's captured run).

| # | Spec requirement | Test function | Result |
|---|---|---|---|
| 1 | Same-org create/read succeeds | `test_same_org_create_and_read_succeeds` | PASS |
| 2 | Cross-org read denied | `test_cross_org_read_is_denied` | PASS |
| 3 | Cross-org update denied | `test_cross_org_update_is_denied` | PASS |
| 4 | Non-owner activation denied | `test_non_owner_activation_is_denied` | PASS |
| 5 | Draft cannot execute/load as active | `test_draft_skill_is_not_returned_by_department_runtime` | PASS |
| 6 | Disabled skill excluded from runtime selection | `test_disabled_skill_is_excluded_from_runtime_selection` | PASS |
| 7 | Active version immutable | `test_active_version_is_immutable_new_version_required` (+ `test_active_skill_cannot_be_modified_in_place`) | PASS |
| 8 | Duplicate activation idempotent | `test_duplicate_activation_is_idempotent_and_safe` | PASS |
| 9 | Invalid/destructive tool rejected | `test_invalid_or_destructive_requested_tool_is_rejected[…]` (5 params) | PASS |
| 10 | Audit record has org, actor, event, version | `test_full_workflow_create_review_activate_retrieve_audit` | PASS |

## 5. Submission requirements

| Item | Present? | Notes |
|---|---|---|
| Source code | Yes | `app/` (9 modules + routers), `tests/` |
| Schema / migrations | Yes | `alembic/versions/0001_initial_schema.py`; verified applying live on fresh SQLite (`Running upgrade -> 0001_initial_schema`) and fresh Postgres via compose |
| Automated tests | Yes | 29 tests, all passing (run quoted above) |
| Docker Compose startup | Yes | Verified live from clean state this session (see §1) |
| `.env.example` (placeholders only) | Yes | Only `CHANGE_ME` placeholder; credentials not present |
| README with real, working API examples | Yes | Curl examples use the real seeded org UUIDs and real routes; spot-checked examples #1–#3 against the live server — payloads/routes match what the code accepts |
| Architecture decision note (substantive, not filler) | Yes | `docs/ARCHITECTURE_DECISIONS.md`, 7 ADRs covering real decisions (tenant filter mechanism, immutability approach, idempotency policy, 404-vs-403, strict sanitizers, Postgres-vs-SQLite) |
| Captured test output file | Yes | README §"Test output" contains the verbatim `pytest -v` run (matches this session's fresh run) |
| Known limitations, stated honestly | Yes | README §"Known limitations" (5 items, including the header-auth shortcut) |
| Meaningful commit history | Yes | 6 incremental commits: scaffolding → app → alembic → tests → docs → compose-fix |

## 6. Restrictions check

| Check | Result |
|---|---|
| No frontend code | PASS — `find` for `*.html/*.js/*.ts/*.tsx`: none |
| No external AI/model API calls | PASS — grep for `openai/anthropic/httpx./requests./aiohttp/urllib.request/...` in `app/` + `alembic/`: no matches; only network dep is FastAPI server stack |
| No cross-tenant admin bypass | PASS — no admin/superadmin route or role; role allowlist is exactly `{owner, member}` (`app/tenant.py:14-16`), enforced at `app/dependencies.py:45-49` |

## 7. Score estimate vs. real rubric

| Category | Max | Estimate | Why |
|---|---|---|---|
| Tenant isolation and authorization | 30 | 26 | Isolation is excellent and live-proven (global query filter, 404-no-oracle, live cross-org denials on two stacks). Deductions: no membership model — owner role is self-asserted via header (F-3), the spec's biggest explicit non-negotiable; `skill_versions` lacks its own `organization_id` (F-1). |
| Correct domain/version lifecycle | 20 | 16 | Lifecycle behavior correct and enforced (CHECK constraint, 409s, immutable versions, v1 snapshot on activation). Deductions: state machine not modeled as enum-backed column + explicit transition map (F-2); idempotent replays leave no audit trace (F-4). |
| Tests and failure handling | 20 | 19 | 29 real tests, all 10 mandatory items mapped and passing, including negative and sanitization cases. Minor: suite runs on SQLite only (justified in ADR-5 and exercised via Compose). |
| Code architecture/readability | 15 | 14 | Clean vertical slice, ContextVar + event-listener isolation, ADRs. Minor: transition logic scattered across routes rather than centralized. |
| Setup and documentation | 10 | 9 | Compose verified from clean state, README examples actually work, `.env.example` clean, captured output. Minor: README curl examples target port 8000 (correct for a clean machine — fine). |
| Git discipline and final report | 5 | 4 | 6 meaningful commits. `PROGRESS.md` is still the untouched template and `FINAL-REPORT-TEMPLATE.md` is unfilled (F-5) — content exists in README but the required artifacts are missing. |
| **Total** | **100** | **88** | |

## 8. Overall verdict

**Needs fixes before submission.** No automatic-rejection trigger was found — secrets clean, isolation live-verified on two stacks, no fake tests, compose starts clean, active versions immutable, no auto-activation. But five concrete findings should be closed first, in priority order:

- **F-3 (highest): No organization-membership model; owner role is self-asserted.** Add a `memberships` table (`organization_id`, `user_id`, `role`) seeded for the fixture orgs, resolve role from membership server-side in `get_tenant_context`, keep the header as identity only. This is the largest gap against the spec's explicit non-negotiable and costs the most marks.
- **F-4: Idempotent replays write no audit row.** Log a distinct event (e.g. `skill.activation_replayed`) on no-op replays without changing state, and update ADR-3 + the idempotency test to match. AGENTS.md requires idempotent ops to be "traceable in the audit trail".
- **F-2: State machine not explicit.** Back `Skill.status` with the `SkillStatus` enum (native ENUM or at least use the enum everywhere) and centralize an allowed-transition map (e.g. `TRANSITIONS = {"draft": {"active","disabled"}, "active": {"disabled"}, "disabled": set()}`) that activate/disable consult.
- **F-1: `skill_versions` has no `organization_id`.** Add the denormalized column (populated from the parent skill, included in the unique/tenant index) so every tenant-scoped table carries the ownership key literally.
- **F-5: `PROGRESS.md` untouched, `FINAL-REPORT-TEMPLATE.md` unfilled.** Fill both per the `log-progress` skill and template (content can be sourced from README; commit).
- **F-6 (minor, hygiene): hardcoded default DB credentials** (`jarvis:jarvis` in `app/config.py:32-36` and `docker-compose.yml`). Make the config default empty and require env, and/or document in Known limitations; also consider gitignoring `*.db`.
