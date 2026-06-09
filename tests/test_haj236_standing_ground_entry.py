# tests/test_haj236_standing_ground_entry.py
# HAJ-236 — broaden ne-waza entry beyond stuffed sacrifice throws.
#
# Background: HAJ-155 made a stuffed STANDING throw reset cleanly to
# standing. The post-223 match review (seed 1081968535) showed the
# consequence — across a full match of standing throws, ne-waza was almost
# never *entered*. This ticket adds a non-sacrifice entry path: a stuffed
# standing throw now probabilistically spills into a ground scramble
# (stuffed aggressor underneath, defender on top) instead of always
# resetting. Rate is governed by ground_continuation.make_ground_
# continuation_decision; geometry reuses the HAJ-155 aggressor-on-bottom
# plumbing.
#
# AC coverage:
#   AC#1 — the decision module exists and is rate-bounded (floor/ceil)
#   AC#2 — a CONTINUE roll opens the ne-waza door on a STANDING stuff
#   AC#3 — geometry: stuffed aggressor on bottom, defender on top, GUARD_TOP
#   AC#4 — the transition is tagged source=STANDING_SCRAMBLE
#   AC#5 — a RESET roll still resets (HAJ-155 behavior preserved)
#   AC#6 — reaping throws out-rate clean hip throws (throw-geometry signal)
#   AC#7 — sacrifice path is unchanged (no ground-continuation roll)

from __future__ import annotations
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from enums import BeltRank, BodyPart, GripDepth, GripMode, GripTarget, GripTypeV2
from enums import Position, SubLoopState
from grip_graph import GripEdge
from match import Match
from referee import build_suzuki
from throws import THROW_DEFS, ThrowID
from ground_continuation import (
    GroundContinuation, GroundContinuationResult,
    make_ground_continuation_decision,
    CONTINUE_FLOOR, CONTINUE_CEIL,
)
import main as main_module
import match as match_module
from body_state import place_judoka


# ---------------------------------------------------------------------------
# FIXTURES (mirror the HAJ-155 suite so the two read consistently)
# ---------------------------------------------------------------------------
def _pair():
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    return t, s


def _seat_deep_grips(graph, attacker, defender):
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


def _elite_match(seed: int = 0):
    random.seed(seed)
    t, s = _pair()
    t.identity.belt_rank = BeltRank.BLACK_5
    s.identity.belt_rank = BeltRank.BLACK_5
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki(), seed=seed)
    m.position = Position.GRIPPING
    _seat_deep_grips(m.grip_graph, t, s)
    _seat_deep_grips(m.grip_graph, s, t)
    return t, s, m


def _force_continue(m) -> None:
    m._roll_ground_continuation = lambda *a, **k: GroundContinuationResult(
        decision=GroundContinuation.CONTINUE_TO_GROUND,
        probability=1.0,
        factors={},
    )


def _force_reset(m) -> None:
    m._roll_ground_continuation = lambda *a, **k: GroundContinuationResult(
        decision=GroundContinuation.RESET_TO_STANDING,
        probability=0.0,
        factors={},
    )


def _drive_outcome(m, t, s, throw_id, outcome, commit_tick=10):
    """Drive an N=1 throw to a forced outcome through the HAJ-148 /
    HAJ-157 N+3 chain (copied from the HAJ-155 suite)."""
    real = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: (
        outcome, -3.0 if outcome != "WAZA_ARI" else 4.5
    )
    collected: list = []
    try:
        collected.extend(m._resolve_commit_throw(t, s, throw_id, tick=commit_tick))
        collected.extend(m._advance_throws_in_progress(tick=commit_tick + 1))
        collected.extend(m._advance_throws_in_progress(tick=commit_tick + 2))
        m._resolve_consequences(tick=commit_tick + 3, events=collected)
        m._resolve_consequences(tick=commit_tick + 4, events=collected)
    finally:
        match_module.resolve_throw = real
    return collected


