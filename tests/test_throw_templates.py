# tests/test_throw_templates.py
# Verifies Part 4 of design-notes/physics-substrate.md:
#   - ThrowClassification split + default weight ordering (4.1, 4.2)
#   - CoupleThrow / LeverThrow templates compose correctly (4.3, 4.4)
#   - SignatureWeights validation (4.2)
#   - Four-dimension match functions each score in [0, 1] with expected
#     monotonicity (4.2)
#   - Timing-window variant tanks body-parts score outside the window (4.6)
#   - Weighted composition respects the classification's weighting pattern
#
# Part 5 / Part 6 will wire template instances through the commit path in
# match.py. These tests cover the scaffolding in isolation.

from __future__ import annotations
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from enums import (
    BodyPart, GripTypeV2, GripDepth, GripMode, GripTarget, DominantSide,
)
from body_state import place_judoka, FootContactState
from grip_graph import GripGraph, GripEdge
from throw_templates import (
    ThrowClassification,
    CoupleThrow, LeverThrow,
    KuzushiRequirement, GripRequirement, ForceRequirement, ForceKind,
    CoupleBodyPartRequirement, LeverBodyPartRequirement,
    UkePostureRequirement, TimingWindow, CoupleAxis, SupportRequirement,
    UkeBaseState, FailureOutcome, FailureSpec,
    SignatureWeights,
    DEFAULT_COUPLE_WEIGHTS, DEFAULT_LEVER_WEIGHTS,
    default_weights_for,
)
from throw_signature import (
    match_kuzushi_vector, match_force_application,
    match_body_parts, match_uke_posture,
    signature_match,
)
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


def _seoi_lever() -> LeverThrow:
    """A Seoi-nage-shaped Lever template — used to exercise the Lever path."""
    return LeverThrow(
        name="test-seoi",
        kuzushi_requirement=KuzushiRequirement(
            direction=(1.0, 0.2),
            tolerance_rad=math.radians(20),
            min_displacement_past_recoverable=0.15,
        ),
        force_grips=(
            GripRequirement(
                hand="left_hand",
                grip_type=(GripTypeV2.SLEEVE_HIGH,),
                min_depth=GripDepth.STANDARD,
                mode=GripMode.DRIVING,
            ),
            GripRequirement(
                hand="right_hand",
                grip_type=(GripTypeV2.LAPEL_HIGH, GripTypeV2.LAPEL_LOW),
                min_depth=GripDepth.STANDARD,
                mode=GripMode.DRIVING,
            ),
        ),
        required_forces=(
            ForceRequirement(
                hand="left_hand", kind=ForceKind.PULL,
                direction=(1.0, 0.0, -0.5), min_magnitude_n=300.0,
            ),
        ),
        min_lift_force_n=600.0,
        body_part_requirement=LeverBodyPartRequirement(
            fulcrum_body_part=BodyPart.RIGHT_SHOULDER,
            fulcrum_contact_on_uke=BodyPart.CORE,
            fulcrum_offset_below_uke_com_m=0.15,
            tori_supporting_feet=SupportRequirement.DOUBLE_SUPPORT,
        ),
        uke_posture_requirement=UkePostureRequirement(
            trunk_sagittal_range=(0.0, math.radians(30)),
            trunk_frontal_range=(math.radians(-15), math.radians(15)),
            com_height_range=(0.85, 1.2),
            uke_com_over_fulcrum=True,
        ),
        commit_threshold=0.70,
        counter_vulnerability=0.55,
        failure_outcome=FailureSpec(
            primary=FailureOutcome.TORI_STUCK_WITH_UKE_ON_BACK,
            secondary=FailureOutcome.TORI_BENT_FORWARD_LOADED,
            tertiary=FailureOutcome.STANCE_RESET,
        ),
    )


