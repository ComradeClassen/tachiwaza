# tests/test_haj93_golden_score.py
# HAJ-93 — Golden score: transition into golden score, sudden-death
# scoring, third-shido-by-hansoku-make resolution, MATCH_ENDED payload.
#
# Acceptance criteria covered:
#   1. Match ending 0-0 in regulation enters golden score (not draw/decision)
#   2. Match ending 1 waza-ari to 1 waza-ari enters golden score
#   3. Match ending unequal waza-ari ends by decision (does NOT enter
#      golden score)
#   4. A waza-ari scored 30s into golden score ends the match
#   5. A third shido in golden score ends the match for the opponent
#   6. All match-ending paths emit a MATCH_ENDED event with consistent
#      payload (winner, method, tick, golden_score, score state)

from __future__ import annotations
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from body_state import place_judoka
from enums import (
    BodyPart, GripTarget, GripTypeV2, GripDepth, GripMode, Position,
)
from grip_graph import GripEdge
from match import Match
from referee import build_suzuki
from throws import ThrowID
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


def _match(regulation_ticks: int = 240, max_ticks: int | None = None,
           seed: int = 1) -> tuple:
    random.seed(seed)
    t, s = _pair()
    if max_ticks is None:
        max_ticks = regulation_ticks
    m = Match(
        fighter_a=t, fighter_b=s, referee=build_suzuki(),
        regulation_ticks=regulation_ticks, max_ticks=max_ticks, seed=seed,
    )
    return t, s, m


def _seat_grips(m, owner, target):
    m.grip_graph.add_edge(GripEdge(
        grasper_id=owner.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=target.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.STANDARD,
        strength=0.8, established_tick=0, mode=GripMode.DRIVING,
    ))
    m.grip_graph.add_edge(GripEdge(
        grasper_id=owner.identity.name, grasper_part=BodyPart.LEFT_HAND,
        target_id=target.identity.name, target_location=GripTarget.RIGHT_SLEEVE,
        grip_type_v2=GripTypeV2.SLEEVE_HIGH, depth_level=GripDepth.STANDARD,
        strength=0.8, established_tick=0, mode=GripMode.DRIVING,
    ))


def _force_waza_ari(t, s, m, throw_id, tick):
    """Drive a clean waza-ari award through _apply_throw_result."""
    m.position = Position.GRIPPING
    _seat_grips(m, t, s)
    real = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: ("WAZA_ARI", 2.0)
    try:
        events = m._apply_throw_result(
            attacker=t, defender=s, throw_id=throw_id,
            outcome="WAZA_ARI", net=2.0, window_quality=1.0, tick=tick,
            execution_quality=0.9,
        )
    finally:
        match_module.resolve_throw = real
    return events


# ===========================================================================
# AC#1 — 0-0 at regulation end → enters golden score
# ===========================================================================
def test_regulation_end_0_0_enters_golden_score() -> None:
    t, s, m = _match(regulation_ticks=240, max_ticks=600)
    # Both fighters at 0 waza-ari; regulation just elapsed.
    events: list = []
    m._check_regulation_end(tick=240, events=events)

    assert m.golden_score is True
    assert m.match_over is False
    assert m.golden_score_start_tick == 240
    starts = [e for e in events if e.event_type == "GOLDEN_SCORE_START"]
    assert len(starts) == 1
    assert starts[0].data["a_waza_ari"] == 0
    assert starts[0].data["b_waza_ari"] == 0


# ===========================================================================
# AC#2 — 1-1 at regulation end → enters golden score
# ===========================================================================
def test_regulation_end_1_1_enters_golden_score() -> None:
    t, s, m = _match(regulation_ticks=240, max_ticks=600)
    t.state.score["waza_ari"] = 1
    s.state.score["waza_ari"] = 1
    events: list = []
    m._check_regulation_end(tick=240, events=events)

    assert m.golden_score is True
    assert m.match_over is False
    starts = [e for e in events if e.event_type == "GOLDEN_SCORE_START"]
    assert len(starts) == 1
    assert starts[0].data["a_waza_ari"] == 1
    assert starts[0].data["b_waza_ari"] == 1


# ===========================================================================
# AC#3 — unequal waza-ari at regulation end → decision (no golden score)
# ===========================================================================
def test_regulation_end_unequal_waza_ari_resolves_by_decision() -> None:
    t, s, m = _match(regulation_ticks=240, max_ticks=600)
    t.state.score["waza_ari"] = 1
    s.state.score["waza_ari"] = 0
    events: list = []
    m._check_regulation_end(tick=240, events=events)

    assert m.golden_score is False
    assert m.match_over is True
    assert m.winner is t
    assert m.win_method == "decision"

    ended = [e for e in events if e.event_type == "MATCH_ENDED"]
    assert len(ended) == 1
    payload = ended[0].data
    assert payload["winner"] == t.identity.name
    assert payload["method"] == "decision"
    assert payload["tick"] == 240
    assert payload["golden_score"] is False
    assert payload["a_waza_ari"] == 1
    assert payload["b_waza_ari"] == 0


def test_regulation_end_unequal_waza_ari_other_side() -> None:
    """Symmetry: trailing fighter doesn't accidentally win the decision."""
    t, s, m = _match(regulation_ticks=240, max_ticks=600)
    t.state.score["waza_ari"] = 0
    s.state.score["waza_ari"] = 1
    events: list = []
    m._check_regulation_end(tick=240, events=events)

    assert m.match_over is True
    assert m.winner is s
    assert m.win_method == "decision"


