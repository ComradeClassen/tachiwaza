# failure_resolution.py
# Physics-substrate Part 4.5 / Part 6.3: failure-outcome routing.
#
# When a committed throw's signature match doesn't clear the commit threshold
# at kake time, tori does not simply "reset". Tori enters a specific
# compromised state — selected from the throw template's FailureSpec based on:
#
#   - which of the four signature dimensions failed worst
#   - uke's fight_iq, composure, and fatigue (resource gate for clean counters)
#   - attacker's composure (low composure extends recovery)
#
# This module selects a FailureOutcome from a FailureSpec and computes the
# recovery duration. match.py applies the resolution by setting stun_ticks
# and pushing a composure delta.
#
# Per-outcome recovery durations come from spec Part 6.3. They are deliberate
# mechanical costs that make failed throws matter — tori can't attack during
# stun_ticks, and action_selection's rung 1 routes them to defensive-only.

from __future__ import annotations
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

from throw_signature import (
    match_kuzushi_vector, match_force_application,
    match_body_parts, match_uke_posture,
)
from throw_templates import (
    ThrowTemplate, FailureOutcome, FailureSpec,
)

if TYPE_CHECKING:
    from judoka import Judoka
    from grip_graph import GripGraph


# ---------------------------------------------------------------------------
# RECOVERY TICKS BY OUTCOME (Part 6.3 — "Recovery: N ticks for tori to …")
# Zero means no compromised state — either the attack partially succeeded
# (PARTIAL_THROW), the grips reset cleanly (STANCE_RESET), or uke changed
# phase (UKE_VOLUNTARY_NEWAZA). Clean counters resolve uke's counter-throw
# separately; tori's own recovery from them is handled by the counter-throw
# landing if it lands, else by a single stun tick.
# ---------------------------------------------------------------------------
RECOVERY_TICKS_BY_OUTCOME: dict[FailureOutcome, int] = {
    FailureOutcome.TORI_SWEEP_BOUNCES_OFF:           1,
    FailureOutcome.TORI_COMPROMISED_SINGLE_SUPPORT:  2,
    FailureOutcome.TORI_COMPROMISED_FORWARD_LEAN:    3,
    FailureOutcome.TORI_BENT_FORWARD_LOADED:         2,
    FailureOutcome.TORI_STUCK_WITH_UKE_ON_BACK:      4,
    FailureOutcome.TORI_ON_KNEE_UKE_STANDING:        3,
    FailureOutcome.TORI_ON_BOTH_KNEES_UKE_STANDING:  5,
    FailureOutcome.STANCE_RESET:                     0,
    FailureOutcome.PARTIAL_THROW:                    0,
    FailureOutcome.UKE_VOLUNTARY_NEWAZA:             0,
    FailureOutcome.UCHI_MATA_SUKASHI:                1,
    FailureOutcome.OSOTO_GAESHI:                     1,
    FailureOutcome.URA_NAGE:                         1,
    FailureOutcome.KAESHI_WAZA_GENERIC:              1,
}


# Counter-readiness gating — uke needs each of iq, composure, and freshness
# to meaningfully exploit a failed throw. The product of the three normalizes
# to [0, 1] and is compared against the throw's sukashi / counter-vulnerability
# when deciding whether the clean-counter branch fires.
COUNTER_READINESS_GATE: float = 0.50
FATIGUED_UKE_THRESHOLD: float = 0.60   # leg fatigue above which uke resets rather than counters
PANICKED_UKE_THRESHOLD: float = 0.30   # composure-fraction below which uke resets


# ---------------------------------------------------------------------------
# FAILURE RESOLUTION — the result of routing a failed commit
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FailureResolution:
    outcome:               FailureOutcome
    recovery_ticks:        int
    failed_dimension:      str                 # "kuzushi" / "force" / "body" / "posture"
    dimension_score:       float               # the failed dimension's score


