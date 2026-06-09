# grip_initiative.py
# HAJ-151 — grip-race initiative scoring + response cascade.
# HAJ-226 — added the sixth response kind, ACCEPT_BAIT (the counter-fighter
# who deliberately does not strip). The model below is now six-branch.
#
# Each grip-fight phase opens with both fighters computing an *initiative
# score* — a weighted combination of aggressive↔patient facet, body
# archetype, fight_iq, composure, height-derived reach proxy, fatigue,
# and intra-match familiarity. The fighter with the higher score reaches
# first; the other perceives via HAJ-149 and picks one of six response
# types (contest / match / pursue-own / defensive / disengage / accept-bait).
#
# Three weight tables are active:
#   - MATCHED stance — base weights. Aggressive is the largest factor.
#   - MIRRORED stance — patience-rewarded variant. Fight_iq grows,
#     aggressive shrinks, GRIP_FIGHTER's archetype bonus shrinks.
#   - CLOCK_PRESSURE — situational overlay applied to either base when
#     match clock < CLOCK_PRESSURE_TICKS_REMAINING and a score
#     differential is non-zero. The trailing fighter gets an aggressive
#     boost; the leading fighter gets a defensive-bias modifier on
#     response-type selection (not on raw initiative).
#
# Calibration is v0.2 — v0.1 ships with a reasonable starting balance
# good enough for the AC#11 regression suite.

from __future__ import annotations
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from enums import BodyArchetype, StanceMatchup

if TYPE_CHECKING:
    from judoka import Judoka


# ---------------------------------------------------------------------------
# RESPONSE KINDS
# ---------------------------------------------------------------------------
RESP_CONTEST:     str = "CONTEST"      # frame the bicep / parry the hand / slap-down
RESP_MATCH:       str = "MATCH"        # mirror leader's reach (sleeve-and-lapel symmetric)
RESP_PURSUE_OWN:  str = "PURSUE_OWN"   # commit to own preferred grip; ignore leader
RESP_DEFENSIVE:   str = "DEFENSIVE"    # frame-and-deny; no own grip seated
RESP_DISENGAGE:   str = "DISENGAGE"    # backstep; reset to STANDING_DISTANT
RESP_ACCEPT_BAIT: str = "ACCEPT_BAIT"  # HAJ-226 — counter-fighter who deliberately
#                                        does NOT strip; lets the leader's grip stand
#                                        and loads a counter off the committed arm.

ALL_RESPONSE_KINDS: tuple[str, ...] = (
    RESP_CONTEST, RESP_MATCH, RESP_PURSUE_OWN, RESP_DEFENSIVE, RESP_DISENGAGE,
    RESP_ACCEPT_BAIT,
)


# ---------------------------------------------------------------------------
# CLOCK-PRESSURE THRESHOLD
# ---------------------------------------------------------------------------
# Match clock under this many ticks remaining + non-zero score differential
# triggers the clock-pressure overlay. v0.1 uses 30 ticks (= 30 seconds of
# regulation at 1-tick-per-second; the spec's "final 30 seconds" floor).
CLOCK_PRESSURE_TICKS_REMAINING: int = 30


# ---------------------------------------------------------------------------
# WEIGHT TABLES
# ---------------------------------------------------------------------------
# Each weight is the score contribution at the *full-strength* axis value
# (e.g., aggressive=10 → +1.0 * weight; archetype hits the named archetype's
# bonus row). The base table sums to roughly 0–6 for a strong configuration;
# the noise std is calibrated against this scale (see SCORE_NOISE_STD below).
@dataclass(frozen=True)
class _InitiativeWeights:
    aggressive:        float
    fight_iq:          float
    composure:         float
    height:            float
    fatigue_penalty:   float
    familiarity:       float
    archetype:         dict[BodyArchetype, float]


_BASE_ARCHETYPE: dict[BodyArchetype, float] = {
    BodyArchetype.GRIP_FIGHTER:      1.5,   # owns the grip war
    BodyArchetype.MOTOR:             0.6,   # relentless pressure
    BodyArchetype.EXPLOSIVE:         0.5,   # patient build, but not slow
    BodyArchetype.LEVER:             0.4,   # reach advantage on lead grip
    BodyArchetype.GROUND_SPECIALIST: -0.2,  # neutral-to-slight-negative on standing
}

