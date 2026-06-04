# tests/test_haj224_grip_strip_calibration.py
# HAJ-224 — grip strip calibration. Covers the two calibration changes not
# already pinned by test_grips.py's apply_strip_pressure margin tests:
#
#   2. Universal baseline strip — every archetype carries a non-zero strip
#      propensity from the driving rung; GRIP_FIGHTER rolls it most often.
#   3. Single-hand first grip — at engagement the leader seats one grip
#      (dominant-hand lapel); the off-hand sleeve grip follows a later tick.

from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from body_state import place_judoka
from enums import BodyArchetype, BodyPart, GripTarget, GripTypeV2, GripDepth, Position
from grip_graph import GripEdge
from actions import ActionKind
from referee import build_suzuki
from match import Match, OFF_HAND_SEAT_LAG_TICKS, ENGAGEMENT_GRIP_SEAT_TICKS_MAX
import action_selection
import main as main_module


class _FixedRandom:
    """Minimal rng stub: random() always returns a fixed value."""
    def __init__(self, val: float) -> None:
        self.val = val

    def random(self) -> float:
        return self.val


def _opp_lapel_edge(owner_name: str, depth: GripDepth) -> GripEdge:
    return GripEdge(
        grasper_id=owner_name,
        grasper_part=BodyPart.RIGHT_HAND,
        target_id="x",
        target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH,
        depth_level=depth,
        strength=0.8,
        established_tick=0,
    )


# ---------------------------------------------------------------------------
# Change 2 — universal baseline strip propensity
# ---------------------------------------------------------------------------
def test_every_archetype_has_nonzero_strip_propensity() -> None:
    j = main_module.build_tanaka()
    for arch in BodyArchetype:
        j.identity.body_archetype = arch
        assert action_selection._strip_propensity(j) > 0.0, arch


def test_grip_fighter_strips_more_often_than_lever_and_motor() -> None:
    # Same fighter, same aggression — only the archetype differs, so the
    # propensity ordering reflects the archetype weighting alone.
    j = main_module.build_tanaka()

    j.identity.body_archetype = BodyArchetype.GRIP_FIGHTER
    grip_fighter = action_selection._strip_propensity(j)
    j.identity.body_archetype = BodyArchetype.LEVER
    lever = action_selection._strip_propensity(j)
    j.identity.body_archetype = BodyArchetype.MOTOR
    motor = action_selection._strip_propensity(j)

    assert grip_fighter > lever
    assert grip_fighter > motor


def test_maybe_emit_strip_fires_and_targets_deepest_opp_edge() -> None:
    j = main_module.build_tanaka()  # fresh — both hands free
    place_judoka(j, com_position=(0.0, 0.0), facing=(1.0, 0.0))
    shallow = _opp_lapel_edge("opp", GripDepth.POCKET)
    deep = _opp_lapel_edge("opp", GripDepth.DEEP)
    # A roll of 0.0 is below any propensity → fires.
    action = action_selection._maybe_emit_strip(
        j, [shallow, deep], _FixedRandom(0.0),
    )
    assert action is not None
    assert action.kind == ActionKind.STRIP
    assert action.edge is deep  # strongest (deepest) grip is targeted


def test_maybe_emit_strip_respects_propensity_roll() -> None:
    j = main_module.build_tanaka()
    place_judoka(j, com_position=(0.0, 0.0), facing=(1.0, 0.0))
    edge = _opp_lapel_edge("opp", GripDepth.STANDARD)
    # A roll of 0.99 exceeds every archetype's propensity → no strip.
    assert action_selection._maybe_emit_strip(j, [edge], _FixedRandom(0.99)) is None
    # No opponent edges → never strips regardless of roll.
    assert action_selection._maybe_emit_strip(j, [], _FixedRandom(0.0)) is None


# ---------------------------------------------------------------------------
# Change 3 — single-hand first grip
# ---------------------------------------------------------------------------
def _pair_match(seed: int = 7):
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki(), seed=seed)
    return t, s, m


def test_leader_seats_single_lead_grip_at_engagement() -> None:
    """At the staging tick the leader owns exactly one grip — the
    dominant-hand lapel — not an atomic two-handed grip."""
    _, _, m = _pair_match()
    m.begin()
    for _ in range(ENGAGEMENT_GRIP_SEAT_TICKS_MAX + 2):
        m.step()
        if m.grip_graph.edge_count() > 0:
            break
    assert m.grip_graph.edge_count() == 1
    lead = m.grip_graph.edges[0]
    assert lead.grip_type_v2 == GripTypeV2.LAPEL_HIGH
    # A second beat is scheduled for the off-hand.
    assert m._pending_off_hand is not None
    assert m._pending_off_hand["leader_name"] == lead.grasper_id


def test_leader_off_hand_follows_on_a_later_tick() -> None:
    """The leader's off-hand sleeve grip seats OFF_HAND_SEAT_LAG_TICKS after
    the lead grip — a second beat, not the same tick."""
    _, _, m = _pair_match()
    m.begin()
    for _ in range(ENGAGEMENT_GRIP_SEAT_TICKS_MAX + 2):
        m.step()
        if m.grip_graph.edge_count() > 0:
            break
    lead = m.grip_graph.edges[0]
    leader_name = lead.grasper_id
    # The off-hand must not be present yet.
    leader_edges = m.grip_graph.edges_owned_by(leader_name)
    assert not any(e.grip_type_v2 == GripTypeV2.SLEEVE_HIGH for e in leader_edges)
    # Walk past the off-hand lag; the sleeve grip should appear.
    for _ in range(OFF_HAND_SEAT_LAG_TICKS + 2):
        m.step()
        leader_edges = m.grip_graph.edges_owned_by(leader_name)
        if any(e.grip_type_v2 == GripTypeV2.SLEEVE_HIGH for e in leader_edges):
            break
    leader_edges = m.grip_graph.edges_owned_by(leader_name)
    assert any(e.grip_type_v2 == GripTypeV2.SLEEVE_HIGH for e in leader_edges)
