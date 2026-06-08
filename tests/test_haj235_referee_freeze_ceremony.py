# tests/test_haj235_referee_freeze_ceremony.py
# HAJ-235 — Referee freeze + ceremony.
#
# Part 1 — no fighter action on ticks strictly between a Matte and its
#          following Hajime (the matte→hajime pause is a render beat, not
#          live wrestling time).
# Part 2 — a passivity / non-combativity shido is bracketed as a real-judo
#          ceremony: matte → shido announcement → hajime restart.
#
# Acceptance criteria:
#   1. No fighter action (move/grip/throw staging) on ticks strictly
#      between a matte and its following hajime.
#   2. A passivity/penalty shido is bracketed: matte → shido → hajime.
#   3. Existing matte reasons (stuffed-throw reset, ne-waza patience) still
#      emit a following hajime.
#   4. Seeded regression confirms no [move]/grip events land in any
#      matte→hajime gap.

from __future__ import annotations
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from body_state import place_judoka
from enums import BodyPart, GripTarget, GripTypeV2, GripDepth, MatteReason
from grip_graph import GripEdge
from match import (
    Match, KUMI_KATA_SHIDO_TICKS, MATTE_TO_HAJIME_PAUSE_TICKS,
)
from referee import build_suzuki
import main as main_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
# Event types / description tags that represent a fighter ACTING (moving,
# gripping, or staging a throw). None of these may land in a matte→hajime gap.
_ACTION_EVENT_TYPES = frozenset({
    "MOVE", "THROW_ENTRY", "THROW_DRIVE", "COUNTER_COMMIT",
})


def _is_fighter_action(ev) -> bool:
    desc = ev.description or ""
    return (
        ev.event_type.startswith("GRIP")
        or ev.event_type in _ACTION_EVENT_TYPES
        or "[move]" in desc
        or "[grip]" in desc
    )


def _pair():
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    return t, s


def _headless(seed: int, max_ticks: int = 400):
    """Run a seeded match headless, capturing every emitted event and the
    exact set of ticks the freeze gate fired on."""
    random.seed(seed)
    t, s = _pair()
    m = Match(t, s, build_suzuki(), max_ticks=max_ticks, seed=seed)
    events: list = []
    freeze_ticks: set = set()
    m._print_events = lambda evs: events.extend(evs)
    m._print_header = lambda: None
    orig_tick = m._tick

    def traced_tick(tick: int) -> None:
        # A tick is frozen iff, at its start, a hajime is pending and we
        # have not yet reached it — exactly the freeze gate's predicate.
        if (m._pending_hajime_tick is not None
                and tick < m._pending_hajime_tick):
            freeze_ticks.add(tick)
        return orig_tick(tick)

    m._tick = traced_tick
    m.run()
    return t, s, m, events, freeze_ticks


def _seat_edge(m, owner, target):
    m.grip_graph.add_edge(GripEdge(
        grasper_id=owner.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=target.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.STANDARD,
        strength=0.8, established_tick=0,
    ))


# ===========================================================================
# Part 1 / AC#1 + AC#4 — freeze: no fighter action in the matte→hajime gap
# ===========================================================================
SEEDS = (1081968535, 1, 7, 1974183401, 2, 3, 99, 123, 2024, 888, 17, 4, 5, 6)


def test_no_fighter_action_on_any_freeze_tick_seeded() -> None:
    """AC#4 — across a battery of seeds (including the post-223 review seed
    1081968535), no move / grip / throw-staging event lands on any tick
    strictly between a matte and its paired hajime."""
    saw_any_freeze = False
    for seed in SEEDS:
        _t, _s, _m, events, freeze = _headless(seed)
        saw_any_freeze = saw_any_freeze or bool(freeze)
        offenders = [
            (ev.tick, ev.event_type, ev.description)
            for ev in events
            if ev.tick in freeze and _is_fighter_action(ev)
        ]
        assert not offenders, (
            f"seed={seed} leaked fighter action into the matte→hajime "
            f"freeze: {offenders[:5]}"
        )
    # Guard against a vacuous pass — at least one seed must exercise a freeze.
    assert saw_any_freeze, "no seed produced a matte→hajime pause to test"


def test_freeze_window_spans_matte_plus_one_to_hajime_minus_one() -> None:
    """The freeze fires on exactly the ticks strictly between the matte and
    its hajime: matte+1 .. matte+PAUSE-1."""
    t, s = _pair()
    m = Match(t, s, build_suzuki(), max_ticks=60, seed=1)
    m._print_events = lambda evs: None
    m._print_header = lambda: None
    m.begin()
    matte_tick = 10
    m._handle_matte(tick=matte_tick)
    frozen = []
    for nxt in range(matte_tick + 1, matte_tick + MATTE_TO_HAJIME_PAUSE_TICKS + 1):
        m.ticks_run = nxt - 1
        if (m._pending_hajime_tick is not None
                and nxt < m._pending_hajime_tick):
            frozen.append(nxt)
        m.step()
    expected = list(range(matte_tick + 1, matte_tick + MATTE_TO_HAJIME_PAUSE_TICKS))
    assert frozen == expected


