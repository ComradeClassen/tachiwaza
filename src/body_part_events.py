# body_part_events.py
# HAJ-145 — BodyPartEvent emission layer.
#
# A BodyPartEvent is the substrate for the future prose layer (HAJ-147 onward):
# every committing action, kuzushi attempt, counter, and grip change decomposes
# into a sequence of these structured events. No prose is generated here — the
# events are structured data only. HAJ-147 maps engine-event-verbs to prose
# word-verbs; HAJ-146 adds grip `intent` and recomputes head state as output.
#
# Schema (per ticket): (actor, part, verb, target?, modifiers[]). The wire
# format adds `tick` (when the event was emitted), `side` (LEFT/RIGHT/NONE so
# right-hand and left-hand events are distinguishable without a stringly-typed
# part), `direction` (a 2D unit vector in the mat frame, for kuzushi-bearing
# events whose contradiction the §13.8 self-cancel detector reads downstream),
# and `source` (the parent engine event_type — GRIP_DEEPEN, PULL, COMMIT,
# COUNTER_COMMIT, etc.) so altitude readers can group BPEs by source.

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from judoka import Judoka
    from grip_graph import GripEdge


# ---------------------------------------------------------------------------
# PART (high-level)
# These are the nine narrative parts the prose layer will speak in. They are
# DELIBERATELY coarser than the 24-part biomechanical BodyPart enum: a prose
# reader at mat-side hears "right hand grips the lapel", not "right_forearm
# at 0.3 fatigue". The fine-grained body-state model still drives mechanics;
# this is the rendering vocabulary.
# ---------------------------------------------------------------------------
class BodyPartHigh(Enum):
    HANDS     = auto()
    ELBOWS    = auto()
    SHOULDERS = auto()
    HEAD      = auto()
    POSTURE   = auto()
    HIPS      = auto()
    KNEES     = auto()
    FEET      = auto()
    BASE      = auto()


# ---------------------------------------------------------------------------
# SIDE
# Most parts come in pairs; some events are bilateral or sideless (POSTURE,
# BASE, HEAD). NONE means the verb applies to the whole part-class.
# ---------------------------------------------------------------------------
class Side(Enum):
    LEFT  = auto()
    RIGHT = auto()
    NONE  = auto()


# ---------------------------------------------------------------------------
# VERB
# The initial engine-event-verb vocabulary from the ticket. These are
# structural verbs (what the simulation emits), not prose word-verbs. HAJ-147
# maps these to per-skill prose registers.
# ---------------------------------------------------------------------------
class BodyPartVerb(Enum):
    # Hands
    GRIP    = auto()
    RELEASE = auto()
    BREAK   = auto()
    PULL    = auto()
    PUSH    = auto()
    SNAP    = auto()
    POST    = auto()
    PIN     = auto()
    REACH   = auto()    # hand-only — committing-to-grip motion before contact

    # Elbows
    TIGHT   = auto()
    FLARE   = auto()
    LIFT    = auto()    # also feet (Sasae propping lift) and shoulders (seoi fulcrum)

    # Hips
    LOAD     = auto()
    TURN_IN  = auto()
    PIVOT    = auto()
    SQUARE   = auto()
    CHECK    = auto()
    COLLAPSE = auto()

    # Knees
    BEND        = auto()
    STRAIGHTEN  = auto()
    CUT_INSIDE  = auto()
    BLOCK       = auto()    # also feet (block-leg)

    # Feet
    STEP   = auto()
    REAP   = auto()
    PROP   = auto()
    HOOK   = auto()

    # Posture (verbs are state-shapes, mapped to prose like "broken forward")
    UPRIGHT          = auto()
    BROKEN_FORWARD   = auto()
    BROKEN_BACK      = auto()
    BROKEN_SIDE      = auto()
    BENT             = auto()
    SQUARED          = auto()

    # Head — HAJ-146 will recompute most of these as outputs of opposing grips
    # with intent=steer; here we expose the verbs so the substrate is ready.
    UP      = auto()
    DOWN    = auto()
    DRIVING = auto()
    TURNED  = auto()


