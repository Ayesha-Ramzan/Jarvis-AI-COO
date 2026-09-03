"""Explicit skill lifecycle state machine.

Single source of truth for which lifecycle transitions are legal. Every
route that moves a skill between states consults :data:`TRANSITIONS`
instead of encoding its own ad-hoc transition logic, and the status column
is backed by :class:`app.models.SkillStatus` at the database level.
"""

from __future__ import annotations

from app.models import SkillStatus

# allowed targets for each source state
TRANSITIONS: dict[SkillStatus, frozenset[SkillStatus]] = {
    SkillStatus.DRAFT: frozenset({SkillStatus.ACTIVE, SkillStatus.DISABLED}),
    SkillStatus.ACTIVE: frozenset({SkillStatus.DISABLED}),
    # Terminal: a disabled skill can never come back.
    SkillStatus.DISABLED: frozenset(),
}


def can_transition(source: SkillStatus, target: SkillStatus) -> bool:
    """Return True only when the state machine allows ``source -> target``."""
    return target in TRANSITIONS.get(source, frozenset())