def test_no_action_events_during_manual_matte_pause() -> None:
    """After a forced matte, stepping through the pause emits no move/grip
    events until hajime; the hajime tick (matte+PAUSE) is NOT frozen."""
    t, s = _pair()
    m = Match(t, s, build_suzuki(), max_ticks=80, seed=3)
    captured: list = []
    m._print_events = lambda evs: captured.extend(evs)
    m._print_header = lambda: None
    m.begin()
    matte_tick = 12
    m._handle_matte(tick=matte_tick)
    hajime_tick = matte_tick + MATTE_TO_HAJIME_PAUSE_TICKS
    captured.clear()
    for nxt in range(matte_tick + 1, hajime_tick + 1):
        m.ticks_run = nxt - 1
        m.step()
    gap = set(range(matte_tick + 1, hajime_tick))
    leaked = [e for e in captured if e.tick in gap and _is_fighter_action(e)]
    assert not leaked, f"action leaked into pause: {[(e.tick, e.event_type) for e in leaked]}"
    hajimes = [e for e in captured if e.event_type == "HAJIME_CALLED"]
    assert [h.tick for h in hajimes] == [hajime_tick]


# ===========================================================================
# Part 2 / AC#2 — passivity shido is bracketed matte → shido → hajime
# ===========================================================================
def _force_passivity_tick(m, owner, target, tick: int):
    """Drive a kumi-kata passivity penalty on `owner` this tick and run the
    post-tick ceremony, returning the emitted events in order."""
    _seat_edge(m, owner, target)
    # One short of threshold; the detection tick takes it over.
    m.kumi_kata_clock[owner.identity.name] = KUMI_KATA_SHIDO_TICKS - 1
    events: list = []
    m._update_grip_passivity(tick, events)   # detection → queue
    m._post_tick(tick, events)               # ceremony resolves here
    return events


def test_passivity_shido_brackets_matte_then_shido_then_hajime() -> None:
    """AC#2 — the shido is announced inside a matte stoppage, and a hajime
    restart is queued for after the pause."""
    t, s = _pair()
    m = Match(t, s, build_suzuki(), max_ticks=200, seed=5)
    m._print_events = lambda evs: None
    m._print_header = lambda: None
    tick = 40
    events = _force_passivity_tick(m, t, s, tick)

    types = [e.event_type for e in events]
    assert "MATTE_CALLED" in types
    assert "SHIDO_AWARDED" in types
    matte_i = types.index("MATTE_CALLED")
    shido_i = types.index("SHIDO_AWARDED")
    # Matte stops the action BEFORE the penalty is announced.
    assert matte_i < shido_i
    # The matte that brackets the penalty carries the PENALTY reason.
    assert events[matte_i].data.get("reason") == MatteReason.PENALTY.name
    # The shido landed on the penalised fighter.
    assert t.state.shidos == 1
    # And the restart hajime is queued for after the freeze (Part 1 path).
    assert m._pending_hajime_tick == tick + MATTE_TO_HAJIME_PAUSE_TICKS


def test_passivity_detection_defers_award_not_inline() -> None:
    """Detection alone queues the penalty — it no longer emits the shido
    inline. The award is the responsibility of the post-tick ceremony."""
    t, s = _pair()
    m = Match(t, s, build_suzuki(), max_ticks=200, seed=5)
    _seat_edge(m, t, s)
    m.kumi_kata_clock[t.identity.name] = KUMI_KATA_SHIDO_TICKS - 1
    events: list = []
    m._update_grip_passivity(40, events)
    assert m._pending_penalty is not None
    assert t.state.shidos == 0
    assert not any(e.event_type == "SHIDO_AWARDED" for e in events)


def test_third_passivity_shido_is_hansoku_make_no_restart() -> None:
    """A third shido ends the match by hansoku-make; no hajime restart is
    queued because there is nothing to restart."""
    t, s = _pair()
    m = Match(t, s, build_suzuki(), max_ticks=200, seed=5)
    t.state.shidos = 2
    tick = 50
    events = _force_passivity_tick(m, t, s, tick)
    assert t.state.shidos == 3
    assert m.match_over is True
    assert m.winner is s
    assert m.win_method == "hansoku-make"
    # No restart after a match-ending penalty.
    assert m._pending_hajime_tick is None
    assert any(e.event_type == "MATCH_ENDED" for e in events)


def test_penalty_matte_reason_renders() -> None:
    """The referee renders the PENALTY matte reason as human text."""
    ref = build_suzuki()
    ev = ref.announce_matte(MatteReason.PENALTY, tick=0)
    assert ev.event_type == "MATTE_CALLED"
    assert ev.data["reason"] == "PENALTY"
    assert "penalty" in ev.description.lower()


# ===========================================================================
# AC#3 — existing matte reasons still emit a following hajime
# ===========================================================================
def test_every_handle_matte_queues_a_following_hajime_seeded() -> None:
    """For every matte routed through _handle_matte (stuffed-throw reset,
    ne-waza patience, OOB, penalty), a hajime fires PAUSE ticks later. The
    post-score follow-up matte is the one reset that intentionally keeps its
    own (non-freezing) path, so it is excluded here."""
    for seed in SEEDS:
        _t, _s, _m, events, _freeze = _headless(seed)
        hajime_ticks = {e.tick for e in events if e.event_type == "HAJIME_CALLED"}
        for e in events:
            if e.event_type != "MATTE_CALLED":
                continue
            if e.data.get("reason") == MatteReason.POST_SCORE_FOLLOW_UP_END.name:
                continue
            expected = e.tick + MATTE_TO_HAJIME_PAUSE_TICKS
            assert expected in hajime_ticks, (
                f"seed={seed} matte ({e.data.get('reason')}) at t{e.tick} "
                f"has no hajime at t{expected}"
            )
