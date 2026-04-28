# significance.py
# HAJ-144 acceptance #1 — significance scoring as a first-class event field.
#
# Every Event the engine emits carries `significance: int` on a 0-10 scale.
# Altitude readers (mat-side / stands / review / broadcast — HAJ-144 part A)
# filter the tick log by `event.significance >= reader.threshold`. Higher
# altitude = higher threshold = lower density.
#
# v0.1 thresholds (per HAJ-144 design):
#   - mat-side:    >= 1  (everything except true noise)
#   - stands:      >= 4
#   - review:      >= 7
#   - broadcast:   >= 9  (and aggregates across matches)
#
# v0.1 score derivation:
#   significance = event_class_base
#                + recognition_score_bonus    (clean signature throws bump up)
#                + execution_magnitude_bonus  (high-eq commits bump up)
#                + match_context_bonus        (golden-medal final, golden score, etc.)
#
# v0.1 ships fixed weights; calibration is a post-ship Gemini-pass question
# per HAJ-144's open question #1. The math is intentionally simple — the
# discrimination axis isn't fineness of score, it's that it EXISTS as data.

from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# EVENT-CLASS BASE TABLE
# Every Event.event_type maps to a base score. Anything below 1 is dropped
# even at mat-side; anything 9+ aggregates to broadcast altitude.
# ---------------------------------------------------------------------------
EVENT_CLASS_BASE: dict[str, int] = {
    # --- Match-defining beats (always render) ---
    "IPPON_AWARDED":              10,
    "SUBMISSION_VICTORY":         10,
    "MATCH_OVER":                 10,
    "TIME_EXPIRED":                9,
    # --- Score events (render at all altitudes) ---
    "SCORE_AWARDED":               9,
    "THROW_LANDING":               7,
    # --- Throw beats (render at mat-side and stands) ---
    "THROW_ENTRY":                 6,
    "COUNTER_COMMIT":              7,
    "STUFFED":                     6,
    "THROW_ABORTED":               4,
    "FAILED":                      4,
    # --- Ne-waza ---
    "NEWAZA_TRANSITION":           7,
    "ESCAPE_SUCCESS":              6,
    "OSAEKOMI_BEGIN":              6,
    "OSAEKOMI_BREAK":              5,
    # --- Referee / phase ---
    "MATTE":                       5,
    "HAJIME":                      5,
    "SHIDO_AWARDED":               5,
    # --- State transitions ---
    "OFFENSIVE_DESPERATION_ENTER": 4,
    "DEFENSIVE_DESPERATION_ENTER": 4,
    "OFFENSIVE_DESPERATION_EXIT":  3,
    "DEFENSIVE_DESPERATION_EXIT":  3,
    "KUZUSHI_INDUCED":             4,
    # --- Grip war (mat-side only by default) ---
    "GRIP_ESTABLISH":              2,
    "GRIP_DEEPEN":                 2,
    "GRIP_DEGRADE":                2,
    "GRIP_STRIPPED":               4,    # a kill is meaningful
    "GRIP_BREAK":                  4,
    "GRIPS_RESET":                 3,
    # --- Sub-events (debug-stream noise) ---
    "SUB_REACH_KUZUSHI":           1,
    "SUB_KUZUSHI_ACHIEVED":        1,
    "SUB_TSUKURI":                 1,
    "SUB_KAKE_COMMIT":             1,
    # --- Editorial / narration layer ---
    "MATCH_CLOCK":                 5,
    # --- Throw-denied (defensive infrastructure) ---
    "THROW_DENIED_DISTANT":        2,
    "THROW_DENIED_OOB":            2,
}


# Threshold defaults per altitude — exposed for the altitude readers.
THRESHOLD_MAT_SIDE:  int = 1
THRESHOLD_STANDS:    int = 4
THRESHOLD_REVIEW:    int = 7
THRESHOLD_BROADCAST: int = 9


def significance_for(
    event_type: str,
    *,
    execution_quality: Optional[float] = None,
    recognition: Optional[float] = None,
    is_golden_score: bool = False,
    is_final: bool = False,
) -> int:
    """Compute a 0-10 significance score for an Event of the given type.

    `execution_quality` ∈ [0, 1]: high-eq throws bump the floor up by 1;
    barely-committed (eq < 0.3) attempts drop by 1.

    `recognition` ∈ [0, 1]: clean signature recognition bumps up by 1;
    low-recognition (< 0.4) drops by 1. None means recognition wasn't
    computed for this event (most non-throw events).

    `is_golden_score` / `is_final`: match-context bonuses; +1 each (capped).

    Result is clamped to [0, 10].
    """
    base = EVENT_CLASS_BASE.get(event_type, 1)

    if execution_quality is not None:
        if execution_quality >= 0.75:
            base += 1
        elif execution_quality < 0.30:
            base -= 1

    if recognition is not None:
        if recognition >= 0.75:
            base += 1
        elif recognition < 0.40:
            base -= 1

    if is_golden_score:
        base += 1
    if is_final:
        base += 1

    if base < 0:
        return 0
    if base > 10:
        return 10
    return base
