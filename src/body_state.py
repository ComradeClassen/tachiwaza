# body_state.py
# Physics-substrate Part 1: BodyState and supporting geometry.
#
# Spec: design-notes/physics-substrate.md, Part 1 (sections 1.1–1.8).
#
# What lives here:
#   - ContactState enum (per body part, incl. REACHING from Part 2.7)
#   - FootContactState enum (per foot: PLANTED / AIRBORNE / DRAGGING)
#   - FootState dataclass
#   - BodyState dataclass (CoM, trunk lean, feet, facing)
#   - base_polygon(body_state) — derived BoS geometry (Part 1.4)
#   - recoverable_envelope(...) — the envelope that makes kuzushi a vector/region
#     test rather than a scalar threshold (Part 1.5)
#   - is_kuzushi(...) — the predicate from Part 1.5
#   - derive_posture(...) — computes the discrete Posture enum from continuous
#     trunk angles so existing throw prerequisite code keeps working while the
#     substrate operates on angles.
#   - place_judoka(...) — sets mat-frame position and facing at match start.
#
# Parts 2–6 (grips, force envelopes, tick update, throw signatures) are not
# implemented here. Points where those hook in are marked `# TODO (Part N)`.

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from math import cos, sin, pi, hypot, atan2
from typing import Optional, TYPE_CHECKING

from enums import Posture

if TYPE_CHECKING:
    from judoka import Judoka


# ---------------------------------------------------------------------------
# CONTACT STATES
# ---------------------------------------------------------------------------
class ContactState(Enum):
    """Per body part contact state (Part 1.6, extended by Part 2.7).

    Stored on BodyPartState. Enables throw signatures to ask questions like
    'is tori's right hip CONTACTING_UKE_NONGRIP?' without inferring it from
    other fields.
    """
    FREE                  = auto()  # No contact with anything.
    GRIPPING_UKE          = auto()  # Hand currently holds a grip on uke.
    SUPPORTING_GROUND     = auto()  # Foot (or knee/hand if fallen) bears weight.
    CONTACTING_UKE_NONGRIP = auto()  # In contact with uke, not gripping (hip, thigh, shin, shoulder).
    STRUCK_BY_UKE         = auto()  # Just received impact; typically during failed throw or counter.
    REACHING              = auto()  # Hand extended toward uke's gi, committed but not yet connected.


class FootContactState(Enum):
    """Per-foot contact state (Part 1.4)."""
    PLANTED  = auto()  # Bearing weight.
    AIRBORNE = auto()  # No contact — mid-step, mid-throw, mid-reap.
    DRAGGING = auto()  # Partial contact during suri-ashi transitions.


# ---------------------------------------------------------------------------
# FOOT STATE
# ---------------------------------------------------------------------------
@dataclass
class FootState:
    """State of one foot at one tick (Part 1.4)."""
    position: tuple[float, float] = (0.0, 0.0)           # mat frame, meters
    contact_state: FootContactState = FootContactState.PLANTED
    weight_fraction: float = 0.5                          # [0.0, 1.0]; two feet sum ≤ 1.0


# ---------------------------------------------------------------------------
# BODY STATE
# ---------------------------------------------------------------------------
@dataclass
class BodyState:
    """A judoka's physical state at one tick (Part 1).

    All positions and velocities are in the mat frame. Trunk angles are in
    radians, stored per Part 1.3 (sagittal + frontal, not a single scalar).
    The recoverable envelope and kuzushi predicate are computed on demand
    from this state plus attributes on Capability/State (leg strength,
    fatigue, composure).
    """
    # Center of mass (Part 1.2)
    com_position: tuple[float, float] = (0.0, 0.0)   # mat frame, meters
    com_velocity: tuple[float, float] = (0.0, 0.0)   # m/s
    com_height: float = 1.0                          # meters (navel above mat)

    # Trunk orientation (Part 1.3). Radians.
    # Sagittal: positive = forward lean; range −30° to +60° (−0.52, +1.05).
    # Frontal:  positive = rightward lean; range −45° to +45° (−0.79, +0.79).
    trunk_sagittal: float = 0.0
    trunk_frontal:  float = 0.0

    # Base of support (Part 1.4)
    foot_state_left:  FootState = field(default_factory=FootState)
    foot_state_right: FootState = field(default_factory=FootState)

    # Facing direction in the mat frame — a unit vector pointing +X of the
    # body frame. Needed for mat↔body frame conversion (Part 2+ will lean
    # on this). Not in Part 1's field list but required to place the BoS
    # rectangle and to compute body-frame kuzushi vectors.
    facing: tuple[float, float] = (1.0, 0.0)


