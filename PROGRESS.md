# PROGRESS.md

Start time: (fill in when work actually begins)
Last updated: (never — run /log-progress to populate)

## Phase status
- [ ] Schema & domain model
- [ ] Auth & tenant scoping
- [ ] Core lifecycle routes
- [ ] Tests (10 mandatory)
- [ ] Docker Compose / .env.example / README
- [ ] Architecture note / limitations / final report

## Mandatory test checklist
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
(none yet)

## Open questions / risks
(none yet)
