# enums.py
# All shared enumerations for the Hajime simulation.
# Keeping enums in one file prevents circular imports — everything else can
# import from here without pulling in the full Judoka or Match machinery.

from enum import Enum, auto
from typing import Optional


# ---------------------------------------------------------------------------
# BODY ARCHETYPES
# ---------------------------------------------------------------------------
class BodyArchetype(Enum):
    LEVER             = auto()  # Height + leverage; harai-goshi, uchi-mata friendly
    MOTOR             = auto()  # Relentless pressure; wins by attrition
    GRIP_FIGHTER      = auto()  # Controls the grip war before committing
    GROUND_SPECIALIST = auto()  # Average standing, dangerous on the mat
    EXPLOSIVE         = auto()  # Patient build-up then one full-commit ippon attempt


# ---------------------------------------------------------------------------
# BELT RANK
# ---------------------------------------------------------------------------
class BeltRank(Enum):
    WHITE   = auto()
    YELLOW  = auto()
    ORANGE  = auto()
    GREEN   = auto()
    BLUE    = auto()
    BROWN   = auto()
    BLACK_1 = auto()  # Shodan
    BLACK_2 = auto()  # Nidan
    BLACK_3 = auto()  # Sandan
    BLACK_4 = auto()  # Yondan
    BLACK_5 = auto()  # Godan


# ---------------------------------------------------------------------------
# DOMINANT SIDE
# ---------------------------------------------------------------------------
class DominantSide(Enum):
    RIGHT = auto()  # Orthodox — most judoka
    LEFT  = auto()  # Southpaw — rarer, tactically disruptive


# ---------------------------------------------------------------------------
# POSITION
# v0.4: expanded with ne-waza sub-positions and THROW_COMMITTED transitional state.
# Position is a match-level attribute (both fighters share it), not per-fighter.
# ---------------------------------------------------------------------------
class Position(Enum):
    # Standing positions
    STANDING_DISTANT = auto()  # Both fighters separated, no grip yet
    GRIPPING         = auto()  # Grip contact established, grip battle underway
    ENGAGED          = auto()  # Close quarters; kuzushi achieved or throw entry
    SCRAMBLE         = auto()  # Chaotic transition after a stuffed throw
    THROW_COMMITTED  = auto()  # One tick: throw entry in progress
    # Ground positions (ne-waza)
    TURTLE_TOP       = auto()  # Top fighter over a turtling opponent
    TURTLE_BOTTOM    = auto()  # Bottom fighter turtling to defend
    GUARD_TOP        = auto()  # Top fighter inside bottom fighter's guard
    GUARD_BOTTOM     = auto()  # Bottom fighter with guard up
    SIDE_CONTROL     = auto()  # Top fighter in yoko-shiho / kesa position
    MOUNT            = auto()  # Top fighter in tatami-gaeshi / kami position
    BACK_CONTROL     = auto()  # Top fighter controls opponent's back
    DOWN             = auto()  # Transitional — fighter hit the mat


# ---------------------------------------------------------------------------
# POSTURE
# ---------------------------------------------------------------------------
class Posture(Enum):
    UPRIGHT       = auto()  # Neutral, stable base
    SLIGHTLY_BENT = auto()  # Pushed or pulled slightly off-balance
    BROKEN        = auto()  # Kuzushi achieved — vulnerable to throw entry


# ---------------------------------------------------------------------------
# STANCE
# ---------------------------------------------------------------------------
class Stance(Enum):
    ORTHODOX = auto()  # Right-handed lead — standard
    SOUTHPAW = auto()  # Left-handed lead — mirrors the opponent's grip map


# ---------------------------------------------------------------------------
# STANCE MATCHUP
# ---------------------------------------------------------------------------
class StanceMatchup(Enum):
    MATCHED  = auto()  # Both orthodox or both southpaw — standard grip war
    MIRRORED = auto()  # Opposite stances — opens sumi-gaeshi, changes grip map