def _uchi_mata_couple() -> CoupleThrow:
    """An Uchi-mata-shaped Couple template."""
    return CoupleThrow(
        name="test-uchi-mata",
        kuzushi_requirement=KuzushiRequirement(
            direction=(1.0, 0.3),
            tolerance_rad=math.radians(30),
            min_velocity_magnitude=0.4,
        ),
        force_grips=(
            GripRequirement(
                hand="left_hand", grip_type=(GripTypeV2.SLEEVE_HIGH,),
                min_depth=GripDepth.STANDARD, mode=GripMode.DRIVING,
            ),
            GripRequirement(
                hand="right_hand",
                grip_type=(GripTypeV2.LAPEL_HIGH, GripTypeV2.COLLAR),
                min_depth=GripDepth.STANDARD, mode=GripMode.DRIVING,
            ),
        ),
        couple_axis=CoupleAxis.SAGITTAL,
        min_torque_nm=500.0,
        body_part_requirement=CoupleBodyPartRequirement(
            tori_supporting_foot="left_foot",
            tori_attacking_limb="right_leg",
            contact_point_on_uke=BodyPart.LEFT_THIGH,
            contact_height_range=(0.55, 0.90),
        ),
        uke_posture_requirement=UkePostureRequirement(
            trunk_sagittal_range=(math.radians(-5), math.radians(20)),
            trunk_frontal_range=(math.radians(-15), math.radians(25)),
            com_height_range=(0.9, 1.2),
            base_state=UkeBaseState.WEIGHT_SHIFTING_FORWARD,
        ),
        commit_threshold=0.55,
        sukashi_vulnerability=0.75,
        failure_outcome=FailureSpec(
            primary=FailureOutcome.TORI_COMPROMISED_SINGLE_SUPPORT,
            secondary=FailureOutcome.UCHI_MATA_SUKASHI,
            tertiary=FailureOutcome.STANCE_RESET,
        ),
    )


def _deashi_harai_timing() -> CoupleThrow:
    """De-ashi-harai-shaped Couple template with a timing_window."""
    base = _uchi_mata_couple()
    return CoupleThrow(
        name="test-deashi",
        kuzushi_requirement=KuzushiRequirement(
            direction=(1.0, 0.0),
            tolerance_rad=math.radians(45),
            min_velocity_magnitude=0.3,
            aligned_with_uke_velocity=True,
        ),
        force_grips=base.force_grips,
        couple_axis=CoupleAxis.TRANSVERSE,
        min_torque_nm=150.0,
        body_part_requirement=CoupleBodyPartRequirement(
            tori_supporting_foot="left_foot",
            tori_attacking_limb="right_foot",
            contact_point_on_uke=BodyPart.RIGHT_FOOT,
            contact_height_range=(0.0, 0.15),
            timing_window=TimingWindow(
                target_foot="right_foot",
                weight_fraction_range=(0.1, 0.3),
                window_duration_ticks=1,
            ),
        ),
        uke_posture_requirement=base.uke_posture_requirement,
        commit_threshold=0.45,
        sukashi_vulnerability=0.25,
        failure_outcome=FailureSpec(
            primary=FailureOutcome.TORI_SWEEP_BOUNCES_OFF,
            secondary=FailureOutcome.STANCE_RESET,
        ),
    )


def _seat_deep_grips(graph: GripGraph, attacker, defender) -> None:
    graph.add_edge(GripEdge(
        grasper_id=attacker.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=defender.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.DEEP,
        strength=1.0, established_tick=0, mode=GripMode.DRIVING,
    ))
    graph.add_edge(GripEdge(
        grasper_id=attacker.identity.name, grasper_part=BodyPart.LEFT_HAND,
        target_id=defender.identity.name, target_location=GripTarget.RIGHT_SLEEVE,
        grip_type_v2=GripTypeV2.SLEEVE_HIGH, depth_level=GripDepth.DEEP,
        strength=1.0, established_tick=0, mode=GripMode.DRIVING,
    ))


# ---------------------------------------------------------------------------
# Part 4.1 / 4.2 — classification and weight structure
# ---------------------------------------------------------------------------
def test_classification_is_set_from_template_type() -> None:
    assert _uchi_mata_couple().classification == ThrowClassification.COUPLE
    assert _seoi_lever().classification == ThrowClassification.LEVER


def test_default_weights_sum_to_one_and_order_by_class() -> None:
    # 4.2: Couple weights body/force > kuzushi; Lever weights kuzushi ≥ force.
    c = DEFAULT_COUPLE_WEIGHTS
    l = DEFAULT_LEVER_WEIGHTS
    assert math.isclose(c.kuzushi + c.force + c.body + c.posture, 1.0)
    assert math.isclose(l.kuzushi + l.force + l.body + l.posture, 1.0)
    assert c.force > c.kuzushi and c.body > c.kuzushi
    assert l.kuzushi > l.force


