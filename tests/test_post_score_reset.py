# tests/test_post_score_reset.py
# HAJ-139 — post-score reset window dispatching to STANDING_DISTANT.
#
# Pre-HAJ-139, after a single waza-ari was awarded, the sub-loop carried
# on with the same grips intact and the next throw could fire on the
# very next tick (as in HAJ-139's example log: t29 waza-ari, t30 next
# throw committing). Post-fix:
#   - position resets to STANDING_DISTANT
#   - all edges break
#   - engagement_ticks pre-decrements to -POST_SCORE_RECOVERY_TICKS so
#     the closing phase pause is longer than first-engagement
#   - a SCORE_RESET event is emitted for prose visibility
#   - a NO_SCORE-downgraded landing also resets (the body still hit the mat)
# Match-ending IPPON / two-waza-ari paths skip the reset (match_over=True).

from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from body_state import place_judoka
from enums import (
    BodyPart, GripTarget, GripTypeV2, GripDepth, Position, SubLoopState,
)
from grip_graph import GripEdge
from match import (
    Match, ENGAGEMENT_TICKS_FLOOR, POST_SCORE_RECOVERY_TICKS,
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


def _seat_grips(m, owner, target):
    """Seat a lapel + sleeve pair owned by `owner` on `target`."""
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
# 1. Direct unit test of _post_score_reset.
# ---------------------------------------------------------------------------
def test_post_score_reset_breaks_edges_and_returns_to_distant() -> None:
    t, s, m = _pair_match()
    m.position = Position.GRIPPING
    _seat_grips(m, t, s)
    assert m.grip_graph.edge_count() > 0

    events = m._post_score_reset(tick=29, reason="waza-ari")

    assert m.position == Position.STANDING_DISTANT
    assert m.grip_graph.edge_count() == 0
    assert m.sub_loop_state == SubLoopState.STANDING
    # engagement_ticks pre-decremented so the closing phase pause is
    # POST_SCORE_RECOVERY_TICKS longer than first-engagement.
    assert m.engagement_ticks == -POST_SCORE_RECOVERY_TICKS
    # SCORE_RESET event emitted for prose visibility.
    assert any(ev.event_type == "SCORE_RESET" for ev in events)
    reset = next(ev for ev in events if ev.event_type == "SCORE_RESET")
    assert reset.data["reason"] == "waza-ari"
    assert reset.data["recovery_bonus"] == POST_SCORE_RECOVERY_TICKS


# ---------------------------------------------------------------------------
# 2. Total pause = floor + recovery before edges seat again.
# ---------------------------------------------------------------------------
def test_post_score_reset_pause_is_floor_plus_recovery() -> None:
    """After a post-score reset, no edges seat until ENGAGEMENT_TICKS_FLOOR
    + POST_SCORE_RECOVERY_TICKS ticks of mutual reach have elapsed."""
    _, _, m = _pair_match()
    m.begin()
    m._post_score_reset(tick=10, reason="waza-ari")

    expected_pause = ENGAGEMENT_TICKS_FLOOR + POST_SCORE_RECOVERY_TICKS
    # Step pause-1 ticks; no edges should have seated yet.
    for _ in range(expected_pause - 1):
        m.step()
        assert m.grip_graph.edge_count() == 0
        assert m.position == Position.STANDING_DISTANT
    # One more tick: edges seat, position transitions out of distant.
    m.step()
    assert m.grip_graph.edge_count() > 0
    assert m.position != Position.STANDING_DISTANT


# ---------------------------------------------------------------------------
# 3. Single waza-ari from a throw triggers the reset; two waza-ari does not.
# ---------------------------------------------------------------------------
def test_single_waza_ari_triggers_post_score_reset() -> None:
    """A waza-ari award through _apply_throw_result must dispatch through
    the post-score reset when match continues."""
    import match as match_module
    t, s, m = _pair_match()
    m.position = Position.GRIPPING
    _seat_grips(m, t, s)
    # Force the resolver to land a clean WAZA_ARI for predictable scoring.
    real_resolve = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: ("WAZA_ARI", 2.0)
    try:
        events = m._apply_throw_result(
            attacker=t, defender=s, throw_id=ThrowID.UCHI_MATA,
            outcome="WAZA_ARI", net=2.0, window_quality=1.0, tick=29,
            execution_quality=0.9,
        )
    finally:
        match_module.resolve_throw = real_resolve
    # Match continues (single waza-ari).
    assert not m.match_over
    assert t.state.score["waza_ari"] == 1
    # SCORE_RESET fired.
    assert any(ev.event_type == "SCORE_RESET" for ev in events)
    # Dyad is back in distant with no edges.
    assert m.position == Position.STANDING_DISTANT
    assert m.grip_graph.edge_count() == 0


def test_two_waza_ari_ends_match_no_reset_event() -> None:
    """When the second waza-ari ends the match, no SCORE_RESET should
    fire — there's no next exchange to set up."""
    import match as match_module
    t, s, m = _pair_match()
    m.position = Position.GRIPPING
    _seat_grips(m, t, s)
    # Pre-load Tanaka with one waza-ari so this one ends the match.
    t.state.score["waza_ari"] = 1
    real_resolve = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: ("WAZA_ARI", 2.0)
    try:
        events = m._apply_throw_result(
            attacker=t, defender=s, throw_id=ThrowID.UCHI_MATA,
            outcome="WAZA_ARI", net=2.0, window_quality=1.0, tick=29,
            execution_quality=0.9,
        )
    finally:
        match_module.resolve_throw = real_resolve
    assert m.match_over
    assert m.winner is t
    # No reset — match is over, the next-engagement state doesn't matter.
    assert not any(ev.event_type == "SCORE_RESET" for ev in events)


def test_no_score_downgrade_triggers_reset() -> None:
    """Even a NO_SCORE-downgraded landing put a fighter on the mat;
    re-engagement must go through STANDING_DISTANT."""
    import match as match_module
    t, s, m = _pair_match()
    m.position = Position.GRIPPING
    _seat_grips(m, t, s)
    # resolve_throw returns WAZA_ARI on raw net; the referee downgrades it.
    real_resolve = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: ("WAZA_ARI", 2.0)
    real_score = m.referee.score_throw
    from referee import ScoreResult
    m.referee.score_throw = lambda landing, tick: ScoreResult(
        award="NO_SCORE", technique_quality=0.4,
        landing_angle=45.0, control_maintained=False,
    )
    try:
        events = m._apply_throw_result(
            attacker=t, defender=s, throw_id=ThrowID.UCHI_MATA,
            outcome="WAZA_ARI", net=2.0, window_quality=1.0, tick=29,
            execution_quality=0.4,
        )
    finally:
        match_module.resolve_throw = real_resolve
        m.referee.score_throw = real_score
    assert any(ev.event_type == "SCORE_RESET" for ev in events)
    assert m.position == Position.STANDING_DISTANT
    assert m.grip_graph.edge_count() == 0


# ---------------------------------------------------------------------------
# 4. Matte uses the same reset path with no recovery bonus.
# ---------------------------------------------------------------------------
def test_handle_matte_uses_zero_recovery_bonus() -> None:
    """Matte resets the dyad through the same helper but with no
    recovery bonus — the matte announcement covers the prose beat."""
    _, _, m = _pair_match()
    m.position = Position.GRIPPING
    m.engagement_ticks = 7
    m._handle_matte(tick=42)
    assert m.position == Position.STANDING_DISTANT
    assert m.engagement_ticks == 0   # no bonus for matte


# ---------------------------------------------------------------------------
# 5. Throw cannot fire during the post-score recovery window.
# ---------------------------------------------------------------------------
def test_no_commit_during_post_score_window() -> None:
    """The HAJ-141 STANDING_DISTANT commit gate is what enforces 'no
    throws during the recovery window.' Verify the gate fires when a
    direct commit is attempted right after a post-score reset."""
    t, s, m = _pair_match()
    m.position = Position.GRIPPING
    _seat_grips(m, t, s)
    m._post_score_reset(tick=10, reason="waza-ari")
    # No edges, distant. A direct commit should be denied.
    assert m.position == Position.STANDING_DISTANT
    assert m.grip_graph.edge_count() == 0
    events = m._resolve_commit_throw(
        attacker=t, defender=s, throw_id=ThrowID.SEOI_NAGE, tick=11,
    )
    assert events
    assert events[0].event_type == "THROW_DENIED_DISTANT"


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
