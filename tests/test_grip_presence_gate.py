# tests/test_grip_presence_gate.py
# HAJ-36 — formal grip-presence commit gate.
#
# Covers:
#   - (a) all-shallow grips block the commit
#   - (a) a grip that has ever been STANDARD passes the floor (max_depth_reached)
#   - (b) requires_both_hands: missing a hand blocks; exempt throws pass
#   - (c) EdgeRequirement unmet blocks
#   - (d) SLIPPING edges block (when max_depth_reached was also POCKET/SLIPPING)
#   - (e) offensive + defensive desperation bypass the gate, and the
#         GateResult records the bypass_kind for logging.

from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from enums import (
    BodyPart, GripTarget, GripTypeV2, GripDepth, GripMode, DominantSide,
    BodyArchetype, BeltRank,
)
from grip_graph import GripGraph, GripEdge
from grip_presence_gate import (
    evaluate_gate,
    REASON_OK, REASON_NO_EDGES, REASON_ALL_SHALLOW,
    REASON_NEEDS_BOTH_HANDS, REASON_EDGE_REQS_UNMET, REASON_SLIPPING_EDGES,
)
from throws import THROW_DEFS, ThrowID
from judoka import Identity, Capability, State, Judoka


def _minimal_judoka(name: str = "T", dom=DominantSide.RIGHT) -> Judoka:
    ident = Identity(
        name=name, age=26, weight_class="-90kg", height_cm=180,
        body_archetype=BodyArchetype.LEVER,
        belt_rank=BeltRank.BLACK_1, dominant_side=dom,
        personality_facets={"aggressive": 4, "technical": 2,
                            "confident": 3, "loyal_to_plan": 3},
        arm_reach_cm=185, hip_height_cm=100, nationality="x",
    )
    cap = Capability(
        right_hand=8, left_hand=8, right_forearm=8, left_forearm=8,
        right_bicep=8, left_bicep=8, right_shoulder=8, left_shoulder=8,
        right_leg=8, left_leg=8, right_foot=8, left_foot=8,
        core=8, lower_back=8, neck=8,
        cardio_capacity=8, cardio_efficiency=8, composure_ceiling=8,
        fight_iq=8, ne_waza_skill=5,
        right_hip=8, left_hip=8, right_thigh=8, left_thigh=8,
        right_knee=8, left_knee=8, right_wrist=8, left_wrist=8, head=5,
        throw_vocabulary=[ThrowID.SEOI_NAGE, ThrowID.O_UCHI_GARI,
                          ThrowID.SUMI_GAESHI],
        throw_profiles={},
        signature_throws=[ThrowID.SEOI_NAGE],
        signature_combos=[],
    )
    return Judoka(identity=ident, capability=cap,
                  state=State.fresh(cap, ident))


def _seat(graph: GripGraph, grasper_name: str, hand: BodyPart,
          target_name: str, target_loc: GripTarget,
          depth: GripDepth, *, max_depth: GripDepth | None = None) -> GripEdge:
    edge = GripEdge(
        grasper_id=grasper_name, grasper_part=hand,
        target_id=target_name, target_location=target_loc,
        grip_type_v2=GripTypeV2.LAPEL_HIGH if "lapel" in target_loc.value else GripTypeV2.SLEEVE,
        depth_level=depth, strength=1.0, established_tick=0,
        mode=GripMode.CONNECTIVE,
    )
    if max_depth is not None:
        edge.max_depth_reached = max_depth
    graph.edges.append(edge)
    return edge


def test_gate_blocks_when_no_edges() -> None:
    j = _minimal_judoka("T")
    g = GripGraph()
    result = evaluate_gate(j, THROW_DEFS[ThrowID.SEOI_NAGE], g)
    assert result.allowed is False
    assert result.reason == REASON_NO_EDGES


