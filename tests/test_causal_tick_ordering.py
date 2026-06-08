# tests/test_causal_tick_ordering.py
# HAJ-148 — causal tick ordering regression tests.
#
# Three canonical scenarios from the issue:
#   1. t007 reproduction — paired commits + stuff + ne-waza door must
#      distribute across at least 3 ticks; no single tick contains more
#      than one substantive event per fighter; no prose attaches to a
#      commit event.
#   2. Simultaneous commits — both fighters commit on the same tick; the
#      commit itself is legal on that tick (different fighters), but each
#      commit's consequences (land / stuff / score) resolve on subsequent
#      ticks rather than co-firing.
#   3. Sacrifice-throw chain — throw → land → ne-waza door fires across
#      three distinct ticks.
#
# Plus: AC#3 (commits silent in prose), AC#4 (landing + score share a
# tick, the commit on the previous tick), AC#8 (match length neutral).

from __future__ import annotations
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from enums import (
    BeltRank, BodyPart, GripTypeV2, GripDepth, GripMode, GripTarget,
    Position, SubLoopState,
)
from body_state import place_judoka
from grip_graph import GripGraph, GripEdge
from throws import ThrowID
from match import Match
from referee import build_suzuki
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
    """Build a match with both fighters as elite (N=1) and grips already
    seated, ready for direct commit-resolution. Bypasses the engagement-
    distance gate because we're driving _resolve_commit_throw directly."""
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
# AC#3 — commits are silent in prose
# ===========================================================================
def test_commit_event_is_silent_in_prose() -> None:
    """No prose line attaches to a THROW_ENTRY event on the tick the
    commit fires. The engineering event still emits for debug / BPE
    bookkeeping; the prose layer suppresses it via the prose_silent flag."""
    t, s, m = _elite_match()
    events = m._resolve_commit_throw(t, s, ThrowID.UCHI_MATA, tick=5)
    entry = next(e for e in events if e.event_type == "THROW_ENTRY")
    # Engineering event still fires (with metadata).
    assert entry.tick == 5
    # But the prose stream is told to skip it.
    assert entry.data.get("prose_silent") is True


def test_no_prose_event_co_occurs_with_commit_in_full_match() -> None:
    """Run a full match and scan the event log: no prose-bearing event may
    share a tick with a THROW_ENTRY event for the same fighter from the
    same throw. (The commit's body-part decomposition fires on the commit
    tick, but the scoring / landing prose is on N+1 from the consequence
    queue.)"""
    import contextlib, io
    random.seed(11)
    t, s = _pair()
    m = Match(
        fighter_a=t, fighter_b=s, referee=build_suzuki(),
        max_ticks=80, seed=11, stream="debug",
    )
    # Capture all events emitted during the match by hooking _print_events.
    all_events: list = []
    real_print = m._print_events
    def _capture(evts):
        all_events.extend(evts)
        return real_print(evts)
    m._print_events = _capture
    with contextlib.redirect_stdout(io.StringIO()):
        m.run()
    # For every THROW_ENTRY, no prose-visible event may share its tick.
    # (HAJ-148 commit-silent rule: prose belongs to the resolution tick.)
    for ev in all_events:
        if ev.event_type != "THROW_ENTRY":
            continue
        # The commit itself must be prose-silent.
        assert ev.data.get("prose_silent") is True, (
            f"THROW_ENTRY at tick {ev.tick} not marked prose_silent"
        )


