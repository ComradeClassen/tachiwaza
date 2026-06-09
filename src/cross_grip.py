# cross_grip.py
# HAJ-238 Phase 2 — cross-grip + pistol cascade seating (kenka-yotsu).
#
# Phase 1 (HAJ-232 / stance.py) made the MATCHED (ai-yotsu) / MIRRORED
# (kenka-yotsu) matchup *live* — a fighter can now rotate stance mid-match. This
# module owns the grip-target choice that the mirrored fight finally enables:
# when stances are kenka-yotsu the lead hands collide, and a fighter can reach
# **across** for the CROSS grip (the "wrong"-hand same-side lapel) or clamp a
# PISTOL sleeve-cuff (sode-tori) instead of the orthodox opposite-lapel tsurite.
#
# The substrate is all there already:
#   - force_envelope.stance_parity rewards these in MIRRORED (CROSS 0.80/1.25,
#     PISTOL 0.85/1.20) and punishes them in MATCHED, so compute_grip_delta
#     already expresses the leverage shift once the edge is seated.
#   - GripTypeV2.is_unconventional() flags CROSS/PISTOL/BELT and the per-grip
#     unconventional_clock draws a passivity shido if the grip doesn't lead to
#     an attack — exactly real judo's "attack off the cross or concede" rule.
#
# What was missing — and what this module decides — is *when a fighter elects
# one*. Three drivers, per design-notes/dynamic-stance-and-cross-gripping.md §4:
#
#   - Fluent inside game (§4.2/§4.3) — a GRIP_FIGHTER or high-fight_iq judoka,
#     comfortable in the kenka-yotsu inside fight, reaches for the cross to win
#     the lead-hand battle. Gated by the kenka-yotsu comfort axis: a fighter
#     clumsy in the stance does not fluently cross-grip.
#   - Disruptor (§4.4) — a fighter *losing* the grip war throws on a cross to
#     break the dominant opponent's rhythm. It threatens an immediate attack and
#     carries the shido clock against the gripper, so it can't be ignored; the
#     dominant fighter must divert to stripping it. A momentum lever for the
#     losing side, so the comfort gate relaxes (desperation reaches lower).
#   - Sode setup (§4.5) — a fighter whose game is sode-tsurikomi-goshi (flagged
#     via identity.style_dna["sode_setup_tendency"]) seats a PISTOL sleeve-cuff
#     as the entry to it.
#
# And the experienced counter (§4.4): a skilled fighter facing the opponent's
# cross doesn't take the bait — they route through the scramble back to their
# *preferred* orthodox grip. That surfaces here as the `converts` flag, which
# the cascade narrates.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from enums import (
    BodyArchetype, DominantSide, GripTarget, GripTypeV2, StanceMatchup,
)
from stance import AXIS_KENKA_YOTSU

if TYPE_CHECKING:
    import random
    from judoka import Judoka


# ---------------------------------------------------------------------------
# GRIP-TARGET PLANS
# ---------------------------------------------------------------------------
PLAN_ORTHODOX: str = "ORTHODOX"   # opposite-lapel tsurite — the symmetric default
PLAN_CROSS:    str = "CROSS"      # katate-ai-gumi — reach across to the same-side lapel
PLAN_PISTOL:   str = "PISTOL"     # sode-tori — sleeve-cuff clamp

ALL_PLANS: tuple[str, ...] = (PLAN_ORTHODOX, PLAN_CROSS, PLAN_PISTOL)


@dataclass
class LeadGripChoice:
    """The lead-hand grip a fighter elects for an exchange."""
    plan: str                       # ORTHODOX | CROSS | PISTOL
    grip_type: GripTypeV2           # LAPEL_HIGH | CROSS | PISTOL
    disruptor: bool = False         # a losing-fighter cross thrown to break rhythm
    converts: bool = False          # skilled fighter routing back to preferred grip
    weights: dict = field(default_factory=dict)
    notes: str = ""


# ---------------------------------------------------------------------------
# TUNING (v0.1 — Phase 3 calibrates against telemetry)
# ---------------------------------------------------------------------------
# Orthodox is the heavy default; cross / pistol are *reached for*. The base
# orthodox weight sets the floor election rate — a fluent black-belt LEVER lands
# a cross perhaps ~1 exchange in 5 in kenka-yotsu, a GRIP_FIGHTER more, a novice
# almost never.
_ORTHODOX_BASE_WEIGHT: float = 3.0

