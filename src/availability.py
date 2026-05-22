# availability.py
# HAJ-207 — Stage 1 availability filter + minimal Stage 2 selection.
#
# Catalog-driven gating that replaces the priority-laddered grip-presence
# checks in the action selector. A technique is Stage-1-available when:
#
#   1. Tori holds every grip in some `canonical_grip_signatures` entry at
#      required-or-better depth, on a matching region of uke; AND
#   2. Uke does not hold any of that signature's `uke_disqualifying_grips`
#      on tori at required-or-better depth; AND
#   3. Tori has the technique in their vocabulary at PROFICIENT tier or
#      higher (KNOWN / NOVICE are training-only — not selectable for
#      live commit).
#
# Stage 2 (minimal) picks one technique from the available set: it gates
# on whether the technique's `admissible_kuzushi_vectors` admit the
# current kuzushi resultant (or contain the `any` wildcard), weights by
# proficiency and the existing perceived-signature score, and applies a
# stochastic fire roll modulated by fight IQ + conditioning.
#
# Spec: design-notes/triage/technique-vocabulary-system.md, Section 1
# (Engine Implications) and Section 2 (v1.2 schema).

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Optional

from enums import (
    BodyPart, DominantSide, GripTarget, GripTypeV2,
    GripDepth as EngineGripDepth,
)
from technique_catalog import (
    GripDepth as CatalogGripDepth,
    GripHand, GripSignature, GripSpec, GripTargetRegion,
    KUZUSHI_ANY_TOKEN, PROFICIENCY_ORDER, ProficiencyTier,
    TechniqueDefinition,
)
from throws import ThrowID

if TYPE_CHECKING:
    from grip_graph import GripEdge, GripGraph
    from judoka import Judoka


# ---------------------------------------------------------------------------
# THROW ↔ TECHNIQUE_ID BRIDGE
# Ring 1 throws live in throws.ThrowID. The catalog keys by string
# technique_id. This mapping is the single authoritative bridge so the
# action selector can translate between the two without duplicating it
# in three places.
# ---------------------------------------------------------------------------
THROW_TO_TECHNIQUE_ID: dict[ThrowID, str] = {
    ThrowID.SEOI_NAGE:              "seoi_nage",
    ThrowID.UCHI_MATA:              "uchi_mata",
    ThrowID.O_SOTO_GARI:            "osoto_gari",
    ThrowID.O_UCHI_GARI:            "ouchi_gari",
    ThrowID.KO_UCHI_GARI:           "kouchi_gari",
    ThrowID.HARAI_GOSHI:            "harai_goshi",
    ThrowID.TAI_OTOSHI:             "tai_otoshi",
    ThrowID.SUMI_GAESHI:            "sumi_gaeshi",
    ThrowID.DE_ASHI_HARAI:          "deashi_harai",
    ThrowID.O_GOSHI:                "o_goshi",
    ThrowID.HARAI_GOSHI_CLASSICAL:  "harai_goshi",
    ThrowID.TOMOE_NAGE:             "tomoe_nage",
    ThrowID.O_GURUMA:               "o_guruma",
}

TECHNIQUE_ID_TO_THROWS: dict[str, list[ThrowID]] = {}
for _tid, _tech in THROW_TO_TECHNIQUE_ID.items():
    TECHNIQUE_ID_TO_THROWS.setdefault(_tech, []).append(_tid)


# Minimum tier at which a technique becomes selectable for live commit.
# KNOWN / NOVICE techniques are training-only per Section 3.
MIN_COMMIT_TIER: ProficiencyTier = ProficiencyTier.PROFICIENT


# ---------------------------------------------------------------------------
# ENGINE ↔ CATALOG MAPPINGS
# ---------------------------------------------------------------------------

# Catalog depth → minimum engine depth (using GripDepth.modifier()).
# SHALLOW maps to POCKET, CONTROLLED to STANDARD, DEEP to DEEP. The check
# is "engine depth >= threshold" using modifier() so the ordering survives
# the SLIPPING (0.2) outlier — a slipping grip cannot satisfy any catalog
# minimum.
_CATALOG_TO_ENGINE_MIN_DEPTH: dict[CatalogGripDepth, float] = {
    CatalogGripDepth.SHALLOW:    EngineGripDepth.POCKET.modifier(),
    CatalogGripDepth.CONTROLLED: EngineGripDepth.STANDARD.modifier(),
    CatalogGripDepth.DEEP:       EngineGripDepth.DEEP.modifier(),
}

