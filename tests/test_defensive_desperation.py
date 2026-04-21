# tests/test_defensive_desperation.py
# HAJ-35 — defensive desperation tracker.
#
# Covers:
#   - signals accumulate and prune at the rolling-window cutoff
#   - pressure_score weighting matches the constants
#   - entry + exit thresholds produce hysteresis (no flicker)
#   - breakdown() returns a dict with the signals producing the score

from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from defensive_desperation import (
    DefensivePressureTracker,
    WINDOW_TICKS, ENTRY_THRESHOLD, EXIT_THRESHOLD,
    WEIGHT_OPP_COMMITS, WEIGHT_KUZUSHI, WEIGHT_COMPOSURE_DROP,
)


def test_tracker_empty_state_has_zero_score() -> None:
    tr = DefensivePressureTracker()
    assert tr.pressure_score(tick=10) == 0.0
    assert tr.active is False


def test_commits_and_kuzushi_accumulate_into_score() -> None:
    tr = DefensivePressureTracker()
    tr.record_opponent_commit(tick=5)
    tr.record_opponent_commit(tick=6)
    tr.record_kuzushi(tick=6)
    expected = 2 * WEIGHT_OPP_COMMITS + 1 * WEIGHT_KUZUSHI
    assert abs(tr.pressure_score(tick=10) - expected) < 1e-9


def test_signals_prune_past_window() -> None:
    tr = DefensivePressureTracker()
    tr.record_opponent_commit(tick=0)
    tr.record_opponent_commit(tick=5)
    # Tick 100 is well past the window — both should prune.
    assert tr.pressure_score(tick=100) == 0.0


def test_composure_drop_contributes_to_score() -> None:
    tr = DefensivePressureTracker()
    tr.record_composure(tick=0, composure=7.0)
    tr.record_composure(tick=5, composure=5.0)
    # drop = 2.0; score = 2.0 * WEIGHT_COMPOSURE_DROP
    score = tr.pressure_score(tick=10)
    assert abs(score - 2.0 * WEIGHT_COMPOSURE_DROP) < 1e-9


def test_entry_and_exit_with_hysteresis() -> None:
    tr = DefensivePressureTracker()
    # Push score above entry threshold with commits + kuzushi.
    for t in range(3):
        tr.record_opponent_commit(tick=t)
    tr.record_kuzushi(tick=3)
    # Score = 3 * 1.0 + 1 * 1.5 = 4.5 >= 3.0 (ENTRY_THRESHOLD)
    assert tr.update(tick=5) is True
    assert tr.active is True

    # Time advances past the window — score drops; state should exit.
    # At tick=5 + WINDOW_TICKS + 1, all commits/kuzushi have pruned.
    assert tr.update(tick=5 + WINDOW_TICKS + 1) is False
    assert tr.active is False


def test_hysteresis_stays_active_between_entry_and_exit() -> None:
    """Between EXIT_THRESHOLD and ENTRY_THRESHOLD, state is sticky: once
    active, it only releases when score drops BELOW exit; it doesn't
    flicker off just because the score dipped under entry.
    """
    tr = DefensivePressureTracker()
    tr.record_opponent_commit(tick=0)
    tr.record_opponent_commit(tick=1)
    tr.record_opponent_commit(tick=2)
    tr.record_kuzushi(tick=3)
    tr.update(tick=5)   # active
    assert tr.active is True

    # Shrink the window so we're between exit and entry. Simulate by
    # feeding a late composure sample so the window starts later — the
    # simplest way is just to query at a tick where some events still
    # fall in-window but score sits between the two thresholds.
    # With 1 commit + 1 kuzushi still in-window: score = 1 + 1.5 = 2.5.
    # That's below ENTRY_THRESHOLD (3.0) but above EXIT_THRESHOLD (1.5).
    tr.opp_commit_ticks = [tr.opp_commit_ticks[-1]]
    # Keeping kuzushi as-is.
    assert tr.update(tick=5) is True   # still active (hysteresis)


def test_breakdown_exposes_signals() -> None:
    tr = DefensivePressureTracker()
    tr.record_opponent_commit(tick=1)
    tr.record_kuzushi(tick=2)
    tr.record_composure(tick=0, composure=7.0)
    tr.record_composure(tick=3, composure=6.2)
    br = tr.breakdown(tick=5)
    assert br["opp_commits"] == 1
    assert br["kuzushi"] == 1
    assert br["composure_drop"] == 0.8
    assert br["window_ticks"] == WINDOW_TICKS
    assert "score" in br and "active" in br


if __name__ == "__main__":
    for n, fn in list(globals().items()):
        if n.startswith("test_") and callable(fn):
            fn()
            print(f"PASS  {n}")
