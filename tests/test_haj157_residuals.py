# tests/test_haj157_residuals.py
# HAJ-157 — HAJ-148 enforcement residuals: sub-event spread for N=1
# throws, counter staging through the intent layer, and dedupe of the
# ne-waza door when both fighters stuff on the same tick.
#
# Closes the residuals flagged out-of-scope at HAJ-154 commit time:
#   V1/V5 — N=1 throws collapse all four sub-events onto the THROW_ENTRY
#           tick. Fix: kuzushi → tsukuri → kake → outcome occupy 4
#           consecutive ticks.
#   V2    — counter throws bypass the staging layer (call
#           _resolve_commit_throw directly), firing on the same tick as
#           their trigger. Fix: route through _stage_commit_intent so the
#           counter's intent fires on tick T and the counter commit
#           fires on tick T+1.
#   V3    — when both fighters stuff on the same tick, the dyad's
#           NEWAZA_TRANSITION_AFTER_STUFF consequence is enqueued twice
#           and the door fires twice. Fix: dedupe at the STUFFED branch.

from __future__ import annotations
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from enums import (
    BeltRank, BodyPart, GripTypeV2, GripDepth, GripMode, GripTarget,
    Position,
)
from body_state import place_judoka
from grip_graph import GripGraph, GripEdge
from throws import ThrowID
from match import Match
from referee import build_suzuki
from skill_compression import SubEvent, sub_event_schedule
import main as main_module
import match as match_module


# ---------------------------------------------------------------------------
# FIXTURES
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


def _elite_match(seed: int = 0) -> tuple[object, object, Match]:
    """Match with both fighters at BLACK_5 (N=1) and grips already
    seated, ready for a direct commit-resolution call."""
    random.seed(seed)
    t, s = _pair()
    t.identity.belt_rank = BeltRank.BLACK_5
    s.identity.belt_rank = BeltRank.BLACK_5
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki(), seed=seed)
    m.position = Position.GRIPPING
    _seat_deep_grips(m.grip_graph, t, s)
    _seat_deep_grips(m.grip_graph, s, t)
    return t, s, m


# ===========================================================================
# AC#1 — N=1 throw distributes across 4 distinct ticks
# ===========================================================================
def test_n1_throw_kuzushi_tsukuri_kake_outcome_on_four_consecutive_ticks() -> None:
    """The four cause-effect beats of an N=1 throw — kuzushi
    (KUZUSHI_ACHIEVED), tsukuri, kake (KAKE_COMMIT), and the outcome —
    fire on four consecutive ticks. None of them co-fire on the same
    tick. Pre-HAJ-157 all four phases collapsed onto the THROW_ENTRY
    tick and the outcome landed on T+1; post-fix the engine event log
    shows the chain spread across T..T+3."""
    t, s, m = _elite_match(seed=1)
    real = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: ("FAILED", -2.0)
    collected: list = []
    try:
        T = 5
        collected.extend(m._resolve_commit_throw(t, s, ThrowID.UCHI_MATA, tick=T))
        collected.extend(m._advance_throws_in_progress(tick=T + 1))
        collected.extend(m._advance_throws_in_progress(tick=T + 2))
        m._resolve_consequences(tick=T + 3, events=collected)
    finally:
        match_module.resolve_throw = real

    def tick_of(event_type: str) -> int:
        return next(e.tick for e in collected if e.event_type == event_type)

    kuzushi_tick = tick_of("SUB_KUZUSHI_ACHIEVED")
    tsukuri_tick = tick_of("SUB_TSUKURI")
    kake_tick    = tick_of("SUB_KAKE_COMMIT")
    outcome_tick = tick_of("FAILED")

    # All four on distinct ticks — no co-firing.
    distinct = {kuzushi_tick, tsukuri_tick, kake_tick, outcome_tick}
    assert len(distinct) == 4, (
        f"expected 4 distinct ticks; got "
        f"kuzushi={kuzushi_tick}, tsukuri={tsukuri_tick}, "
        f"kake={kake_tick}, outcome={outcome_tick}"
    )

    # Chain order: kuzushi → tsukuri → kake → outcome, consecutive.
    assert kuzushi_tick == T
    assert tsukuri_tick == T + 1
    assert kake_tick    == T + 2
    assert outcome_tick == T + 3