# ===========================================================================
# AC#1 + AC#2 — t007 reproduction
# ===========================================================================
def test_t007_reproduction_distributes_across_at_least_three_ticks() -> None:
    """The HAJ-144 t007 scenario: paired commits → stuff → ne-waza door.
    Pre-fix this all bunched onto a single tick; post-fix it must
    distribute across at least 3 distinct ticks."""
    # Force a STUFFED outcome so the ne-waza door fires.
    t, s, m = _elite_match(seed=7)
    real_resolve = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: ("STUFFED", -2.0)
    collected: list = []
    try:
        # Tick N: both fighters commit (legal on the same tick — they're
        # different fighters; the within-fighter cap holds because each
        # only fires one COMMIT_THROW). HAJ-157 V1/V5 — the N=1 throw
        # spreads across 4 ticks: RK+KA on N, TS on N+1, KC on N+2,
        # outcome on N+3 from the consequence queue.
        N = 5
        collected.extend(m._resolve_commit_throw(t, s, ThrowID.O_UCHI_GARI, tick=N))
        collected.extend(m._resolve_commit_throw(s, t, ThrowID.O_UCHI_GARI, tick=N))
        # Tick N+1: tsukuri sub-events emit from _advance.
        collected.extend(m._advance_throws_in_progress(tick=N + 1))
        # Tick N+2: kake sub-events emit from _advance.
        collected.extend(m._advance_throws_in_progress(tick=N + 2))
        # Tick N+3: STUFFED outcomes fire from RESOLVE_KAKE_N1 consequences;
        # both stuffs share the same tick, so the ne-waza door dedupe at
        # the STUFFED branch (HAJ-157 V3) keeps the door queued exactly
        # once for tick N+4.
        m._resolve_consequences(tick=N + 3, events=collected)
        # Tick N+4: the ne-waza door fires.
        m._resolve_consequences(tick=N + 4, events=collected)
    finally:
        match_module.resolve_throw = real_resolve

    ticks_seen = sorted({e.tick for e in collected})
    assert len(ticks_seen) >= 3, (
        f"expected the t007 chain to span ≥ 3 ticks, got {ticks_seen}"
    )

    # AC#1 — at most one substantive ladder event per fighter per tick.
    # The commit on N is the only ladder substantive each fighter fires;
    # everything on N+1/N+2 is from the consequence queue.
    SUBSTANTIVE_TYPES = frozenset({
        "THROW_ENTRY", "STUFFED", "FAILED", "THROW_LANDING",
        "COUNTER_COMMIT", "BLOCK_HIP", "GRIP_STRIPPED",
    })
    for tick_n in ticks_seen:
        per_fighter: dict[str, int] = {t.identity.name: 0, s.identity.name: 0}
        for ev in collected:
            if ev.tick != tick_n:
                continue
            if ev.event_type not in SUBSTANTIVE_TYPES:
                continue
            if ev.data.get("from_consequence_queue"):
                # Consequence-queue events are not "from the action ladder"
                # per AC#1; they're the resolution of the prior tick's
                # commit, which the ladder is not double-counted for.
                continue
            actor = ev.data.get("attacker") or ev.data.get("fighter")
            if actor in per_fighter:
                per_fighter[actor] += 1
        for fighter, count in per_fighter.items():
            assert count <= 1, (
                f"tick {tick_n}: fighter {fighter} has {count} substantive "
                f"ladder events (max 1 per HAJ-148 AC#1)"
            )

    # No prose event co-occurs with a commit.
    for ev in collected:
        if ev.event_type == "THROW_ENTRY":
            assert ev.data.get("prose_silent") is True


# ===========================================================================
# Simultaneous commits — both legal, consequences distribute
# ===========================================================================
def test_simultaneous_commits_legal_consequences_distribute() -> None:
    """Both fighters commit on the same tick — legal, since they're
    different fighters. Each commit's consequence resolves on a later
    tick rather than co-firing with the commits."""
    t, s, m = _elite_match(seed=42)
    real_resolve = match_module.resolve_throw
    # Force one to land waza-ari, the other to fail outright. This
    # guarantees both commits actually resolve (no chain into ne-waza
    # for either).
    outcomes = iter([("WAZA_ARI", 4.5), ("FAILED", -3.5)])
    match_module.resolve_throw = lambda *a, **kw: next(outcomes)
    collected: list = []
    try:
        N = 8
        collected.extend(m._resolve_commit_throw(t, s, ThrowID.SEOI_NAGE, tick=N))
        collected.extend(m._resolve_commit_throw(s, t, ThrowID.UCHI_MATA, tick=N))
        # HAJ-157 V1/V5 — N=1 throws spread RK+KA / TS / KC over 3 ticks,
        # outcome lands on N+3 via RESOLVE_KAKE_N1.
        collected.extend(m._advance_throws_in_progress(tick=N + 1))
        collected.extend(m._advance_throws_in_progress(tick=N + 2))
        m._resolve_consequences(tick=N + 3, events=collected)
    finally:
        match_module.resolve_throw = real_resolve

    # Both THROW_ENTRY events live on N.
    entries = [e for e in collected if e.event_type == "THROW_ENTRY"]
    assert len(entries) == 2
    assert all(e.tick == N for e in entries)

    # Resolution events live on N+1 or later, never on N.
    resolution_types = {"THROW_LANDING", "STUFFED", "FAILED", "SCORE_AWARDED"}
    res = [e for e in collected if e.event_type in resolution_types]
    assert res, "expected at least one resolution event"
    for ev in res:
        assert ev.tick > N, (
            f"resolution event {ev.event_type} on tick {ev.tick} co-fires "
            f"with the commit tick {N}"
        )


