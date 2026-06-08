# tests/test_passivity_during_throw.py
# Verifies HAJ-43: kumi-kata and unconventional-grip clocks pause for any
# fighter with a throw in progress. A passivity shido during an active
# commit is incoherent — the fighter IS attacking.

from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from body_state import place_judoka
from enums import BodyPart, GripTarget, GripTypeV2, GripDepth
from grip_graph import GripEdge
from match import Match, KUMI_KATA_SHIDO_TICKS, UNCONVENTIONAL_SHIDO_TICKS, _ThrowInProgress
from referee import build_suzuki
from skill_compression import SubEvent
from throws import ThrowID
import main as main_module


def _pair_match():
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())
    return t, s, m


def _seat_edge(m, owner, target):
    m.grip_graph.add_edge(GripEdge(
        grasper_id=owner.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=target.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.STANDARD,
        strength=0.8, established_tick=0,
    ))


def _stash_throw(m, attacker, defender, throw_id=ThrowID.SEOI_NAGE):
    m._throws_in_progress[attacker.identity.name] = _ThrowInProgress(
        attacker_name=attacker.identity.name,
        defender_name=defender.identity.name,
        throw_id=throw_id, start_tick=0, compression_n=5,
        schedule={}, commit_actual=0.7,
    )


# ---------------------------------------------------------------------------
# Kumi-kata clock — primary HAJ-43 fix
# ---------------------------------------------------------------------------
def test_kumi_kata_clock_pauses_during_in_progress_throw() -> None:
    """A grip-holding fighter mid-throw doesn't accrue passivity ticks.
    Drive enough ticks past KUMI_KATA_SHIDO_TICKS to be sure: no shido."""
    t, s, m = _pair_match()
    _seat_edge(m, t, s)
    _stash_throw(m, t, s)

    pre_clock = m.kumi_kata_clock[t.identity.name] = 25  # near the threshold
    before_shidos = t.state.shidos
    events: list = []
    for tick in range(1, KUMI_KATA_SHIDO_TICKS + 10):
        m._update_grip_passivity(tick, events)
    # Clock paused at its pre-throw value, no shido fired.
    assert m.kumi_kata_clock[t.identity.name] == pre_clock
    assert t.state.shidos == before_shidos
    assert not any(e.event_type == "SHIDO_AWARDED" for e in events)


def test_kumi_kata_clock_advances_for_other_fighter() -> None:
    """Pause only applies to the fighter mid-throw. The opponent's clock
    advances normally."""
    t, s, m = _pair_match()
    _seat_edge(m, t, s)
    _seat_edge(m, s, t)
    _stash_throw(m, t, s)   # only t is mid-throw

    events: list = []
    for tick in range(1, 6):
        m._update_grip_passivity(tick, events)
    assert m.kumi_kata_clock[t.identity.name] == 0   # paused at start value
    assert m.kumi_kata_clock[s.identity.name] == 5   # ticked normally


def test_kumi_kata_clock_resumes_after_throw_resolves() -> None:
    """Once the in-progress tip is removed, the clock should advance again."""
    t, s, m = _pair_match()
    _seat_edge(m, t, s)
    _stash_throw(m, t, s)
    m.kumi_kata_clock[t.identity.name] = 20

    events: list = []
    m._update_grip_passivity(tick=1, events=events)
    assert m.kumi_kata_clock[t.identity.name] == 20   # paused

    # Throw resolves.
    del m._throws_in_progress[t.identity.name]
    m._update_grip_passivity(tick=2, events=events)
    assert m.kumi_kata_clock[t.identity.name] == 21   # ticking again


# ---------------------------------------------------------------------------
# Unconventional-grip clock — same rule applies
# ---------------------------------------------------------------------------
def test_unconventional_shido_does_not_fire_during_throw() -> None:
    """Unconventional grips are penalized when held without attack — but
    a fighter mid-commit IS attacking. No shido while the tip is live."""
    t, s, m = _pair_match()
    pistol = GripEdge(
        grasper_id=t.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=s.identity.name, target_location=GripTarget.RIGHT_SLEEVE,
        grip_type_v2=GripTypeV2.PISTOL, depth_level=GripDepth.STANDARD,
        strength=0.8, established_tick=0,
        unconventional_clock=UNCONVENTIONAL_SHIDO_TICKS,
    )
    m.grip_graph.add_edge(pistol)
    _stash_throw(m, t, s)

    before = t.state.shidos
    events: list = []
    m._update_grip_passivity(tick=1, events=events)
    assert t.state.shidos == before
    # The clock isn't reset either — the unconventional grip's countdown
    # picks up where it left off when the throw ends.
    assert pistol.unconventional_clock == UNCONVENTIONAL_SHIDO_TICKS


# ---------------------------------------------------------------------------
# Regression: existing behavior unchanged when no throw is in flight
# ---------------------------------------------------------------------------
def test_kumi_kata_shido_still_fires_outside_a_throw() -> None:
    """The pre-existing path still works: a fighter sitting on grips
    without attacking eats the passivity shido at KUMI_KATA_SHIDO_TICKS."""
    t, s, m = _pair_match()
    _seat_edge(m, t, s)
    # No tip stashed.

    events: list = []
    for tick in range(1, KUMI_KATA_SHIDO_TICKS + 2):
        m._update_grip_passivity(tick, events)
    # HAJ-235 — detection queues the penalty; resolving it emits the shido.
    assert m._pending_penalty is not None
    m._award_pending_penalty(tick, events)
    assert any(e.event_type == "SHIDO_AWARDED" for e in events)
