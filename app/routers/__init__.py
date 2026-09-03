"""Skill registry endpoints, all strictly organization-scoped.

Lifecycle rules enforced here (and mirrored by DB constraints):

  * draft  -> owner activates (snapshots an immutable SkillVersion)
  * active -> immutable; any change must be a NEW SkillVersion, then that
              version may be activated to become the runtime definition
  * active -> owner disables (terminal state; excluded from runtime)
  * every mutation writes an audit row (org, actor, event, version hash)
"""
