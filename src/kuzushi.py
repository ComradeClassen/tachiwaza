# kuzushi.py
# Phase A.1 — grip-as-cause polarity reversal foundation (HAJ-130).
#
# Spec: design-notes/grip-as-cause.md §2 (Event-Driven Kuzushi) and §3.6
# (Combo Pulls and Sequence Composition).
#
# Kuzushi was previously a momentary CoM-envelope predicate
# (body_state.is_kuzushi). The spec wants it as a decaying *event log*: each
# pull or foot attack emits a force event into uke's buffer, and the throw
# selection layer reads the *accumulated, decayed* state to decide whether
# uke is currently compromised in a way some throw's signature matches.
#
# This module is data + math only. Nothing here mutates Judoka or fires from
# action handlers — that wiring is HAJ-A.2 (PULL emits) and HAJ-A.3
# (signature_match reads).
#
# Naming note: the existing `compromised_state.py` module uses the same word
# for the *failed-throw* tori-state machine (Part 6.3). Different concept,
# different namespace. Importing both side-by-side is fine because the
# clashing name `compromised_state` only exists as a function in this module
# and as a module name elsewhere.

from __future__ import annotations
import math
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Iterable, Optional

if TYPE_CHECKING:
    from judoka import Judoka
    from grip_graph import GripEdge
    from enums import GripTypeV2 as _GripTypeV2
    from actions import ActionKind as _ActionKind

# 2D vector in the mat frame, meters or m/s depending on context. Aligned
# with body_state.py's convention so events can be composed directly with
# CoM velocities without a wrapper type.
Vector2 = tuple[float, float]


# ---------------------------------------------------------------------------
# SOURCE
# ---------------------------------------------------------------------------
class KuzushiSource(Enum):
    """Where a kuzushi event came from. Drives source-specific scoring at the
    signature-match layer (HAJ-A.3 onward) — e.g. foot attacks may compose
    with pulls but score differently for sweep-family throws."""
    PULL        = auto()  # Emitted by a PULL action through an established grip.
    FOOT_ATTACK = auto()  # Emitted by ko-uchi / o-uchi / de-ashi style foot attacks.
    OTHER       = auto()  # Catch-all for future emitters; tests use this too.


# ---------------------------------------------------------------------------
# EVENT
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class KuzushiEvent:
    """A single force event applied to uke's CoM at a single tick.

    `vector` is the unit (or near-unit) direction the kuzushi pushes uke's
    CoM; `magnitude` is the force amplitude at emission. Decay is applied
    later by `compromised_state` so the stored magnitude is always the raw
    emission value — calibration can re-tune the decay curve without
    re-emitting events.
    """
    tick_emitted: int
    vector:       Vector2
    magnitude:    float
    source_kind:  KuzushiSource


# ---------------------------------------------------------------------------
# DECAY
# ---------------------------------------------------------------------------
# Half-life of an event in ticks. Spec §2: "a pull two ticks ago is mostly
# live; one from ten ticks ago is mostly faded". With a 5-tick half-life:
#   age=0  → 1.000   (just emitted)
#   age=2  → 0.757   (mostly live)
#   age=5  → 0.500   (half)
#   age=10 → 0.250   (mostly faded — spec wanted "mostly faded", this leaves
#                    a small tail; calibration may want a steeper curve)
#   age=20 → 0.0625  (essentially gone, but buffer cap drops it before then)
#
# Calibration target: HAJ-A.7 will tune against telemetry. Until then the
# 5-tick half-life and 20-tick buffer give a clean mostly-live → mostly-gone
# arc inside one combo's worth of ticks.
DECAY_HALF_LIFE_TICKS: float = 5.0
KUZUSHI_BUFFER_CAPACITY: int = 20


def decay_factor(age_ticks: int) -> float:
    """Multiplicative decay applied to an event's magnitude given its age.

    Negative ages (event from the future) are clamped to 1.0 — defensive
    against caller bugs, not an expected condition.
    """
    if age_ticks <= 0:
        return 1.0
    return 0.5 ** (age_ticks / DECAY_HALF_LIFE_TICKS)


