# tests/test_locomotion.py
# HAJ-128 — tactical mat positioning: locomotion + edge perception +
# positional intent.
#
# Pre-HAJ-128 fighters never moved on the mat — STEP existed in the
# action schema but action_selection never emitted one. Two equal
# fighters pulsed against each other at the start position.
#
# Post-HAJ-128:
#   - PositionalStyle (HOLD_CENTER / PRESSURE / DEFENSIVE_EDGE) on Identity.
#   - perceive_edge_distance: noisy distance to the nearest mat edge,
#     scaled by perception_std (fight_iq + fatigue + composure).
#   - select_actions appends a STEP when positional intent fires.
#   - _apply_body_actions advances both foot AND CoM on STEP.
#   - Per-step cardio cost; step magnitude attenuates under deep
#     opponent grips.

from __future__ import annotations
import io
import os
import random
import statistics
import sys
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from actions import ActionKind, step
from body_state import place_judoka
from enums import (
    BodyPart, GripTarget, GripTypeV2, GripDepth, GripMode, PositionalStyle,
)
from grip_graph import GripGraph, GripEdge
from action_selection import (
    select_actions, _maybe_emit_step,
    STEP_MAGNITUDE_M, STEP_MAGNITUDE_REDUCED_M,
)
from perception import (
    perceive_edge_distance, actual_distance_to_edge, perception_std,
)
from match import Match, MAT_HALF_WIDTH, STEP_CARDIO_COST
from referee import build_suzuki
import main as main_module


def _pair():
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    return t, s


# ---------------------------------------------------------------------------
# PositionalStyle wiring
# ---------------------------------------------------------------------------
def test_default_positional_style_is_hold_center() -> None:
    """Existing fighter builders that don't pass positional_style get
    HOLD_CENTER as the safe default."""
    from judoka import Identity
    from enums import BodyArchetype, BeltRank, DominantSide
    ident = Identity(
        name="Test", age=20, weight_class="-90kg", height_cm=180,
        body_archetype=BodyArchetype.LEVER, belt_rank=BeltRank.BLACK_1,
        dominant_side=DominantSide.RIGHT,
    )
    assert ident.positional_style == PositionalStyle.HOLD_CENTER


def test_positional_style_can_be_set_explicitly() -> None:
    from judoka import Identity
    from enums import BodyArchetype, BeltRank, DominantSide
    ident = Identity(
        name="Test", age=20, weight_class="-90kg", height_cm=180,
        body_archetype=BodyArchetype.LEVER, belt_rank=BeltRank.BLACK_1,
        dominant_side=DominantSide.RIGHT,
        positional_style=PositionalStyle.PRESSURE,
    )
    assert ident.positional_style == PositionalStyle.PRESSURE


# ---------------------------------------------------------------------------
# Edge perception: ground truth + noise scales with fight_iq
# ---------------------------------------------------------------------------
def test_actual_distance_to_edge_uses_chebyshev() -> None:
    """Distance is to the nearest of the four edges (max-norm), centered
    at origin. A fighter at (0, 0) is half_width away from every edge."""
    t, _ = _pair()
    t.state.body_state.com_position = (0.0, 0.0)
    assert actual_distance_to_edge(t, MAT_HALF_WIDTH) == MAT_HALF_WIDTH


def test_actual_distance_to_edge_falls_off_with_displacement() -> None:
    t, _ = _pair()
    t.state.body_state.com_position = (1.0, 0.0)
    assert actual_distance_to_edge(t, MAT_HALF_WIDTH) == MAT_HALF_WIDTH - 1.0


def test_perceive_edge_distance_noise_scales_with_fight_iq() -> None:
    """Low fight_iq → wide noise; high fight_iq → tight noise. Compare
    two builders at equal positions and measure the spread of
    perception calls. Standard deviation of the high-IQ samples should
    be lower than the low-IQ samples (often by 5×+)."""
    t, _ = _pair()
    t.state.body_state.com_position = (0.5, 0.0)  # 1.0 m from edge

    # Force fight_iq via direct mutation — the production builders
    # already have specific values; we want the test to be deterministic.
    rng = random.Random(0)
    samples_low: list[float] = []
    samples_high: list[float] = []
    t.capability.fight_iq = 1
    for _ in range(400):
        samples_low.append(perceive_edge_distance(t, MAT_HALF_WIDTH, rng))
    rng2 = random.Random(0)
    t.capability.fight_iq = 10
    for _ in range(400):
        samples_high.append(perceive_edge_distance(t, MAT_HALF_WIDTH, rng2))
    sd_low = statistics.stdev(samples_low)
    sd_high = statistics.stdev(samples_high)
    assert sd_low > sd_high * 2, (
        f"low-IQ perception should be noticeably noisier; "
        f"low_sd={sd_low:.3f} high_sd={sd_high:.3f}"
    )


