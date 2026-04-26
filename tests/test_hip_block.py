# tests/test_hip_block.py
# Verifies HAJ-57: uke's hip-block as tsukuri-denial defensive action.
#
# The story:
#   - Hip-loading throws (Seoi-nage, O-goshi, Harai-goshi*, Uchi-mata, Tai-otoshi,
#     O-guruma) require tori to tuck under uke's hip line. An upright uke can
#     drive their hips forward to deny that geometry.
#   - Non-hip-loading throws (O-soto-gari, Tomoe-nage, ashi-waza, leg-reaps)
#     don't have a hip line to deny, so the block is a no-op.
#   - Posture gate: uke's trunk_sagittal must be <= 0 (upright or back-leaning).
#     A bent-over uke can't generate the forward hip drive.
#
# Three layers of testing:
#   1. The hip_loading classification matrix is correct.
#   2. action_selection's BLOCK_HIP rung respects the gates.
#   3. Match._check_hip_blocks aborts the throw with BLOCKED_BY_HIP.

from __future__ import annotations
import math
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from actions import Action, ActionKind, block_hip
from action_selection import select_actions, HIP_BLOCK_FIRE_PROB_AT_FULL_IQ
from body_state import place_judoka
from grip_graph import GripGraph, GripEdge
from enums import BodyPart, GripTypeV2, GripDepth, GripMode, GripTarget
from throws import ThrowID
from throw_templates import FailureOutcome
from worked_throws import worked_template_for, WORKED_THROWS
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


def _seat_grips(graph: GripGraph, attacker, defender) -> None:
    """Both fighters with deep two-handed grips, so neither's action ladder
    drops back to REACH while the test runs."""
    for fr, to, hand, target_loc, gt in (
        (attacker, defender, BodyPart.RIGHT_HAND, GripTarget.LEFT_LAPEL, GripTypeV2.LAPEL_HIGH),
        (attacker, defender, BodyPart.LEFT_HAND,  GripTarget.RIGHT_SLEEVE, GripTypeV2.SLEEVE),
        (defender, attacker, BodyPart.RIGHT_HAND, GripTarget.LEFT_LAPEL, GripTypeV2.LAPEL_HIGH),
        (defender, attacker, BodyPart.LEFT_HAND,  GripTarget.RIGHT_SLEEVE, GripTypeV2.SLEEVE),
    ):
        graph.add_edge(GripEdge(
            grasper_id=fr.identity.name, grasper_part=hand,
            target_id=to.identity.name, target_location=target_loc,
            grip_type_v2=gt, depth_level=GripDepth.DEEP,
            strength=1.0, established_tick=0, mode=GripMode.DRIVING,
        ))


# ---------------------------------------------------------------------------
# 1. CLASSIFICATION MATRIX (chat-refined per HAJ-57)
# ---------------------------------------------------------------------------
HIP_LOADING_THROWS = {
    ThrowID.UCHI_MATA,
    ThrowID.SEOI_NAGE,
    ThrowID.O_GOSHI,
    ThrowID.TAI_OTOSHI,
    ThrowID.HARAI_GOSHI,
    ThrowID.HARAI_GOSHI_CLASSICAL,
    ThrowID.O_GURUMA,
}
NON_HIP_LOADING_THROWS = {
    ThrowID.O_SOTO_GARI,        # Couple, backward sweep + chest push, no hip tuck
    ThrowID.DE_ASHI_HARAI,      # ashi-waza, hand+foot
    ThrowID.KO_UCHI_GARI,       # ashi-waza, hand+foot
    ThrowID.O_UCHI_GARI,        # inner-leg reap, no hip load
    ThrowID.TOMOE_NAGE,         # sacrifice, foot-on-belt below uke (hip drop helps tori)
}


def test_hip_loading_classification_matches_chat_review() -> None:
    """Each worked throw's body_part_requirement.hip_loading flag matches
    the chat-refined classification."""
    for tid in HIP_LOADING_THROWS:
        template = worked_template_for(tid)
        assert template is not None, tid
        assert template.body_part_requirement.hip_loading is True, (
            f"{tid.name} should be hip_loading=True"
        )
    for tid in NON_HIP_LOADING_THROWS:
        template = worked_template_for(tid)
        assert template is not None, tid
        assert template.body_part_requirement.hip_loading is False, (
            f"{tid.name} should be hip_loading=False"
        )


def test_classification_covers_every_worked_throw() -> None:
    """No worked throw should be unclassified — every entry in
    WORKED_THROWS belongs in either HIP_LOADING or NON_HIP_LOADING."""
    classified = HIP_LOADING_THROWS | NON_HIP_LOADING_THROWS
    assert set(WORKED_THROWS.keys()) == classified


