# tests/test_force_model.py
# Verifies Part 3 of design-notes/physics-substrate.md:
#   - Action dataclass + kind buckets (3.2)
#   - Priority ladder action selection (3.3)
#   - 12-step tick update produces kuzushi from sustained pull (3.4)
#   - Perception gap — elite std < novice std, clamped to [0, 1] (3.5)
#   - COMMIT_THROW routes through resolve_throw + referee (3.4 step 11)
#   - Random noise on force magnitudes and trunk angles is bounded (3.8)
#   - Match still runs end-to-end with the physics-substrate loop

from __future__ import annotations
import os
import sys
import random

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from actions import (
    Action, ActionKind,
    GRIP_KINDS, FORCE_KINDS, BODY_KINDS, DRIVING_FORCE_KINDS,
    reach, deepen, strip, release, pull, push, hold_connective, feint,
    step as step_action, commit_throw,
)
from enums import (
    GripTypeV2, GripDepth, GripMode, GripTarget, BodyPart, SubLoopState,
    DominantSide, Position,
)
from body_state import place_judoka, ContactState
from grip_graph import GripGraph, GripEdge
from perception import (
    actual_signature_match, perceive, perception_std,
)
from action_selection import select_actions, COMMIT_THRESHOLD
from throws import ThrowID
import main as main_module


# ---------------------------------------------------------------------------
# Part 3.2 — action space
# ---------------------------------------------------------------------------
def test_action_kind_buckets_are_disjoint_and_complete() -> None:
    # Every defined kind belongs to exactly one of the four buckets.
    buckets = [GRIP_KINDS, FORCE_KINDS, BODY_KINDS]
    all_bucketed = set().union(*buckets)
    # COMMIT_THROW is the sole compound and is not in a bucket.
    assert ActionKind.COMMIT_THROW not in all_bucketed
    for kind in ActionKind:
        if kind == ActionKind.COMMIT_THROW:
            continue
        membership = sum(kind in b for b in buckets)
        assert membership == 1, f"{kind.name} in {membership} buckets"


def test_driving_force_kinds_is_subset_of_force_kinds() -> None:
    assert DRIVING_FORCE_KINDS.issubset(FORCE_KINDS)
    # HOLD_CONNECTIVE is a FORCE action but not DRIVING.
    assert ActionKind.HOLD_CONNECTIVE in FORCE_KINDS
    assert ActionKind.HOLD_CONNECTIVE not in DRIVING_FORCE_KINDS


def test_constructors_set_expected_fields() -> None:
    a = pull("right_hand", (1.0, 0.0), 400.0)
    assert a.kind == ActionKind.PULL and a.magnitude == 400.0
    b = feint("left_hand", (0.0, 1.0), 100.0)
    assert b.is_feint is True and b.kind == ActionKind.FEINT


# ---------------------------------------------------------------------------
# Part 3.3 — priority ladder
# ---------------------------------------------------------------------------
def _pair():
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    return t, s


def test_selection_no_grips_returns_reach() -> None:
    t, s = _pair()
    g = GripGraph()
    random.seed(0)
    actions = select_actions(t, s, g, kumi_kata_clock=0)
    # HAJ-128 — locomotion may append a STEP alongside the REACH pair.
    # The grip-side invariant is "no edges → both grip actions are REACH";
    # locomotion is orthogonal and rides the same tick.
    grip_actions = [a for a in actions if a.kind != ActionKind.STEP]
    assert all(a.kind == ActionKind.REACH for a in grip_actions)
    assert len(grip_actions) == 2


def test_selection_shallow_grips_deepen_and_strip() -> None:
    t, s = _pair()
    g = GripGraph()
    # Seat fresh POCKET grips via attempt_engagement.
    for j in (t, s):
        j.state.body["right_hand"].contact_state = ContactState.REACHING
        j.state.body["left_hand"].contact_state  = ContactState.REACHING
    g.attempt_engagement(t, s, current_tick=1)
    random.seed(1)
    actions = select_actions(t, s, g, kumi_kata_clock=0)
    kinds = {a.kind for a in actions}
    assert ActionKind.DEEPEN in kinds
    # Strip picked up the opponent's strongest grip.
    strip_acts = [a for a in actions if a.kind == ActionKind.STRIP]
    assert strip_acts, "expected STRIP against opponent's strongest grip"


def test_selection_deep_grips_drive_forces() -> None:
    t, s = _pair()
    g = GripGraph()
    g.add_edge(GripEdge(
        grasper_id=t.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=s.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.DEEP,
        strength=1.0, established_tick=0,
    ))
    random.seed(2)
    actions = select_actions(t, s, g, kumi_kata_clock=0)
    # Must issue at least one driving force.
    assert any(a.kind in DRIVING_FORCE_KINDS for a in actions)


# ---------------------------------------------------------------------------
# Part 3.5 — perception
# ---------------------------------------------------------------------------
def test_perception_std_lower_for_elite() -> None:
    t, _ = _pair()
    original_iq = t.capability.fight_iq
    t.capability.fight_iq = 10
    elite_std = perception_std(t)
    t.capability.fight_iq = 1
    novice_std = perception_std(t)
    t.capability.fight_iq = original_iq
    assert novice_std > elite_std


def test_perception_error_clamps_to_unit_interval() -> None:
    t, _ = _pair()
    t.capability.fight_iq = 0  # maximum std
    random.seed(3)
    for _ in range(200):
        p = perceive(0.5, t)
        assert 0.0 <= p <= 1.0