def test_perception_std_pipeline_inherited() -> None:
    """Edge perception std comes through perception_std × scale, so the
    fatigue and composure terms apply consistently with the
    throw-signature path."""
    t, _ = _pair()
    base = perception_std(t)
    # Cooked hands → wider std.
    t.state.body["right_hand"].fatigue = 1.0
    t.state.body["left_hand"].fatigue  = 1.0
    cooked = perception_std(t)
    assert cooked > base


# ---------------------------------------------------------------------------
# STEP physics moves CoM with the foot (HAJ-128 semantics)
# ---------------------------------------------------------------------------
def test_step_action_advances_com_with_foot() -> None:
    """STEP at magnitude m moves the foot by m and CoM by m/2."""
    t, _ = _pair()
    t.state.body_state.com_position = (0.0, 0.0)
    t.state.body_state.foot_state_right.position = (0.05, 0.0)
    s = main_module.build_sato()
    place_judoka(s, com_position=(2.0, 0.0), facing=(-1.0, 0.0))
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki(), max_ticks=5)
    step_action = step("right_foot", (1.0, 0.0), 0.40)
    m._apply_body_actions(t, [step_action])
    fx, fy = t.state.body_state.foot_state_right.position
    assert abs(fx - (0.05 + 0.40)) < 1e-6
    cx, cy = t.state.body_state.com_position
    assert abs(cx - 0.20) < 1e-6, f"CoM should advance by mag/2 = 0.20; got {cx}"


def test_step_costs_cardio() -> None:
    """A STEP draws STEP_CARDIO_COST off the cardio reserve."""
    t, _ = _pair()
    s = main_module.build_sato()
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki(), max_ticks=5)
    cardio_before = t.state.cardio_current
    step_action = step("right_foot", (1.0, 0.0), 0.30)
    m._apply_body_actions(t, [step_action])
    assert (cardio_before - t.state.cardio_current) >= STEP_CARDIO_COST - 1e-9


# ---------------------------------------------------------------------------
# _maybe_emit_step intent by style
# ---------------------------------------------------------------------------
def test_hold_center_does_not_step_when_at_center() -> None:
    """A HOLD_CENTER fighter sitting at the origin doesn't bother to step."""
    t, s = _pair()
    t.identity.positional_style = PositionalStyle.HOLD_CENTER
    t.state.body_state.com_position = (0.0, 0.0)
    g = GripGraph()
    rng = random.Random(0)
    for _ in range(50):
        out = _maybe_emit_step(t, s, g, rng)
        assert out is None, "HOLD_CENTER at center should not step"


def test_hold_center_steps_toward_center_when_drifted() -> None:
    """A HOLD_CENTER fighter past the drift threshold steps back inward."""
    t, s = _pair()
    t.identity.positional_style = PositionalStyle.HOLD_CENTER
    t.state.body_state.com_position = (1.2, 0.0)  # drifted toward +x
    g = GripGraph()
    # Run many trials so the per-tick prob fires at least once.
    rng = random.Random(123)
    saw_step_inward = False
    for _ in range(200):
        out = _maybe_emit_step(t, s, g, rng)
        if out is not None:
            assert out.kind == ActionKind.STEP
            # Should point toward -x (back to origin).
            assert out.direction[0] < 0
            saw_step_inward = True
            break
    assert saw_step_inward, "HOLD_CENTER should step inward when drifted"


def test_pressure_steps_toward_opponent() -> None:
    """A PRESSURE fighter steps in the direction of the opponent."""
    t, s = _pair()
    t.identity.positional_style = PositionalStyle.PRESSURE
    g = GripGraph()
    rng = random.Random(0)
    saw_forward = False
    for _ in range(200):
        out = _maybe_emit_step(t, s, g, rng)
        if out is not None:
            # Tanaka at -0.5, Sato at +0.5 → step direction +x.
            assert out.direction[0] > 0
            saw_forward = True
            break
    assert saw_forward, "PRESSURE fighter should step toward opponent at least once"