# ===========================================================================
# AC#1 — the decision module is rate-bounded
# ===========================================================================
def test_probability_is_clamped_to_floor_and_ceil() -> None:
    """Even a maximally scramble-prone / maximally reset-prone setup is
    bounded by the module's floor and ceiling so ne-waza can never be a
    hard never or a hard always from this path."""
    t, s = _pair()
    rng = random.Random(0)
    # A high chase_advantage throw between two fighters should still land
    # under the ceiling.
    hi = make_ground_continuation_decision(
        t, s, throw_id=ThrowID.UCHI_MATA, chase_advantage=1.0, rng=rng,
    )
    assert hi.probability <= CONTINUE_CEIL + 1e-9
    # A zero-advantage throw should still land at or above the floor.
    lo = make_ground_continuation_decision(
        t, s, throw_id=ThrowID.SEOI_NAGE, chase_advantage=0.0, rng=rng,
    )
    assert lo.probability >= CONTINUE_FLOOR - 1e-9


def test_decision_is_deterministic_for_a_given_rng() -> None:
    """Same fighters + same seeded RNG → same decision (reproducibility
    is the contract the match seed relies on)."""
    t, s = _pair()
    a = make_ground_continuation_decision(
        t, s, throw_id=ThrowID.O_SOTO_GARI, chase_advantage=0.75,
        rng=random.Random(42),
    )
    b = make_ground_continuation_decision(
        t, s, throw_id=ThrowID.O_SOTO_GARI, chase_advantage=0.75,
        rng=random.Random(42),
    )
    assert a.decision == b.decision
    assert a.probability == b.probability


# ===========================================================================
# AC#2 — a CONTINUE roll opens the ne-waza door on a STANDING stuff
# ===========================================================================
def test_standing_stuff_continue_opens_ne_waza_door() -> None:
    t, s, m = _elite_match(seed=3)
    _force_continue(m)
    events = _drive_outcome(m, t, s, ThrowID.O_SOTO_GARI, "STUFFED")
    transitioned = (
        m.sub_loop_state == SubLoopState.NE_WAZA
        or any(c.kind == "NEWAZA_TRANSITION_AFTER_STUFF"
               for c in m._consequence_queue)
        or any(e.event_type == "NEWAZA_TRANSITION" for e in events)
    )
    assert transitioned, (
        "a stuffed STANDING throw that rolled CONTINUE must open the "
        "ne-waza door"
    )


def test_standing_stuff_continue_prose_cites_scramble() -> None:
    t, s, m = _elite_match(seed=4)
    _force_continue(m)
    events = _drive_outcome(m, t, s, ThrowID.O_SOTO_GARI, "STUFFED")
    stuffs = [e for e in events if e.event_type == "STUFFED"]
    assert stuffs
    desc = stuffs[0].description.lower()
    assert "ground" in desc or "scramble" in desc or "mat" in desc
    # Still classified STANDING — the throw class didn't change; only the
    # routing did.
    assert stuffs[0].data.get("throw_class") == "STANDING"


def test_ground_continuation_decision_event_emitted() -> None:
    """A prose-silent GROUND_CONTINUATION event carries the factor
    breakdown for the engineering stream."""
    t, s, m = _elite_match(seed=5)
    _force_continue(m)
    events = _drive_outcome(m, t, s, ThrowID.O_SOTO_GARI, "STUFFED")
    gc = [e for e in events if e.event_type == "GROUND_CONTINUATION"]
    assert gc, "expected a GROUND_CONTINUATION decision event"
    assert gc[0].data.get("decision") == "CONTINUE_TO_GROUND"
    assert gc[0].data.get("prose_silent") is True


# ===========================================================================
# AC#3 — geometry: stuffed aggressor on bottom, defender on top
# ===========================================================================
def test_standing_scramble_puts_aggressor_on_bottom() -> None:
    t, s, m = _elite_match(seed=6)
    _force_continue(m)
    # Force the resolver to accept the ground commit so the transition
    # lands deterministically (mirrors the HAJ-155 geometry test).
    m.ne_waza_resolver.attempt_ground_commit = lambda a, d, q: ["forced"]
    _drive_outcome(m, t, s, ThrowID.O_SOTO_GARI, "STUFFED")
    if m.sub_loop_state != SubLoopState.NE_WAZA:
        m._resolve_consequences(tick=15, events=[])
    assert m.sub_loop_state == SubLoopState.NE_WAZA
    # The stuffed aggressor (Tanaka) is underneath; the defender (Sato)
    # is the top fighter.
    assert m.ne_waza_top_id == s.identity.name
    assert m.position == Position.GUARD_TOP


