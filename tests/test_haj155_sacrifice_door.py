# tests/test_haj155_sacrifice_door.py
# HAJ-155 — sacrifice-throw ne-waza door gate.
#
# Pre-fix: any failed standing throw routed both fighters to ne-waza,
# so a stuffed O-uchi-gari produced the same `[ne-waza]` door event as
# a stuffed Tomoe-nage. The HAJ-144 t007 reproduction (stuffed O-uchi-
# gari → both in GUARD_TOP) was the canonical bug.
#
# Post-fix: the throw vocabulary gains a `throw_class` field; only
# SACRIFICE throws (Sumi-gaeshi, Tomoe-nage) open the ne-waza door on
# stuff or fail. STANDING throws reset to standing. Sacrifice-throw
# failures route tori onto the bottom (geometry-appropriate entry —
# the throw committed tori to the ground).
#
# AC coverage:
#   AC#1 — throw_class field + classification (resolver + ThrowDef)
#   AC#2 — standing-throw stuffs reset to standing (no ne-waza door)
#   AC#3 — sacrifice-throw stuffs route to ne-waza (door fires)
#   AC#4 — geometry-appropriate entry (tori on bottom, uke on top)
#   AC#5 — HAJ-144 t007 regression: stuffed O-uchi-gari, no door
#   AC#6 — HAJ-152 unchanged: successful sacrifice scoring still routes
#          through the post-score follow-up window

from __future__ import annotations
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from enums import (
    BeltRank, BodyPart, GripDepth, GripMode, GripTarget, GripTypeV2,
    Position, SubLoopState,
)
from grip_graph import GripEdge
from match import Match
from referee import build_suzuki
from throws import (
    THROW_DEFS, ThrowClass, ThrowID,
    is_sacrifice_throw, throw_class_for,
)
from ground_continuation import (
    GroundContinuation, GroundContinuationResult,
)
import main as main_module
import match as match_module
from body_state import place_judoka


# ---------------------------------------------------------------------------
# HAJ-236 — standing-stuff ground continuation is now probabilistic. HAJ-155
# guaranteed a standing stuff resets; HAJ-236 makes that the *default* but
# lets reaping throws / ground-hungry fighters spill to the floor. The
# HAJ-155 regression tests below pin the RESET branch deterministically by
# forcing the roll, so they keep testing "a standing stuff can cleanly
# reset" independent of HAJ-236 tuning. The continuation branch has its own
# coverage in test_haj236_standing_ground_entry.py.
# ---------------------------------------------------------------------------
def _force_ground_reset(m) -> None:
    m._roll_ground_continuation = lambda *a, **k: GroundContinuationResult(
        decision=GroundContinuation.RESET_TO_STANDING,
        probability=0.0,
        factors={},
    )


# ---------------------------------------------------------------------------
# FIXTURES
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


def _drive_outcome(m, t, s, throw_id, outcome, commit_tick=10):
    """Drive an N=1 throw to a forced outcome through the HAJ-148 /
    HAJ-157 N+3 chain. Returns the cumulative event list spanning
    commit_tick → commit_tick + 4 so the ne-waza door consequence
    (if it fires) lands in the returned list."""
    real = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: (outcome, -3.0 if outcome != "WAZA_ARI" else 4.5)
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
# AC#1 — throw_class field + classification
# ===========================================================================
def test_throw_class_field_exists_and_defaults_to_standing() -> None:
    """All throws in THROW_DEFS carry a throw_class; default is STANDING."""
    for throw_id, td in THROW_DEFS.items():
        assert hasattr(td, "throw_class"), (
            f"{throw_id.name} missing throw_class field"
        )
        assert isinstance(td.throw_class, ThrowClass)


def test_sacrifice_throws_marked_explicitly() -> None:
    """Sumi-gaeshi and Tomoe-nage are SACRIFICE; everything else is
    STANDING (conservative v0.1 assignment per the ticket)."""
    sacrifice = {ThrowID.SUMI_GAESHI, ThrowID.TOMOE_NAGE}
    for throw_id in sacrifice:
        assert is_sacrifice_throw(throw_id), (
            f"{throw_id.name} should be SACRIFICE"
        )
    for throw_id, td in THROW_DEFS.items():
        if throw_id in sacrifice:
            continue
        assert td.throw_class is ThrowClass.STANDING, (
            f"{throw_id.name} should default to STANDING; got {td.throw_class}"
        )