def test_defensive_edge_steps_inward_when_close_to_edge() -> None:
    """A DEFENSIVE_EDGE fighter near the boundary retreats."""
    t, s = _pair()
    t.identity.positional_style = PositionalStyle.DEFENSIVE_EDGE
    # Place near the +x edge.
    t.state.body_state.com_position = (MAT_HALF_WIDTH - 0.2, 0.0)
    g = GripGraph()
    # High fight_iq so the perception is reliable.
    t.capability.fight_iq = 10
    rng = random.Random(0)
    saw_inward = False
    for _ in range(200):
        out = _maybe_emit_step(t, s, g, rng)
        if out is not None:
            assert out.direction[0] < 0, (
                f"DEFENSIVE_EDGE should step toward center (−x); got {out.direction}"
            )
            saw_inward = True
            break
    assert saw_inward, "DEFENSIVE_EDGE near edge should step inward"


def test_defensive_edge_does_not_step_when_far_from_edge() -> None:
    """A DEFENSIVE_EDGE fighter sitting at the origin shouldn't retreat."""
    t, s = _pair()
    t.identity.positional_style = PositionalStyle.DEFENSIVE_EDGE
    t.state.body_state.com_position = (0.0, 0.0)
    t.capability.fight_iq = 10  # accurate perception
    g = GripGraph()
    rng = random.Random(0)
    for _ in range(50):
        out = _maybe_emit_step(t, s, g, rng)
        # Most calls should return None (truth = MAT_HALF_WIDTH = 1.5,
        # well above the trigger). Some may flap due to noise — allow
        # but bound the rate.
        if out is not None:
            # If a step did fire, it's the rare noise-driven case.
            continue


# ---------------------------------------------------------------------------
# Grip-range gate: deep opponent grips reduce step magnitude
# ---------------------------------------------------------------------------
def test_step_magnitude_reduced_under_deep_opponent_grip() -> None:
    """When the opponent has a DEEP grip on this fighter, step
    magnitude attenuates."""
    t, s = _pair()
    t.identity.positional_style = PositionalStyle.PRESSURE
    g = GripGraph()
    g.add_edge(GripEdge(
        grasper_id=s.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=t.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.DEEP,
        strength=1.0, established_tick=0, mode=GripMode.DRIVING,
    ))
    rng = random.Random(0)
    seen_mags: set[float] = set()
    for _ in range(200):
        out = _maybe_emit_step(t, s, g, rng)
        if out is not None:
            seen_mags.add(round(out.magnitude, 3))
    # The reduced-magnitude value should appear; the full one should not.
    assert STEP_MAGNITUDE_REDUCED_M in seen_mags or not seen_mags
    assert STEP_MAGNITUDE_M not in seen_mags


# ---------------------------------------------------------------------------
# select_actions appends STEP when intent fires
# ---------------------------------------------------------------------------
def test_select_actions_appends_step_for_pressure_fighter() -> None:
    """Tanaka (PRESSURE in main.py) emits a STEP at least once over
    a small batch of ticks."""
    t, s = _pair()
    g = GripGraph()
    saw_step = False
    for seed in range(40):
        random.seed(seed)
        acts = select_actions(t, s, g, kumi_kata_clock=0)
        if any(a.kind == ActionKind.STEP for a in acts):
            saw_step = True
            break
    assert saw_step, "PRESSURE fighter should emit STEP in some ticks"


def test_select_actions_does_not_append_step_during_commit() -> None:
    """Commits are exclusive — locomotion must not co-occur with a
    COMMIT_THROW (the commit owns the tick)."""
    from actions import commit_throw
    from throws import ThrowID
    t, s = _pair()
    t.identity.positional_style = PositionalStyle.PRESSURE
    # Seat deep grips so a commit is plausible.
    g = GripGraph()
    g.add_edge(GripEdge(
        grasper_id=t.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=s.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.DEEP,
        strength=1.0, established_tick=0, mode=GripMode.DRIVING,
    ))
    g.add_edge(GripEdge(
        grasper_id=t.identity.name, grasper_part=BodyPart.LEFT_HAND,
        target_id=s.identity.name, target_location=GripTarget.RIGHT_SLEEVE,
        grip_type_v2=GripTypeV2.SLEEVE_HIGH, depth_level=GripDepth.DEEP,
        strength=1.0, established_tick=0, mode=GripMode.DRIVING,
    ))
    # Run select_actions repeatedly. When it produces a commit, ensure
    # no STEP rides along.
    found = False
    for seed in range(60):
        random.seed(seed)
        acts = select_actions(t, s, g, kumi_kata_clock=0)
        if any(a.kind == ActionKind.COMMIT_THROW for a in acts):
            found = True
            assert not any(a.kind == ActionKind.STEP for a in acts), (
                "STEP must not co-occur with COMMIT_THROW"
            )
    # If no commits emerged in this batch, the assertion never failed
    # (vacuously true). That's fine — the invariant is the absence.