# ---------------------------------------------------------------------------
# EMOTIONAL STATE
# Carries over between matches (Ring 2+ feature). Declared now for data model.
# ---------------------------------------------------------------------------
class EmotionalState(Enum):
    ELATED   = auto()
    RELIEVED = auto()
    DRAINED  = auto()
    SHAKEN   = auto()
    FOCUSED  = auto()


# ===========================================================================
# NEW IN PHASE 2 SESSION 2
# ===========================================================================

# ---------------------------------------------------------------------------
# BODY PART
# Enum of all 24 body parts. Values are string keys for the body dicts.
# Includes symbolic aliases (DOMINANT_HAND etc.) resolved at match time.
# ---------------------------------------------------------------------------
class BodyPart(Enum):
    # Hands — primary gripping units
    RIGHT_HAND    = "right_hand"
    LEFT_HAND     = "left_hand"
    # Forearms — grip endurance and frame
    RIGHT_FOREARM = "right_forearm"
    LEFT_FOREARM  = "left_forearm"
    # Biceps — pulling strength
    RIGHT_BICEP   = "right_bicep"
    LEFT_BICEP    = "left_bicep"
    # Shoulders — throw entry and posture maintenance
    RIGHT_SHOULDER = "right_shoulder"
    LEFT_SHOULDER  = "left_shoulder"
    # Legs (whole-leg unit — throw power and defensive base)
    RIGHT_LEG = "right_leg"
    LEFT_LEG  = "left_leg"
    # Feet — footwork precision and sweep accuracy
    RIGHT_FOOT = "right_foot"
    LEFT_FOOT  = "left_foot"
    # Core structures
    CORE       = "core"
    LOWER_BACK = "lower_back"
    NECK       = "neck"
    # New in v0.4 — ne-waza graspers, joint targets, head
    HEAD        = "head"
    RIGHT_HIP   = "right_hip"
    LEFT_HIP    = "left_hip"
    RIGHT_THIGH = "right_thigh"
    LEFT_THIGH  = "left_thigh"
    RIGHT_KNEE  = "right_knee"
    LEFT_KNEE   = "left_knee"
    RIGHT_WRIST = "right_wrist"
    LEFT_WRIST  = "left_wrist"
    # Symbolic aliases for throw EdgeRequirements (resolved at match time)
    DOMINANT_HAND     = "__dominant_hand__"
    NON_DOMINANT_HAND = "__non_dominant_hand__"


# ---------------------------------------------------------------------------
# GRIP TARGET
# Locations on a fighter's gi or body that can be gripped.
# Includes symbolic aliases resolved based on attacker's dominant side.
# ---------------------------------------------------------------------------
class GripTarget(Enum):
    # Standing gi-based targets
    LEFT_LAPEL    = "left_lapel"
    RIGHT_LAPEL   = "right_lapel"
    LEFT_SLEEVE   = "left_sleeve"
    RIGHT_SLEEVE  = "right_sleeve"
    BACK_COLLAR   = "back_collar"
    LEFT_BACK_GI  = "left_back_gi"
    RIGHT_BACK_GI = "right_back_gi"
    BELT          = "belt"
    # Ne-waza body-based targets
    NECK           = "neck"
    LEFT_WRIST     = "left_wrist"
    RIGHT_WRIST    = "right_wrist"
    LEFT_ELBOW     = "left_elbow"
    RIGHT_ELBOW    = "right_elbow"
    LEFT_SHOULDER  = "left_shoulder"
    RIGHT_SHOULDER = "right_shoulder"
    LEFT_KNEE      = "left_knee"
    RIGHT_KNEE     = "right_knee"
    LEFT_ANKLE     = "left_ankle"
    RIGHT_ANKLE    = "right_ankle"
    HEAD           = "head"
    WAIST          = "waist"
    # Symbolic aliases (resolved based on attacker's dominant side at match time)
    OPPOSITE_LAPEL  = "__opposite_lapel__"   # right-dominant → LEFT_LAPEL
    DOMINANT_LAPEL  = "__dominant_lapel__"   # right-dominant → RIGHT_LAPEL
    DOMINANT_SLEEVE = "__dominant_sleeve__"  # right-dominant → RIGHT_SLEEVE
    OPPOSITE_SLEEVE = "__opposite_sleeve__"  # right-dominant → LEFT_SLEEVE
    ANY             = "__any__"              # Match any target


