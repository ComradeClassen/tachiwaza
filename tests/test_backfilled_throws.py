# tests/test_backfilled_throws.py
# Verifies Part 5.5 / HAJ-29 backfill — the eight remaining worked templates:
#   - O-goshi, Tai-otoshi, Ko-uchi-gari, O-uchi-gari
#   - Harai-goshi (competitive Couple) + Harai-goshi (classical Lever)
#   - Tomoe-nage, O-guruma
#
# Mechanics already tested in test_worked_throws.py; this suite focuses on
# per-instance sanity: classification correctness, commit thresholds within
# spec bounds, registry completeness, perception routing, and a smoke test
# that each template yields a finite signature score.

from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from enums import (
    BodyPart, GripTypeV2, GripDepth, GripMode, GripTarget,
)
from body_state import place_judoka
from grip_graph import GripGraph, GripEdge
from throws import ThrowID, THROW_REGISTRY, THROW_DEFS
from throw_templates import (
    ThrowClassification, CoupleThrow, LeverThrow, FailureOutcome,
)
from throw_signature import signature_match
from worked_throws import (
    WORKED_THROWS, worked_template_for,
    O_GOSHI, TAI_OTOSHI, KO_UCHI_GARI, O_UCHI_GARI,
    HARAI_GOSHI, HARAI_GOSHI_CLASSICAL, TOMOE_NAGE, O_GURUMA,
)
from perception import actual_signature_match
import main as main_module


# ---------------------------------------------------------------------------
# FIXTURES
# ---------------------------------------------------------------------------
def _pair():
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    return t, s


def _seat_deep_grips(graph, attacker, defender, tsurite=GripTypeV2.LAPEL_HIGH):
    graph.add_edge(GripEdge(
        grasper_id=attacker.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=defender.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=tsurite, depth_level=GripDepth.DEEP,
        strength=1.0, established_tick=0, mode=GripMode.DRIVING,
    ))
    graph.add_edge(GripEdge(
        grasper_id=attacker.identity.name, grasper_part=BodyPart.LEFT_HAND,
        target_id=defender.identity.name, target_location=GripTarget.RIGHT_SLEEVE,
        grip_type_v2=GripTypeV2.SLEEVE_HIGH, depth_level=GripDepth.DEEP,
        strength=1.0, established_tick=0, mode=GripMode.DRIVING,
    ))


# ---------------------------------------------------------------------------
# Registry and display data
# ---------------------------------------------------------------------------
def test_worked_throws_registry_has_all_twelve() -> None:
    """Original four + eight backfill = twelve worked templates."""
    assert len(WORKED_THROWS) == 12
    for tid in (ThrowID.O_GOSHI, ThrowID.TAI_OTOSHI, ThrowID.KO_UCHI_GARI,
                ThrowID.O_UCHI_GARI, ThrowID.HARAI_GOSHI,
                ThrowID.HARAI_GOSHI_CLASSICAL, ThrowID.TOMOE_NAGE,
                ThrowID.O_GURUMA):
        assert tid in WORKED_THROWS


def test_new_throw_ids_have_display_entries_and_throw_defs() -> None:
    for tid in (ThrowID.O_GOSHI, ThrowID.HARAI_GOSHI_CLASSICAL,
                ThrowID.TOMOE_NAGE, ThrowID.O_GURUMA):
        assert tid in THROW_REGISTRY, f"{tid.name} missing display name"
        assert tid in THROW_DEFS,     f"{tid.name} missing legacy ThrowDef"


# ---------------------------------------------------------------------------
# Per-template classification + threshold bounds
# ---------------------------------------------------------------------------
def test_classifications_match_part_5_5_notes() -> None:
    # Lever forms:
    assert O_GOSHI.classification               == ThrowClassification.LEVER
    assert TAI_OTOSHI.classification            == ThrowClassification.LEVER
    assert HARAI_GOSHI_CLASSICAL.classification == ThrowClassification.LEVER
    assert TOMOE_NAGE.classification            == ThrowClassification.LEVER
    assert O_GURUMA.classification              == ThrowClassification.LEVER
    # Couple forms:
    assert KO_UCHI_GARI.classification == ThrowClassification.COUPLE
    assert O_UCHI_GARI.classification  == ThrowClassification.COUPLE
    assert HARAI_GOSHI.classification  == ThrowClassification.COUPLE


def test_commit_thresholds_within_classification_bounds() -> None:
    """Spec 4.3: Couple 0.4–0.6; Spec 4.4: Lever 0.6–0.8."""
    for throw in (KO_UCHI_GARI, O_UCHI_GARI, HARAI_GOSHI):
        assert 0.40 <= throw.commit_threshold <= 0.60, (
            f"{throw.name} Couple threshold out of range"
        )
    for throw in (O_GOSHI, TAI_OTOSHI, HARAI_GOSHI_CLASSICAL,
                  TOMOE_NAGE, O_GURUMA):
        assert 0.60 <= throw.commit_threshold <= 0.80, (
            f"{throw.name} Lever threshold out of range"
        )


def test_ko_uchi_gari_carries_timing_window() -> None:
    """Spec 5.5: Ko-uchi-gari is the second timing-window ashi-waza."""
    tw = KO_UCHI_GARI.body_part_requirement.timing_window
    assert tw is not None
    assert tw.target_foot == "right_foot"


