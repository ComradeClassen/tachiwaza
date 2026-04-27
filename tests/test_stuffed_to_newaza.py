# tests/test_stuffed_to_newaza.py
# HAJ-140 — stuffing throws should lead to ne-waza.
#
# Pre-fix, attempt_ground_commit's combined transition probability sat
# around 25–35% for typical fighters: stuffed throws stayed standing the
# majority of the time, and the stuffed aggressor (no stun applied) fired
# defensive-desperation commits the same tick they were stuffed —
# producing eq=0.00 throws and unrealistic next-tick scoring (the example
# log in HAJ-140: t211 stuffed, t212 waza-ari).
#
# Post-fix:
#   - Defender baseline ~0.85 + skill bonus → the dispatch fires reliably.
#   - Aggressor still occasionally commits (sacrifice scramble), modulated
#     by ne_waza_skill and window quality.
#   - Stuffed aggressor receives STUFFED_AGGRESSOR_STUN_TICKS so even when
#     the dispatch doesn't fire, they cannot re-commit on the next tick.

from __future__ import annotations
import os
import random as _r
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from body_state import place_judoka
from enums import (
    BodyPart, GripTarget, GripTypeV2, GripDepth, Position, SubLoopState,
)
from grip_graph import GripEdge
from match import (
    Match, STUFFED_AGGRESSOR_STUN_TICKS,
)
from referee import build_suzuki
from throws import ThrowID
from ne_waza import NewazaResolver
import main as main_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _pair_match():
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())
    return t, s, m


def _seat_grips(m, owner, target):
    m.grip_graph.add_edge(GripEdge(
        grasper_id=owner.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=target.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.STANDARD,
        strength=0.8, established_tick=0,
    ))
    m.grip_graph.add_edge(GripEdge(
        grasper_id=owner.identity.name, grasper_part=BodyPart.LEFT_HAND,
        target_id=target.identity.name, target_location=GripTarget.RIGHT_SLEEVE,
        grip_type_v2=GripTypeV2.SLEEVE_HIGH, depth_level=GripDepth.STANDARD,
        strength=0.8, established_tick=0,
    ))


# ---------------------------------------------------------------------------
# 1. attempt_ground_commit empirical probability
# ---------------------------------------------------------------------------
def test_ground_commit_fires_reliably_for_typical_fighters() -> None:
    """Over many rolls, two median-skill fresh fighters should transition
    to ne-waza in the high majority of stuffed throws (>= 80%)."""
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    resolver = NewazaResolver()
    _r.seed(0)
    fires = 0
    trials = 1000
    for _ in range(trials):
        if resolver.attempt_ground_commit(t, s, window_quality=0.5):
            fires += 1
    rate = fires / trials
    assert rate >= 0.80, f"ne-waza dispatch rate {rate:.2%} below 80% target"


def test_ground_commit_skill_scaling() -> None:
    """An elite ne-waza specialist (defender or aggressor) should drive
    the dispatch rate well above the all-novice case. The defender is
    the dominant dispatcher, so an elite defender pulls the rate to
    near-certain transition even against a novice aggressor."""
    elite = main_module.build_tanaka()
    novice = main_module.build_sato()
    elite.capability.ne_waza_skill = 10
    novice.capability.ne_waza_skill = 2
    resolver = NewazaResolver()
    _r.seed(1)
    # Elite as DEFENDER → high dispatch rate.
    elite_def_fires = sum(
        1 for _ in range(500)
        if resolver.attempt_ground_commit(novice, elite, window_quality=0.5)
    )
    assert elite_def_fires / 500 >= 0.90, (
        f"elite defender dispatch rate {elite_def_fires/500:.2%} below 90%"
    )
    # Elite as AGGRESSOR → still well above pre-fix ~25%, defender-skill-
    # gated so this is the lower bound.
    _r.seed(2)
    elite_agg_fires = sum(
        1 for _ in range(500)
        if resolver.attempt_ground_commit(elite, novice, window_quality=0.5)
    )
    assert elite_agg_fires / 500 >= 0.70, (
        f"elite aggressor dispatch rate {elite_agg_fires/500:.2%} below 70%"
    )


