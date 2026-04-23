# execution_quality.py
# Physics-substrate Part 4.2.1: execution quality as a first-class concept.
#
# Spec: design-notes/physics-substrate.md, Part 4.2.1.
#
# Every fired throw carries an execution_quality score in [0.0, 1.0] derived
# from its actual_match and commit_threshold. The score is consumed by four
# downstream systems: force transfer, landing severity, counter vulnerability,
# and prose register. This module owns the computation, the banding, and the
# per-throw narration table. Consumers live in match.py, referee.py, and
# counter_windows.py.

from __future__ import annotations
from enum import Enum, auto
from typing import Optional

from throws import ThrowID


# ---------------------------------------------------------------------------
# TUNING (Phase 3 calibration targets; the spec commits the *coupling*, not
# these numbers)
# ---------------------------------------------------------------------------
DEFAULT_COMMIT_THRESHOLD: float = 0.50   # legacy throws without a worked template

# Force transfer: linear from FLOOR at eq=0 to 1.0 at eq=1. The floor keeps
# a barely-committed throw from zeroing out entirely — it still delivers
# *some* force, just much less than a clean finish.
FORCE_TRANSFER_FLOOR: float = 0.30

# Landing severity gates (referee.score_throw consumes these).
IPPON_MIN_EQ:    float = 0.70
WAZA_ARI_MIN_EQ: float = 0.40

# Counter vulnerability: low-eq throws leave tori more exploitable. Multiplier
# applied to counter fire probability; 1.0 at clean (eq=1.0), 1.0+MAX at
# marginal (eq=0.0).
COUNTER_VULNERABILITY_MAX_BONUS: float = 0.6


# ---------------------------------------------------------------------------
# QUALITY BAND
# ---------------------------------------------------------------------------
class QualityBand(Enum):
    LOW  = auto()   # eq < 0.40 — sloppy; uke may recover
    MED  = auto()   # 0.40 ≤ eq < 0.70 — partial finish
    HIGH = auto()   # eq ≥ 0.70 — clean


# ---------------------------------------------------------------------------
# COMPUTATION
# ---------------------------------------------------------------------------
def compute_execution_quality(
    actual_match: float, commit_threshold: float,
) -> float:
    """Part 4.2.1: `(actual - threshold) / (1 - threshold)`, clamped to [0, 1].

    Returns 0.0 at the commit threshold, 1.0 at perfect signature match. If
    commit_threshold ≥ 1.0 (degenerate) the formula would divide by zero —
    fall back to 0.0 for safety.
    """
    denom = 1.0 - commit_threshold
    if denom <= 1e-9:
        return 0.0
    eq = (actual_match - commit_threshold) / denom
    if eq < 0.0:
        return 0.0
    if eq > 1.0:
        return 1.0
    return eq


def commit_threshold_for(throw_id: ThrowID) -> float:
    """Read commit_threshold from the worked template, or fall back to the
    default for legacy throws still on the ThrowDef path.
    """
    from worked_throws import worked_template_for
    template = worked_template_for(throw_id)
    if template is None:
        return DEFAULT_COMMIT_THRESHOLD
    return float(template.commit_threshold)


def band_for(eq: float) -> QualityBand:
    if eq >= IPPON_MIN_EQ:
        return QualityBand.HIGH
    if eq >= WAZA_ARI_MIN_EQ:
        return QualityBand.MED
    return QualityBand.LOW


# ---------------------------------------------------------------------------
# CONSUMER CURVES
# ---------------------------------------------------------------------------
def force_transfer_multiplier(eq: float) -> float:
    """Scale applied to kake force magnitude. Linear from FLOOR to 1.0."""
    return FORCE_TRANSFER_FLOOR + (1.0 - FORCE_TRANSFER_FLOOR) * max(
        0.0, min(1.0, eq),
    )


def counter_vulnerability_multiplier(eq: float) -> float:
    """Scale applied to uke's counter-fire probability against this tori.
    Low-eq throws are more exploitable; 1.0 at eq=1, 1.0+MAX_BONUS at eq=0.
    """
    e = max(0.0, min(1.0, eq))
    return 1.0 + COUNTER_VULNERABILITY_MAX_BONUS * (1.0 - e)


# ---------------------------------------------------------------------------
# PROSE REGISTER (Part 4.2.1 point 4)
# One narration line per band per worked throw. These are starter strings —
# the spec commits the *coupling*, not the prose itself. Expand per throw as
# calibration feedback lands.
#
# The generic fallback applies to any throw not explicitly listed (legacy
# ThrowDef-only throws, or templates added after this table was written).
# ---------------------------------------------------------------------------
_GENERIC_NARRATION: dict[QualityBand, str] = {
    QualityBand.HIGH: "clean finish, control maintained",
    QualityBand.MED:  "partial execution — uke lands but tori doesn't follow",
    QualityBand.LOW:  "scrappy entry, uke absorbs and resets",
}

