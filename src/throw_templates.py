# throw_templates.py
# Physics-substrate Part 4: the two throw templates (Couple and Lever) plus the
# four-dimension signature framework they share.
#
# Spec: design-notes/physics-substrate.md, Part 4 (sections 4.1–4.7).
#
# Scope of this module (Part 4 only — templates, not instances):
#   - ThrowClassification enum (Couple vs Lever — 4.1)
#   - Sub-requirement dataclasses populating the four signature dimensions (4.3/4.4):
#       KuzushiRequirement, GripRequirement, ForceRequirement,
#       CoupleBodyPartRequirement, LeverBodyPartRequirement,
#       UkePostureRequirement, TimingWindow
#   - Axis / support / base-state enums referenced by the requirements
#   - FailureOutcome enum and FailureSpec — structured failure routing (4.5 + 6.3)
#   - CoupleThrow / LeverThrow template dataclasses (4.3 / 4.4)
#   - Default signature weights per classification (4.2)
#
# Part 5 (worked throws) instantiates these templates for Uchi-mata, O-soto-gari,
# Seoi-nage, and De-ashi-harai. The four-dimension match functions and weighted
# composition live in `throw_signature.py`.

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

from enums import BodyPart, GripTypeV2, GripDepth, GripMode


# ---------------------------------------------------------------------------
# CLASSIFICATION (Part 4.1)
# ---------------------------------------------------------------------------
class ThrowClassification(Enum):
    COUPLE = auto()   # Pure torque on uke's CoM via two opposing forces.
    LEVER  = auto()   # Fulcrum on tori; uke rotates over it.


# ---------------------------------------------------------------------------
# COUPLE AXIS (Part 4.3 — rotation axis the force couple acts about)
# ---------------------------------------------------------------------------
class CoupleAxis(Enum):
    VERTICAL   = auto()  # Rotation about uke's long axis — spin throws.
    SAGITTAL   = auto()  # Forward pitch — Uchi-mata family.
    TRANSVERSE = auto()  # Backward pitch — O-soto-gari family.


# ---------------------------------------------------------------------------
# SUPPORT REQUIREMENT (Part 4.4 — what tori's feet/knees must be doing)
# ---------------------------------------------------------------------------
class SupportRequirement(Enum):
    SINGLE_SUPPORT           = auto()  # One foot planted — most Couple throws.
    DOUBLE_SUPPORT           = auto()  # Both feet planted — most Lever standings.
    ONE_KNEE_DOWN_ONE_BENT   = auto()  # Seoi-nage one-knee drop.
    BOTH_KNEES_DOWN          = auto()  # Seoi-nage two-knee drop.


# ---------------------------------------------------------------------------
# UKE BASE STATE (Part 4.3 — what uke's base is doing at commit time)
# ---------------------------------------------------------------------------
class UkeBaseState(Enum):
    NEUTRAL                   = auto()
    WEIGHT_SHIFTING_FORWARD   = auto()  # Uchi-mata setup — weight rising onto toes.
    WEIGHT_ON_REAPED_LEG      = auto()  # General reap precondition.
    WEIGHT_ON_REAPED_LEG_HEEL = auto()  # O-soto-gari — heel loaded for the reap.
    MID_STEP                  = auto()  # De-ashi-harai — one foot in transition.


# ---------------------------------------------------------------------------
# FORCE KIND (Part 4.4 — specific pulls, pushes, lifts for Lever throws)
# ---------------------------------------------------------------------------
class ForceKind(Enum):
    PULL = auto()
    PUSH = auto()
    LIFT = auto()


