---
name: audit
description: Runs a full retroactive verification pass of the Jarvis AI COO evaluation submission against every requirement in AGENTS.md. Use this when code already exists and needs to be checked against the spec, not built from scratch — every item requires real evidence (a command actually run, a file actually read), never an assumption.
type: flow
---

# audit — retroactive verification pass

This skill exists for one situation: the code was already written, possibly without `AGENTS.md`
loaded during the build. Nothing gets marked PASS here because it "looks right" — every line item
below needs a command that was actually run, or a file that was actually opened and quoted, this
session. Guessing defeats the entire point of the audit.

Produce the final output using `AUDIT-REPORT-TEMPLATE.md`'s structure: every checklist line gets
`PASS`, `FAIL`, or `PARTIAL`, plus one line of concrete evidence (a file path + line range, a
command and its real output, a test name). No evidence, no PASS.

## 1. Baseline — confirm what actually exists

```
git log --oneline --all
git status
find . -name "*.py" -not -path "*/venv/*" -not -path "*/.git/*" | sort
```

Read the actual directory structure before checking anything else — don't assume a conventional
layout.

## 2. Hard constraints (automatic-rejection level — check these first and flag loudly if any fail)

- **No committed secret or real data.** `git log -p | grep -iE "(api[_-]?key|secret|password|token)\s*=" ` across full history, not just the current tree — a secret committed and later removed still counts. Check `.env.example` has placeholders only, and that `.env` (if it exists locally) is gitignored.
- **No cross-tenant leakage.** Find every query/service function that touches skills, skill versions, or the audit log. For each one, confirm `organization_id` is part of the filter — either directly or inherited from an already-scoped parent object. List any that aren't. Then actually run (or write and run, if missing) a live request as Organization A attempting to read/update/activate an Organization B skill, and confirm it's denied, not just "should be" denied by code inspection.
- **No fake tests.** Open every test file. For a sample of the 10 mandatory tests, check the assertion actually depends on the behavior under test — e.g. a cross-org-denied test must assert a 403/404, not just that the call didn't crash. Flag any test that would pass even if the feature were broken.
- **App actually starts.** Run `docker compose up` (or the documented equivalent) from a clean state and hit a real endpoint. Quote the actual output. Don't infer this from the compose file existing.
- **Active version immutable.** Search for any code path that runs `UPDATE` against an active skill version's content. Confirm the only way to change behavior is creating a new version row.
- **No automatic activation.** Confirm skill creation never sets status to `active` without a separate, explicit activation call.

## 2b. Stack requirement check

- Confirm which database is actually in use (check the connection string / driver, not just the
  ORM config). If it's SQLite rather than the preferred PostgreSQL, confirm the architecture
  decision note contains an actual written justification for that choice — its absence isn't a
  minor documentation gap, the spec makes SQLite conditional on it being present.

## 3. Domain model non-negotiables

- `organization_id` present on every tenant-scoped table (skills, skill_versions, audit_log, and anything else tenant-owned) — check the actual schema/migration files, quote the column definitions.
- Lifecycle is a real state machine (draft → active → disabled) with enforced transitions, not a free-text/unchecked status field.
- Organization membership has a role (owner/member or equivalent), and activation checks that role server-side — find the actual check in code, don't assume it exists because a role column exists.
- Requested tools are validated against an explicit allow-list — find the validation code, confirm it actually rejects something not on the list.
- Audit log entries are written for version creation and activation, each containing organization, actor, event type, and version — quote an actual row shape or the insert statement.

## 4. Minimum API capabilities — confirm each exists and is reachable

- Create a skill draft
- List skills for the current organization
- Read one skill with its versions
- Create a new immutable version
- Activate an approved version
- Disable a skill
- Retrieve active skills for a department

For each, note the actual route path and method.

## 5. Mandatory automated tests — run the real suite

```
pytest -v   # or the project's actual test command — find it, don't guess
```

Quote the real pass/fail summary. Then map each of the 10 spec items to an actual test function
by name:
1. Same-organization create/read succeeds
2. Cross-organization read is denied
3. Cross-organization update is denied
4. Non-owner activation is denied
5. Draft skill cannot execute or load as active
6. Disabled skill is excluded from runtime selection
7. Active version is immutable
8. Duplicate activation request is safe and idempotent
9. Invalid or destructive requested tool is rejected
10. Audit record contains organization, actor, event, and version

Any spec item with no corresponding test is a FAIL, regardless of whether the underlying behavior
happens to work.

## 6. Submission requirements — confirm presence, not just plausibility

- Source code ✓/✗
- Database schema and/or migrations ✓/✗
- Automated tests ✓/✗
- Docker Compose startup ✓/✗ (already verified live in step 2)
- `.env.example` with placeholders only ✓/✗
- README with setup instructions and real, working API examples — actually try the documented curl/httpie examples against a running instance if time allows, or at minimum confirm the routes and payloads match what the code accepts
- Architecture decision note ✓/✗ — and whether it actually explains real decisions (Postgres vs SQLite, auth approach, immutability approach) rather than being generic filler
- Test output captured to a file (not just tests existing) ✓/✗
- Known limitations documented honestly ✓/✗
- Meaningful commit history — `git log --oneline` should show incremental commits across the build, not one giant commit at the end

## 7. Restrictions check

- No frontend code present
- No external AI/model API calls anywhere in the code
- No cross-tenant admin bypass route of any kind

## 8. Score estimate against the real rubric

Give an honest self-estimate per category, grounded in what was actually found in steps 2–7, not
a round number:

| Category | Max | Estimate | Why |
|---|---|---|---|
| Tenant isolation and authorization | 30 | | |
| Correct domain/version lifecycle | 20 | | |
| Tests and failure handling | 20 | | |
| Code architecture/readability | 15 | | |
| Setup and documentation | 10 | | |
| Git discipline and final report | 5 | | |

## 9. Output

Write the full checklist to `AUDIT-REPORT.md` at the repo root using `AUDIT-REPORT-TEMPLATE.md`'s
structure, then print the same content in the response. Do not soften a FAIL into a PARTIAL to
make the summary look better — the whole point of this pass is an accurate picture, not a
reassuring one.