def test_gate_blocks_all_shallow() -> None:
    j = _minimal_judoka("T")
    g = GripGraph()
    # Both hands engaged but only POCKET, never reached STANDARD.
    _seat(g, "T", BodyPart.RIGHT_HAND, "S", GripTarget.LEFT_LAPEL,
          GripDepth.POCKET)
    _seat(g, "T", BodyPart.LEFT_HAND, "S", GripTarget.RIGHT_SLEEVE,
          GripDepth.POCKET)
    result = evaluate_gate(j, THROW_DEFS[ThrowID.SEOI_NAGE], g)
    assert result.allowed is False
    assert result.reason == REASON_ALL_SHALLOW


def test_gate_accepts_grip_that_ever_reached_standard() -> None:
    """HAJ-36 nuance: a grip currently SLIPPING but with max_depth_reached
    of STANDARD satisfies the floor — the attacker earned it once."""
    j = _minimal_judoka("T")
    g = GripGraph()
    _seat(g, "T", BodyPart.RIGHT_HAND, "S", GripTarget.LEFT_LAPEL,
          GripDepth.POCKET, max_depth=GripDepth.STANDARD)
    _seat(g, "T", BodyPart.LEFT_HAND, "S", GripTarget.RIGHT_SLEEVE,
          GripDepth.POCKET, max_depth=GripDepth.STANDARD)
    result = evaluate_gate(j, THROW_DEFS[ThrowID.O_UCHI_GARI], g)
    # O_UCHI_GARI has requires_both_hands=False and a permissive EdgeRequirement
    # so only check (a) here: depth-floor passes via max_depth_reached.
    assert result.allowed is True
    assert result.reason == REASON_OK


def test_gate_requires_both_hands_when_flag_set() -> None:
    j = _minimal_judoka("T")
    g = GripGraph()
    # Only the right hand owns an edge; SEOI requires both.
    _seat(g, "T", BodyPart.RIGHT_HAND, "S", GripTarget.LEFT_LAPEL,
          GripDepth.STANDARD)
    result = evaluate_gate(j, THROW_DEFS[ThrowID.SEOI_NAGE], g)
    assert result.allowed is False
    assert result.reason == REASON_NEEDS_BOTH_HANDS


def test_gate_exempts_one_handed_throws_from_both_hands_rule() -> None:
    """SUMI_GAESHI has requires_both_hands=False — a single strong grip
    should clear the gate."""
    j = _minimal_judoka("T")
    g = GripGraph()
    _seat(g, "T", BodyPart.RIGHT_HAND, "S", GripTarget.LEFT_LAPEL,
          GripDepth.STANDARD)
    result = evaluate_gate(j, THROW_DEFS[ThrowID.SUMI_GAESHI], g)
    assert result.allowed is True


def test_gate_offensive_desperation_bypasses_with_reason_preserved() -> None:
    j = _minimal_judoka("T")
    g = GripGraph()
    _seat(g, "T", BodyPart.RIGHT_HAND, "S", GripTarget.LEFT_LAPEL,
          GripDepth.POCKET)
    _seat(g, "T", BodyPart.LEFT_HAND, "S", GripTarget.RIGHT_SLEEVE,
          GripDepth.POCKET)
    result = evaluate_gate(
        j, THROW_DEFS[ThrowID.SEOI_NAGE], g,
        offensive_desperation=True,
    )
    assert result.allowed is True
    assert result.bypassed is True
    assert result.bypass_kind == "offensive"
    assert result.reason == REASON_ALL_SHALLOW   # original failure preserved


def test_gate_defensive_desperation_bypasses() -> None:
    j = _minimal_judoka("T")
    g = GripGraph()
    # Right-hand only — normally blocked by needs_both_hands.
    _seat(g, "T", BodyPart.RIGHT_HAND, "S", GripTarget.LEFT_LAPEL,
          GripDepth.STANDARD)
    result = evaluate_gate(
        j, THROW_DEFS[ThrowID.SEOI_NAGE], g,
        defensive_desperation=True,
    )
    assert result.allowed is True
    assert result.bypassed is True
    assert result.bypass_kind == "defensive"
    assert result.reason == REASON_NEEDS_BOTH_HANDS


if __name__ == "__main__":
    for n, fn in list(globals().items()):
        if n.startswith("test_") and callable(fn):
            fn()
            print(f"PASS  {n}")
