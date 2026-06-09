# tests/test_dynamic_stance.py
# HAJ-232 Phase 1 — dynamic stance state, belt-gated comfort vector, the
# hybrid switch cost, and the per-tick switch decision (tactical +
# grip-pressure-forced) with its STANCE_CHANGE narration thread.

from __future__ import annotations
import io
import os
import sys
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from body_state import place_judoka
from enums import BeltRank, Stance, StanceMatchup
from referee import build_suzuki
import main as main_module
import stance as stance_mod
from stance import (
    AXIS_KENKA_YOTSU, AXIS_ORTHODOX, AXIS_SOUTHPAW,
    StanceSwitchDecision, axis_key, comfort_for_stance, evaluate_switch,
    flip_stance, initial_stance_comfort, stance_initiative_penalty,
)


def _pair():
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    return t, s


class _FakeRng:
    """Deterministic stand-in for random.Random — returns a fixed value."""
    def __init__(self, value: float) -> None:
        self._value = value

    def random(self) -> float:
        return self._value


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def test_flip_and_axis_key() -> None:
    assert flip_stance(Stance.ORTHODOX) == Stance.SOUTHPAW
    assert flip_stance(Stance.SOUTHPAW) == Stance.ORTHODOX
    assert axis_key(Stance.ORTHODOX) == AXIS_ORTHODOX
    assert axis_key(Stance.SOUTHPAW) == AXIS_SOUTHPAW


# ---------------------------------------------------------------------------
# Belt-gated initial comfort vector (§3.3)
# ---------------------------------------------------------------------------
def test_initial_comfort_belt_gated() -> None:
    t, _ = _pair()
    ident = t.identity

    # White belt: comfortable in base stance, near-helpless off it / inside.
    ident.belt_rank = BeltRank.WHITE
    ident.stance_matchup_comfort = {}
    white = initial_stance_comfort(ident, Stance.ORTHODOX)
    assert white[AXIS_ORTHODOX] > 0.8
    assert white[AXIS_SOUTHPAW] < 0.15
    assert white[AXIS_KENKA_YOTSU] < 0.2

    # Black belt: has paid the tuition — fluent off-stance and inside.
    ident.belt_rank = BeltRank.BLACK_5
    black = initial_stance_comfort(ident, Stance.ORTHODOX)
    assert black[AXIS_SOUTHPAW] > white[AXIS_SOUTHPAW]
    assert black[AXIS_KENKA_YOTSU] > 0.6


def test_base_stance_axis_follows_base_stance() -> None:
    t, _ = _pair()
    ident = t.identity
    ident.belt_rank = BeltRank.GREEN
    ident.stance_matchup_comfort = {}
    c = initial_stance_comfort(ident, Stance.SOUTHPAW)
    # Southpaw is now the *base* axis, so it should be the high one.
    assert c[AXIS_SOUTHPAW] > c[AXIS_ORTHODOX]


def test_identity_override_wins() -> None:
    t, _ = _pair()
    ident = t.identity
    ident.belt_rank = BeltRank.WHITE
    ident.stance_matchup_comfort = {AXIS_KENKA_YOTSU: 0.95}
    c = initial_stance_comfort(ident, Stance.ORTHODOX)
    assert c[AXIS_KENKA_YOTSU] == 0.95


def test_comfort_for_stance_defaults_to_one_when_unset() -> None:
    # Stance-static fighter (empty vector) reads as fully comfortable.
    t, _ = _pair()
    t.state.stance_comfort = {}
    assert comfort_for_stance(t.state, Stance.SOUTHPAW) == 1.0


# ---------------------------------------------------------------------------
# Hybrid switch cost (§6.2)
# ---------------------------------------------------------------------------
def test_penalty_zero_for_stance_static_fighter() -> None:
    t, _ = _pair()
    t.state.stance_comfort = {}
    t.state.stance_settling_ticks = 4
    assert stance_initiative_penalty(t, StanceMatchup.MATCHED) == 0.0


def test_settling_window_adds_penalty() -> None:
    t, _ = _pair()
    t.state.stance_comfort = {AXIS_ORTHODOX: 1.0, AXIS_SOUTHPAW: 1.0,
                              AXIS_KENKA_YOTSU: 1.0}
    t.state.current_stance = Stance.ORTHODOX
    settled = stance_initiative_penalty(t, StanceMatchup.MATCHED)
    t.state.stance_settling_ticks = 4
    settling = stance_initiative_penalty(t, StanceMatchup.MATCHED)
    assert settled == 0.0
    assert settling > settled


def test_low_comfort_and_kenka_add_penalty() -> None:
    t, _ = _pair()
    t.state.stance_comfort = {AXIS_ORTHODOX: 0.2, AXIS_SOUTHPAW: 0.2,
                              AXIS_KENKA_YOTSU: 0.2}
    t.state.current_stance = Stance.ORTHODOX
    t.state.stance_settling_ticks = 0
    matched = stance_initiative_penalty(t, StanceMatchup.MATCHED)
    mirrored = stance_initiative_penalty(t, StanceMatchup.MIRRORED)
    assert matched > 0.0                 # off-comfort term
    assert mirrored > matched            # plus the kenka-yotsu term


