# tests/test_haj70_tick_order_nullification.py
# HAJ-70 — mid-throw counter nullification (tick-order discipline).
#
# Match 4 (Bellandi vs Reid): Reid's Ura-nage counter fired *after*
# Bellandi's throw had achieved KAKE and Reid had landed on her back. The
# throw was already resolved, so the counter "doesn't count." This is a
# tick-order bug: once tori's throw resolves to LANDED_OR_SCORING within a
# tick (Step 11), any uke counter for that same tick must be discarded
# rather than applied against the stale mid-throw state.
#
# Two vectors, both reading the per-tick `_throws_resolved_this_tick` set:
#   1. A *fresh* counter the Step-11 counter check would fire after the
#      throw already resolved earlier in the same tick (the Bellandi/Reid
#      scenario — the in-progress attempt finished in _advance, then the
#      counter check read tori's stale vulnerability windows).
#   2. A counter *queued* on a prior tick whose commit consequence is due
#      on the same tick tori's throw resolves.

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
from counter_windows import CounterWindow
from match import Match, _ThrowInProgress, _Consequence
from referee import build_suzuki
import main as main_module
import match as match_module


# ---------------------------------------------------------------------------
# FIXTURES (mirrors tests/test_causal_tick_ordering.py)
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
    random.seed(seed)
    t, s = _pair()
    t.identity.belt_rank = BeltRank.BLACK_5
    s.identity.belt_rank = BeltRank.BLACK_5
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki(), seed=seed)
    m.position = Position.GRIPPING
    _seat_deep_grips(m.grip_graph, t, s)
    _seat_deep_grips(m.grip_graph, s, t)
    return t, s, m


def _force_counter_fires(monkey_target) -> None:
    """Patch the counter sub-functions on match_module so any read window
    deterministically fires a counter. Caller is responsible for restoring."""
    monkey_target.actual_counter_window = (
        lambda *a, **kw: CounterWindow.GO_NO_SEN
    )
    monkey_target.perceived_counter_window = (
        lambda *a, **kw: CounterWindow.GO_NO_SEN
    )
    monkey_target.has_counter_resources = lambda *a, **kw: True
    monkey_target.select_counter_throw = (
        lambda *a, **kw: ThrowID.DE_ASHI_HARAI
    )
    monkey_target.counter_fire_probability = lambda *a, **kw: 1.0


# ===========================================================================
# Vector 1 — fresh counter discarded after the throw resolved this tick
# ===========================================================================
def test_fresh_counter_fires_when_throw_not_resolved() -> None:
    """Baseline: with the counter sub-functions forced and no throw resolved
    this tick, _try_fire_counter emits a COUNTER_COMMIT (the pre-fix
    behavior we must NOT break for legitimate counters)."""
    t, s, m = _elite_match(seed=1)
    saved = (
        match_module.actual_counter_window,
        match_module.perceived_counter_window,
        match_module.has_counter_resources,
        match_module.select_counter_throw,
        match_module.counter_fire_probability,
    )
    try:
        _force_counter_fires(match_module)
        # s counters t; t has NOT resolved a throw this tick.
        m._throws_resolved_this_tick.clear()
        events = m._try_fire_counter(s, t, tick=20, rng=random.Random(0))
    finally:
        (match_module.actual_counter_window,
         match_module.perceived_counter_window,
         match_module.has_counter_resources,
         match_module.select_counter_throw,
         match_module.counter_fire_probability) = saved

    assert events is not None
    types = {e.event_type for e in events}
    assert "COUNTER_COMMIT" in types
    assert "COUNTER_NULLIFIED" not in types


def test_fresh_counter_nullified_after_throw_resolved_this_tick() -> None:
    """HAJ-70 core: t's throw resolved to LANDED_OR_SCORING earlier this
    tick; s's counter against t is discarded — no COUNTER_COMMIT, a single
    COUNTER_NULLIFIED breadcrumb instead."""
    t, s, m = _elite_match(seed=1)
    saved = (
        match_module.actual_counter_window,
        match_module.perceived_counter_window,
        match_module.has_counter_resources,
        match_module.select_counter_throw,
        match_module.counter_fire_probability,
    )
    try:
        _force_counter_fires(match_module)
        # t's throw already reached KAKE / scored this tick.
        m._throws_resolved_this_tick = {t.identity.name}
        events = m._try_fire_counter(s, t, tick=20, rng=random.Random(0))
    finally:
        (match_module.actual_counter_window,
         match_module.perceived_counter_window,
         match_module.has_counter_resources,
         match_module.select_counter_throw,
         match_module.counter_fire_probability) = saved

    assert events is not None
    types = [e.event_type for e in events]
    assert "COUNTER_COMMIT" not in types
    assert types.count("COUNTER_NULLIFIED") == 1
    null_ev = next(e for e in events if e.event_type == "COUNTER_NULLIFIED")
    assert null_ev.data["attacker"] == t.identity.name
    assert null_ev.data["defender"] == s.identity.name
    assert null_ev.data["reason"] == "throw_resolved_this_tick"
    # Debug-only: the nullification is a mechanics breadcrumb, not a beat.
    assert null_ev.data.get("prose_silent") is True
    assert match_module._is_debug_only_event("COUNTER_NULLIFIED") is True