def test_n1_reach_kuzushi_pairs_with_kuzushi_phase() -> None:
    """REACH_KUZUSHI semantically belongs to the kuzushi phase for the
    N=1 spread (the pre-commit IntentSignal already covers the
    setup-class signature one tick earlier on the staging layer). The
    schedule pairs RK + KA on offset 0; no separate RK-only tick."""
    schedule = sub_event_schedule(1)
    assert SubEvent.REACH_KUZUSHI in schedule[0]
    assert SubEvent.KUZUSHI_ACHIEVED in schedule[0]
    # Tsukuri / kake are on subsequent offsets — not bundled with RK.
    assert SubEvent.TSUKURI not in schedule[0]
    assert SubEvent.KAKE_COMMIT not in schedule[0]


# ===========================================================================
# AC#2 — higher compression still folds phases (no regression on N>=2)
# ===========================================================================
def test_higher_compression_schedules_unchanged() -> None:
    """N=2..N=8 schedules are unchanged from the existing
    compression_n_for layout. Only N=1 gains a spread layout."""
    # N=2: REACH on tick 0; KA + TS + KC together on tick 1.
    s2 = sub_event_schedule(2)
    assert s2[0] == [SubEvent.REACH_KUZUSHI]
    assert SubEvent.KUZUSHI_ACHIEVED in s2[1]
    assert SubEvent.TSUKURI in s2[1]
    assert SubEvent.KAKE_COMMIT in s2[1]
    # N=3: REACH; KA + TS; KC.
    s3 = sub_event_schedule(3)
    assert s3[0] == [SubEvent.REACH_KUZUSHI]
    assert SubEvent.KUZUSHI_ACHIEVED in s3[1] and SubEvent.TSUKURI in s3[1]
    assert s3[2] == [SubEvent.KAKE_COMMIT]
    # N=4: each event on its own tick.
    s4 = sub_event_schedule(4)
    assert s4[0] == [SubEvent.REACH_KUZUSHI]
    assert s4[1] == [SubEvent.KUZUSHI_ACHIEVED]
    assert s4[2] == [SubEvent.TSUKURI]
    assert s4[3] == [SubEvent.KAKE_COMMIT]


def test_n2_throw_resolves_on_kake_tick_inline() -> None:
    """N>=2 throws resolve their outcome on the KAKE_COMMIT tick — the
    HAJ-157 V1/V5 deferral applies only to N=1. Confirms no regression
    on the multi-tick path."""
    random.seed(7)
    t, s = _pair()
    # Tanaka BLACK_1 + non-tokui UCHI_MATA → N=2.
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())
    m.position = Position.GRIPPING
    _seat_deep_grips(m.grip_graph, t, s)
    real = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: ("FAILED", -2.0)
    try:
        m._resolve_commit_throw(t, s, ThrowID.UCHI_MATA, tick=10)
        # KAKE on tick 11 (offset 1); outcome fires inline that same tick.
        kake_events = m._advance_throws_in_progress(tick=11)
    finally:
        match_module.resolve_throw = real
    kinds = {e.event_type for e in kake_events}
    assert "SUB_KAKE_COMMIT" in kinds
    assert "FAILED" in kinds, "N>=2 outcome co-fires with KAKE_COMMIT"


# ===========================================================================
# AC#3 + AC#4 — counter throws fire on T+1 of the trigger; counter
# intent precedes counter commit by 1 tick
# ===========================================================================
def test_counter_throw_commit_fires_one_tick_after_trigger() -> None:
    """A counter triggered on tick T fires its THROW_ENTRY on tick T+1
    via the FIRE_COMMIT_FROM_INTENT consequence. Pre-HAJ-157 the
    counter committed synchronously on T (the same tick as the action
    being countered), bunching cause and effect."""
    random.seed(0)
    t, s = _pair()
    # Sharpen Sato so the counter resource gates pass.
    s.capability.fight_iq = 10
    s.state.composure_current = float(s.capability.composure_ceiling)
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())
    m.position = Position.GRIPPING
    _seat_deep_grips(m.grip_graph, t, s)
    # Tanaka starts a multi-tick UCHI_MATA so the counter check has a tip.
    m._resolve_commit_throw(t, s, ThrowID.UCHI_MATA, tick=1)

    class _RigRng:
        """RNG that always passes perception-noise + counter-fire rolls."""
        def random(self):
            return 0.0
        def choice(self, seq):
            return seq[0]

    trigger_tick = 2
    events = m._check_counter_opportunities(tick=trigger_tick, rng=_RigRng())
    counter_marker = next(e for e in events if e.event_type == "COUNTER_COMMIT")
    assert counter_marker.tick == trigger_tick
    # No THROW_ENTRY for Sato on the trigger tick.
    sato_entries_on_trigger = [
        e for e in events
        if e.event_type == "THROW_ENTRY"
        and isinstance(e.description, str)
        and "Sato" in e.description
    ]
    assert not sato_entries_on_trigger, (
        "Sato's counter THROW_ENTRY must not co-fire with COUNTER_COMMIT"
    )

    # On tick+1, FIRE_COMMIT_FROM_INTENT fires Sato's counter THROW_ENTRY.
    follow: list = []
    m._resolve_consequences(tick=trigger_tick + 1, events=follow)
    sato_entries = [
        e for e in follow
        if e.event_type == "THROW_ENTRY"
        and isinstance(e.description, str)
        and "Sato" in e.description
    ]
    assert sato_entries, (
        "Sato's counter THROW_ENTRY must fire on tick+1 from "
        "the FIRE_COMMIT_FROM_INTENT consequence"
    )
    assert sato_entries[0].tick == trigger_tick + 1


