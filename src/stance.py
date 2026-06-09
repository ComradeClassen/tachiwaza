# stance.py
# HAJ-232 Phase 1 — dynamic stance state, comfort vector, and the
# switch-decision model.
#
# Until HAJ-232 a fighter's `current_stance` was frozen at match start and
# never reassigned, so the MATCHED (ai-yotsu) / MIRRORED (kenka-yotsu)
# matchup printed once in the header and never moved. The substrate for a
# *live* matchup already existed — `StanceMatchup.of()` recomputes from the
# two fighters' stances every tick, per-grip `stance_parity` already rewards
# CROSS/PISTOL in MIRRORED, and the unconventional shido clock is wired — but
# the inputs never changed.
#
# This module owns the missing piece: the comfort model and the per-tick
# decision of *whether and why* a fighter shifts stance. Two agencies, per
# the design pass (design-notes/dynamic-stance-and-cross-gripping.md §6.1):
#
#   - deliberate / tactical — a fighter switches to deny the opponent their
#     preferred matchup or to open their own kenka-yotsu game; only into a
#     stance they are competent enough in.
#   - grip-pressure-forced — a fighter losing the grip war gets rotated off
#     their stance involuntarily; the "forced out of comfort" path that the
#     reviewer wants as the experience loop's engine.
#
# The cost of being off-stance is hybrid (§6.2): a short flat *settling
# window* (the visible clumsy beat after a switch) layered on a continuous
# `(1 - comfort)` term (the persistent disadvantage). Both surface as an
# additive penalty on grip initiative via `stance_initiative_penalty`.
#
# Comfort is a *vector* (§6.3): per-stance comfort (orthodox / southpaw) plus
# a separate kenka-yotsu / cross-grip axis, each independently readable and —
# in Phase 3 — independently trainable and gradable. Phase 1 seeds the vector
# belt-gated at match start; the XP accrual that moves it lives in Phase 3.

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from enums import BeltRank, BodyArchetype, Stance, StanceMatchup

if TYPE_CHECKING:
    from judoka import Identity, Judoka, State


# ---------------------------------------------------------------------------
# COMFORT AXES
# ---------------------------------------------------------------------------
# The comfort vector keys. Per-stance comfort answers "how clean is this
# fighter in orthodox / in southpaw"; the kenka-yotsu axis answers "how well
# do they handle the mirrored inside-fight" independent of which stance they
# are standing in.
AXIS_ORTHODOX: str = "orthodox"
AXIS_SOUTHPAW: str = "southpaw"
AXIS_KENKA_YOTSU: str = "kenka_yotsu"

COMFORT_AXES: tuple[str, ...] = (AXIS_ORTHODOX, AXIS_SOUTHPAW, AXIS_KENKA_YOTSU)


def axis_key(stance: Stance) -> str:
    """The per-stance comfort axis for a given stance."""
    return AXIS_ORTHODOX if stance == Stance.ORTHODOX else AXIS_SOUTHPAW


def flip_stance(stance: Stance) -> Stance:
    """The other stance — a switch is always a flip (only two stances exist)."""
    return Stance.SOUTHPAW if stance == Stance.ORTHODOX else Stance.ORTHODOX


# ---------------------------------------------------------------------------
# BELT-GATED INITIAL COMFORT
# ---------------------------------------------------------------------------
# Belt rank gates *initial* flexibility (§3.3): a white belt is comfortable
# only in their base stance and near-helpless off it / in the inside fight; a
# black belt has already paid that tuition and ebbs between stances freely.
# The fraction below maps the BeltRank ladder to 0.0 (WHITE) .. 1.0 (BLACK_5).
_BELT_ORDER: tuple[BeltRank, ...] = (
    BeltRank.WHITE, BeltRank.YELLOW, BeltRank.ORANGE, BeltRank.GREEN,
    BeltRank.BLUE, BeltRank.BROWN, BeltRank.BLACK_1, BeltRank.BLACK_2,
    BeltRank.BLACK_3, BeltRank.BLACK_4, BeltRank.BLACK_5,
)


def _belt_fraction(belt: BeltRank) -> float:
    try:
        idx = _BELT_ORDER.index(belt)
    except ValueError:
        return 0.5
    return idx / (len(_BELT_ORDER) - 1)


# Base-stance comfort is high for everyone (you can always fight your own
# stance); it ticks up slightly with rank. Off-stance and kenka-yotsu comfort
# start near-zero at white and climb with the belt.
_BASE_COMFORT_FLOOR: float = 0.85
_BASE_COMFORT_BELT_GAIN: float = 0.15
_OFFSTANCE_COMFORT_FLOOR: float = 0.05
_OFFSTANCE_COMFORT_BELT_GAIN: float = 0.75
_KENKA_COMFORT_FLOOR: float = 0.10
_KENKA_COMFORT_BELT_GAIN: float = 0.65