# ---------------------------------------------------------------------------
# COMPROMISED STATE (accumulated decayed kuzushi)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CompromisedState:
    """Sum of all live kuzushi events on uke at a given tick, with decay
    applied. `vector` is the resultant push direction (post-cancellation);
    `magnitude` is its Euclidean length. `total_decayed_magnitude` is the
    *uncancelled* sum — useful when callers care about how much kuzushi
    pressure exists regardless of direction (e.g. "is uke being worked
    over right now?" vs. "is uke pushed in any one direction?").
    """
    vector:                   Vector2
    magnitude:                float
    total_decayed_magnitude:  float

    @classmethod
    def empty(cls) -> "CompromisedState":
        return cls(vector=(0.0, 0.0), magnitude=0.0, total_decayed_magnitude=0.0)


def compromised_state(
    events:       Iterable[KuzushiEvent],
    current_tick: int,
) -> CompromisedState:
    """Collapse a stream of events into a single compromised-state snapshot.

    Each event contributes `vector * magnitude * decay_factor(age)` to the
    resultant. Same-direction events stack additively; opposing events
    partially or fully cancel via vector summation.

    `total_decayed_magnitude` is computed from per-event magnitudes (not
    from the resultant), so two equal-and-opposite pulls yield magnitude=0
    but total_decayed_magnitude=2*decayed_each. That distinction matters
    for the HAJ-A.3 layer: a fighter being yanked in two directions at once
    is still being kuzushi'd, even if the net vector is zero.
    """
    rx = ry = 0.0
    total = 0.0
    for ev in events:
        d = decay_factor(current_tick - ev.tick_emitted)
        contribution = ev.magnitude * d
        vx, vy = ev.vector
        rx += vx * contribution
        ry += vy * contribution
        total += contribution
    mag = (rx * rx + ry * ry) ** 0.5
    return CompromisedState(
        vector=(rx, ry),
        magnitude=mag,
        total_decayed_magnitude=total,
    )


# ---------------------------------------------------------------------------
# BUFFER HELPERS
# ---------------------------------------------------------------------------
def fresh_buffer() -> deque[KuzushiEvent]:
    """Construct an empty per-fighter buffer with the standard cap. Used as
    the default_factory for `Judoka.kuzushi_events`."""
    return deque(maxlen=KUZUSHI_BUFFER_CAPACITY)


def record_kuzushi_event(judoka: "Judoka", event: KuzushiEvent) -> None:
    """Append an event to the judoka's buffer. The deque's `maxlen` handles
    auto-drop of the oldest event when the buffer is full."""
    judoka.kuzushi_events.append(event)


def seed_kuzushi_from_velocity(
    judoka:       "Judoka",
    velocity:     Vector2,
    current_tick: int = 0,
    source_kind:  "KuzushiSource" = None,
) -> Optional[KuzushiEvent]:
    """Test-fixture / scenario helper. Synthesizes the buffer state that
    pre-HAJ-132 tests created by setting `defender.com_velocity` directly.

    `velocity` is in the mat frame (same convention as `com_velocity`). The
    helper appends one event whose magnitude × decay equals the velocity's
    magnitude scaled by KUZUSHI_PER_MPS, with direction matching the
    velocity's. Querying compromised_state at `current_tick` then returns a
    vector aligned with `velocity` and a magnitude that, after the in-throw-
    signature unit conversion, matches the original Couple m/s threshold.

    Production code does NOT call this — PULL emits via pull_kuzushi_event
    in match.py. This is the fixture-only equivalent for unit tests that
    don't simulate a full tick.
    """
    if source_kind is None:
        source_kind = KuzushiSource.PULL
    vx, vy = velocity
    speed = (vx * vx + vy * vy) ** 0.5
    if speed < 1e-9:
        return None
    direction = (vx / speed, vy / speed)
    magnitude = speed * KUZUSHI_PER_MPS
    event = KuzushiEvent(
        tick_emitted=current_tick, vector=direction,
        magnitude=magnitude, source_kind=source_kind,
    )
    judoka.kuzushi_events.append(event)
    return event