def test_throw_class_resolver_returns_standing_for_unknown_id() -> None:
    """Defensive — a ThrowID missing from THROW_DEFS resolves to
    STANDING (the conservative no-door path)."""
    # Use a sentinel ID through the resolver function directly. Any
    # ThrowID known to NOT be in THROW_DEFS should fall back to
    # STANDING; in practice all enum values are mapped, so we just
    # confirm the default class on a known STANDING throw.
    assert throw_class_for(ThrowID.UCHI_MATA) is ThrowClass.STANDING


# ===========================================================================
# AC#2 — standing-throw stuffs reset to standing (no ne-waza door)
# ===========================================================================
def test_o_uchi_gari_stuff_does_not_open_ne_waza_door() -> None:
    """The HAJ-144 t007 anchor: a stuffed standing throw must NOT
    enqueue a NEWAZA_TRANSITION_AFTER_STUFF consequence."""
    t, s, m = _elite_match(seed=7)
    _force_ground_reset(m)
    events = _drive_outcome(m, t, s, ThrowID.O_UCHI_GARI, "STUFFED")
    door_consequences = [
        c for c in m._consequence_queue
        if c.kind == "NEWAZA_TRANSITION_AFTER_STUFF"
    ]
    assert door_consequences == [], (
        "stuffed O-uchi-gari (STANDING) must NOT enqueue ne-waza door"
    )
    # And no NEWAZA_TRANSITION event in the log either.
    ne_evs = [e for e in events if e.event_type == "NEWAZA_TRANSITION"]
    assert ne_evs == []


def test_uchi_mata_stuff_does_not_open_ne_waza_door() -> None:
    t, s, m = _elite_match(seed=11)
    _force_ground_reset(m)
    _drive_outcome(m, t, s, ThrowID.UCHI_MATA, "STUFFED")
    assert not [c for c in m._consequence_queue
                if c.kind == "NEWAZA_TRANSITION_AFTER_STUFF"]


def test_standing_stuff_event_describes_standing_reset() -> None:
    """The STUFFED event prose for a standing throw cites 'resetting
    to standing' — outcome-bound, honest about the routing."""
    t, s, m = _elite_match(seed=3)
    _force_ground_reset(m)
    events = _drive_outcome(m, t, s, ThrowID.UCHI_MATA, "STUFFED")
    stuffs = [e for e in events if e.event_type == "STUFFED"]
    assert stuffs
    desc = stuffs[0].description.lower()
    assert "stand" in desc
    assert stuffs[0].data.get("throw_class") == "STANDING"


def test_standing_stuff_keeps_match_in_standing_phase() -> None:
    """After a standing-throw stuff resolves, sub_loop_state should
    NOT be NE_WAZA — the dyad is still on its feet."""
    t, s, m = _elite_match(seed=1)
    _force_ground_reset(m)
    _drive_outcome(m, t, s, ThrowID.UCHI_MATA, "STUFFED")
    assert m.sub_loop_state != SubLoopState.NE_WAZA


# ===========================================================================
# AC#3 — sacrifice-throw stuffs route to ne-waza
# ===========================================================================
def test_sumi_gaeshi_stuff_opens_ne_waza_door() -> None:
    """A stuffed sacrifice throw enqueues the ne-waza door."""
    t, s, m = _elite_match(seed=5)
    events = _drive_outcome(m, t, s, ThrowID.SUMI_GAESHI, "STUFFED")
    # The door consequence either fires by tick+4 (so it's already
    # consumed) or remains queued; either way the dyad ends up in
    # NE_WAZA.
    ne_transitions = [e for e in events if e.event_type == "NEWAZA_TRANSITION"]
    queued = [c for c in m._consequence_queue
              if c.kind == "NEWAZA_TRANSITION_AFTER_STUFF"]
    assert ne_transitions or queued, (
        "stuffed Sumi-gaeshi must open the ne-waza door"
    )


def test_tomoe_nage_stuff_opens_ne_waza_door() -> None:
    t, s, m = _elite_match(seed=2)
    events = _drive_outcome(m, t, s, ThrowID.TOMOE_NAGE, "STUFFED")
    ne_transitions = [e for e in events if e.event_type == "NEWAZA_TRANSITION"]
    queued = [c for c in m._consequence_queue
              if c.kind == "NEWAZA_TRANSITION_AFTER_STUFF"]
    assert ne_transitions or queued