# Catalog target region → predicate on a GripEdge. Each predicate returns
# True if the edge's grip_type_v2 + target_location match the region's
# intent. The catalog regions are uke-relative ("uke_lapel_high") so we
# match by grip-shape family; the canonical right-stance configuration
# is enforced by the hand mapping below, not by the side of the lapel.
_REGION_PREDICATES: dict[GripTargetRegion, "_RegionPredicate"] = {}


def _region_lapel_high(edge: "GripEdge") -> bool:
    return edge.grip_type_v2 == GripTypeV2.LAPEL_HIGH or edge.grip_type_v2.is_collar()


def _region_lapel_low(edge: "GripEdge") -> bool:
    return edge.grip_type_v2 == GripTypeV2.LAPEL_LOW


def _region_sleeve_upper(edge: "GripEdge") -> bool:
    return edge.grip_type_v2 == GripTypeV2.SLEEVE_HIGH


def _region_sleeve_lower(edge: "GripEdge") -> bool:
    # PISTOL is a sleeve-cuff clamp; treat as a lower-sleeve region.
    return edge.grip_type_v2 in (GripTypeV2.SLEEVE_LOW, GripTypeV2.PISTOL)


def _region_back(edge: "GripEdge") -> bool:
    return edge.grip_type_v2.is_collar() or edge.target_location in (
        GripTarget.BACK_COLLAR, GripTarget.LEFT_BACK_GI, GripTarget.RIGHT_BACK_GI,
    )


def _region_belt(edge: "GripEdge") -> bool:
    return edge.grip_type_v2 == GripTypeV2.BELT or edge.target_location == GripTarget.BELT


def _region_never(_edge: "GripEdge") -> bool:
    # Leg-grab regions don't have a corresponding standing-grip enum in the
    # engine yet. Techniques requiring them are filtered out automatically.
    return False


_REGION_PREDICATES = {
    GripTargetRegion.UKE_LAPEL_HIGH:   _region_lapel_high,
    GripTargetRegion.UKE_LAPEL_LOW:    _region_lapel_low,
    GripTargetRegion.UKE_SLEEVE_UPPER: _region_sleeve_upper,
    GripTargetRegion.UKE_SLEEVE_LOWER: _region_sleeve_lower,
    GripTargetRegion.UKE_BACK:         _region_back,
    GripTargetRegion.UKE_BELT:         _region_belt,
    GripTargetRegion.UKE_LEG_OUTER:    _region_never,
    GripTargetRegion.UKE_LEG_INNER:    _region_never,
    GripTargetRegion.UKE_HEEL:         _region_never,
}


# Catalog hand label → engine body-part key. Canonical right-stance reading:
# tori_left ↔ left_hand, tori_right ↔ right_hand. When a signature is
# `mirror_eligible` and tori is LEFT-dominant, the labels swap so a
# left-dominant uchi-mata specialist's grips resolve correctly.
def _resolve_hand(
    hand: GripHand, tori_dominant: DominantSide, mirror_eligible: bool,
) -> str:
    canonical_right = tori_dominant == DominantSide.RIGHT or not mirror_eligible
    if hand == GripHand.TORI_RIGHT:
        return "right_hand" if canonical_right else "left_hand"
    return "left_hand" if canonical_right else "right_hand"


# Type alias for the region predicate (declared after definitions so the
# concrete signatures resolve cleanly at import time).
from typing import Callable as _Callable
_RegionPredicate = _Callable[["GripEdge"], bool]