# ---------------------------------------------------------------------------
# 2. SELECTION RUNG GATES
# ---------------------------------------------------------------------------
def _block_count(judoka, opponent, graph, opponent_throw, n=400):
    """Run select_actions n times with fresh seeds; count BLOCK_HIP picks."""
    blocks = 0
    for seed in range(n):
        actions = select_actions(
            judoka, opponent, graph,
            kumi_kata_clock=0,
            rng=random.Random(seed),
            opponent_in_progress_throw=opponent_throw,
        )
        if any(a.kind == ActionKind.BLOCK_HIP for a in actions):
            blocks += 1
    return blocks


def test_upright_high_iq_uke_blocks_hip_loading_throw() -> None:
    """An upright, high-IQ uke fires BLOCK_HIP at roughly the configured
    fire probability when tori has a hip-loading throw mid-flight."""
    t, s = _pair()
    s.capability.fight_iq = 10
    s.state.body_state.trunk_sagittal = 0.0
    g = GripGraph()
    _seat_grips(g, t, s)
    blocks = _block_count(s, t, g, ThrowID.SEOI_NAGE)
    expected = HIP_BLOCK_FIRE_PROB_AT_FULL_IQ * 400
    # ±10% tolerance on a 400-sample binomial.
    assert abs(blocks - expected) < 60


def test_bent_over_uke_cannot_block() -> None:
    """A forward-bent uke cannot drive hips forward — never picks BLOCK_HIP
    even with full IQ and a hip-loading throw mid-flight."""
    t, s = _pair()
    s.capability.fight_iq = 10
    s.state.body_state.trunk_sagittal = math.radians(20)   # bent forward
    g = GripGraph()
    _seat_grips(g, t, s)
    blocks = _block_count(s, t, g, ThrowID.SEOI_NAGE)
    assert blocks == 0


def test_back_leaning_uke_can_block() -> None:
    """Posture gate is `trunk_sagittal <= 0` — back-leaning passes the gate
    just like upright (the spec says 'upright or back-leaning')."""
    t, s = _pair()
    s.capability.fight_iq = 10
    s.state.body_state.trunk_sagittal = math.radians(-10)  # back-leaning
    g = GripGraph()
    _seat_grips(g, t, s)
    blocks = _block_count(s, t, g, ThrowID.SEOI_NAGE)
    assert blocks > 200      # well above noise floor


def test_uke_does_not_block_non_hip_loading_throw() -> None:
    """O-soto-gari: no hip line to deny. Block is wasted, never fires."""
    t, s = _pair()
    s.capability.fight_iq = 10
    s.state.body_state.trunk_sagittal = 0.0
    g = GripGraph()
    _seat_grips(g, t, s)
    blocks = _block_count(s, t, g, ThrowID.O_SOTO_GARI)
    assert blocks == 0


def test_uke_does_not_block_tomoe_nage() -> None:
    """Tomoe-nage: foot-on-belt fulcrum below uke. Hip drop *helps* tori,
    so the block is not a defense."""
    t, s = _pair()
    s.capability.fight_iq = 10
    s.state.body_state.trunk_sagittal = 0.0
    g = GripGraph()
    _seat_grips(g, t, s)
    blocks = _block_count(s, t, g, ThrowID.TOMOE_NAGE)
    assert blocks == 0


def test_low_iq_uke_blocks_less_often() -> None:
    """Fire probability scales linearly with fight_iq."""
    t, s = _pair()
    g = GripGraph()
    _seat_grips(g, t, s)
    s.state.body_state.trunk_sagittal = 0.0

    s.capability.fight_iq = 10
    high = _block_count(s, t, g, ThrowID.SEOI_NAGE)
    s.capability.fight_iq = 3
    low = _block_count(s, t, g, ThrowID.SEOI_NAGE)
    s.capability.fight_iq = 0
    none = _block_count(s, t, g, ThrowID.SEOI_NAGE)

    assert high > low > none
    assert none == 0


def test_no_in_progress_throw_no_block() -> None:
    """No throw mid-flight → no block is selected even when posture/iq pass."""
    t, s = _pair()
    s.capability.fight_iq = 10
    s.state.body_state.trunk_sagittal = 0.0
    g = GripGraph()
    _seat_grips(g, t, s)
    blocks = _block_count(s, t, g, opponent_throw=None)
    assert blocks == 0


