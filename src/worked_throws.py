# worked_throws.py
# Physics-substrate Part 5: parameterized instances of the Part 4 templates.
#
# Spec: design-notes/physics-substrate.md, Part 5 (sections 5.1–5.4).
#
# Four throws chosen to exercise every mechanic in Parts 1–4:
#   - Uchi-mata           — canonical forward-rotation Couple throw
#   - O-soto-gari         — canonical backward-rotation Couple throw
#   - Seoi-nage (morote)  — canonical Lever throw
#   - De-ashi-harai       — timing-window ashi-waza Couple variant
#
# The remaining v0.1 throws (HARAI_GOSHI, TAI_OTOSHI, O_UCHI_GARI, KO_UCHI_GARI,
# SUMI_GAESHI) stay on the legacy `ThrowDef`/`EdgeRequirement` path in throws.py
# until their Session-4 backfill lands.
#
# Sidedness: these are the right-sided canonical instances — they assume a
# right-dominant tori (tsurite=right, hikite=left). Left-dominant tori would
# need mirrored instances; v0.1 fighters (Tanaka, Sato) are both right-dominant.

from __future__ import annotations
import math

from enums import BodyPart, GripTypeV2, GripDepth, GripMode
from throws import ThrowID
from throw_templates import (
    CoupleThrow, LeverThrow, ThrowTemplate,
    KuzushiRequirement, GripRequirement, ForceRequirement, ForceKind,
    CoupleBodyPartRequirement, LeverBodyPartRequirement,
    UkePostureRequirement, TimingWindow,
    ContactQualityProfile, HipEngagementProfile,
    CoupleAxis, SupportRequirement, UkeBaseState,
    FailureOutcome, FailureSpec,
)


# HAJ-59 — starter hip-engagement profiles. The `engaged_floor` values are
# the calibration-target collapse points:
#   - Tai-otoshi (shin fulcrum): near-total collapse — the shin-block
#     geometry is incompatible with hip loading.
#   - O-soto-gari (Couple, transverse couple): ~50% body-dim penalty,
#     producing the ~0.3 eq reduction in HAJ-59 point 2.
#   - Uchi-mata (Couple, sagittal couple): same ~50% floor — the lift
#     becomes a bump.
# Angles in radians. Phase 3 tunes these against match feel.
_HIP_ENGAGEMENT_HARD = HipEngagementProfile(
    clean_trunk_sagittal_rad=math.radians(20),
    engaged_trunk_sagittal_rad=math.radians(40),
    engaged_floor=0.05,           # Tai-otoshi — collapse
)
_HIP_ENGAGEMENT_SOFT = HipEngagementProfile(
    clean_trunk_sagittal_rad=math.radians(15),
    engaged_trunk_sagittal_rad=math.radians(35),
    engaged_floor=0.50,           # O-soto-gari, Uchi-mata — ~0.3 eq reduction
)


# ---------------------------------------------------------------------------
# UCHI-MATA (内股) — spec 5.1
# ---------------------------------------------------------------------------
UCHI_MATA: CoupleThrow = CoupleThrow(
    name="Uchi-mata",
    kuzushi_requirement=KuzushiRequirement(
        direction=(1.0, 0.3),                    # forward + slight right in uke's frame
        tolerance_rad=math.radians(30),
        min_velocity_magnitude=0.4,              # uke onto the toes
    ),
    force_grips=(
        GripRequirement(
            hand="left_hand",                    # hikite
            grip_type=(GripTypeV2.SLEEVE,),
            min_depth=GripDepth.STANDARD,
            mode=GripMode.DRIVING,
        ),
        GripRequirement(
            hand="right_hand",                   # tsurite
            grip_type=(GripTypeV2.LAPEL_HIGH, GripTypeV2.COLLAR),
            min_depth=GripDepth.STANDARD,
            mode=GripMode.DRIVING,
        ),
    ),
    couple_axis=CoupleAxis.SAGITTAL,             # forward pitch
    min_torque_nm=500.0,                         # moderate-to-high
    body_part_requirement=CoupleBodyPartRequirement(
        tori_supporting_foot="left_foot",
        tori_attacking_limb="right_leg",
        contact_point_on_uke=BodyPart.LEFT_THIGH,
        contact_height_range=(0.55, 0.90),       # upper thigh to hip crease
        # HAJ-59 — top-leg Uchi-mata variant: hip engagement turns the
        # lift into a bump. Throw still fires at reduced quality.
        hip_engagement=_HIP_ENGAGEMENT_SOFT,
        # HAJ-57 — even though Uchi-mata is torque-driven (Couple), the
        # body-part requirement demands tori's hip in close contact with
        # uke's hip line for the reap to land. Hip-blockable.
        hip_loading=True,
    ),
    uke_posture_requirement=UkePostureRequirement(
        trunk_sagittal_range=(math.radians(-5), math.radians(20)),
        trunk_frontal_range=(math.radians(-15), math.radians(25)),
        com_height_range=(0.95, 1.30),           # HIGH — weight rising onto toes
        base_state=UkeBaseState.WEIGHT_SHIFTING_FORWARD,
    ),
    commit_threshold=0.55,
    sukashi_vulnerability=0.75,                  # HIGH — uchi-mata-sukashi is real
    failure_outcome=FailureSpec(
        primary=FailureOutcome.TORI_COMPROMISED_SINGLE_SUPPORT,
        secondary=FailureOutcome.UCHI_MATA_SUKASHI,
        tertiary=FailureOutcome.STANCE_RESET,
    ),
)


