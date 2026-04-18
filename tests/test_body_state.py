# tests/test_body_state.py
# Verifies Part 1 of design-notes/physics-substrate.md:
#   - BodyState initial values (Part 1.8)
#   - base_polygon geometry (Part 1.4)
#   - recoverable_envelope + is_kuzushi predicate (Part 1.5)
#   - Posture derivation from continuous trunk angles (Part 1.3)

from __future__ import annotations
import os
import sys
from math import pi, hypot

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from body_state import (
    BodyState, FootState, FootContactState, ContactState,
    base_polygon, recoverable_envelope, is_kuzushi, derive_posture,
    fresh_body_state, place_judoka, SHOULDER_WIDTH_M, FOOT_LENGTH_M,
)
from enums import Posture
from judoka import State
import main as main_module


# ---------------------------------------------------------------------------
# Part 1.8 — initial state of both judoka at Hajime
# ---------------------------------------------------------------------------
def test_hajime_initial_state_matches_part_1_8() -> None:
    tanaka = main_module.build_tanaka()
    sato   = main_module.build_sato()
    place_judoka(tanaka, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(sato,   com_position=(+0.5, 0.0), facing=(-1.0, 0.0))

    # 1.0 m CoM-to-CoM separation
    dx = tanaka.state.body_state.com_position[0] - sato.state.body_state.com_position[0]
    dy = tanaka.state.body_state.com_position[1] - sato.state.body_state.com_position[1]
    assert abs(hypot(dx, dy) - 1.0) < 1e-9

    for j in (tanaka, sato):
        bs = j.state.body_state
        # shizentai: zero velocity, upright, shoulder-width feet
        assert bs.com_velocity == (0.0, 0.0)
        assert bs.trunk_sagittal == 0.0
        assert bs.trunk_frontal == 0.0
        assert bs.foot_state_left.contact_state == FootContactState.PLANTED
        assert bs.foot_state_right.contact_state == FootContactState.PLANTED
        assert abs(bs.foot_state_left.weight_fraction - 0.5) < 1e-9
        assert abs(bs.foot_state_right.weight_fraction - 0.5) < 1e-9
        # com_height pulled from identity.hip_height_cm (0.85–1.15 m envelope)
        assert 0.85 <= bs.com_height <= 1.15
        # Feet are SUPPORTING_GROUND; other parts are FREE.
        assert j.state.body.get("right_foot").contact_state == ContactState.SUPPORTING_GROUND
        assert j.state.body.get("left_foot").contact_state == ContactState.SUPPORTING_GROUND
        assert j.state.body.get("right_hand").contact_state == ContactState.FREE
        # Stun / cardio / composure at initial values.
        assert j.state.stun_ticks == 0
        assert j.state.cardio_current == 1.0
        assert j.state.composure_current == float(j.capability.composure_ceiling)
        # Derived posture lands on UPRIGHT.
        assert j.state.posture == Posture.UPRIGHT

    # Shoulder-width separation between the two feet of one judoka.
    lf = tanaka.state.body_state.foot_state_left.position
    rf = tanaka.state.body_state.foot_state_right.position
    assert abs(hypot(lf[0] - rf[0], lf[1] - rf[1]) - SHOULDER_WIDTH_M) < 1e-9


# ---------------------------------------------------------------------------
# Part 1.4 — base_polygon geometry
# ---------------------------------------------------------------------------
def test_base_polygon_double_support_is_non_degenerate() -> None:
    bs = fresh_body_state()
    poly = base_polygon(bs)
    assert len(poly) >= 4          # it is at least a quadrilateral
    # The CoM projection sits inside the BoS in shizentai.
    from body_state import _point_in_polygon
    assert _point_in_polygon(bs.com_position, poly)


def test_base_polygon_single_support_collapses_to_one_foot() -> None:
    bs = fresh_body_state()
    bs.foot_state_left.contact_state = FootContactState.AIRBORNE
    poly = base_polygon(bs)
    assert len(poly) == 4   # a single foot's 4 corners
    # Polygon hugs the right foot.
    rx, ry = bs.foot_state_right.position
    for px, py in poly:
        assert abs(px - rx) <= FOOT_LENGTH_M
        assert abs(py - ry) <= FOOT_LENGTH_M


def test_base_polygon_no_support_is_empty() -> None:
    bs = fresh_body_state()
    bs.foot_state_left.contact_state = FootContactState.AIRBORNE
    bs.foot_state_right.contact_state = FootContactState.AIRBORNE
    assert base_polygon(bs) == []


# ---------------------------------------------------------------------------
# Part 1.5 — recoverable_envelope and kuzushi predicate
# ---------------------------------------------------------------------------
def test_kuzushi_false_when_static_and_com_inside_base() -> None:
    bs = fresh_body_state()
    assert is_kuzushi(bs, leg_strength=0.8, fatigue=0.0, composure=1.0) is False


def test_kuzushi_true_when_com_far_outside_envelope() -> None:
    bs = fresh_body_state()
    # Shove the CoM 5 m away — well outside any plausible envelope.
    bs.com_position = (5.0, 0.0)
    assert is_kuzushi(bs, leg_strength=0.8, fatigue=0.0, composure=1.0) is True


def test_envelope_narrows_opposite_to_velocity() -> None:
    """Part 1.5: forward-moving judoka cannot easily recover to the rear.

    Compare the same envelope static vs. moving at 1.5 m/s. The pure-forward
    extent should be unchanged (motion aids forward recovery); the pure-rear
    extent should collapse to approximately the BoS edge.
    """
    bs_static = fresh_body_state(facing=(1.0, 0.0))
    bs_moving = fresh_body_state(facing=(1.0, 0.0))
    bs_moving.com_velocity = (1.5, 0.0)

    env_static = recoverable_envelope(bs_static, 1.0, 0.0, 1.0)
    env_moving = recoverable_envelope(bs_moving, 1.0, 0.0, 1.0)

    # Sample 0 is theta=0 → pure forward (+x). Sample ENVELOPE_SAMPLES/2 is
    # pure backward (−x).
    from body_state import ENVELOPE_SAMPLES
    rear_idx = ENVELOPE_SAMPLES // 2

    # Forward reach unchanged under forward motion.
    assert abs(env_static[0][0] - env_moving[0][0]) < 1e-6

    # Rear reach collapses to ~BoS edge (no envelope extension).
    assert env_moving[rear_idx][0] > env_static[rear_idx][0]   # closer to origin
    assert env_moving[rear_idx][0] > -0.2                       # near the BoS


def test_envelope_shrinks_with_fatigue_and_composure() -> None:
    bs = fresh_body_state()
    fresh = recoverable_envelope(bs, leg_strength=1.0, fatigue=0.0, composure=1.0)
    tired = recoverable_envelope(bs, leg_strength=1.0, fatigue=0.8, composure=0.3)
    # Compute forward reach in each case and confirm monotone shrinkage.
    assert max(p[0] for p in fresh) > max(p[0] for p in tired)


def test_no_support_always_kuzushi() -> None:
    bs = fresh_body_state()
    bs.foot_state_left.contact_state = FootContactState.AIRBORNE
    bs.foot_state_right.contact_state = FootContactState.AIRBORNE
    assert is_kuzushi(bs, leg_strength=1.0, fatigue=0.0, composure=1.0) is True


# ---------------------------------------------------------------------------
# Part 1.3 — posture derivation from continuous trunk angles
# ---------------------------------------------------------------------------
def test_derive_posture_upright_for_near_zero_lean() -> None:
    assert derive_posture(0.0, 0.0) == Posture.UPRIGHT
    assert derive_posture(5 * pi / 180, 0.0) == Posture.UPRIGHT


def test_derive_posture_slightly_bent_for_moderate_lean() -> None:
    assert derive_posture(25 * pi / 180, 0.0) == Posture.SLIGHTLY_BENT


def test_derive_posture_broken_for_deep_lean() -> None:
    assert derive_posture(50 * pi / 180, 0.0) == Posture.BROKEN
    # Frontal lean alone can also break posture.
    assert derive_posture(0.0, 40 * pi / 180) == Posture.BROKEN


# ---------------------------------------------------------------------------
# Integration: end-to-end match still runs
# ---------------------------------------------------------------------------
def test_match_still_runs_end_to_end() -> None:
    import random
    from match import Match
    from referee import build_suzuki

    random.seed(42)
    tanaka = main_module.build_tanaka()
    sato   = main_module.build_sato()
    place_judoka(tanaka, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(sato,   com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    Match(fighter_a=tanaka, fighter_b=sato, referee=build_suzuki()).run()


if __name__ == "__main__":
    # Dead-simple runner without pytest dependency.
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