# ---------------------------------------------------------------------------
# TARGET (grip-bearing events only)
# A grasper hand's target on uke's gi or body. The fine-grained GripTarget
# enum has 20+ values (split by side, by ne-waza body part); this is the
# narrative-layer collapse: a reader hears "left lapel" or "right sleeve",
# not "left_lapel" vs "left_back_gi".
# ---------------------------------------------------------------------------
class BodyPartTarget(Enum):
    LAPEL       = auto()
    SLEEVE      = auto()
    COLLAR      = auto()
    BELT        = auto()
    CROSS_GRIP  = auto()
    BACK_OF_GI  = auto()
    WRIST       = auto()


# ---------------------------------------------------------------------------
# MODIFIERS
# Six axes (per ticket). Each axis is a discrete level-enum; None means the
# modifier wasn't computed for this event (some events don't have a coherent
# value on every axis — a posture event has no Tightness, a release has no
# Speed). HAJ-147 reads these for prose-register selection.
#
# Modifier values are derived from the actor's SkillVector at emission time:
# the same engine action looks crisp from an elite and sloppy from a novice
# because the modifier resolves against different per-axis values. The driving
# axis per modifier is documented on each enum.
# ---------------------------------------------------------------------------
class Crispness(Enum):
    """Driven by the action's primary execution axis (lapel_grip, sleeve_grip,
    stripping, defending, pull_execution, foot_sweeps, leg_attacks)."""
    SLOPPY  = auto()
    AVERAGE = auto()
    CRISP   = auto()


class Tightness(Enum):
    """Driven by the same axis as crispness — high-skill grippers keep
    elbows tight to the body, novices flare them."""
    FLARING = auto()
    NEUTRAL = auto()
    TIGHT   = auto()


class Timing(Enum):
    """Driven by `sequencing_precision`. EARLY/LATE are caller-provided when
    the event is part of a sequence (e.g. pull arrives before kuzushi has
    stacked, foot attack arrives after uke recovers); ON is the default."""
    EARLY = auto()
    ON    = auto()
    LATE  = auto()


class Commitment(Enum):
    """Set explicitly at emission time. TENTATIVE for low-magnitude / setup
    actions; COMMITTING for full-effort commits; OVERCOMMITTED for desperation
    or self-cancellation states."""
    TENTATIVE       = auto()
    COMMITTING      = auto()
    OVERCOMMITTED   = auto()


class Speed(Enum):
    """Driven by the action's execution axis."""
    SLOW      = auto()
    NORMAL    = auto()
    EXPLOSIVE = auto()


class Connection(Enum):
    """Driven by `base_recovery` and posture: a fighter with weak base /
    bent posture is DISCONNECTED; a rooted base produces ROOTED."""
    DISCONNECTED = auto()
    PARTIAL      = auto()
    ROOTED       = auto()


@dataclass(frozen=True)
class Modifiers:
    crispness:  Optional[Crispness]  = None
    tightness:  Optional[Tightness]  = None
    timing:     Optional[Timing]     = None
    commitment: Optional[Commitment] = None
    speed:      Optional[Speed]      = None
    connection: Optional[Connection] = None

    def to_dict(self) -> dict[str, str]:
        d: dict[str, str] = {}
        for axis_name, val in (
            ("crispness",  self.crispness),
            ("tightness",  self.tightness),
            ("timing",     self.timing),
            ("commitment", self.commitment),
            ("speed",      self.speed),
            ("connection", self.connection),
        ):
            if val is not None:
                d[axis_name] = val.name
        return d


# ---------------------------------------------------------------------------
# BODY PART EVENT
# The wire-format. `actor` is a fighter name string (matches Event.data
# convention everywhere else in the engine). Tests should read these from
# Match.body_part_events or from Event.data["body_part_events"].
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BodyPartEvent:
    tick:       int
    actor:      str
    part:       BodyPartHigh
    side:       Side
    verb:       BodyPartVerb
    target:     Optional[BodyPartTarget] = None
    direction:  Optional[tuple[float, float]] = None
    modifiers:  Modifiers = field(default_factory=Modifiers)
    source:     str = ""    # parent engine event_type, e.g. "PULL", "GRIP_DEEPEN", "COMMIT"

    def to_dict(self) -> dict:
        """Lossless dict form for embedding inside Event.data — the viewer's
        ticker reads structured records out of Event.data, never the raw
        BodyPartEvent object (which is frozen / non-trivial to serialize)."""
        return {
            "tick":      self.tick,
            "actor":     self.actor,
            "part":      self.part.name,
            "side":      self.side.name,
            "verb":      self.verb.name,
            "target":    self.target.name if self.target else None,
            "direction": list(self.direction) if self.direction else None,
            "modifiers": self.modifiers.to_dict(),
            "source":    self.source,
        }