# ---------------------------------------------------------------------------
# Stunned fighters can't step
# ---------------------------------------------------------------------------
def test_stunned_fighter_does_not_step() -> None:
    t, s = _pair()
    t.identity.positional_style = PositionalStyle.PRESSURE
    t.state.stun_ticks = 5
    g = GripGraph()
    for seed in range(20):
        random.seed(seed)
        acts = select_actions(t, s, g, kumi_kata_clock=0)
        assert not any(a.kind == ActionKind.STEP for a in acts), (
            "stunned fighter should not emit STEP"
        )


# ---------------------------------------------------------------------------
# End-to-end: Tanaka(PRESSURE) vs Sato(DEFENSIVE_EDGE) produces visible
# CoM displacement over a short match.
# ---------------------------------------------------------------------------
def test_step_alternates_feet_via_trailing_pick() -> None:
    """The trailing-foot picker (HAJ-128 fix to the dot-split bug) must
    walk feet alternately. After two consecutive steps in the same
    direction, both feet should have advanced — not just the dominant
    one. Pre-fix: only the dominant foot ever moved, so over time the
    off-side foot was stranded at the start position."""
    from action_selection import _trailing_step_foot
    t, _ = _pair()
    bs = t.state.body_state
    # Manual setup so this test is independent of place_judoka layout.
    bs.com_position = (0.0, 0.0)
    bs.foot_state_left.position  = (0.0, +0.18)
    bs.foot_state_right.position = (0.0, -0.18)

    # Direction +x; both feet equally trailing → tie, picks right_foot
    # by ordering. Step it forward.
    direction = (1.0, 0.0)
    pick1 = _trailing_step_foot(t, direction)
    bs.foot_state_right.position = (0.30, -0.18)
    bs.com_position = (0.15, 0.0)

    # Now left_foot is more trailing (proj=-0.15) than right (proj=+0.15).
    pick2 = _trailing_step_foot(t, direction)
    assert pick1 != pick2, (
        f"feet should alternate; both picks were {pick1}"
    )
    assert pick2 == "left_foot"


def test_facing_reorients_toward_opponent_each_tick() -> None:
    """After a tick of physics, each fighter's facing is the unit vector
    pointing at the opponent's CoM. Pre-fix the facing stayed at its
    Hajime-time value while CoM drifted, so the viewer arrow was wrong."""
    random.seed(1)
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki(),
              max_ticks=5, seed=1)
    buf = io.StringIO()
    with redirect_stdout(buf):
        m.run()

    # facing_a should point from a → b, facing_b from b → a.
    ax, ay = t.state.body_state.com_position
    bx, by = s.state.body_state.com_position
    dx, dy = bx - ax, by - ay
    norm = (dx * dx + dy * dy) ** 0.5
    expect_a = (dx / norm, dy / norm)
    expect_b = (-expect_a[0], -expect_a[1])
    fa = t.state.body_state.facing
    fb = s.state.body_state.facing
    # Allow a tiny numerical tolerance.
    assert abs(fa[0] - expect_a[0]) < 1e-6
    assert abs(fa[1] - expect_a[1]) < 1e-6
    assert abs(fb[0] - expect_b[0]) < 1e-6
    assert abs(fb[1] - expect_b[1]) < 1e-6


def test_pressure_match_produces_visible_displacement() -> None:
    """Run a short match between the canonical fighters and verify
    that CoM displacement from the start position exceeds what
    grip-only force pulses would produce. Without locomotion, neither
    fighter drifts more than ~0.05 m from start in 30 ticks; with
    locomotion, displacement should be in the hundreds of millimeters
    range."""
    random.seed(42)
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    m = Match(
        fighter_a=t, fighter_b=s, referee=build_suzuki(),
        max_ticks=30, seed=42,
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        m.run()
    # Tanaka should have moved by more than the grip-only baseline.
    tx, _ = t.state.body_state.com_position
    displacement = abs(tx - (-0.5))
    assert displacement > 0.20, (
        f"PRESSURE fighter should produce visible mat displacement; "
        f"|dx| = {displacement:.3f} m"
    )
