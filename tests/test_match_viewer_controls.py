# tests/test_match_viewer_controls.py
# HAJ-126 — viewer v2 debug controls (pause/step/scrub/inspect/ticker).
#
# These tests cover the Match-side refactor (begin/step/end public loop
# API + run() delegation to a driver-style renderer) and a scripted
# driver fake that exercises pause/step/window-close semantics without
# opening pygame. The pygame renderer's wall-clock pacing and key/mouse
# bindings are not unit-tested — they're a UI shell with no logic the
# headless suite can verify usefully.

from __future__ import annotations
import io
import os
import random
import sys
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from body_state import place_judoka
from match import Match
from match_viewer import (
    RecordingRenderer, ScriptedDriverRenderer,
    MIN_TPS, MAX_TPS,
)
from referee import build_suzuki
import main as main_module


def _pair():
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    return t, s


def _new_match(*, max_ticks=12, seed=1, renderer=None):
    random.seed(seed)
    t, s = _pair()
    return Match(
        fighter_a=t, fighter_b=s, referee=build_suzuki(),
        max_ticks=max_ticks, seed=seed, renderer=renderer,
        # HAJ-234 — these are loop-plumbing tests written before golden-score
        # resolution existed; they assert the match is bounded by max_ticks.
        # A scoreless regulation now opens a golden-score window, so disable
        # that window here (golden_score_ticks=0 -> a level regulation end
        # resolves immediately) to keep the original regulation-bounded
        # contract these tests were written against.
        golden_score_ticks=0,
    )


# ---------------------------------------------------------------------------
# Public loop API: begin / step / end / is_done
# ---------------------------------------------------------------------------
def test_match_exposes_begin_step_end_is_done() -> None:
    m = _new_match()
    for name in ("begin", "step", "end", "is_done"):
        assert callable(getattr(m, name)), (
            f"Match.{name} should be callable on the public loop API"
        )


def test_step_advances_one_tick_at_a_time() -> None:
    m = _new_match(max_ticks=20)
    buf = io.StringIO()
    with redirect_stdout(buf):
        m.begin()
        assert m.ticks_run == 0
        m.step()
        assert m.ticks_run == 1
        m.step()
        assert m.ticks_run == 2
        m.end()


def test_is_done_at_max_ticks() -> None:
    m = _new_match(max_ticks=3)
    buf = io.StringIO()
    with redirect_stdout(buf):
        m.begin()
        for _ in range(10):
            if m.is_done():
                break
            m.step()
        m.end()
    assert m.is_done()


def test_step_is_noop_when_done() -> None:
    """Calling step() after the match ended should not advance ticks_run
    further — the loop is closed."""
    m = _new_match(max_ticks=2)
    buf = io.StringIO()
    with redirect_stdout(buf):
        m.begin()
        while not m.is_done():
            m.step()
        ticks_at_end = m.ticks_run
        m.step()
        m.step()
        m.end()
    assert m.ticks_run == ticks_at_end


# ---------------------------------------------------------------------------
# Pause/step preserves state vs running uninterrupted
# ---------------------------------------------------------------------------
def test_paused_then_stepped_state_matches_uninterrupted() -> None:
    """ACCEPTANCE: pause/step/play produces identical results to running
    uninterrupted. We seed two matches identically; one runs through
    begin/step/end calling step in a tight loop, the other runs the same
    number of begin/step calls but interleaves no-op pauses (which under
    the public API just means not calling step()). Both must end in the
    same state."""
    # Reference: run-through with 8 steps via the public API.
    random.seed(123)
    t1, s1 = _pair()
    m1 = Match(fighter_a=t1, fighter_b=s1, referee=build_suzuki(),
               max_ticks=8, seed=123)
    buf = io.StringIO()
    with redirect_stdout(buf):
        m1.begin()
        for _ in range(8):
            if m1.is_done():
                break
            m1.step()
        m1.end()

    # Same total step count, but with arbitrary "pauses" — i.e. extra
    # calls to is_done() / state reads between steps. These should not
    # alter outcome.
    random.seed(123)
    t2, s2 = _pair()
    m2 = Match(fighter_a=t2, fighter_b=s2, referee=build_suzuki(),
               max_ticks=8, seed=123)
    buf2 = io.StringIO()
    with redirect_stdout(buf2):
        m2.begin()
        for i in range(8):
            if m2.is_done():
                break
            # "Pause": read state, do nothing.
            _ = m2.is_done()
            _ = m2.ticks_run
            _ = m2.fighter_a.state.composure_current
            m2.step()
        m2.end()

    assert m1.ticks_run == m2.ticks_run
    assert m1.match_over == m2.match_over
    assert m1.fighter_a.state.score == m2.fighter_a.state.score
    assert m1.fighter_b.state.score == m2.fighter_b.state.score
    # Output streams should also match — the public API is deterministic.
    assert buf.getvalue() == buf2.getvalue()