# ---------------------------------------------------------------------------
# FAILURE OUTCOME (Part 4.5 + Part 6.3)
# Structured enum of the specific named compromised-state configurations the
# throw templates can route to on failure. The generic categories from 4.5
# (stance reset, partial throw, uke voluntarily to newaza, clean counter)
# round out the enum so a FailureSpec can name any of them.
# ---------------------------------------------------------------------------
class FailureOutcome(Enum):
    # Named compromised-state configurations (Part 6.3)
    TORI_COMPROMISED_FORWARD_LEAN    = auto()
    TORI_COMPROMISED_SINGLE_SUPPORT  = auto()
    TORI_STUCK_WITH_UKE_ON_BACK      = auto()
    TORI_BENT_FORWARD_LOADED         = auto()
    TORI_ON_KNEE_UKE_STANDING        = auto()
    TORI_ON_BOTH_KNEES_UKE_STANDING  = auto()
    TORI_SWEEP_BOUNCES_OFF           = auto()
    # Generic 4.5 outcomes
    PARTIAL_THROW                    = auto()
    STANCE_RESET                     = auto()
    UKE_VOLUNTARY_NEWAZA             = auto()
    # Named clean counters
    UCHI_MATA_SUKASHI                = auto()
    OSOTO_GAESHI                     = auto()
    URA_NAGE                         = auto()
    KAESHI_WAZA_GENERIC              = auto()


# ---------------------------------------------------------------------------
# SUB-REQUIREMENT DATACLASSES
# Each of the four signature dimensions is populated by one of these.
# Float angles are in RADIANS throughout (consistent with BodyState).
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class KuzushiRequirement:
    """Part 4.3 / 4.4 — kuzushi vector dimension.

    `direction` is a 2D unit vector in uke's body frame (forward = +X, right = +Y).
    Couple throws set `min_velocity_magnitude`; Lever throws set
    `min_displacement_past_recoverable`. Exactly one of the two is load-bearing
    for the match score, chosen by the enclosing template's classification.
    """
    direction: tuple[float, float]
    tolerance_rad: float
    min_velocity_magnitude: float = 0.0           # m/s — Couple dimension
    min_displacement_past_recoverable: float = 0.0  # m  — Lever dimension
    # Special-case flag: De-ashi-harai's kuzushi vector rides uke's existing
    # velocity rather than specifying a fixed direction. Set True to let the
    # match function score against any non-zero velocity in any direction.
    aligned_with_uke_velocity: bool = False


@dataclass(frozen=True)
class GripRequirement:
    """Part 4.3 / 4.4 — one grip the force-application dimension needs.

    `hand` is "right_hand" or "left_hand" in absolute terms (resolved at Part 5
    instantiation time based on sidedness). `grip_type` is one of the seven
    canonical standing grips; if multiple are acceptable use a tuple.
    `min_depth` is the minimum `GripDepth` on the (POCKET < STANDARD < DEEP)
    ordering. `mode` is the tick-mode the grip must be in to count.
    """
    hand: str
    grip_type: tuple[GripTypeV2, ...]
    min_depth: GripDepth = GripDepth.STANDARD
    mode: GripMode = GripMode.DRIVING


@dataclass(frozen=True)
class ForceRequirement:
    """Part 4.4 — Lever throws specify specific pulls/pushes/lifts.

    `direction` is in uke's body frame. `min_magnitude_n` is delivered force
    (post-envelope + modifiers). Couple throws typically skip this and lean
    on `min_torque_nm` on the enclosing template.
    """
    hand: str
    kind: ForceKind
    direction: tuple[float, float, float]
    min_magnitude_n: float


@dataclass(frozen=True)
class TimingWindow:
    """Part 4.6 — foot-sweep centered-window variant.

    When present on a Couple throw's body_part_requirement, the body-parts
    dimension is additionally gated by uke's `target_foot.weight_fraction`
    lying inside `weight_fraction_range` at commit time. Outside the window
    the body-parts match score plummets regardless of grip/posture.
    """
    target_foot: str                         # "right_foot" or "left_foot"
    weight_fraction_range: tuple[float, float]
    window_duration_ticks: int = 1