def initial_stance_comfort(identity: Optional["Identity"], base_stance: Stance) -> dict:
    """Belt-gated comfort vector at match start.

    `identity.stance_matchup_comfort` (a pre-existing Identity hook) overrides
    any axis it names, so hand-authored fighters — the kenka-yotsu hunter, the
    stance-ambidextrous veteran — can be expressed directly. Without an
    identity (stub fighters in unit tests) we return an empty vector and the
    rest of the system treats the fighter as stance-static.
    """
    if identity is None:
        return {}

    belt = _belt_fraction(identity.belt_rank)
    base_axis = axis_key(base_stance)
    off_axis = AXIS_SOUTHPAW if base_axis == AXIS_ORTHODOX else AXIS_ORTHODOX

    comfort = {
        base_axis: _clamp01(_BASE_COMFORT_FLOOR + _BASE_COMFORT_BELT_GAIN * belt),
        off_axis: _clamp01(_OFFSTANCE_COMFORT_FLOOR + _OFFSTANCE_COMFORT_BELT_GAIN * belt),
        AXIS_KENKA_YOTSU: _clamp01(_KENKA_COMFORT_FLOOR + _KENKA_COMFORT_BELT_GAIN * belt),
    }

    overrides = getattr(identity, "stance_matchup_comfort", None) or {}
    for key, value in overrides.items():
        if key in COMFORT_AXES:
            comfort[key] = _clamp01(float(value))
    return comfort


def comfort_for_stance(state: "State", stance: Stance) -> float:
    """Per-stance comfort, defaulting to fully comfortable when the vector is
    unset so stance-static (identity-less) fighters incur no penalty."""
    return state.stance_comfort.get(axis_key(stance), 1.0)


# ---------------------------------------------------------------------------
# HYBRID SWITCH COST  (§6.2)
# ---------------------------------------------------------------------------
# Number of ticks the clumsy "settling" window lasts after a switch. During
# it the fighter pays the flat settling penalty on top of the continuous
# discomfort term, and may not switch again (you can't fluently re-switch
# mid-settle).
STANCE_SETTLING_TICKS: int = 4

# Initiative-score penalties (the score sums to roughly 0–6, so these are
# meaningful without being crippling — see grip_initiative._InitiativeWeights).
_SETTLING_INIT_PENALTY: float = 0.8      # flat, while settling
_OFFSTANCE_INIT_WEIGHT: float = 0.6      # × (1 - comfort[current stance])
_KENKA_INIT_WEIGHT: float = 0.4          # × (1 - kenka comfort), MIRRORED only


def stance_initiative_penalty(judoka: "Judoka", matchup: StanceMatchup) -> float:
    """Additive grip-initiative penalty (>= 0) from being off-comfort.

    Subtracted from the fighter's sampled initiative so a fighter who has just
    switched, or who is standing in a low-comfort stance, reaches more slowly —
    the persistent disadvantage that carries the experience story. Returns 0.0
    for stance-static fighters (empty comfort vector)."""
    state = judoka.state
    if not state.stance_comfort:
        return 0.0

    penalty = 0.0
    if state.stance_settling_ticks > 0:
        penalty += _SETTLING_INIT_PENALTY
    cur_comfort = comfort_for_stance(state, state.current_stance)
    penalty += _OFFSTANCE_INIT_WEIGHT * (1.0 - cur_comfort)
    if matchup == StanceMatchup.MIRRORED:
        kenka = state.stance_comfort.get(AXIS_KENKA_YOTSU, 1.0)
        penalty += _KENKA_INIT_WEIGHT * (1.0 - kenka)
    return penalty


# ---------------------------------------------------------------------------
# SWITCH DECISION  (§6.1)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class StanceSwitchDecision:
    target: Stance
    reason: str   # "tactical" | "grip_pressure"


# Forced trigger: the opponent's grip advantage (compute_grip_delta) above
# which being rotated off-stance becomes possible, and the span over which
# severity saturates.
_FORCED_GRIP_DELTA_THRESHOLD: float = 0.6
_FORCED_GRIP_DELTA_SPAN: float = 1.4
_FORCED_BASE_P: float = 0.12   # per-tick ceiling at full severity, zero resistance

