# throws.py
# Defines throw and combo data types, the JudokaThrowProfile (per-judoka effectiveness),
# and the global registries that the rest of the simulation looks up from.
#
# Phase 2 Session 2 additions:
#   - EdgeRequirement: what grip edges a throw needs to fire
#   - ThrowDef: full prerequisite + physics definition for each standing throw
#   - THROW_DEFS: the new registry checked before any throw attempt
#   - NewazaTechniqueID / NewazaTechniqueDef: ground technique chains
#   - NEWAZA_REGISTRY: the ne-waza technique lookup table
#
# The old Throw / THROW_REGISTRY / Combo / COMBO_REGISTRY are preserved —
# they supply display names and combo chain data still used by match.py.

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

from enums import (
    BodyPart, GripTarget, GripType, LandingProfile, Posture, DominantSide,
)


# ---------------------------------------------------------------------------
# THROW IDs — unchanged from Phase 1
# ---------------------------------------------------------------------------
class ThrowID(Enum):
    SEOI_NAGE    = auto()  # Shoulder throw — Tanaka's signature
    UCHI_MATA    = auto()  # Inner thigh reap — Sato's signature
    O_SOTO_GARI  = auto()  # Major outer reap
    O_UCHI_GARI  = auto()  # Major inner reap
    KO_UCHI_GARI = auto()  # Minor inner reap — low-commitment setup
    HARAI_GOSHI  = auto()  # Hip sweep
    TAI_OTOSHI   = auto()  # Body drop — combo finisher when harai-goshi is read
    SUMI_GAESHI  = auto()  # Corner sacrifice — mirrored-stance favourite


# ---------------------------------------------------------------------------
# COMBO IDs — unchanged from Phase 1
# ---------------------------------------------------------------------------
class ComboID(Enum):
    KO_UCHI_TO_SEOI     = auto()  # Ankle reap → shoulder throw
    O_UCHI_TO_UCHI_MATA = auto()  # Major inner reap → inner thigh sweep
    HARAI_TO_TAI_OTOSHI = auto()  # Hip sweep → body drop


# ---------------------------------------------------------------------------
# THROW — global registry entry (display name + description)
# ---------------------------------------------------------------------------
@dataclass
class Throw:
    """Global registry entry. What a throw IS, not how well anyone does it."""
    throw_id: ThrowID
    name: str
    description: str


# ---------------------------------------------------------------------------
# COMBO — global registry entry
# ---------------------------------------------------------------------------
@dataclass
class Combo:
    """Global registry entry for a two-throw chain."""
    combo_id: ComboID
    name: str
    sequence: list[ThrowID]
    chain_bonus: float   # Probability boost when listed in signature_combos


# ---------------------------------------------------------------------------
# JUDOKA THROW PROFILE — per-judoka effectiveness ratings
# Lives in a judoka's Capability layer.
# ---------------------------------------------------------------------------
@dataclass
class JudokaThrowProfile:
    """Capability layer — how effective THIS judoka is with THIS throw from each side."""
    throw_id: ThrowID
    effectiveness_dominant: int   # 0–10: from the trained (strong) side
    effectiveness_off_side: int   # 0–10: from the off (weak) side


# ===========================================================================
# NEW IN PHASE 2 SESSION 2
# ===========================================================================

# ---------------------------------------------------------------------------
# EDGE REQUIREMENT
# Declares what the grip graph must look like before a throw can be attempted.
# GripGraph.satisfies() checks the current edge list against these requirements.
# ---------------------------------------------------------------------------
@dataclass
class EdgeRequirement:
    """One prerequisite edge a throw needs satisfied in the grip graph."""
    grasper_part: BodyPart           # Which body part (or alias) must hold the grip
    target_location: GripTarget      # What location it must grip on the opponent
    grip_type_in: list[GripType] = field(default_factory=list)  # Empty = any type
    min_depth: float = 0.0           # Minimum edge depth (0–1)
    min_strength: float = 0.0        # Minimum edge strength (0–1)