# ---------------------------------------------------------------------------
# O-SOTO-GARI (大外刈) — spec 5.2
# ---------------------------------------------------------------------------
O_SOTO_GARI: CoupleThrow = CoupleThrow(
    name="O-soto-gari",
    kuzushi_requirement=KuzushiRequirement(
        direction=(-1.0, 0.5),                   # backward + rightward in uke's frame
        tolerance_rad=math.radians(25),
        min_velocity_magnitude=0.3,              # reaction to pull / step onto heel
    ),
    force_grips=(
        GripRequirement(
            hand="left_hand",                    # hikite
            grip_type=(GripTypeV2.SLEEVE,),
            min_depth=GripDepth.STANDARD,
            mode=GripMode.DRIVING,
        ),
        GripRequirement(
            hand="right_hand",                   # tsurite
            grip_type=(GripTypeV2.LAPEL_LOW, GripTypeV2.LAPEL_HIGH),
            min_depth=GripDepth.STANDARD,
            mode=GripMode.DRIVING,
        ),
    ),
    couple_axis=CoupleAxis.TRANSVERSE,           # backward pitch
    min_torque_nm=600.0,                         # high — requires strong pivot-knee extension
    body_part_requirement=CoupleBodyPartRequirement(
        tori_supporting_foot="left_foot",        # planted alongside uke's right foot
        tori_attacking_limb="right_leg",
        contact_point_on_uke=BodyPart.RIGHT_THIGH,
        contact_height_range=(0.35, 0.65),       # knee to mid-thigh
        # HAJ-55 — contact-point + torso-closure feed execution_quality.
        # Ideal: thigh-to-thigh (≤0.50 m) + chest-to-chest (≤0.45 m).
        # Max  : heel-to-calf reach (≥1.20 m) + arm's length (≥1.10 m).
        contact_quality=ContactQualityProfile(
            ideal_torso_closure_m=0.45,
            max_torso_closure_m=1.10,
            ideal_reaping_contact_m=0.50,
            max_reaping_contact_m=1.20,
        ),
        # HAJ-59 — backward-rotation Couple; hip loading dilutes the
        # transverse torque (reap becomes a shove from the waist).
        hip_engagement=_HIP_ENGAGEMENT_SOFT,
    ),
    uke_posture_requirement=UkePostureRequirement(
        trunk_sagittal_range=(math.radians(-10), math.radians(5)),
        trunk_frontal_range=(math.radians(-15), math.radians(20)),
        com_height_range=(0.88, 1.15),           # MEDIUM_HIGH — not jigotai
        base_state=UkeBaseState.WEIGHT_ON_REAPED_LEG_HEEL,
    ),
    commit_threshold=0.50,
    sukashi_vulnerability=0.35,                  # osoto-sukashi is rare
    failure_outcome=FailureSpec(
        primary=FailureOutcome.TORI_COMPROMISED_FORWARD_LEAN,
        secondary=FailureOutcome.OSOTO_GAESHI,
        tertiary=FailureOutcome.STANCE_RESET,
    ),
)