_MIRRORED_ARCHETYPE: dict[BodyArchetype, float] = {
    # In mirrored stance, the asymmetric foot/hand placement makes reading
    # more important than reaching. GRIP_FIGHTER's bonus shrinks; the others
    # stay roughly flat.
    BodyArchetype.GRIP_FIGHTER:      0.8,
    BodyArchetype.MOTOR:             0.5,
    BodyArchetype.EXPLOSIVE:         0.5,
    BodyArchetype.LEVER:             0.3,
    BodyArchetype.GROUND_SPECIALIST: -0.2,
}


MATCHED_WEIGHTS = _InitiativeWeights(
    aggressive=2.0,
    fight_iq=1.0,
    composure=1.0,
    height=0.4,
    fatigue_penalty=0.6,
    familiarity=0.3,
    archetype=_BASE_ARCHETYPE,
)

MIRRORED_WEIGHTS = _InitiativeWeights(
    aggressive=1.0,         # shrunk
    fight_iq=2.0,           # grown
    composure=1.0,
    height=0.4,
    fatigue_penalty=0.6,
    familiarity=0.3,
    archetype=_MIRRORED_ARCHETYPE,
)


# Clock-pressure overlay — applied on top of either base. The trailing
# fighter (chasing a score) gets a sizable aggressive-weight bonus;
# the leading fighter gets a smaller penalty (their initiative isn't
# crippled, just nudged toward defense).
CLOCK_PRESSURE_TRAILING_BOOST: float = 1.0
CLOCK_PRESSURE_LEADING_PENALTY: float = 0.4


# Noise scale on the final score. Two fighters with similar attributes
# still produce *different* scores per exchange — sometimes A wins,
# sometimes B — but the higher-expected-value fighter wins more grip
# races over a tournament.
SCORE_NOISE_STD: float = 0.6


# Reference scale for height differentials. A 30-cm gap (extreme by
# weight-class standards) maps to one full unit of the height axis;
# typical gaps stay within a fraction of a unit.
HEIGHT_DIFFERENTIAL_SCALE_CM: float = 30.0


# ---------------------------------------------------------------------------
# AXIS HELPERS
# ---------------------------------------------------------------------------
def _aggressive_frac(j: "Judoka") -> float:
    """Return the aggressive facet on a [0, 1] scale; 5 is neutral."""
    raw = float(j.identity.personality_facets.get("aggressive", 5))
    return max(0.0, min(1.0, raw / 10.0))


def _loyal_to_plan_frac(j: "Judoka") -> float:
    raw = float(j.identity.personality_facets.get("loyal_to_plan", 5))
    return max(0.0, min(1.0, raw / 10.0))


def _composure_frac(j: "Judoka") -> float:
    ceiling = max(1.0, float(j.capability.composure_ceiling))
    return max(0.0, min(1.0, j.state.composure_current / ceiling))


def _fatigue_frac(j: "Judoka") -> float:
    return max(0.0, min(1.0, 1.0 - float(j.state.cardio_current)))


# ---------------------------------------------------------------------------
# INITIATIVE SCORE
# ---------------------------------------------------------------------------
def expected_initiative(
    judoka: "Judoka",
    opponent: "Judoka",
    *,
    stance_matchup: StanceMatchup = StanceMatchup.MATCHED,
    clock_pressure_role: Optional[str] = None,  # None | "trailing" | "leading"
    fatigue_frac: Optional[float] = None,
    familiarity_delta: int = 0,
) -> float:
    """Compute the expected (mean) initiative score before noise. The
    score is a weighted sum of axes; higher means "reaches first more
    often" in a grip-race draw between the two fighters.

    `familiarity_delta` is the (positive or negative) running tally of
    grip exchanges this fighter has won minus lost so far in the match.
    A small bonus for momentum; capped externally by callers if needed.
    """
    weights = (MIRRORED_WEIGHTS if stance_matchup == StanceMatchup.MIRRORED
               else MATCHED_WEIGHTS)

    score = 0.0
    score += _aggressive_frac(judoka) * weights.aggressive
    score += weights.archetype.get(judoka.identity.body_archetype, 0.0)
    score += float(judoka.capability.fight_iq) / 10.0 * weights.fight_iq
    score += _composure_frac(judoka) * weights.composure

    height_delta = (
        (judoka.identity.height_cm - opponent.identity.height_cm)
        / HEIGHT_DIFFERENTIAL_SCALE_CM
    )
    score += height_delta * weights.height

    if fatigue_frac is None:
        fatigue_frac = _fatigue_frac(judoka)
    score -= fatigue_frac * weights.fatigue_penalty

    score += familiarity_delta * weights.familiarity

    # Clock pressure — applies on top of the base table.
    if clock_pressure_role == "trailing":
        score += CLOCK_PRESSURE_TRAILING_BOOST
    elif clock_pressure_role == "leading":
        score -= CLOCK_PRESSURE_LEADING_PENALTY

    return score