# ---------------------------------------------------------------------------
# CONSTANTS — foot and envelope geometry
# ---------------------------------------------------------------------------
FOOT_LENGTH_M = 0.27   # adult foot length
FOOT_WIDTH_M  = 0.10   # adult foot width

# Recoverable envelope base reach (meters) for a nominal leg_strength=1.0,
# fatigue=0, composure=1.0, zero velocity. Calibration target; not a
# commitment of the spec.
# TODO (Part 6): calibrate against Phase 3 numbers.
ENVELOPE_BASE_REACH_M = 0.35

# How sharply com_velocity collapses the envelope in the opposite-to-motion
# direction. Per Part 1.5: at 1.5 m/s forward, backward recovery distance
# should approach 0. That gives narrowing ≈ 1.0 at v=1.5 → coeff ≈ 0.67.
VELOCITY_NARROWING_PER_MPS = 0.67

# Envelope polygon sample count. 16 gives smooth enough coverage for the
# point-in-polygon kuzushi test without making fatigue/composure changes
# visibly jagged.
ENVELOPE_SAMPLES = 16


# ---------------------------------------------------------------------------
# GEOMETRY HELPERS
# ---------------------------------------------------------------------------
def _unit(v: tuple[float, float]) -> tuple[float, float]:
    mag = hypot(v[0], v[1])
    if mag < 1e-9:
        return (0.0, 0.0)
    return (v[0] / mag, v[1] / mag)


def _perp(v: tuple[float, float]) -> tuple[float, float]:
    return (-v[1], v[0])