def test_counter_intent_precedes_counter_commit_by_one_tick() -> None:
    """Per HAJ-149's intent contract applied to the counter path:
    every counter THROW_ENTRY must be preceded by a counter
    INTENT_SIGNAL on the prior tick. Pre-HAJ-157 the counter went
    straight to _resolve_commit_throw and bypassed the staging layer
    entirely — no pre-commit intent signal fired."""
    random.seed(0)
    t, s = _pair()
    s.capability.fight_iq = 10
    s.state.composure_current = float(s.capability.composure_ceiling)
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())
    m.position = Position.GRIPPING
    _seat_deep_grips(m.grip_graph, t, s)
    m._resolve_commit_throw(t, s, ThrowID.UCHI_MATA, tick=1)

    class _RigRng:
        def random(self):
            return 0.0
        def choice(self, seq):
            return seq[0]

    T = 2
    trigger = m._check_counter_opportunities(tick=T, rng=_RigRng())
    follow: list = []
    m._resolve_consequences(tick=T + 1, events=follow)

    intents = [
        e for e in trigger
        if e.event_type == "INTENT_SIGNAL"
        and e.data.get("fighter") == s.identity.name
    ]
    assert intents, "counter must emit a pre-commit IntentSignal"
    intent_tick = intents[0].tick
    counter_entry = next(
        e for e in follow
        if e.event_type == "THROW_ENTRY"
        and isinstance(e.description, str)
        and "Sato" in e.description
    )
    assert counter_entry.tick - intent_tick == 1


# ===========================================================================
# AC#5 — no duplicate ne-waza door for simultaneous stuffs
# ===========================================================================
def test_simultaneous_stuffs_dedupe_to_single_newaza_door() -> None:
    """When both fighters stuff on the same tick, only one
    NEWAZA_TRANSITION_AFTER_STUFF consequence is queued for the dyad.
    Pre-HAJ-157 each fighter's _apply_throw_result enqueued its own
    consequence, so the door fired twice. HAJ-155 — only sacrifice
    throws open the door, so this test uses Sumi-gaeshi to exercise
    the dedupe path."""
    t, s, m = _elite_match(seed=42)
    real = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: ("STUFFED", -2.0)
    try:
        T = 5
        # Both fighters commit sacrifice throws on the same tick. B-3a —
        # Sumi-gaeshi is now a 2-tick worked throw, so both stuffs land on
        # T+4 (was T+3) from the consequence queue.
        m._resolve_commit_throw(t, s, ThrowID.SUMI_GAESHI, tick=T)
        m._resolve_commit_throw(s, t, ThrowID.SUMI_GAESHI, tick=T)
        # Walk the schedule (offsets 1, 2, 3), then resolve on T+4.
        m._advance_throws_in_progress(tick=T + 1)
        m._advance_throws_in_progress(tick=T + 2)
        m._advance_throws_in_progress(tick=T + 3)
        outcomes: list = []
        m._resolve_consequences(tick=T + 4, events=outcomes)
    finally:
        match_module.resolve_throw = real

    # Two STUFFED events on T+3 — one per fighter.
    stuffs = [e for e in outcomes if e.event_type == "STUFFED"]
    assert len(stuffs) == 2, (
        f"expected 2 STUFFED events on simultaneous stuffs; got {len(stuffs)}"
    )
    # Exactly ONE NEWAZA_TRANSITION_AFTER_STUFF consequence queued for T+4.
    door_consequences = [
        c for c in m._consequence_queue
        if c.kind == "NEWAZA_TRANSITION_AFTER_STUFF"
    ]
    assert len(door_consequences) == 1, (
        f"expected exactly 1 ne-waza door consequence; got "
        f"{len(door_consequences)}"
    )
    assert door_consequences[0].due_tick == T + 5