# ===========================================================================
# HAJ-131 — PULL → KuzushiEvent emission
# ===========================================================================
# Pull-force formula per grip-as-cause.md §2 / §13.6:
#   force = f(strength, technique, experience, grip_depth, uke_posture_vulnerability)
#
# The continuous physical force still flows through `_compute_net_force_on`
# in match.py (Part 2.4 calibration pipeline). The event-layer magnitude
# computed here is the *symbolic* kuzushi delivered into uke's buffer for
# downstream signature_match (HAJ-132). The two layers are intentionally
# distinct: one drives CoM motion, the other accumulates as compromised
# state. They share inputs but score them differently.
# ---------------------------------------------------------------------------

# Calibration stub. Tuned to give a STANDARD-depth pull from a balanced
# black-belt with neutral fight_iq a magnitude of order ~30, comparable
# in scale to the CoM forces in match.py. Final value tuned in HAJ-A.7.
BASE_PULL_KUZUSHI_FORCE: float = 100.0


# ---------------------------------------------------------------------------
# UNIT CONVERSIONS (HAJ-132 — signature_match reads buffer)
# ---------------------------------------------------------------------------
# Throw templates declare kuzushi-vector thresholds in physical units:
#   - Couple: `min_velocity_magnitude` in m/s
#   - Lever:  `min_displacement_past_recoverable` in meters
# The buffer's accumulated magnitude is in symbolic kuzushi-force units
# (dimensionless multiples of BASE_PULL_KUZUSHI_FORCE). These constants
# convert the per-template thresholds into the buffer's units so the
# throw-signature comparison is meaningful.
#
# Tuning rationale (calibration stubs; HAJ-A.7 will tune):
#   - KUZUSHI_PER_MPS = 100: a 0.4 m/s threshold (e.g. Sumi-gaeshi) becomes
#     40 kuzushi units, achievable from one strong PULL or two moderate
#     pulls composing in the buffer.
#   - KUZUSHI_PER_M = 400: a 0.10 m displacement threshold (Lever) becomes
#     40 kuzushi units, achievable from one strong PULL — Lever throws are
#     supposed to require sustained kuzushi accumulation, so 0.13–0.15 m
#     thresholds map to 52–60 units (~2 well-timed pulls).
KUZUSHI_PER_MPS: float = 100.0
KUZUSHI_PER_M:   float = 400.0


# ---------------------------------------------------------------------------
# DIRECTION LOOKUP — (grip_type, pull_direction) → kuzushi unit vector
# ---------------------------------------------------------------------------
# Most grip types translate the attacker's pull direction directly into
# uke's CoM perturbation: pulling forward through a lapel pulls uke
# forward. CROSS is the standout exception — the cross-grip's geometry
# wraps around uke's centerline, so the lateral component of the pull
# arrives on uke flipped. SLEEVE_LOW and PISTOL inject a small rotational
# bias because cuff-style grips couple to uke's wrist rotation, not to
# the shoulder line; the resulting CoM perturbation has a perpendicular
# component the pure pull direction lacks.
#
# Values are radians of rotation applied to the unit pull vector. Positive
# = counterclockwise in mat frame. Calibration question; HAJ-A.7 may tune.
def _direction_bias_radians(grip_type: "_GripTypeV2") -> float:
    from enums import GripTypeV2
    return {
        GripTypeV2.SLEEVE_HIGH: 0.0,
        GripTypeV2.SLEEVE_LOW:  math.radians(10.0),
        GripTypeV2.LAPEL_LOW:   0.0,
        GripTypeV2.LAPEL_HIGH:  0.0,
        GripTypeV2.COLLAR:      0.0,
        GripTypeV2.BELT:        0.0,
        GripTypeV2.PISTOL:      math.radians(10.0),
        GripTypeV2.CROSS:       0.0,  # handled below — needs sign flip, not rotation
    }.get(grip_type, 0.0)


def kuzushi_direction(
    grip_type: "_GripTypeV2",
    pull_direction: Vector2,
) -> Vector2:
    """Map (grip_type, pull_direction) → unit kuzushi vector applied to uke's CoM.

    Most grip types are identity. SLEEVE_LOW and PISTOL inject ~10° of
    rotational bias (the wrist-rotation component of cuff-style grips).
    CROSS flips the lateral component (the cross-grip's geometry mirrors
    the pull's lateral component across uke's centerline).

    Returns a unit vector. Returns (0, 0) if pull_direction is zero.
    """
    from enums import GripTypeV2
    px, py = pull_direction
    mag = math.hypot(px, py)
    if mag == 0.0:
        return (0.0, 0.0)
    ux, uy = px / mag, py / mag
    if grip_type == GripTypeV2.CROSS:
        # Cross-grip wraps the centerline — the lateral (y in mat frame
        # when facing is +x) component arrives on uke inverted.
        ux, uy = ux, -uy
    rot = _direction_bias_radians(grip_type)
    if rot == 0.0:
        return (ux, uy)
    c, s = math.cos(rot), math.sin(rot)
    return (c * ux - s * uy, s * ux + c * uy)