# ---------------------------------------------------------------------------
# PROFICIENCY LOOKUP
# Pre-HAJ-207 Capability tracked throw vocabulary as a flat ThrowID list
# without explicit tier semantics. The new path reads tiers from
# `Capability.technique_records` when present (Ring 2+ vocabulary state);
# otherwise we treat any throw_vocabulary entry as PROFICIENT — the
# minimum tier that licenses live commit — so legacy fixtures keep working.
# ---------------------------------------------------------------------------
def proficiency_tier_for(
    judoka: "Judoka", technique_id: str,
) -> ProficiencyTier:
    """Return the judoka's proficiency tier for a catalog technique_id.

    Reads `capability.technique_records` if the field is populated (the
    long-horizon orchestrator/resolver path). Falls back to PROFICIENT
    when the technique's ThrowID counterpart is in `throw_vocabulary`,
    and to KNOWN when nothing matches — KNOWN does not clear
    MIN_COMMIT_TIER, so unknown techniques drop out of the available set.
    """
    records = getattr(judoka.capability, "technique_records", None)
    if records is not None:
        rec = records.get(technique_id)
        if rec is not None:
            return rec.proficiency_tier
    for throw_id in TECHNIQUE_ID_TO_THROWS.get(technique_id, ()):
        if throw_id in judoka.capability.throw_vocabulary:
            return ProficiencyTier.PROFICIENT
    return ProficiencyTier.KNOWN


def _tier_meets_commit_minimum(tier: ProficiencyTier) -> bool:
    return (PROFICIENCY_ORDER.index(tier)
            >= PROFICIENCY_ORDER.index(MIN_COMMIT_TIER))


# ---------------------------------------------------------------------------
# STAGE 1 — AVAILABILITY FILTER
# ---------------------------------------------------------------------------
def _edge_matches_grip_spec(
    edge: "GripEdge", spec: GripSpec,
    grasper_id: str, target_id: str,
    grasper_dominant: DominantSide, mirror_eligible: bool,
) -> bool:
    """True when `edge` satisfies catalog `spec` for `grasper_id` gripping
    `target_id`. Reads the edge's max_depth_reached (the "earned" peak)
    rather than current depth so a momentarily-stripped grip retains the
    commit eligibility it already established — same convention the
    grip-presence gate uses (see HAJ-36).
    """
    if edge.grasper_id != grasper_id or edge.target_id != target_id:
        return False
    expected_part = _resolve_hand(spec.hand, grasper_dominant, mirror_eligible)
    if edge.grasper_part.value != expected_part:
        return False
    predicate = _REGION_PREDICATES.get(spec.target_region)
    if predicate is None or not predicate(edge):
        return False
    peak = edge.max_depth_reached or edge.depth_level
    if peak.modifier() < _CATALOG_TO_ENGINE_MIN_DEPTH[spec.minimum_depth]:
        return False
    return True


def _spec_satisfied_by_any_edge(
    spec: GripSpec, edges: list["GripEdge"],
    grasper_id: str, target_id: str,
    grasper_dominant: DominantSide, mirror_eligible: bool,
) -> bool:
    return any(
        _edge_matches_grip_spec(
            e, spec, grasper_id, target_id, grasper_dominant, mirror_eligible,
        )
        for e in edges
    )


def _signature_available(
    signature: GripSignature,
    grip_graph: "GripGraph",
    tori: "Judoka",
    uke: "Judoka",
) -> bool:
    """Check one (signature) entry of `canonical_grip_signatures`.

    Tori must satisfy every `tori_required_grips` spec; uke must hold
    none of the `uke_disqualifying_grips`.
    """
    tori_edges = grip_graph.edges_owned_by(tori.identity.name)
    uke_edges = grip_graph.edges_owned_by(uke.identity.name)
    mirror = signature.mirror_eligible
    tori_dom = tori.identity.dominant_side
    uke_dom = uke.identity.dominant_side

    for spec in signature.tori_required_grips:
        if not _spec_satisfied_by_any_edge(
            spec, tori_edges,
            grasper_id=tori.identity.name, target_id=uke.identity.name,
            grasper_dominant=tori_dom, mirror_eligible=mirror,
        ):
            return False

    for spec in signature.uke_disqualifying_grips:
        # The disqualifying spec is authored from tori's perspective:
        # "tori_right hand on uke_sleeve_lower deep" means uke holds the
        # described grip on tori (a deep pistol-grip-on-tori's-sleeve
        # blocks the throw). Resolve the hand against uke's dominant
        # side because uke is the grasper here.
        if _spec_satisfied_by_any_edge(
            spec, uke_edges,
            grasper_id=uke.identity.name, target_id=tori.identity.name,
            grasper_dominant=uke_dom, mirror_eligible=mirror,
        ):
            return False

    return True