# ---------------------------------------------------------------------------
# AXIS-LEVEL DERIVATION
# Map a SkillVector axis value [0, 1] onto a discrete level. Thresholds
# match the standard "novice / journeyman / elite" split: below 0.40 reads
# as low, 0.40–0.70 as average, above 0.70 as high. v0.1 calibration —
# tuneable when HAJ-147's prose layer surfaces them.
# ---------------------------------------------------------------------------
_LOW_THRESH:  float = 0.40
_HIGH_THRESH: float = 0.70


def _level_low_mid_high(value: float) -> int:
    """0 → low, 1 → mid, 2 → high."""
    if value < _LOW_THRESH:
        return 0
    if value < _HIGH_THRESH:
        return 1
    return 2


def crispness_from_axis(value: float) -> Crispness:
    return [Crispness.SLOPPY, Crispness.AVERAGE, Crispness.CRISP][
        _level_low_mid_high(value)
    ]


def tightness_from_axis(value: float) -> Tightness:
    return [Tightness.FLARING, Tightness.NEUTRAL, Tightness.TIGHT][
        _level_low_mid_high(value)
    ]


def speed_from_axis(value: float) -> Speed:
    return [Speed.SLOW, Speed.NORMAL, Speed.EXPLOSIVE][
        _level_low_mid_high(value)
    ]


def timing_from_precision(value: float, *, hint: Optional[str] = None) -> Timing:
    """Default mapping is precision-axis driven. `hint` overrides — emitters
    that detect a sequence-level early/late condition (pull arrives before
    kuzushi has stacked; foot attack arrives after uke has recovered) pass
    "early" or "late" to force the level. The default reads sequencing
    precision: low precision drifts the timing off; high precision lands ON.
    """
    if hint == "early":
        return Timing.EARLY
    if hint == "late":
        return Timing.LATE
    if value < _LOW_THRESH:
        # Low precision tends to read EARLY (rushed) or LATE (mistimed);
        # without a directional signal we collapse to LATE as the more common
        # novice failure mode in the canon. HAJ-147 will refine this.
        return Timing.LATE
    return Timing.ON


def connection_from_base(value: float) -> Connection:
    return [Connection.DISCONNECTED, Connection.PARTIAL, Connection.ROOTED][
        _level_low_mid_high(value)
    ]


# ---------------------------------------------------------------------------
# MODIFIER COMPUTE
# Build a Modifiers record for an event, given the actor and the SkillVector
# axis that drives the action's execution. Callers pass the axis name; this
# function reads the actor's vector once and resolves the six axes.
# ---------------------------------------------------------------------------
def compute_modifiers(
    actor: "Judoka",
    *,
    execution_axis: str,
    commitment: Commitment = Commitment.COMMITTING,
    timing_hint: Optional[str] = None,
) -> Modifiers:
    """Resolve the six-axis modifier bundle for one BodyPartEvent.

    `execution_axis` is the SkillVector field name driving crispness /
    tightness / speed (e.g. "pull_execution", "lapel_grip", "foot_sweeps").
    Connection reads `base_recovery`. Timing reads `sequencing_precision`
    unless overridden by `timing_hint` ("early" / "late").
    """
    sv = getattr(actor, "skill_vector", None)
    if sv is None:
        # Defensive — pre-HAJ-137 fighters had no skill_vector. Return all-Nones
        # so callers that lift events into the log don't crash; the prose
        # layer treats missing modifiers as "neutral".
        return Modifiers(commitment=commitment)

    exec_value = float(getattr(sv, execution_axis, 0.5))
    base_value = float(getattr(sv, "base_recovery", 0.5))
    seq_value  = float(getattr(sv, "sequencing_precision", 0.5))

    return Modifiers(
        crispness=crispness_from_axis(exec_value),
        tightness=tightness_from_axis(exec_value),
        timing=timing_from_precision(seq_value, hint=timing_hint),
        commitment=commitment,
        speed=speed_from_axis(exec_value),
        connection=connection_from_base(base_value),
    )