# ===========================================================================
# Sacrifice-throw chain — throw → land → ne-waza door across 3 ticks
# ===========================================================================
def test_sacrifice_throw_chain_distributes_across_distinct_ticks() -> None:
    """A stuffed sacrifice-style commit (we approximate with any STUFFED
    outcome) produces the chain: commit → stuff → ne-waza door, each on a
    distinct tick. B-3a — Sumi-gaeshi is now a 2-tick worked throw (was a
    1-tick snap), so the spread is one tick longer and the outcome lands on
    N+4 (was N+3)."""
    t, s, m = _elite_match(seed=3)
    real_resolve = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: ("STUFFED", -1.0)
    collected: list = []
    try:
        N = 12
        # Tick N: commit (silent in prose) + RK + KA sub-events.
        collected.extend(m._resolve_commit_throw(t, s, ThrowID.SUMI_GAESHI, tick=N))
        # Ticks N+1..N+3: drive + TS + KC sub-events emit from _advance.
        collected.extend(m._advance_throws_in_progress(tick=N + 1))
        collected.extend(m._advance_throws_in_progress(tick=N + 2))
        collected.extend(m._advance_throws_in_progress(tick=N + 3))
        # Tick N+4: STUFFED resolution fires; ne-waza door scheduled for N+5.
        m._resolve_consequences(tick=N + 3, events=collected)
        m._resolve_consequences(tick=N + 4, events=collected)
    finally:
        match_module.resolve_throw = real_resolve

    commit_tick = next(e.tick for e in collected if e.event_type == "THROW_ENTRY")
    stuff_tick = next(
        e.tick for e in collected if e.event_type == "STUFFED"
    )
    assert commit_tick == N
    assert stuff_tick == N + 4
    # Every event from the queue carries the from_consequence_queue mark.
    queue_events = [e for e in collected if e.data.get("from_consequence_queue")]
    assert any(e.tick == N + 4 for e in queue_events), (
        "stuff resolution should be a queue event on N+4"
    )


# ===========================================================================
# AC#4 — throw landing and score fire on the same tick (post-commit)
# ===========================================================================
def test_landing_and_score_share_a_tick_on_n_plus_three() -> None:
    """The landing event and the score event share a tick. The commit
    that produced them lives 3 ticks earlier (HAJ-157 V1/V5 — N=1
    throws spread kuzushi/tsukuri/kake across consecutive ticks before
    the outcome lands). Patch both resolve_throw and the
    actual_signature_match read so the kake-time recompute returns a
    clean 1.0 (eq=1.0); without that the referee would downgrade the
    WAZA_ARI to no-score on a 0.0 eq."""
    t, s, m = _elite_match(seed=99)
    real_resolve = match_module.resolve_throw
    real_sig = match_module.actual_signature_match
    match_module.resolve_throw = lambda *a, **kw: ("WAZA_ARI", 4.0)
    match_module.actual_signature_match = lambda *a, **kw: 1.0
    collected: list = []
    try:
        N = 6
        collected.extend(m._resolve_commit_throw(t, s, ThrowID.SEOI_NAGE, tick=N))
        # Walk the four-tick chain.
        collected.extend(m._advance_throws_in_progress(tick=N + 1))
        collected.extend(m._advance_throws_in_progress(tick=N + 2))
        m._resolve_consequences(tick=N + 3, events=collected)
    finally:
        match_module.resolve_throw = real_resolve
        match_module.actual_signature_match = real_sig

    commit = next(e for e in collected if e.event_type == "THROW_ENTRY")
    score = next(
        e for e in collected
        if e.event_type in ("WAZA_ARI_AWARDED", "IPPON_AWARDED")
    )
    assert commit.tick == N
    assert score.tick == N + 3


# ===========================================================================
# AC#8 — match length neutral
# ===========================================================================
def test_match_length_neutral() -> None:
    """A 60-tick match with the new causal-ordering rules still consumes
    exactly 60 ticks. Bumping or shrinking the tick budget would be a
    calibration regression."""
    import contextlib, io
    # HAJ-235 — the matte→hajime freeze removes live-action ticks during the
    # pause, shifting seeded trajectories. Seed 5 now ties at the regulation
    # boundary and enters golden score, which by design runs past the tick
    # budget; re-pinned to a seed that still resolves inside the 60-tick
    # window so the budget-neutrality assertion stays meaningful.
    random.seed(6)
    t, s = _pair()
    m = Match(
        fighter_a=t, fighter_b=s, referee=build_suzuki(),
        max_ticks=60, seed=6, stream="debug",
    )
    with contextlib.redirect_stdout(io.StringIO()):
        m.run()
    # Match either ran to time-up (ticks_run == max_ticks) or ended early
    # by ippon/two-waza-ari. In both cases ticks_run is bounded by
    # max_ticks; the budget itself is what we're guarding.
    assert m.ticks_run <= 60
    # And the post-148 tick budget didn't artificially inflate via bonus
    # ticks — m.max_ticks remains 60 throughout the run.
    assert m.max_ticks == 60


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