# Tactical trigger: you only deliberately rotate into a stance you can fight,
# and the urge is diffuse per tick (it accumulates over an exchange).
_TACTICAL_MIN_TARGET_COMFORT: float = 0.45
_TACTICAL_NEUTRAL: float = 0.5
_TACTICAL_BASE_P: float = 0.06
_TACTICAL_ARCH_FACTOR: dict = {
    BodyArchetype.GRIP_FIGHTER: 1.5,   # owns the grip war; seeks the fight it wants
    BodyArchetype.EXPLOSIVE:    1.2,   # sets up their own entry
    BodyArchetype.MOTOR:        1.0,
    BodyArchetype.LEVER:        0.9,
    BodyArchetype.GROUND_SPECIALIST: 0.7,
}


def _composure_fraction(judoka: "Judoka") -> float:
    ceiling = float(judoka.capability.composure_ceiling)
    if ceiling <= 0:
        return 1.0
    return _clamp01(judoka.state.composure_current / ceiling)


def evaluate_switch(
    judoka: "Judoka",
    opponent: "Judoka",
    *,
    matchup: StanceMatchup,
    grip_delta_against: float,
    rng,
) -> Optional[StanceSwitchDecision]:
    """Decide whether `judoka` changes stance this tick.

    `grip_delta_against` is the opponent's grip advantage over this fighter
    (`compute_grip_delta(opponent, judoka, matchup)`): positive means this
    fighter is losing the grip war. `rng` is an independently-seeded
    `random.Random` so the decision never perturbs other RNG streams.

    Returns a decision, or None for "hold stance". Forced (pressure) is checked
    before tactical, but a fighter mid-settle holds — you can't re-switch while
    still clumsy from the last one.
    """
    state = judoka.state
    if not state.stance_comfort:
        return None   # stance-static fighter (no identity / comfort)
    if state.stance_settling_ticks > 0:
        return None   # locked out mid-settle

    current = state.current_stance
    target = flip_stance(current)
    fight_iq = judoka.capability.fight_iq / 10.0

    # --- Forced (grip-pressure) trigger -------------------------------------
    if grip_delta_against >= _FORCED_GRIP_DELTA_THRESHOLD:
        severity = _clamp01(
            (grip_delta_against - _FORCED_GRIP_DELTA_THRESHOLD) / _FORCED_GRIP_DELTA_SPAN
        )
        # Resistance to being steered: anchored in current-stance comfort, your
        # ring IQ, and composure. A rattled novice off his comfort gets rotated;
        # a composed veteran holds his feet.
        resist = (
            0.4 * comfort_for_stance(state, current)
            + 0.4 * fight_iq
            + 0.2 * _composure_fraction(judoka)
        )
        p_forced = _FORCED_BASE_P * severity * (1.0 - resist)
        if rng.random() < p_forced:
            return StanceSwitchDecision(target=target, reason="grip_pressure")

    # --- Tactical (deliberate) trigger --------------------------------------
    target_comfort = comfort_for_stance(state, target)
    if target_comfort >= _TACTICAL_MIN_TARGET_COMFORT:
        kenka = state.stance_comfort.get(AXIS_KENKA_YOTSU, 0.0)
        # Flipping one fighter flips the matchup. In MATCHED, switching forces
        # MIRRORED (the kenka-yotsu hunter's desire = their kenka comfort); in
        # MIRRORED, switching restores MATCHED (desire = 1 - kenka comfort).
        if matchup == StanceMatchup.MATCHED:
            desire = kenka
        else:
            desire = 1.0 - kenka
        incentive = max(0.0, desire - _TACTICAL_NEUTRAL)
        arch_factor = _TACTICAL_ARCH_FACTOR.get(judoka.identity.body_archetype, 1.0)
        p_tactical = (
            _TACTICAL_BASE_P * incentive * fight_iq * arch_factor * target_comfort
        )
        if rng.random() < p_tactical:
            return StanceSwitchDecision(target=target, reason="tactical")

    return None


# ---------------------------------------------------------------------------
# NARRATION  (§6.7 — live stance thread)
# ---------------------------------------------------------------------------
def matchup_nickname(matchup: StanceMatchup) -> str:
    return "ai-yotsu" if matchup == StanceMatchup.MATCHED else "kenka-yotsu"


def stance_change_coach_prose(
    name: str, target: Stance, matchup_after: StanceMatchup, reason: str,
) -> str:
    """Mat-side line for a stance switch — the running stance thread the
    static header used to stand in for."""
    stance_word = target.name.lower()
    if reason == "tactical":
        if matchup_after == StanceMatchup.MIRRORED:
            return f"{name} drops into {stance_word}, forcing the cross-grip fight."
        return f"{name} squares back to {stance_word} to take away the inside angle."
    # grip_pressure
    return f"{name} gets steered off his feet, rotated into {stance_word}."


def _clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x
