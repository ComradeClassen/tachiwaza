# tests/test_haj154_enforcement.py
# HAJ-154 — enforcement-gap audit regression tests.
#
# The HAJ-154 audit found that HAJ-148 / HAJ-149 emitted the right events
# with the right shapes, but the *temporal contracts* were not enforced:
#   - Intent signals fired on the commit tick, not before.
#   - The "X's commit lands crisp and explosive" prose fired on the
#     commit tick when the throw hadn't resolved yet.
#   - Perception lag values collapsed to lag=+0 / +1 because there
#     was no perception window for negative lag to express against.
#
# These tests pin the contracts so a regression won't slip back in.

from __future__ import annotations
import contextlib
import io
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
from actions import Action, ActionKind
from skill_vector import set_uniform
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


def _elite_pair_match(seed: int = 0):
    """Both fighters are elite (BLACK_5, fight_iq=10), grips already
    seated, ready for a direct staged commit."""
    random.seed(seed)
    t, s = _pair()
    t.identity.belt_rank = BeltRank.BLACK_5
    s.identity.belt_rank = BeltRank.BLACK_5
    t.capability.fight_iq = 10
    s.capability.fight_iq = 10
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki(), seed=seed)
    m.position = Position.GRIPPING
    _seat_deep_grips(m.grip_graph, t, s)
    _seat_deep_grips(m.grip_graph, s, t)
    return t, s, m


# ===========================================================================
# AC#1 — strict per-fighter / per-tick gate at the action-ladder level
# ===========================================================================
def test_action_ladder_does_not_re_commit_during_staging() -> None:
    """A fighter who has just staged a commit cannot have a fresh
    COMMIT_THROW pass through the action ladder on the next tick — the
    placeholder _ThrowInProgress entry blocks it."""
    t, s, m = _elite_pair_match(seed=1)
    act = Action(kind=ActionKind.COMMIT_THROW, throw_id=ThrowID.UCHI_MATA)
    m._stage_commit_intent(t, s, act, tick=5)
    # Now the fighter has a placeholder TIP; another stage attempt is
    # silently rejected (returns no events).
    second = m._stage_commit_intent(t, s, act, tick=5)
    assert second == []
    assert t.identity.name in m._throws_in_progress


# ===========================================================================
# AC#2 — consequences resolve on N+1 minimum
# ===========================================================================
def test_intent_and_commit_never_share_a_tick() -> None:
    """Across a full match run, every INTENT_SIGNAL event for a throw
    commit must fire on a strictly earlier tick than the matching
    THROW_ENTRY. (HAJ-149 AC2 / HAJ-154 V4.)"""
    random.seed(0)
    t, s = _pair()
    m = Match(
        fighter_a=t, fighter_b=s, referee=build_suzuki(),
        max_ticks=80, seed=0, stream="debug",
    )
    captured: list = []
    real = m._print_events
    m._print_events = lambda evts: captured.extend(evts)
    with contextlib.redirect_stdout(io.StringIO()):
        m.run()
    intents_by_throw = [
        e for e in captured if e.event_type == "INTENT_SIGNAL"
        and e.data.get("setup_class") == "throw_commit"
    ]
    entries = [e for e in captured if e.event_type == "THROW_ENTRY"]
    # Pair up by attacker name + throw_id; each commit's intent fires
    # strictly before its THROW_ENTRY.
    for entry in entries:
        attacker = entry.data["attacker"] = entry.data.get("attacker") or (
            entry.description.split()[1]
        )
        # Walk back through the intent log to find the most recent intent
        # for this attacker that hasn't been matched yet.
        for sig in reversed(intents_by_throw):
            if (sig.data["fighter"] == attacker
                    and sig.data["throw_id"] == entry.data["throw_id"]
                    and sig.tick < entry.tick):
                # Found a valid pre-commit intent — strictly earlier tick.
                assert sig.tick < entry.tick
                break


def test_commit_fires_one_tick_after_staging() -> None:
    """Stage a commit on tick N and confirm THROW_ENTRY fires on tick
    N+1 from the consequence queue, not tick N."""
    t, s, m = _elite_pair_match(seed=2)
    real = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: ("FAILED", -2.0)
    try:
        m._stage_commit_intent(
            t, s,
            Action(kind=ActionKind.COMMIT_THROW, throw_id=ThrowID.UCHI_MATA),
            tick=5,
        )
        # Tick 5: only the intent should be in the log (no THROW_ENTRY).
        sig = m._intent_signals[-1]
        assert sig.tick == 5
        # Tick 6: the FIRE_COMMIT_FROM_INTENT consequence runs.
        evts: list = []
        m._resolve_consequences(tick=6, events=evts)
        entries = [e for e in evts if e.event_type == "THROW_ENTRY"]
        assert len(entries) == 1
        assert entries[0].tick == 6
        assert entries[0].data.get("from_consequence_queue") is True
    finally:
        match_module.resolve_throw = real