# ---------------------------------------------------------------------------
# SEOI-NAGE (背負投, morote form) — spec 5.3
# ---------------------------------------------------------------------------
SEOI_NAGE_MOROTE: LeverThrow = LeverThrow(
    name="Seoi-nage",
    kuzushi_requirement=KuzushiRequirement(
        direction=(1.0, 0.2),                    # forward, very slight right-corner
        tolerance_rad=math.radians(20),
        min_displacement_past_recoverable=0.15,  # real kuzushi, not incipient
    ),
    force_grips=(
        GripRequirement(
            hand="left_hand",                    # hikite
            grip_type=(GripTypeV2.SLEEVE,),
            min_depth=GripDepth.STANDARD,
            mode=GripMode.DRIVING,
        ),
        GripRequirement(
            hand="right_hand",                   # tsurite
            grip_type=(GripTypeV2.LAPEL_LOW, GripTypeV2.LAPEL_HIGH),
            min_depth=GripDepth.STANDARD,
            mode=GripMode.DRIVING,
        ),
    ),
    required_forces=(
        ForceRequirement(                        # hikite pull, ~30° below horizontal
            hand="left_hand", kind=ForceKind.PULL,
            direction=(1.0, 0.0, -0.58),         # forward-down across tori's body
            min_magnitude_n=300.0,
        ),
        ForceRequirement(                        # tsurite lift + forward push
            hand="right_hand", kind=ForceKind.LIFT,
            direction=(0.7, 0.0, 0.71),          # forward-up; internal shoulder rotation
            min_magnitude_n=250.0,
        ),
    ),
    min_lift_force_n=600.0,                      # HIGH — sustained through kake
    body_part_requirement=LeverBodyPartRequirement(
        fulcrum_body_part=BodyPart.RIGHT_SHOULDER,
        fulcrum_contact_on_uke=BodyPart.CORE,    # chest-and-right-armpit → simplified to CORE
        fulcrum_offset_below_uke_com_m=0.15,     # tori's hips below uke's by ≥ 0.15 m
        tori_supporting_feet=SupportRequirement.DOUBLE_SUPPORT,
        hip_loading=True,                        # HAJ-57 — shoulder lift loads uke's weight
    ),
    uke_posture_requirement=UkePostureRequirement(
        trunk_sagittal_range=(math.radians(0), math.radians(30)),    # upright or forward
        trunk_frontal_range=(math.radians(-15), math.radians(15)),
        com_height_range=(0.88, 1.20),           # NOT jigotai-low, NOT back-leaning
        uke_com_over_fulcrum=True,
    ),
    commit_threshold=0.70,                       # HIGH — cannot exploit partial kuzushi
    counter_vulnerability=0.55,                  # ura-nage, sode-tsurikomi-gaeshi
    failure_outcome=FailureSpec(
        primary=FailureOutcome.TORI_STUCK_WITH_UKE_ON_BACK,
        secondary=FailureOutcome.TORI_BENT_FORWARD_LOADED,
        tertiary=FailureOutcome.STANCE_RESET,
    ),
    # Shoulder-fulcrum lift cannot be driven without tsurite on the lapel
    # or collar — the lift channel IS the dominant hand.
    requires_dominant_hand_grip=True,
)


# ---------------------------------------------------------------------------
# DE-ASHI-HARAI (出足払) — spec 5.4
# ---------------------------------------------------------------------------
DE_ASHI_HARAI: CoupleThrow = CoupleThrow(
    name="De-ashi-harai",
    kuzushi_requirement=KuzushiRequirement(
        direction=(1.0, 0.0),                    # nominal — overridden by aligned flag
        tolerance_rad=math.radians(45),          # wide — motion is uke's own
        min_velocity_magnitude=0.3,              # uke must actually be stepping
        aligned_with_uke_velocity=True,          # catches any non-zero uke velocity
    ),
    force_grips=(
        GripRequirement(
            hand="left_hand",                    # hikite — destabilizes upper body
            grip_type=(GripTypeV2.SLEEVE,),
            min_depth=GripDepth.STANDARD,
            mode=GripMode.DRIVING,
        ),
        GripRequirement(
            hand="right_hand",                   # tsurite — light downward pull
            grip_type=(GripTypeV2.LAPEL_LOW,),
            min_depth=GripDepth.POCKET,          # pocket is enough — the foot does the work
            mode=GripMode.DRIVING,
        ),
    ),
    couple_axis=CoupleAxis.TRANSVERSE,
    min_torque_nm=150.0,                         # LOW — hands only destabilize
    body_part_requirement=CoupleBodyPartRequirement(
        tori_supporting_foot="left_foot",
        tori_attacking_limb="right_foot",
        contact_point_on_uke=BodyPart.RIGHT_FOOT,
        contact_height_range=(0.0, 0.15),
        timing_window=TimingWindow(
            target_foot="right_foot",            # uke's forward-stepping foot
            weight_fraction_range=(0.1, 0.3),    # narrow unweighting window
            window_duration_ticks=1,
        ),
    ),
    uke_posture_requirement=UkePostureRequirement(
        trunk_sagittal_range=(math.radians(-10), math.radians(15)),
        trunk_frontal_range=(math.radians(-45), math.radians(45)),   # any
        com_height_range=(0.70, 1.40),                                # any
        base_state=UkeBaseState.MID_STEP,
    ),
    commit_threshold=0.45,                       # moderate — useless without timing window
    sukashi_vulnerability=0.25,
    failure_outcome=FailureSpec(
        primary=FailureOutcome.TORI_SWEEP_BOUNCES_OFF,
        secondary=FailureOutcome.STANCE_RESET,
        tertiary=FailureOutcome.PARTIAL_THROW,
    ),
)