def test_ground_commit_never_certain() -> None:
    """The dispatch should top out below 1.0 so there's always some chance
    a stuffed throw resets back to standing — the referee's
    STUFFED_MATTE_TICKS catches that case."""
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    t.capability.ne_waza_skill = 10
    s.capability.ne_waza_skill = 10
    resolver = NewazaResolver()
    _r.seed(42)
    misses = 0
    for _ in range(5000):
        if not resolver.attempt_ground_commit(t, s, window_quality=1.0):
            misses += 1
            break
    # At least one miss in 5000 rolls (clamped at 0.98 each).
    assert misses >= 1


# ---------------------------------------------------------------------------
# 2. Stuffed aggressor is stunned regardless of dispatch outcome
# ---------------------------------------------------------------------------
def test_stuffed_aggressor_receives_stun_ticks() -> None:
    """A stuffed throw applies STUFFED_AGGRESSOR_STUN_TICKS to the
    aggressor so the next-tick action selection rejects any commit."""
    t, s, m = _pair_match()
    m.position = Position.GRIPPING
    _seat_grips(m, t, s)
    assert t.state.stun_ticks == 0
    m._apply_throw_result(
        attacker=t, defender=s, throw_id=ThrowID.UCHI_MATA,
        outcome="STUFFED", net=-3.0, window_quality=0.5, tick=10,
    )
    assert t.state.stun_ticks >= STUFFED_AGGRESSOR_STUN_TICKS


def test_stuffed_aggressor_action_selection_blocked() -> None:
    """A stunned stuffed aggressor must not be able to commit on the
    immediate next tick — action selection's rung-1 stun gate blocks
    even defensive-desperation paths."""
    from action_selection import select_actions
    from actions import ActionKind

    t, s, m = _pair_match()
    m.position = Position.GRIPPING
    _seat_grips(m, t, s)
    m._apply_throw_result(
        attacker=t, defender=s, throw_id=ThrowID.UCHI_MATA,
        outcome="STUFFED", net=-3.0, window_quality=0.5, tick=10,
    )
    # If the dispatch landed in NE_WAZA, the stun is moot; only check
    # the standing-stayed branch.
    if m.sub_loop_state == SubLoopState.STANDING:
        actions = select_actions(
            t, s, m.grip_graph, kumi_kata_clock=0,
            defensive_desperation=True,
            position=m.position,
            current_tick=11,
        )
        # Stunned fighters get the defensive fallback (hold_connective only).
        assert all(a.kind != ActionKind.COMMIT_THROW for a in actions)


# ---------------------------------------------------------------------------
# 3. STUFFED triggers either ne-waza or stun — not the pre-fix "neither"
# ---------------------------------------------------------------------------
def test_stuffed_throw_either_ne_waza_or_aggressor_stunned() -> None:
    """Across many seeds, every stuffed throw must end up in NE_WAZA OR
    leave the aggressor stunned. Pre-fix, ~75% of stuffed throws would
    leave both fighters fully able to act in standing the next tick."""
    import match as match_module
    real_resolve = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: ("STUFFED", -3.0)
    try:
        for seed in range(20):
            _r.seed(seed)
            t, s, m = _pair_match()
            m.position = Position.GRIPPING
            _seat_grips(m, t, s)
            m._apply_throw_result(
                attacker=t, defender=s, throw_id=ThrowID.UCHI_MATA,
                outcome="STUFFED", net=-3.0, window_quality=0.5, tick=10,
            )
            ne_waza_landed = m.sub_loop_state == SubLoopState.NE_WAZA
            aggressor_stunned = t.state.stun_ticks > 0
            assert ne_waza_landed or aggressor_stunned, (
                f"seed {seed}: stuffed left aggressor unstunned in standing"
            )
    finally:
        match_module.resolve_throw = real_resolve


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
