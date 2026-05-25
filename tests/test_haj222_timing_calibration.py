# tests/test_haj222_timing_calibration.py
# HAJ-222 — engine timing calibration regression tests.
#
# Three issues from the seed-1974183401 playtest:
#   1. Cognitive event collapse — perception, intent, and execution all
#      fire at lag=0. Post-fix: perception fires at minimum 1 tick lag
#      for elite, scaling with fight_iq and telegraph clarity.
#   2. Matte fires during active throw resolution. Post-fix: stuffed-throw
#      matte defers while any throw is in flight; matte clears every
#      pending throw-resolution consequence.
#   3. Composure decay rate too aggressive — both judoka enter defensive
#      desperation 25 seconds into a four-minute match. Post-fix:
#      ENTRY_THRESHOLD raised so routine exchange pressure no longer
#      trips the gate.

from __future__ import annotations
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from body_state import place_judoka
from defensive_desperation import (
    DefensivePressureTracker, ENTRY_THRESHOLD,
)
from enums import (
    BeltRank, BodyPart, GripTypeV2, GripDepth, GripMode, GripTarget,
    MatteReason, Position, SubLoopState,
)
from grip_graph import GripGraph, GripEdge
from match import Match, _Consequence
from reaction_lag import (
    LAG_CLAMP_MIN, LAG_CLAMP_MAX, expected_lag, sample_lag,
)
from referee import build_suzuki, MatchState
from skill_vector import set_uniform
import main as main_module


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _pair():
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    return t, s


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


# ===========================================================================
# Issue 1 — Perception lag floor
# ===========================================================================
def test_lag_clamp_min_is_one_tick_post_haj222() -> None:
    """HAJ-222 AC: perception cannot fire on the commit tick itself.
    At our tick resolution (~1 s), even elite physical reaction takes
    at least one tick to register."""
    assert LAG_CLAMP_MIN >= 1, (
        f"LAG_CLAMP_MIN must be >= 1 post-HAJ-222 (got {LAG_CLAMP_MIN})"
    )


def test_elite_base_lag_at_least_one_tick() -> None:
    """Elite (iq=10) baseline lag is ~1 tick — the spec's floor."""
    t, s = _pair()
    set_uniform(t, 0.5)
    set_uniform(s, 0.5)
    t.capability.fight_iq = 10
    s.capability.fight_iq = 10
    base = expected_lag(t, s)
    assert 0.5 <= base <= 1.5, (
        f"elite base lag should be ~1.0 at neutral disguise, got {base}"
    )


def test_mid_base_lag_is_two_to_three_ticks() -> None:
    """Mid-level (iq=5) baseline lag sits in the 2–3 tick band."""
    t, s = _pair()
    set_uniform(t, 0.5)
    set_uniform(s, 0.5)
    t.capability.fight_iq = 5
    s.capability.fight_iq = 5
    base = expected_lag(t, s)
    assert 2.0 <= base <= 3.0, (
        f"mid base lag should sit in [2, 3] at neutral disguise, got {base}"
    )


def test_novice_base_lag_is_three_to_five_ticks() -> None:
    """Novice (iq=0) baseline lag sits in the 3–5 tick band."""
    t, s = _pair()
    set_uniform(t, 0.5)
    set_uniform(s, 0.5)
    t.capability.fight_iq = 0
    s.capability.fight_iq = 0
    base = expected_lag(t, s)
    assert 3.0 <= base <= 5.0, (
        f"novice base lag should sit in [3, 5] at neutral disguise, got {base}"
    )


def test_sloppy_telegraph_speeds_up_perception() -> None:
    """A sloppy / well-telegraphed commit (disguise=0) reads faster
    than a hidden one (disguise=1) for the same perceiver."""
    t, s = _pair()
    t.capability.fight_iq = 5
    # Tori's disguise — set sequencing + pull_execution to 0 (sloppy).
    set_uniform(s, 0.0)
    sloppy_lag = expected_lag(t, s)
    # Tori now well-hidden.
    set_uniform(s, 1.0)
    hidden_lag = expected_lag(t, s)
    assert sloppy_lag < hidden_lag, (
        f"sloppy telegraph should shorten lag: "
        f"sloppy={sloppy_lag}, hidden={hidden_lag}"
    )