# Kenka-yotsu comfort gates. Below the fluent gate a fighter is too clumsy in
# the inside fight to *electively* cross-grip; the disruptor gate is lower
# because desperation reaches for the lever even when the hands aren't clean.
_FLUENT_KENKA_GATE:    float = 0.35
_DISRUPTOR_KENKA_GATE: float = 0.20

# Cross-grip weight scales.
_CROSS_FLUENT_WEIGHT:  float = 2.0   # × aptitude, for the fluent inside cross
_CROSS_DISRUPT_WEIGHT: float = 2.4   # × disruption severity, for the losing-fighter cross

# Pistol weight scales.
_PISTOL_SODE_WEIGHT:   float = 2.2   # × aptitude, for the sode-tsurikomi setup
_PISTOL_INSIDE_WEIGHT: float = 0.5   # × aptitude, generic pistol inside option

# Disruptor pressure band — `grip_pressure` is the opponent's grip advantage
# (compute_grip_delta(opponent, fighter)). Below the floor there's nothing to
# disrupt; severity saturates across the span.
_DISRUPT_PRESSURE_FLOOR: float = 0.6
_DISRUPT_PRESSURE_SPAN:  float = 1.4

# "Skilled enough to route through a scramble back to the preferred grip" — the
# experienced-counter threshold on (fight_iq × kenka comfort). A solid black-belt
# (iq 8, kenka ~0.49 → 0.39) clears it; a mid-IQ fighter does not.
_CONVERT_SKILL_THRESHOLD: float = 0.35

# Archetype tilt for reaching into the kenka-yotsu cross/pistol fight.
_ARCH_INSIDE_FACTOR: dict = {
    BodyArchetype.GRIP_FIGHTER:      1.6,   # owns the grip war; lives for the inside fight
    BodyArchetype.LEVER:             1.1,   # long lead hand reaches the cross well
    BodyArchetype.EXPLOSIVE:         1.0,
    BodyArchetype.MOTOR:             0.9,
    BodyArchetype.GROUND_SPECIALIST: 0.7,
}


# ---------------------------------------------------------------------------
# AXIS HELPERS
# ---------------------------------------------------------------------------
def _kenka_comfort(fighter: "Judoka") -> float:
    """The fighter's kenka-yotsu / cross-grip comfort (0–1). Defaults to 0.0
    for a stance-static fighter (empty vector) — no comfort, no fluent cross."""
    return float(fighter.state.stance_comfort.get(AXIS_KENKA_YOTSU, 0.0))


def _fight_iq_frac(fighter: "Judoka") -> float:
    return max(0.0, min(1.0, float(fighter.capability.fight_iq) / 10.0))


def _sode_tendency(fighter: "Judoka") -> float:
    dna = getattr(fighter.identity, "style_dna", None) or {}
    return max(0.0, min(1.0, float(dna.get("sode_setup_tendency", 0.0))))


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


# ---------------------------------------------------------------------------
# LEAD-GRIP PLACEMENT
# ---------------------------------------------------------------------------
def lead_grip_placement(plan: str, dominant_side: DominantSide) -> tuple:
    """Resolve (grip_type_v2, target_location, hand_key) for the lead-hand grip
    a fighter seats under `plan`, from their dominant side.

    Orthodox lead is the dominant hand on the *opposite* lapel (the tsurite).
    The cross reaches the *same-side* lapel — the "wrong"-hand katate-ai-gumi
    that breaks the symmetric geometry. The pistol clamps the opposite sleeve
    cuff (sode-tori).
    """
    is_right = dominant_side == DominantSide.RIGHT
    hand_key = "right_hand" if is_right else "left_hand"
    if plan == PLAN_CROSS:
        target = GripTarget.RIGHT_LAPEL if is_right else GripTarget.LEFT_LAPEL
        return GripTypeV2.CROSS, target, hand_key
    if plan == PLAN_PISTOL:
        target = GripTarget.LEFT_SLEEVE if is_right else GripTarget.RIGHT_SLEEVE
        return GripTypeV2.PISTOL, target, hand_key
    # Orthodox tsurite — opposite lapel.
    target = GripTarget.LEFT_LAPEL if is_right else GripTarget.RIGHT_LAPEL
    return GripTypeV2.LAPEL_HIGH, target, hand_key