@dataclass(frozen=True)
class HipEngagementProfile:
    """Part 5 / HAJ-59 — quality penalty for hip engagement on throws whose
    fulcrum is NOT the hip (Tai-otoshi, O-soto-gari, Uchi-mata, etc.).

    Sensei rejects hip loading on these throws across the instructional
    corpus. Under Part 4.2.1 this is a quality reduction rather than a
    state failure: the throw fires, but at low execution_quality.

    The detector uses tori's `trunk_sagittal` at kake as a proxy for hip
    engagement. At or below `clean_trunk_sagittal_rad` the throw is clean
    (multiplier = 1.0); at or above `engaged_trunk_sagittal_rad` the
    multiplier collapses to `engaged_floor`; linear interpolation between.

    `engaged_floor` close to 0.0 (e.g., Tai-otoshi) collapses the body-
    parts dimension when hip-engaged — signature drops sharply, eq drops
    toward zero. A higher floor (e.g., 0.5 for O-soto) produces the ~0.3
    eq reduction described in HAJ-59 point 2.
    """
    clean_trunk_sagittal_rad:    float
    engaged_trunk_sagittal_rad:  float
    engaged_floor:               float


@dataclass(frozen=True)
class ContactQualityProfile:
    """Part 5.2 / HAJ-55 — continuous contact-quality dimensions feeding
    execution_quality (Part 4.2.1), not the commit gate.

    Two sub-scores are derived from horizontal CoM-to-CoM distance at kake:
      - torso_closure quality: 1.0 at ≤ `ideal_torso_closure_m`, linear
        falloff to 0.0 at `max_torso_closure_m`.
      - reaping_leg_contact quality: 1.0 at ≤ `ideal_reaping_contact_m`,
        linear falloff to 0.0 at `max_reaping_contact_m`.

    Both are appended to the Couple body-parts check list, so the signature
    still fires across the whole range — what varies is the body-parts
    score, and therefore execution_quality. Contact-point is *never* a
    hard gate.
    """
    ideal_torso_closure_m:   float
    max_torso_closure_m:     float
    ideal_reaping_contact_m: float
    max_reaping_contact_m:   float


@dataclass(frozen=True)
class CoupleBodyPartRequirement:
    """Part 4.3 — Couple throw body-parts dimension.

    `tori_supporting_foot` bears tori's weight during kake; `tori_attacking_limb`
    delivers the reap/sweep; `contact_point_on_uke` is where the attacking limb
    lands; `contact_height_range` bounds that contact vertically (meters above
    the mat). `timing_window` is populated only for ashi-waza variants.
    `contact_quality` is populated (Part 5.2, HAJ-55) for throws whose body
    dimension should score continuously on torso-closure / contact-point
    instead of binary-at-threshold.
    """
    tori_supporting_foot: str
    tori_attacking_limb:  str
    contact_point_on_uke: BodyPart
    contact_height_range: tuple[float, float]
    timing_window:   Optional[TimingWindow]           = None
    contact_quality: Optional[ContactQualityProfile]  = None
    hip_engagement:  Optional[HipEngagementProfile]   = None


@dataclass(frozen=True)
class LeverBodyPartRequirement:
    """Part 4.4 — Lever throw body-parts dimension.

    `fulcrum_body_part` is the one of tori's 24 parts the throw pivots around;
    `fulcrum_contact_on_uke` is where it bears against uke;
    `fulcrum_offset_below_uke_com_m` is the geometric constraint "tori's hips
    must be below uke's hips" expressed as a minimum positive offset.
    `tori_supporting_feet` constrains tori's base (double support, one knee
    down, etc. — see SupportRequirement).
    """
    fulcrum_body_part:                 BodyPart
    fulcrum_contact_on_uke:            BodyPart
    fulcrum_offset_below_uke_com_m:    float
    tori_supporting_feet:              SupportRequirement
    # HAJ-59 — hip-engagement quality penalty, populated for non-hip Lever
    # throws (e.g., Tai-otoshi, shin fulcrum). Hip-fulcrum throws leave
    # this None; they want hip engagement.
    hip_engagement: Optional[HipEngagementProfile] = None


@dataclass(frozen=True)
class UkePostureRequirement:
    """Part 4.3 / 4.4 — uke posture dimension. All angles in radians.

    `base_state` constrains what uke's base is doing (Couple-relevant; Lever
    templates typically leave NEUTRAL). `uke_com_over_fulcrum` is the Lever-
    specific geometric predicate; ignored for Couple.
    """
    trunk_sagittal_range:  tuple[float, float]
    trunk_frontal_range:   tuple[float, float]
    com_height_range:      tuple[float, float]    # meters above mat
    base_state:            UkeBaseState = UkeBaseState.NEUTRAL
    uke_com_over_fulcrum:  bool = False