# ---------------------------------------------------------------------------
# THROW DEF
# Full definition of a standing throw for Phase 2 match resolution.
# Replaces the old effectiveness-only approach with a graph-gated system.
# ---------------------------------------------------------------------------
@dataclass
class ThrowDef:
    """Full throw definition — grip prerequisites + physics profile."""
    throw_id: ThrowID
    name: str
    requires: list[EdgeRequirement]         # Graph prerequisites (all must be satisfied)
    posture_requirement: list[Posture]      # Acceptable defender postures
    primary_body_parts: list[BodyPart]      # Attacker body parts that do the work
    landing_profile: LandingProfile
    base_effectiveness_dominant: float      # Raw throw power from dominant side (0–10)
    base_effectiveness_off_side: float      # Raw throw power from off-side (0–10)


# ---------------------------------------------------------------------------
# NE-WAZA TECHNIQUE IDs
# ---------------------------------------------------------------------------
class NewazaTechniqueID(Enum):
    OKURI_ERI_JIME    = auto()  # Sliding collar choke
    JUJI_GATAME       = auto()  # Cross armlock
    KESA_GATAME       = auto()  # Scarf hold (pin)
    YOKO_SHIHO_GATAME = auto()  # Side four-quarter hold (pin)


# ---------------------------------------------------------------------------
# NE-WAZA TECHNIQUE DEF
# ---------------------------------------------------------------------------
@dataclass
class NewazaTechniqueDef:
    """Definition of a ground technique — position requirements and chain length."""
    tech_id: NewazaTechniqueID
    name: str
    required_position_names: list[str]  # Position.name values where this can initiate
    chain_length: int                   # Ticks to full commitment (0 = pin, no chain)
    min_ne_waza_skill: int              # Minimum skill to attempt


# ===========================================================================
# THROW REGISTRY — display names (unchanged from Phase 1)
# ===========================================================================
THROW_REGISTRY: dict[ThrowID, Throw] = {

    ThrowID.SEOI_NAGE: Throw(
        throw_id=ThrowID.SEOI_NAGE,
        name="Seoi-nage",
        description=(
            "Shoulder throw. Right-side entry; the attacker turns in, "
            "loads the opponent across the back, and lifts them over."
        ),
    ),
    ThrowID.UCHI_MATA: Throw(
        throw_id=ThrowID.UCHI_MATA,
        name="Uchi-mata",
        description=(
            "Inner thigh reap. The attacking leg sweeps up the inside of "
            "the opponent's thigh while pulling them forward and over."
        ),
    ),
    ThrowID.O_SOTO_GARI: Throw(
        throw_id=ThrowID.O_SOTO_GARI,
        name="O-soto-gari",
        description=(
            "Major outer reap. The attacker sweeps the opponent's outside "
            "leg from behind while driving them backward."
        ),
    ),
    ThrowID.O_UCHI_GARI: Throw(
        throw_id=ThrowID.O_UCHI_GARI,
        name="O-uchi-gari",
        description=(
            "Major inner reap. Hooks and reaps the inside of the opponent's "
            "right leg — excellent as a combo opener."
        ),
    ),
    ThrowID.KO_UCHI_GARI: Throw(
        throw_id=ThrowID.KO_UCHI_GARI,
        name="Ko-uchi-gari",
        description=(
            "Minor inner reap. Small, fast reap of the opponent's ankle. "
            "Low commitment; its value is mostly as a setup for a follow-on throw."
        ),
    ),
    ThrowID.HARAI_GOSHI: Throw(
        throw_id=ThrowID.HARAI_GOSHI,
        name="Harai-goshi",
        description=(
            "Hip sweep. Hip-to-hip contact; the attacker's leg sweeps both "
            "of the opponent's legs while the hips act as a fulcrum."
        ),
    ),
    ThrowID.TAI_OTOSHI: Throw(
        throw_id=ThrowID.TAI_OTOSHI,
        name="Tai-otoshi",
        description=(
            "Body drop. No hip contact — the attacker blocks the opponent's "
            "lead leg and rotates them over."
        ),
    ),
    ThrowID.SUMI_GAESHI: Throw(
        throw_id=ThrowID.SUMI_GAESHI,
        name="Sumi-gaeshi",
        description=(
            "Corner sacrifice throw. Attacker falls backward, hooking the opponent's "
            "inner thigh with the foot and flipping them over."
        ),
    ),
}


