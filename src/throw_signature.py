# throw_signature.py
# Physics-substrate Part 4.2: the four-dimension signature match.
#
# Spec: design-notes/physics-substrate.md, Part 4.2 (shared by 4.3 / 4.4).
#
# A throw's `actual_match` is a weighted sum of four per-dimension scores:
#
#   actual_match = w_kuzushi * match_kuzushi_vector +
#                  w_force   * match_force_application +
#                  w_body    * match_body_parts +
#                  w_posture * match_uke_posture
#
# Weights vary by classification (spec 4.2); they live on the template
# (CoupleThrow / LeverThrow.signature_weights()).
#
# Each dimension returns a score in [0.0, 1.0]. Sub-conditions within a
# dimension are averaged — giving the signature graded values rather than
# binary pass/fail, which is what the Part 3.5 perception layer needs to
# produce meaningful false positives and false negatives.
#
# What this module does NOT do:
#   - It does not know about in-tick actions (PULL/PUSH commands). It reads
#     from the grip graph + BodyState, the same authoritative inputs that
#     Part 3.5's actual_signature_match reads. Part 5 or later may pipe
#     in-tick action data through for finer force-dimension scoring.
#   - It does not resolve failure outcomes — that's the commit-resolver's job
#     in Part 5 / match.py.

from __future__ import annotations

from math import acos, hypot, pi
from typing import TYPE_CHECKING

from enums import GripDepth, GripMode, DominantSide
from force_envelope import FORCE_ENVELOPES, delivered_pull_force
from throw_templates import (
    ThrowClassification, CoupleThrow, LeverThrow, ThrowTemplate,
    KuzushiRequirement, GripRequirement, CoupleBodyPartRequirement,
    LeverBodyPartRequirement, UkePostureRequirement, SupportRequirement,
    SignatureWeights,
)


# ---------------------------------------------------------------------------
# FORCE-APPLICATION MODULATORS (Parts 4.3 / 4.4) — calibration targets.
# Bidirectional effect: grip configuration on the attacker's dominant hand
# either grants a Lever the lift channel (engaged) or starves it (free),
# and uke's absence of grips removes the structural resistance a Couple
# throw's torque has to overcome.
# ---------------------------------------------------------------------------
DOMINANT_HAND_FREE_LEVER_PENALTY: float = 0.40  # 0.3–0.5 band; start mid
UKE_UNGRIPPED_COUPLE_BONUS:       float = 0.30  # ~0.3 per ticket

if TYPE_CHECKING:
    from judoka import Judoka
    from grip_graph import GripGraph, GripEdge


# ---------------------------------------------------------------------------
# DEPTH ORDERING — POCKET < STANDARD < DEEP; SLIPPING floors to POCKET.
# ---------------------------------------------------------------------------
_DEPTH_RANK: dict[GripDepth, int] = {
    GripDepth.SLIPPING: 0,
    GripDepth.POCKET:   1,
    GripDepth.STANDARD: 2,
    GripDepth.DEEP:     3,
}


def _depth_at_least(actual: GripDepth, minimum: GripDepth) -> bool:
    return _DEPTH_RANK[actual] >= _DEPTH_RANK[minimum]


# ---------------------------------------------------------------------------
# GEOMETRY HELPERS
# ---------------------------------------------------------------------------
def _to_body_frame(
    vec: tuple[float, float], facing: tuple[float, float],
) -> tuple[float, float]:
    """Rotate a mat-frame 2D vector into the judoka's body frame.

    Body frame: forward = +X (aligned with `facing`), right = +Y.
    """
    fx, fy = facing
    norm = hypot(fx, fy)
    if norm < 1e-9:
        return vec
    fx, fy = fx / norm, fy / norm
    # Inverse rotation: body_x = facing·vec; body_y = perp(facing)·vec.
    return (fx * vec[0] + fy * vec[1], -fy * vec[0] + fx * vec[1])


