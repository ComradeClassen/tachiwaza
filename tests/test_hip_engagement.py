# tests/test_hip_engagement.py
# Verifies HAJ-59: hip-engagement as execution quality input (not a new
# compromised state).
#
# Covers:
#   - HipEngagementProfile is populated on Tai-otoshi (Lever), O-soto-gari
#     (Couple), and Uchi-mata (Couple); hip-fulcrum throws (Seoi-nage,
#     O-goshi, Harai-goshi classical, O-guruma) leave it None.
#   - _hip_engagement_multiplier is 1.0 below the clean angle, floor at or
#     above the engaged angle, and linear in between.
#   - Multiplier is applied to both _match_couple_body_parts and
#     _match_lever_body_parts when a profile is set.
#   - Hip-engaged executions never hard-zero the body-parts dimension.
#   - Tai-otoshi collapses more aggressively than O-soto-gari / Uchi-mata
#     (hard vs soft floor), matching HAJ-59 point 2.
#   - End-to-end: execution_quality for a hip-engaged Tai-otoshi is markedly
#     lower than for the clean-trunk version.
#   - No new FailureOutcome enum member was introduced — TORI_SELF_BLOCKED
#     does not exist (HAJ-59's "no new compromised state" requirement).

from __future__ import annotations
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from enums import BodyPart, GripTypeV2, GripDepth, GripMode, GripTarget
from body_state import place_judoka
from grip_graph import GripGraph, GripEdge
from throws import ThrowID
from throw_templates import HipEngagementProfile, FailureOutcome
from throw_signature import (
    _hip_engagement_multiplier, _match_couple_body_parts,
    _match_lever_body_parts, signature_match,
)
from worked_throws import (
    TAI_OTOSHI, O_SOTO_GARI, UCHI_MATA,
    SEOI_NAGE_MOROTE, O_GOSHI, HARAI_GOSHI_CLASSICAL, O_GURUMA,
)
from execution_quality import compute_execution_quality
import main as main_module


# ---------------------------------------------------------------------------
# FIXTURES
# ---------------------------------------------------------------------------
def _pair(tori_x: float = -0.25, uke_x: float = 0.25):
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
        grip_type_v2=GripTypeV2.SLEEVE, depth_level=GripDepth.STANDARD,
        strength=0.8, established_tick=0, mode=GripMode.DRIVING,
    ))


# ---------------------------------------------------------------------------
# Template population
# ---------------------------------------------------------------------------
def test_tai_otoshi_has_hard_hip_engagement_profile() -> None:
    prof = TAI_OTOSHI.body_part_requirement.hip_engagement
    assert prof is not None
    # Hard collapse — floor near zero.
    assert prof.engaged_floor < 0.20


def test_o_soto_and_uchi_mata_have_soft_hip_engagement_profile() -> None:
    for throw in (O_SOTO_GARI, UCHI_MATA):
        prof = throw.body_part_requirement.hip_engagement
        assert prof is not None
        # Soft floor — around 0.5, producing ~0.3 eq reduction.
        assert 0.35 <= prof.engaged_floor <= 0.65


def test_hip_fulcrum_throws_leave_profile_unset() -> None:
    """Seoi-nage, O-goshi, Harai-goshi classical, and O-guruma all use hip
    or hip-adjacent fulcrums — they WANT hip engagement, so no penalty.
    """
    for throw in (SEOI_NAGE_MOROTE, O_GOSHI, HARAI_GOSHI_CLASSICAL, O_GURUMA):
        assert throw.body_part_requirement.hip_engagement is None


# ---------------------------------------------------------------------------
# _hip_engagement_multiplier curve
# ---------------------------------------------------------------------------
def test_multiplier_one_below_clean_threshold() -> None:
    prof = HipEngagementProfile(
        clean_trunk_sagittal_rad=math.radians(20),
        engaged_trunk_sagittal_rad=math.radians(40),
        engaged_floor=0.1,
    )
    t, _ = _pair()
    t.state.body_state.trunk_sagittal = math.radians(5)
    assert _hip_engagement_multiplier(prof, t) == 1.0
    t.state.body_state.trunk_sagittal = math.radians(20)
    assert _hip_engagement_multiplier(prof, t) == 1.0


def test_multiplier_floor_at_or_above_engaged_angle() -> None:
    prof = HipEngagementProfile(
        clean_trunk_sagittal_rad=math.radians(20),
        engaged_trunk_sagittal_rad=math.radians(40),
        engaged_floor=0.1,
    )
    t, _ = _pair()
    t.state.body_state.trunk_sagittal = math.radians(40)
    assert abs(_hip_engagement_multiplier(prof, t) - 0.1) < 1e-9
    t.state.body_state.trunk_sagittal = math.radians(60)
    assert abs(_hip_engagement_multiplier(prof, t) - 0.1) < 1e-9


def test_multiplier_linear_midpoint() -> None:
    prof = HipEngagementProfile(
        clean_trunk_sagittal_rad=math.radians(20),
        engaged_trunk_sagittal_rad=math.radians(40),
        engaged_floor=0.2,
    )
    t, _ = _pair()
    t.state.body_state.trunk_sagittal = math.radians(30)  # midpoint
    # At midpoint: multiplier = 1.0 - (1.0 - 0.2) * 0.5 = 0.6
    assert abs(_hip_engagement_multiplier(prof, t) - 0.6) < 1e-9


# ---------------------------------------------------------------------------
# Body-parts dimension never hard-zeros on hip engagement alone
# ---------------------------------------------------------------------------
def _set_clean_trunk(j) -> None:
    j.state.body_state.trunk_sagittal = math.radians(5)


def _set_hip_engaged(j) -> None:
    j.state.body_state.trunk_sagittal = math.radians(50)


