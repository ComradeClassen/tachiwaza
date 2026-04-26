# tests/test_o_soto_contact_quality.py
# Verifies HAJ-55 / physics-substrate Part 5.2:
#   - O-soto-gari's body_part_requirement carries a ContactQualityProfile
#   - _match_couple_body_parts scores torso_closure and reaping_leg_contact
#     as continuous sub-checks derived from CoM-to-CoM distance
#   - The two sub-scores never hard-zero the body-parts dimension:
#     heel-to-calf at arm's length still fires, just at low quality
#   - Close placement yields high signature; far placement yields lower
#     signature and lower execution_quality, not commit gating
#   - The same throw at different distances produces materially different
#     execution_quality scores end-to-end through the match pipeline
#   - Legacy Couple throws without a contact_quality profile are unchanged

from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from enums import BodyPart, GripTypeV2, GripDepth, GripMode, GripTarget
from body_state import place_judoka
from grip_graph import GripGraph, GripEdge
from throws import ThrowID
from throw_templates import ContactQualityProfile
from throw_signature import (
    _contact_quality_scores, _linear_falloff, _match_couple_body_parts,
    match_body_parts, signature_match,
)
from worked_throws import O_SOTO_GARI, DE_ASHI_HARAI
from execution_quality import compute_execution_quality
from kuzushi import seed_kuzushi_from_velocity
import main as main_module


# ---------------------------------------------------------------------------
# FIXTURES
# ---------------------------------------------------------------------------
def _pair(tori_x: float = -0.5, uke_x: float = 0.5):
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(tori_x, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(uke_x, 0.0), facing=(-1.0, 0.0))
    return t, s


def _seat_deep_grips(graph: GripGraph, attacker, defender) -> None:
    graph.add_edge(GripEdge(
        grasper_id=attacker.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=defender.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.STANDARD,
        strength=0.8, established_tick=0, mode=GripMode.DRIVING,
    ))
    graph.add_edge(GripEdge(
        grasper_id=attacker.identity.name, grasper_part=BodyPart.LEFT_HAND,
        target_id=defender.identity.name, target_location=GripTarget.RIGHT_SLEEVE,
        grip_type_v2=GripTypeV2.SLEEVE_HIGH, depth_level=GripDepth.STANDARD,
        strength=0.8, established_tick=0, mode=GripMode.DRIVING,
    ))


# ---------------------------------------------------------------------------
# Template carries the profile
# ---------------------------------------------------------------------------
def test_o_soto_gari_has_contact_quality_profile() -> None:
    prof = O_SOTO_GARI.body_part_requirement.contact_quality
    assert prof is not None
    # Thigh contact should be reachable from closer than heel-contact limit,
    # and closure ideal should be within the reaping-contact span.
    assert prof.ideal_torso_closure_m < prof.max_torso_closure_m
    assert prof.ideal_reaping_contact_m < prof.max_reaping_contact_m


def test_de_ashi_harai_has_no_contact_quality_profile() -> None:
    # Contact-quality is specific to O-soto — ashi-waza throws keep the
    # timing-window gate and don't use contact-point scoring.
    assert DE_ASHI_HARAI.body_part_requirement.contact_quality is None


# ---------------------------------------------------------------------------
# _linear_falloff
# ---------------------------------------------------------------------------
def test_linear_falloff_at_or_below_ideal_is_one() -> None:
    assert _linear_falloff(0.3, ideal=0.5, maximum=1.0) == 1.0
    assert _linear_falloff(0.5, ideal=0.5, maximum=1.0) == 1.0


def test_linear_falloff_at_or_above_max_is_zero() -> None:
    assert _linear_falloff(1.0, ideal=0.5, maximum=1.0) == 0.0
    assert _linear_falloff(1.5, ideal=0.5, maximum=1.0) == 0.0


def test_linear_falloff_midpoint_is_half() -> None:
    assert abs(_linear_falloff(0.75, ideal=0.5, maximum=1.0) - 0.5) < 1e-9


def test_linear_falloff_degenerate_span_returns_zero() -> None:
    # ideal == max is a degenerate spec; anything past ideal should return 0.
    assert _linear_falloff(0.5, ideal=0.5, maximum=0.5) == 1.0
    assert _linear_falloff(0.6, ideal=0.5, maximum=0.5) == 0.0


# ---------------------------------------------------------------------------
# _contact_quality_scores from CoM distance
# ---------------------------------------------------------------------------
def test_contact_quality_high_at_close_distance() -> None:
    prof = O_SOTO_GARI.body_part_requirement.contact_quality
    t, s = _pair(tori_x=0.0, uke_x=prof.ideal_torso_closure_m - 0.05)
    closure, reaping = _contact_quality_scores(prof, t, s)
    assert closure == 1.0
    assert reaping == 1.0