def test_signature_weights_validation_rejects_bad_sum() -> None:
    try:
        SignatureWeights(kuzushi=0.5, force=0.5, body=0.5, posture=0.0)
    except ValueError:
        return
    raise AssertionError("expected ValueError on weights that don't sum to 1")


def test_default_weights_for_dispatches_by_classification() -> None:
    assert default_weights_for(ThrowClassification.COUPLE) is DEFAULT_COUPLE_WEIGHTS
    assert default_weights_for(ThrowClassification.LEVER)  is DEFAULT_LEVER_WEIGHTS


# ---------------------------------------------------------------------------
# Dimension 1 — kuzushi vector
# ---------------------------------------------------------------------------
def test_kuzushi_zero_when_defender_is_stationary() -> None:
    t, s = _pair()
    throw = _uchi_mata_couple()
    assert match_kuzushi_vector(throw, t, s) == 0.0


def test_kuzushi_scores_high_with_forward_velocity_matching_direction() -> None:
    t, s = _pair()
    # Sato faces (-1, 0). HAJ-132 — kuzushi-vector reads the event buffer.
    # A forward-kuzushi event (mat-frame -X) translates to +X in Sato's body
    # frame, satisfying Uchi-mata's +X direction.
    seed_kuzushi_from_velocity(s, (-0.6, 0.0))
    throw = _uchi_mata_couple()
    assert match_kuzushi_vector(throw, t, s) >= 0.9


def test_kuzushi_penalizes_misaligned_velocity() -> None:
    t, s = _pair()
    seed_kuzushi_from_velocity(s, (0.0, 0.6))   # perpendicular to +X
    throw = _uchi_mata_couple()
    # Direction score collapses but magnitude floor is met.
    score = match_kuzushi_vector(throw, t, s)
    assert 0.0 <= score <= 0.6


def test_kuzushi_aligned_with_uke_velocity_flag_ignores_direction() -> None:
    t, s = _pair()
    seed_kuzushi_from_velocity(s, (0.0, 0.5))   # lateral
    throw = _deashi_harai_timing()
    assert match_kuzushi_vector(throw, t, s) >= 0.9


# ---------------------------------------------------------------------------
# Dimension 2 — force application
# ---------------------------------------------------------------------------
def test_force_zero_without_grips() -> None:
    t, s = _pair()
    g = GripGraph()
    # Use a Lever template so the Couple "uke-ungripped" bonus (Part 4.3
    # force-application modulator) doesn't apply; this tests the base
    # computation in isolation.
    throw = _seoi_lever()
    assert match_force_application(throw, t, s, g) == 0.0


def test_force_scores_both_components_with_deep_driving_grips() -> None:
    t, s = _pair()
    g = GripGraph()
    _seat_deep_grips(g, t, s)
    throw = _uchi_mata_couple()
    score = match_force_application(throw, t, s, g)
    # Grip-presence component is 1.0; delivered force floors are tuned to be
    # well met by 2×DEEP DRIVING grips on an athletic attacker.
    assert score >= 0.75


def test_force_zero_when_grips_are_connective_not_driving() -> None:
    t, s = _pair()
    g = GripGraph()
    _seat_deep_grips(g, t, s)
    # Seat a token uke-owned edge so the Couple "uke-ungripped" bonus
    # (Part 4.3 force-application modulator) doesn't perturb the zero.
    g.add_edge(GripEdge(
        grasper_id=s.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=t.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.POCKET,
        strength=0.5, established_tick=0, mode=GripMode.CONNECTIVE,
    ))
    for e in g.edges:
        e.mode = GripMode.CONNECTIVE
    throw = _uchi_mata_couple()
    # Grip-presence fails (mode mismatch) AND delivered DRIVING force is zero.
    assert match_force_application(throw, t, s, g) == 0.0


# ---------------------------------------------------------------------------
# Dimension 3 — body parts (Couple + Lever + timing window)
# ---------------------------------------------------------------------------
def test_couple_body_parts_full_when_support_and_limb_present() -> None:
    t, s = _pair()
    throw = _uchi_mata_couple()
    assert match_body_parts(throw, t, s) >= 0.9


