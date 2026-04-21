# defensive_desperation.py
# HAJ-35 — defensive desperation mode.
#
# The offensive side already has a desperation mode in compromised_state.py:
# a fighter whose composure has collapsed AND whose kumi-kata clock is near
# shido will commit throws they shouldn't. The defensive side had no
# equivalent — a fighter pinned defending wave after wave of attack looked
# the same as one cruising through the first tick.
#
# Defensive desperation is a composite-pressure state tracked per fighter
# across a short rolling window. The signals are:
#
#   - opponent_commits_in_window   : how many times the opponent has fired
#                                    COMMIT_THROW against this fighter in the
#                                    last WINDOW_TICKS ticks
#   - kuzushi_events_in_window     : how many times this fighter was newly
#                                    detected off-balance in the window
#   - composure_drop_in_window     : composure loss (positive number) since
#                                    WINDOW_TICKS ago
#
# Each signal contributes to a pressure score via fixed weights. When the
# score crosses ENTRY_THRESHOLD the fighter enters the state; it exits when
# the score drops below EXIT_THRESHOLD (hysteresis to prevent flicker).
#
# Mechanical effects (HAJ-35 effect spec — all three apply when active):
#
#   1. Counter-window perception bump — tired eyes reading the pattern let
#      the defender see incoming throws they'd otherwise miss. Applied in
#      counter_windows.perceived_counter_window via a +CW_PERCEPTION_BONUS
#      term.
#
#   2. Counter-fire probability bump — a desperate defender is more
#      willing to throw a risky counter. Applied in
#      counter_windows.counter_fire_probability as a multiplicative bonus.
#
#   3. Grip-presence gate bypass — when the defender eventually commits a
#      throw of their own, the formal gate allows it even from weak grips,
#      same as offensive desperation. Applied in grip_presence_gate.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from judoka import Judoka


# ---------------------------------------------------------------------------
# TUNING (calibration stubs; Phase 3 tunes against telemetry)
# ---------------------------------------------------------------------------
WINDOW_TICKS: int = 15           # sliding window across all three signals

WEIGHT_OPP_COMMITS:     float = 1.0   # per opponent commit in window
WEIGHT_KUZUSHI:         float = 1.5   # per kuzushi event in window
WEIGHT_COMPOSURE_DROP:  float = 0.8   # per unit of composure lost in window

ENTRY_THRESHOLD: float = 3.0     # score at which the state fires
EXIT_THRESHOLD:  float = 1.5     # score at which the state releases

# Effect magnitudes — read by counter_windows.py and surfaced in debug.
CW_PERCEPTION_BONUS:       float = 0.12  # additive on perceived-window score
CW_FIRE_PROB_MULT:         float = 1.25  # multiplicative on counter-fire prob


# ---------------------------------------------------------------------------
# PRESSURE SIGNALS — per-fighter, updated every tick by Match
# ---------------------------------------------------------------------------
@dataclass
class DefensivePressureTracker:
    """Rolling-window signals that feed the defensive-desperation predicate.

    Each list is a list of tick indices; entries older than WINDOW_TICKS
    are pruned on access. Composure history is a (tick, composure) list
    so we can compute drop over the window.
    """
    opp_commit_ticks: list[int] = field(default_factory=list)
    kuzushi_ticks:    list[int] = field(default_factory=list)
    composure_hist:   list[tuple[int, float]] = field(default_factory=list)
    active:           bool = False   # hysteresis state

    def record_opponent_commit(self, tick: int) -> None:
        self.opp_commit_ticks.append(tick)

    def record_kuzushi(self, tick: int) -> None:
        self.kuzushi_ticks.append(tick)

    def record_composure(self, tick: int, composure: float) -> None:
        self.composure_hist.append((tick, composure))

    def _prune(self, tick: int) -> None:
        cutoff = tick - WINDOW_TICKS
        self.opp_commit_ticks = [t for t in self.opp_commit_ticks if t >= cutoff]
        self.kuzushi_ticks    = [t for t in self.kuzushi_ticks    if t >= cutoff]
        self.composure_hist   = [(t, c) for (t, c) in self.composure_hist if t >= cutoff]

    def pressure_score(self, tick: int) -> float:
        """Composite score. Higher = more defensive pressure."""
        self._prune(tick)
        commits_n = len(self.opp_commit_ticks)
        kuzushi_n = len(self.kuzushi_ticks)
        if self.composure_hist:
            oldest = self.composure_hist[0][1]
            newest = self.composure_hist[-1][1]
            drop = max(0.0, oldest - newest)
        else:
            drop = 0.0
        return (
            commits_n * WEIGHT_OPP_COMMITS
            + kuzushi_n * WEIGHT_KUZUSHI
            + drop * WEIGHT_COMPOSURE_DROP
        )

    def update(self, tick: int) -> bool:
        """Recompute state with hysteresis; return current active flag."""
        score = self.pressure_score(tick)
        if self.active and score < EXIT_THRESHOLD:
            self.active = False
        elif not self.active and score >= ENTRY_THRESHOLD:
            self.active = True
        return self.active

    def breakdown(self, tick: int) -> dict:
        """Debug-friendly snapshot of the signals producing the score."""
        self._prune(tick)
        commits_n = len(self.opp_commit_ticks)
        kuzushi_n = len(self.kuzushi_ticks)
        if self.composure_hist:
            oldest = self.composure_hist[0][1]
            newest = self.composure_hist[-1][1]
            drop = max(0.0, oldest - newest)
        else:
            drop = 0.0
        return {
            "score":         self.pressure_score(tick),
            "opp_commits":   commits_n,
            "kuzushi":       kuzushi_n,
            "composure_drop": round(drop, 2),
            "window_ticks":  WINDOW_TICKS,
            "active":        self.active,
        }