# ---------------------------------------------------------------------------
# LEAD-GRIP SELECTION  (§4.2 / §4.4 / §4.5)
# ---------------------------------------------------------------------------
def select_lead_grip(
    fighter: "Judoka",
    opponent: "Judoka",
    *,
    matchup: StanceMatchup,
    grip_pressure: float = 0.0,
    facing_unconventional: bool = False,
    rng: "random.Random",
) -> LeadGripChoice:
    """Decide which lead-hand grip `fighter` reaches for this exchange.

    `grip_pressure` is the opponent's grip advantage over `fighter`
    (compute_grip_delta(opponent, fighter, matchup)); positive means the fighter
    is losing the grip war and the disruptor cross becomes attractive.
    `facing_unconventional` is True when the opponent already holds a CROSS or
    PISTOL grip — a skilled fighter routes through that scramble back to their
    own preferred grip (the `converts` flag) rather than answer cross with cross.

    The cross-grip game is a MIRRORED-only phenomenon: in MATCHED stance the
    geometry (and stance_parity) punishes it, so the function returns orthodox
    outright. Returns a LeadGripChoice; `plan == PLAN_ORTHODOX` is the default.
    """
    orthodox = LeadGripChoice(
        plan=PLAN_ORTHODOX, grip_type=GripTypeV2.LAPEL_HIGH,
        weights={PLAN_ORTHODOX: _ORTHODOX_BASE_WEIGHT},
    )

    # Only kenka-yotsu opens the cross/pistol fight.
    if matchup != StanceMatchup.MIRRORED:
        return orthodox

    kenka = _kenka_comfort(fighter)
    iq = _fight_iq_frac(fighter)
    arch = fighter.identity.body_archetype
    arch_factor = _ARCH_INSIDE_FACTOR.get(arch, 1.0)

    # Inside-fight aptitude — how cleanly this fighter can wield an unconventional
    # grip. Gated hard on the kenka comfort axis and fight IQ.
    aptitude = kenka * iq * arch_factor

    # Experienced counter (§4.4): facing the opponent's cross, a skilled judoka
    # converts the scramble back to their preferred orthodox grip instead of
    # trading cross for cross. Skilled = high (fight_iq × kenka comfort).
    skilled = (iq * kenka) >= _CONVERT_SKILL_THRESHOLD
    if facing_unconventional and skilled:
        orthodox.converts = True
        orthodox.notes = "routes through the scramble back to the preferred grip"
        return orthodox

    cross_w = 0.0
    pistol_w = 0.0

    # Fluent inside game — reached for only above the fluent comfort gate.
    if kenka >= _FLUENT_KENKA_GATE:
        cross_w += _CROSS_FLUENT_WEIGHT * aptitude
        pistol_w += _PISTOL_INSIDE_WEIGHT * aptitude

    # Sode setup — the sleeve-cuff entry to sode-tsurikomi-goshi. Needs a
    # minimum of inside competence but is driven by the sode tendency, not raw
    # aptitude, so a dedicated sode player reaches for it readily.
    sode = _sode_tendency(fighter)
    if sode > 0.0 and kenka >= _DISRUPTOR_KENKA_GATE:
        pistol_w += _PISTOL_SODE_WEIGHT * sode * (0.4 + 0.6 * iq)

    # Disruptor cross — a losing fighter breaks the dominant opponent's rhythm.
    disruptor_active = False
    if kenka >= _DISRUPTOR_KENKA_GATE:
        severity = _clamp01(
            (grip_pressure - _DISRUPT_PRESSURE_FLOOR) / _DISRUPT_PRESSURE_SPAN
        )
        if severity > 0.0:
            # Even a non-fluent fighter throws the disruptor, but the cleaner
            # their inside game the more reliably it lands.
            cross_w += _CROSS_DISRUPT_WEIGHT * severity * (0.5 + 0.5 * aptitude)
            disruptor_active = True

    weights = {
        PLAN_ORTHODOX: _ORTHODOX_BASE_WEIGHT,
        PLAN_CROSS: cross_w,
        PLAN_PISTOL: pistol_w,
    }
    total = sum(weights.values())
    if total <= 0.0:
        return orthodox

    roll = rng.uniform(0.0, total)
    cumulative = 0.0
    chosen = PLAN_ORTHODOX
    for plan in ALL_PLANS:
        cumulative += weights[plan]
        if roll <= cumulative:
            chosen = plan
            break

    if chosen == PLAN_ORTHODOX:
        orthodox.weights = weights
        return orthodox

    grip_type, _, _ = lead_grip_placement(chosen, fighter.identity.dominant_side)
    # The cross is a disruptor when the pressure term is what carried it — i.e.
    # the fighter is being dominated. (A fluent inside cross under no pressure is
    # the artist's reach, narrated differently.)
    is_disruptor = chosen == PLAN_CROSS and disruptor_active
    return LeadGripChoice(
        plan=chosen, grip_type=grip_type,
        disruptor=is_disruptor, weights=weights,
    )


