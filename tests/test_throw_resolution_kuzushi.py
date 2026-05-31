# tests/test_throw_resolution_kuzushi.py
# The kake landing-drive folded into uke's kuzushi buffer.
#
# When a throw lands (IPPON / WAZA_ARI) with a multi-tick drive, uke's CoM is
# walked across the mat. Pre-fix this only moved uke's com_position; the
# decaying kuzushi buffer never saw it. Post-fix, _resolve_kake records a
# THROW_RESOLUTION KuzushiEvent into uke's buffer scaled by the drive length.
# Snap / failed throws apply zero drive and emit nothing.

from __future__ import annotations
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from body_state import place_judoka
from kuzushi import (
    KuzushiSource, throw_resolution_kuzushi_event,
    BASE_THROW_RESOLUTION_KUZUSHI_FORCE, THROW_RESOLUTION_DRIVE_CAP_M,
)
from match import Match
from referee import build_suzuki
from throws import ThrowID
import match as match_module
import main as main_module


def _pair_match():
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())
    return t, s, m


# ---------------------------------------------------------------------------
# 1. Builder — zero drive emits nothing
# ---------------------------------------------------------------------------
def test_zero_drive_emits_nothing() -> None:
    t, _, _ = _pair_match()
    assert throw_resolution_kuzushi_event(t, (0.0, 0.0), current_tick=0) is None


# ---------------------------------------------------------------------------
# 2. Builder — direction + source + tick
# ---------------------------------------------------------------------------
def test_drive_event_direction_and_source() -> None:
    t, _, _ = _pair_match()
    ev = throw_resolution_kuzushi_event(t, (1.0, 0.0), current_tick=9)
    assert ev is not None
    assert ev.source_kind == KuzushiSource.THROW_RESOLUTION
    assert ev.tick_emitted == 9
    assert math.isclose(ev.vector[0], 1.0, abs_tol=1e-9)
    assert math.isclose(ev.vector[1], 0.0, abs_tol=1e-9)


def test_drive_event_direction_normalized_for_diagonal() -> None:
    t, _, _ = _pair_match()
    ev = throw_resolution_kuzushi_event(t, (3.0, 4.0), current_tick=0)
    assert math.isclose(math.hypot(*ev.vector), 1.0, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# 3. Builder — magnitude scales with drive length and caps
# ---------------------------------------------------------------------------
def test_magnitude_scales_with_drive_length() -> None:
    t, _, _ = _pair_match()
    short = throw_resolution_kuzushi_event(t, (0.5, 0.0), current_tick=0)
    longer = throw_resolution_kuzushi_event(t, (1.0, 0.0), current_tick=0)
    assert longer.magnitude > short.magnitude
    assert math.isclose(
        short.magnitude, BASE_THROW_RESOLUTION_KUZUSHI_FORCE * 0.5, rel_tol=1e-9,
    )


def test_magnitude_caps_on_long_drive() -> None:
    t, _, _ = _pair_match()
    huge = throw_resolution_kuzushi_event(
        t, (THROW_RESOLUTION_DRIVE_CAP_M + 5.0, 0.0), current_tick=0,
    )
    expected = BASE_THROW_RESOLUTION_KUZUSHI_FORCE * THROW_RESOLUTION_DRIVE_CAP_M
    assert math.isclose(huge.magnitude, expected, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# 4. Integration — _resolve_kake records into uke's buffer on a landing
# ---------------------------------------------------------------------------
def test_resolve_kake_records_drive_into_uke_buffer(monkeypatch) -> None:
    """A landing throw with a nonzero drive_vector emits a THROW_RESOLUTION
    event into the defender's buffer. resolve_throw is forced to WAZA_ARI and
    _apply_throw_result is stubbed so the test isolates the emit wiring."""
    t, s, m = _pair_match()
    monkeypatch.setattr(match_module, "resolve_throw",
                        lambda *a, **k: ("WAZA_ARI", 1.0))
    monkeypatch.setattr(m, "_apply_throw_result", lambda *a, **k: [])
    pre = len(s.kuzushi_events)
    m._resolve_kake(t, s, ThrowID.O_SOTO_GARI, actual=1.0, tick=15,
                    drive_vector=(1.2, 0.0))
    assert len(s.kuzushi_events) == pre + 1
    ev = s.kuzushi_events[-1]
    assert ev.source_kind == KuzushiSource.THROW_RESOLUTION
    assert ev.tick_emitted == 15


def test_resolve_kake_no_drive_records_nothing(monkeypatch) -> None:
    """A landing throw with zero drive (snap throw) emits no resolution
    event."""
    t, s, m = _pair_match()
    monkeypatch.setattr(match_module, "resolve_throw",
                        lambda *a, **k: ("WAZA_ARI", 1.0))
    monkeypatch.setattr(m, "_apply_throw_result", lambda *a, **k: [])
    pre = len(s.kuzushi_events)
    m._resolve_kake(t, s, ThrowID.O_SOTO_GARI, actual=1.0, tick=15,
                    drive_vector=(0.0, 0.0))
    assert len(s.kuzushi_events) == pre


def test_resolve_kake_failed_throw_records_nothing(monkeypatch) -> None:
    """A non-scoring outcome applies no drive and emits no resolution event
    even if a drive_vector is passed."""
    t, s, m = _pair_match()
    monkeypatch.setattr(match_module, "resolve_throw",
                        lambda *a, **k: ("NO_SCORE", 0.0))
    monkeypatch.setattr(m, "_apply_throw_result", lambda *a, **k: [])
    pre = len(s.kuzushi_events)
    m._resolve_kake(t, s, ThrowID.O_SOTO_GARI, actual=0.4, tick=15,
                    drive_vector=(1.2, 0.0))
    assert len(s.kuzushi_events) == pre


if __name__ == "__main__":
    import traceback
    passed = failed = 0
    # Minimal monkeypatch shim for direct (non-pytest) execution.
    class _MP:
        def __init__(self): self._undo = []
        def setattr(self, obj, name, val):
            old = getattr(obj, name)
            self._undo.append((obj, name, old))
            setattr(obj, name, val)
        def undo(self):
            for obj, name, old in reversed(self._undo):
                setattr(obj, name, old)
            self._undo = []
    for fn_name, fn in list(globals().items()):
        if fn_name.startswith("test_") and callable(fn):
            try:
                if "monkeypatch" in fn.__code__.co_varnames[:fn.__code__.co_argcount]:
                    mp = _MP()
                    try:
                        fn(mp)
                    finally:
                        mp.undo()
                else:
                    fn()
                passed += 1
                print(f"PASS  {fn_name}")
            except Exception:
                failed += 1
                print(f"FAIL  {fn_name}")
                traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
