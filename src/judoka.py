# judoka.py
# Defines the three-layer Judoka model: Identity, Capability, and State.
#
# Phase 2 Session 2 changes:
#   - BODY_PARTS expanded from 15 to 24 (added head, hips, thighs, knees, wrists)
#   - Capability: 9 new body part fields with defaults; keep right_leg/left_leg intact
#   - BodyPartState: injury_state (InjuryState enum) replaces bool injured
#   - State: stun_ticks field + grip_configuration replaced by grip_graph reference slot
#   - Identity: cultural layer hooks added (arm_reach_cm, hip_height_cm, etc.)
#   - effective_body_part(): updated to use InjuryState.multiplier() + stun_ticks
#
# Design principle: layers remain structurally separate.
#   Identity = who they are (static/slow)
#   Capability = what they can do fresh (dojo-trained)
#   State = what's true right now (match-volatile)

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from enums import (
    BodyArchetype, BeltRank, DominantSide,
    Position, Posture, Stance, EmotionalState, InjuryState,
)
from throws import ThrowID, ComboID, JudokaThrowProfile


# ---------------------------------------------------------------------------
# BODY PARTS LIST — 24 parts (v0.4)
# Single source of truth for all body part keys. Both Capability (scores) and
# State (fatigue/injury) initialize from this list.
# ---------------------------------------------------------------------------
BODY_PARTS: list[str] = [
    # Hands — primary grip units
    "right_hand",    "left_hand",
    # Forearms — grip endurance and pulling power
    "right_forearm", "left_forearm",
    # Biceps — pulling strength, frame-breaking
    "right_bicep",   "left_bicep",
    # Shoulders — throw entry, posture maintenance
    "right_shoulder", "left_shoulder",
    # Legs — throw power and defensive base (whole-leg unit)
    "right_leg",     "left_leg",
    # Feet — footwork precision and sweep accuracy
    "right_foot",    "left_foot",
    # Core structures
    "core",          "lower_back",    "neck",
    # New in v0.4: ne-waza graspers, joint targets, head
    "head",
    "right_hip",     "left_hip",
    "right_thigh",   "left_thigh",
    "right_knee",    "left_knee",
    "right_wrist",   "left_wrist",
]  # 24 parts total


# ---------------------------------------------------------------------------
# AGE MODIFIER (STUB)
# Phase 1/2 stub — returns 1.0 for all attributes. Real curves added Phase 3.
# ---------------------------------------------------------------------------
def age_modifier(attribute_name: str, age: int) -> float:
    return 1.0


# ---------------------------------------------------------------------------
# EFFECTIVE CAPABILITY HELPER
# ---------------------------------------------------------------------------
def effective_capability(attribute_name: str, base_value: int, age: int) -> float:
    return base_value * age_modifier(attribute_name, age)


# ===========================================================================
# LAYER 1 — IDENTITY
# ===========================================================================
@dataclass
class Identity:
    """Static attributes that define who this judoka is."""
    name: str
    age: int
    weight_class: str
    height_cm: int
    body_archetype: BodyArchetype
    belt_rank: BeltRank
    dominant_side: DominantSide

    # Personality facets: 0–10 scale between two poles
    personality_facets: dict[str, int] = field(default_factory=dict)

    # -----------------------------------------------------------------------
    # Cultural / physical layer (v0.4 additions) — declared now, read Ring 2+
    # -----------------------------------------------------------------------
    # Physical variables from biomechanics.md
    arm_reach_cm: int = 185      # Grip control radius; who grips first at engagement
    hip_height_cm: int = 98      # Kuzushi geometry — affects throw moment arm
    # weight_distribution encoded as a string for now (FRONT_LOADED/NEUTRAL/BACK_LOADED)
    weight_distribution: str = "NEUTRAL"
    mass_density: str = "AVERAGE"   # LIGHT / AVERAGE / DENSE

    # Cultural layer hooks (Ring 2+)
    nationality: str = ""
    training_lineage: list[str] = field(default_factory=list)
    style_dna: dict[str, float] = field(default_factory=dict)
    stance_matchup_comfort: dict[str, float] = field(default_factory=dict)


# ===========================================================================
# LAYER 2 — CAPABILITY
# ===========================================================================
@dataclass
class Capability:
    """Maximum performance when fully fresh. Changes slowly through training."""

    # --- BODY PARTS (0–10 each) — original 15 ---
    right_hand: int
    left_hand: int
    right_forearm: int
    left_forearm: int
    right_bicep: int
    left_bicep: int
    right_shoulder: int
    left_shoulder: int
    right_leg: int
    left_leg: int
    right_foot: int
    left_foot: int
    core: int
    lower_back: int
    neck: int

    # --- CARDIO ---
    cardio_capacity: int
    cardio_efficiency: int

    # --- MIND ---
    composure_ceiling: int
    fight_iq: int
    ne_waza_skill: int

    # --- THROW VOCABULARY ---
    throw_vocabulary: list[ThrowID] = field(default_factory=list)
    throw_profiles: dict[ThrowID, JudokaThrowProfile] = field(default_factory=dict)
    signature_throws: list[ThrowID] = field(default_factory=list)
    signature_combos: list[ComboID] = field(default_factory=list)

    # --- NEW BODY PARTS (v0.4 — 9 additions with sensible defaults) ---
    # These default to moderate values; hand-crafted judoka can override in main.py.
    head: int = 5           # Head pressure, impact resistance
    right_hip: int = 7      # Hip rotation power for throws; ne-waza base
    left_hip: int = 7
    right_thigh: int = 7    # Inner thigh reap power; leg-lock target
    left_thigh: int = 7
    right_knee: int = 6     # Footwork precision; joint-lock vulnerability
    left_knee: int = 6
    right_wrist: int = 7    # Fine-motor grip and joint-lock target
    left_wrist: int = 7


