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
# ACTUAL-SIGNATURE MATCH (v0.1)
# The true 0.0–1.0 match for a throw given current match state. v0.1 composes
# two simple factors — grip prerequisites satisfied, and defender in kuzushi.
# Part 4 will replace this with the four-dimension signature (grips × posture
# × velocity × reap-contact).
# ---------------------------------------------------------------------------
def actual_signature_match(
    throw_id: ThrowID,
    attacker: "Judoka",
    defender: "Judoka",
    graph: "GripGraph",
) -> float:
    """Ground-truth signature match in [0, 1].

    Two 0.5-weight factors:
      - grip graph satisfies the throw's EdgeRequirements
      - defender is in kuzushi (CoM outside recoverable envelope)
    """
    td = THROW_DEFS.get(throw_id)
    if td is None:
        return 0.0

    grip_score = 0.5 if graph.satisfies(
        td.requires, attacker.identity.name, attacker.identity.dominant_side
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

    return grip_score + kuzushi_score
