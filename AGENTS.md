# AGENTS.md — Jarvis AI COO Developer Evaluation

Kimi CLI loads this file automatically from the project root at session start — no setup needed
beyond having it present. This is a timed, individually-scored technical evaluation, not a team
project. One person, one repo, one 8-hour clock starting when work begins. There is no
task-list/PR-review loop here — the only reviewer is whoever scores the final submission against
the rubric below, after the fact.

## If source code already exists in this repo

Don't assume it's correct just because it exists, and don't assume it was built with this file
loaded. Run the `audit` skill (`.kimi/skills/audit/`) before making any further changes — it
verifies everything below against the actual code with real evidence (commands run, files read,
tests executed), and produces `AUDIT-REPORT.md`. Fix whatever it finds before treating the task
as done.

## What's being built

An **Organization-Scoped Skill Registry** vertical slice for a multi-tenant AI COO platform.
Multiple organizations create, review and activate custom AI COO "skills" while staying fully
isolated from each other's data. Frontend and external AI/model APIs are explicitly not required —
this is a backend-only exercise in tenant isolation, authorization, and immutable versioning.

Fixture organizations to build and test against: **ABC Construction**, **XYZ Builders**.

Required end-to-end workflow:
```
Authenticated organization
→ manual skill draft create
→ draft review
→ owner activation
→ active skill retrieve
→ exact version audit record
```

## Hard constraints — any one of these can mean automatic rejection

- No committed secret, credential, or real company/customer data — `.env.example` gets
  placeholders only.
- No cross-tenant leakage of any kind — Organization A must never read, update, or activate
  Organization B's skill, in any code path, including "admin" shortcuts (there are none — no
  cross-tenant admin bypass is allowed).
- No fake tests — tests must actually exercise the behavior they claim to prove, not assert
  something trivially true.
- The application must actually start (Docker Compose, from a clean checkout, following the
  README exactly).
- An active skill must never be silently mutated — activating a new version is the only way
  behavior changes; the active row itself is immutable.
- No automatic skill activation — activation is always an explicit, authorized, owner-only action.

## Domain model non-negotiables

- **Canonical ownership key: `organization_id`.** Every tenant-scoped table and every query that
  touches tenant data filters on it — no exceptions, no "trusted" cross-tenant path.
- **Skill lifecycle: `draft → active → disabled`.** Model this as a real state machine (enum +
  explicit allowed transitions), not a free-text status column anyone can set to anything.
- **Active version immutability.** Changing an active skill's behavior always means creating a new
  version row. Never `UPDATE` an active version's content in place. Version rows, once created,
  don't change.
- **Owner-only activation.** "Owner" is a role, not just "belongs to the right organization" —
  model organization membership with a role (e.g. owner/member) and check the role server-side on
  every activation call, not just at the router/UI layer.
- **Tool permissions are opt-in, never automatic.** A skill's requested tools must be validated
  against an explicit allow-list; unknown or destructive tool requests are rejected outright, not
  silently ignored or silently granted.
- **Everything that changes state gets audited.** Version creation and activation are audit
  logged with, at minimum: organization, actor, event type, and the exact version affected.
  Idempotent operations (e.g. re-activating an already-active version) should be safe and should
  still be traceable in the audit trail, not throw an unhandled error.

## Minimum API capabilities (route names are your choice)

- Create a skill draft.
- List skills belonging to the current organization.
- Read one skill together with its versions.
- Create a new immutable version.
- Activate an approved version.
- Disable a skill.
- Retrieve active skills for a department.

## Mandatory automated tests — every one of these needs a real, passing test

1. Same-organization create/read succeeds.
2. Cross-organization read is denied.
3. Cross-organization update is denied.
4. Non-owner activation is denied.
5. Draft skill cannot execute or load as active.
6. Disabled skill is excluded from runtime selection.
7. Active version is immutable.
8. Duplicate activation request is safe and idempotent.
9. Invalid or destructive requested tool is rejected.
10. Audit record contains organization, actor, event, and version.

Treat this list as the spec's own acceptance criteria — every one maps directly to marks under
"Tenant isolation and authorization" (30) and "Tests and failure handling" (20), more than half
the total score. Write these before or alongside the feature they cover, not as an afterthought
at hour 7.

## Core stack requirements

- FastAPI backend.
- PostgreSQL preferred. SQLite is allowed only with a written justification in the architecture
  decision note — don't reach for it just because it's less setup.
- Docker Compose startup that works from a clean checkout with nothing manually pre-provisioned.

## 8-hour phase budget (suggested, adjust as reality dictates)

Keep `PROGRESS.md` (see the `orient` and `log-progress` skills under `.kimi/skills/`) updated as
you move through these so nothing has to be reconstructed from memory at hour 8:

1. **Hour 0–1 — Schema & domain model.** Organizations, memberships/roles, skills, skill versions,
   audit log. Get migrations running before writing any route.
2. **Hour 1–2.5 — Auth & tenant scoping.** Whatever authentication mechanism you pick (simple
   API-key-per-org-actor is enough — no external auth provider needed), get the
   `organization_id` + role resolved from every request before any route logic touches data.
3. **Hour 2.5–4.5 — Core lifecycle routes.** Draft create, list, read-with-versions, new version,
   activate, disable, department-scoped active-skill retrieval. Isolation and ownership checks go
   in a shared dependency/service layer, not copy-pasted per route.
4. **Hour 4.5–6 — Tests.** All 10 mandatory tests, using both fixture organizations to prove
   isolation, not just one org tested against itself.
5. **Hour 6–7 — Docker Compose, `.env.example`, README with real API examples (curl or httpie
   examples that actually work against the compose stack).**
6. **Hour 7–8 — Architecture decision note, known limitations, final report (see
   `FINAL-REPORT-TEMPLATE.md`), commit cleanup.** Don't leave the meaningful-commit-history
   requirement (Git discipline, 5 marks) for a single end-of-day squash commit — it should already
   exist from committing as you go.

## Submission checklist — the repo must contain

- Source code.
- Database schema and/or migrations.
- Automated tests.
- Docker Compose startup.
- `.env.example` with placeholders only.
- README with setup instructions and real API examples.
- A short architecture decision note.
- Test output (a captured run, not just "tests exist").
- Known limitations, stated honestly.
- Meaningful commit history.

## Restrictions

- No copied proprietary code from any employer's private repos.
- No real customer or company data anywhere, including test fixtures.
- No hardcoded secrets.
- No frontend.
- No external AI/model API.
- No automatic skill activation.
- No cross-tenant admin shortcut, ever, for any reason including debugging convenience.
- If the scope seems worth expanding beyond what's written here, that's a stop-and-ask, not a
  silent decision.
