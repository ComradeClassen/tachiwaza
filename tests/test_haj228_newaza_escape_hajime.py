# tests/test_haj228_newaza_escape_hajime.py
# HAJ-228 — Restart-Hajime not emitted after ne-waza escape-to-standing.
#
# From the 2026-06-04 match-log triage (Cluster 2.2, t013): a ne-waza
# escape resets the fighters to standing and the narrator emits the
# ne_waza→closing phase line "Matte — they're back on their feet", but no
# Hajime! followed because the escape reset bypassed the matte/hajime
# scheduler.
#
# Acceptance:
#   A ne-waza-escape reset to standing emits a Hajime! restart line after
#   the pause, same as other Matte paths — while preserving HAJ-152 AC#7
#   (no POST_SCORE_FOLLOW_UP_MATTE consequence fires on the chase-escape).

from __future__ import annotations
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from body_state import place_judoka
from enums import SubLoopState, Position
from match import Match, MATTE_TO_HAJIME_PAUSE_TICKS, _ThrowInProgress
from referee import build_suzuki
from throws import ThrowID
import main as main_module


def _pair():
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    return t, s


def _headless(seed: int, max_ticks: int = 600):
    random.seed(seed)
    t, s = _pair()
    m = Match(t, s, build_suzuki(), max_ticks=max_ticks, seed=seed)
    events: list = []
    m._print_events = lambda evs: events.extend(evs)
    m._print_header = lambda: None
    m.run()
    return m, events


# ===========================================================================
# Unit — the shared reset helper schedules the restart hajime
# ===========================================================================
def test_reset_after_newaza_schedules_restart_hajime() -> None:
    """_reset_to_standing_after_newaza seats the dyad at STANDING_DISTANT
    AND schedules the restart Hajime PAUSE ticks out — the wiring HAJ-228
    was missing."""
    t, s = _pair()
    m = Match(t, s, build_suzuki(), seed=1)
    # Pretend we're mid-ground with a parked standing throw and an open
    # post-score follow-up window — all of which the reset must clear.
    m.sub_loop_state = SubLoopState.NE_WAZA
    m._post_score_follow_up = {"stage": "NE_WAZA", "reason": "chase"}
    m._throws_in_progress[t.identity.name] = _ThrowInProgress(
        attacker_name=t.identity.name, defender_name=s.identity.name,
        throw_id=ThrowID.UCHI_MATA, start_tick=10, compression_n=1,
        schedule={}, commit_actual=0.5,
    )

    m._reset_to_standing_after_newaza(tick=20)

    assert m.sub_loop_state == SubLoopState.STANDING
    assert m.position == Position.STANDING_DISTANT
    assert not m._throws_in_progress
    assert m._post_score_follow_up is None
    # The restart hajime is scheduled — the HAJ-228 fix.
    assert m._pending_hajime_tick == 20 + MATTE_TO_HAJIME_PAUSE_TICKS


def test_reset_after_newaza_queues_no_post_score_matte() -> None:
    """HAJ-152 AC#7 preserved: the chase-escape reset does not queue a
    POST_SCORE_FOLLOW_UP_MATTE consequence — the restart Hajime is the
    symmetric beat for the 'back on their feet' line, not a post-score-end
    matte."""
    t, s = _pair()
    m = Match(t, s, build_suzuki(), seed=1)
    m.sub_loop_state = SubLoopState.NE_WAZA
    m._post_score_follow_up = {"stage": "NE_WAZA", "reason": "chase"}
    m._reset_to_standing_after_newaza(tick=20)
    queued = [c for c in m._consequence_queue
              if c.kind == "POST_SCORE_FOLLOW_UP_MATTE"]
    assert not queued


# ===========================================================================
# Integration — a real ne-waza escape emits a following Hajime
# ===========================================================================
def test_escape_to_standing_emits_restart_hajime_seed0() -> None:
    """Deterministic regression: seed 0 produces a ne-waza escape at t25;
    a Hajime! must fire at t25 + PAUSE (the match runs well past, so the
    restart is observable)."""
    m, events = _headless(seed=0)
    escapes = [e for e in events if e.event_type == "ESCAPE_SUCCESS"]
    hajimes = {e.tick for e in events if e.event_type == "HAJIME_CALLED"}
    assert escapes, "seed 0 should produce a ne-waza escape"
    for esc in escapes:
        assert esc.tick + MATTE_TO_HAJIME_PAUSE_TICKS in hajimes, (
            f"no restart Hajime at t{esc.tick + MATTE_TO_HAJIME_PAUSE_TICKS} "
            f"after escape at t{esc.tick}"
        )


def test_every_newaza_escape_schedules_hajime_seeded() -> None:
    """Across a seed battery, every ESCAPE_SUCCESS / SUBMISSION_RELEASED
    reset is followed by a restart Hajime at +PAUSE — unless the match
    ended during the pause (a submission/score on the escape tick, or the
    clock running out), in which case there is nothing to restart."""
    seen_escape = False
    for seed in range(0, 25):
        m, events = _headless(seed)
        hajimes = {e.tick for e in events if e.event_type == "HAJIME_CALLED"}
        for e in events:
            if e.event_type not in ("ESCAPE_SUCCESS", "SUBMISSION_RELEASED"):
                continue
            seen_escape = True
            expected = e.tick + MATTE_TO_HAJIME_PAUSE_TICKS
            if m.match_over and m.ticks_run < expected:
                continue  # match ended inside the pause — no restart due
            assert expected in hajimes, (
                f"seed={seed}: {e.event_type} at t{e.tick} has no restart "
                f"Hajime at t{expected}"
            )
    assert seen_escape, "no seed produced a ne-waza escape to test"