# ===========================================================================
# THROW DEFS — grip-graph-gated prerequisites (new in Session 2)
# ===========================================================================
THROW_DEFS: dict[ThrowID, ThrowDef] = {

    ThrowID.SEOI_NAGE: ThrowDef(
        throw_id=ThrowID.SEOI_NAGE,
        name="Seoi-nage",
        requires=[
            # Must have deep collar grip on the opposite lapel
            EdgeRequirement(
                grasper_part=BodyPart.DOMINANT_HAND,
                target_location=GripTarget.OPPOSITE_LAPEL,
                grip_type_in=[GripType.DEEP, GripType.HIGH_COLLAR],
                min_depth=0.6,
            ),
            # Must have sleeve control on the pulling side
            EdgeRequirement(
                grasper_part=BodyPart.NON_DOMINANT_HAND,
                target_location=GripTarget.DOMINANT_SLEEVE,
                grip_type_in=[GripType.STANDARD, GripType.PISTOL],
                min_depth=0.3,
            ),
        ],
        posture_requirement=[Posture.UPRIGHT, Posture.SLIGHTLY_BENT],
        primary_body_parts=[
            BodyPart.LOWER_BACK, BodyPart.CORE, BodyPart.RIGHT_HIP, BodyPart.RIGHT_THIGH,
        ],
        landing_profile=LandingProfile.FORWARD_ROTATIONAL,
        base_effectiveness_dominant=9.0,
        base_effectiveness_off_side=3.0,
    ),

    ThrowID.UCHI_MATA: ThrowDef(
        throw_id=ThrowID.UCHI_MATA,
        name="Uchi-mata",
        requires=[
            # Moderate collar control — uchi-mata doesn't need a deep grip
            EdgeRequirement(
                grasper_part=BodyPart.DOMINANT_HAND,
                target_location=GripTarget.OPPOSITE_LAPEL,
                grip_type_in=[GripType.STANDARD, GripType.DEEP],
                min_depth=0.3,
            ),
            # Sleeve pull
            EdgeRequirement(
                grasper_part=BodyPart.NON_DOMINANT_HAND,
                target_location=GripTarget.DOMINANT_SLEEVE,
                min_depth=0.2,
            ),
        ],
        posture_requirement=[Posture.UPRIGHT, Posture.SLIGHTLY_BENT, Posture.BROKEN],
        primary_body_parts=[BodyPart.RIGHT_THIGH, BodyPart.CORE, BodyPart.LOWER_BACK],
        landing_profile=LandingProfile.FORWARD_ROTATIONAL,
        base_effectiveness_dominant=9.0,
        base_effectiveness_off_side=5.0,
    ),

    ThrowID.O_SOTO_GARI: ThrowDef(
        throw_id=ThrowID.O_SOTO_GARI,
        name="O-soto-gari",
        requires=[
            EdgeRequirement(
                grasper_part=BodyPart.DOMINANT_HAND,
                target_location=GripTarget.OPPOSITE_LAPEL,
                grip_type_in=[GripType.STANDARD, GripType.DEEP],
                min_depth=0.3,
            ),
            EdgeRequirement(
                grasper_part=BodyPart.NON_DOMINANT_HAND,
                target_location=GripTarget.DOMINANT_SLEEVE,
                min_depth=0.2,
            ),
        ],
        posture_requirement=[Posture.UPRIGHT, Posture.SLIGHTLY_BENT, Posture.BROKEN],
        primary_body_parts=[BodyPart.RIGHT_LEG, BodyPart.CORE],
        landing_profile=LandingProfile.REAR_ROTATIONAL,
        base_effectiveness_dominant=7.0,
        base_effectiveness_off_side=5.0,
    ),

    ThrowID.O_UCHI_GARI: ThrowDef(
        throw_id=ThrowID.O_UCHI_GARI,
        name="O-uchi-gari",
        requires=[
            # Very low requirements — inside hook from almost any contact
            EdgeRequirement(
                grasper_part=BodyPart.DOMINANT_HAND,
                target_location=GripTarget.ANY,
                min_depth=0.2,
            ),
        ],
        posture_requirement=[Posture.UPRIGHT, Posture.SLIGHTLY_BENT, Posture.BROKEN],
        primary_body_parts=[BodyPart.RIGHT_LEG, BodyPart.CORE, BodyPart.LOWER_BACK],
        landing_profile=LandingProfile.LATERAL,
        base_effectiveness_dominant=7.0,
        base_effectiveness_off_side=6.0,
    ),

    ThrowID.KO_UCHI_GARI: ThrowDef(
        throw_id=ThrowID.KO_UCHI_GARI,
        name="Ko-uchi-gari",
        requires=[
            # Minimal — any contact at all; this throw is a setup, not a finisher
            EdgeRequirement(
                grasper_part=BodyPart.DOMINANT_HAND,
                target_location=GripTarget.ANY,
                min_depth=0.1,
            ),
        ],
        posture_requirement=[Posture.UPRIGHT, Posture.SLIGHTLY_BENT, Posture.BROKEN],
        primary_body_parts=[BodyPart.RIGHT_FOOT, BodyPart.CORE],
        landing_profile=LandingProfile.LATERAL,
        base_effectiveness_dominant=5.0,
        base_effectiveness_off_side=5.0,
    ),

    ThrowID.HARAI_GOSHI: ThrowDef(
        throw_id=ThrowID.HARAI_GOSHI,
        name="Harai-goshi",
        requires=[
            # Hip entry requires deep collar — getting under the opponent
            EdgeRequirement(
                grasper_part=BodyPart.DOMINANT_HAND,
                target_location=GripTarget.OPPOSITE_LAPEL,
                grip_type_in=[GripType.DEEP, GripType.HIGH_COLLAR],
                min_depth=0.5,
            ),
            EdgeRequirement(
                grasper_part=BodyPart.NON_DOMINANT_HAND,
                target_location=GripTarget.DOMINANT_SLEEVE,
                min_depth=0.3,
            ),
        ],
        posture_requirement=[Posture.SLIGHTLY_BENT, Posture.BROKEN],
        primary_body_parts=[
            BodyPart.RIGHT_THIGH, BodyPart.CORE, BodyPart.LOWER_BACK, BodyPart.RIGHT_HIP,
        ],
        landing_profile=LandingProfile.HIGH_FORWARD_ROTATIONAL,
        base_effectiveness_dominant=7.0,
        base_effectiveness_off_side=4.0,
    ),

    ThrowID.TAI_OTOSHI: ThrowDef(
        throw_id=ThrowID.TAI_OTOSHI,
        name="Tai-otoshi",
        requires=[
            # More forgiving than seoi — moderate depth works (no hip rotation needed)
            EdgeRequirement(
                grasper_part=BodyPart.DOMINANT_HAND,
                target_location=GripTarget.OPPOSITE_LAPEL,
                grip_type_in=[GripType.STANDARD, GripType.DEEP],
                min_depth=0.4,
            ),
            EdgeRequirement(
                grasper_part=BodyPart.NON_DOMINANT_HAND,
                target_location=GripTarget.DOMINANT_SLEEVE,
                min_depth=0.3,
            ),
        ],
        posture_requirement=[Posture.UPRIGHT, Posture.SLIGHTLY_BENT, Posture.BROKEN],
        primary_body_parts=[BodyPart.LOWER_BACK, BodyPart.CORE, BodyPart.RIGHT_KNEE],
        landing_profile=LandingProfile.FORWARD_ROTATIONAL,
        base_effectiveness_dominant=6.0,
        base_effectiveness_off_side=5.0,
    ),

    ThrowID.SUMI_GAESHI: ThrowDef(
        throw_id=ThrowID.SUMI_GAESHI,
        name="Sumi-gaeshi",
        requires=[
            # Sacrifice throw — opportunistic; works from awkward positions
            EdgeRequirement(
                grasper_part=BodyPart.DOMINANT_HAND,
                target_location=GripTarget.ANY,
                min_depth=0.2,
            ),
        ],
        posture_requirement=[Posture.UPRIGHT, Posture.SLIGHTLY_BENT, Posture.BROKEN],
        primary_body_parts=[BodyPart.CORE, BodyPart.RIGHT_THIGH],
        landing_profile=LandingProfile.SACRIFICE,
        base_effectiveness_dominant=5.0,
        base_effectiveness_off_side=7.0,  # Higher off-side: mirrored stance specialty
    ),
}