# ---------------------------------------------------------------------------
# HAND ↔ SIDE / FINE-GRAINED-PART HELPERS
# ---------------------------------------------------------------------------
def side_for_hand(hand: str) -> Side:
    """`hand` is a body-state key like 'right_hand' or 'left_hand'."""
    if hand.startswith("right"):
        return Side.RIGHT
    if hand.startswith("left"):
        return Side.LEFT
    return Side.NONE


def side_for_foot(foot: str) -> Side:
    if foot.startswith("right"):
        return Side.RIGHT
    if foot.startswith("left"):
        return Side.LEFT
    return Side.NONE


def side_for_body_part(part_value: str) -> Side:
    if "right" in part_value:
        return Side.RIGHT
    if "left" in part_value:
        return Side.LEFT
    return Side.NONE


def target_from_grip_target(target_loc: str) -> Optional[BodyPartTarget]:
    """Collapse the fine-grained GripTarget enum.value strings onto the
    seven-element BodyPartTarget vocabulary. Unknown / ne-waza-only targets
    return None (those events get rendered without a target slot)."""
    s = (target_loc or "").lower()
    if "lapel" in s:
        return BodyPartTarget.LAPEL
    if "sleeve" in s:
        return BodyPartTarget.SLEEVE
    if "collar" in s:
        return BodyPartTarget.COLLAR
    if "belt" in s:
        return BodyPartTarget.BELT
    if "back_gi" in s or "back_of_gi" in s:
        return BodyPartTarget.BACK_OF_GI
    if "wrist" in s:
        return BodyPartTarget.WRIST
    if "cross" in s:
        return BodyPartTarget.CROSS_GRIP
    return None


def target_from_grip_type_v2(grip_type_v2_name: str) -> Optional[BodyPartTarget]:
    """Fallback path when a grip is identified by GripTypeV2 (SLEEVE_HIGH /
    LAPEL_LOW / etc.) rather than a target_location string."""
    n = grip_type_v2_name.upper()
    if n.startswith("SLEEVE"):
        return BodyPartTarget.SLEEVE
    if n.startswith("LAPEL"):
        return BodyPartTarget.LAPEL
    if n == "COLLAR":
        return BodyPartTarget.COLLAR
    if n == "BELT":
        return BodyPartTarget.BELT
    if n == "PISTOL":
        return BodyPartTarget.SLEEVE
    if n == "CROSS":
        return BodyPartTarget.CROSS_GRIP
    return None


# ---------------------------------------------------------------------------
# DETECT SELF-CANCELLATION (§13.8)
# A pull-vector and step-vector emitted by the same actor on the same tick
# are self-cancelling when their dot product is sufficiently negative —
# the fighter is pulling one way while their base steps the other. The
# detection itself runs downstream (HAJ-147), but we expose the predicate
# here so tests can verify the substrate carries enough information.
# ---------------------------------------------------------------------------
def is_self_cancel_pair(a: BodyPartEvent, b: BodyPartEvent) -> bool:
    """True iff `a` and `b` are an opposed pull/step pair from the same
    actor on the same tick. `direction` must be populated on both."""
    if a.actor != b.actor:
        return False
    if a.tick != b.tick:
        return False
    pulls = {BodyPartVerb.PULL, BodyPartVerb.PUSH}
    steps = {BodyPartVerb.STEP, BodyPartVerb.REAP, BodyPartVerb.HOOK}
    has_pull = (a.verb in pulls and b.verb in steps) or (
        b.verb in pulls and a.verb in steps
    )
    if not has_pull:
        return False
    if a.direction is None or b.direction is None:
        return False
    ax, ay = a.direction
    bx, by = b.direction
    a_mag = math.hypot(ax, ay)
    b_mag = math.hypot(bx, by)
    if a_mag < 1e-6 or b_mag < 1e-6:
        return False
    dot = (ax * bx + ay * by) / (a_mag * b_mag)
    # Opposed within ~120° wedge — same threshold pull_self_cancellation_factor
    # uses for full-cancel weighting (cos(120°) = -0.5).
    return dot < -0.4
