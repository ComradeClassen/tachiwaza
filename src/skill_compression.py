# skill_compression.py
# Physics-substrate Part 6.1: skill-compression of the tsukuri-kuzushi-kake
# sequence.
#
# Spec: design-notes/physics-substrate.md, Part 6.1.
#
# Classical Japanese judo theory divides a throw into three phases — kuzushi,
# tsukuri, kake — but Matsumoto 1978 and every study since has shown these
# phases overlap temporally in skilled performance. This module models that
# with a single belt-rank-indexed compression factor N: the number of ticks
# across which a throw attempt unfolds.
#
# Elite: N=1 (single-tick commit). White belt: N=5–6 (wide gaps between
# sub-events). Per-technique override: tokui-waza fires at N-1 (floor 1) —
# the specialist's advantage.
#
# The four sub-events — REACH_KUZUSHI, KUZUSHI_ACHIEVED, TSUKURI, KAKE_COMMIT
# — are always emitted, collapsed or spread across N ticks. KAKE_COMMIT is
# always on the final tick; that's when resolve_throw / _apply_throw_result
# fires. The intermediate ticks expose counter-windows (Part 6.2, future
# work) and mid-attempt interrupt states.

from __future__ import annotations
from enum import Enum, auto
from typing import TYPE_CHECKING

from enums import BeltRank
from throws import ThrowID

if TYPE_CHECKING:
    from judoka import Judoka


# ---------------------------------------------------------------------------
# SUB-EVENT (the four phases of a throw attempt)
# ---------------------------------------------------------------------------
class SubEvent(Enum):
    REACH_KUZUSHI    = auto()  # Tori applies force; uke's CoM begins to move.
    KUZUSHI_ACHIEVED = auto()  # Uke's CoM has exited the recoverable region.
    TSUKURI          = auto()  # Tori repositions — turn-in, hip load, fulcrum set.
    KAKE_COMMIT      = auto()  # The throw executes.


# ---------------------------------------------------------------------------
# BELT-RANK TO N MAPPING (spec 6.1 table)
# v0.1 calibration values. Phase 3 will tune against match telemetry.
# ---------------------------------------------------------------------------
N_BY_BELT: dict[BeltRank, int] = {
    BeltRank.WHITE:   5,   # Three distinct pulses; wide gaps.
    BeltRank.YELLOW:  4,   # Pull and enter overlap slightly.
    BeltRank.ORANGE:  4,
    BeltRank.GREEN:   3,   # Pull-enter compressed; throw separate.
    BeltRank.BLUE:    3,
    BeltRank.BROWN:   2,   # Kuzushi-tsukuri overlap; kake still visible.
    BeltRank.BLACK_1: 2,   # Shodan — compressed to two ticks.
    BeltRank.BLACK_2: 2,
    BeltRank.BLACK_3: 1,   # Advanced dan — single continuous action.
    BeltRank.BLACK_4: 1,
    BeltRank.BLACK_5: 1,   # Elite / Olympic.
}

N_FLOOR: int = 1
N_CEILING: int = 8   # defensive cap so pathological inputs don't explode the schedule


# ---------------------------------------------------------------------------
# COMPRESSION N FOR A JUDOKA / THROW PAIR
# ---------------------------------------------------------------------------
def compression_n_for(judoka: "Judoka", throw_id: ThrowID) -> int:
    """Ticks this judoka spends executing this throw.

    Base value comes from belt rank; tokui-waza (throws listed in
    capability.signature_throws) get N-1 to a floor of 1. The spec commits
    to the ordering only — values are Phase 3 calibration.
    """
    base = N_BY_BELT.get(judoka.identity.belt_rank, 3)
    if throw_id in judoka.capability.signature_throws:
        base = max(N_FLOOR, base - 1)
    return max(N_FLOOR, min(N_CEILING, base))


# ---------------------------------------------------------------------------
# SUB-EVENT SCHEDULE
# Maps tick-offset (0 = first tick of attempt) → list of SubEvents emitted.
# KAKE_COMMIT is always on the final tick (offset N-1); REACH_KUZUSHI is
# always on the first tick (offset 0). Intermediate events distribute per
# spec 6.1's examples:
#
#   N = 1 : all four on tick 0 (elite — single continuous action)
#   N = 2 : REACH on tick 0;  KA + TS + KC together on tick 1
#           (spec: "KUZUSHI_ACHIEVED and TSUKURI emit together")
#   N = 3 : REACH;  KA + TS;  KC      — kuzushi and tsukuri still paired
#   N = 4 : REACH;  KA;  TS;  KC      — each sub-event its own tick
#   N ≥ 5 : REACH + silent padding + KA + TS + KC — wide gaps between events
# ---------------------------------------------------------------------------
def sub_event_schedule(n: int) -> dict[int, list[SubEvent]]:
    """Return {tick_offset: [SubEvent,...]} for a throw of compression N."""
    if n < 1:
        n = 1
    RK, KA, TS, KC = (
        SubEvent.REACH_KUZUSHI, SubEvent.KUZUSHI_ACHIEVED,
        SubEvent.TSUKURI,       SubEvent.KAKE_COMMIT,
    )
    if n == 1:
        return {0: [RK, KA, TS, KC]}
    if n == 2:
        return {0: [RK], 1: [KA, TS, KC]}
    if n == 3:
        return {0: [RK], 1: [KA, TS], 2: [KC]}
    if n == 4:
        return {0: [RK], 1: [KA], 2: [TS], 3: [KC]}
    # n >= 5: keep the final three events tight and pad the REACH phase.
    return {0: [RK], n - 3: [KA], n - 2: [TS], n - 1: [KC]}


# ---------------------------------------------------------------------------
# SUB-EVENT DISPLAY
# ---------------------------------------------------------------------------
SUB_EVENT_LABELS: dict[SubEvent, str] = {
    SubEvent.REACH_KUZUSHI:    "reach-kuzushi",
    SubEvent.KUZUSHI_ACHIEVED: "kuzushi",
    SubEvent.TSUKURI:          "tsukuri",
    SubEvent.KAKE_COMMIT:      "kake",
}