# ===========================================================================
# AC#4 — waza-ari scored 30s into golden score ends the match
# ===========================================================================
def test_waza_ari_in_golden_score_ends_match() -> None:
    t, s, m = _match(regulation_ticks=240, max_ticks=600)
    # Simulate already in golden score.
    m.golden_score = True
    m.golden_score_start_tick = 240
    score_tick = 240 + 30  # 30 seconds in
    events = _force_waza_ari(t, s, m, ThrowID.UCHI_MATA, tick=score_tick)

    assert m.match_over is True
    assert m.winner is t
    assert m.win_method == "waza-ari (golden score)"
    # Tori has exactly one waza-ari — sudden death, not "two waza-ari".
    assert t.state.score["waza_ari"] == 1

    ended = [e for e in events if e.event_type == "MATCH_ENDED"]
    assert len(ended) == 1
    payload = ended[0].data
    assert payload["winner"] == t.identity.name
    assert payload["method"] == "waza-ari (golden score)"
    assert payload["tick"] == score_tick
    assert payload["golden_score"] is True
    assert payload["a_waza_ari"] == 1
    assert payload["b_waza_ari"] == 0


# ===========================================================================
# AC#5 — third shido in golden score ends the match for the opponent
# ===========================================================================
def test_third_shido_in_golden_score_ends_match_for_opponent() -> None:
    """Match 5 Shavdatuashvili vs. Heydarov case: shidos accumulate from
    regulation into golden score; the third shido (whenever it lands) ends
    the match with the opponent as winner by hansoku-make."""
    t, s, m = _match(regulation_ticks=240, max_ticks=600)
    # Tori arrives in golden score already on 2 shidos from regulation.
    t.state.shidos = 2
    m.golden_score = True
    m.golden_score_start_tick = 240
    # Fire a third passivity shido against tori in golden score.
    score_tick = 240 + 45
    events: list = []
    # Drive the passivity update; mock the referee call so it returns a shido.
    from referee import ShidoCall
    real = m.referee.update_passivity
    m.referee.update_passivity = lambda name, active, tick: (
        ShidoCall(fighter_id=name, reason="passivity", tick=tick)
        if name == t.identity.name else None
    )
    try:
        m._update_passivity(tick=score_tick, events=events)
    finally:
        m.referee.update_passivity = real

    # HAJ-235 — passivity detection now queues the penalty; the award
    # (and the third-shido hansoku-make) lands in the matte→shido→hajime
    # ceremony resolved from _post_tick.
    assert m._pending_penalty is not None
    m._award_pending_penalty(tick=score_tick, events=events)

    assert t.state.shidos == 3
    assert m.match_over is True
    assert m.winner is s
    assert m.win_method == "hansoku-make"

    ended = [e for e in events if e.event_type == "MATCH_ENDED"]
    assert len(ended) == 1
    payload = ended[0].data
    assert payload["winner"] == s.identity.name
    assert payload["method"] == "hansoku-make"
    assert payload["tick"] == score_tick
    assert payload["golden_score"] is True
    assert payload["a_shidos"] == 3


# ===========================================================================
# AC#6 — MATCH_ENDED payload also fires for regulation-time ippon
# ===========================================================================
def test_ippon_in_regulation_emits_match_ended_event() -> None:
    """Sanity check that the unified MATCH_ENDED event also fires for
    non-golden-score endings — this is what every consumer must hook off."""
    t, s, m = _match(regulation_ticks=240, max_ticks=240)
    m.position = Position.GRIPPING
    _seat_grips(m, t, s)
    real = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: ("IPPON", 4.0)
    try:
        events = m._apply_throw_result(
            attacker=t, defender=s, throw_id=ThrowID.UCHI_MATA,
            outcome="IPPON", net=4.0, window_quality=1.0, tick=42,
            execution_quality=1.0,
        )
    finally:
        match_module.resolve_throw = real

    assert m.match_over is True
    assert m.winner is t
    assert m.win_method == "ippon"

    ended = [e for e in events if e.event_type == "MATCH_ENDED"]
    assert len(ended) == 1
    payload = ended[0].data
    assert payload["winner"] == t.identity.name
    assert payload["method"] == "ippon"
    assert payload["tick"] == 42
    assert payload["golden_score"] is False


# ===========================================================================
# Integration — _check_regulation_end fires from _post_tick at the boundary
# ===========================================================================
def test_post_tick_invokes_regulation_end_check_at_boundary() -> None:
    """The wiring: _post_tick calls _check_regulation_end once tick crosses
    regulation_ticks. We confirm the flag flips by stepping the match
    forward to the boundary with an empty consequence load."""
    t, s, m = _match(regulation_ticks=5, max_ticks=200)
    # Suppress event printing noise.
    m._print_events = lambda evs: None
    m._print_header = lambda: None
    m.begin()
    while m.ticks_run < 5 and not m.is_done():
        m.step()
    # After tick 5 (the regulation boundary), golden score is on AND no
    # MATCH_ENDED has fired (waza-ari counts are still equal at 0-0).
    assert m.golden_score is True
    assert m.match_over is False
    # is_done stays False until match_over (max_ticks=200 still ahead).
    assert not m.is_done()


def test_end_match_is_idempotent() -> None:
    """First-writer-wins: a second _end_match call after match_over does
    nothing. Guards against double MATCH_ENDED emission when two paths
    happen to land on the same tick."""
    t, s, m = _match(regulation_ticks=240, max_ticks=600)
    events: list = []
    m._end_match(t, "ippon", tick=10, events=events)
    m._end_match(s, "hansoku-make", tick=10, events=events)
    assert m.winner is t
    assert m.win_method == "ippon"
    ended = [e for e in events if e.event_type == "MATCH_ENDED"]
    assert len(ended) == 1