# ===========================================================================
# STATE — BODY PART STATE
# ===========================================================================
@dataclass
class BodyPartState:
    """Tracks the real-time condition of one body part during a match."""
    fatigue: float = 0.0                         # 0.0 = fresh; 1.0 = cooked
    injury_state: InjuryState = InjuryState.HEALTHY  # severity of current injury
    stun_ticks: int = 0                          # ticks of temporary impairment remaining

    @property
    def injured(self) -> bool:
        """Backward-compatible accessor: True if anything worse than HEALTHY."""
        return self.injury_state != InjuryState.HEALTHY


# ===========================================================================
# LAYER 3 — STATE
# ===========================================================================
@dataclass
class State:
    """Live, moment-to-moment condition of a judoka in a match. Resets each match."""

    # --- BODY STATE ---
    body: dict[str, BodyPartState]   # one entry per BODY_PARTS key

    # --- CARDIO ---
    cardio_current: float   # 1.0 = full; depletes with sustained action

    # --- MIND ---
    composure_current: float         # drops after stuffed throws, scoring events, etc.
    last_event_emotional_weight: float  # spike value; decays over ticks

    # --- MATCH POSITION ---
    position: Position   # where the judoka is in the match space
    posture: Posture     # how upright (BROKEN = vulnerable to throw entry)
    current_stance: Stance

    # --- GRIP STATE ---
    # Phase 1 was a dict. Phase 2: grip state lives on the Match's GripGraph.
    # This field kept as an empty dict for backward compat; not read in Phase 2.
    grip_configuration: dict

    # --- STUN ---
    stun_ticks: int = 0   # match-level stun (composure hit, disorientation)
                           # decays 1 per tick; while > 0, effective values are penalised

    # --- SCORING ---
    score: dict = field(default_factory=lambda: {"waza_ari": 0, "ippon": False})
    shidos: int = 0

    # --- INSTRUCTION TRACKING ---
    recent_events: list = field(default_factory=list)
    current_instruction: str = ""
    instruction_received_strength: float = 0.0

    # --- RING 2+ HOOKS ---
    relationship_with_sensei: dict = field(default_factory=dict)
    matches_today: int = 0
    cumulative_fatigue_debt: dict = field(default_factory=dict)
    emotional_state_from_last_match: Optional[EmotionalState] = None

    @classmethod
    def fresh(cls, capability: Capability) -> "State":
        """Initialize a clean match-start State from a Capability."""
        return cls(
            body={part: BodyPartState() for part in BODY_PARTS},
            cardio_current=1.0,
            composure_current=float(capability.composure_ceiling),
            last_event_emotional_weight=0.0,
            position=Position.STANDING_DISTANT,
            posture=Posture.UPRIGHT,
            current_stance=Stance.ORTHODOX,
            grip_configuration={},
            stun_ticks=0,
            score={"waza_ari": 0, "ippon": False},
            shidos=0,
            recent_events=[],
            current_instruction="",
            instruction_received_strength=0.0,
            relationship_with_sensei={},
            matches_today=0,
            cumulative_fatigue_debt={part: 0.0 for part in BODY_PARTS},
            emotional_state_from_last_match=None,
        )


# ===========================================================================
# JUDOKA
# ===========================================================================
@dataclass
class Judoka:
    """A complete judoka: Identity + Capability + State composed into one object."""
    identity: Identity
    capability: Capability
    state: State

    def effective_body_part(self, part: str) -> float:
        """Compute the effective strength of one body part right now.

        Formula: base_capability × age_modifier × (1 - fatigue)
                 × injury_multiplier × stun_multiplier

        A 9-rated right_hand: fresh = 9.0, with 0.4 fatigue + minor pain ≈ 4.3.
        """
        # Base capability — getattr works for all 24 named fields
        base = getattr(self.capability, part, 5)  # default 5 for any unlisted part

        # Age modifier (stub — always 1.0 until Phase 3 calibration)
        age_mod = age_modifier(part, self.identity.age)

        # Fatigue from State
        part_state = self.state.body.get(part)
        if part_state is None:
            return base * age_mod  # part not tracked — return unmodified

        fatigue = part_state.fatigue

        # Injury severity multiplier
        injury_mult = part_state.injury_state.multiplier()

        # Stun multiplier: match-level stun (on State.stun_ticks)
        # reduces all parts by up to 30% while active
        stun_mult = 1.0
        if self.state.stun_ticks > 0:
            stun_mult = max(0.7, 1.0 - self.state.stun_ticks * 0.05)

        return base * age_mod * (1.0 - fatigue) * injury_mult * stun_mult