# ===========================================================================
# NE-WAZA TECHNIQUE REGISTRY
# ===========================================================================
NEWAZA_REGISTRY: dict[NewazaTechniqueID, NewazaTechniqueDef] = {

    NewazaTechniqueID.OKURI_ERI_JIME: NewazaTechniqueDef(
        tech_id=NewazaTechniqueID.OKURI_ERI_JIME,
        name="Okuri-eri-jime",
        required_position_names=["BACK_CONTROL", "SIDE_CONTROL"],
        chain_length=12,  # 12 ticks to submission if not escaped
        min_ne_waza_skill=4,
    ),

    NewazaTechniqueID.JUJI_GATAME: NewazaTechniqueDef(
        tech_id=NewazaTechniqueID.JUJI_GATAME,
        name="Juji-gatame",
        required_position_names=["GUARD_TOP", "SIDE_CONTROL", "MOUNT"],
        chain_length=10,
        min_ne_waza_skill=5,
    ),

    NewazaTechniqueID.KESA_GATAME: NewazaTechniqueDef(
        tech_id=NewazaTechniqueID.KESA_GATAME,
        name="Kesa-gatame",
        required_position_names=["SIDE_CONTROL"],
        chain_length=0,   # Pin — OsaekomiClock handles it, no chain
        min_ne_waza_skill=2,
    ),

    NewazaTechniqueID.YOKO_SHIHO_GATAME: NewazaTechniqueDef(
        tech_id=NewazaTechniqueID.YOKO_SHIHO_GATAME,
        name="Yoko-shiho-gatame",
        required_position_names=["SIDE_CONTROL"],
        chain_length=0,   # Pin — OsaekomiClock handles it, no chain
        min_ne_waza_skill=2,
    ),
}


# ===========================================================================
# COMBO REGISTRY — unchanged from Phase 1
# ===========================================================================
COMBO_REGISTRY: dict[ComboID, Combo] = {

    ComboID.KO_UCHI_TO_SEOI: Combo(
        combo_id=ComboID.KO_UCHI_TO_SEOI,
        name="Ko-uchi → Seoi-nage",
        sequence=[ThrowID.KO_UCHI_GARI, ThrowID.SEOI_NAGE],
        chain_bonus=0.25,
    ),

    ComboID.O_UCHI_TO_UCHI_MATA: Combo(
        combo_id=ComboID.O_UCHI_TO_UCHI_MATA,
        name="O-uchi → Uchi-mata",
        sequence=[ThrowID.O_UCHI_GARI, ThrowID.UCHI_MATA],
        chain_bonus=0.30,
    ),

    ComboID.HARAI_TO_TAI_OTOSHI: Combo(
        combo_id=ComboID.HARAI_TO_TAI_OTOSHI,
        name="Harai-goshi → Tai-otoshi",
        sequence=[ThrowID.HARAI_GOSHI, ThrowID.TAI_OTOSHI],
        chain_bonus=0.20,
    ),
}