def test_hip_lever_throws_demand_fulcrum_offset() -> None:
    """O-goshi, Harai-goshi classical, and O-guruma all place a fulcrum
    below uke's CoM (hip-line / thigh-line). Tai-otoshi uses a shin
    fulcrum with a much smaller offset. Tomoe-nage is an exception —
    tori is on the ground, not below uke's hips in the usual sense.
    """
    assert O_GOSHI.body_part_requirement.fulcrum_offset_below_uke_com_m > 0.10
    assert HARAI_GOSHI_CLASSICAL.body_part_requirement.fulcrum_offset_below_uke_com_m > 0.05
    assert O_GURUMA.body_part_requirement.fulcrum_offset_below_uke_com_m > 0.05
    assert 0.0 < TAI_OTOSHI.body_part_requirement.fulcrum_offset_below_uke_com_m < 0.10


def test_tomoe_nage_failure_primary_is_on_both_knees() -> None:
    """Tomoe-nage sacrifices standing position — the primary failure state
    matches the two-knee exposure per Part 6.3."""
    assert TOMOE_NAGE.failure_outcome.primary == FailureOutcome.TORI_ON_BOTH_KNEES_UKE_STANDING


# ---------------------------------------------------------------------------
# Signature-match plumbing
# ---------------------------------------------------------------------------
def test_every_backfilled_throw_returns_finite_signature() -> None:
    """Plumbing smoke test — every worked template should score cleanly
    against a default dyad (non-NaN, within [0, 1]) even if the score
    itself is low.
    """
    t, s = _pair()
    g = GripGraph()
    for tid, template in WORKED_THROWS.items():
        score = signature_match(template, t, s, g)
        assert 0.0 <= score <= 1.0, f"{tid.name}: score {score} out of [0,1]"


def test_actual_signature_match_routes_all_backfilled_throws() -> None:
    """perception.actual_signature_match dispatches to the template scorer
    for every backfilled ID, not the legacy two-factor scorer.
    """
    t, s = _pair()
    g = GripGraph()
    _seat_deep_grips(g, t, s)
    s.state.body_state.com_velocity = (-0.5, 0.0)   # forward in uke's frame
    for tid in (ThrowID.O_GOSHI, ThrowID.TAI_OTOSHI, ThrowID.KO_UCHI_GARI,
                ThrowID.O_UCHI_GARI, ThrowID.HARAI_GOSHI,
                ThrowID.HARAI_GOSHI_CLASSICAL, ThrowID.TOMOE_NAGE,
                ThrowID.O_GURUMA):
        template = worked_template_for(tid)
        assert template is not None, f"{tid.name} not routed"
        direct = signature_match(template, t, s, g)
        routed = actual_signature_match(tid, t, s, g)
        assert abs(direct - routed) < 1e-9, (
            f"{tid.name}: routed {routed} != direct {direct}"
        )


# ---------------------------------------------------------------------------
# Worked-scenario sanity per throw
# ---------------------------------------------------------------------------
def test_o_uchi_gari_scores_with_backward_kuzushi() -> None:
    t, s = _pair()
    g = GripGraph()
    _seat_deep_grips(g, t, s, tsurite=GripTypeV2.LAPEL_LOW)
    # Sato facing (-1, 0); backward in body frame means mat +X velocity.
    s.state.body_state.com_velocity = (0.4, 0.0)
    score = signature_match(O_UCHI_GARI, t, s, g)
    assert score >= O_UCHI_GARI.commit_threshold


def test_o_goshi_needs_hips_below() -> None:
    t, s = _pair()
    g = GripGraph()
    g.add_edge(GripEdge(
        grasper_id=t.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=s.identity.name, target_location=GripTarget.BELT,
        grip_type_v2=GripTypeV2.BELT, depth_level=GripDepth.DEEP,
        strength=1.0, established_tick=0, mode=GripMode.DRIVING,
    ))
    g.add_edge(GripEdge(
        grasper_id=t.identity.name, grasper_part=BodyPart.LEFT_HAND,
        target_id=s.identity.name, target_location=GripTarget.RIGHT_SLEEVE,
        grip_type_v2=GripTypeV2.SLEEVE_HIGH, depth_level=GripDepth.DEEP,
        strength=1.0, established_tick=0, mode=GripMode.DRIVING,
    ))
    s.state.body_state.com_position = (1.0, 0.0)
    s.state.body_state.com_velocity = (-0.4, 0.0)
    # Tori hips level → fulcrum geometry fails → score zero (hard gate).
    flat = signature_match(O_GOSHI, t, s, g)
    assert flat == 0.0
    # Drop tori's CoM below uke's — fulcrum met.
    t.state.body_state.com_height = s.state.body_state.com_height - 0.18
    dropped = signature_match(O_GOSHI, t, s, g)
    assert dropped > flat


def test_ko_uchi_gari_fires_inside_timing_window() -> None:
    t, s = _pair()
    g = GripGraph()
    _seat_deep_grips(g, t, s, tsurite=GripTypeV2.LAPEL_LOW)
    s.state.body_state.com_velocity = (0.2, -0.2)
    # Default weight fraction 0.5 — outside the (0.15, 0.40) window.
    outside = signature_match(KO_UCHI_GARI, t, s, g)
    s.state.body_state.foot_state_right.weight_fraction = 0.25
    inside = signature_match(KO_UCHI_GARI, t, s, g)
    assert inside > outside


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import traceback
    passed = 0
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                passed += 1
                print(f"PASS  {name}")
            except Exception:
                failed += 1
                print(f"FAIL  {name}")
                traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