def sample_initiative(
    judoka: "Judoka",
    opponent: "Judoka",
    *,
    rng: Optional[random.Random] = None,
    **kwargs,
) -> float:
    """Sample initiative from a Gaussian centered on expected_initiative.
    The noise std is fixed; calibration is v0.2."""
    r = rng if rng is not None else random
    mu = expected_initiative(judoka, opponent, **kwargs)
    return mu + r.gauss(0.0, SCORE_NOISE_STD)


# ---------------------------------------------------------------------------
# CLOCK-PRESSURE ROLE INFERENCE
# ---------------------------------------------------------------------------
def clock_pressure_roles(
    fighter_a: "Judoka", fighter_b: "Judoka",
    *, current_tick: int, max_ticks: int,
    a_score: dict, b_score: dict,
) -> tuple[Optional[str], Optional[str]]:
    """Compute the (a_role, b_role) clock-pressure roles.

    Returns ('trailing', 'leading') / ('leading', 'trailing') / (None, None).
    None when clock-pressure is not active (clock too high or no score
    differential).
    """
    ticks_remaining = max_ticks - current_tick
    if ticks_remaining > CLOCK_PRESSURE_TICKS_REMAINING:
        return None, None

    a_total = (1000 if a_score.get("ippon") else 0) + a_score.get("waza_ari", 0)
    b_total = (1000 if b_score.get("ippon") else 0) + b_score.get("waza_ari", 0)
    if a_total == b_total:
        return None, None
    if a_total > b_total:
        return "leading", "trailing"
    return "trailing", "leading"


# ---------------------------------------------------------------------------
# RESPONSE SELECTION (six branches — HAJ-151 five + HAJ-226 ACCEPT_BAIT)
# ---------------------------------------------------------------------------
@dataclass
class GripResponseChoice:
    kind: str
    weights: dict[str, float]
    rolled: float
    notes: str = ""


# Base probability weights — these are the *starting* weights before
# attribute / context modulation. v0.1 keeps them deliberately diffuse
# so the modulation steps below carry the per-fighter signature; v0.2
# can tighten them after calibration.
_BASE_RESPONSE_WEIGHTS: dict[str, float] = {
    RESP_CONTEST:     1.0,
    RESP_MATCH:       1.5,
    RESP_PURSUE_OWN:  1.0,
    RESP_DEFENSIVE:   0.7,
    RESP_DISENGAGE:   0.5,
    # HAJ-226 — ACCEPT_BAIT is a specialist read: low base weight, lifted
    # hard by counter-archetype / patience / fight_iq / composure in the
    # modulation step and damped by clock pressure and fatigue. Lowest of
    # the six by design — only the right fighter in the right moment picks it.
    RESP_ACCEPT_BAIT: 0.4,
}


