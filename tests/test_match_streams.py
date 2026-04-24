# tests/test_match_streams.py
# HAJ-65 — dual match log output: debug stream vs prose stream.
#
# The match log has two named views of the same underlying tick events:
#   - "debug":  engineer-facing (tick numbers, handles like [G#NN], grip
#               edge transitions, physics variables, execution_quality).
#   - "prose":  reader-facing (throw lines, referee calls, score
#               announcements), without tick prefixes or numeric debug.
#
# These tests exercise the emission layer by capturing stdout from a short
# match run under each stream setting.

from __future__ import annotations
import io
import os
import re
import sys
import random
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from body_state import place_judoka
from debug_inspector import DebugSession
import main as main_module


def _pair():
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    return t, s


def _run_match(stream: str, *, debug: bool = False, seed: int = 1,
               max_ticks: int = 120) -> str:
    """Run a short match with the given stream setting and return captured
    stdout as a single string."""
    from match import Match
    from referee import build_suzuki

    random.seed(seed)
    t, s = _pair()
    dbg = DebugSession(pause_on=set()) if debug else None
    m = Match(
        fighter_a=t, fighter_b=s, referee=build_suzuki(),
        max_ticks=max_ticks, debug=dbg, seed=seed, stream=stream,
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        m.run()
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Default stream (--stream=both) preserves the legacy tick-prefixed format.
# Existing tests monkey-patch _print_events, so they don't cover this — we
# pin it explicitly so future refactors don't silently break the default.
# ---------------------------------------------------------------------------
def test_default_stream_emits_tick_prefixed_lines() -> None:
    out = _run_match(stream="both")
    assert re.search(r"^t\d{3}: ", out, flags=re.MULTILINE), (
        "expected at least one tick-prefixed line in the default stream"
    )


# ---------------------------------------------------------------------------
# Side-by-side (stream="both"): engineer-with-ticks on the left, prose with
# a countdown match clock on the right, one row per event.
# ---------------------------------------------------------------------------
def test_both_stream_renders_side_by_side_with_separator() -> None:
    """At least one event is prose-worthy (Hajime!), so at least one row
    has both columns — detect by the vertical-bar separator."""
    out = _run_match(stream="both")
    assert "│" in out, "expected side-by-side separator '│' in both stream"


def test_both_stream_left_column_has_tick_prefix() -> None:
    """Every side-by-side row starts with the engineer's tNNN: prefix."""
    out = _run_match(stream="both")
    sbs_rows = [ln for ln in out.splitlines() if "│" in ln]
    assert sbs_rows, "expected at least one side-by-side row"
    for row in sbs_rows:
        assert re.match(r"^t\d{3}: ", row), (
            f"row missing tick prefix on left column: {row!r}"
        )


def test_both_stream_right_column_has_match_clock() -> None:
    """Prose side shows a countdown clock in M:SS form, right after the
    separator. A 120-tick match clock starts at 2:00; Hajime! on tick 0
    should produce exactly that clock reading in the first prose row."""
    out = _run_match(stream="both", max_ticks=120)
    # Match one row that carries Hajime! — its prose column should open
    # with the full-match clock.
    hajime_rows = [ln for ln in out.splitlines()
                   if "│" in ln and "Hajime!" in ln]
    assert hajime_rows, "expected at least one side-by-side row with Hajime!"
    # The clock appears right after the separator, followed by two spaces.
    assert re.search(r"│\s+2:00\s+", hajime_rows[0]), (
        f"expected '2:00' match clock after separator, got: {hajime_rows[0]!r}"
    )


def test_both_stream_clock_counts_down_with_ticks() -> None:
    """A later event in the match shows a lower clock value than an
    earlier one. Uses the generic ordering of clock readings across all
    side-by-side rows rather than pinning specific ticks."""
    out = _run_match(stream="both", max_ticks=120, seed=42)
    clocks: list[tuple[int, int]] = []
    pattern = re.compile(r"^t(\d{3}):.*?│\s+(\d+):(\d{2})\s")
    for ln in out.splitlines():
        m = pattern.match(ln)
        if not m:
            continue
        tick = int(m.group(1))
        minutes, seconds = int(m.group(2)), int(m.group(3))
        clocks.append((tick, minutes * 60 + seconds))
    assert len(clocks) >= 2, "expected at least 2 clocked rows"
    # Clock = max_ticks - tick, so ticks ascending ⇔ clocks descending.
    for (t1, c1), (t2, c2) in zip(clocks, clocks[1:]):
        if t2 > t1:
            assert c2 <= c1, (
                f"clock should be monotonic non-increasing across ticks; "
                f"tick {t1}={c1}s then tick {t2}={c2}s"
            )


def test_both_stream_debug_only_events_leave_prose_column_blank() -> None:
    """Grip edge churn is debug-only; when such an event is the only thing
    on its row, the right (prose) column must be blank — i.e. no separator
    on that row. The row is still tick-prefixed on the left."""
    out = _run_match(stream="both")
    # Grip events are frequent; find at least one.
    grip_rows = [ln for ln in out.splitlines() if "[grip]" in ln]
    assert grip_rows, "expected at least one [grip] event row"
    # Every grip-only row: starts with tNNN:, has no separator (no prose side).
    for row in grip_rows:
        assert re.match(r"^t\d{3}: ", row)
        assert "│" not in row, (
            f"debug-only [grip] event should not emit a prose column: {row!r}"
        )


def test_invalid_stream_name_rejected() -> None:
    from match import Match
    from referee import build_suzuki
    t, s = _pair()
    try:
        Match(fighter_a=t, fighter_b=s, referee=build_suzuki(),
              stream="garbage")
    except ValueError:
        return
    assert False, "expected ValueError for unknown stream"


# ---------------------------------------------------------------------------
# Prose stream — the core assertion of HAJ-65.
# ---------------------------------------------------------------------------
def test_prose_stream_has_no_debug_handles() -> None:
    """Even with --debug (DebugSession attached), the prose stream must not
    carry engineer-facing handles like [G#03], [T#01], or [F#A]."""
    out = _run_match(stream="prose", debug=True)
    # Prose output should be non-trivial — a 120-tick match always opens
    # with the Hajime call and typically sees grip events that become
    # referee or throw lines down the line.
    assert out.strip(), "expected some prose output from a 120-tick match"

    assert not re.search(r"\[G#\d+\]", out), (
        "found a grip handle [G#NN] in prose stream output"
    )
    assert not re.search(r"\[T#\d+\]", out), (
        "found a throw handle [T#NN] in prose stream output"
    )
    assert not re.search(r"\[F#[AB]\]", out), (
        "found a fighter handle [F#A/B] in prose stream output"
    )


def test_prose_stream_has_no_tick_prefix() -> None:
    out = _run_match(stream="prose")
    assert not re.search(r"^t\d{3}: ", out, flags=re.MULTILINE), (
        "found a tick-prefixed line (tNNN:) in prose stream output"
    )


def test_prose_stream_strips_execution_quality_numerics() -> None:
    """execution_quality is a debug value per HAJ-65; `(eq=0.72)` must not
    leak into the prose stream."""
    out = _run_match(stream="prose")
    assert "eq=" not in out, (
        "found an (eq=...) parenthetical in prose stream output"
    )


def test_prose_stream_drops_grip_and_physics_events() -> None:
    """Grip edge transitions ([grip] ...) and physics kuzushi beats
    ([physics] ...) are debug-only and should be absent from prose."""
    out = _run_match(stream="prose")
    assert "[grip]" not in out, "found a [grip] event in prose stream"
    assert "[physics]" not in out, "found a [physics] event in prose stream"


def test_prose_stream_keeps_referee_calls() -> None:
    """Referee announcements are the canonical reader-facing signal —
    `Hajime!` fires on tick 0 so it must be present in the prose stream."""
    out = _run_match(stream="prose")
    assert "Hajime!" in out, (
        "prose stream missing referee Hajime! announcement"
    )


# ---------------------------------------------------------------------------
# Entry point (mirrors other tests in this suite).
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import traceback
    passed = 0
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
                passed += 1
            except Exception:
                print(f"  FAIL  {name}")
                traceback.print_exc()
                failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
