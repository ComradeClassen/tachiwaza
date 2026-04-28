# tests/test_pull_self_cancellation.py
# HAJ-136 — pull self-cancellation: soft-vs-hard emergent from skill.
#
# Pre-fix all PULLs of the same drive_mag delivered the same envelope-
# bounded force regardless of how the attacker was actually moving.
# Per grip-as-cause.md §13.8, the soft-pull question resolves as
# emergent: a novice pulling while stepping toward uke moves their
# base under the force vector → the lever arm collapses → delivered
# force is reduced. They feel like they pulled hard; they actually
# pulled soft. White-belt judo isn't weaker, it's mechanically
# self-defeating in a way black-belt judo isn't.
#
# Post-fix:
#   - pull_self_cancellation_factor reads attacker CoM velocity vs.
#     pull direction; cancel_speed is the speed component along the
#     wrong axis.
#   - pull_execution skill axis (stubbed from fight_iq) modulates how
#     much of the raw cancellation actually lands on delivered force.
#   - KuzushiEvent magnitude reflects actual delivered force.
#   - Physics force in _compute_net_force_on also gets the factor.

from __future__ import annotations
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from body_state import place_judoka
from enums import (
    BodyPart, GripTarget, GripTypeV2, GripDepth,
)
from grip_graph import GripEdge
from kuzushi import (
    KuzushiSource,
    pull_self_cancellation_factor, pull_kuzushi_event, pull_kuzushi_magnitude,
    PULL_CANCELLATION_MIN_FACTOR, PULL_CANCELLATION_SAT_SPEED,
)
import main as main_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _pair():
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    return t, s


def _seat_lapel(graph, owner, target):
    edge = GripEdge(
        grasper_id=owner.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=target.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.STANDARD,
        strength=0.8, established_tick=0,
    )
    graph.add_edge(edge)
    return edge


# ---------------------------------------------------------------------------
# 1. Cancellation factor math.
# ---------------------------------------------------------------------------
def test_planted_attacker_has_no_cancellation() -> None:
    """Zero CoM velocity → factor = 1.0 (no cancellation possible)."""
    t, _ = _pair()
    t.state.body_state.com_velocity = (0.0, 0.0)
    pull_dir = (-1.0, 0.0)   # drawing opp toward attacker (toward -x)
    factor = pull_self_cancellation_factor(t, pull_dir)
    assert factor == 1.0


def test_pulling_with_motion_no_cancellation() -> None:
    """Attacker moving WITH the pull (stepping back as they pull) is the
    clean-pull case — base moves away from force vector, lever arm
    holds. Factor should be 1.0."""
    t, _ = _pair()
    pull_dir = (-1.0, 0.0)   # force on uke toward -x
    # Attacker steps in -x direction (away from uke at +x). dot is positive.
    t.state.body_state.com_velocity = (-0.4, 0.0)
    factor = pull_self_cancellation_factor(t, pull_dir)
    assert factor == 1.0


def test_stepping_into_pull_cancels_for_novice() -> None:
    """Low-skill attacker stepping toward uke while pulling — full
    self-cancellation exposure."""
    t, _ = _pair()
    t.capability.fight_iq = 0
    t.skill_vector.pull_execution = 0.0   # zero pull_execution skill
    # Pull direction is opp→me (toward -x); attacker moves toward +x (toward uke).
    pull_dir = (-1.0, 0.0)
    t.state.body_state.com_velocity = (PULL_CANCELLATION_SAT_SPEED, 0.0)
    factor = pull_self_cancellation_factor(t, pull_dir)
    # Saturated cancel + zero skill → factor at the floor.
    assert abs(factor - PULL_CANCELLATION_MIN_FACTOR) < 1e-9


def test_stepping_into_pull_minimal_for_elite() -> None:
    """High-skill attacker eats almost no penalty — the body knows
    how to brace and pull cleanly even while moving."""
    t, _ = _pair()
    t.capability.fight_iq = 10
    t.skill_vector.pull_execution = 1.0   # max pull_execution skill
    pull_dir = (-1.0, 0.0)
    t.state.body_state.com_velocity = (PULL_CANCELLATION_SAT_SPEED, 0.0)
    factor = pull_self_cancellation_factor(t, pull_dir)
    # Elite nullifies the effective penalty entirely.
    assert factor == 1.0


def test_partial_cancel_scales_with_skill() -> None:
    """At a fixed cancellation speed, factor is a monotone function of
    pull_execution skill."""
    t, _ = _pair()
    pull_dir = (-1.0, 0.0)
    t.state.body_state.com_velocity = (PULL_CANCELLATION_SAT_SPEED * 0.5, 0.0)
    t.skill_vector.pull_execution = 0.1
    f_low = pull_self_cancellation_factor(t, pull_dir)
    t.skill_vector.pull_execution = 0.5
    f_mid = pull_self_cancellation_factor(t, pull_dir)
    t.skill_vector.pull_execution = 1.0
    f_high = pull_self_cancellation_factor(t, pull_dir)
    assert f_low < f_mid < f_high
    assert f_high == 1.0


def test_zero_pull_direction_returns_one() -> None:
    """Defensive — zero pull direction is a no-op."""
    t, _ = _pair()
    t.state.body_state.com_velocity = (1.0, 0.0)
    assert pull_self_cancellation_factor(t, (0.0, 0.0)) == 1.0


