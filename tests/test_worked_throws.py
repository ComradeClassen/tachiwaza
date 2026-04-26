# tests/test_worked_throws.py
# Verifies Part 5 of design-notes/physics-substrate.md:
#   - All four worked throws instantiate correctly (5.1–5.4)
#   - Each scores non-zero in a properly staged scenario
#   - Each scores low when the setup is mismatched
#   - perception.actual_signature_match routes to the template scorer
#   - Timing window on De-ashi-harai short-circuits body-parts out of window
#   - match._resolve_commit_throw still produces THROW_ENTRY for template throws

from __future__ import annotations
import math
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from enums import (
    BodyPart, GripTypeV2, GripDepth, GripMode, GripTarget,
)
from body_state import place_judoka, FootContactState
from grip_graph import GripGraph, GripEdge
from throws import ThrowID, THROW_REGISTRY
from throw_templates import ThrowClassification, CoupleThrow, LeverThrow
from throw_signature import signature_match
from worked_throws import (
    UCHI_MATA, O_SOTO_GARI, SEOI_NAGE_MOROTE, DE_ASHI_HARAI,
    WORKED_THROWS, worked_template_for,
)
from perception import actual_signature_match
from kuzushi import seed_kuzushi_from_velocity
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


def _seat_deep_grips(graph: GripGraph, attacker, defender,
                     tsurite_type: GripTypeV2 = GripTypeV2.LAPEL_HIGH) -> None:
    graph.add_edge(GripEdge(
        grasper_id=attacker.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=defender.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=tsurite_type, depth_level=GripDepth.DEEP,
        strength=1.0, established_tick=0, mode=GripMode.DRIVING,
    ))
    graph.add_edge(GripEdge(
        grasper_id=attacker.identity.name, grasper_part=BodyPart.LEFT_HAND,
        target_id=defender.identity.name, target_location=GripTarget.RIGHT_SLEEVE,
        grip_type_v2=GripTypeV2.SLEEVE_HIGH, depth_level=GripDepth.DEEP,
        strength=1.0, established_tick=0, mode=GripMode.DRIVING,
    ))


# ---------------------------------------------------------------------------
# Template instantiation sanity
# ---------------------------------------------------------------------------
def test_part_5_1_through_5_4_worked_throws_are_registered() -> None:
    """The original four worked throws from spec 5.1–5.4 must be in the
    registry. The Part 5.5 / HAJ-29 backfill adds more; test_backfilled_throws
    covers the full set.
    """
    for tid in (ThrowID.UCHI_MATA, ThrowID.O_SOTO_GARI,
                ThrowID.SEOI_NAGE, ThrowID.DE_ASHI_HARAI):
        assert tid in WORKED_THROWS


def test_classifications_match_spec() -> None:
    assert UCHI_MATA.classification        == ThrowClassification.COUPLE
    assert O_SOTO_GARI.classification      == ThrowClassification.COUPLE
    assert SEOI_NAGE_MOROTE.classification == ThrowClassification.LEVER
    assert DE_ASHI_HARAI.classification    == ThrowClassification.COUPLE


def test_commit_thresholds_respect_classification_bounds() -> None:
    # Spec 4.3: Couple 0.4–0.6; Spec 4.4: Lever 0.6–0.8.
    assert 0.40 <= UCHI_MATA.commit_threshold     <= 0.60
    assert 0.40 <= O_SOTO_GARI.commit_threshold   <= 0.60
    assert 0.40 <= DE_ASHI_HARAI.commit_threshold <= 0.60
    assert 0.60 <= SEOI_NAGE_MOROTE.commit_threshold <= 0.80


def test_deashi_harai_has_timing_window() -> None:
    tw = DE_ASHI_HARAI.body_part_requirement.timing_window
    assert tw is not None
    assert tw.target_foot == "right_foot"
    assert tw.weight_fraction_range == (0.1, 0.3)


def test_throw_registry_has_de_ashi_harai_display_name() -> None:
    assert ThrowID.DE_ASHI_HARAI in THROW_REGISTRY
    assert THROW_REGISTRY[ThrowID.DE_ASHI_HARAI].name == "De-ashi-harai"


# ---------------------------------------------------------------------------
# Signature scoring scenarios
# ---------------------------------------------------------------------------
def test_uchi_mata_scores_high_when_properly_staged() -> None:
    t, s = _pair()
    g = GripGraph()
    _seat_deep_grips(g, t, s, tsurite_type=GripTypeV2.LAPEL_HIGH)
    # Sato facing (-1, 0) — kuzushi event (-0.6, 0) means "forward" in Sato's frame.
    seed_kuzushi_from_velocity(s, (-0.6, 0.0))
    score = signature_match(UCHI_MATA, t, s, g)
    assert score >= 0.55   # clears Uchi-mata's commit threshold


def test_uchi_mata_below_threshold_without_grips_or_kuzushi() -> None:
    """A Couple throw *can* fire on imperfect kuzushi (spec 4.3), but it
    cannot fire with neither kuzushi nor grips — force + kuzushi dimensions
    both zeroed collapses the weighted sum below the commit threshold.

    Seat a token uke-owned edge so the Part 4.3 ungripped-uke force-dim
    bonus does not confound the test — the question here is about tori's
    inputs, not uke's grip state.
    """
    t, s = _pair()
    g = GripGraph()
    g.add_edge(GripEdge(
        grasper_id=s.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=t.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.POCKET,
        strength=0.5, established_tick=0, mode=GripMode.CONNECTIVE,
    ))
    score = signature_match(UCHI_MATA, t, s, g)
    assert score < UCHI_MATA.commit_threshold