# ---------------------------------------------------------------------------
# SELECT FAILURE OUTCOME (Part 4.5)
# ---------------------------------------------------------------------------
def select_failure_outcome(
    throw: ThrowTemplate,
    attacker: "Judoka",
    defender: "Judoka",
    graph: "GripGraph",
    rng: random.Random | None = None,
) -> FailureResolution:
    """Pick a FailureOutcome for a failed commit attempt.

    Spec 4.5 factors, in roughly this order of influence:

      1. Dominant failed dimension — which signature dimension scored lowest.
         Body-parts failures tend toward primary (compromised-state) outcomes;
         kuzushi failures can route to stance reset if uke isn't a threat.
      2. Uke resources — a fatigued or panicked uke falls back to tertiary
         (usually STANCE_RESET or PARTIAL_THROW) rather than counter.
      3. Uke readiness — a sharp, composed uke with high fight_iq has a real
         chance of firing the secondary (clean counter) branch.

    The outcome is stochastic. Pass `rng` for deterministic tests.
    """
    r = rng if rng is not None else random

    # 1. Per-dimension scores — identify the worst.
    dim_scores = _dimension_scores(throw, attacker, defender, graph)
    worst_dim = min(dim_scores, key=dim_scores.get)
    worst_score = dim_scores[worst_dim]

    # 2. Uke resource gate — is uke fit enough to exploit the failure?
    uke_fatigue    = _avg_leg_fatigue(defender)
    uke_composure  = _composure_fraction(defender)
    uke_iq         = defender.capability.fight_iq / 10.0
    counter_ready  = uke_iq * uke_composure * (1.0 - uke_fatigue)

    spec: FailureSpec = throw.failure_outcome
    outcome = _route(
        spec=spec,
        counter_ready=counter_ready,
        uke_fatigue=uke_fatigue,
        uke_composure=uke_composure,
        throw_vuln=_counter_vulnerability_of(throw),
        rng=r,
    )

    # 3. Recovery duration, extended for a panicked attacker (Part 6.3
    # "Recovery extended by 1–2 ticks" under TORI_DESPERATION_STATE overlay).
    recovery = RECOVERY_TICKS_BY_OUTCOME.get(outcome, 0)
    if _composure_fraction(attacker) < PANICKED_UKE_THRESHOLD:
        recovery += 1

    return FailureResolution(
        outcome=outcome,
        recovery_ticks=recovery,
        failed_dimension=worst_dim,
        dimension_score=worst_score,
    )


# ---------------------------------------------------------------------------
# APPLY FAILURE RESOLUTION
# ---------------------------------------------------------------------------
def apply_failure_resolution(
    resolution: FailureResolution,
    attacker: "Judoka",
    composure_drop: float = 0.10,
) -> None:
    """Apply the mechanical consequences of a failed commit to tori.

    Effects:
      - stun_ticks += resolution.recovery_ticks (defensive-only during recovery)
      - composure_current drops by `composure_drop`
      - BodyState reconfiguration per the Part 6.3 compromised-state config
        matching resolution.outcome (trunk flex, foot state, CoM height)
    """
    from compromised_state import apply_compromised_body_state
    attacker.state.stun_ticks += resolution.recovery_ticks
    attacker.state.composure_current = max(
        0.0, attacker.state.composure_current - composure_drop
    )
    apply_compromised_body_state(attacker, resolution.outcome)


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
def _dimension_scores(
    throw: ThrowTemplate, attacker: "Judoka", defender: "Judoka",
    graph: "GripGraph",
) -> dict[str, float]:
    return {
        "kuzushi": match_kuzushi_vector(throw, attacker, defender),
        "force":   match_force_application(throw, attacker, graph),
        "body":    match_body_parts(throw, attacker, defender),
        "posture": match_uke_posture(throw, defender),
    }


def _avg_leg_fatigue(j: "Judoka") -> float:
    rl = j.state.body.get("right_leg")
    ll = j.state.body.get("left_leg")
    if rl is None or ll is None:
        return 0.0
    return 0.5 * (rl.fatigue + ll.fatigue)


def _composure_fraction(j: "Judoka") -> float:
    ceiling = max(1.0, float(j.capability.composure_ceiling))
    return max(0.0, min(1.0, j.state.composure_current / ceiling))


def _counter_vulnerability_of(throw: ThrowTemplate) -> float:
    """Pick the right vulnerability knob for the throw's class."""
    if hasattr(throw, "counter_vulnerability"):
        return float(getattr(throw, "counter_vulnerability"))
    return float(getattr(throw, "sukashi_vulnerability", 0.0))


def _route(
    spec: FailureSpec,
    counter_ready: float,
    uke_fatigue: float,
    uke_composure: float,
    throw_vuln: float,
    rng: random.Random,
) -> FailureOutcome:
    """Route to primary/secondary/tertiary outcome given gate inputs."""
    # Tertiary branch: fatigued or panicked uke falls back to the safe reset
    # outcome rather than committing to a counter.
    if spec.tertiary is not None and (
        uke_fatigue > FATIGUED_UKE_THRESHOLD
        or uke_composure < PANICKED_UKE_THRESHOLD
    ):
        return spec.tertiary

    # Secondary branch: uke is sharp AND the throw has meaningful vulnerability.
    if spec.secondary is not None and counter_ready >= COUNTER_READINESS_GATE:
        # Probability of counter firing scales with both readiness and the
        # throw's inherent vulnerability.
        p = counter_ready * throw_vuln
        if rng.random() < p:
            return spec.secondary

    return spec.primary
