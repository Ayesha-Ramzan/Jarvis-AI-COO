<!--
Output of the `audit` skill. Every row needs PASS / FAIL / PARTIAL plus real evidence — a file
path + line range, a command and its actual output, or a test function name. No evidence, no
PASS. This file gets pasted back for review, so accuracy matters more than a clean-looking score.
-->

# AUDIT-REPORT.md

Audited on: (timestamp)
Repo / commit audited: (git remote + `git log -1 --format="%H %ci"`)

## 1. Hard constraints (automatic-rejection level)

| Check | Result | Evidence |
|---|---|---|
| No committed secret / real data | | |
| No cross-tenant leakage (live-tested, not just inspected) | | |
| No fake tests (assertions actually depend on real behavior) | | |
| App actually starts (`docker compose up`, real output quoted) | | |
| Active version never mutated in place | | |
| No automatic activation on creation | | |

## 2. Domain model non-negotiables

| Check | Result | Evidence |
|---|---|---|
| `organization_id` on every tenant-scoped table | | |
| Lifecycle is an enforced state machine, not a free-text field | | |
| Owner-only activation checked server-side | | |
| Requested tools validated against an allow-list | | |
| Audit log has organization, actor, event, version on write | | |

## 3. Minimum API capabilities

| Capability | Route/method | Reachable? |
|---|---|---|
| Create skill draft | | |
| List skills for current org | | |
| Read one skill with versions | | |
| Create new immutable version | | |
| Activate approved version | | |
| Disable a skill | | |
| Retrieve active skills for a department | | |

## 4. Mandatory tests — real suite run

Command run: `<exact command>`
Result summary: `<real pass/fail counts, pasted from actual output>`

| # | Spec requirement | Test function | Result |
|---|---|---|---|
| 1 | Same-org create/read succeeds | | |
| 2 | Cross-org read denied | | |
| 3 | Cross-org update denied | | |
| 4 | Non-owner activation denied | | |
| 5 | Draft cannot execute/load as active | | |
| 6 | Disabled skill excluded from runtime selection | | |
| 7 | Active version immutable | | |
| 8 | Duplicate activation idempotent | | |
| 9 | Invalid/destructive tool rejected | | |
| 10 | Audit record has org, actor, event, version | | |

## 5. Submission requirements

| Item | Present? | Notes |
|---|---|---|
| Source code | | |
| Schema / migrations | | |
| Automated tests | | |
| Docker Compose startup | | |
| `.env.example` (placeholders only) | | |
| README with real, working API examples | | |
| Architecture decision note (substantive, not filler) | | |
| Captured test output file | | |
| Known limitations, stated honestly | | |
| Meaningful commit history | | |

## 6. Restrictions check

| Check | Result |
|---|---|
| No frontend code | |
| No external AI/model API calls | |
| No cross-tenant admin bypass | |

## 7. Score estimate vs. real rubric

| Category | Max | Estimate | Why |
|---|---|---|---|
| Tenant isolation and authorization | 30 | | |
| Correct domain/version lifecycle | 20 | | |
| Tests and failure handling | 20 | | |
| Code architecture/readability | 15 | | |
| Setup and documentation | 10 | | |
| Git discipline and final report | 5 | | |
| **Total** | **100** | | |

## 8. Overall verdict

Ready to submit as-is / needs fixes before submission (list them, in priority order) / at risk of
automatic rejection (name the specific trigger).
