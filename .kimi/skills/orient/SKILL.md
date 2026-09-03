---
name: orient
description: Invoke this before starting ANY work on the Jarvis AI COO evaluation task — every new session, every resume after a break, no exceptions. Reloads current build progress and re-states the hard constraints so nothing drifts over the 8-hour build.
---

# Orient — run this first, every time

## 1. Confirm you're in the right repo

```
git remote -v
git status
git log --oneline -10
```

Confirm this is the evaluation repo (not a stray clone or an unrelated project directory) before
touching anything.

## 2. Reload progress — don't rely on memory of what was already built

Read `PROGRESS.md` at the repo root. It holds:
- Which phase (schema, auth, routes, tests, docs) is done vs. in progress.
- Which of the 10 mandatory tests are currently passing, failing, or not yet written.
- Any architecture decisions already made — don't re-litigate a decision that was already settled
  unless something concrete changed.

If `PROGRESS.md` doesn't exist yet, this is the first session — create it from the template
structure the `log-progress` skill produces, and note the actual start time.

## 3. Re-state the constraints that can't be allowed to drift

Long single-session builds are exactly where scope creeps and shortcuts sneak in. Re-read
`AGENTS.md`'s "Hard constraints" and "Domain model non-negotiables" sections before writing more
code, and hold these front-of-mind for the rest of the session:

- **`organization_id` is the ownership key on every tenant-scoped query — no exceptions.** If a
  query, service function, or test is about to touch a `skills`/`skill_versions`/`audit_log` row
  without an `organization_id` filter (or without it flowing from an already-scoped parent), stop
  and fix it before continuing, not after.
- **Active version rows are never updated in place.** If the next change is an `UPDATE` on
  anything currently `active`, that's the wrong operation — it should be a new version row plus an
  activation call, not a mutation.
- **Activation is owner-only, checked server-side, every time.** Never assume a request is
  authorized because the frontend (if any) wouldn't have shown the button — there is no frontend
  here, and the check must live in the service/route layer regardless.
- **Requested tools are validated against an allow-list, never auto-granted.** If a new skill
  version's `requested_tools` field is about to be accepted without checking it against something
  concrete, that's the gap the "invalid or destructive requested tool is rejected" test exists to
  catch — write the validation before the test, or the test before the validation, but never skip
  it.

## 4. Before marking any phase "done" in `PROGRESS.md`

Run the actual test suite. Don't mark a phase complete because the code was written and looks
right — `PROGRESS.md` should only ever record what was actually verified to pass, matching the
"no fake tests" rejection criterion. A phase marked done that later turns out broken is worse than
one honestly marked in-progress.

## 5. Self-improvement

If something about this task's environment turns out to be non-obvious (a FastAPI/SQLAlchemy/
Alembic gotcha, a Docker Compose networking quirk, a test-fixture setup detail worth not
rediscovering), add it here directly rather than letting it get relearned the hard way in a later
session.