def stage1_available_techniques(
    grip_graph: "GripGraph",
    tori: "Judoka",
    uke: "Judoka",
    catalog: dict[str, TechniqueDefinition],
) -> set[str]:
    """Return technique_ids whose canonical_grip_signature is satisfied
    by the current grip configuration AND that tori has at proficient+
    tier.

    A technique is available if ANY of its canonical_grip_signatures
    matches — multi-signature lists in the catalog (v1.2) express
    distinct grip variants of the same technique.
    """
    available: set[str] = set()
    for technique_id, definition in catalog.items():
        tier = proficiency_tier_for(tori, technique_id)
        if not _tier_meets_commit_minimum(tier):
            continue
        for signature in definition.canonical_grip_signatures:
            if _signature_available(signature, grip_graph, tori, uke):
                available.add(technique_id)
                break
    return available


# ---------------------------------------------------------------------------
# STAGE 2 — KUZUSHI-VECTOR MATCH + SELECTION
# ---------------------------------------------------------------------------

# Proficiency → weight contribution in Stage 2 sampling. The ladder
# above PROFICIENT widens slowly so an EXPERT fighter biases hard toward
# their best techniques without locking out merely proficient options
# (real judo: even a master fires their D-techniques occasionally).
_PROFICIENCY_WEIGHTS: dict[ProficiencyTier, float] = {
    ProficiencyTier.KNOWN:        0.0,   # guarded by _tier_meets_commit_minimum
    ProficiencyTier.NOVICE:       0.0,
    ProficiencyTier.PROFICIENT:   1.0,
    ProficiencyTier.INTERMEDIATE: 1.4,
    ProficiencyTier.COMPETITIVE:  1.8,
    ProficiencyTier.EXPERT:       2.2,
    ProficiencyTier.MASTER:       2.6,
    ProficiencyTier.LEGENDARY:    3.0,
}


# Direction-vector classification thresholds. The kuzushi resultant is a
# 2D vector in world frame; uke's facing rotates it into uke's local
# frame so "forward" means uke is being pulled in the direction they
# face. Diagonal bands are 45° wide; pure axes get a 22.5° tolerance
# either side. Vectors below MIN_MAGNITUDE are treated as "no direction"
# — Stage 2 skips kuzushi-vector matching and admits techniques whose
# admissible vectors include `any`.
KUZUSHI_DIRECTION_MIN_MAGNITUDE: float = 0.05
_HALF_BAND_RADIANS: float = math.radians(22.5)


def classify_kuzushi_direction(
    kuzushi_vector: tuple[float, float],
    uke_facing: tuple[float, float],
) -> Optional[str]:
    """Classify a (x, y) kuzushi resultant in world frame into one of the
    catalog direction tokens, expressed in uke's local frame.

    Returns None when the resultant magnitude is below threshold (no
    meaningful direction to match).
    """
    vx, vy = kuzushi_vector
    magnitude = (vx * vx + vy * vy) ** 0.5
    if magnitude < KUZUSHI_DIRECTION_MIN_MAGNITUDE:
        return None
    fx, fy = uke_facing
    facing_norm = (fx * fx + fy * fy) ** 0.5 or 1.0
    fx /= facing_norm
    fy /= facing_norm
    # Project onto uke's local axes: forward = +x_local = uke's facing;
    # +y_local = uke's left (90° CCW of facing in world frame).
    forward = (vx * fx + vy * fy) / magnitude
    left    = (vx * -fy + vy * fx) / magnitude
    angle = math.atan2(left, forward)  # 0 = forward, π/2 = uke-left, π = rear.
    # Map angle to bands (22.5° = π/8 = _HALF_BAND_RADIANS).
    bands = [
        ("forward_pure",            0.0),
        ("forward_left_diagonal",   math.pi / 4),
        ("side_left",               math.pi / 2),
        ("rear_left_diagonal",      3 * math.pi / 4),
        ("rear_pure",               math.pi),
        ("rear_right_diagonal",   -3 * math.pi / 4),
        ("side_right",            -math.pi / 2),
        ("forward_right_diagonal", -math.pi / 4),
    ]
    # Pick the band centre closest to `angle` on the circle.
    best_token = bands[0][0]
    best_diff = math.pi * 2
    for token, centre in bands:
        diff = abs(_angular_diff(angle, centre))
        if diff < best_diff:
            best_diff = diff
            best_token = token
    return best_token