def _modulate_response_weights(
    follower: "Judoka",
    leader: "Judoka",
    *,
    stance_matchup: StanceMatchup,
    clock_pressure_role: Optional[str],
    perception_specificity: float,
) -> dict[str, float]:
    w = dict(_BASE_RESPONSE_WEIGHTS)

    arch = follower.identity.body_archetype

    # Archetype biases.
    #
    # HAJ-226 — ACCEPT_BAIT splits the archetypes into "proactive" (GRIP_FIGHTER
    # contests, MOTOR pressures — they take the grip war to the opponent and
    # rarely concede a grip on purpose) and "counter-leaning" (LEVER counters
    # off the opponent's commitment, EXPLOSIVE waits to capitalize, and
    # GROUND_SPECIALIST is happy to be gripped on the way to the mat). The
    # latter group is where "give them the grip, take the reaction" lives.
    if arch == BodyArchetype.GRIP_FIGHTER:
        w[RESP_CONTEST]     *= 1.6   # GRIP_FIGHTER prefers contest
        w[RESP_MATCH]       *= 1.2
        w[RESP_DEFENSIVE]   *= 0.8
        w[RESP_DISENGAGE]   *= 0.7
        w[RESP_ACCEPT_BAIT] *= 0.5   # contests the grip; rarely concedes it
    elif arch == BodyArchetype.EXPLOSIVE:
        w[RESP_PURSUE_OWN]  *= 1.8   # EXPLOSIVE pursues their own setup
        w[RESP_CONTEST]     *= 0.7
        w[RESP_MATCH]       *= 0.8
        w[RESP_ACCEPT_BAIT] *= 1.8   # patient build → capitalize on the commit
    elif arch == BodyArchetype.MOTOR:
        w[RESP_CONTEST]     *= 1.3
        w[RESP_DISENGAGE]   *= 0.6
        w[RESP_ACCEPT_BAIT] *= 0.5   # pressures forward; doesn't sit on a counter
    elif arch == BodyArchetype.LEVER:
        w[RESP_PURSUE_OWN]  *= 1.2
        w[RESP_DEFENSIVE]   *= 1.1
        w[RESP_ACCEPT_BAIT] *= 1.5   # counters off the opponent's commitment
    elif arch == BodyArchetype.GROUND_SPECIALIST:
        w[RESP_DEFENSIVE]   *= 1.4
        w[RESP_PURSUE_OWN]  *= 1.1
        w[RESP_CONTEST]     *= 0.8
        w[RESP_ACCEPT_BAIT] *= 1.4   # accepts the grip on the way to the mat

    # Aggressive facet — high aggressive prefers contest/match; low aggressive prefers defensive/disengage.
    aggr = _aggressive_frac(follower)
    w[RESP_CONTEST]   *= 0.5 + aggr
    w[RESP_MATCH]     *= 0.7 + 0.6 * aggr
    w[RESP_DEFENSIVE] *= 1.5 - aggr
    w[RESP_DISENGAGE] *= 1.5 - aggr
    # HAJ-226 — accepting the bait is a patient read, not a passive one: the
    # counter-fighter is calm, not rushing to contest. Patient profiles favor
    # it (×1.3 at aggressive=0), aggressive ones shun it (×0.7 at aggressive=10).
    w[RESP_ACCEPT_BAIT] *= 0.7 + 0.6 * (1.0 - aggr)

    # Loyal-to-plan — high loyal_to_plan prefers disengage when the
    # engagement is unfavorable (don't get drawn into a grip war you
    # can't win). Approximates by reading initiative deficit via the
    # leader's archetype bonus relative to follower's.
    loyal = _loyal_to_plan_frac(follower)
    leader_arch_bonus = _BASE_ARCHETYPE.get(leader.identity.body_archetype, 0.0)
    follower_arch_bonus = _BASE_ARCHETYPE.get(arch, 0.0)
    if leader_arch_bonus > follower_arch_bonus + 0.3:
        # Unfavorable: high-loyal_to_plan boosts disengage.
        w[RESP_DISENGAGE] *= 1.0 + loyal * 0.8

    # Fight_iq — high IQ uses targeted responses (contest, defensive,
    # disengage); low IQ defaults to safe MATCH.
    iq = float(follower.capability.fight_iq) / 10.0
    if iq < 0.4:
        w[RESP_MATCH] *= 1.5
        w[RESP_DISENGAGE] *= 0.5   # novices don't read engagement well enough
        w[RESP_DEFENSIVE] *= 0.7
        w[RESP_ACCEPT_BAIT] *= 0.4  # HAJ-226 — baiting needs a read novices lack
    elif iq > 0.7:
        w[RESP_CONTEST] *= 1.2
        w[RESP_DISENGAGE] *= 1.2   # elite reads when to bail
        w[RESP_ACCEPT_BAIT] *= 1.4  # HAJ-226 — and reads when to invite the grip

    # Composure — low composure (panicked) reaches for the safe MATCH /
    # DEFENSIVE; high composure reads more freely.
    comp = _composure_frac(follower)
    if comp < 0.4:
        w[RESP_MATCH]     *= 1.3
        w[RESP_DEFENSIVE] *= 1.2
        w[RESP_CONTEST]   *= 0.8
        # HAJ-226 — inviting the grip while loading a counter takes nerve;
        # a rattled fighter strips or frames on reflex instead.
        w[RESP_ACCEPT_BAIT] *= 0.6
    elif comp > 0.7:
        # Composed fighters can afford the patient counter posture.
        w[RESP_ACCEPT_BAIT] *= 1.3

    # Mirrored-stance bias — patience-rewarded variant: contest is
    # less preferred (crossing-grip contest is messy), defensive and
    # pursue-own go up.
    if stance_matchup == StanceMatchup.MIRRORED:
        w[RESP_CONTEST]    *= 0.8
        w[RESP_DEFENSIVE]  *= 1.2
        w[RESP_PURSUE_OWN] *= 1.2
        # HAJ-226 — the patience-rewarded variant rewards the bait too:
        # letting the cross stand and countering off it is a patient read,
        # and crossing-grip contest is messy enough to make accepting it
        # the cleaner counter.
        w[RESP_ACCEPT_BAIT] *= 1.3

    # Clock-pressure modifier on response selection (per the spec's
    # "leading fighter gets defensive-bias modifier on response-type
    # selection, not raw initiative").
    if clock_pressure_role == "leading":
        w[RESP_DEFENSIVE] *= 1.6
        w[RESP_DISENGAGE] *= 1.6
        w[RESP_CONTEST]   *= 0.7
    elif clock_pressure_role == "trailing":
        w[RESP_CONTEST]   *= 1.3
        w[RESP_DISENGAGE] *= 0.5
    # HAJ-226 — either way, the clock kills the patient counter: a leader
    # protecting a lead won't gift a grip, and a trailing fighter needs the
    # grip now, not a reaction two beats later.
    if clock_pressure_role in ("leading", "trailing"):
        w[RESP_ACCEPT_BAIT] *= 0.5

    # HAJ-226 — fatigue damps the bait: loading a counter off a conceded grip
    # is metabolically expensive, and a gassed fighter strips/frames instead.
    fatigue_frac = _fatigue_frac(follower)
    w[RESP_ACCEPT_BAIT] *= max(0.3, 1.0 - 0.6 * fatigue_frac)

    # Perception specificity — vague perception (high tori disguise)
    # pushes the perceiver toward the *safer* responses.
    if perception_specificity < 0.3:
        w[RESP_MATCH]     *= 1.3
        w[RESP_DEFENSIVE] *= 1.2
        w[RESP_DISENGAGE] *= 1.2
        w[RESP_CONTEST]   *= 0.6
        # HAJ-226 — you can't bait a commit you can't read; vague perception
        # makes the accept-and-counter posture a gamble, so down it goes.
        w[RESP_ACCEPT_BAIT] *= 0.6

    return w