# ---------------------------------------------------------------------------
# GRIP TYPE
# How the grasper is anchored at the target location. Different types have
# different strength profiles, fatigue rates, and dominance contributions.
# ---------------------------------------------------------------------------
class GripType(Enum):
    STANDARD      = auto()  # Classical sleeve/lapel hold
    PISTOL        = auto()  # Sleeve choke-grip, palm down, locked thumb
    CROSS         = auto()  # Reaching across the body to opposite side
    DEEP          = auto()  # Hand far inside the collar, controlling posture
    POCKET        = auto()  # Gripping at the seam — brief and weak
    HIGH_COLLAR   = auto()  # Grip up near the back of the neck
    BELT          = auto()  # Georgian over-the-top
    OVER_BACK     = auto()  # Chidaoba-style across the shoulder
    RUSSIAN       = auto()  # Wrist control with arm hook (sambo crossover)
    UNDERHOOK     = auto()  # Arm under armpit (ne-waza control)
    TWO_ON_ONE    = auto()  # Both hands on opponent's one limb
    CHOKE_HOLD    = auto()  # Active choke configuration
    ARMBAR_THREAT = auto()  # Juji-gatame extension configuration

    def dominance_factor(self) -> float:
        """Contribution weight when computing grip_delta."""
        return {
            GripType.STANDARD:      1.0,
            GripType.PISTOL:        1.2,
            GripType.CROSS:         0.8,
            GripType.DEEP:          1.3,
            GripType.POCKET:        0.5,
            GripType.HIGH_COLLAR:   1.1,
            GripType.BELT:          1.4,
            GripType.OVER_BACK:     1.2,
            GripType.RUSSIAN:       0.9,
            GripType.UNDERHOOK:     1.0,
            GripType.TWO_ON_ONE:    1.5,
            GripType.CHOKE_HOLD:    0.8,
            GripType.ARMBAR_THREAT: 0.7,
        }[self]

    def fatigue_rate(self) -> float:
        """Per-tick fatigue multiplier on the grasping body part."""
        return {
            GripType.STANDARD:      1.0,
            GripType.PISTOL:        1.3,
            GripType.CROSS:         1.2,
            GripType.DEEP:          1.4,
            GripType.POCKET:        0.6,
            GripType.HIGH_COLLAR:   1.2,
            GripType.BELT:          1.3,
            GripType.OVER_BACK:     1.1,
            GripType.RUSSIAN:       1.0,
            GripType.UNDERHOOK:     0.9,
            GripType.TWO_ON_ONE:    1.2,
            GripType.CHOKE_HOLD:    0.8,
            GripType.ARMBAR_THREAT: 0.7,
        }[self]


