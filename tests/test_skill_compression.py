# tests/test_skill_compression.py
# Verifies Part 6.1 of design-notes/physics-substrate.md:
#   - Belt-rank → N mapping (elite 1 tick; white belt 5–6 ticks)
#   - Tokui-waza override: signature throws use N-1 (floor 1)
#   - sub_event_schedule collapses/spreads the four sub-events per spec
#     examples (N=1 single line; N=2 KA+TS+KC together; N≥5 wide gaps)
#   - Multi-tick commit emits THROW_ENTRY + sub-events across N ticks
#   - Single-tick (N=1) commit still resolves in one tick
#   - Mid-attempt stun aborts the attempt through the failed-commit pipeline
#   - Action-selection COMMIT_THROW is stripped while an attempt is in flight

from __future__ import annotations
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from enums import (
    BeltRank, BodyPart, GripTypeV2, GripDepth, GripMode, GripTarget,
)
from body_state import place_judoka
from grip_graph import GripGraph, GripEdge
from throws import ThrowID
from skill_compression import (
    N_BY_BELT, compression_n_for, sub_event_schedule, SubEvent,
)
from actions import Action, ActionKind, commit_throw
import main as main_module


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


# ---------------------------------------------------------------------------
# Belt → N mapping
# ---------------------------------------------------------------------------
def test_n_by_belt_monotone_elite_to_white() -> None:
    # White belt is slowest, elite is fastest.
    assert N_BY_BELT[BeltRank.WHITE]   >= N_BY_BELT[BeltRank.GREEN]
    assert N_BY_BELT[BeltRank.GREEN]   >= N_BY_BELT[BeltRank.BROWN]
    assert N_BY_BELT[BeltRank.BROWN]   >= N_BY_BELT[BeltRank.BLACK_1]
    assert N_BY_BELT[BeltRank.BLACK_1] >= N_BY_BELT[BeltRank.BLACK_5]
    assert N_BY_BELT[BeltRank.BLACK_5] == 1
    # White belt lands in the 5–6 range per spec.
    assert 5 <= N_BY_BELT[BeltRank.WHITE] <= 6


def test_tokui_waza_override_is_n_minus_one_floor_one() -> None:
    t, _ = _pair()
    # Tanaka is BLACK_1 with SEOI_NAGE in signature_throws.
    base_n    = N_BY_BELT[t.identity.belt_rank]
    sig_n     = compression_n_for(t, ThrowID.SEOI_NAGE)
    nonsig_n  = compression_n_for(t, ThrowID.UCHI_MATA)
    assert sig_n    == max(1, base_n - 1)
    assert nonsig_n == base_n


def test_tokui_waza_floor_is_one_for_elite() -> None:
    t, _ = _pair()
    t.identity.belt_rank = BeltRank.BLACK_5   # N = 1 baseline
    assert compression_n_for(t, ThrowID.SEOI_NAGE) == 1
    # Non-signature for BLACK_5 also = 1.
    assert compression_n_for(t, ThrowID.UCHI_MATA) == 1


# ---------------------------------------------------------------------------
# sub_event_schedule shapes per spec
# ---------------------------------------------------------------------------
def test_schedule_n1_emits_all_four_on_single_tick() -> None:
    s = sub_event_schedule(1)
    assert s == {0: [SubEvent.REACH_KUZUSHI, SubEvent.KUZUSHI_ACHIEVED,
                     SubEvent.TSUKURI, SubEvent.KAKE_COMMIT]}


def test_schedule_n2_pairs_ka_ts_together() -> None:
    s = sub_event_schedule(2)
    assert SubEvent.KUZUSHI_ACHIEVED in s[1]
    assert SubEvent.TSUKURI          in s[1]
    assert SubEvent.KAKE_COMMIT      in s[1]
    assert s[0] == [SubEvent.REACH_KUZUSHI]


def test_schedule_n4_gives_one_event_per_tick() -> None:
    s = sub_event_schedule(4)
    assert s[0] == [SubEvent.REACH_KUZUSHI]
    assert s[1] == [SubEvent.KUZUSHI_ACHIEVED]
    assert s[2] == [SubEvent.TSUKURI]
    assert s[3] == [SubEvent.KAKE_COMMIT]


def test_schedule_n5_has_silent_padding_and_tight_finish() -> None:
    s = sub_event_schedule(5)
    # REACH on tick 0, then a silent gap.
    assert s[0] == [SubEvent.REACH_KUZUSHI]
    assert 1 not in s
    # KA / TS / KC in the final three ticks.
    assert s[2] == [SubEvent.KUZUSHI_ACHIEVED]
    assert s[3] == [SubEvent.TSUKURI]
    assert s[4] == [SubEvent.KAKE_COMMIT]


def test_schedule_always_ends_with_kake_commit() -> None:
    for n in range(1, 9):
        s = sub_event_schedule(n)
        assert SubEvent.KAKE_COMMIT in s[n - 1], (
            f"N={n}: KAKE_COMMIT should be on the final tick"
        )