# ---------------------------------------------------------------------------
# 2. Magnitude is reduced via pull_kuzushi_event.
# ---------------------------------------------------------------------------
def test_event_magnitude_reflects_actual_delivered_force() -> None:
    """Same pull, same grip, two CoM states (planted vs. self-cancelling).
    The novice's emitted event must be smaller than the planted version."""
    from grip_graph import GripGraph
    t, s = _pair()
    # Low pull_execution but non-zero (pull_kuzushi_magnitude reads
    # pull_execution as the technique factor; 0 zeros the whole event).
    t.skill_vector.pull_execution = 0.1
    g = GripGraph()
    edge = _seat_lapel(g, t, s)
    pull_dir = (-1.0, 0.0)

    # Planted attacker: clean pull.
    t.state.body_state.com_velocity = (0.0, 0.0)
    ev_clean = pull_kuzushi_event(
        attacker=t, edge=edge, victim=s,
        pull_direction=pull_dir, current_tick=1,
    )

    # Stepping into the pull: muddled.
    t.state.body_state.com_velocity = (PULL_CANCELLATION_SAT_SPEED, 0.0)
    ev_muddled = pull_kuzushi_event(
        attacker=t, edge=edge, victim=s,
        pull_direction=pull_dir, current_tick=2,
    )

    assert ev_clean is not None and ev_muddled is not None
    assert ev_muddled.magnitude < ev_clean.magnitude
    # At fight_iq=1, pull_execution=0.1 → effective cancel = 0.9 ×
    # (1 - 0.3) = 0.63 → factor ≈ 0.37. Half-magnitude or less proves
    # the felt-hard, actually-soft pattern.
    assert ev_muddled.magnitude <= ev_clean.magnitude * 0.5


def test_elite_event_magnitude_unaffected_by_motion() -> None:
    """At max pull_execution, motion doesn't reduce the emitted event."""
    from grip_graph import GripGraph
    t, s = _pair()
    t.skill_vector.pull_execution = 1.0
    g = GripGraph()
    edge = _seat_lapel(g, t, s)
    pull_dir = (-1.0, 0.0)

    t.state.body_state.com_velocity = (0.0, 0.0)
    ev_clean = pull_kuzushi_event(
        attacker=t, edge=edge, victim=s,
        pull_direction=pull_dir, current_tick=1,
    )
    t.state.body_state.com_velocity = (PULL_CANCELLATION_SAT_SPEED, 0.0)
    ev_moving = pull_kuzushi_event(
        attacker=t, edge=edge, victim=s,
        pull_direction=pull_dir, current_tick=2,
    )
    assert ev_clean is not None and ev_moving is not None
    assert abs(ev_moving.magnitude - ev_clean.magnitude) < 1e-6


# ---------------------------------------------------------------------------
# 3. Physics force is reduced via _compute_net_force_on (in match.py).
# ---------------------------------------------------------------------------
def test_physics_force_reduced_for_self_cancelling_pull() -> None:
    """The Match-level force computation must also apply the factor —
    the kuzushi event mirrors physics, not a different number."""
    import random
    random.seed(0)
    from match import Match
    from referee import build_suzuki
    from actions import pull as pull_action

    t, s = _pair()
    t.skill_vector.pull_execution = 0.1
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())
    edge = _seat_lapel(m.grip_graph, t, s)
    edge.depth_level = GripDepth.DEEP   # full envelope to make signal clearer

    pull_dir = (-1.0, 0.0)
    pull_act = pull_action("right_hand", pull_dir, 400.0)

    # Planted CoM: clean pull, physics force should be near full.
    t.state.body_state.com_velocity = (0.0, 0.0)
    random.seed(0)
    fx_clean, _ = m._compute_net_force_on(
        victim=s, attacker=t, attacker_actions=[pull_act], tick=1,
    )

    # CoM stepping into pull at saturation: novice eats full penalty.
    t.state.body_state.com_velocity = (PULL_CANCELLATION_SAT_SPEED, 0.0)
    random.seed(0)
    fx_muddled, _ = m._compute_net_force_on(
        victim=s, attacker=t, attacker_actions=[pull_act], tick=2,
    )

    # Force is in -x direction; both should be negative.
    assert fx_clean < 0.0
    assert fx_muddled < 0.0
    # Muddled magnitude is meaningfully smaller (closer to zero).
    assert abs(fx_muddled) < abs(fx_clean)


# ---------------------------------------------------------------------------
# 4. The "felt-hard, actually-weak" pattern emerges across many pulls.
# ---------------------------------------------------------------------------
def test_novice_kuzushi_doesnt_compose_to_throw_threshold() -> None:
    """Novice fires several pulls while stepping forward. Each event is
    small. The composed kuzushi state stays below the magnitudes a clean
    pull would build."""
    from kuzushi import compromised_state, record_kuzushi_event
    from grip_graph import GripGraph

    def run_three(precision: float, com_velocity: tuple[float, float]) -> float:
        t, s = _pair()
        t.skill_vector.pull_execution = precision
        t.state.body_state.com_velocity = com_velocity
        g = GripGraph()
        edge = _seat_lapel(g, t, s)
        for tick in range(1, 4):
            ev = pull_kuzushi_event(
                attacker=t, edge=edge, victim=s,
                pull_direction=(-1.0, 0.0), current_tick=tick,
            )
            if ev is not None:
                record_kuzushi_event(s, ev)
        state = compromised_state(s.kuzushi_events, current_tick=4)
        return state.magnitude

    novice_into_pull = run_three(
        precision=0.1, com_velocity=(PULL_CANCELLATION_SAT_SPEED, 0.0),
    )
    elite_into_pull = run_three(
        precision=1.0, com_velocity=(PULL_CANCELLATION_SAT_SPEED, 0.0),
    )
    elite_planted = run_three(
        precision=1.0, com_velocity=(0.0, 0.0),
    )

    # Novice's composed kuzushi is materially smaller than elite's at
    # the same motion (the §13.8 emergent-soft-pull pattern).
    assert novice_into_pull < elite_into_pull
    # Elite is unaffected by the motion (planted ≈ moving).
    assert abs(elite_into_pull - elite_planted) < elite_planted * 0.05


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