# ---------------------------------------------------------------------------
# PHYSICS SUBSTRATE PART 2 — GRIP TYPE (seven standing grip types)
# Clean separation from the legacy GripType enum above, which mixes grip
# shape, depth, and ne-waza holds. GripTypeV2 covers only the seven
# canonical standing grip types from the biomechanics literature.
#
# Legacy GripType stays in place for ne-waza grips (CHOKE_HOLD, ARMBAR_THREAT,
# UNDERHOOK, TWO_ON_ONE) and for legacy standing throw prerequisites in
# throws.py until Part 4 replaces EdgeRequirement with the four-dimension
# signature.
# ---------------------------------------------------------------------------
class GripTypeV2(Enum):
    # HAJ-53 — sleeve grip splits by height. Sensei's Tai-otoshi teaching
    # makes the cuff/elbow distinction explicit: the cuff (LOW) gives wrist
    # rotation control and a longer pull-around moment arm; the elbow/tricep
    # (HIGH) gives leverage to lift uke's shoulder line for hikite-driven
    # forward throws. Most throws prefer HIGH; Tai-otoshi prefers LOW.
    SLEEVE_LOW  = auto()  # Cuff — wrist rotation, long moment arm, easier to slip.
    SLEEVE_HIGH = auto()  # Elbow/tricep — strong lift, shorter moment arm, harder to strip.
    LAPEL_LOW   = auto()  # Eri-tori lower — mid-chest, standard working grip.
    LAPEL_HIGH  = auto()  # Eri-tori upper — collarbone; strong lift (tsurite).
    COLLAR      = auto()  # Oku-eri — deep behind neck; max rotation authority.
    BELT        = auto()  # Obi-tori — wraps back to grip belt; max CoM lift.
    PISTOL      = auto()  # Sode-tori — sleeve-cuff clamp; defensive, strip-resistant.
    CROSS       = auto()  # Katate-ai-gumi — "wrong" hand across; breaks geometry.

    def is_unconventional(self) -> bool:
        """Under current IJF rules, unconventional grips must lead to immediate
        attack. Used for the per-grip 5-tick unconventional-grip clock (Part 2.6).
        """
        return self in (GripTypeV2.BELT, GripTypeV2.PISTOL, GripTypeV2.CROSS)

    def is_sleeve(self) -> bool:
        """HAJ-53 — both sleeve sub-types share the sleeve family for any
        logic that doesn't care about height (display, generic vocabulary
        rules, kumi-kata clocks)."""
        return self in (GripTypeV2.SLEEVE_LOW, GripTypeV2.SLEEVE_HIGH)


# ---------------------------------------------------------------------------
# GRIP DEPTH (Part 2.4)
# Discrete levels with modifiers in [0.0, 1.0] that multiply into the force
# envelope. Stripping moves DEEP → STANDARD → POCKET → SLIPPING → stripped.
# ---------------------------------------------------------------------------
class GripDepth(Enum):
    SLIPPING = auto()   # 0.2 — being actively stripped, one tick from lost
    POCKET   = auto()   # 0.4 — fingertip grip, barely held
    STANDARD = auto()   # 0.7 — normal working grip
    DEEP     = auto()   # 1.0 — fully seated grip

    def modifier(self) -> float:
        return {
            GripDepth.SLIPPING: 0.2,
            GripDepth.POCKET:   0.4,
            GripDepth.STANDARD: 0.7,
            GripDepth.DEEP:     1.0,
        }[self]

    def degraded(self) -> Optional["GripDepth"]:
        """Next step in the strip chain. None means the grip is stripped entirely."""
        return {
            GripDepth.DEEP:     GripDepth.STANDARD,
            GripDepth.STANDARD: GripDepth.POCKET,
            GripDepth.POCKET:   GripDepth.SLIPPING,
            GripDepth.SLIPPING: None,
        }[self]

    def deepened(self) -> "GripDepth":
        """Next step when DEEPEN succeeds. DEEP is terminal."""
        return {
            GripDepth.SLIPPING: GripDepth.POCKET,
            GripDepth.POCKET:   GripDepth.STANDARD,
            GripDepth.STANDARD: GripDepth.DEEP,
            GripDepth.DEEP:     GripDepth.DEEP,
        }[self]


# ---------------------------------------------------------------------------
# GRIP MODE (Part 2.5) — per-tick choice by the owning judoka
# ---------------------------------------------------------------------------
class GripMode(Enum):
    CONNECTIVE = auto()  # Binds the dyad, minimal force, low fatigue cost.
    DRIVING    = auto()  # Transmits directed force; high fatigue cost.


