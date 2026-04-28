# recognition.py
# HAJ-144 acceptance #5 + #6 — recognition mechanic, computed not declared,
# runs after commit only.
#
# A throw setup is fluid until it commits — what reads as an O-soto entry
# can become a Ko-soto-gari counter, a Tani-otoshi sacrifice, or a quick
# switch to Uchi-mata as the body adapts to uke's defensive read.
# Pre-commit anticipation would burn the prose layer with announcer calls
# that retroactively turn out wrong. The post-commit-only rule is design,
# not optimization: real announcers do call throws early and sometimes
# get them wrong; the design choice is to err on the side of the prose
# layer never getting burned. Body-part prose still describes in-progress
# motion at all altitudes that render it; what waits for commit is the
# *naming*.
#
# A recognition score in [0, 1] expresses how cleanly an in-flight throw
# matches a known signature. v0.1 reads four signature elements off the
# committed worked-throw template:
#
#   1. KUZUSHI_VECTOR — does uke's compromised state align with the
#      kuzushi requirement direction?
#   2. GRIPS_PRESENT — are both the hikite and tsurite force-grips seated
#      at or above min_depth?
#   3. CONTACT_LIMB — is tori's attacking limb / fulcrum positioned per
#      the body-part requirement?
#   4. POSTURE_BREAK — is uke's posture broken in a direction matching
#      the kuzushi vector?
#
# Each element is a boolean / float, summed and normalized. The score
# feeds significance scoring (HAJ-144 #1) and feeds whether the technique
# name surfaces (HAJ-144 #6 / acceptance criteria for the prose layer).
#
# Threshold conventions used by altitude readers (per HAJ-144 part D):
#   - all_clean       (>= 0.85): name lands at score with announcer flourish
#   - most_clean      (>= 0.65): name lands at score
#   - some_clean      (>= 0.40): no technique name, body-part prose only
#   - few_clean       (<  0.40): no technique name, generic "tori threw uke down"

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Optional

from enums import Posture
from throws import ThrowID

if TYPE_CHECKING:
    from judoka import Judoka
    from grip_graph import GripGraph
    from throw_templates import ThrowTemplate


# ---------------------------------------------------------------------------
# RECOGNITION THRESHOLDS — what the prose layer reads to decide "name it".
# ---------------------------------------------------------------------------
RECOGNITION_ALL_CLEAN:  float = 0.85
RECOGNITION_MOST_CLEAN: float = 0.65
RECOGNITION_SOME_CLEAN: float = 0.40


def recognition_score(
    template: "ThrowTemplate",
    attacker: "Judoka",
    defender: "Judoka",
    grip_graph: "GripGraph",
    current_tick: int,
) -> float:
    """Score how cleanly the in-flight throw matches its template
    signature. Result in [0, 1]. Runs *after* commit (the caller is
    expected to be the commit-resolution path in match.py); pre-commit
    callers would violate the design (HAJ-144 part D rule)."""
    elements: list[float] = []

    # 1. Grips present at minimum depth, in the right mode.
    elements.append(_grip_element(template, attacker, grip_graph))

    # 2. Kuzushi vector aligned.
    elements.append(_kuzushi_element(template, defender, current_tick))

    # 3. Posture broken in the right direction.
    elements.append(_posture_element(template, defender))

    # 4. Contact / fulcrum geometry — v0.1 collapses to a binary
    #    "did the body-part requirement's contact_limb name a non-empty
    #    field?" since the full geometric check requires position state
    #    we'd need to thread through. The signature is sufficient for the
    #    naming decision; deeper geometry is HAJ-148+.
    elements.append(_contact_element(template))

    # Equal-weight average. v0.1 calibration target — unequal weights
    # could highlight the kuzushi-vector mismatch more strongly.
    return sum(elements) / max(1, len(elements))


def recognition_band(score: float) -> str:
    """Map a recognition score onto a coarse band the prose layer reads.
    Returns one of "all_clean" / "most_clean" / "some_clean" / "few_clean"."""
    if score >= RECOGNITION_ALL_CLEAN:
        return "all_clean"
    if score >= RECOGNITION_MOST_CLEAN:
        return "most_clean"
    if score >= RECOGNITION_SOME_CLEAN:
        return "some_clean"
    return "few_clean"


def name_lands_at(band: str) -> bool:
    """Per HAJ-144 part D: technique name surfaces at the score line for
    `most_clean` and above; below that, only body-part prose (no name)."""
    return band in ("all_clean", "most_clean")


# ===========================================================================
# ELEMENT-LEVEL SCORERS
# ===========================================================================

def _grip_element(
    template: "ThrowTemplate", attacker: "Judoka", grip_graph: "GripGraph",
) -> float:
    """Return [0, 1] — fraction of force_grips on the template that are
    actually seated at min_depth-or-better on `attacker`'s side."""
    grips = template.force_grips
    if not grips:
        return 1.0
    seated = 0
    for req in grips:
        for edge in grip_graph.edges_owned_by(attacker.identity.name):
            if edge.grasper_part.value != req.hand:
                continue
            if edge.grip_type_v2 not in req.grip_type:
                continue
            if edge.depth_level.modifier() < req.min_depth.modifier():
                continue
            seated += 1
            break
    return seated / len(grips)


def _kuzushi_element(
    template: "ThrowTemplate", defender: "Judoka", current_tick: int,
) -> float:
    """Compare uke's accumulated kuzushi state vector to the template's
    requirement direction. Returns [0, 1] based on cosine similarity."""
    from kuzushi import compromised_state
    state = compromised_state(defender.kuzushi_events, current_tick)
    if state.magnitude < 1e-3:
        return 0.0
    rx, ry = template.kuzushi_requirement.direction
    rmag = math.hypot(rx, ry)
    if rmag < 1e-6:
        return 0.0
    rx, ry = rx / rmag, ry / rmag
    sx, sy = state.vector
    smag = math.hypot(sx, sy)
    if smag < 1e-6:
        return 0.0
    sx, sy = sx / smag, sy / smag
    cos = max(-1.0, min(1.0, rx * sx + ry * sy))
    # Map [-1, 1] cosine onto [0, 1] — opposed directions score 0,
    # aligned directions score 1.
    return (cos + 1.0) / 2.0


def _posture_element(template: "ThrowTemplate", defender: "Judoka") -> float:
    """A broken posture matches if uke's posture state is BROKEN.
    Slightly-bent counts as a half-match; UPRIGHT is 0. Posture is
    derived continuously from trunk angles by body_state.derive_posture()."""
    from body_state import derive_posture
    bs = defender.state.body_state
    p = derive_posture(bs.trunk_sagittal, bs.trunk_frontal)
    if p == Posture.BROKEN:
        return 1.0
    if p == Posture.SLIGHTLY_BENT:
        return 0.5
    return 0.0


def _contact_element(template: "ThrowTemplate") -> float:
    """v0.1 — fixed 0.7 floor for templates that declare a body-part
    requirement (every worked throw does). Real geometric check is
    HAJ-148+ work; the substrate is sufficient for the naming decision."""
    # Both Couple and Lever templates declare body_part_requirement.
    # If the attribute exists and is populated, the contact element is
    # at least neutral.
    if getattr(template, "body_part_requirement", None) is not None:
        return 0.7
    return 0.0


def recognized_name(
    template: "ThrowTemplate", score: float,
) -> Optional[str]:
    """Return the canonical throw name iff the recognition band is high
    enough for the name to surface; otherwise None. Per HAJ-144 part D
    the name appears at score time only when recognition is `most_clean`
    or `all_clean`."""
    if name_lands_at(recognition_band(score)):
        return template.name
    return None