def test_single_stuff_still_queues_exactly_one_newaza_door() -> None:
    """Sanity check: one fighter stuffing alone still queues exactly
    one ne-waza door consequence. The dedupe is conservative — it only
    fires when a duplicate is already queued for the same tick. HAJ-155
    — uses Sumi-gaeshi (sacrifice) so the door actually fires."""
    t, s, m = _elite_match(seed=11)
    real = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: ("STUFFED", -2.0)
    try:
        T = 5
        # B-3a — Sumi-gaeshi is now a 2-tick worked throw; the stuff lands on
        # T+4 (was T+3) and the ne-waza door is queued for T+5.
        m._resolve_commit_throw(t, s, ThrowID.SUMI_GAESHI, tick=T)
        m._advance_throws_in_progress(tick=T + 1)
        m._advance_throws_in_progress(tick=T + 2)
        m._advance_throws_in_progress(tick=T + 3)
        outcomes: list = []
        m._resolve_consequences(tick=T + 4, events=outcomes)
    finally:
        match_module.resolve_throw = real

    door_consequences = [
        c for c in m._consequence_queue
        if c.kind == "NEWAZA_TRANSITION_AFTER_STUFF"
    ]
    assert len(door_consequences) == 1


# ===========================================================================
# AC#6 — t007 reproduction continues to pass under HAJ-148 contract
# ===========================================================================
def test_t007_reproduction_chain_still_distributes() -> None:
    """The t007 case (paired commits → stuff → ne-waza door) continues
    to span multiple ticks under the new HAJ-157 spread. AC#6 — no
    regression on the existing HAJ-154 reproduction."""
    t, s, m = _elite_match(seed=7)
    real = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: ("STUFFED", -2.0)
    collected: list = []
    try:
        T = 5
        collected.extend(m._resolve_commit_throw(t, s, ThrowID.O_UCHI_GARI, tick=T))
        collected.extend(m._resolve_commit_throw(s, t, ThrowID.O_UCHI_GARI, tick=T))
        collected.extend(m._advance_throws_in_progress(tick=T + 1))
        collected.extend(m._advance_throws_in_progress(tick=T + 2))
        m._resolve_consequences(tick=T + 3, events=collected)
        m._resolve_consequences(tick=T + 4, events=collected)
    finally:
        match_module.resolve_throw = real
    ticks_seen = sorted({e.tick for e in collected})
    assert len(ticks_seen) >= 3, (
        f"t007 chain should span >= 3 ticks; got {ticks_seen}"
    )


# ===========================================================================
# AC#7 — HAJ-148 / HAJ-154 top-level contracts continue to hold
# ===========================================================================
def test_throw_entry_remains_prose_silent_after_haj157() -> None:
    """The HAJ-148 AC3 contract — THROW_ENTRY events are flagged
    prose_silent — survives the HAJ-157 sub-event spread."""
    t, s, m = _elite_match(seed=2)
    real = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: ("FAILED", -2.0)
    try:
        events = m._resolve_commit_throw(t, s, ThrowID.UCHI_MATA, tick=5)
        entry = next(e for e in events if e.event_type == "THROW_ENTRY")
        assert entry.data.get("prose_silent") is True
    finally:
        match_module.resolve_throw = real


def test_outcome_lands_strictly_after_commit_for_n1() -> None:
    """HAJ-148 contract — the outcome (LANDED / STUFFED / FAILED) of
    an N=1 commit lands on a strictly later tick than the THROW_ENTRY.
    HAJ-157 stretches the gap from 1 tick to 3 ticks; the contract
    that they don't share a tick is preserved."""
    t, s, m = _elite_match(seed=3)
    real = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: ("FAILED", -2.0)
    collected: list = []
    try:
        T = 5
        collected.extend(m._resolve_commit_throw(t, s, ThrowID.UCHI_MATA, tick=T))
        collected.extend(m._advance_throws_in_progress(tick=T + 1))
        collected.extend(m._advance_throws_in_progress(tick=T + 2))
        m._resolve_consequences(tick=T + 3, events=collected)
    finally:
        match_module.resolve_throw = real
    entry = next(e for e in collected if e.event_type == "THROW_ENTRY")
    failed = next(e for e in collected if e.event_type == "FAILED")
    assert failed.tick > entry.tick


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