# ===========================================================================
# PART 5.5 / HAJ-29 BACKFILL
# The remaining v0.1 throws, each inheriting the template structure without
# new physics code. Research depth varies per spec 5.5 — numerical values
# are starter calibrations. Phase 3 work will tune these against match feel.
# ===========================================================================

# ---------------------------------------------------------------------------
# O-GOSHI (大腰) — Lever, sacrum/hip fulcrum (foundational hip throw)
# ---------------------------------------------------------------------------
O_GOSHI: LeverThrow = LeverThrow(
    name="O-goshi",
    kuzushi_requirement=KuzushiRequirement(
        direction=(1.0, 0.0),                    # straight forward
        tolerance_rad=math.radians(25),
        min_displacement_past_recoverable=0.12,
    ),
    force_grips=(
        GripRequirement(
            hand="left_hand",                    # hikite (sleeve)
            grip_type=(GripTypeV2.SLEEVE,),
            min_depth=GripDepth.STANDARD,
            mode=GripMode.DRIVING,
        ),
        GripRequirement(
            hand="right_hand",                   # tsurite — belt or lapel
            grip_type=(GripTypeV2.BELT, GripTypeV2.LAPEL_HIGH),
            min_depth=GripDepth.STANDARD,
            mode=GripMode.DRIVING,
        ),
    ),
    required_forces=(
        ForceRequirement(
            hand="left_hand", kind=ForceKind.PULL,
            direction=(1.0, 0.0, -0.3),
            min_magnitude_n=280.0,
        ),
        ForceRequirement(
            hand="right_hand", kind=ForceKind.LIFT,
            direction=(0.4, 0.0, 0.92),          # mostly up + slight forward
            min_magnitude_n=300.0,
        ),
    ),
    min_lift_force_n=550.0,                      # sustained lift through kake
    body_part_requirement=LeverBodyPartRequirement(
        fulcrum_body_part=BodyPart.LOWER_BACK,   # sacrum region
        fulcrum_contact_on_uke=BodyPart.CORE,
        fulcrum_offset_below_uke_com_m=0.12,
        tori_supporting_feet=SupportRequirement.DOUBLE_SUPPORT,
        hip_loading=True,                        # HAJ-57 — sacrum/hip fulcrum, classical hip throw
    ),
    uke_posture_requirement=UkePostureRequirement(
        trunk_sagittal_range=(math.radians(-5), math.radians(25)),
        trunk_frontal_range=(math.radians(-15), math.radians(15)),
        com_height_range=(0.88, 1.25),
        uke_com_over_fulcrum=True,
    ),
    commit_threshold=0.65,
    counter_vulnerability=0.55,
    failure_outcome=FailureSpec(
        primary=FailureOutcome.TORI_BENT_FORWARD_LOADED,
        secondary=FailureOutcome.KAESHI_WAZA_GENERIC,
        tertiary=FailureOutcome.STANCE_RESET,
    ),
    # Hip-fulcrum lift — tsurite on belt/lapel carries uke's weight over
    # the sacrum. Dominant hand free collapses the lift channel.
    requires_dominant_hand_grip=True,
)