def test_couple_body_parts_zero_when_supporting_foot_airborne() -> None:
    t, s = _pair()
    t.state.body_state.foot_state_left.contact_state = FootContactState.AIRBORNE
    throw = _uchi_mata_couple()
    # One of two checks fails (supporting-foot), so score halves.
    assert match_body_parts(throw, t, s) < 0.6


def test_lever_body_parts_needs_double_support_and_fulcrum_offset() -> None:
    t, s = _pair()
    throw = _seoi_lever()
    # Tori's CoM height equals uke's (shizentai). Offset = 0, fulcrum-score = 0.
    score_flat = match_body_parts(throw, t, s)
    # Drop Tanaka's CoM to simulate the "hips below uke's hips" seoi entry.
    t.state.body_state.com_height = s.state.body_state.com_height - 0.20
    score_dropped = match_body_parts(throw, t, s)
    assert score_dropped > score_flat
    assert score_dropped >= 0.9


def test_timing_window_zeros_body_parts_outside_the_window() -> None:
    t, s = _pair()
    throw = _deashi_harai_timing()
    # Default shizentai: weight_fraction 0.5 for each foot — outside (0.1, 0.3).
    outside = match_body_parts(throw, t, s)
    # Now slide it into the window.
    s.state.body_state.foot_state_right.weight_fraction = 0.2
    inside = match_body_parts(throw, t, s)
    assert inside > outside
    assert outside < 0.5


# ---------------------------------------------------------------------------
# Dimension 4 — uke posture
# ---------------------------------------------------------------------------
def test_posture_full_in_shizentai_for_upright_permitted_throw() -> None:
    t, s = _pair()
    throw = _uchi_mata_couple()
    assert match_uke_posture(throw, s) == 1.0


def test_posture_drops_when_trunk_outside_range() -> None:
    t, s = _pair()
    s.state.body_state.trunk_sagittal = math.radians(40)   # beyond (-5°, +20°)
    throw = _uchi_mata_couple()
    # One of three checks fails.
    assert match_uke_posture(throw, s) < 1.0


# ---------------------------------------------------------------------------
# Composed signature
# ---------------------------------------------------------------------------
def test_signature_match_is_between_zero_and_one() -> None:
    t, s = _pair()
    g = GripGraph()
    _seat_deep_grips(g, t, s)
    seed_kuzushi_from_velocity(s, (-0.6, 0.0))
    throw = _uchi_mata_couple()
    score = signature_match(throw, t, s, g)
    assert 0.0 <= score <= 1.0
    assert score > 0.5   # All four dimensions at least partially firing.


def test_signature_match_lever_weighting_differs_from_couple() -> None:
    """A scenario where kuzushi is strong but grips are absent should score
    differently under Lever weighting (kuzushi heavier) vs Couple weighting
    (force/body heavier).
    """
    t, s = _pair()
    g = GripGraph()
    # No grips. Strong kuzushi event composed in uke's buffer.
    s.state.body_state.com_position = (1.0, 0.0)
    seed_kuzushi_from_velocity(s, (-0.5, 0.0))   # forward in uke's frame

    couple = _uchi_mata_couple()
    lever  = _seoi_lever()
    # Lower Tanaka to satisfy seoi fulcrum offset.
    t.state.body_state.com_height = s.state.body_state.com_height - 0.20

    c_score = signature_match(couple, t, s, g)
    l_score = signature_match(lever, t, s, g)
    # Lever weighting puts more mass on kuzushi; with grips missing but
    # kuzushi strong, the Lever score should be at least as high as Couple's.
    assert l_score >= c_score


def test_signature_respects_custom_weights_override() -> None:
    t, s = _pair()
    g = GripGraph()
    throw = _uchi_mata_couple()
    # 100% weight on posture — only this dimension contributes.
    w = SignatureWeights(kuzushi=0.0, force=0.0, body=0.0, posture=1.0)
    # Posture is in range at shizentai → full score.
    assert signature_match(throw, t, s, g, weights=w) == 1.0


# ---------------------------------------------------------------------------
# Entry point for direct pytest-less running
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