# ---------------------------------------------------------------------------
# UKE POSTURE VULNERABILITY (the timing axis from §5.1 fight-IQ Timing)
# ---------------------------------------------------------------------------
# Same pull, different uke states, different kuzushi magnitudes. A pull on
# a grounded balanced uke barely moves them. A pull on an uke who's mid-
# step, already moving, or already leaning multiplies into a far larger
# effective kuzushi. This is the mechanical expression of the timing
# skill: catching uke at the right physical moment.
#
# Multipliers stack multiplicatively. Range: roughly [0.7, 2.5].
POSTURE_VULN_BASE:           float = 1.0
POSTURE_VULN_AIRBORNE_FOOT:  float = 1.5   # one foot off the mat
POSTURE_VULN_DRAGGING_FOOT:  float = 1.2   # foot mid-suri-ashi
POSTURE_VULN_MOVING_COM:     float = 1.2   # |com_velocity| above threshold
POSTURE_VULN_TILTED_TRUNK:   float = 1.2   # trunk angle off neutral
POSTURE_VULN_MOVING_THRESHOLD_MPS: float = 0.30  # m/s
POSTURE_VULN_TILT_THRESHOLD_RAD:   float = math.radians(15.0)


def uke_posture_vulnerability(victim: "Judoka") -> float:
    """Multiplier on pull kuzushi magnitude based on uke's current posture.

    Computed from FootContactState (mid-step or dragging foot is wide
    open), CoM velocity (already in motion compounds the pull), and trunk
    angles (already off-balance compounds further). Defensive, calibration-
    stub thresholds; HAJ-A.7 will tune."""
    from body_state import FootContactState
    bs = victim.state.body_state
    m = POSTURE_VULN_BASE

    for foot in (bs.foot_state_left, bs.foot_state_right):
        if foot.contact_state == FootContactState.AIRBORNE:
            m *= POSTURE_VULN_AIRBORNE_FOOT
        elif foot.contact_state == FootContactState.DRAGGING:
            m *= POSTURE_VULN_DRAGGING_FOOT

    vx, vy = bs.com_velocity
    if math.hypot(vx, vy) >= POSTURE_VULN_MOVING_THRESHOLD_MPS:
        m *= POSTURE_VULN_MOVING_COM

    if (abs(bs.trunk_sagittal) >= POSTURE_VULN_TILT_THRESHOLD_RAD
            or abs(bs.trunk_frontal) >= POSTURE_VULN_TILT_THRESHOLD_RAD):
        m *= POSTURE_VULN_TILTED_TRUNK

    return m


# ---------------------------------------------------------------------------
# HAJ-136 — PULL SELF-CANCELLATION
# ---------------------------------------------------------------------------
# Per grip-as-cause.md §13.8: soft-vs-hard pull is emergent from execution
# quality, not a parameter the fighter sets. A novice's pull can mechanically
# cancel itself — they pull while simultaneously stepping toward uke, which
# moves their base under the force vector and reduces net delivered force.
# They feel like they pulled hard; they actually pulled soft.
#
# Geometry: the pull direction is "force applied to uke" (opp → me when
# drawing uke toward attacker). The attacker's CoM moving in the OPPOSITE
# of pull_direction (i.e., me → opp, "stepping into the pull") is the
# self-cancellation case — the lever arm collapses as the attacker's
# base shifts toward the force vector.
#
# Cancellation severity is the speed component along the bad axis,
# clamped to a calibration ceiling. The pull_execution skill axis (stub
# from fight_iq until HAJ-137 ships the proper axis) modulates how much
# of the raw cancellation actually lands on the delivered force: a high-
# skill fighter braces and pulls cleanly; a low-skill fighter eats the
# full penalty.