# ---------------------------------------------------------------------------
# TAI-OTOSHI (体落) — Lever, shin fulcrum, pure rotational (no lift)
# ---------------------------------------------------------------------------
TAI_OTOSHI: LeverThrow = LeverThrow(
    name="Tai-otoshi",
    kuzushi_requirement=KuzushiRequirement(
        direction=(1.0, 0.15),
        tolerance_rad=math.radians(20),
        min_displacement_past_recoverable=0.12,
    ),
    force_grips=(
        GripRequirement(
            hand="left_hand",
            grip_type=(GripTypeV2.SLEEVE,),
            min_depth=GripDepth.STANDARD,
            mode=GripMode.DRIVING,
        ),
        GripRequirement(
            hand="right_hand",
            grip_type=(GripTypeV2.LAPEL_HIGH, GripTypeV2.LAPEL_LOW),
            min_depth=GripDepth.STANDARD,
            mode=GripMode.DRIVING,
        ),
    ),
    required_forces=(
        ForceRequirement(
            hand="left_hand", kind=ForceKind.PULL,
            direction=(1.0, 0.0, -0.4),
            min_magnitude_n=320.0,
        ),
    ),
    min_lift_force_n=150.0,                      # LOW — pure rotational, no lift
    body_part_requirement=LeverBodyPartRequirement(
        fulcrum_body_part=BodyPart.RIGHT_KNEE,   # extended shin/knee as block
        fulcrum_contact_on_uke=BodyPart.RIGHT_KNEE,
        fulcrum_offset_below_uke_com_m=0.05,     # shin-low fulcrum, not hip-low
        tori_supporting_feet=SupportRequirement.DOUBLE_SUPPORT,
        # HAJ-59 — hips must stay back; shin-block geometry is incompatible
        # with hip loading. Hard collapse toward eq=0 when engaged.
        hip_engagement=_HIP_ENGAGEMENT_HARD,
        # HAJ-57 — even with shin (not hip) as fulcrum, the throw demands
        # tori rotate past uke's hip line. Uke's hip-drive denies the
        # turn-in geometry, not the eventual fulcrum.
        hip_loading=True,
    ),
    uke_posture_requirement=UkePostureRequirement(
        trunk_sagittal_range=(math.radians(-5), math.radians(25)),
        trunk_frontal_range=(math.radians(-20), math.radians(20)),
        com_height_range=(0.88, 1.25),
        uke_com_over_fulcrum=True,
    ),
    commit_threshold=0.65,
    counter_vulnerability=0.45,
    failure_outcome=FailureSpec(
        primary=FailureOutcome.TORI_COMPROMISED_FORWARD_LEAN,
        secondary=FailureOutcome.KAESHI_WAZA_GENERIC,
        tertiary=FailureOutcome.STANCE_RESET,
    ),
    # Pure rotational Lever — tsurite on lapel rotates uke over the shin
    # block. Without the dominant hand the pull-around vector is lost.
    requires_dominant_hand_grip=True,
)


# ---------------------------------------------------------------------------
# KO-UCHI-GARI (小内刈) — Couple, timing-sensitive ashi-waza
# Spec 5.5: "most timing-sensitive ashi-waza, possibly gets the timing_window
# variant like de-ashi-harai." Modeled with a timing window on uke's rear foot.
# ---------------------------------------------------------------------------
KO_UCHI_GARI: CoupleThrow = CoupleThrow(
    name="Ko-uchi-gari",
    kuzushi_requirement=KuzushiRequirement(
        direction=(-0.7, 0.3),                   # back and slightly lateral
        tolerance_rad=math.radians(35),
        min_velocity_magnitude=0.25,
    ),
    force_grips=(
        GripRequirement(
            hand="left_hand",
            grip_type=(GripTypeV2.SLEEVE,),
            min_depth=GripDepth.POCKET,
            mode=GripMode.DRIVING,
        ),
        GripRequirement(
            hand="right_hand",
            grip_type=(GripTypeV2.LAPEL_LOW, GripTypeV2.LAPEL_HIGH),
            min_depth=GripDepth.POCKET,
            mode=GripMode.DRIVING,
        ),
    ),
    couple_axis=CoupleAxis.TRANSVERSE,
    min_torque_nm=150.0,                         # low — timing does the work
    body_part_requirement=CoupleBodyPartRequirement(
        tori_supporting_foot="left_foot",
        tori_attacking_limb="right_foot",
        contact_point_on_uke=BodyPart.RIGHT_FOOT,
        contact_height_range=(0.0, 0.20),
        timing_window=TimingWindow(
            target_foot="right_foot",
            weight_fraction_range=(0.15, 0.40),  # slightly wider window than de-ashi
            window_duration_ticks=1,
        ),
    ),
    uke_posture_requirement=UkePostureRequirement(
        trunk_sagittal_range=(math.radians(-15), math.radians(20)),
        trunk_frontal_range=(math.radians(-45), math.radians(45)),
        com_height_range=(0.70, 1.40),
        base_state=UkeBaseState.MID_STEP,
    ),
    commit_threshold=0.45,
    sukashi_vulnerability=0.25,
    failure_outcome=FailureSpec(
        primary=FailureOutcome.TORI_SWEEP_BOUNCES_OFF,
        secondary=FailureOutcome.STANCE_RESET,
        tertiary=FailureOutcome.PARTIAL_THROW,
    ),
)