def _angular_diff(a: float, b: float) -> float:
    """Shortest signed angular distance from b to a, in [-π, π]."""
    d = (a - b + math.pi) % (2 * math.pi) - math.pi
    return d


def _technique_admits_direction(
    definition: TechniqueDefinition, direction_token: Optional[str],
) -> bool:
    if KUZUSHI_ANY_TOKEN in definition.admissible_kuzushi_vectors:
        return True
    if direction_token is None:
        # No direction available; only `any` techniques are admissible.
        return False
    return direction_token in definition.admissible_kuzushi_vectors


def stage2_fire_probability(judoka: "Judoka") -> float:
    """Stochastic gate scaling with fight IQ + cardio.

    A fresh, high-IQ fighter recognizes openings and commits cleanly; a
    cooked low-IQ fighter hesitates or rushes. Clamped to [0.2, 0.95]
    so even an extreme low-end fighter still fires occasionally and an
    elite one never fires automatically (real judo: openings are missed
    even at the top).
    """
    iq = max(0, min(10, int(judoka.capability.fight_iq)))
    cardio = max(0.0, min(1.0, float(judoka.state.cardio_current)))
    return max(0.2, min(0.95, 0.35 + 0.04 * iq + 0.30 * cardio))


def stage2_select_technique(
    available: set[str],
    catalog: dict[str, TechniqueDefinition],
    tori: "Judoka",
    kuzushi_vector: tuple[float, float],
    uke_facing: tuple[float, float],
    perceived_signature: dict[str, float],
    rng: random.Random,
) -> Optional[str]:
    """Pick one technique from `available` to commit, or None to skip
    this tick.

    Selection blends three signals (per HAJ-207 ticket):
      - kuzushi-vector match against admissible_kuzushi_vectors
      - proficiency weighting (PROFICIENT < INTERMEDIATE < ... < LEGENDARY)
      - stochastic roll modulated by fight IQ + conditioning

    `perceived_signature` is the existing engine perceived-signature
    score per technique_id; we treat it as a stand-in for the
    "kinetic_preconditions" weight at v0.1 — a technique that doesn't
    even register on perception isn't a viable commit candidate.
    """
    direction = classify_kuzushi_direction(kuzushi_vector, uke_facing)

    weighted: list[tuple[str, float]] = []
    for tid in available:
        definition = catalog.get(tid)
        if definition is None:
            continue
        if not _technique_admits_direction(definition, direction):
            continue
        tier = proficiency_tier_for(tori, tid)
        prof_w = _PROFICIENCY_WEIGHTS.get(tier, 0.0)
        if prof_w <= 0.0:
            continue
        # Signature score is in [0, 1]; bias the weight so techniques the
        # engine perceives as already-firing dominate. A floor of 0.1
        # keeps low-signature options reachable when nothing yet scores.
        sig = max(0.1, perceived_signature.get(tid, 0.0))
        weighted.append((tid, prof_w * sig))

    if not weighted:
        return None

    if rng.random() >= stage2_fire_probability(tori):
        return None

    total = sum(w for _, w in weighted)
    if total <= 0.0:
        return None
    pick = rng.random() * total
    cumulative = 0.0
    for tid, w in weighted:
        cumulative += w
        if pick <= cumulative:
            return tid
    return weighted[-1][0]


# ---------------------------------------------------------------------------
# CONVENIENCE — TIER PREDICATE FOR DOWNSTREAM CALLERS
# ---------------------------------------------------------------------------
def can_commit_at_tier(tier: ProficiencyTier) -> bool:
    """Public re-export so other modules don't need to know MIN_COMMIT_TIER."""
    return _tier_meets_commit_minimum(tier)