def test_o_soto_gari_scores_high_with_backward_kuzushi() -> None:
    t, s = _pair()
    g = GripGraph()
    _seat_deep_grips(g, t, s, tsurite_type=GripTypeV2.LAPEL_LOW)
    # Sato tilted slightly back with backward kuzushi event — o-soto.
    seed_kuzushi_from_velocity(s, (0.4, 0.0))          # backward in Sato's frame
    s.state.body_state.trunk_sagittal = math.radians(-3)
    score = signature_match(O_SOTO_GARI, t, s, g)
    assert score >= O_SOTO_GARI.commit_threshold


def test_seoi_nage_requires_displaced_uke_and_hips_below() -> None:
    t, s = _pair()
    g = GripGraph()
    _seat_deep_grips(g, t, s, tsurite_type=GripTypeV2.LAPEL_HIGH)
    # Staged seoi: uke's CoM forward, tori dropped, strong kuzushi event.
    s.state.body_state.com_position = (1.0, 0.0)
    seed_kuzushi_from_velocity(s, (-0.4, 0.0))
    t.state.body_state.com_height   = s.state.body_state.com_height - 0.20
    score = signature_match(SEOI_NAGE_MOROTE, t, s, g)
    assert score >= SEOI_NAGE_MOROTE.commit_threshold


def test_seoi_nage_fails_when_tori_hips_not_below() -> None:
    """Spec 5.3's #1 failure mode: hips above uke's hips → throw can't fire."""
    t, s = _pair()
    g = GripGraph()
    _seat_deep_grips(g, t, s, tsurite_type=GripTypeV2.LAPEL_HIGH)
    s.state.body_state.com_position = (1.0, 0.0)
    seed_kuzushi_from_velocity(s, (-0.4, 0.0))
    # Tori's hips LEVEL with uke's — fulcrum geometry fails.
    score = signature_match(SEOI_NAGE_MOROTE, t, s, g)
    assert score < SEOI_NAGE_MOROTE.commit_threshold


def test_de_ashi_harai_zero_outside_timing_window() -> None:
    t, s = _pair()
    g = GripGraph()
    _seat_deep_grips(g, t, s, tsurite_type=GripTypeV2.LAPEL_LOW)
    seed_kuzushi_from_velocity(s, (0.0, 0.4))   # lateral kuzushi
    # Default weight_fraction = 0.5 — outside (0.1, 0.3).
    score = signature_match(DE_ASHI_HARAI, t, s, g)
    assert score < DE_ASHI_HARAI.commit_threshold


def test_de_ashi_harai_fires_inside_timing_window() -> None:
    t, s = _pair()
    g = GripGraph()
    _seat_deep_grips(g, t, s, tsurite_type=GripTypeV2.LAPEL_LOW)
    seed_kuzushi_from_velocity(s, (0.0, 0.4))
    # Catch the foot mid-step.
    s.state.body_state.foot_state_right.weight_fraction = 0.2
    score = signature_match(DE_ASHI_HARAI, t, s, g)
    assert score >= DE_ASHI_HARAI.commit_threshold


# ---------------------------------------------------------------------------
# Integration with perception.actual_signature_match
# ---------------------------------------------------------------------------
def test_actual_signature_match_routes_to_template_for_worked_throws() -> None:
    t, s = _pair()
    g = GripGraph()
    # Legacy scorer would give 0.0 (no grips). Template scorer can still score
    # posture (1.0) × posture_weight (0.10) = 0.10, so a worked throw's
    # baseline-state score is strictly positive where legacy was zero.
    worked_score = actual_signature_match(ThrowID.UCHI_MATA, t, s, g)
    assert worked_score > 0.0
    # A ThrowID not in the worked registry still uses legacy and returns 0.
    # SUMI_GAESHI is the only v0.1 throw without a Part-5 template.
    assert ThrowID.SUMI_GAESHI not in WORKED_THROWS
    legacy_score = actual_signature_match(ThrowID.SUMI_GAESHI, t, s, g)
    assert legacy_score == 0.0


def test_template_scorer_matches_direct_call() -> None:
    t, s = _pair()
    g = GripGraph()
    _seat_deep_grips(g, t, s)
    seed_kuzushi_from_velocity(s, (-0.5, 0.0))
    direct = signature_match(UCHI_MATA, t, s, g)
    routed = actual_signature_match(ThrowID.UCHI_MATA, t, s, g)
    assert abs(direct - routed) < 1e-9


# ---------------------------------------------------------------------------
# Match commit path integration
# ---------------------------------------------------------------------------
def test_commit_throw_resolves_for_worked_template() -> None:
    """Forcing a COMMIT_THROW on Uchi-mata via a template-scored throw still
    produces THROW_ENTRY and clears the kumi-kata clock.
    """
    from match import Match
    from referee import build_suzuki
    random.seed(4)
    t, s = _pair()
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())

    _seat_deep_grips(m.grip_graph, t, s)
    s.state.body_state.com_velocity = (-0.5, 0.0)

    events = m._resolve_commit_throw(t, s, ThrowID.UCHI_MATA, tick=5)
    assert any(ev.event_type == "THROW_ENTRY" for ev in events)
    assert m._last_attack_tick[t.identity.name] == 5
    assert m.kumi_kata_clock[t.identity.name] == 0


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
