# reaction_lag.py
# HAJ-149 — fight_iq-modulated reaction lag, the perception-to-response axis.
# HAJ-222 — recalibrated against the seed-1974183401 playtest. Pre-fix the
# distribution centered near zero, producing the cognitive-collapse cluster
# where tori's commit and uke's perception both landed on the same tick;
# real perception costs at least one tick of recognition + decision even for
# elite judoka, so the base distribution now sits in [1, 5] across the
# fight_iq range and the absolute floor is clamped at 1.
#
#   lag == 0 : would react on the commit tick (unreachable post-HAJ-222 clamp)
#   lag == 1 : elite reaction — sees the developing commit, reacts on the
#              resolution tick (commit_tick + 1) and still in time to BRACE
#   lag >= 2 : reacts after resolution — sees the consequence, no BRACE
#
# The discrete tick resolution (1 tick = ~1s of game time) makes
# sub-tick anticipation an engine artefact rather than a real cognitive
# beat: even a black-belt international can't *physically* respond
# before the attacker's signal forms. The model now reflects that.
#
# See HAJ-149 spec §"Signed reaction lag" for the per-axis modulators
# and HAJ-222 for the calibration rationale.

from __future__ import annotations
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from judoka import Judoka


# ---------------------------------------------------------------------------
# CALIBRATION CONSTANTS
# ---------------------------------------------------------------------------
# fight_iq → base expected lag mapping (linear; iq runs 0..10).
#
# HAJ-222 recalibration:
#   iq=10 (elite)  → base lag 1.0  (one tick of physical reaction time,
#                                   still in time to BRACE for resolution)
#   iq=5  (mid)    → base lag 2.5  ("2-3 ticks for mid-level" per spec)
#   iq=0  (novice) → base lag 4.0  ("3-5 ticks for novice" per spec)
#
# Slope = (lag_at_iq0 - lag_at_iq10) / 10 = (4.0 - 1.0) / 10 = 0.3 per iq.
BASE_LAG_INTERCEPT_IQ0:  float = 4.0    # iq=0 sits four ticks late
BASE_LAG_SLOPE_PER_IQ:   float = -0.3   # each iq point trims 0.3 ticks

# Distribution std around the expected lag. Discrete tick-resolution
# samples come from rounding a Gaussian draw; std=0.6 gives ~85% of
# samples within ±1 tick of the expected value (one-tick variance).
LAG_SAMPLE_STD:          float = 0.6

# Telegraph clarity (HAJ-222). Disguise scales the lag in both
# directions around the neutral pivot 0.5: a clearly-telegraphed
# (sloppy / well-known) commit is faster to read; a hidden setup
# slows the read. Pre-HAJ-222 only the late-shift direction existed
# (high disguise added lag), which contributed to the cluster bug —
# without a corresponding early-shift, even highly-telegraphed
# commits inherited the base lag instead of being read sooner.
DISGUISE_NEUTRAL:        float = 0.5
DISGUISE_LAG_RANGE:      float = 2.0    # ±1.0 tick shift at the extremes
FATIGUE_LAG_PENALTY:     float = 0.8    # tired = slower perception
COMPROMISED_LAG_PENALTY: float = 1.0    # compromised state = degraded read

# Composure × desperation interaction. A high-composure fighter under
# desperation focuses (sharpens read); a low-composure fighter under
# desperation panics (dulls read). Centered around composure_frac=0.5;
# above sharpens (negative shift), below dulls (positive shift).
DESPERATION_COMPOSURE_PIVOT: float = 0.5
DESPERATION_COMPOSURE_GAIN:  float = 1.0

# Familiarity: seen this throw class before in the match. Caps the
# perception bonus so a single repeat doesn't make uke clairvoyant.
FAMILIARITY_LAG_BONUS_PER_OBS: float = 0.3
FAMILIARITY_OBS_CAP:           int   = 3

# Hard clamps on the final lag.
#
# HAJ-222: LAG_CLAMP_MIN raised from -2 to 1 — a fighter cannot
# perceive an opponent's commit *before it forms* at our tick
# resolution (one tick ≈ one second of game time). Even an
# elite black-belt international needs at least one tick of
# physical reaction. This is the calibration knob that broke
# the cognitive-event-collapse cluster from the seed-1974183401
# playtest: with min=-2 the system could schedule the brace on
# the same tick as the commit; with min=1 the brace always lands
# on the resolution tick at the earliest.
LAG_CLAMP_MIN: int = 1
LAG_CLAMP_MAX: int = +5


# ---------------------------------------------------------------------------
# DISGUISE — composite of sequencing and pull-execution skill
# ---------------------------------------------------------------------------
def disguise_for(judoka: "Judoka") -> float:
    """A fighter's disguise level — how readable / hard-to-read their
    setup is. Returns a value in [0, 1].

    Pre-HAJ-149 there was no `kuzushi_disguise` attribute. Disguise is
    derived from existing skill axes that *should* correlate with smooth,
    hard-to-read setups: sequencing precision (clean combos that don't
    telegraph) and pull execution (no self-cancellation that gives the
    plan away). v0.2 may promote disguise to a first-class axis.
    """
    from skill_vector import axis
    seq = axis(judoka, "sequencing_precision")
    pull = axis(judoka, "pull_execution")
    return max(0.0, min(1.0, 0.5 * (seq + pull)))