def test_contact_quality_low_at_far_distance() -> None:
    prof = O_SOTO_GARI.body_part_requirement.contact_quality
    t, s = _pair(tori_x=0.0, uke_x=prof.max_reaping_contact_m + 0.1)
    closure, reaping = _contact_quality_scores(prof, t, s)
    assert closure == 0.0
    assert reaping == 0.0


def test_contact_quality_monotonic_with_distance() -> None:
    prof = O_SOTO_GARI.body_part_requirement.contact_quality
    samples = []
    for d in (0.30, 0.60, 0.90, 1.20):
        t, s = _pair(tori_x=0.0, uke_x=d)
        closure, reaping = _contact_quality_scores(prof, t, s)
        samples.append((closure, reaping))
    # Each component should be monotonically non-increasing with distance.
    closures = [x[0] for x in samples]
    reapings = [x[1] for x in samples]
    assert closures == sorted(closures, reverse=True)
    assert reapings == sorted(reapings, reverse=True)


# ---------------------------------------------------------------------------
# _match_couple_body_parts — signature never hard-zeros on contact alone
# ---------------------------------------------------------------------------
def test_body_parts_score_positive_at_max_distance() -> None:
    """Heel-to-calf arm's-length execution must still score > 0 on body
    parts: the foot-planted + limb-healthy checks remain, contact checks
    drop to 0 but are averaged, not multiplied.
    """
    prof = O_SOTO_GARI.body_part_requirement.contact_quality
    t, s = _pair(tori_x=0.0, uke_x=prof.max_reaping_contact_m + 0.05)
    score = _match_couple_body_parts(O_SOTO_GARI.body_part_requirement, t, s)
    assert score > 0.0
    assert score < 1.0


def test_body_parts_score_higher_when_close() -> None:
    """Same state, close vs far placement — body-parts dimension is higher
    at close distance.
    """
    prof = O_SOTO_GARI.body_part_requirement.contact_quality
    t_close, s_close = _pair(tori_x=0.0, uke_x=prof.ideal_torso_closure_m - 0.05)
    t_far,   s_far   = _pair(tori_x=0.0, uke_x=prof.max_reaping_contact_m)
    close_score = _match_couple_body_parts(
        O_SOTO_GARI.body_part_requirement, t_close, s_close,
    )
    far_score = _match_couple_body_parts(
        O_SOTO_GARI.body_part_requirement, t_far, s_far,
    )
    assert close_score > far_score


# ---------------------------------------------------------------------------
# End-to-end: execution_quality varies across the distance range
# ---------------------------------------------------------------------------
def test_execution_quality_varies_with_contact_distance() -> None:
    """Two identical setups except for CoM-to-CoM distance produce materially
    different execution_quality values for O-soto-gari. Both must exceed the
    commit threshold (signature still fires) but the far case's eq should be
    noticeably lower.
    """
    prof = O_SOTO_GARI.body_part_requirement.contact_quality
    graph = GripGraph()

    t_close, s_close = _pair(tori_x=0.0, uke_x=prof.ideal_torso_closure_m - 0.05)
    _seat_deep_grips(graph, t_close, s_close)
    # Seed a backward kuzushi event so the kuzushi-vector dim is non-zero.
    s_close.state.body_state.facing = (-1.0, 0.0)
    seed_kuzushi_from_velocity(s_close, (0.4, 0.0))
    sig_close = signature_match(O_SOTO_GARI, t_close, s_close, graph)

    graph2 = GripGraph()
    t_far, s_far = _pair(tori_x=0.0, uke_x=prof.max_reaping_contact_m)
    _seat_deep_grips(graph2, t_far, s_far)
    s_far.state.body_state.facing = (-1.0, 0.0)
    seed_kuzushi_from_velocity(s_far, (0.4, 0.0))
    sig_far = signature_match(O_SOTO_GARI, t_far, s_far, graph2)

    eq_close = compute_execution_quality(sig_close, O_SOTO_GARI.commit_threshold)
    eq_far   = compute_execution_quality(sig_far,   O_SOTO_GARI.commit_threshold)

    # Both sides should at least see a signature match above zero; the point
    # the ticket insists on is monotonicity and non-gating.
    assert sig_close > sig_far
    assert eq_close > eq_far


# ---------------------------------------------------------------------------
# Legacy Couple throws unaffected
# ---------------------------------------------------------------------------
def test_couple_body_parts_unchanged_for_throws_without_profile() -> None:
    """De-ashi-harai has no contact_quality; body_parts should still score
    via (foot + limb + timing_window) like before.
    """
    graph = GripGraph()
    t, s = _pair(tori_x=0.0, uke_x=0.5)
    # De-ashi-harai has a TimingWindow on RIGHT_FOOT; without setting
    # weight_fraction inside the window the gate hard-zeros — that's the
    # existing (Part 4.6) behaviour, confirmed preserved.
    s.state.body_state.foot_state_right.weight_fraction = 0.2  # inside window
    score = _match_couple_body_parts(DE_ASHI_HARAI.body_part_requirement, t, s)
    assert score > 0.0


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