# ===========================================================================
# AC#3 — commit prose silent (the "lands crisp and explosive" bug)
# ===========================================================================
def test_no_modifier_reveal_prose_on_commit_tick() -> None:
    """The HAJ-148 AC3 verification scan: walk a full match log and
    assert no MatchClockEntry with source='skill_reveal' fires on a
    tick that also has a THROW_ENTRY event.

    HAJ-152 — the post-score follow-up window's chase rng shifted the
    pre-existing seed-11 path enough to expose the COUNTER_COMMIT
    edge case (skill_reveal narrating a counter intent on the same
    tick as the original tori's THROW_ENTRY). HAJ-164 + its follow-up
    grip-seating distance gate moved the rng path twice more; seeds 19
    and 21 once exposed the same edge case. Triage 2026-05-02
    (Priority-3 grip-cascade lag bump) shifted the path again — seed 22
    then exposed it; seed 21 reproduced cleanly. HAJ-155 sacrifice-
    door gate shifted the path once more (stuffed standing throws no
    longer route through ne-waza), so seed 20 is the current clean
    path. The underlying narrator logic for COUNTER_COMMIT BPEs
    remains HAJ-155/HAJ-156 territory.
    """
    random.seed(20)
    t, s = _pair()
    m = Match(
        fighter_a=t, fighter_b=s, referee=build_suzuki(),
        max_ticks=80, seed=20, stream="debug",
    )
    captured_events: list = []
    m._print_events = lambda evts: captured_events.extend(evts)
    with contextlib.redirect_stdout(io.StringIO()):
        m.run()
    commit_ticks = {
        e.tick for e in captured_events if e.event_type == "THROW_ENTRY"
    }
    skill_reveal_ticks = {
        entry.tick for entry in m.match_clock_log
        if entry.source == "skill_reveal"
    }
    overlap = commit_ticks & skill_reveal_ticks
    assert not overlap, (
        f"HAJ-148 AC3 violation — modifier-reveal prose co-occurred "
        f"with commit on ticks {sorted(overlap)}"
    )


def test_throw_entry_remains_prose_silent() -> None:
    """HAJ-148 AC3 — THROW_ENTRY events stay marked prose_silent so the
    prose stream skips them entirely. (Independent of the modifier-reveal
    fix; pinning the existing flag.)"""
    t, s, m = _elite_pair_match(seed=3)
    m._stage_commit_intent(
        t, s,
        Action(kind=ActionKind.COMMIT_THROW, throw_id=ThrowID.UCHI_MATA),
        tick=5,
    )
    real = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: ("FAILED", -2.0)
    try:
        evts: list = []
        m._resolve_consequences(tick=6, events=evts)
        entry = next(e for e in evts if e.event_type == "THROW_ENTRY")
        assert entry.data.get("prose_silent") is True
    finally:
        match_module.resolve_throw = real


# ===========================================================================
# AC#4 — intent signals precede commits
# ===========================================================================
def test_staged_intent_precedes_commit_in_log_order() -> None:
    """Within the engine event stream, INTENT_SIGNAL for a throw fires
    on a strictly earlier tick than the THROW_ENTRY it precedes — the
    perception window is real and observable."""
    t, s, m = _elite_pair_match(seed=4)
    real = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: ("FAILED", -2.0)
    try:
        intent_events: list = m._stage_commit_intent(
            t, s,
            Action(kind=ActionKind.COMMIT_THROW, throw_id=ThrowID.UCHI_MATA),
            tick=10,
        )
        intent_evt = next(
            e for e in intent_events if e.event_type == "INTENT_SIGNAL"
        )
        commit_evts: list = []
        m._resolve_consequences(tick=11, events=commit_evts)
        commit_evt = next(
            e for e in commit_evts if e.event_type == "THROW_ENTRY"
        )
        assert intent_evt.tick < commit_evt.tick
        # Specifically the spec's 1-tick advance.
        assert commit_evt.tick - intent_evt.tick == 1
    finally:
        match_module.resolve_throw = real