# ---------------------------------------------------------------------------
# O-UCHI-GARI (大内刈) — Couple, backward kuzushi, standard force-couple
# ---------------------------------------------------------------------------
O_UCHI_GARI: CoupleThrow = CoupleThrow(
    name="O-uchi-gari",
    kuzushi_requirement=KuzushiRequirement(
        direction=(-1.0, -0.2),                  # backward and slightly left
        tolerance_rad=math.radians(30),
        min_velocity_magnitude=0.3,
    ),
    force_grips=(
        GripRequirement(
            hand="left_hand",
            grip_type=(GripTypeV2.SLEEVE,),
            min_depth=GripDepth.STANDARD,
            mode=GripMode.DRIVING,
        ),
        GripRequirement(
            hand="right_hand",
            grip_type=(GripTypeV2.LAPEL_LOW, GripTypeV2.LAPEL_HIGH),
            min_depth=GripDepth.STANDARD,
            mode=GripMode.DRIVING,
        ),
    ),
    couple_axis=CoupleAxis.TRANSVERSE,
    min_torque_nm=400.0,
    body_part_requirement=CoupleBodyPartRequirement(
        tori_supporting_foot="left_foot",
        tori_attacking_limb="right_leg",
        contact_point_on_uke=BodyPart.LEFT_THIGH,    # inner thigh hook
        contact_height_range=(0.40, 0.70),
    ),
    uke_posture_requirement=UkePostureRequirement(
        trunk_sagittal_range=(math.radians(-10), math.radians(15)),
        trunk_frontal_range=(math.radians(-20), math.radians(20)),
        com_height_range=(0.85, 1.20),
        base_state=UkeBaseState.WEIGHT_ON_REAPED_LEG,
    ),
    commit_threshold=0.50,
    sukashi_vulnerability=0.30,
    failure_outcome=FailureSpec(
        primary=FailureOutcome.TORI_COMPROMISED_SINGLE_SUPPORT,
        secondary=FailureOutcome.STANCE_RESET,
        tertiary=FailureOutcome.PARTIAL_THROW,
    ),
)


# ---------------------------------------------------------------------------
# HARAI-GOSHI (払腰) competitive form — Couple
# Per spec 5.5 / Imamura 2007: modern competitive Harai-goshi is Couple-class.
# ---------------------------------------------------------------------------
HARAI_GOSHI: CoupleThrow = CoupleThrow(
    name="Harai-goshi",
    kuzushi_requirement=KuzushiRequirement(
        direction=(1.0, 0.3),                    # forward-right corner
        tolerance_rad=math.radians(30),
        min_velocity_magnitude=0.4,
    ),
    force_grips=(
        GripRequirement(
            hand="left_hand",
            grip_type=(GripTypeV2.SLEEVE,),
            min_depth=GripDepth.STANDARD,
            mode=GripMode.DRIVING,
        ),
        GripRequirement(
            hand="right_hand",
            grip_type=(GripTypeV2.LAPEL_HIGH, GripTypeV2.COLLAR),
            min_depth=GripDepth.STANDARD,
            mode=GripMode.DRIVING,
        ),
    ),
    couple_axis=CoupleAxis.SAGITTAL,
    min_torque_nm=550.0,
    body_part_requirement=CoupleBodyPartRequirement(
        tori_supporting_foot="left_foot",
        tori_attacking_limb="right_leg",
        contact_point_on_uke=BodyPart.RIGHT_THIGH,   # sweeping leg brushes far thigh
        contact_height_range=(0.45, 0.80),
        # HAJ-57 — competitive Harai-goshi still tucks tori's hip against
        # uke's hip line for the sweep to be levered. Hip-blockable.
        hip_loading=True,
    ),
    uke_posture_requirement=UkePostureRequirement(
        trunk_sagittal_range=(math.radians(-5), math.radians(25)),
        trunk_frontal_range=(math.radians(-15), math.radians(25)),
        com_height_range=(0.95, 1.30),
        base_state=UkeBaseState.WEIGHT_SHIFTING_FORWARD,
    ),
    commit_threshold=0.55,
    sukashi_vulnerability=0.55,
    failure_outcome=FailureSpec(
        primary=FailureOutcome.TORI_COMPROMISED_SINGLE_SUPPORT,
        secondary=FailureOutcome.TORI_COMPROMISED_FORWARD_LEAN,
        tertiary=FailureOutcome.STANCE_RESET,
    ),
)


