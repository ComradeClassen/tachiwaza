# tests/test_sleeve_height.py
# Verifies HAJ-53: SLEEVE grip splits into SLEEVE_LOW (cuff) and SLEEVE_HIGH
# (elbow/tricep). Different throws prefer different heights.
#
# Locks four properties:
#   1. The enum has both sub-types and the family-membership helper works.
#   2. Force envelopes differ — LOW has stronger rotation authority and a
#      longer moment arm; HIGH has stronger lift and strip resistance.
#   3. Tai-otoshi requires SLEEVE_LOW; the rest of the worked vocabulary
#      requires SLEEVE_HIGH on the hikite hand.
#   4. The default reach action issues SLEEVE_HIGH (the standard hikite).
#   5. The grip-graph auto-seat path uses SLEEVE_HIGH.

from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from enums import GripTypeV2, GripTarget, DominantSide
from force_envelope import FORCE_ENVELOPES
from throws import ThrowID
from worked_throws import WORKED_THROWS, worked_template_for
from action_selection import _reach_actions
from actions import ActionKind
import main as main_module


# ---------------------------------------------------------------------------
# 1. Enum + family helper
# ---------------------------------------------------------------------------
def test_sleeve_subtypes_exist() -> None:
    assert hasattr(GripTypeV2, "SLEEVE_LOW")
    assert hasattr(GripTypeV2, "SLEEVE_HIGH")
    # Bare SLEEVE no longer exists — callers must pick a height.
    assert not hasattr(GripTypeV2, "SLEEVE")


def test_is_sleeve_classifier() -> None:
    assert GripTypeV2.SLEEVE_LOW.is_sleeve()
    assert GripTypeV2.SLEEVE_HIGH.is_sleeve()
    assert not GripTypeV2.LAPEL_HIGH.is_sleeve()
    assert not GripTypeV2.PISTOL.is_sleeve()


# ---------------------------------------------------------------------------
# 2. Force envelopes — LOW vs HIGH have distinct mechanical profiles
# ---------------------------------------------------------------------------
def test_both_sleeve_subtypes_have_envelopes() -> None:
    assert GripTypeV2.SLEEVE_LOW in FORCE_ENVELOPES
    assert GripTypeV2.SLEEVE_HIGH in FORCE_ENVELOPES


def test_low_has_longer_moment_arm_and_more_rotation_authority() -> None:
    """Cuff sits farther from uke's CoM than the elbow does, and the wrist
    rotation control is the cuff's mechanical signature. These two
    properties are why Tai-otoshi prefers LOW."""
    low = FORCE_ENVELOPES[GripTypeV2.SLEEVE_LOW]
    high = FORCE_ENVELOPES[GripTypeV2.SLEEVE_HIGH]
    assert low.moment_arm_to_uke_com > high.moment_arm_to_uke_com
    assert low.rotation_authority > high.rotation_authority


def test_high_has_stronger_lift_and_strip_resistance() -> None:
    """Elbow/tricep grip: leverage to lift uke's shoulder line, and harder
    to strip than the cuff. These are why most throws prefer HIGH."""
    low = FORCE_ENVELOPES[GripTypeV2.SLEEVE_LOW]
    high = FORCE_ENVELOPES[GripTypeV2.SLEEVE_HIGH]
    assert high.max_lift_force > low.max_lift_force
    assert high.strip_resistance > low.strip_resistance


# ---------------------------------------------------------------------------
# 3. Per-throw preferred-height matrix
# ---------------------------------------------------------------------------
def test_tai_otoshi_requires_sleeve_low() -> None:
    """Tai-otoshi is the canonical sleeve-LOW throw — the cuff drives the
    pull-around vector around the shin block."""
    template = worked_template_for(ThrowID.TAI_OTOSHI)
    sleeve_grip = next(
        g for g in template.force_grips if g.hand == "left_hand"
    )
    assert sleeve_grip.grip_type == (GripTypeV2.SLEEVE_LOW,)


def test_all_other_throws_prefer_sleeve_high() -> None:
    """Every other worked throw with a hikite-hand sleeve grip should ask
    for SLEEVE_HIGH (elbow/tricep), the standard hikite control."""
    for tid, template in WORKED_THROWS.items():
        if tid == ThrowID.TAI_OTOSHI:
            continue
        for req in template.force_grips:
            if any(gt.is_sleeve() for gt in req.grip_type):
                assert GripTypeV2.SLEEVE_HIGH in req.grip_type, (
                    f"{tid.name} should accept SLEEVE_HIGH on the hikite "
                    f"hand, got {req.grip_type}"
                )
                assert GripTypeV2.SLEEVE_LOW not in req.grip_type, (
                    f"{tid.name} should not require SLEEVE_LOW (Tai-otoshi "
                    f"is the only sleeve-LOW throw)"
                )


# ---------------------------------------------------------------------------
# 4. Reach default
# ---------------------------------------------------------------------------
def test_default_reach_targets_sleeve_high() -> None:
    """The action ladder's reach rung issues a SLEEVE_HIGH grab — the
    standard hikite. Tai-otoshi specialists requiring LOW would need a
    Ring-2 coach instruction layer to override."""
    t = main_module.build_tanaka()
    assert t.identity.dominant_side == DominantSide.RIGHT
    actions = _reach_actions(t)
    sleeve_action = next(
        a for a in actions if a.target_location in (
            GripTarget.RIGHT_SLEEVE, GripTarget.LEFT_SLEEVE,
        )
    )
    assert sleeve_action.kind == ActionKind.REACH
    assert sleeve_action.grip_type == GripTypeV2.SLEEVE_HIGH


# ---------------------------------------------------------------------------
# 5. Auto-seat path
# ---------------------------------------------------------------------------
def test_auto_seat_creates_sleeve_high_edge() -> None:
    """The grip_graph engagement path that auto-seats the non-dominant
    hand on uke's sleeve uses SLEEVE_HIGH (the default hikite)."""
    from grip_graph import GripGraph
    from body_state import place_judoka
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    g = GripGraph()
    new_edges = g.attempt_engagement(t, s, current_tick=0)
    sleeve_edges = [
        e for e in new_edges
        if e.target_location in (GripTarget.RIGHT_SLEEVE, GripTarget.LEFT_SLEEVE)
    ]
    assert sleeve_edges
    for edge in sleeve_edges:
        assert edge.grip_type_v2 == GripTypeV2.SLEEVE_HIGH