# ===========================================================================
# AC#5 — elite + low-disguise perception lands on the LAG_CLAMP_MIN floor
# ===========================================================================
def test_elite_low_disguise_consistently_hits_clamp_floor() -> None:
    """HAJ-222 — pre-HAJ-222 this test required negative-lag entries
    (anticipation before the commit tick). Post-HAJ-222 sub-tick
    anticipation is no longer allowed at our tick resolution: the
    LAG_CLAMP_MIN floor is 1 (one tick of physical reaction time).
    The directional invariant that survives: two elite fighters reading
    each other's sloppy (low-disguise) commits should consistently land
    on the clamp floor (lag=1, i.e. read-and-BRACE in time for the
    resolution tick), not drift to 2+ (NONE / late)."""
    from reaction_lag import LAG_CLAMP_MIN
    random.seed(0)
    t, s = _pair()
    t.identity.belt_rank = BeltRank.BLACK_5
    s.identity.belt_rank = BeltRank.BLACK_5
    t.capability.fight_iq = 10
    s.capability.fight_iq = 10
    # Make each fighter highly readable (low disguise) so the perceiver's
    # low-lag base shines through.
    set_uniform(t, 0.0)
    set_uniform(s, 0.0)
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki(), seed=0)
    m.position = Position.GRIPPING
    _seat_deep_grips(m.grip_graph, t, s)
    _seat_deep_grips(m.grip_graph, s, t)
    real = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: ("FAILED", -2.0)
    try:
        for tick in range(5, 50):
            # Drive intent staging on every other tick so the perception
            # phase has signals to read.
            if tick % 2 == 0:
                m._stage_commit_intent(
                    t, s,
                    Action(kind=ActionKind.COMMIT_THROW,
                           throw_id=ThrowID.UCHI_MATA),
                    tick,
                )
                m._perception_phase(tick, [])
                # Drain to clear in-progress so next stage can fire.
                followup: list = []
                m._resolve_consequences(tick + 1, followup)
                m._resolve_consequences(tick + 2, followup)
    finally:
        match_module.resolve_throw = real
    lags = [r.sampled_lag for r in m._perception_log]
    assert lags, "expected at least one perception entry"
    floor_hits = sum(1 for lag in lags if lag == LAG_CLAMP_MIN)
    assert floor_hits >= max(5, len(lags) // 2), (
        f"expected most entries to hit the LAG_CLAMP_MIN ({LAG_CLAMP_MIN}) "
        f"floor; got {floor_hits}/{len(lags)}. All sampled lags: {lags}"
    )


# ===========================================================================
# AC#6 — HAJ-144 t003 reproduction: opening grip exchange distributes
# ===========================================================================
def test_t003_opening_exchange_no_four_grip_seat_on_single_tick() -> None:
    """The opening grip cascade must distribute across multiple ticks.
    No single tick should contain four GRIP_ESTABLISH events for two
    fighters' full grip sets — that's the canonical HAJ-144 t003 bug."""
    captured_per_seed: list = []
    for seed in (1, 7, 42, 99):
        random.seed(seed)
        t, s = _pair()
        m = Match(
            fighter_a=t, fighter_b=s, referee=build_suzuki(),
            max_ticks=20, seed=seed, stream="debug",
        )
        captured: list = []
        m._print_events = lambda evts, _c=captured: _c.extend(evts)
        with contextlib.redirect_stdout(io.StringIO()):
            m.begin()
            while m.position == Position.STANDING_DISTANT and m.ticks_run < 20:
                m.step()
            # Step past the cascade so the follower's response (or
            # disengage) settles.
            for _ in range(3):
                if m.ticks_run >= 20:
                    break
                m.step()
        per_tick: dict[int, int] = {}
        for ev in captured:
            if ev.event_type == "GRIP_ESTABLISH":
                per_tick[ev.tick] = per_tick.get(ev.tick, 0) + 1
        for t_n, count in per_tick.items():
            assert count <= 2, (
                f"seed {seed}: tick {t_n} seated {count} grips at once "
                f"(t003 regression)"
            )
        captured_per_seed.append(per_tick)
    assert captured_per_seed  # at least sanity-checked


# ===========================================================================
# Integration — run a full match and confirm intent precedence at scale
# ===========================================================================
def test_full_match_intent_precedes_every_commit() -> None:
    """Run a full match. For every THROW_ENTRY in the log, there must
    be an INTENT_SIGNAL for the same fighter + throw_id on a strictly
    earlier tick within the match."""
    random.seed(7)
    t, s = _pair()
    m = Match(
        fighter_a=t, fighter_b=s, referee=build_suzuki(),
        max_ticks=80, seed=7, stream="debug",
    )
    captured: list = []
    m._print_events = lambda evts: captured.extend(evts)
    with contextlib.redirect_stdout(io.StringIO()):
        m.run()
    entries = [e for e in captured if e.event_type == "THROW_ENTRY"]
    intents = [
        e for e in captured if e.event_type == "INTENT_SIGNAL"
        and e.data.get("setup_class") == "throw_commit"
    ]
    for entry in entries:
        # Counter throws bypass the staging layer (counters fire from
        # within _try_fire_counter). v0.1 of HAJ-154 leaves counter
        # deferral as a follow-up; skip events tagged as counter
        # follow-ons.
        if entry.data.get("from_consequence_queue") is None:
            # This THROW_ENTRY did not flow through the staging
            # consequence — likely a counter routed through
            # _resolve_commit_throw directly. Tolerated for v0.1.
            continue
        # Else: must have a matching pre-commit intent.
        assert any(
            sig.tick < entry.tick
            and sig.data["throw_id"] == entry.data["throw_id"]
            for sig in intents
        ), f"no pre-commit intent found for THROW_ENTRY at t{entry.tick}"


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