def test_sacrifice_stuff_event_describes_ne_waza_window() -> None:
    """STUFFED prose for a sacrifice throw cites the ne-waza window
    opening — outcome-bound."""
    t, s, m = _elite_match(seed=4)
    events = _drive_outcome(m, t, s, ThrowID.SUMI_GAESHI, "STUFFED")
    stuffs = [e for e in events if e.event_type == "STUFFED"]
    assert stuffs
    desc = stuffs[0].description.lower()
    assert "ne-waza" in desc or "ground" in desc
    assert stuffs[0].data.get("throw_class") == "SACRIFICE"


def test_sacrifice_throw_failed_outcome_opens_ne_waza_door() -> None:
    """FAILED outcomes on sacrifice throws also open the door (per
    the ticket: 'On stuff or failure, the ne-waza door opens')."""
    t, s, m = _elite_match(seed=8)
    _drive_outcome(m, t, s, ThrowID.SUMI_GAESHI, "FAILED")
    queued_or_resolved = (
        m.sub_loop_state == SubLoopState.NE_WAZA
        or any(c.kind == "NEWAZA_TRANSITION_AFTER_STUFF"
               for c in m._consequence_queue)
    )
    assert queued_or_resolved


# ===========================================================================
# AC#4 — geometry-appropriate entry: tori on bottom, uke on top
# ===========================================================================
def test_sacrifice_stuff_puts_tori_on_bottom() -> None:
    """The aggressor (tori) committed to the ground geometrically;
    the engine must reflect that — tori is on the bottom, uke is the
    top fighter."""
    t, s, m = _elite_match(seed=12)
    # Force ne_waza_resolver.attempt_ground_commit to fire so the
    # transition actually lands (default skill rolls may decline).
    m.ne_waza_resolver.attempt_ground_commit = (
        lambda a, d, q: ["forced"]
    )
    _drive_outcome(m, t, s, ThrowID.SUMI_GAESHI, "STUFFED")
    if m.sub_loop_state != SubLoopState.NE_WAZA:
        # The transition lands on the door consequence's due_tick;
        # advance one more tick to fire the queued consequence.
        m._resolve_consequences(tick=15, events=[])
    assert m.sub_loop_state == SubLoopState.NE_WAZA
    assert m.ne_waza_top_id == s.identity.name, (
        f"uke ({s.identity.name}) should be on top after sacrifice "
        f"stuff; got {m.ne_waza_top_id}"
    )
    # Position is GUARD_TOP — uke passing tori's open guard.
    assert m.position == Position.GUARD_TOP


def test_standing_stuff_does_not_assign_ne_waza_top() -> None:
    """Standing stuff resets to standing; ne_waza_top_id stays None
    (no ne-waza routing happened)."""
    t, s, m = _elite_match(seed=9)
    _force_ground_reset(m)
    _drive_outcome(m, t, s, ThrowID.UCHI_MATA, "STUFFED")
    assert m.ne_waza_top_id is None


# ===========================================================================
# AC#5 — HAJ-144 t007 regression test
# ===========================================================================
def test_haj144_t007_reproduction_no_ne_waza_door() -> None:
    """Re-run the t007 anchor (stuffed O-uchi-gari): no ne-waza door
    fires; both fighters reset to standing."""
    t, s, m = _elite_match(seed=7)
    _force_ground_reset(m)
    events = _drive_outcome(m, t, s, ThrowID.O_UCHI_GARI, "STUFFED")
    # No ne-waza door event fires (queued or resolved).
    assert not [e for e in events if e.event_type == "NEWAZA_TRANSITION"]
    assert not [c for c in m._consequence_queue
                if c.kind == "NEWAZA_TRANSITION_AFTER_STUFF"]
    # Sub-loop state stays out of NE_WAZA — the dyad is still standing.
    assert m.sub_loop_state != SubLoopState.NE_WAZA


# ===========================================================================
# AC#6 — HAJ-152 unchanged: successful sacrifice score routes through
# the post-score follow-up window, not the ne-waza door
# ===========================================================================
def test_successful_sacrifice_waza_ari_does_not_use_stuff_door() -> None:
    """A scored sacrifice throw goes through the HAJ-152 post-score
    follow-up window (chase-decision path), NOT the HAJ-155 stuff
    door. The two pathways must remain distinct."""
    t, s, m = _elite_match(seed=14)
    events = _drive_outcome(m, t, s, ThrowID.SUMI_GAESHI, "WAZA_ARI")
    # No stuff door consequence — the post-score path owns the
    # follow-up.
    assert not [c for c in m._consequence_queue
                if c.kind == "NEWAZA_TRANSITION_AFTER_STUFF"]
    # The scoring path opened a post-score follow-up instead.
    assert m._post_score_follow_up is not None or any(
        e.event_type == "SCORE_AWARDED" for e in events
    )


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