THROW_QUALITY_NARRATION: dict[ThrowID, dict[QualityBand, str]] = {
    ThrowID.UCHI_MATA: {
        QualityBand.HIGH: "full hip rotation, uke airborne and flat",
        QualityBand.MED:  "reaping leg catches, uke rolls through the landing",
        QualityBand.LOW:  "hip-loaded top-leg variant — lift became a bump, uke steps out",
    },
    ThrowID.O_SOTO_GARI: {
        QualityBand.HIGH: "thigh-to-thigh contact at chest closure, uke dropped flat",
        QualityBand.MED:  "calf contact at mid-range, uke pitches but posts a hand",
        QualityBand.LOW:  "heel-to-calf at arm's length, sweep glances — uke stays up",
    },
    ThrowID.SEOI_NAGE: {
        QualityBand.HIGH: "uke loaded across the shoulders and airborne",
        QualityBand.MED:  "uke slides around the side, half-committed landing",
        QualityBand.LOW:  "tori stuck bent forward, uke rides the back",
    },
    ThrowID.DE_ASHI_HARAI: {
        QualityBand.HIGH: "foot catches mid-unweight, uke drops laterally",
        QualityBand.MED:  "foot clips the ankle, uke stumbles but catches",
        QualityBand.LOW:  "foot glances off a planted leg — no sweep",
    },
    ThrowID.TAI_OTOSHI: {
        QualityBand.HIGH: "uke trips cleanly over the blocked leg",
        QualityBand.MED:  "hips crowd in, block half-formed — uke rolls over",
        QualityBand.LOW:  "loaded the hip — Tai-otoshi doesn't want the hip — the throw landed crooked",
    },
    ThrowID.HARAI_GOSHI: {
        QualityBand.HIGH: "hip contact, sweeping leg brushes thigh, clean arc",
        QualityBand.MED:  "partial hip engagement, uke spins off the side",
        QualityBand.LOW:  "sweep misses the thigh, uke pushes off tori's hip",
    },
    ThrowID.HARAI_GOSHI_CLASSICAL: {
        QualityBand.HIGH: "hip-fulcrum loaded, uke wheeled over the pivot",
        QualityBand.MED:  "fulcrum engaged but low — uke rotates off the knee",
        QualityBand.LOW:  "tori bent forward under load, no rotation delivered",
    },
    ThrowID.O_GOSHI: {
        QualityBand.HIGH: "sacrum under uke's CoM, full lift and rotation",
        QualityBand.MED:  "lift half-completed, uke comes over flat-footed",
        QualityBand.LOW:  "no lift arrived — tori bent forward, uke climbs off",
    },
    ThrowID.O_UCHI_GARI: {
        QualityBand.HIGH: "inner hook drives uke's weight onto the reaped leg",
        QualityBand.MED:  "hook catches but weight never fully loads",
        QualityBand.LOW:  "leg threads through without pressure — uke steps clear",
    },
    ThrowID.KO_UCHI_GARI: {
        QualityBand.HIGH: "ankle sweep times the unweight perfectly",
        QualityBand.MED:  "ankle clipped, uke recovers balance",
        QualityBand.LOW:  "sweep mistimed, foot glances the planted side",
    },
    ThrowID.SUMI_GAESHI: {
        QualityBand.HIGH: "corner drop lands clean, uke flipped over the hook",
        QualityBand.MED:  "partial rotation, uke lands sideways in scramble",
        QualityBand.LOW:  "tori on their back, uke standing — ne-waza opens",
    },
    ThrowID.TOMOE_NAGE: {
        QualityBand.HIGH: "foot on belt, full overhead arc, uke flat",
        QualityBand.MED:  "arc incomplete — uke comes down in scramble",
        QualityBand.LOW:  "tori on both knees, uke steps over — posture lost",
    },
    ThrowID.O_GURUMA: {
        QualityBand.HIGH: "extended leg at hip-line, uke wheeled over cleanly",
        QualityBand.MED:  "fulcrum low — uke rotates part-way and rolls out",
        QualityBand.LOW:  "leg misses the hip-line, uke pushes through",
    },
}


def narration_for(
    throw_id: ThrowID, band: QualityBand,
) -> str:
    table = THROW_QUALITY_NARRATION.get(throw_id)
    if table is None:
        return _GENERIC_NARRATION[band]
    return table.get(band, _GENERIC_NARRATION[band])