# Speed at which the cancellation factor saturates (the attacker's base
# is moving the wrong way fast enough that any stronger drift adds no
# additional penalty). 0.6 m/s ≈ a brisk walking step into uke.
PULL_CANCELLATION_SAT_SPEED: float = 0.6

# Floor on the delivered-force multiplier when the pull is fully cancelled
# AND the attacker has zero pull_execution skill. Per the ticket: "fully
# self-cancelled pull = ~0.3× envelope force." Calibration stub.
PULL_CANCELLATION_MIN_FACTOR: float = 0.30


def _pull_execution_factor(attacker: "Judoka") -> float:
    """Pull execution quality in [0, 1].

    HAJ-137 — reads `pull_execution` off the skill vector. Falls back
    to fight_iq/10 on legacy fixtures via skill_vector.axis().
    """
    from skill_vector import axis
    return max(0.0, min(1.0, axis(attacker, "pull_execution")))


def pull_self_cancellation_factor(
    attacker: "Judoka", pull_direction: Vector2,
) -> float:
    """Multiplier on delivered pull force given the attacker's CoM motion.

    Returns 1.0 when the pull is clean (CoM is planted or moving with the
    pull, e.g. a step backward that adds to the lever arm). Returns
    [PULL_CANCELLATION_MIN_FACTOR, 1.0] otherwise, with low-skill fighters
    eating proportionally more of the penalty.

    Math:
      cancel_speed = max(0, -dot(com_velocity, pull_direction_unit))
                     # speed in m/s along the wrong axis
      raw_cancel  = clamp01(cancel_speed / SAT_SPEED)
                     # 0 = clean, 1 = fully canceled at saturation
      effective   = raw_cancel * (1 - pull_execution)
                     # high skill nullifies; low skill exposes full
      factor      = 1 - effective * (1 - MIN_FACTOR)
                     # in [MIN_FACTOR, 1.0]
    """
    dx, dy = pull_direction
    norm = math.hypot(dx, dy)
    if norm < 1e-9:
        return 1.0
    ux, uy = dx / norm, dy / norm
    vx, vy = attacker.state.body_state.com_velocity
    # Negative dot = attacker moving against the pull (the cancel case).
    cancel_speed = max(0.0, -(vx * ux + vy * uy))
    if cancel_speed <= 0.0:
        return 1.0
    raw_cancel = min(1.0, cancel_speed / PULL_CANCELLATION_SAT_SPEED)
    effective = raw_cancel * (1.0 - _pull_execution_factor(attacker))
    return 1.0 - effective * (1.0 - PULL_CANCELLATION_MIN_FACTOR)


# ---------------------------------------------------------------------------
# EXPERIENCE FACTOR (placeholder until HAJ-C.3 ships pull_execution axis)
# ---------------------------------------------------------------------------
def _belt_experience_factor(attacker: "Judoka") -> float:
    """Map BeltRank to an experience multiplier in [0.4, 1.0]. WHITE = 0.4,
    BLACK_5 = 1.0, linear in between.

    TODO: HAJ-C.3 — replace with a dedicated `experience` skill axis that
    can vary independently of belt rank (an under-graded judoka with deep
    randori hours; an over-graded judoka skipped through promotions).
    """
    from enums import BeltRank
    rank_order = list(BeltRank)
    idx = rank_order.index(attacker.identity.belt_rank)
    span = max(1, len(rank_order) - 1)
    return 0.4 + 0.6 * (idx / span)


# ---------------------------------------------------------------------------
# PULL KUZUSHI MAGNITUDE
# ---------------------------------------------------------------------------
def pull_kuzushi_magnitude(
    attacker: "Judoka",
    edge: "GripEdge",
    victim: "Judoka",
) -> float:
    """Return event magnitude for one PULL action through `edge`.

    Implements the §2 / §13.6 formula:
        force = f(strength, technique, experience, grip_depth, uke_posture_vulnerability)

    All five terms are normalized multiplicatively against BASE_PULL_KUZUSHI_FORCE.
    The result is the symbolic event magnitude, distinct from the
    physical CoM force the same PULL drives through the grip envelope.
    """
    from force_envelope import grip_strength
    from skill_vector import axis
    strength    = grip_strength(attacker)
    # HAJ-137 — technique now reads pull_execution off the skill vector.
    technique   = max(0.0, min(1.0, axis(attacker, "pull_execution")))
    experience  = _belt_experience_factor(attacker)
    depth       = edge.depth_level.modifier()
    posture_v   = uke_posture_vulnerability(victim)
    return BASE_PULL_KUZUSHI_FORCE * strength * technique * experience * depth * posture_v