# ---------------------------------------------------------------------------
# HARAI-GOSHI (払腰) classical form — Lever, hip fulcrum
# ---------------------------------------------------------------------------
HARAI_GOSHI_CLASSICAL: LeverThrow = LeverThrow(
    name="Harai-goshi (classical)",
    kuzushi_requirement=KuzushiRequirement(
        direction=(1.0, 0.25),
        tolerance_rad=math.radians(22),
        min_displacement_past_recoverable=0.12,
    ),
    force_grips=(
        GripRequirement(
            hand="left_hand",
            grip_type=(GripTypeV2.SLEEVE,),
            min_depth=GripDepth.STANDARD,
            mode=GripMode.DRIVING,
        ),
        GripRequirement(
            hand="right_hand",
            grip_type=(GripTypeV2.LAPEL_HIGH, GripTypeV2.COLLAR),
            min_depth=GripDepth.STANDARD,
            mode=GripMode.DRIVING,
        ),
    ),
    required_forces=(
        ForceRequirement(
            hand="left_hand", kind=ForceKind.PULL,
            direction=(1.0, 0.0, -0.3),
            min_magnitude_n=300.0,
        ),
    ),
    min_lift_force_n=450.0,
    body_part_requirement=LeverBodyPartRequirement(
        fulcrum_body_part=BodyPart.RIGHT_HIP,
        fulcrum_contact_on_uke=BodyPart.CORE,
        fulcrum_offset_below_uke_com_m=0.10,
        tori_supporting_feet=SupportRequirement.DOUBLE_SUPPORT,
        hip_loading=True,                        # HAJ-57 — classical hip-fulcrum hip throw
    ),
    uke_posture_requirement=UkePostureRequirement(
        trunk_sagittal_range=(math.radians(0), math.radians(25)),
        trunk_frontal_range=(math.radians(-15), math.radians(15)),
        com_height_range=(0.90, 1.25),
        uke_com_over_fulcrum=True,
    ),
    commit_threshold=0.68,
    counter_vulnerability=0.55,
    failure_outcome=FailureSpec(
        primary=FailureOutcome.TORI_BENT_FORWARD_LOADED,
        secondary=FailureOutcome.KAESHI_WAZA_GENERIC,
        tertiary=FailureOutcome.STANCE_RESET,
    ),
    # Hip-fulcrum Lever — same lift-channel requirement as O-goshi.
    requires_dominant_hand_grip=True,
)


# ---------------------------------------------------------------------------
# TOMOE-NAGE (巴投) — Lever with inverted commit
# Spec 5.5: tori sacrifices own balance as part of kuzushi; foot-on-belt
# fulcrum. Commit threshold slightly lower than other Lever forms because
# tori is already giving up standing position.
# ---------------------------------------------------------------------------
TOMOE_NAGE: LeverThrow = LeverThrow(
    name="Tomoe-nage",
    kuzushi_requirement=KuzushiRequirement(
        direction=(1.0, 0.0),                    # straight forward — uke must be coming in
        tolerance_rad=math.radians(25),
        min_displacement_past_recoverable=0.10,
    ),
    force_grips=(
        GripRequirement(
            hand="left_hand",
            grip_type=(GripTypeV2.SLEEVE,),
            min_depth=GripDepth.STANDARD,
            mode=GripMode.DRIVING,
        ),
        GripRequirement(
            hand="right_hand",
            grip_type=(GripTypeV2.LAPEL_LOW, GripTypeV2.LAPEL_HIGH),
            min_depth=GripDepth.STANDARD,
            mode=GripMode.DRIVING,
        ),
    ),
    required_forces=(
        ForceRequirement(
            hand="left_hand", kind=ForceKind.PULL,
            direction=(1.0, 0.0, 0.3),           # pull forward-up as tori drops
            min_magnitude_n=350.0,
        ),
    ),
    min_lift_force_n=200.0,                      # LOW — tori goes under; gravity finishes it
    body_part_requirement=LeverBodyPartRequirement(
        fulcrum_body_part=BodyPart.RIGHT_FOOT,   # foot planted on uke's belt/lower abdomen
        fulcrum_contact_on_uke=BodyPart.CORE,
        fulcrum_offset_below_uke_com_m=0.0,      # tori on the ground; offset not the usual constraint
        tori_supporting_feet=SupportRequirement.ONE_KNEE_DOWN_ONE_BENT,
        # HAJ-57 — sacrifice throw with foot-on-belt fulcrum below uke. A
        # uke hip drop helps tori (gives them the lift), so hip block is
        # not a defense. Stays False.
    ),
    uke_posture_requirement=UkePostureRequirement(
        trunk_sagittal_range=(math.radians(-5), math.radians(30)),
        trunk_frontal_range=(math.radians(-20), math.radians(20)),
        com_height_range=(0.85, 1.30),
        uke_com_over_fulcrum=True,
    ),
    commit_threshold=0.60,                       # slightly lower — sacrifice nature
    counter_vulnerability=0.65,                  # tori is on the ground; miss = bad
    failure_outcome=FailureSpec(
        primary=FailureOutcome.TORI_ON_BOTH_KNEES_UKE_STANDING,
        secondary=FailureOutcome.UKE_VOLUNTARY_NEWAZA,
        tertiary=FailureOutcome.STANCE_RESET,
    ),
)


