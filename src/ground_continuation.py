# ground_continuation.py
# HAJ-236 — stuffed-standing-throw ground-continuation decision.
#
# HAJ-155 made a stuffed/failed STANDING throw reset cleanly to standing
# (so a stuffed O-uchi-gari wouldn't look mechanically identical to a
# stuffed Tomoe-nage). That gate was a hard "always reset". The post-223
# match review (seed 1081968535) showed the side effect: across a full
# match of standing throws, ne-waza was almost never *entered* — every
# stuffed reap reset to standing, and the only doors were the rare
# sacrifice throw and the post-score chase (HAJ-152). The owner's t076
# note — "if a throw is stuffed, that's a chance for ne-waza" — is the
# motivating observation.
#
# This module replaces HAJ-155's hard reset with a *probabilistic* gate
# for standing throws. A stuffed standing throw now sometimes spills into
# a ground scramble (the stuffed aggressor underneath, the defender on
# top) instead of resetting. The rate is governed so ne-waza appears at a
# realistic frequency without dominating: most stuffs still reset, and a
# clean hip throw stuffed between two stand-up players almost always does.
#
# The decision mirrors `chase_decision.make_chase_decision` in shape:
# additive attribute-weighted factors, clamped, rolled against a seeded
# RNG, with a factor breakdown surfaced for the engineering log.
#
# Calibration is v0.1 against the design-note targets
# (`design-notes/ne-waza-entry-paths.md`); v0.2 tunes against telemetry.

from __future__ import annotations
import random
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from judoka import Judoka
    from throws import ThrowID


# ---------------------------------------------------------------------------
# GROUND-CONTINUATION DECISION
# ---------------------------------------------------------------------------
class GroundContinuation(Enum):
    CONTINUE_TO_GROUND = auto()  # the scramble spills to ne-waza
    RESET_TO_STANDING  = auto()  # clean reset (HAJ-155 legacy behavior)


@dataclass
class GroundContinuationResult:
    """Output of make_ground_continuation_decision.

    `decision` is the chosen branch; `probability` is the continuation
    probability that was rolled against; `factors` captures the per-
    component contributions for the engineering log so the test suite
    (and the debug overlay) can inspect why a stuffed throw did or did
    not spill to the ground.
    """
    decision: GroundContinuation
    probability: float
    factors: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# TUNING — v0.1 calibration stubs (v0.2 tunes against simulation telemetry)
# ---------------------------------------------------------------------------
# Base continuation probability for a neutral stuff on a neutral throw.
# Deliberately low: the *default* outcome of a stuffed standing throw is
# still a reset (HAJ-155 spirit). The modifiers below lift it for the
# throws and fighters where a ground scramble is geometrically natural.
CONTINUE_BASE: float = 0.12

# Weight on the throw's geometry signal. We reuse the throw's
# `post_score_chase_advantage` (0.0–1.0) as the scramble-tendency proxy:
# the same property that makes a *scored* throw chase-ready — reaping and
# leg throws (O-soto 0.75, O-uchi 0.70, Uchi-mata 0.85) tangle the bodies
# — makes a *stuffed* one more likely to spill to the floor. Clean hip /
# shoulder throws (seoi 0.50) bounce off and reset. Centered on 0.5.
W_THROW_GEOMETRY: float = 0.30

# Weight on the would-be TOP fighter's ne-waza skill. On a stuffed
# standing throw the aggressor over-committed and ends up underneath; the
# defender is the one who can elect to follow them down into top position.
# A defender with real ne-waza wants the floor; a pure stand-up player
# lets them up. 0–10 scaled to 0–1, centered.
W_TOP_SKILL: float = 0.25

# Weight on the would-be BOTTOM fighter's (the stuffed aggressor's)
# ne-waza appetite — a ground-comfortable aggressor keeps fighting from
# the bottom rather than scrambling clear. Smaller than the top weight:
# the top fighter has positional choice; the bottom fighter mostly reacts.
W_BOTTOM_SKILL: float = 0.10

# Fatigue penalty. Ground scrambles are explosive; gassed legs/hands
# disengage and reset rather than commit to the floor. Averaged across
# leg/hand fatigue of both fighters, weighted.
W_FATIGUE: float = 0.15

# Clamp. The ceiling is deliberately modest — even the most scramble-prone
# stuffed throw between two grapplers continues to ground only about half
# the time. The floor keeps a clean stuff from being a hard "never".
CONTINUE_FLOOR: float = 0.02
CONTINUE_CEIL:  float = 0.50


# ---------------------------------------------------------------------------
# MAKE GROUND-CONTINUATION DECISION
# ---------------------------------------------------------------------------
def make_ground_continuation_decision(
    aggressor: "Judoka",
    defender: "Judoka",
    *,
    throw_id: "ThrowID",
    chase_advantage: float,
    rng: Optional[random.Random] = None,
) -> GroundContinuationResult:
    """Decide whether a stuffed STANDING throw spills into ne-waza.

    Args:
        aggressor: the stuffed tori (ends up on the bottom if it spills).
        defender: the uke who stuffed it (ends up on top if it spills).
        throw_id: the stuffed throw (for the engineering event).
        chase_advantage: the throw's `post_score_chase_advantage` value
            (0.0–1.0), reused as the scramble-tendency signal. Higher →
            more likely to tangle to the floor.
        rng: explicit RNG for reproducibility; falls back to the module
            random.

    Returns:
        GroundContinuationResult with the chosen branch, the rolled
        probability, and the factor breakdown for the engineering log.
    """
    r = rng if rng is not None else random

    factors: dict[str, float] = {}
    factors["base"] = CONTINUE_BASE

    # Throw geometry — centered around 0.5 so a neutral 0.5 throw is a
    # no-op, a reaping 0.85 throw adds, a sub-0.5 hip throw subtracts.
    factors["throw_geometry"] = (chase_advantage - 0.5) * W_THROW_GEOMETRY * 2.0

    # Would-be top fighter (defender) ne-waza skill — 0–10 → 0–1, centered.
    top_skill = max(0, min(10, int(defender.capability.ne_waza_skill))) / 10.0
    factors["top_skill"] = (top_skill - 0.5) * W_TOP_SKILL * 2.0

    # Would-be bottom fighter (aggressor) ne-waza appetite.
    bottom_skill = (
        max(0, min(10, int(aggressor.capability.ne_waza_skill))) / 10.0
    )
    factors["bottom_skill"] = (bottom_skill - 0.5) * W_BOTTOM_SKILL * 2.0

    # Fatigue — averaged leg/hand fatigue across both fighters.
    fat_parts = ("right_leg", "left_leg", "right_hand", "left_hand")
    fatigues: list[float] = []
    for f in (aggressor, defender):
        body = f.state.body
        fatigues.extend(body[p].fatigue for p in fat_parts if p in body)
    avg_fat = sum(fatigues) / len(fatigues) if fatigues else 0.0
    factors["fatigue"] = -avg_fat * W_FATIGUE

    probability = sum(factors.values())
    probability = max(CONTINUE_FLOOR, min(CONTINUE_CEIL, probability))

    rolled = r.random()
    if rolled < probability:
        decision = GroundContinuation.CONTINUE_TO_GROUND
    else:
        decision = GroundContinuation.RESET_TO_STANDING

    return GroundContinuationResult(
        decision=decision,
        probability=probability,
        factors=factors,
    )