# ---------------------------------------------------------------------------
# PULL → EVENT (the integration entry point used from match.py)
# ---------------------------------------------------------------------------
def pull_kuzushi_event(
    attacker:        "Judoka",
    edge:            "GripEdge",
    victim:          "Judoka",
    pull_direction:  Vector2,
    current_tick:    int,
) -> Optional[KuzushiEvent]:
    """Build the KuzushiEvent emitted by one PULL action this tick.

    HAJ-136 — the emitted magnitude reflects *actual delivered force*,
    not requested. A pull executed while the attacker's CoM is moving
    into uke (the novice "felt-hard, actually-soft" pattern) loses
    magnitude per pull_self_cancellation_factor. High-skill fighters
    brace and pull clean; low-skill fighters eat the full penalty.

    Returns None when the event would be a no-op (zero magnitude or
    zero direction) — callers can append unconditionally and skip the
    None case, or guard before calling. Either pattern works.
    """
    mag = pull_kuzushi_magnitude(attacker, edge, victim)
    if mag <= 0.0:
        return None
    cancel_factor = pull_self_cancellation_factor(attacker, pull_direction)
    mag *= cancel_factor
    if mag <= 0.0:
        return None
    direction = kuzushi_direction(edge.grip_type_v2, pull_direction)
    if direction == (0.0, 0.0):
        return None
    return KuzushiEvent(
        tick_emitted=current_tick,
        vector=direction,
        magnitude=mag,
        source_kind=KuzushiSource.PULL,
    )


# ===========================================================================
# HAJ-133 — FOOT_ATTACK → KuzushiEvent emission
# ===========================================================================
# Per grip-as-cause.md §3.5, foot attacks are a kuzushi-generating action
# family parallel to PULL. They don't drive force through a grip — they
# disrupt uke's base directly with the attacker's leg. The event-layer
# magnitude is the symbolic kuzushi delivered into uke's buffer; the
# physics CoM force is a separate (smaller, transient) effect that is
# v0.2 work — for v0.1 the action is purely a kuzushi emitter (parallel
# to how PULL emits alongside its own physics force, but PULL has the
# physics force from the grip envelope while foot attacks don't yet
# have a corresponding force-envelope mechanic).
#
# Magnitude scale is intentionally lower than PULL: a probing sweep is
# a setup, not a drive. Real-judo intuition: three-to-four foot setups
# compose to a kuzushi state similar to one strong pull.
BASE_FOOT_ATTACK_KUZUSHI_FORCE: float = 35.0


def foot_attack_kuzushi_direction(
    action_kind:   "_ActionKind",
    attack_vector: Vector2,
    attacker_facing: Vector2 = (1.0, 0.0),
) -> Vector2:
    """Map (foot-attack kind, attack vector, attacker facing) → unit kuzushi
    vector applied to uke's CoM.

    Per HAJ-133 spec:
      * FOOT_SWEEP_SETUP — lateral-down toward swept side. We project the
        attack vector and apply a small downward-lateral bias (the swept
        leg pulls uke's foot out from under, dropping that side).
      * LEG_ATTACK_SETUP — rear-corner of victim. Ko-uchi / o-uchi reap
        the leg backward, so kuzushi vector points along the rearward
        direction (opposite attacker facing) blended with the attack
        vector for the lateral component.
      * DISRUPTIVE_STEP — opposite of step direction. Stepping past uke
        forces them to yield in the opposite direction.

    Returns a unit vector. Returns (0, 0) when attack_vector is zero.
    """
    from actions import ActionKind
    ax, ay = attack_vector
    mag = math.hypot(ax, ay)
    if mag == 0.0:
        return (0.0, 0.0)
    ux, uy = ax / mag, ay / mag

    if action_kind == ActionKind.FOOT_SWEEP_SETUP:
        # Sweep yanks uke's base laterally — kuzushi vector tracks the
        # sweep direction directly. The "down" component lives in the
        # decay model (an event with this lateral vector compounds with
        # gravity to topple uke).
        return (ux, uy)

    if action_kind == ActionKind.LEG_ATTACK_SETUP:
        # Reap-style leg attacks drive uke rearward (relative to attacker)
        # plus whichever lateral side the attacking foot is on.
        fx, fy = attacker_facing
        ffmag = math.hypot(fx, fy) or 1.0
        rear_x, rear_y = -fx / ffmag, -fy / ffmag
        # Blend rear (60%) + lateral attack vector (40%).
        bx, by = rear_x * 0.60 + ux * 0.40, rear_y * 0.60 + uy * 0.40
        bm = math.hypot(bx, by) or 1.0
        return (bx / bm, by / bm)

    if action_kind == ActionKind.DISRUPTIVE_STEP:
        # Step past uke → uke's CoM yields opposite the step.
        return (-ux, -uy)

    # Unknown kind — fall through to no-op so callers stay safe.
    return (0.0, 0.0)