# ---------------------------------------------------------------------------
# EXPECTED LAG
# ---------------------------------------------------------------------------
def expected_lag(
    perceiver: "Judoka",
    attacker: "Judoka",
    *,
    fatigue_frac: Optional[float] = None,
    compromised: bool = False,
    in_desperation: bool = False,
    composure_frac: Optional[float] = None,
    familiarity_count: int = 0,
) -> float:
    """Compute the perceiver's expected reaction lag in (signed) ticks.

    The result is a continuous expected value; `sample_lag` samples a
    discrete tick from a Gaussian centered on this expected value.

    All modulator arguments are optional because callers may pass `None`
    when they don't have the relevant signal handy (e.g., a unit test of
    the base mapping). Keep call sites uncluttered: only fill the
    arguments that are actually load-bearing for this perception event.
    """
    iq = float(perceiver.capability.fight_iq)
    base = BASE_LAG_INTERCEPT_IQ0 + BASE_LAG_SLOPE_PER_IQ * iq

    # Opponent's telegraph clarity. Centered on DISGUISE_NEUTRAL so a
    # well-hidden setup (disguise=1) slows the read and a sloppy /
    # telegraphed setup (disguise=0) speeds it up. Pre-HAJ-222 only
    # the slow-down half existed; sloppy attackers inherited the
    # base lag instead of being easier to read.
    base += (disguise_for(attacker) - DISGUISE_NEUTRAL) * DISGUISE_LAG_RANGE

    # Fatigue — defaults to derived from cardio if not supplied.
    if fatigue_frac is None:
        cardio = float(getattr(perceiver.state, "cardio_current", 1.0))
        fatigue_frac = max(0.0, min(1.0, 1.0 - cardio))
    base += fatigue_frac * FATIGUE_LAG_PENALTY

    # Compromised state.
    if compromised:
        base += COMPROMISED_LAG_PENALTY

    # Composure × desperation.
    if in_desperation:
        if composure_frac is None:
            ceiling = max(1.0, float(perceiver.capability.composure_ceiling))
            composure_frac = max(0.0, min(
                1.0, perceiver.state.composure_current / ceiling
            ))
        # > pivot → sharpens (negative shift); < pivot → dulls (positive shift).
        delta = (DESPERATION_COMPOSURE_PIVOT - composure_frac)
        base += delta * DESPERATION_COMPOSURE_GAIN

    # Familiarity.
    obs = max(0, min(FAMILIARITY_OBS_CAP, familiarity_count))
    base -= obs * FAMILIARITY_LAG_BONUS_PER_OBS

    return base


# ---------------------------------------------------------------------------
# DISCRETE LAG SAMPLING
# ---------------------------------------------------------------------------
def sample_lag(
    perceiver: "Judoka",
    attacker: "Judoka",
    *,
    rng: Optional[random.Random] = None,
    **modulators,
) -> int:
    """Sample a discrete reaction-lag (in ticks) from the distribution
    centered on `expected_lag(...)`. Clamped to [LAG_CLAMP_MIN,
    LAG_CLAMP_MAX] so consequence-queue scheduling doesn't drift into
    multi-tick anticipation (out of v0.1 scope).
    """
    r = rng if rng is not None else random
    mu = expected_lag(perceiver, attacker, **modulators)
    raw = r.gauss(mu, LAG_SAMPLE_STD)
    return max(LAG_CLAMP_MIN, min(LAG_CLAMP_MAX, int(round(raw))))


# ---------------------------------------------------------------------------
# RESPONSE TYPE
# ---------------------------------------------------------------------------
@dataclass
class PerceptionResponse:
    """A perceiver's chosen response to an observed intent signal."""
    kind: str               # "INTERRUPT" | "BRACE" | "REPLAN" | "NONE"
    perceiver: str          # fighter name
    target_actor: str       # opponent name
    target_tick: int        # the tick the response acts upon (typically the
                            # attacker's resolution tick)
    sampled_lag: int        # the lag this perceiver rolled
    notes: str = ""


def choose_response(
    perceiver: "Judoka",
    attacker: "Judoka",
    *,
    sampled_lag: int,
    commit_tick: int,
    rng: Optional[random.Random] = None,
) -> PerceptionResponse:
    """Pick a response type for a perceived commit.

    v0.1 implements the BRACE-for-N+1 path as the concrete behavior:
    when the perceiver reads the commit in time (lag <= 0), they choose
    to brace for the opponent's resolution tick. Lag == +1 still allows
    reaction on the resolution tick (just barely in time). Lag >= +2 is
    "too late" — no response.

    INTERRUPT and REPLAN are scaffolded for HAJ-150 / HAJ-152 to wire in;
    the response kinds are valid in the type system but not yet
    selected here. See the HAJ-149 spec §"Three perception responses".
    """
    a_name = attacker.identity.name
    p_name = perceiver.identity.name
    # Resolution tick is commit_tick + 1 under HAJ-148's deferral rule.
    resolution_tick = commit_tick + 1
    # The perceiver's effective awareness tick.
    awareness_tick = commit_tick + sampled_lag

    if awareness_tick <= resolution_tick:
        return PerceptionResponse(
            kind="BRACE",
            perceiver=p_name, target_actor=a_name,
            target_tick=resolution_tick, sampled_lag=sampled_lag,
            notes=f"awareness@t{awareness_tick}, brace for resolution",
        )
    return PerceptionResponse(
        kind="NONE",
        perceiver=p_name, target_actor=a_name,
        target_tick=resolution_tick, sampled_lag=sampled_lag,
        notes=f"awareness@t{awareness_tick}, after resolution — too late",
    )