def _convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Andrew's monotone chain. Returns hull in CCW order; duplicates removed."""
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _point_in_polygon(p: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
    """Ray-casting test. Works for any simple polygon (convex or not)."""
    if len(polygon) < 3:
        return False
    x, y = p
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if ((y1 > y) != (y2 > y)):
            x_cross = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < x_cross:
                inside = not inside
    return inside


def _polygon_centroid(polygon: list[tuple[float, float]]) -> tuple[float, float]:
    if not polygon:
        return (0.0, 0.0)
    cx = sum(p[0] for p in polygon) / len(polygon)
    cy = sum(p[1] for p in polygon) / len(polygon)
    return (cx, cy)


# ---------------------------------------------------------------------------
# BASE POLYGON (Part 1.4, derived)
# ---------------------------------------------------------------------------
def base_polygon(body_state: BodyState) -> list[tuple[float, float]]:
    """Convex hull of planted/dragging foot outlines (Part 1.4).

    Double-support (both planted) → a rectangle spanning the two feet.
    Single-support (one airborne) → the footprint of the remaining foot.
    No-contact (both airborne) → empty polygon; balance impossible.
    """
    forward = _unit(body_state.facing) or (1.0, 0.0)
    side = _perp(forward)
    hl, hw = FOOT_LENGTH_M / 2, FOOT_WIDTH_M / 2

    corners: list[tuple[float, float]] = []
    for foot in (body_state.foot_state_left, body_state.foot_state_right):
        if foot.contact_state == FootContactState.AIRBORNE:
            continue
        fx, fy = foot.position
        for du, dv in ((+hl, +hw), (+hl, -hw), (-hl, +hw), (-hl, -hw)):
            corners.append((
                fx + du * forward[0] + dv * side[0],
                fy + du * forward[1] + dv * side[1],
            ))
    if not corners:
        return []
    return _convex_hull(corners)


# ---------------------------------------------------------------------------
# RECOVERABLE ENVELOPE (Part 1.5)
# ---------------------------------------------------------------------------
def recoverable_envelope(
    body_state: BodyState,
    leg_strength: float,
    fatigue: float,
    composure: float,
) -> list[tuple[float, float]]:
    """Polygon around the BoS that the judoka can still step back into.

    Sampled at ENVELOPE_SAMPLES directions around the BoS centroid. The reach
    in each direction scales with leg_strength × (1 − fatigue) × composure,
    and is narrowed in the direction opposite to com_velocity (a judoka
    moving forward cannot easily recover to the rear).

    Returns a polygon in mat-frame coordinates. Empty list if no feet bear
    weight (kuzushi is unavoidable in that tick).
    """
    bp = base_polygon(body_state)
    if not bp:
        return []

    centroid = _polygon_centroid(bp)
    speed = hypot(*body_state.com_velocity)
    vel_dir = _unit(body_state.com_velocity) if speed > 1e-9 else (0.0, 0.0)

    leg = max(0.0, leg_strength)
    fat = max(0.0, min(1.0, fatigue))
    com = max(0.0, min(1.0, composure))
    base_reach = ENVELOPE_BASE_REACH_M * leg * (1.0 - fat) * com

    envelope: list[tuple[float, float]] = []
    for k in range(ENVELOPE_SAMPLES):
        theta = 2 * pi * k / ENVELOPE_SAMPLES
        dir_x, dir_y = cos(theta), sin(theta)

        # Project the BoS hull outward in this direction: find the max
        # signed projection of any hull vertex onto this direction.
        base_offset = max(
            (p[0] - centroid[0]) * dir_x + (p[1] - centroid[1]) * dir_y
            for p in bp
        )

        # Narrow the envelope opposite to velocity. align = 1 aligned with
        # motion; align = −1 directly opposing motion. Only the opposite-
        # to-motion side is narrowed.
        align = dir_x * vel_dir[0] + dir_y * vel_dir[1]
        velocity_factor = max(0.0, 1.0 - VELOCITY_NARROWING_PER_MPS * speed * max(0.0, -align))
        reach = base_reach * velocity_factor

        total = base_offset + reach
        envelope.append((centroid[0] + dir_x * total, centroid[1] + dir_y * total))
    return envelope


def is_kuzushi(
    body_state: BodyState,
    leg_strength: float,
    fatigue: float,
    composure: float,
) -> bool:
    """Part 1.5: `com_projection outside recoverable_envelope`.

    True when the judoka's CoM has exited the region from which they can
    still recover balance.
    """
    envelope = recoverable_envelope(body_state, leg_strength, fatigue, composure)
    if not envelope:
        return True
    return not _point_in_polygon(body_state.com_position, envelope)


# ---------------------------------------------------------------------------
# POSTURE DERIVATION
# The continuous trunk angles are authoritative. The discrete Posture enum
# from enums.py is now a derived view kept alive while Parts 2–6 still
# consult `state.posture` in throw prerequisites.
# ---------------------------------------------------------------------------
UPRIGHT_LIMIT_RAD       = 15.0 * pi / 180.0   # ≈0.26
SLIGHTLY_BENT_LIMIT_RAD = 35.0 * pi / 180.0   # ≈0.61


def derive_posture(trunk_sagittal: float, trunk_frontal: float) -> Posture:
    """Collapse continuous trunk angles to the discrete Posture enum."""
    lean = max(abs(trunk_sagittal), abs(trunk_frontal))
    if lean < UPRIGHT_LIMIT_RAD:
        return Posture.UPRIGHT
    if lean < SLIGHTLY_BENT_LIMIT_RAD:
        return Posture.SLIGHTLY_BENT
    return Posture.BROKEN


# ---------------------------------------------------------------------------
# INITIAL STATE (Part 1.8)
# ---------------------------------------------------------------------------
SHOULDER_WIDTH_M = 0.35   # foot-to-foot separation in shizentai


def fresh_body_state(
    com_position: tuple[float, float] = (0.0, 0.0),
    facing: tuple[float, float] = (1.0, 0.0),
    com_height: float = 1.0,
) -> BodyState:
    """Part 1.8: both judoka spawn in shizentai.

    Standing natural posture, zero velocity, both feet planted shoulder-width
    apart with equal weight, all trunk angles 0.
    """
    forward = _unit(facing) or (1.0, 0.0)
    side = _perp(forward)
    half_w = SHOULDER_WIDTH_M / 2

    left_pos = (
        com_position[0] - half_w * side[0],
        com_position[1] - half_w * side[1],
    )
    right_pos = (
        com_position[0] + half_w * side[0],
        com_position[1] + half_w * side[1],
    )

    return BodyState(
        com_position=com_position,
        com_velocity=(0.0, 0.0),
        com_height=com_height,
        trunk_sagittal=0.0,
        trunk_frontal=0.0,
        foot_state_left=FootState(
            position=left_pos,
            contact_state=FootContactState.PLANTED,
            weight_fraction=0.5,
        ),
        foot_state_right=FootState(
            position=right_pos,
            contact_state=FootContactState.PLANTED,
            weight_fraction=0.5,
        ),
        facing=forward,
    )


def place_judoka(judoka: "Judoka", com_position: tuple[float, float], facing: tuple[float, float]) -> None:
    """Re-seat a judoka's BodyState at a specific mat-frame position and facing.

    Used at Hajime to set up the 1.0 m separation between tori and uke.
    Preserves com_height from the existing BodyState so per-judoka height
    (set from identity.hip_height_cm) is kept.
    """
    current = judoka.state.body_state
    judoka.state.body_state = fresh_body_state(
        com_position=com_position,
        facing=facing,
        com_height=current.com_height,
    )