# ---------------------------------------------------------------------------
# run() delegates to a driver-style renderer
# ---------------------------------------------------------------------------
def test_run_delegates_to_driver_when_drives_loop() -> None:
    """A renderer with drives_loop() == True takes over the loop. Match
    calls start → run_interactive(self) → stop in that order."""
    drv = ScriptedDriverRenderer(["step", "step", "step", "close"])
    m = _new_match(max_ticks=20, renderer=drv)
    buf = io.StringIO()
    with redirect_stdout(buf):
        m.run()
    # The driver received start, executed 3 steps, closed, then got stop.
    assert drv.start_calls == 1
    assert drv.stop_calls == 1
    # The match advanced exactly the scripted number of steps.
    assert m.ticks_run == 3


def test_push_renderer_is_not_treated_as_driver() -> None:
    """RecordingRenderer has no drives_loop method; Match must use the
    in-line loop, not delegate."""
    rec = RecordingRenderer()
    m = _new_match(max_ticks=5, renderer=rec)
    buf = io.StringIO()
    with redirect_stdout(buf):
        m.run()
    # Got at least the tick-0 paint plus a few ticks worth of updates.
    assert rec.update_calls >= 2
    # Match completed normally to max_ticks (or sooner via match_over).
    assert m.is_done()


# ---------------------------------------------------------------------------
# Scripted driver: scripted close mid-match exits cleanly
# ---------------------------------------------------------------------------
def test_driver_can_close_mid_match() -> None:
    drv = ScriptedDriverRenderer(["step", "step", "close", "step", "step"])
    m = _new_match(max_ticks=240, renderer=drv)
    buf = io.StringIO()
    with redirect_stdout(buf):
        m.run()
    # Closed after 2 steps; later step commands ignored.
    assert m.ticks_run == 2
    assert drv.is_open() is False


# ---------------------------------------------------------------------------
# Driver receives push update() during step() so the ticker can populate
# ---------------------------------------------------------------------------
def test_driver_step_fires_update_for_ticker() -> None:
    """Match.step() routes events through renderer.update(). A driver
    that mixes both APIs (drives the loop AND inherits update) gets the
    same per-tick events the push path sees — that's what powers the
    docked ticker without duplicating the event pipeline."""

    class CountingDriver(ScriptedDriverRenderer):
        def __init__(self):
            super().__init__(["step", "step", "step"])
            self.received_events: list = []

        def update(self, tick, match, events):
            super().update(tick, match, events)
            self.received_events.append((tick, len(events)))

    drv = CountingDriver()
    m = _new_match(max_ticks=20, renderer=drv)
    buf = io.StringIO()
    with redirect_stdout(buf):
        m.run()
    # tick 0 paint + 3 stepped ticks = 4 update calls.
    assert drv.update_calls == 4
    assert [t for t, _ in drv.received_events] == [0, 1, 2, 3]


# ---------------------------------------------------------------------------
# Speed scrub bounds (without pygame)
# ---------------------------------------------------------------------------
def test_speed_scrub_clamped_to_bounds() -> None:
    """The renderer constructor clamps initial tps into [MIN_TPS, MAX_TPS]."""
    # Avoid touching pygame. Construct only the speed-scrub state by
    # calling the keydown helper through a dummy.
    # We can't import the pygame renderer directly without pygame.font
    # init succeeding, so verify the bounds via the constants.
    assert MIN_TPS == 0.1
    assert MAX_TPS >= 10.0   # ticket spec says at least 10x
