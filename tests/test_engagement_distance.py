# tests/test_engagement_distance.py
# HAJ-141 — STANDING_DISTANT closing-phase regressions.
#
# Three properties this test file pins down:
#   1. Match start: at least one tick of STANDING_DISTANT before any grip
#      action seats edges on the graph.
#   2. Post-matte: same property holds across a Matte boundary.
#   3. Kumi-kata clock anchored to first grip: the clock is dormant
#      across the whole closing phase and starts at 0 the tick the
#      fighter's first grip seats.

from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from body_state import place_judoka
from enums import (
    BodyPart, GripTarget, GripTypeV2, GripDepth, MatteReason, Position,
    SubLoopState,
)
from grip_graph import GripEdge
from match import (
    Match, ENGAGEMENT_TICKS_FLOOR, KUMI_KATA_SHIDO_TICKS,
)
from referee import build_suzuki
from throws import ThrowID
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


# ---------------------------------------------------------------------------
# 1. Match start uses STANDING_DISTANT.
# ---------------------------------------------------------------------------
def test_match_starts_in_standing_distant_with_no_edges() -> None:
    """Constructed Match is in STANDING_DISTANT with an empty grip graph."""
    _, _, m = _pair_match()
    assert m.position == Position.STANDING_DISTANT
    assert m.sub_loop_state == SubLoopState.STANDING
    assert m.grip_graph.edge_count() == 0


def test_match_holds_distant_for_at_least_one_tick_before_grip() -> None:
    """At least one tick must elapse in STANDING_DISTANT before any edge
    seats on the graph. The closing-phase floor is ENGAGEMENT_TICKS_FLOOR."""
    assert ENGAGEMENT_TICKS_FLOOR >= 1
    _, _, m = _pair_match()
    m.begin()
    # Tick 1: still distant — engagement_ticks is at most 1, below the floor.
    m.step()
    assert m.grip_graph.edge_count() == 0
    assert m.position == Position.STANDING_DISTANT


def test_match_seats_first_edge_only_after_floor_ticks() -> None:
    """Walk forward until the floor elapses and verify the engagement
    transitions to GRIPPING. With v0.1 calibration (1 tick = 1 sec) and
    floor = 3 ticks, this matches the HAJ-141 AC#3 target of first-grip
    timestamp ≈ t=2 to t=4."""
    _, _, m = _pair_match()
    m.begin()
    for _ in range(ENGAGEMENT_TICKS_FLOOR):
        m.step()
    # Edges seated and position advanced out of STANDING_DISTANT.
    assert m.grip_graph.edge_count() > 0
    assert m.position != Position.STANDING_DISTANT


# ---------------------------------------------------------------------------
# 2. Post-matte resume uses STANDING_DISTANT.
# ---------------------------------------------------------------------------
def test_handle_matte_dispatches_to_standing_distant() -> None:
    """A Matte resolution must reset the dyad to STANDING_DISTANT with no
    edges and engagement_ticks zeroed — there has to be a destination
    state for HAJ-139 (post-score reset) and HAJ-129 (ne-waza exit) to
    dispatch into."""
    t, s, m = _pair_match()
    # Drop a stale edge in to confirm matte clears it.
    m.grip_graph.add_edge(GripEdge(
        grasper_id=t.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=s.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.STANDARD,
        strength=0.8, established_tick=0,
    ))
    m.position = Position.GRIPPING
    m.engagement_ticks = 5
    m.kumi_kata_clock[t.identity.name] = 12
    m._handle_matte(tick=42)
    assert m.position == Position.STANDING_DISTANT
    assert m.sub_loop_state == SubLoopState.STANDING
    assert m.engagement_ticks == 0
    assert m.grip_graph.edge_count() == 0