def test_sample_lag_never_below_one() -> None:
    """Across many draws and every fight_iq, sampled lag is >= 1."""
    rng = random.Random(11)
    t, s = _pair()
    for iq in (0, 3, 5, 7, 10):
        t.capability.fight_iq = iq
        s.capability.fight_iq = iq
        for _ in range(200):
            lag = sample_lag(t, s, rng=rng)
            assert lag >= 1, f"sampled lag below 1 at iq={iq}: {lag}"


# ===========================================================================
# Issue 2 — Matte ordering + state cleanup
# ===========================================================================
def _build_matte_state(
    *, stuffed_tick: int, current_tick: int, any_throw_in_flight: bool,
) -> MatchState:
    return MatchState(
        tick=current_tick,
        position=Position.GRIPPING,
        sub_loop_state=SubLoopState.STANDING,
        fighter_a_id="A", fighter_b_id="B",
        fighter_a_score={"ippon": False, "waza_ari": 0},
        fighter_b_score={"ippon": False, "waza_ari": 0},
        fighter_a_last_attack_tick=0, fighter_b_last_attack_tick=0,
        fighter_a_shidos=0, fighter_b_shidos=0,
        ne_waza_active=False,
        osaekomi_holder_id=None, osaekomi_ticks=0,
        stalemate_ticks=0, stuffed_throw_tick=stuffed_tick,
        any_throw_in_flight=any_throw_in_flight,
    )


def test_stuffed_matte_defers_while_throw_in_flight() -> None:
    """HAJ-222 issue 2 part 1 — when a fresh throw is mid-resolution,
    the stuffed-throw matte must NOT fire. Pre-fix the stuffed_throw_tick
    from a prior exchange could trigger matte on the same tick a new
    commit was running its reach-kuzushi / kuzushi sub-events."""
    ref = build_suzuki()
    # Stuff happened long enough ago that the post-stuff window has
    # elapsed (stuffed_throw_tolerance=0.3 → STUFFED_MATTE_TICKS=6).
    in_flight_state = _build_matte_state(
        stuffed_tick=20, current_tick=30, any_throw_in_flight=True,
    )
    assert ref.should_call_matte(in_flight_state, current_tick=30) is None, (
        "matte must not fire while a throw is in flight"
    )
    # Same window, no in-flight throw → matte fires.
    clean_state = _build_matte_state(
        stuffed_tick=20, current_tick=30, any_throw_in_flight=False,
    )
    assert ref.should_call_matte(clean_state, current_tick=30) == (
        MatteReason.STUFFED_THROW_TIMEOUT
    )


def test_matte_clears_pending_throw_resolution_consequences() -> None:
    """HAJ-222 issue 2 part 2 — Matte must drop every pending
    throw-resolution consequence so no stray failure event fires for
    a throw the referee has already declared dead. Pre-fix the t035
    stray "harai-goshi failed" from seed 1974183401 was caused by a
    RESOLVE_KAKE_N1 consequence surviving the matte at t032."""
    from throws import ThrowID
    t, s = _pair()
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki(), seed=0)
    # Stage representative pending consequences for both judoka,
    # covering every kind that can drive a throw-resolution event.
    m._consequence_queue.extend([
        _Consequence(due_tick=35, kind="RESOLVE_KAKE_N1", payload={
            "attacker_name": t.identity.name,
            "defender_name": s.identity.name,
            "throw_id": ThrowID.UCHI_MATA,
        }),
        _Consequence(due_tick=37, kind="RESOLVE_DRIVE_THROW", payload={
            "attacker_name": s.identity.name,
            "defender_name": t.identity.name,
            "throw_id": ThrowID.O_SOTO_GARI,
        }),
        _Consequence(due_tick=33, kind="FIRE_COMMIT_FROM_INTENT", payload={
            "attacker_name": t.identity.name,
            "defender_name": s.identity.name,
            "throw_id": ThrowID.HARAI_GOSHI,
            "offensive_desperation": False,
            "defensive_desperation": True,
            "gate_bypass_reason": None,
            "gate_bypass_kind": None,
            "commit_motivation": None,
        }),
        _Consequence(due_tick=33, kind="NEWAZA_TRANSITION_AFTER_STUFF", payload={
            "attacker_name": t.identity.name,
            "defender_name": s.identity.name,
            "throw_class": "SACRIFICE",
        }),
        # An unrelated consequence kind that should NOT be dropped.
        _Consequence(due_tick=40, kind="GRIP_INIT_RECOMPUTE", payload={
            "survivor_name": s.identity.name,
            "failed_attacker_name": t.identity.name,
        }),
    ])
    # Also seed an in-progress throw entry so we can verify it's cleared.
    from match import _ThrowInProgress
    m._throws_in_progress[t.identity.name] = _ThrowInProgress(
        attacker_name=t.identity.name, defender_name=s.identity.name,
        throw_id=ThrowID.UCHI_MATA, start_tick=30, compression_n=1,
        schedule={}, commit_actual=0.5, commit_execution_quality=0.5,
        execution_ticks=1, drive_vector=(0.0, 0.0),
    )
    m._handle_matte(tick=32)
    # Throw resolution consequences all dropped.
    surviving = {c.kind for c in m._consequence_queue}
    for dropped in (
        "RESOLVE_KAKE_N1", "RESOLVE_DRIVE_THROW",
        "FIRE_COMMIT_FROM_INTENT", "NEWAZA_TRANSITION_AFTER_STUFF",
    ):
        assert dropped not in surviving, (
            f"{dropped} should be dropped on matte (still in {surviving})"
        )
    # Unrelated consequence kinds survive.
    assert "GRIP_INIT_RECOMPUTE" in surviving
    # In-progress entry cleared.
    assert not m._throws_in_progress