def test_check_counter_opportunities_respects_resolution() -> None:
    """The Step-11 entry point (_check_counter_opportunities), not just the
    inner helper, must honor the resolution set: neither fighter may land a
    counter on a tick where their opponent's throw already resolved."""
    t, s, m = _elite_match(seed=2)
    saved = (
        match_module.actual_counter_window,
        match_module.perceived_counter_window,
        match_module.has_counter_resources,
        match_module.select_counter_throw,
        match_module.counter_fire_probability,
    )
    try:
        _force_counter_fires(match_module)
        # Both throws "resolved" this tick → no counter from either side.
        m._throws_resolved_this_tick = {t.identity.name, s.identity.name}
        events = m._check_counter_opportunities(tick=20, rng=random.Random(0))
    finally:
        (match_module.actual_counter_window,
         match_module.perceived_counter_window,
         match_module.has_counter_resources,
         match_module.select_counter_throw,
         match_module.counter_fire_probability) = saved

    types = {e.event_type for e in events}
    assert "COUNTER_COMMIT" not in types
    assert "COUNTER_NULLIFIED" in types


# ===========================================================================
# Vector 2 — queued counter commit discarded when its target resolves a
# throw on the same tick (the literal acceptance scenario:
# "tori commits a successful throw on tick N; uke has a counter action
#  queued for tick N; after tick N resolves only the throw outcome is
#  recorded, the counter is discarded with a debug log entry.")
# ===========================================================================
def test_queued_counter_discarded_when_tori_scores_same_tick() -> None:
    t, s, m = _elite_match(seed=3)
    N = 25

    real_resolve = match_module.resolve_throw
    real_sig = match_module.actual_signature_match
    # net in [WAZA_ARI_THRESHOLD, IPPON_THRESHOLD) → a single, non-match-
    # ending waza-ari, so _resolve_consequences keeps processing the queue
    # and reaches uke's counter consequence (an ippon would end the match
    # first and never exercise the guard).
    match_module.resolve_throw = lambda *a, **kw: ("WAZA_ARI", 2.0)
    match_module.actual_signature_match = lambda *a, **kw: 1.0
    collected: list = []
    try:
        # tori (t) has a throw resolving to a clean waza-ari on tick N.
        m._consequence_queue.append(_Consequence(
            due_tick=N, kind="RESOLVE_KAKE_N1",
            payload={
                "attacker_name": t.identity.name,
                "defender_name": s.identity.name,
                "throw_id": ThrowID.SEOI_NAGE,
            },
        ))
        # uke (s) has a counter commit *queued* for the same tick N: the
        # staging layer left a placeholder in-progress entry (from an
        # earlier tick) plus a FIRE_COMMIT_FROM_INTENT consequence. Append
        # it AFTER tori's resolution so the throw resolves first.
        m._throws_in_progress[s.identity.name] = _ThrowInProgress(
            attacker_name=s.identity.name,
            defender_name=t.identity.name,
            throw_id=ThrowID.URA_NAGE if hasattr(ThrowID, "URA_NAGE")
            else ThrowID.DE_ASHI_HARAI,
            start_tick=N - 1,
            compression_n=2,
            schedule={},
            commit_actual=0.0,
        )
        m._consequence_queue.append(_Consequence(
            due_tick=N, kind="FIRE_COMMIT_FROM_INTENT",
            payload={
                "attacker_name": s.identity.name,
                "defender_name": t.identity.name,
                "throw_id": ThrowID.DE_ASHI_HARAI,
                "offensive_desperation": False,
                "defensive_desperation": False,
                "gate_bypass_reason": None,
                "gate_bypass_kind": None,
                "commit_motivation": None,
            },
        ))
        m._resolve_consequences(tick=N, events=collected)
    finally:
        match_module.resolve_throw = real_resolve
        match_module.actual_signature_match = real_sig

    types = [e.event_type for e in collected]
    # The throw outcome is recorded.
    assert "WAZA_ARI_AWARDED" in types
    # The queued counter was discarded: no fresh THROW_ENTRY for uke, a
    # single COUNTER_NULLIFIED breadcrumb instead.
    assert "THROW_ENTRY" not in types
    assert types.count("COUNTER_NULLIFIED") == 1
    # The counter-fighter is not left stuck mid-attempt.
    assert s.identity.name not in m._throws_in_progress
    null_ev = next(e for e in collected if e.event_type == "COUNTER_NULLIFIED")
    assert null_ev.data["attacker"] == t.identity.name  # the one who threw
    assert null_ev.data["defender"] == s.identity.name  # the late counter


# ===========================================================================
# Entry point (mirrors the repo's plain-runner convention)
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