def test_post_matte_holds_distant_before_re_engagement() -> None:
    """After Matte, the next tick must not seat new edges immediately;
    the closing phase has to elapse just like at match start."""
    _, _, m = _pair_match()
    m.begin()
    # Run once so engagement_ticks advances, then matte resets it.
    m.step()
    m._handle_matte(tick=m.ticks_run)
    assert m.position == Position.STANDING_DISTANT
    assert m.grip_graph.edge_count() == 0
    # One post-matte tick: still no edges (engagement_ticks below floor).
    m.step()
    assert m.grip_graph.edge_count() == 0
    assert m.position == Position.STANDING_DISTANT


# ---------------------------------------------------------------------------
# 3. Kumi-kata clock anchored to first-grip-seated.
# ---------------------------------------------------------------------------
def test_kumi_kata_clock_dormant_during_standing_distant() -> None:
    """The clock must not advance for either fighter during the closing
    phase. AC#5: clock value at first-grip-attempt-tick equals 0 (start of
    a fresh 30-tick window), not (something pre-decremented by closing-
    phase ticks)."""
    t, s, m = _pair_match()
    m.begin()
    for _ in range(ENGAGEMENT_TICKS_FLOOR - 1):
        m.step()
    # Still in STANDING_DISTANT, no edges → both fighters' clocks at 0.
    assert m.position == Position.STANDING_DISTANT
    assert m.grip_graph.edge_count() == 0
    assert m.kumi_kata_clock[t.identity.name] == 0
    assert m.kumi_kata_clock[s.identity.name] == 0


def test_kumi_kata_clock_starts_when_first_grip_seats() -> None:
    """The first tick a fighter owns a grip is the first tick the clock
    advances. We walk through the closing phase, observe the engagement
    seat edges, and check the clock state at that boundary."""
    t, s, m = _pair_match()
    m.begin()
    # Advance until edges seat (closing phase elapses).
    while m.grip_graph.edge_count() == 0 and m.ticks_run < 20:
        m.step()
    assert m.grip_graph.edge_count() > 0
    # Each fighter owns at least one grip now → clock has been advanced
    # exactly once (the tick the engagement seated).
    own_a = m.grip_graph.edges_owned_by(t.identity.name)
    own_b = m.grip_graph.edges_owned_by(s.identity.name)
    assert own_a and own_b
    # Clock values are exactly 1 — the seating tick incremented them once.
    assert m.kumi_kata_clock[t.identity.name] == 1
    assert m.kumi_kata_clock[s.identity.name] == 1
    # And nowhere near the shido threshold.
    assert m.kumi_kata_clock[t.identity.name] < KUMI_KATA_SHIDO_TICKS


# ---------------------------------------------------------------------------
# Bonus: action-legality enforcement (AC #2).
# ---------------------------------------------------------------------------
def test_commit_throw_denied_during_standing_distant() -> None:
    """Even with all the right setup, a throw commit fired while position
    is STANDING_DISTANT must be rejected. This guards against the
    defensive-desperation ladder bypass producing throws-from-thin-air at
    match start or post-matte."""
    t, s, m = _pair_match()
    # Sanity: starting state.
    assert m.position == Position.STANDING_DISTANT
    events = m._resolve_commit_throw(
        attacker=t, defender=s, throw_id=ThrowID.SEOI_NAGE, tick=1,
    )
    assert len(events) == 1
    assert events[0].event_type == "THROW_DENIED_DISTANT"
    assert events[0].data["reason"] == "standing_distant"
    # No throw in progress was created.
    assert t.identity.name not in m._throws_in_progress


def test_select_actions_returns_only_reach_during_standing_distant() -> None:
    """Action selection short-circuits to REACH actions when position is
    distant; no commits, no force drives, no rung-2 paths."""
    from action_selection import select_actions
    from actions import ActionKind

    t, s, m = _pair_match()
    actions = select_actions(
        t, s, m.grip_graph, kumi_kata_clock=0,
        position=Position.STANDING_DISTANT,
    )
    assert all(a.kind == ActionKind.REACH for a in actions)
    assert any(a.kind == ActionKind.REACH for a in actions)


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
