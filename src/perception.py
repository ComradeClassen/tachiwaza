# perception.py
# Physics-substrate Part 3.5: the gap between actual and perceived signature.
#
# Elite judoka perceive throw-availability with high accuracy; novices
# perceive it noisily and biased. That gap, not a separate "skill" knob,
# drives:
#   - "novices commit to doomed throws" (false-positive perception)
#   - "novices miss real openings"       (false-negative perception)
#   - feint effectiveness (uke's perception of whether a force is a commit)
#
# v0.1 implementation: symmetric Gaussian noise whose std scales inversely
# with fight_iq. Fatigue and composure widen the std. Bias (systematic
# over- or under-estimate) is left as zero for v0.1 — the noise alone
# is enough to produce the emergent phenomena.

from __future__ import annotations
import random
from typing import TYPE_CHECKING

from throws import THROW_DEFS, ThrowID

if TYPE_CHECKING:
    from judoka import Judoka
    from grip_graph import GripGraph


# Calibration stubs; Phase 3 tunes against match telemetry.
BASE_STD:         float = 0.30   # std at fight_iq=0, no fatigue, full composure
MIN_STD:          float = 0.02   # floor so elite perception is never literally perfect
FATIGUE_STD_BONUS: float = 0.15  # additional std contributed by fully-cooked hands/cardio
COMPOSURE_STD_BONUS: float = 0.20  # additional std contributed by zero composure


def _composure_mod(judoka: "Judoka") -> float:
    ceiling = max(1.0, float(judoka.capability.composure_ceiling))
    return max(0.0, min(1.0, judoka.state.composure_current / ceiling))


def perception_std(judoka: "Judoka") -> float:
    """Standard deviation of perception error for this judoka right now.

    Elite + fresh + composed → near MIN_STD.
    Novice + fatigued + panicked → approaches BASE_STD + bonuses.
    """
    iq = float(judoka.capability.fight_iq)
    # fight_iq is 0–10; invert to a [0, 1] novice weight.
    novice_w = max(0.0, (10.0 - iq) / 10.0)
    base = MIN_STD + novice_w * (BASE_STD - MIN_STD)

    # Fatigue: average of the two gripping hands' fatigue in [0, 1].
    rh = judoka.state.body.get("right_hand")
    lh = judoka.state.body.get("left_hand")
    fatigue = 0.0
    if rh is not None and lh is not None:
        fatigue = 0.5 * (rh.fatigue + lh.fatigue)
    # Composure: low composure → panicked → noisier perception.
    panic = 1.0 - _composure_mod(judoka)

    return base + fatigue * FATIGUE_STD_BONUS + panic * COMPOSURE_STD_BONUS


def perceive(actual_match: float, judoka: "Judoka",
             rng: random.Random | None = None) -> float:
    """Return the judoka's perceived signature-match for a throw.

    actual_match is 0.0–1.0. Result is clamped to the same range.
    """
    r = rng if rng is not None else random
    std = perception_std(judoka)
    noisy = actual_match + r.gauss(0.0, std)
    return max(0.0, min(1.0, noisy))


# ---------------------------------------------------------------------------
# EDGE PERCEPTION (HAJ-128)
# Real judoka feel the boundary through the tatami seam under one foot.
# Elite + composed fighters perceive it accurately; novices drift unaware.
#
# Returns a noisy estimate of the distance from this fighter's CoM to the
# nearest edge of the contest area. Noise scales with the same
# perception_std the throw-signature path uses, so fight_iq, fatigue, and
# composure all modulate it consistently.
#
# Output is in METERS (HAJ-124 unit declaration). Clamped at 0 — a fighter
# perceiving "negative distance" is nonsensical; treat sub-zero as "you
# are out of bounds" via the actual is_out_of_bounds check.
# ---------------------------------------------------------------------------
EDGE_PERCEPTION_NOISE_SCALE: float = 1.5  # meters of noise at full perception_std