def test_actual_signature_match_has_two_factors() -> None:
    t, s = _pair()
    g = GripGraph()
    # With no grips, match is zero (prereqs fail, no kuzushi).
    assert actual_signature_match(ThrowID.SEOI_NAGE, t, s, g) == 0.0


# ---------------------------------------------------------------------------
# Part 3.4 — tick update end-to-end
# ---------------------------------------------------------------------------
def test_sustained_pull_moves_com_or_trunk() -> None:
    """Drive a match forward for 30 ticks; verify the physics loop is doing
    work on at least one fighter — CoM translated, trunk leaned, fatigue
    building, or kuzushi/score event fired.

    HAJ-36: the grip-presence commit gate can keep a match's first 30
    ticks free of throw commits, so we widen the "work was done" check
    to also accept body-state changes and fatigue accumulation.
    """
    from match import Match
    from referee import build_suzuki
    random.seed(1)
    t, s = _pair()
    # Snapshot the starting CoM and hand fatigue so we can compare below.
    start_com_a = t.state.body_state.com_position
    start_com_b = s.state.body_state.com_position
    start_fat_a = t.state.body["right_hand"].fatigue
    start_fat_b = s.state.body["right_hand"].fatigue

    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki(), max_ticks=30)
    m._print_events = lambda evs: None
    m._print_header = lambda: None
    m._resolve_match = lambda: None
    m.run()

    any_kuzushi = m._a_was_kuzushi_last_tick or m._b_was_kuzushi_last_tick
    any_score = (t.state.score["waza_ari"] + s.state.score["waza_ari"]
                 + int(t.state.score["ippon"]) + int(s.state.score["ippon"])) > 0
    com_moved = (
        t.state.body_state.com_position != start_com_a
        or s.state.body_state.com_position != start_com_b
    )
    fatigued = (
        t.state.body["right_hand"].fatigue > start_fat_a
        or s.state.body["right_hand"].fatigue > start_fat_b
    )
    assert any_kuzushi or any_score or m.match_over or com_moved or fatigued


def test_match_reaches_decision_within_240_ticks() -> None:
    """The new physics loop must still produce a decision (win/draw) rather
    than hanging in a stalemate.

    HAJ-36: under the grip-presence commit gate, many POCKET-only matches
    terminate as natural draws — which counts as a decision. We keep
    _resolve_match live so the draw branch can stamp win_method.
    """
    from match import Match
    from referee import build_suzuki
    random.seed(1)
    t, s = _pair()
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki(), max_ticks=240)
    m._print_events = lambda evs: None
    m._print_header = lambda: None
    # _resolve_match is intentionally left live so draws stamp win_method.
    # Monkey-patch only the print sites it touches.
    m._print_final_state = lambda _f: None
    m.run()
    assert m.ticks_run <= 240
    # Match either ended (winner set) or ran the full distance with a draw.
    assert m.win_method in ("ippon", "two waza-ari", "decision", "draw",
                             "hansoku-make", "ippon (pin)", "ippon (submission)")


def test_commit_throw_resolves_via_resolve_throw() -> None:
    """Force a COMMIT_THROW-only action and verify it produces a THROW_ENTRY
    event with the expected throw name.
    """
    from match import Match
    from referee import build_suzuki
    random.seed(4)
    t, s = _pair()
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())

    # Seat strong grips for Tanaka so signature match is non-zero.
    from enums import BodyPart, GripTarget
    m.grip_graph.add_edge(GripEdge(
        grasper_id=t.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=s.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.DEEP,
        strength=1.0, established_tick=0,
    ))
    m.grip_graph.add_edge(GripEdge(
        grasper_id=t.identity.name, grasper_part=BodyPart.LEFT_HAND,
        target_id=s.identity.name, target_location=GripTarget.RIGHT_SLEEVE,
        grip_type_v2=GripTypeV2.SLEEVE_HIGH, depth_level=GripDepth.DEEP,
        strength=1.0, established_tick=0,
    ))

    events = m._resolve_commit_throw(t, s, ThrowID.SEOI_NAGE, tick=5)
    assert any(ev.event_type == "THROW_ENTRY" for ev in events)
    # last_attack_tick was set; kumi-kata clock was reset.
    assert m._last_attack_tick[t.identity.name] == 5
    assert m.kumi_kata_clock[t.identity.name] == 0


# ---------------------------------------------------------------------------
# Part 3.8 — noise is bounded
# ---------------------------------------------------------------------------
def test_force_noise_does_not_drive_unbounded_displacement() -> None:
    """CoM displacement should stay physically plausible (<5m) over 30 ticks.
    Catches a noise-scale bug that would let force blow up.
    """
    from match import Match
    from referee import build_suzuki
    random.seed(2)
    t, s = _pair()
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki(), max_ticks=30)
    m._print_events = lambda evs: None
    m._print_header = lambda: None
    m._resolve_match = lambda: None
    m.run()
    for j in (t, s):
        x, y = j.state.body_state.com_position
        assert abs(x) < 5.0 and abs(y) < 5.0


# ---------------------------------------------------------------------------
# SubLoopState collapse sanity
# ---------------------------------------------------------------------------
def test_sub_loop_state_collapsed_to_standing_plus_newaza() -> None:
    assert hasattr(SubLoopState, "STANDING")
    assert hasattr(SubLoopState, "NE_WAZA")
    # Old states are gone.
    assert not hasattr(SubLoopState, "ENGAGEMENT")
    assert not hasattr(SubLoopState, "TUG_OF_WAR")
    assert not hasattr(SubLoopState, "KUZUSHI_WINDOW")
    assert not hasattr(SubLoopState, "STIFLED_RESET")


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