def foot_attack_kuzushi_magnitude(
    attacker:    "Judoka",
    action_kind: "_ActionKind",
    victim:      "Judoka",
    intensity:   float = 1.0,
) -> float:
    """Return event magnitude for one foot-attack action this tick.

    Mirrors `pull_kuzushi_magnitude` but without a grip-depth term (foot
    attacks don't go through a grip).

    HAJ-137 — technique now reads the per-kind offensive-footwork axis
    off the skill vector: FOOT_SWEEP_SETUP → foot_sweeps,
    LEG_ATTACK_SETUP → leg_attacks, DISRUPTIVE_STEP → disruptive_stepping.
    A fighter with a high foot_sweeps axis but low leg_attacks now
    delivers visibly different magnitudes between the two action kinds.

    `intensity` lets the caller scale the magnitude (e.g. a heavy reap
    vs. a light probe).
    """
    from actions import ActionKind
    from skill_vector import axis
    axis_for_kind = {
        ActionKind.FOOT_SWEEP_SETUP: "foot_sweeps",
        ActionKind.LEG_ATTACK_SETUP: "leg_attacks",
        ActionKind.DISRUPTIVE_STEP:  "disruptive_stepping",
    }.get(action_kind)
    if axis_for_kind is None:
        return 0.0
    technique  = max(0.0, min(1.0, axis(attacker, axis_for_kind)))
    experience = _belt_experience_factor(attacker)
    posture_v  = uke_posture_vulnerability(victim)
    # Per-kind weight: leg attacks land harder than probing sweeps;
    # disruptive steps are the lightest setup.
    kind_weight = {
        ActionKind.FOOT_SWEEP_SETUP: 0.7,
        ActionKind.LEG_ATTACK_SETUP: 1.0,
        ActionKind.DISRUPTIVE_STEP:  0.5,
    }.get(action_kind, 0.0)
    return (BASE_FOOT_ATTACK_KUZUSHI_FORCE
            * technique * experience * posture_v
            * kind_weight * max(0.0, intensity))


def foot_attack_kuzushi_event(
    attacker:        "Judoka",
    victim:          "Judoka",
    action_kind:     "_ActionKind",
    attack_vector:   Vector2,
    current_tick:    int,
    intensity:       float = 1.0,
    attacker_facing: Optional[Vector2] = None,
) -> Optional[KuzushiEvent]:
    """Build the KuzushiEvent emitted by one foot-attack action.

    Returns None when the event would be a no-op (zero magnitude or
    zero direction).
    """
    mag = foot_attack_kuzushi_magnitude(
        attacker, action_kind, victim, intensity=intensity,
    )
    if mag <= 0.0:
        return None
    if attacker_facing is None:
        attacker_facing = attacker.state.body_state.facing
    direction = foot_attack_kuzushi_direction(
        action_kind, attack_vector, attacker_facing=attacker_facing,
    )
    if direction == (0.0, 0.0):
        return None
    return KuzushiEvent(
        tick_emitted=current_tick,
        vector=direction,
        magnitude=mag,
        source_kind=KuzushiSource.FOOT_ATTACK,
    )