# ---------------------------------------------------------------------------
# Switch decision (§6.1)
# ---------------------------------------------------------------------------
def test_no_switch_when_stance_static() -> None:
    t, s = _pair()
    t.state.stance_comfort = {}
    assert evaluate_switch(
        t, s, matchup=StanceMatchup.MATCHED,
        grip_delta_against=5.0, rng=_FakeRng(0.0),
    ) is None


def test_no_switch_while_settling() -> None:
    t, s = _pair()
    t.state.stance_settling_ticks = 3
    assert evaluate_switch(
        t, s, matchup=StanceMatchup.MATCHED,
        grip_delta_against=5.0, rng=_FakeRng(0.0),
    ) is None


def test_forced_switch_under_grip_pressure() -> None:
    t, s = _pair()
    decision = evaluate_switch(
        t, s, matchup=StanceMatchup.MATCHED,
        grip_delta_against=5.0,          # being dominated in the grip war
        rng=_FakeRng(0.0),               # roll always succeeds
    )
    assert decision is not None
    assert decision.reason == "grip_pressure"
    assert decision.target == flip_stance(t.state.current_stance)


def test_no_forced_switch_below_threshold() -> None:
    t, s = _pair()
    # No grip pressure and a non-kenka-hunter comfort profile → hold stance.
    t.state.stance_comfort = {AXIS_ORTHODOX: 0.9, AXIS_SOUTHPAW: 0.9,
                              AXIS_KENKA_YOTSU: 0.3}
    assert evaluate_switch(
        t, s, matchup=StanceMatchup.MATCHED,
        grip_delta_against=0.0, rng=_FakeRng(0.0),
    ) is None


def test_tactical_switch_for_kenka_hunter() -> None:
    t, s = _pair()
    # A kenka-yotsu hunter: high inside comfort, fluent in both stances.
    t.state.stance_comfort = {AXIS_ORTHODOX: 0.9, AXIS_SOUTHPAW: 0.9,
                              AXIS_KENKA_YOTSU: 0.95}
    decision = evaluate_switch(
        t, s, matchup=StanceMatchup.MATCHED,   # they want MIRRORED
        grip_delta_against=0.0,                # no pressure; purely tactical
        rng=_FakeRng(0.0),
    )
    assert decision is not None
    assert decision.reason == "tactical"


# ---------------------------------------------------------------------------
# Match integration — apply + narration thread
# ---------------------------------------------------------------------------
def _match():
    from match import Match
    t, s = _pair()
    return Match(fighter_a=t, fighter_b=s, referee=build_suzuki(),
                 max_ticks=50, seed=1), t, s


def test_apply_stance_switch_flips_and_opens_window() -> None:
    m, t, _ = _match()
    assert t.state.current_stance == Stance.ORTHODOX
    events: list = []
    m._apply_stance_switch(
        t, StanceSwitchDecision(target=Stance.SOUTHPAW, reason="tactical"),
        tick=7, events=events,
    )
    assert t.state.current_stance == Stance.SOUTHPAW
    assert t.state.stance_settling_ticks == stance_mod.STANCE_SETTLING_TICKS
    assert len(events) == 1
    ev = events[0]
    assert ev.event_type == "STANCE_CHANGE"
    assert ev.data["reason"] == "tactical"
    assert ev.data["new_stance"] == "SOUTHPAW"
    assert ev.data["matchup_after"] == "MIRRORED"
    assert ev.data["coach_prose"]           # mat-side prose present
    assert "[stance]" in ev.description


def test_live_matchup_recomputes_after_switch() -> None:
    m, t, s = _match()
    assert m._compute_stance_matchup() == StanceMatchup.MATCHED
    m._apply_stance_switch(
        t, StanceSwitchDecision(target=Stance.SOUTHPAW, reason="grip_pressure"),
        tick=3, events=[],
    )
    assert m._compute_stance_matchup() == StanceMatchup.MIRRORED


def test_settling_window_decays_each_tick() -> None:
    m, t, _ = _match()
    t.state.stance_settling_ticks = 2
    m._decay_stance_settling(t)
    assert t.state.stance_settling_ticks == 1
    m._decay_stance_settling(t)
    assert t.state.stance_settling_ticks == 0
    m._decay_stance_settling(t)   # floors at 0
    assert t.state.stance_settling_ticks == 0


def test_full_match_runs_clean_with_dynamic_stance() -> None:
    # Smoke: a full match still runs end-to-end with stance evaluation wired
    # into the tick loop, and the opening header still prints the matchup.
    m, _, _ = _match()
    buf = io.StringIO()
    with redirect_stdout(buf):
        m.run()
    out = buf.getvalue()
    assert "Stance matchup:" in out