# ---------------------------------------------------------------------------
# 3. MATCH RESOLUTION — _check_hip_blocks aborts the throw
# ---------------------------------------------------------------------------
def test_match_aborts_hip_loading_throw_when_uke_blocks() -> None:
    """When uke's actions include BLOCK_HIP and tori has a hip-loading
    throw in progress, the throw is removed with BLOCKED_BY_HIP."""
    from match import Match, _ThrowInProgress
    from referee import build_suzuki
    from skill_compression import SubEvent
    t, s = _pair()
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())
    # Plant a hip-loading throw mid-flight for tori.
    m._throws_in_progress[t.identity.name] = _ThrowInProgress(
        attacker_name=t.identity.name,
        defender_name=s.identity.name,
        throw_id=ThrowID.SEOI_NAGE,
        start_tick=0, compression_n=3,
        schedule={1: [SubEvent.REACH_KUZUSHI]},
        commit_actual=0.7,
    )
    events = m._check_hip_blocks(
        actions_a=[],
        actions_b=[block_hip()],
        tick=2,
    )
    assert t.identity.name not in m._throws_in_progress
    assert any(e.event_type == "THROW_BLOCKED_BY_HIP" for e in events)
    assert m._compromised_states[t.identity.name] == FailureOutcome.BLOCKED_BY_HIP


def test_match_does_not_abort_non_hip_loading_throw() -> None:
    """BLOCK_HIP against an O-soto-gari is a no-op — the tip stays."""
    from match import Match, _ThrowInProgress
    from referee import build_suzuki
    from skill_compression import SubEvent
    t, s = _pair()
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())
    m._throws_in_progress[t.identity.name] = _ThrowInProgress(
        attacker_name=t.identity.name,
        defender_name=s.identity.name,
        throw_id=ThrowID.O_SOTO_GARI,
        start_tick=0, compression_n=3,
        schedule={1: [SubEvent.REACH_KUZUSHI]},
        commit_actual=0.7,
    )
    events = m._check_hip_blocks(
        actions_a=[],
        actions_b=[block_hip()],
        tick=2,
    )
    assert t.identity.name in m._throws_in_progress
    assert events == []


def test_block_recovery_is_zero_ticks() -> None:
    """BLOCKED_BY_HIP recovery is 0 — uke gets a clean reset, no stun delay."""
    from match import Match, _ThrowInProgress
    from referee import build_suzuki
    from skill_compression import SubEvent
    t, s = _pair()
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())
    m._throws_in_progress[t.identity.name] = _ThrowInProgress(
        attacker_name=t.identity.name, defender_name=s.identity.name,
        throw_id=ThrowID.UCHI_MATA, start_tick=0, compression_n=3,
        schedule={}, commit_actual=0.7,
    )
    pre_stun = t.state.stun_ticks
    pre_composure = t.state.composure_current
    m._check_hip_blocks(actions_a=[], actions_b=[block_hip()], tick=1)
    # Tori takes no recovery and no composure cost — the block prevented
    # the throw, it didn't fail.
    assert t.state.stun_ticks == pre_stun
    assert t.state.composure_current == pre_composure


def test_block_clears_commit_bookkeeping() -> None:
    """Commit-time motivation/snapshot for tori is dropped on block, so
    the next attempt isn't tainted by stale state."""
    from match import Match, _ThrowInProgress
    from referee import build_suzuki
    from skill_compression import SubEvent
    t, s = _pair()
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())
    m._throws_in_progress[t.identity.name] = _ThrowInProgress(
        attacker_name=t.identity.name, defender_name=s.identity.name,
        throw_id=ThrowID.HARAI_GOSHI, start_tick=0, compression_n=3,
        schedule={}, commit_actual=0.7,
    )
    m._commit_kumi_kata_snapshot[t.identity.name] = 25
    m._check_hip_blocks(actions_a=[], actions_b=[block_hip()], tick=1)
    assert t.identity.name not in m._commit_kumi_kata_snapshot


def test_legacy_throw_without_template_cannot_be_blocked() -> None:
    """A throw without a worked template (legacy ThrowDef path) has no
    body_part_requirement and so cannot be hip-blocked. The action is a
    no-op rather than a crash."""
    from match import Match, _ThrowInProgress
    from referee import build_suzuki
    t, s = _pair()
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())
    # SUMI_GAESHI has no worked template (still on legacy path).
    m._throws_in_progress[t.identity.name] = _ThrowInProgress(
        attacker_name=t.identity.name, defender_name=s.identity.name,
        throw_id=ThrowID.SUMI_GAESHI, start_tick=0, compression_n=3,
        schedule={}, commit_actual=0.5,
    )
    events = m._check_hip_blocks(
        actions_a=[], actions_b=[block_hip()], tick=1,
    )
    assert t.identity.name in m._throws_in_progress
    assert events == []