def test_couple_body_parts_score_positive_when_hip_engaged() -> None:
    """O-soto-gari: hip-engaged still fires (body_parts > 0)."""
    t, s = _pair(tori_x=0.0, uke_x=0.45)  # close — good contact quality
    _set_hip_engaged(t)
    score = _match_couple_body_parts(
        O_SOTO_GARI.body_part_requirement, t, s,
    )
    assert 0.0 < score < 1.0


def test_couple_body_parts_score_drops_when_hip_engaged() -> None:
    t, s_clean = _pair(tori_x=0.0, uke_x=0.45)
    _set_clean_trunk(t)
    clean_score = _match_couple_body_parts(
        O_SOTO_GARI.body_part_requirement, t, s_clean,
    )
    t2, s_hip = _pair(tori_x=0.0, uke_x=0.45)
    _set_hip_engaged(t2)
    hip_score = _match_couple_body_parts(
        O_SOTO_GARI.body_part_requirement, t2, s_hip,
    )
    assert clean_score > hip_score


def test_lever_body_parts_score_positive_when_hip_engaged() -> None:
    """Tai-otoshi: hip-engaged still fires (body_parts > 0) even with the
    hard collapse floor — the multiplier is 0.05, not 0.
    """
    t, s = _pair()
    # Raise tori CoM so fulcrum offset (0.05 m below uke) is satisfied.
    t.state.body_state.com_height = 0.90
    s.state.body_state.com_height  = 1.05
    _set_hip_engaged(t)
    score = _match_lever_body_parts(
        TAI_OTOSHI.body_part_requirement, t, s,
    )
    prof = TAI_OTOSHI.body_part_requirement.hip_engagement
    # Engaged floor > 0; score > 0.
    assert score > 0.0
    # And below the unengaged ceiling.
    t.state.body_state.trunk_sagittal = math.radians(5)
    clean_score = _match_lever_body_parts(
        TAI_OTOSHI.body_part_requirement, t, s,
    )
    assert clean_score > score


def test_tai_otoshi_collapses_harder_than_o_soto() -> None:
    """Hard vs soft floors: the ratio of engaged/clean body_parts for
    Tai-otoshi should be lower than for O-soto-gari.
    """
    t, s = _pair(tori_x=0.0, uke_x=0.45)
    t.state.body_state.com_height = 0.90
    s.state.body_state.com_height = 1.05

    _set_clean_trunk(t)
    tai_clean = _match_lever_body_parts(TAI_OTOSHI.body_part_requirement, t, s)
    oso_clean = _match_couple_body_parts(O_SOTO_GARI.body_part_requirement, t, s)

    _set_hip_engaged(t)
    tai_hip = _match_lever_body_parts(TAI_OTOSHI.body_part_requirement, t, s)
    oso_hip = _match_couple_body_parts(O_SOTO_GARI.body_part_requirement, t, s)

    tai_ratio = tai_hip / tai_clean if tai_clean > 0 else 0.0
    oso_ratio = oso_hip / oso_clean if oso_clean > 0 else 0.0
    assert tai_ratio < oso_ratio, (
        f"Tai-otoshi collapse ratio {tai_ratio:.3f} should be < "
        f"O-soto ratio {oso_ratio:.3f}"
    )


# ---------------------------------------------------------------------------
# End-to-end: execution_quality drops for hip-engaged attempts
# ---------------------------------------------------------------------------
def test_signature_drops_sharply_when_tai_otoshi_hip_engaged() -> None:
    """Tai-otoshi's hard collapse: signature should drop by roughly the
    body-weight × (1 - engaged_floor) share when trunk is loaded. Lever
    kuzushi requires real CoM displacement to boost past threshold, so we
    assert on signature (not eq) for the Lever case.
    """
    graph = GripGraph()
    t, s = _pair()
    _seat_deep_grips(graph, t, s)
    t.state.body_state.com_height = 0.90
    s.state.body_state.com_height = 1.08

    _set_clean_trunk(t)
    sig_clean = signature_match(TAI_OTOSHI, t, s, graph)

    _set_hip_engaged(t)
    sig_hip = signature_match(TAI_OTOSHI, t, s, graph)

    assert sig_clean > sig_hip
    # With an engaged_floor of 0.05 and body weight 0.35, the hard collapse
    # should produce a signature drop of at least ~0.1 in practice.
    assert (sig_clean - sig_hip) > 0.10


def test_execution_quality_drops_when_o_soto_hip_engaged() -> None:
    graph = GripGraph()
    t, s = _pair(tori_x=0.0, uke_x=0.45)  # close — contact quality high
    _seat_deep_grips(graph, t, s)
    s.state.body_state.com_velocity = (0.4, 0.0)
    s.state.body_state.facing = (-1.0, 0.0)

    _set_clean_trunk(t)
    sig_clean = signature_match(O_SOTO_GARI, t, s, graph)

    _set_hip_engaged(t)
    sig_hip = signature_match(O_SOTO_GARI, t, s, graph)

    eq_clean = compute_execution_quality(sig_clean, O_SOTO_GARI.commit_threshold)
    eq_hip   = compute_execution_quality(sig_hip,   O_SOTO_GARI.commit_threshold)
    # HAJ-59 target: soft floor should produce ~0.3 eq reduction.
    assert eq_clean > eq_hip
    assert (eq_clean - eq_hip) > 0.10


# ---------------------------------------------------------------------------
# No new compromised state
# ---------------------------------------------------------------------------
def test_no_tori_self_blocked_failure_outcome() -> None:
    """HAJ-59 explicitly does NOT create a TORI_SELF_BLOCKED enum member.
    The phenomenon is quality variation, not a state transition.
    """
    assert not hasattr(FailureOutcome, "TORI_SELF_BLOCKED")


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