# ---------------------------------------------------------------------------
# FAILURE SPEC (Part 4.5 — open-ended failure routing)
# Primary is the default landing spot; secondary/tertiary are alternatives
# chosen by the resolver based on uke resources, fight_iq, and tendencies.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FailureSpec:
    primary:   FailureOutcome
    secondary: Optional[FailureOutcome] = None
    tertiary:  Optional[FailureOutcome] = None


# ---------------------------------------------------------------------------
# SIGNATURE WEIGHTS (Part 4.2)
# Weights sum to 1.0 and are ordered (kuzushi, force, body, posture).
# Exact values are calibration targets; the spec commits only to the relative
# ordering per classification. These are reasonable starting points.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SignatureWeights:
    kuzushi: float
    force:   float
    body:    float
    posture: float

    def __post_init__(self) -> None:
        total = self.kuzushi + self.force + self.body + self.posture
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"SignatureWeights must sum to 1.0, got {total:.4f}"
            )


DEFAULT_COUPLE_WEIGHTS = SignatureWeights(
    kuzushi=0.20, force=0.35, body=0.35, posture=0.10,
)
DEFAULT_LEVER_WEIGHTS = SignatureWeights(
    kuzushi=0.35, force=0.20, body=0.35, posture=0.10,
)


def default_weights_for(classification: ThrowClassification) -> SignatureWeights:
    if classification == ThrowClassification.COUPLE:
        return DEFAULT_COUPLE_WEIGHTS
    return DEFAULT_LEVER_WEIGHTS


# ---------------------------------------------------------------------------
# COUPLE THROW TEMPLATE (Part 4.3)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CoupleThrow:
    """A Couple-class throw. The template; Part 5 produces instances."""
    name: str
    kuzushi_requirement:       KuzushiRequirement
    force_grips:               tuple[GripRequirement, ...]
    couple_axis:               CoupleAxis
    min_torque_nm:             float
    body_part_requirement:     CoupleBodyPartRequirement
    uke_posture_requirement:   UkePostureRequirement
    commit_threshold:          float     # Typically 0.4–0.6 (spec 4.3).
    sukashi_vulnerability:     float     # 0–1; probability weight for void counter.
    failure_outcome:           FailureSpec
    # Weight override — rarely used; most Couple throws accept the defaults.
    weights: Optional[SignatureWeights] = None

    classification: ThrowClassification = field(
        default=ThrowClassification.COUPLE, init=False,
    )

    def signature_weights(self) -> SignatureWeights:
        return self.weights or DEFAULT_COUPLE_WEIGHTS


# ---------------------------------------------------------------------------
# LEVER THROW TEMPLATE (Part 4.4)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LeverThrow:
    """A Lever-class throw. The template; Part 5 produces instances."""
    name: str
    kuzushi_requirement:       KuzushiRequirement
    force_grips:               tuple[GripRequirement, ...]
    required_forces:           tuple[ForceRequirement, ...]
    min_lift_force_n:          float
    body_part_requirement:     LeverBodyPartRequirement
    uke_posture_requirement:   UkePostureRequirement
    commit_threshold:          float     # Typically 0.6–0.8 (spec 4.4).
    counter_vulnerability:     float     # 0–1; weight for redirection counter.
    failure_outcome:           FailureSpec
    weights: Optional[SignatureWeights] = None

    classification: ThrowClassification = field(
        default=ThrowClassification.LEVER, init=False,
    )

    def signature_weights(self) -> SignatureWeights:
        return self.weights or DEFAULT_LEVER_WEIGHTS


# ---------------------------------------------------------------------------
# UNION HELPER
# Many Part 5 / Part 6 call sites want a "throw template of either kind" type.
# Python 3.10+ unions keep this light; explicit alias for readability.
# ---------------------------------------------------------------------------
ThrowTemplate = CoupleThrow | LeverThrow
