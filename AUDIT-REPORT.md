# AUDIT-REPORT.md

Audited on: 2026-09-04 (third, post-late-fixes audit)
Repo / commit audited: `87ae402d48b44bb7b6750178e014155726c43ea4` (final code tree, pushed to https://github.com/Ayesha-Ramzan/Jarvis-AI-COO)

This is the **final audit**, run after the live-API review round found three
issues (one functional bug, two accuracy/process defects). Every claim below
was produced this session with a command that actually ran — no assumptions.
Areas verified correct by the independent live review (tenant isolation,
audit trail, Dockerfile, dependency pins) were **not modified**, per the
review instructions; their prior evidence stands.

## Findings from the live-API review — all fixed and verified

### F-7 (HIGHEST — functional bug): version switching on an active skill was broken

- **Reproduced from the review:** `activate_skill` routed *every*
  non-idempotent path through `can_transition(skill.status, ACTIVE)`;
  `TRANSITIONS[ACTIVE] = {DISABLED}` made `ACTIVE -> ACTIVE` return False, so
  activating a newly created v2 while active on v1 answered **409 "A disabled
  skill cannot be reactivated"** — the documented "switch active version"
  capability (spec minimum #6, "Activate an approved version") was dead code.
- **Fix** (commit `da7ce9e`): the state-machine gate now governs only genuine
  status transitions. A disabled skill is blocked by an explicit terminal-state
  guard (accurate message); draft -> active still consults `TRANSITIONS`; and
  switching the active version while the skill *stays* active takes its own
  explicit path — version ownership checked via `_get_version_or_404`, status
  unchanged, previously active version row never touched, audit event records
  `version_switch: true` and `previous_version_id`.
- **Live verification (real curl, uvicorn + Alembic-migrated SQLite, this
  session):**
  - create draft -> 201 (`skill_id=80c0271c-…`)
  - activate v1 -> 200, `active_version_id=1c7fc2bb-…`
  - `POST /{id}/versions` -> 201, v2 `77721100-…`
  - `POST /{id}/activate {"version_id": "77721100-…"}` -> **HTTP 200**, body
    `"status":"active"`, `"active_version_id":"77721100-da3f-4ff9-9e43-4f5206c314fd"`
  - audit trail shows the second `skill.activated` with `"version_switch":true`
    and `"previous_version_id":"1c7fc2bb-…`
  - disable -> 200; re-activate -> **409** `{"detail":"A disabled skill cannot be reactivated."}`
- **New tests** (the coverage that was missing): `test_active_skill_can_switch_to_new_version`
  (200, v2 active, v1 hash/name untouched, runtime serves v2, audit logged),
  `test_cross_org_version_switch_is_denied`, `test_activation_of_foreign_org_version_is_denied`.

### F-8: test suite was not hermetic against an ambient `.env`

- **Reproduced:** following the README quick start (`cp .env.example .env`)
  then `pytest -v` failed `test_no_hardcoded_database_credentials` and
  `test_resolved_url_requires_credentials`, because `Settings` always read
  `./.env` and `.env.example` bakes in `POSTGRES_USER=jarvis`.
- **Fix** (commit `87ae402`): `app/config.py` resolves `env_file` once at
  import — `None` when `ENVIRONMENT=test` (guaranteed by `pytest.ini` and
  `tests/conftest.py` before app modules import), `.env` otherwise. Non-test
  behavior is unchanged and documented.
- **Verification (real outputs, pasted in README):** `pytest -v` with `.env`
  present → **52 passed**; without `.env` → **52 passed**. The two credential
  tests still assert real Settings behavior (they construct a real `Settings`).

### F-9: FINAL-REPORT.md named a nonexistent commit SHA

- The previous value (`34467f3e…`) does not exist in history
  (`git cat-file -t` → not found). Fixed process: the SHA is now recorded as
  the last edit after all code/test/doc commits landed and were pushed, and
  the field states explicitly that the report commit is the repository's last
  commit (a commit cannot contain its own hash). Verifiable via
  `git cat-file -t <sha>` and `git log --oneline` on GitHub.

## Regression checks (re-run this session)

| Check | Result | Evidence |
|---|---|---|
| No committed secret / real data | PASS | `git log --all -p` credential-pattern scan: only `.env.example` placeholder `POSTGRES_PASSWORD=CHANGE_ME` and prior audit text; no `.env`/`*.db` tracked (`git ls-files`). |
| Suite green | PASS | `pytest -q` → **52 passed** (10 mandatory spec tests + isolation, lifecycle, immutability, version switching, idempotency, tool approvals, sanitization, config, migrations). |
| Tenant isolation untouched | PASS | `app/database.py` `with_loader_criteria` filter unchanged this round; cross-org switch/activate/read still 404 via suite tests run above. |
| Immutability untouched | PASS | No UPDATE path for `SkillVersion` added; switch test asserts v1 hash/name unchanged after the switch. |
| Disabled terminal state | PASS | Live curl: disable → 200, re-activate → 409 with accurate message; `test_disabled_skill_cannot_be_reactivated`. |
| Docs consistency | PASS | README badge/counts/captured outputs = 52; PROGRESS.md updated with the late-fixes section; FINAL-REPORT.md test count and migration range (0001-0005) synced. |

## Verdict

All three review findings fixed with live evidence; no regressions; 52/52
tests green in both hermeticity modes. Submission artifacts are consistent
with the pushed history.