# ---------------------------------------------------------------------------
# INJURY STATE
# Per-body-part injury severity. Replaces the boolean injured flag.
# ---------------------------------------------------------------------------
class InjuryState(Enum):
    HEALTHY      = auto()  # No injury — full output
    MINOR_PAIN   = auto()  # Soreness — slight degradation
    IMPAIRED     = auto()  # Significant — 50% output
    MATCH_ENDING = auto()  # Structural — cannot continue

    def multiplier(self) -> float:
        """Effective-output multiplier for a part at this injury state."""
        return {
            InjuryState.HEALTHY:      1.0,
            InjuryState.MINOR_PAIN:   0.8,
            InjuryState.IMPAIRED:     0.5,
            InjuryState.MATCH_ENDING: 0.1,
        }[self]


# ---------------------------------------------------------------------------
# LANDING PROFILE
# The geometric arc a throw produces on landing. Read by the Referee to
# determine IPPON vs WAZA_ARI vs NO_SCORE.
# ---------------------------------------------------------------------------
class LandingProfile(Enum):
    FORWARD_ROTATIONAL      = auto()  # Seoi-nage, uchi-mata — rotating forward
    HIGH_FORWARD_ROTATIONAL = auto()  # Harai-goshi at altitude
    REAR_ROTATIONAL         = auto()  # O-soto-gari — driving backward
    LATERAL                 = auto()  # O-uchi-gari, ko-uchi-gari — sideways
    SACRIFICE               = auto()  # Sumi-gaeshi — attacker also falls


# ---------------------------------------------------------------------------
# MATTE REASON
# Why the referee called Matte. Used in event logs and coach windows.
# ---------------------------------------------------------------------------
class MatteReason(Enum):
    SCORING               = auto()  # Score was just awarded
    STALEMATE             = auto()  # Neither fighter making progress
    OUT_OF_BOUNDS         = auto()  # One or both fighters left the mat
    PASSIVITY             = auto()  # Extended non-action, penalty pending
    STUFFED_THROW_TIMEOUT = auto()  # Stuffed throw; ref closes ne-waza window
    INJURY                = auto()  # Medical stop
    OSAEKOMI_DECISION     = auto()  # Pin clock reached decision threshold


# ---------------------------------------------------------------------------
# COUNTER ACTION
# Actions available to the bottom fighter in ne-waza commitment chains.
# Each counter-action is a graph operation: adding edges or contesting existing ones.
# ---------------------------------------------------------------------------
class CounterAction(Enum):
    HAND_FIGHT = auto()  # Fight the grips establishing the sub/lock
    FRAME      = auto()  # Post an arm/leg to create distance
    HIP_OUT    = auto()  # Shrimp hip out to escape guard/side control
    BRIDGE     = auto()  # Explosive bridge to upset top fighter's base
    TURNOVER   = auto()  # Attempt to reverse position
    SHRIMP     = auto()  # Combined hip-out + turning away


# ---------------------------------------------------------------------------
# SUB-LOOP STATE
# The current phase of the grip sub-loop state machine. Owned by Match.
# The sub-loop runs continuously between Hajime and Matte; dozens of cycles
# may occur between any two Matte calls.
# ---------------------------------------------------------------------------
class SubLoopState(Enum):
    """Coarse phase of live match time. Physics-substrate Part 3 replaced the
    old ENGAGEMENT/TUG_OF_WAR/KUZUSHI_WINDOW/STIFLED_RESET machine with a
    single STANDING phase whose flow is driven by the per-tick force model.
    NE_WAZA is still a genuine phase because the ground resolver takes over.
    """
    STANDING        = auto()  # Live standing exchange — Part 3 physics driven
    THROW_COMMITTED = auto()  # One-tick state: throw entry in progress
    NE_WAZA         = auto()  # Ground work — pins, chokes, armbars