def test_standing_scramble_transition_tagged_source() -> None:
    t, s, m = _elite_match(seed=8)
    _force_continue(m)
    m.ne_waza_resolver.attempt_ground_commit = lambda a, d, q: ["forced"]
    events = _drive_outcome(m, t, s, ThrowID.O_SOTO_GARI, "STUFFED")
    transitions = [e for e in events if e.event_type == "NEWAZA_TRANSITION"]
    if not transitions:
        extra: list = []
        m._resolve_consequences(tick=15, events=extra)
        transitions = [e for e in extra if e.event_type == "NEWAZA_TRANSITION"]
    assert transitions
    assert transitions[0].data.get("source") == "STANDING_SCRAMBLE"


# ===========================================================================
# AC#5 — a RESET roll preserves HAJ-155 reset behavior
# ===========================================================================
def test_standing_stuff_reset_still_resets() -> None:
    t, s, m = _elite_match(seed=7)
    _force_reset(m)
    events = _drive_outcome(m, t, s, ThrowID.O_SOTO_GARI, "STUFFED")
    assert not [c for c in m._consequence_queue
                if c.kind == "NEWAZA_TRANSITION_AFTER_STUFF"]
    assert m.sub_loop_state != SubLoopState.NE_WAZA
    stuffs = [e for e in events if e.event_type == "STUFFED"]
    assert stuffs and "stand" in stuffs[0].description.lower()


# ===========================================================================
# AC#6 — throw-geometry signal: reaping throws out-rate clean hip throws
# ===========================================================================
def test_reaping_throws_continue_more_often_than_clean_hip_throws() -> None:
    """Over many seeds, a reaping throw (high chase_advantage) spills to
    the ground more often than a clean shoulder throw (neutral
    advantage). This is the 'by throw' lever the ticket asks for."""
    t, s = _pair()
    osoto_adv = THROW_DEFS[ThrowID.O_SOTO_GARI].post_score_chase_advantage
    seoi_adv = THROW_DEFS[ThrowID.SEOI_NAGE].post_score_chase_advantage
    assert osoto_adv > seoi_adv  # sanity: the data encodes the signal

    def rate(advantage: float) -> float:
        cont = 0
        n = 400
        for i in range(n):
            res = make_ground_continuation_decision(
                t, s, throw_id=ThrowID.O_SOTO_GARI, chase_advantage=advantage,
                rng=random.Random(i),
            )
            if res.decision == GroundContinuation.CONTINUE_TO_GROUND:
                cont += 1
        return cont / n

    assert rate(osoto_adv) > rate(seoi_adv), (
        "reaping throws should spill to the ground more often than clean "
        "hip throws"
    )


def test_continuation_rate_is_realistic_not_dominant() -> None:
    """Governance check (design Q4): even the scramble-prone reaping
    throw continues to the ground a minority of the time — most stuffs
    still reset. Keeps ne-waza a flavor, not the norm."""
    t, s = _pair()
    osoto_adv = THROW_DEFS[ThrowID.O_SOTO_GARI].post_score_chase_advantage
    cont = 0
    n = 600
    for i in range(n):
        res = make_ground_continuation_decision(
            t, s, throw_id=ThrowID.O_SOTO_GARI, chase_advantage=osoto_adv,
            rng=random.Random(10_000 + i),
        )
        if res.decision == GroundContinuation.CONTINUE_TO_GROUND:
            cont += 1
    r = cont / n
    assert 0.05 < r < 0.5, (
        f"reaping-throw continuation rate {r:.2f} outside the realistic "
        f"band (should be a minority of stuffs)"
    )


# ===========================================================================
# AC#7 — sacrifice path is unchanged (no ground-continuation roll)
# ===========================================================================
def test_sacrifice_stuff_does_not_consult_ground_continuation() -> None:
    """A sacrifice throw always opens the door via the HAJ-155 geometry;
    it must NOT call the HAJ-236 roll (forcing the roll to RESET must not
    suppress the sacrifice door)."""
    t, s, m = _elite_match(seed=2)
    _force_reset(m)  # would suppress a standing stuff — but not sacrifice
    _drive_outcome(m, t, s, ThrowID.SUMI_GAESHI, "STUFFED")
    opened = (
        m.sub_loop_state == SubLoopState.NE_WAZA
        or any(c.kind == "NEWAZA_TRANSITION_AFTER_STUFF"
               for c in m._consequence_queue)
    )
    assert opened, "sacrifice stuff must open the door regardless of the roll"


# ===========================================================================
# Entry point
# ===========================================================================
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