# ===========================================================================
# Issue 3 — Defensive desperation threshold
# ===========================================================================
def test_haj222_playtest_pressure_no_longer_triggers_desperation() -> None:
    """HAJ-222 issue 3 — the exact pressure scores Sato (3.6) and
    Tanaka (4.4) carried at t024/t025 in seed 1974183401 no longer
    flip the desperation gate. Pre-fix ENTRY_THRESHOLD=3.0 fired on
    both; post-fix ENTRY_THRESHOLD=6.0 requires more sustained pressure."""
    tr_sato = DefensivePressureTracker()
    # Sato's tick-24 signals: 2 commits, 1 kuzushi, composure drop 0.10.
    tr_sato.record_opponent_commit(tick=10)
    tr_sato.record_opponent_commit(tick=15)
    tr_sato.record_kuzushi(tick=18)
    tr_sato.record_composure(tick=9, composure=10.0)
    tr_sato.record_composure(tick=24, composure=9.9)
    sato_score = tr_sato.pressure_score(tick=24)
    assert sato_score < ENTRY_THRESHOLD, (
        f"Sato's t024 pressure ({sato_score}) should not trip the new "
        f"entry threshold ({ENTRY_THRESHOLD})"
    )
    assert tr_sato.update(tick=24) is False

    tr_tanaka = DefensivePressureTracker()
    # Tanaka's tick-25 signals: 1 commit, 2 kuzushi, composure drop 0.50.
    tr_tanaka.record_opponent_commit(tick=12)
    tr_tanaka.record_kuzushi(tick=14)
    tr_tanaka.record_kuzushi(tick=20)
    tr_tanaka.record_composure(tick=10, composure=10.0)
    tr_tanaka.record_composure(tick=25, composure=9.5)
    tanaka_score = tr_tanaka.pressure_score(tick=25)
    assert tanaka_score < ENTRY_THRESHOLD, (
        f"Tanaka's t025 pressure ({tanaka_score}) should not trip the new "
        f"entry threshold ({ENTRY_THRESHOLD})"
    )
    assert tr_tanaka.update(tick=25) is False


def test_sustained_pressure_still_triggers_desperation() -> None:
    """The threshold raise is a calibration shift, not a removal — a
    judoka who's been chased across the mat (5+ commits and multiple
    kuzushi events in the window) still enters defensive desperation."""
    tr = DefensivePressureTracker()
    for t in range(20, 30):  # 10 ticks of one-sided attack
        if t % 2 == 0:
            tr.record_opponent_commit(tick=t)
        if t % 3 == 0:
            tr.record_kuzushi(tick=t)
    tr.record_composure(tick=20, composure=10.0)
    tr.record_composure(tick=34, composure=9.0)
    score = tr.pressure_score(tick=34)
    assert score >= ENTRY_THRESHOLD, (
        f"sustained pressure should still trip desperation: score={score}"
    )
    assert tr.update(tick=34) is True


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
