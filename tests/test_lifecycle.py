"""F-2: the skill lifecycle is a real, enum-backed state machine.

These tests fail without the fix: previously the status column was a bare
String(32) and the transition rules were implicit per-route conditionals.
"""

from __future__ import annotations

from sqlalchemy import Enum as SAEnum

from app.lifecycle import TRANSITIONS, can_transition
from app.models import Skill, SkillStatus


def test_status_column_is_enum_backed() -> None:
    column_type = Skill.__table__.c.status.type
    assert isinstance(column_type, SAEnum)
    assert set(column_type.enums) == {"draft", "active", "disabled"}
    assert Skill.__table__.c.status.default.arg is SkillStatus.DRAFT


def test_transition_map_is_explicit_and_terminal() -> None:
    assert can_transition(SkillStatus.DRAFT, SkillStatus.ACTIVE)
    assert can_transition(SkillStatus.DRAFT, SkillStatus.DISABLED)
    assert can_transition(SkillStatus.ACTIVE, SkillStatus.DISABLED)
    # 'disabled' is terminal: no transition out, not even to itself.
    assert TRANSITIONS[SkillStatus.DISABLED] == frozenset()
    assert not can_transition(SkillStatus.DISABLED, SkillStatus.ACTIVE)
    assert not can_transition(SkillStatus.DISABLED, SkillStatus.DISABLED)