# ---------------------------------------------------------------------------
# DEFENSIVE FRAME  (§4.5 — pistol as a defensive frame)
# ---------------------------------------------------------------------------
# In the cascade's DEFENSIVE branch the follower seats an off-hand sleeve frame
# rather than an offensive grip. A pistol-capable fighter in kenka-yotsu frames
# with a PISTOL (sode-tori) clamp instead — strip-resistant, it denies the
# opponent's attack without conceding the inside.
_PISTOL_FRAME_BASE_WEIGHT: float = 1.0
_SLEEVE_FRAME_BASE_WEIGHT: float = 2.0


def select_defensive_frame(
    fighter: "Judoka",
    *,
    matchup: StanceMatchup,
    rng: "random.Random",
) -> GripTypeV2:
    """Pick the grip type for the follower's DEFENSIVE sleeve frame: a plain
    SLEEVE_HIGH frame, or — for a kenka-yotsu-capable fighter in MIRRORED — a
    strip-resistant PISTOL (sode-tori) frame."""
    if matchup != StanceMatchup.MIRRORED:
        return GripTypeV2.SLEEVE_HIGH

    kenka = _kenka_comfort(fighter)
    if kenka < _DISRUPTOR_KENKA_GATE:
        return GripTypeV2.SLEEVE_HIGH

    iq = _fight_iq_frac(fighter)
    arch_factor = _ARCH_INSIDE_FACTOR.get(fighter.identity.body_archetype, 1.0)
    sode = _sode_tendency(fighter)
    pistol_w = _PISTOL_FRAME_BASE_WEIGHT * kenka * (0.5 + 0.5 * iq) * arch_factor
    pistol_w *= (1.0 + sode)   # a sode player frames with the pistol readily
    sleeve_w = _SLEEVE_FRAME_BASE_WEIGHT

    if rng.uniform(0.0, pistol_w + sleeve_w) <= pistol_w:
        return GripTypeV2.PISTOL
    return GripTypeV2.SLEEVE_HIGH


# ---------------------------------------------------------------------------
# NARRATION  (§4.3 — kenka-yotsu grip-fight family; folds into HAJ-225)
# ---------------------------------------------------------------------------
def lead_grip_coach_prose(name: str, choice: LeadGripChoice) -> Optional[str]:
    """Mat-side line for an unconventional lead-grip election, or None for the
    orthodox default (which the standard cascade prose already covers)."""
    if choice.converts:
        return (
            f"{name} doesn't take the cross — he works through the scramble "
            f"back to his own grip."
        )
    if choice.plan == PLAN_CROSS:
        if choice.disruptor:
            return (
                f"{name} reaches across for the cross grip — a disruptor to "
                f"break the rhythm of the grip fight."
            )
        return f"{name} reaches across for the cross grip, hunting the inside."
    if choice.plan == PLAN_PISTOL:
        return f"{name} clamps the sleeve-cuff — a pistol grip into the sode."
    return None


def defensive_frame_coach_prose(name: str, frame: GripTypeV2) -> Optional[str]:
    if frame == GripTypeV2.PISTOL:
        return f"{name} frames with a pistol grip on the sleeve, denying the entry."
    return None