# ---------------------------------------------------------------------------
# Match integration — multi-tick commit
# ---------------------------------------------------------------------------
def test_multi_tick_commit_defers_resolution_until_kake() -> None:
    """Force Tanaka's commit on Uchi-mata (non-signature → N=2) and verify
    the attempt unfolds across two ticks: THROW_ENTRY at start, KAKE at end.
    """
    from match import Match
    from referee import build_suzuki
    random.seed(7)
    t, s = _pair()
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())
    _seat_deep_grips(m.grip_graph, t, s)
    s.state.body_state.com_velocity = (-0.5, 0.0)

    # Uchi-mata is NOT in Tanaka's signature throws (Seoi-nage and
    # Harai-goshi are); BLACK_1 base N = 2. Expect 2-tick attempt.
    assert compression_n_for(t, ThrowID.UCHI_MATA) == 2

    tick0 = 5
    events0 = m._resolve_commit_throw(t, s, ThrowID.UCHI_MATA, tick=tick0)
    entry = [e for e in events0 if e.event_type == "THROW_ENTRY"]
    assert entry, "expected THROW_ENTRY on start tick"
    assert entry[0].data.get("compression_n") == 2
    # After start, the attempt is stashed and no THROW_LANDING / FAILED yet.
    assert t.identity.name in m._throws_in_progress
    assert not any(e.event_type in ("THROW_LANDING", "FAILED") for e in events0)

    # Advance one tick — this should emit the remaining sub-events and
    # resolve via resolve_throw.
    events1 = m._advance_throws_in_progress(tick=tick0 + 1)
    kinds = {e.event_type for e in events1}
    assert "SUB_KAKE_COMMIT" in kinds
    # Attempt cleared from the tracker after resolution.
    assert t.identity.name not in m._throws_in_progress


def test_elite_single_tick_commit_resolves_immediately() -> None:
    """An elite's throw (N=1) resolves in one tick — no in-progress stash."""
    from match import Match
    from referee import build_suzuki
    random.seed(8)
    t, s = _pair()
    t.identity.belt_rank = BeltRank.BLACK_5   # N = 1
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())
    _seat_deep_grips(m.grip_graph, t, s)

    events = m._resolve_commit_throw(t, s, ThrowID.UCHI_MATA, tick=3)
    kinds = {e.event_type for e in events}
    assert "THROW_ENTRY" in kinds
    # All four sub-events fired this tick.
    for ev in (SubEvent.REACH_KUZUSHI, SubEvent.KUZUSHI_ACHIEVED,
               SubEvent.TSUKURI, SubEvent.KAKE_COMMIT):
        assert f"SUB_{ev.name}" in kinds
    # No lingering in-progress state.
    assert t.identity.name not in m._throws_in_progress


def test_double_commit_by_same_fighter_is_rejected() -> None:
    """While Tanaka is mid-attempt, a second COMMIT_THROW from him is ignored."""
    from match import Match
    from referee import build_suzuki
    random.seed(9)
    t, s = _pair()
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())
    _seat_deep_grips(m.grip_graph, t, s)

    m._resolve_commit_throw(t, s, ThrowID.UCHI_MATA, tick=1)
    # Sanity: in-progress.
    assert t.identity.name in m._throws_in_progress
    events = m._resolve_commit_throw(t, s, ThrowID.O_SOTO_GARI, tick=1)
    assert events == []


def test_mid_attempt_stun_aborts_through_failed_pipeline() -> None:
    """If the attacker gains stun_ticks mid-attempt, advancement aborts and
    emits a THROW_ABORTED + FAILED event pair with an outcome.
    """
    from match import Match
    from referee import build_suzuki
    random.seed(10)
    t, s = _pair()
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())
    _seat_deep_grips(m.grip_graph, t, s)
    s.state.body_state.com_velocity = (-0.5, 0.0)

    m._resolve_commit_throw(t, s, ThrowID.UCHI_MATA, tick=1)
    assert t.identity.name in m._throws_in_progress

    # Stun tori before the next advancement tick.
    t.state.stun_ticks = 2
    events = m._advance_throws_in_progress(tick=2)
    kinds = [e.event_type for e in events]
    assert "THROW_ABORTED" in kinds
    assert "FAILED" in kinds
    assert t.identity.name not in m._throws_in_progress


def test_commit_strip_while_in_progress() -> None:
    """_strip_commits_if_in_progress removes COMMIT_THROW actions for a
    fighter who already has an attempt in flight.
    """
    from match import Match
    from referee import build_suzuki
    t, s = _pair()
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())
    actions = [commit_throw(ThrowID.UCHI_MATA), Action(kind=ActionKind.HOLD_CONNECTIVE)]
    # No in-progress — actions pass through untouched.
    assert m._strip_commits_if_in_progress(t.identity.name, actions) == actions
    # With in-progress — the commit is stripped.
    _seat_deep_grips(m.grip_graph, t, s)
    m._resolve_commit_throw(t, s, ThrowID.UCHI_MATA, tick=1)
    stripped = m._strip_commits_if_in_progress(t.identity.name, actions)
    assert all(a.kind != ActionKind.COMMIT_THROW for a in stripped)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
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