def actual_distance_to_edge(judoka: "Judoka", half_width: float) -> float:
    """Ground-truth distance to the nearest edge of a square contest area
    centered at the origin. Uses the chebyshev (L∞) metric — the closest
    edge is whichever component (x or y) is most extreme."""
    x, y = judoka.state.body_state.com_position
    return max(0.0, half_width - max(abs(x), abs(y)))


def perceive_edge_distance(
    judoka: "Judoka", half_width: float,
    rng: random.Random | None = None,
) -> float:
    """Noisy perception of distance to the nearest edge.

    Elite + fresh + composed → near ground truth.
    Novice + fatigued + panicked → wide noise; may misjudge by meters.
    """
    r = rng if rng is not None else random
    truth = actual_distance_to_edge(judoka, half_width)
    std = perception_std(judoka) * EDGE_PERCEPTION_NOISE_SCALE
    noisy = truth + r.gauss(0.0, std)
    return max(0.0, noisy)


# ---------------------------------------------------------------------------
# ACTUAL-SIGNATURE MATCH
# Ground-truth 0.0–1.0 match for a throw given current match state.
#
# Two paths:
#   - Worked-template path (Part 5): throw has an entry in WORKED_THROWS →
#     dispatch to throw_signature.signature_match, which runs the full
#     four-dimension weighted match (Part 4.2).
#   - Legacy path: two 0.5-weight factors (grip prereqs + kuzushi predicate).
#     Used for throws not yet instantiated as Part-5 templates.
# ---------------------------------------------------------------------------
def actual_signature_match(
    throw_id: ThrowID,
    attacker: "Judoka",
    defender: "Judoka",
    graph: "GripGraph",
    current_tick: int = 0,
) -> float:
    from worked_throws import worked_template_for
    template = worked_template_for(throw_id)
    if template is not None:
        from throw_signature import signature_match
        base = signature_match(template, attacker, defender, graph,
                               current_tick=current_tick)
    else:
        # --- Legacy two-factor path ---
        td_ = THROW_DEFS.get(throw_id)
        if td_ is None:
            return 0.0
        grip_score = 0.5 if graph.satisfies(
            td_.requires, attacker.identity.name, attacker.identity.dominant_side
        ) else 0.0
        from body_state import is_kuzushi
        leg_strength = min(
            attacker.effective_body_part("right_leg"),
            attacker.effective_body_part("left_leg"),
        ) / 10.0
        d_fatigue = 0.5 * (
            defender.state.body["right_leg"].fatigue
            + defender.state.body["left_leg"].fatigue
        )
        d_composure = _composure_mod(defender)
        kuzushi_score = 0.5 if is_kuzushi(
            defender.state.body_state,
            leg_strength=leg_strength,
            fatigue=d_fatigue,
            composure=d_composure,
        ) else 0.0
        base = grip_score + kuzushi_score

    return _apply_stance_preference(base, throw_id, attacker, defender)


# ---------------------------------------------------------------------------
# STANCE PREFERENCE (HAJ-51)
# A throw with a preferred_stance_parity gets a small boost in its preferred
# matchup and a small penalty in the other. Stance-agnostic throws (preference
# None) are unaffected. Magnitude is intentionally modest so the signature
# bias doesn't dominate the four-dimension worked-template score.
# ---------------------------------------------------------------------------
STANCE_PREFERENCE_BOOST:   float = 1.10
STANCE_PREFERENCE_PENALTY: float = 0.85


def _apply_stance_preference(
    base: float, throw_id: "ThrowID", attacker: "Judoka", defender: "Judoka",
) -> float:
    td = THROW_DEFS.get(throw_id)
    if td is None or td.preferred_stance_parity is None:
        return base
    from enums import StanceMatchup
    matchup = StanceMatchup.of(
        attacker.state.current_stance, defender.state.current_stance
    )
    if matchup == td.preferred_stance_parity:
        scaled = base * STANCE_PREFERENCE_BOOST
    else:
        scaled = base * STANCE_PREFERENCE_PENALTY
    return max(0.0, min(1.0, scaled))