def select_response(
    follower: "Judoka",
    leader: "Judoka",
    *,
    stance_matchup: StanceMatchup = StanceMatchup.MATCHED,
    clock_pressure_role: Optional[str] = None,
    perception_specificity: float = 0.5,
    rng: Optional[random.Random] = None,
) -> GripResponseChoice:
    """Pick one of the six response kinds via weighted random.

    Weights are computed by `_modulate_response_weights`; the weighted
    pick is over the (kind, weight) pairs. Returns a GripResponseChoice
    with the modulated weights and the rolled fraction so callers can
    log the decision (AC#11 "decision is logged").
    """
    r = rng if rng is not None else random
    weights = _modulate_response_weights(
        follower, leader,
        stance_matchup=stance_matchup,
        clock_pressure_role=clock_pressure_role,
        perception_specificity=perception_specificity,
    )
    total = sum(weights.values())
    if total <= 0.0:
        return GripResponseChoice(
            kind=RESP_MATCH, weights=weights, rolled=0.0,
            notes="degenerate weights; fell back to MATCH",
        )
    roll = r.uniform(0.0, total)
    rolled_frac = roll / total
    cumulative = 0.0
    for kind in ALL_RESPONSE_KINDS:
        cumulative += weights[kind]
        if roll <= cumulative:
            return GripResponseChoice(
                kind=kind, weights=weights, rolled=rolled_frac,
            )
    # Float drift fallback.
    return GripResponseChoice(
        kind=RESP_MATCH, weights=weights, rolled=rolled_frac,
        notes="float drift; fell back to MATCH",
    )