def _angle_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Unsigned angle in radians between two 2D vectors (both non-zero)."""
    na = hypot(*a)
    nb = hypot(*b)
    if na < 1e-9 or nb < 1e-9:
        return pi
    cos_theta = (a[0] * b[0] + a[1] * b[1]) / (na * nb)
    return acos(max(-1.0, min(1.0, cos_theta)))


def _in_range(x: float, lo_hi: tuple[float, float]) -> bool:
    lo, hi = lo_hi
    return lo <= x <= hi


# ---------------------------------------------------------------------------
# DIMENSION 1 — KUZUSHI VECTOR (Part 4.2 dimension 1)
# HAJ-132 — polarity reversal. This dimension now reads uke's decaying
# event buffer, not uke's current CoM-velocity snapshot. Throws fire
# because pulls composed, not because uke happens to be moving this tick.
#
# Force/body/posture dimensions remain snapshot reads — see ticket spec
# for why each of those is naturally a current-tick check.
# ---------------------------------------------------------------------------
def match_kuzushi_vector(
    throw: ThrowTemplate, attacker: "Judoka", defender: "Judoka",
    current_tick: int = 0,
) -> float:
    """Score uke's kuzushi against the throw's `kuzushi_requirement`.

    Direction is matched against the resultant of uke's decayed event
    buffer (in uke's body frame). Magnitude is matched against the buffer's
    accumulated magnitude — converted from the per-template m/s threshold
    (Couple) or m threshold (Lever) via KUZUSHI_PER_MPS / KUZUSHI_PER_M.

    Special flag `aligned_with_uke_velocity` (De-ashi-harai) relaxes the
    direction check — any non-zero buffered kuzushi satisfies it.
    """
    from kuzushi import compromised_state, KUZUSHI_PER_MPS, KUZUSHI_PER_M
    req: KuzushiRequirement = throw.kuzushi_requirement
    facing = defender.state.body_state.facing

    cs = compromised_state(defender.kuzushi_events, current_tick)
    cv_body = _to_body_frame(cs.vector, facing)
    cv_mag = hypot(*cv_body)

    # Direction score: 1.0 inside tolerance, linear falloff to 0 at 2×tolerance.
    if req.aligned_with_uke_velocity:
        dir_score = 1.0 if cv_mag > 1e-6 else 0.0
    else:
        if cv_mag < 1e-6:
            dir_score = 0.0
        else:
            angle = _angle_between(cv_body, req.direction)
            if angle <= req.tolerance_rad:
                dir_score = 1.0
            elif angle >= 2.0 * req.tolerance_rad:
                dir_score = 0.0
            else:
                dir_score = 1.0 - (angle - req.tolerance_rad) / req.tolerance_rad

    if throw.classification == ThrowClassification.COUPLE:
        if req.min_velocity_magnitude <= 0.0:
            mag_score = 1.0
        else:
            threshold_kuzushi = req.min_velocity_magnitude * KUZUSHI_PER_MPS
            mag_score = min(1.0, cs.magnitude / threshold_kuzushi)
        return 0.5 * dir_score + 0.5 * mag_score

    # Lever: per-template displacement threshold converted to kuzushi units.
    if req.min_displacement_past_recoverable <= 0.0:
        disp_score = 1.0 if cs.magnitude > 0.0 else 0.0
    else:
        threshold_kuzushi = req.min_displacement_past_recoverable * KUZUSHI_PER_M
        disp_score = min(1.0, cs.magnitude / threshold_kuzushi)
    return 0.5 * dir_score + 0.5 * disp_score


# ---------------------------------------------------------------------------
# DIMENSION 2 — FORCE APPLICATION (Part 4.2 dimension 2)
# ---------------------------------------------------------------------------
def match_force_application(
    throw: ThrowTemplate, attacker: "Judoka", defender: "Judoka",
    graph: "GripGraph",
) -> float:
    """Score the attacker's current grips against the throw's force-application
    dimension. Reads from the grip graph (edges, depths, modes) rather than
    in-tick action commands — matching Part 3.5's signature-match conventions.

    Components (averaged):
      - Every GripRequirement in `force_grips` is satisfied: right hand, one
        of the accepted grip types, depth ≥ min_depth, current mode matches.
      - The sum of delivered pull force across driving grips meets the throw's
        force floor (min_torque_nm for Couple, min_lift_force_n for Lever).

    Two bidirectional modulators on top of the averaged base score (Parts
    4.3 / 4.4, "force application modulators"; calibration targets):

      - Lever throws with `requires_dominant_hand_grip=True`: if tori's
        dominant hand is not GRIPPING_UKE on a required grip type, subtract
        DOMINANT_HAND_FREE_LEVER_PENALTY — the lift channel is missing.
      - Couple throws against an uke with zero grips in GRIPPING_UKE state:
        add UKE_UNGRIPPED_COUPLE_BONUS — uke has surrendered the structural
        resistance the torque has to overcome.

    The final score is clamped to [0, 1].
    """
    attacker_edges = graph.edges_owned_by(attacker.identity.name)
    grip_req_tuple = throw.force_grips

    # Part A — grip presence / depth / mode.
    if not grip_req_tuple:
        grip_score = 1.0
    else:
        satisfied = sum(
            1 for req in grip_req_tuple
            if _grip_requirement_met(req, attacker_edges)
        )
        grip_score = satisfied / len(grip_req_tuple)

    # Part B — delivered-force floor. Estimate total pull force available on
    # this tick across the grips that satisfy the requirements in DRIVING mode.
    delivered = 0.0
    for req in grip_req_tuple:
        edge = _matching_edge(req, attacker_edges)
        if edge is None or edge.mode != GripMode.DRIVING:
            continue
        delivered += delivered_pull_force(
            edge.grip_type_v2, edge.depth_level, attacker, req.hand,
        )

    if throw.classification == ThrowClassification.COUPLE:
        floor = max(1.0, float(throw.min_torque_nm))
    else:
        floor = max(1.0, float(throw.min_lift_force_n))
    force_score = min(1.0, delivered / floor)

    score = 0.5 * grip_score + 0.5 * force_score

    # --- Modulators ------------------------------------------------------
    if throw.classification == ThrowClassification.LEVER:
        if getattr(throw, "requires_dominant_hand_grip", False):
            if not _dominant_hand_gripping_required_type(
                throw, attacker, attacker_edges,
            ):
                score -= DOMINANT_HAND_FREE_LEVER_PENALTY
    else:  # Couple
        if _uke_has_no_grips(defender, graph):
            score += UKE_UNGRIPPED_COUPLE_BONUS

    return max(0.0, min(1.0, score))


def _dominant_hand_gripping_required_type(
    throw: "LeverThrow", attacker: "Judoka", attacker_edges: list["GripEdge"],
) -> bool:
    """True when tori's dominant hand currently holds a grip on uke whose
    grip_type_v2 is accepted by the throw's dominant-hand GripRequirement,
    AND the hand's body-part ContactState is GRIPPING_UKE.

    The dominant hand is the grasping hand for tsurite (the lifting hand).
    For a right-dominant attacker this is `right_hand`; left-dominant mirrors.
    The check reads both the grip edge (grasper_part + grip type) and the
    body-part ContactState — ContactState is the canonical source of truth
    for "is this hand on uke's gi right now?" per Part 1.6 / 2.7.
    """
    from body_state import ContactState as _ContactState

    dom_key = (
        "right_hand" if attacker.identity.dominant_side == DominantSide.RIGHT
        else "left_hand"
    )

    # Find the GripRequirement targeting the dominant hand. If the throw's
    # force_grips doesn't name the dominant hand, nothing to modulate —
    # treat as satisfied so no penalty applies.
    dom_req: "GripRequirement | None" = None
    for req in throw.force_grips:
        if req.hand == dom_key:
            dom_req = req
            break
    if dom_req is None:
        return True

    # ContactState gate — the hand must actually be on uke. A stripped grip
    # or a reaching hand does not count as engaged.
    hand_state = attacker.state.body.get(dom_key)
    if hand_state is None or hand_state.contact_state != _ContactState.GRIPPING_UKE:
        return False

    # Edge-level gate — there must be an edge from the dominant hand whose
    # grip_type_v2 is one of the accepted types for the requirement. Depth
    # and mode are intentionally NOT checked here: the modulator asks the
    # narrower question "is the hand in play on the right kind of grip?"
    # — depth and mode already inform the base grip_score above.
    for edge in attacker_edges:
        if edge.grasper_part.value != dom_key:
            continue
        if edge.grip_type_v2 in dom_req.grip_type:
            return True
    return False


def _uke_has_no_grips(defender: "Judoka", graph: "GripGraph") -> bool:
    """True when uke currently owns zero grip edges on tori. Reads the grip
    graph rather than uke's hand ContactStates so it agrees with the edge
    list the rest of the signature machinery reads from.
    """
    return not graph.edges_owned_by(defender.identity.name)


def _grip_requirement_met(
    req: GripRequirement, attacker_edges: list["GripEdge"],
) -> bool:
    return _matching_edge(req, attacker_edges) is not None


def _matching_edge(
    req: GripRequirement, attacker_edges: list["GripEdge"],
) -> "GripEdge | None":
    for e in attacker_edges:
        if e.grasper_part.value != req.hand:
            continue
        if e.grip_type_v2 not in req.grip_type:
            continue
        if not _depth_at_least(e.depth_level, req.min_depth):
            continue
        if req.mode is not None and e.mode != req.mode:
            continue
        return e
    return None


# ---------------------------------------------------------------------------
# DIMENSION 3 — BODY PARTS (Part 4.2 dimension 3)
# ---------------------------------------------------------------------------
def match_body_parts(
    throw: ThrowTemplate, attacker: "Judoka", defender: "Judoka",
) -> float:
    """Score tori's body-part engagement against the throw template.

    Couple body-parts:  tori's supporting foot is PLANTED ∧ attacking limb is
                        healthy ∧ (if timing_window set) uke's target foot
                        weight_fraction inside window.
    Lever body-parts:   support configuration matches ∧ fulcrum geometry
                        matches (tori's hips below uke's hips by ≥ offset).
    """
    if throw.classification == ThrowClassification.COUPLE:
        return _match_couple_body_parts(
            throw.body_part_requirement, attacker, defender
        )
    return _match_lever_body_parts(
        throw.body_part_requirement, attacker, defender
    )


def _match_couple_body_parts(
    req: CoupleBodyPartRequirement, attacker: "Judoka", defender: "Judoka",
) -> float:
    from body_state import FootContactState
    checks: list[float] = []

    # Tori's supporting foot must be planted.
    foot_state = (
        attacker.state.body_state.foot_state_left
        if req.tori_supporting_foot == "left_foot"
        else attacker.state.body_state.foot_state_right
    )
    checks.append(1.0 if foot_state.contact_state == FootContactState.PLANTED else 0.0)

    # Attacking limb must be healthy enough to deliver (>30% effective output).
    limb_key = req.tori_attacking_limb.replace("_leg", "_leg")
    effective = attacker.effective_body_part(limb_key)
    checks.append(1.0 if effective >= 3.0 else effective / 3.0)

    # Timing-window variant (Part 4.6): uke's target foot weight fraction must
    # lie inside the specified range. Spec 4.6: "signature match plummets
    # outside the timing window regardless of other dimensions" — so outside
    # the window, the body-parts dimension hard-zeros.
    if req.timing_window is not None:
        tw = req.timing_window
        target_foot_state = (
            defender.state.body_state.foot_state_left
            if tw.target_foot == "left_foot"
            else defender.state.body_state.foot_state_right
        )
        lo, hi = tw.weight_fraction_range
        if not (lo <= target_foot_state.weight_fraction <= hi):
            return 0.0
        checks.append(1.0)

    # Part 5.2 / HAJ-55 — continuous contact-point and torso-closure quality.
    # These never gate the body-parts dimension to zero; they modulate it so
    # a heel-to-calf arm's-length execution produces a low-but-non-zero
    # body-parts score, which in turn lowers execution_quality downstream.
    if req.contact_quality is not None:
        closure_q, reaping_q = _contact_quality_scores(
            req.contact_quality, attacker, defender,
        )
        checks.append(closure_q)
        checks.append(reaping_q)

    score = sum(checks) / len(checks) if checks else 0.0

    # HAJ-59 — hip engagement on non-hip Couple throws dilutes the body-
    # parts dimension multiplicatively. The throw still fires (score > 0);
    # signature drops, eq drops downstream.
    if req.hip_engagement is not None:
        score *= _hip_engagement_multiplier(req.hip_engagement, attacker)
    return score


def _contact_quality_scores(
    profile, attacker: "Judoka", defender: "Judoka",
) -> tuple[float, float]:
    """Derive (torso_closure_quality, reaping_leg_contact_quality) in [0,1]
    from horizontal CoM-to-CoM distance at kake.

    Both are linear: 1.0 at ≤ ideal, 0.0 at ≥ max, linear in between. The
    two thresholds differ — reaping-contact quality falls off over a wider
    range than closure quality because tori's extended leg can reach the
    thigh from a bit further than chest-to-chest closure allows.
    """
    ax, ay = attacker.state.body_state.com_position
    dx, dy = defender.state.body_state.com_position
    dist = hypot(dx - ax, dy - ay)
    closure_q = _linear_falloff(
        dist, profile.ideal_torso_closure_m, profile.max_torso_closure_m,
    )
    reaping_q = _linear_falloff(
        dist, profile.ideal_reaping_contact_m, profile.max_reaping_contact_m,
    )
    return closure_q, reaping_q


def _linear_falloff(value: float, ideal: float, maximum: float) -> float:
    """1.0 at value ≤ ideal; 0.0 at value ≥ maximum; linear in between."""
    if value <= ideal:
        return 1.0
    if value >= maximum:
        return 0.0
    span = maximum - ideal
    if span <= 1e-9:
        return 0.0
    return 1.0 - (value - ideal) / span


def _hip_engagement_multiplier(profile, attacker: "Judoka") -> float:
    """Part 5 / HAJ-59 — multiplier applied to body-parts score when a
    non-hip throw is being executed with hip engagement.

    Proxy: tori's `trunk_sagittal` at kake. Clean execution keeps trunk
    near-vertical (hips back); hip engagement means tori has bent forward
    from the waist to drive hip contact into uke. Returns 1.0 below the
    clean threshold, linearly falls to `engaged_floor` at the full-
    engagement angle. Never returns below `engaged_floor` — the throw
    always fires; only quality is penalized.
    """
    trunk = attacker.state.body_state.trunk_sagittal
    clean = profile.clean_trunk_sagittal_rad
    engaged = profile.engaged_trunk_sagittal_rad
    floor = profile.engaged_floor
    if trunk <= clean:
        return 1.0
    if trunk >= engaged:
        return floor
    span = engaged - clean
    if span <= 1e-9:
        return floor
    t = (trunk - clean) / span
    return 1.0 - (1.0 - floor) * t


def _match_lever_body_parts(
    req: LeverBodyPartRequirement, attacker: "Judoka", defender: "Judoka",
) -> float:
    from body_state import FootContactState

    # Fulcrum-geometry hard gate (spec 5.3): "Critical constraint — tori's
    # hips MUST be below uke's hips." Per Gutiérrez-Santiago (2013) this is
    # the #1 failure mode for Seoi-nage. If the offset isn't met, the Lever
    # body-parts dimension plummets to zero regardless of support config.
    tori_h = attacker.state.body_state.com_height
    uke_h  = defender.state.body_state.com_height
    offset = uke_h - tori_h
    if req.fulcrum_offset_below_uke_com_m > 0.0:
        if offset < req.fulcrum_offset_below_uke_com_m:
            return 0.0
        fulcrum_score = 1.0
    else:
        fulcrum_score = 1.0 if offset >= 0.0 else 0.0

    # Support configuration.
    left_planted  = attacker.state.body_state.foot_state_left.contact_state  == FootContactState.PLANTED
    right_planted = attacker.state.body_state.foot_state_right.contact_state == FootContactState.PLANTED
    if req.tori_supporting_feet == SupportRequirement.DOUBLE_SUPPORT:
        support_score = 1.0 if (left_planted and right_planted) else 0.0
    elif req.tori_supporting_feet == SupportRequirement.SINGLE_SUPPORT:
        support_score = 1.0 if (left_planted ^ right_planted) else 0.0
    else:
        # Knee-down variants — we can't yet distinguish kneeling from standing
        # in BodyState v1. Treat as "not standing double support" for now and
        # credit the geometry check if at least one foot/knee is bearing load.
        support_score = 1.0 if (left_planted or right_planted) else 0.5

    score = 0.5 * (support_score + fulcrum_score)
    # HAJ-59 — hip engagement on non-hip Lever throws (Tai-otoshi etc.)
    # collapses the body-parts dimension multiplicatively.
    if req.hip_engagement is not None:
        score *= _hip_engagement_multiplier(req.hip_engagement, attacker)
    return score


# ---------------------------------------------------------------------------
# DIMENSION 4 — UKE POSTURE (Part 4.2 dimension 4)
# ---------------------------------------------------------------------------
def match_uke_posture(
    throw: ThrowTemplate, defender: "Judoka",
) -> float:
    """Score uke's trunk angles, CoM height, and base state against the throw.

    Each sub-check returns 1.0 inside the allowed range and 0.0 outside.
    Scores are averaged across sub-checks.
    """
    req: UkePostureRequirement = throw.uke_posture_requirement
    state = defender.state.body_state

    checks: list[float] = []
    checks.append(1.0 if _in_range(state.trunk_sagittal, req.trunk_sagittal_range) else 0.0)
    checks.append(1.0 if _in_range(state.trunk_frontal,  req.trunk_frontal_range)  else 0.0)
    checks.append(1.0 if _in_range(state.com_height,     req.com_height_range)     else 0.0)
    return sum(checks) / len(checks)


# ---------------------------------------------------------------------------
# COMPOSED SIGNATURE MATCH (Part 4.2)
# ---------------------------------------------------------------------------
def signature_match(
    throw: ThrowTemplate,
    attacker: "Judoka",
    defender: "Judoka",
    graph: "GripGraph",
    weights: SignatureWeights | None = None,
    current_tick: int = 0,
) -> float:
    """The weighted four-dimension actual_match score in [0.0, 1.0].

    Weights default to the classification's canonical weighting (Part 4.2);
    pass `weights` to override for experiments.

    Two hard gates override the weighted sum and force the signature to zero:
      - Couple with timing_window, outside the window (spec 4.6): "match
        plummets regardless of other dimensions."
      - Lever with fulcrum-offset constraint, tori's hips above uke's (spec
        5.3): "tori's hips MUST be below uke's hips."
    Both are enforced inside the body-parts match function, which returns
    exactly 0.0 in those cases — we propagate that to the full signature.
    """
    w = weights or throw.signature_weights()
    b = match_body_parts(throw, attacker, defender)
    if b == 0.0 and _has_hard_body_gate(throw):
        return 0.0
    k = match_kuzushi_vector(throw, attacker, defender, current_tick=current_tick)
    f = match_force_application(throw, attacker, defender, graph)
    p = match_uke_posture(throw, defender)
    score = w.kuzushi * k + w.force * f + w.body * b + w.posture * p
    # Floating-point hygiene at the boundaries.
    return max(0.0, min(1.0, score))


def _has_hard_body_gate(throw: ThrowTemplate) -> bool:
    """True when the template's body-parts requirement carries a hard gate
    (timing window for Couple; fulcrum-offset constraint for Lever) that
    should short-circuit the full signature to zero when unmet.
    """
    if throw.classification == ThrowClassification.COUPLE:
        return throw.body_part_requirement.timing_window is not None
    return throw.body_part_requirement.fulcrum_offset_below_uke_com_m > 0.0