# ---------------------------------------------------------------------------
# O-GURUMA (大車) — Lever, extended-leg fulcrum at hip-line
# Spec 5.5: "maximum moment arm among Lever throws."
# ---------------------------------------------------------------------------
O_GURUMA: LeverThrow = LeverThrow(
    name="O-guruma",
    kuzushi_requirement=KuzushiRequirement(
        direction=(1.0, 0.3),
        tolerance_rad=math.radians(22),
        min_displacement_past_recoverable=0.13,
    ),
    force_grips=(
        GripRequirement(
            hand="left_hand",
            grip_type=(GripTypeV2.SLEEVE,),
            min_depth=GripDepth.STANDARD,
            mode=GripMode.DRIVING,
        ),
        GripRequirement(
            hand="right_hand",
            grip_type=(GripTypeV2.LAPEL_HIGH, GripTypeV2.COLLAR),
            min_depth=GripDepth.STANDARD,
            mode=GripMode.DRIVING,
        ),
    ),
    required_forces=(
        ForceRequirement(
            hand="left_hand", kind=ForceKind.PULL,
            direction=(1.0, 0.0, -0.2),
            min_magnitude_n=320.0,
        ),
    ),
    min_lift_force_n=400.0,
    body_part_requirement=LeverBodyPartRequirement(
        fulcrum_body_part=BodyPart.RIGHT_THIGH,  # extended leg at hip-line
        fulcrum_contact_on_uke=BodyPart.CORE,
        fulcrum_offset_below_uke_com_m=0.08,
        tori_supporting_feet=SupportRequirement.DOUBLE_SUPPORT,
        hip_loading=True,                        # HAJ-57 — extended-leg fulcrum at hip-line
    ),
    uke_posture_requirement=UkePostureRequirement(
        trunk_sagittal_range=(math.radians(0), math.radians(30)),
        trunk_frontal_range=(math.radians(-15), math.radians(20)),
        com_height_range=(0.90, 1.30),
        uke_com_over_fulcrum=True,
    ),
    commit_threshold=0.65,
    counter_vulnerability=0.50,
    failure_outcome=FailureSpec(
        primary=FailureOutcome.TORI_BENT_FORWARD_LOADED,
        secondary=FailureOutcome.KAESHI_WAZA_GENERIC,
        tertiary=FailureOutcome.STANCE_RESET,
    ),
    # Extended-leg fulcrum with maximum moment arm — tsurite loads uke
    # over the extended leg. No lift channel without the dominant hand.
    requires_dominant_hand_grip=True,
)


# ---------------------------------------------------------------------------
# REGISTRY
# Maps ThrowID → worked template. Throws not in this table fall back to the
# legacy THROW_DEFS / EdgeRequirement path in throws.py.
# ---------------------------------------------------------------------------
WORKED_THROWS: dict[ThrowID, ThrowTemplate] = {
    # Part 5.1–5.4 — the originally-specified four
    ThrowID.UCHI_MATA:             UCHI_MATA,
    ThrowID.O_SOTO_GARI:           O_SOTO_GARI,
    ThrowID.SEOI_NAGE:             SEOI_NAGE_MOROTE,
    ThrowID.DE_ASHI_HARAI:         DE_ASHI_HARAI,
    # Part 5.5 / HAJ-29 backfill
    ThrowID.O_GOSHI:               O_GOSHI,
    ThrowID.TAI_OTOSHI:            TAI_OTOSHI,
    ThrowID.KO_UCHI_GARI:          KO_UCHI_GARI,
    ThrowID.O_UCHI_GARI:           O_UCHI_GARI,
    ThrowID.HARAI_GOSHI:           HARAI_GOSHI,
    ThrowID.HARAI_GOSHI_CLASSICAL: HARAI_GOSHI_CLASSICAL,
    ThrowID.TOMOE_NAGE:            TOMOE_NAGE,
    ThrowID.O_GURUMA:              O_GURUMA,
}


def worked_template_for(throw_id: ThrowID) -> ThrowTemplate | None:
    """Return the Part-5 worked template for a throw, or None if it's still
    on the legacy ThrowDef path.
    """
    return WORKED_THROWS.get(throw_id)
