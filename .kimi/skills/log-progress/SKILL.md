---
name: log-progress
description: Refreshes PROGRESS.md with current build status — which phase is done, which mandatory tests pass, what decisions were made. Run this after finishing any phase of the Jarvis AI COO evaluation task, not just at the end of the session.
type: flow
---

# log-progress

Run after completing any phase from `AGENTS.md`'s 8-hour budget, or any time state feels stale.
Overwrite `PROGRESS.md` (don't append indefinitely — keep it current, not a diary).

## 1. Check real state, don't infer it

```
git log --oneline -10
git status
```

Run the actual test suite and capture real pass/fail counts — don't write "tests passing" from
memory of what should be passing.

## 2. Rewrite `PROGRESS.md`

Structure:

```
# PROGRESS.md

Start time: <filled in once, first session only>
Last updated: <timestamp, every run>

## Phase status
- [ ] Schema & domain model
- [ ] Auth & tenant scoping
- [ ] Core lifecycle routes
- [ ] Tests (10 mandatory)
- [ ] Docker Compose / .env.example / README
- [ ] Architecture note / limitations / final report

## Mandatory test checklist (from the spec — check off only what's actually green)
- [ ] Same-organization create/read succeeds
- [ ] Cross-organization read is denied
- [ ] Cross-organization update is denied
- [ ] Non-owner activation is denied
- [ ] Draft skill cannot execute or load as active
- [ ] Disabled skill is excluded from runtime selection
- [ ] Active version is immutable
- [ ] Duplicate activation request is safe and idempotent
- [ ] Invalid or destructive requested tool is rejected
- [ ] Audit record contains organization, actor, event, and version

## Decisions made
(one line each — e.g. "Postgres + SQLAlchemy + Alembic migrations, API-key-per-actor auth via
header, no JWT — keeps the auth surface small for an 8-hour scope")

## Open questions / risks
(anything uncertain enough to flag in "Known limitations" later)
```

## 3. Report

State plainly what changed since the last log — phases completed, tests newly green, any test
still red. If a test that was previously green is now red, say so — don't quietly drop it from
the checklist.

## 4. At the end of the build

Once every phase and every mandatory test is checked off, use the accumulated `PROGRESS.md`
content to fill out `FINAL-REPORT-TEMPLATE.md` — most of the fields (architecture decisions, tests
passed, known limitations) should already exist here rather than needing to be reconstructed from
memory under deadline pressure.
