# tests/test_grips.py
# Verifies Part 2 of design-notes/physics-substrate.md:
#   - Force envelope relative-ordering (Part 2.3 table)
#   - GripDepth chain modifiers (Part 2.4)
#   - Reach durations scale with belt rank (Part 2.7 + Part 6.1)
#   - Engagement seats grips at POCKET and flips REACHING → GRIPPING_UKE
#   - Deterministic strip chain (Part 2.8)
#   - Kumi-kata passivity shido at 30 ticks (Part 2.6)
#   - Unconventional-grip shido at 5 ticks (Part 2.6)
#   - Mode fatigue costs (Part 2.5)
#   - Legacy GripType derivation still works for throws.py prereqs
#   - tick_update no longer randomly breaks edges (only on force-break)

from __future__ import annotations
import os
import sys
import random

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from enums import (
    GripTypeV2, GripDepth, GripMode, GripType, GripTarget, BodyPart, BeltRank,
    DominantSide,
)
from force_envelope import (
    FORCE_ENVELOPES, MODE_FATIGUE_MULTIPLIER,
    delivered_pull_force, grip_strength,
)
from grip_graph import GripGraph, GripEdge
from body_state import ContactState, place_judoka
import main as main_module


# ---------------------------------------------------------------------------
# Part 2.3 — force envelope relative ordering
# ---------------------------------------------------------------------------
def test_envelope_relative_ordering_matches_spec() -> None:
    e = FORCE_ENVELOPES
    # Sleeve pull > sleeve push (sleeves are pulled, not pushed)
    assert e[GripTypeV2.SLEEVE_HIGH].max_pull_force > e[GripTypeV2.SLEEVE_HIGH].max_push_force
    # Belt lift is category max (uchi-mata / tsurikomi lift)
    assert e[GripTypeV2.BELT].max_lift_force >= max(
        e[gt].max_lift_force for gt in GripTypeV2 if gt != GripTypeV2.BELT
    )
    # Collar rotation authority is category max (kubi-nage, koshi-guruma)
    assert e[GripTypeV2.COLLAR].rotation_authority >= max(
        e[gt].rotation_authority for gt in GripTypeV2 if gt != GripTypeV2.COLLAR
    )
    # Pistol strip resistance is category max (sleeve-cuff clamp)
    assert e[GripTypeV2.PISTOL].strip_resistance >= max(
        e[gt].strip_resistance for gt in GripTypeV2 if gt != GripTypeV2.PISTOL
    )
    # Cross strip resistance is category min (cross-grip is brittle)
    assert e[GripTypeV2.CROSS].strip_resistance <= min(
        e[gt].strip_resistance for gt in GripTypeV2 if gt != GripTypeV2.CROSS
    )


def test_depth_modifier_chain_is_monotone() -> None:
    m = GripDepth.modifier
    assert m(GripDepth.SLIPPING) < m(GripDepth.POCKET) < m(GripDepth.STANDARD) < m(GripDepth.DEEP)


def test_delivered_force_scales_with_depth() -> None:
    t = main_module.build_tanaka()
    place_judoka(t, com_position=(0.0, 0.0), facing=(1.0, 0.0))
    pocket = delivered_pull_force(GripTypeV2.SLEEVE_HIGH, GripDepth.POCKET,   t, "right_hand")
    deep   = delivered_pull_force(GripTypeV2.SLEEVE_HIGH, GripDepth.DEEP,     t, "right_hand")
    assert deep > pocket > 0.0


def test_mode_fatigue_multiplier_ordering() -> None:
    assert MODE_FATIGUE_MULTIPLIER[GripMode.CONNECTIVE] < 1.0
    assert MODE_FATIGUE_MULTIPLIER[GripMode.DRIVING]    > 1.0


# ---------------------------------------------------------------------------
# Part 2.7 — reach duration compressed by belt rank
# ---------------------------------------------------------------------------
def test_reach_ticks_scale_with_belt() -> None:
    g = GripGraph()
    t = main_module.build_tanaka()
    t.identity.belt_rank = BeltRank.WHITE
    assert g.reach_ticks_for(t) == 5
    t.identity.belt_rank = BeltRank.BLACK_1
    assert g.reach_ticks_for(t) == 1


# ---------------------------------------------------------------------------
# Engagement seats POCKET grips and flips hand contact state
# ---------------------------------------------------------------------------
def test_attempt_engagement_seats_pocket_and_flips_contact_state() -> None:
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))

    # Before engagement, mark both hands REACHING (what Match does).
    for j in (t, s):
        j.state.body["right_hand"].contact_state = ContactState.REACHING
        j.state.body["left_hand"].contact_state  = ContactState.REACHING

    g = GripGraph()
    edges = g.attempt_engagement(t, s, current_tick=5)

    assert len(edges) == 4  # two hands per fighter
    for e in edges:
        assert e.depth_level == GripDepth.POCKET
        assert e.mode == GripMode.CONNECTIVE
        assert e.unconventional_clock == 0

    # Both fighters have both hands now GRIPPING_UKE
    for j in (t, s):
        assert j.state.body["right_hand"].contact_state == ContactState.GRIPPING_UKE
        assert j.state.body["left_hand"].contact_state  == ContactState.GRIPPING_UKE


# ---------------------------------------------------------------------------
# Part 2.8 — deterministic strip chain
# ---------------------------------------------------------------------------
def test_strip_pressure_below_resistance_is_noop() -> None:
    t = main_module.build_tanaka()
    place_judoka(t, com_position=(0.0, 0.0), facing=(1.0, 0.0))
    g = GripGraph()
    edge = GripEdge(
        grasper_id=t.identity.name,
        grasper_part=BodyPart.RIGHT_HAND,
        target_id="x",
        target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.PISTOL,  # high strip resistance
        depth_level=GripDepth.DEEP,
        strength=1.0,
        established_tick=0,
    )
    g.add_edge(edge)
    result = g.apply_strip_pressure(edge, strip_force=10.0, grasper=t)
    assert result is None
    assert edge.depth_level == GripDepth.DEEP
    assert edge in g.edges


def test_strip_pressure_above_resistance_degrades_one_step() -> None:
    t = main_module.build_tanaka()
    place_judoka(t, com_position=(0.0, 0.0), facing=(1.0, 0.0))
    g = GripGraph()
    edge = GripEdge(
        grasper_id=t.identity.name,
        grasper_part=BodyPart.RIGHT_HAND,
        target_id="x",
        target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.CROSS,  # lowest strip resistance (200)
        depth_level=GripDepth.STANDARD,
        strength=1.0,
        established_tick=0,
    )
    g.add_edge(edge)
    result = g.apply_strip_pressure(edge, strip_force=10_000.0, grasper=t)
    assert result is not None
    assert result.event_type == "GRIP_DEGRADE"
    assert edge.depth_level == GripDepth.POCKET  # STANDARD → POCKET
    assert edge in g.edges


def test_strip_pressure_past_slipping_removes_edge() -> None:
    t = main_module.build_tanaka()
    place_judoka(t, com_position=(0.0, 0.0), facing=(1.0, 0.0))
    g = GripGraph()
    edge = GripEdge(
        grasper_id=t.identity.name,
        grasper_part=BodyPart.RIGHT_HAND,
        target_id="x",
        target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.CROSS,
        depth_level=GripDepth.SLIPPING,
        strength=1.0,
        established_tick=0,
    )
    g.add_edge(edge)
    t.state.body["right_hand"].contact_state = ContactState.GRIPPING_UKE
    result = g.apply_strip_pressure(edge, strip_force=10_000.0, grasper=t)
    assert result is not None
    assert result.event_type == "GRIP_STRIPPED"
    assert edge not in g.edges
    assert t.state.body["right_hand"].contact_state == ContactState.FREE


# ---------------------------------------------------------------------------
# tick_update — no more random FAILURE roll
# ---------------------------------------------------------------------------
def test_tick_update_does_not_randomly_drop_edges() -> None:
    """An idle CONNECTIVE grip on a fresh hand should never be removed by
    tick_update alone — stripping is deterministic, not stochastic.
    """
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))

    g = GripGraph()
    edge = GripEdge(
        grasper_id=t.identity.name,
        grasper_part=BodyPart.RIGHT_HAND,
        target_id=s.identity.name,
        target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH,
        depth_level=GripDepth.STANDARD,
        strength=0.8,
        established_tick=0,
    )
    g.add_edge(edge)

    random.seed(1)
    for tick in range(1, 60):
        g.tick_update(tick, t, s)
    assert edge in g.edges


def test_driving_mode_drains_hand_faster_than_connective() -> None:
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))

    g = GripGraph()
    conn = GripEdge(
        grasper_id=t.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=s.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.STANDARD,
        strength=0.8, established_tick=0, mode=GripMode.CONNECTIVE,
    )
    driv = GripEdge(
        grasper_id=t.identity.name, grasper_part=BodyPart.LEFT_HAND,
        target_id=s.identity.name, target_location=GripTarget.RIGHT_SLEEVE,
        grip_type_v2=GripTypeV2.SLEEVE_HIGH, depth_level=GripDepth.STANDARD,
        strength=0.8, established_tick=0, mode=GripMode.DRIVING,
    )
    g.add_edge(conn)
    g.add_edge(driv)

    # Fresh fatigue
    t.state.body["right_hand"].fatigue = 0.0
    t.state.body["left_hand"].fatigue  = 0.0
    for tick in range(1, 30):
        g.tick_update(tick, t, s)

    assert t.state.body["left_hand"].fatigue > t.state.body["right_hand"].fatigue


# ---------------------------------------------------------------------------
# Part 2.6 — passivity
# ---------------------------------------------------------------------------
def test_unconventional_grip_clock_ticks_under_tick_update() -> None:
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))

    g = GripGraph()
    pistol = GripEdge(
        grasper_id=t.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=s.identity.name, target_location=GripTarget.RIGHT_SLEEVE,
        grip_type_v2=GripTypeV2.PISTOL, depth_level=GripDepth.STANDARD,
        strength=0.8, established_tick=0,
    )
    sleeve = GripEdge(
        grasper_id=t.identity.name, grasper_part=BodyPart.LEFT_HAND,
        target_id=s.identity.name, target_location=GripTarget.LEFT_SLEEVE,
        grip_type_v2=GripTypeV2.SLEEVE_HIGH, depth_level=GripDepth.STANDARD,
        strength=0.8, established_tick=0,
    )
    g.add_edge(pistol)
    g.add_edge(sleeve)

    for tick in range(1, 8):
        g.tick_update(tick, t, s)

    assert pistol.unconventional_clock == 7  # ticked each call
    assert sleeve.unconventional_clock == 0  # conventional — doesn't tick


def test_register_attack_resets_unconventional_clocks() -> None:
    t = main_module.build_tanaka()
    s = main_module.build_sato()

    g = GripGraph()
    e = GripEdge(
        grasper_id=t.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=s.identity.name, target_location=GripTarget.RIGHT_SLEEVE,
        grip_type_v2=GripTypeV2.PISTOL, depth_level=GripDepth.STANDARD,
        strength=0.8, established_tick=0,
        unconventional_clock=4,
    )
    g.add_edge(e)
    g.register_attack(t.identity.name)
    assert e.unconventional_clock == 0


def test_kumi_kata_shido_issued_at_30_ticks() -> None:
    """Drive Match forward enough ticks for a grip-holding fighter to
    accrue a kumi-kata passivity shido. Bypasses the sub-loop state
    machine: we manually stash an edge and call _update_grip_passivity.
    """
    import random as _r
    _r.seed(7)
    from match import Match, KUMI_KATA_SHIDO_TICKS
    from referee import build_suzuki

    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))

    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())
    # Seat an edge owned by t so the clock advances.
    m.grip_graph.add_edge(GripEdge(
        grasper_id=t.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=s.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.STANDARD,
        strength=0.8, established_tick=0,
    ))

    before = t.state.shidos
    events: list = []
    for tick in range(1, KUMI_KATA_SHIDO_TICKS + 2):
        m._update_grip_passivity(tick, events)
    assert t.state.shidos > before
    assert any(ev.event_type == "SHIDO_AWARDED" for ev in events)


def test_unconventional_shido_issued_at_5_ticks() -> None:
    from match import Match, UNCONVENTIONAL_SHIDO_TICKS
    from referee import build_suzuki

    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))

    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())
    pistol = GripEdge(
        grasper_id=t.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=s.identity.name, target_location=GripTarget.RIGHT_SLEEVE,
        grip_type_v2=GripTypeV2.PISTOL, depth_level=GripDepth.STANDARD,
        strength=0.8, established_tick=0,
        unconventional_clock=UNCONVENTIONAL_SHIDO_TICKS,
    )
    m.grip_graph.add_edge(pistol)

    before = t.state.shidos
    events: list = []
    m._update_grip_passivity(tick=1, events=events)
    assert t.state.shidos == before + 1
    assert pistol.unconventional_clock == 0


# ---------------------------------------------------------------------------
# Legacy GripType compatibility (throws.py prereqs unaffected)
# ---------------------------------------------------------------------------
def test_legacy_grip_type_maps_deep_lapel_high_to_high_collar() -> None:
    e = GripEdge(
        grasper_id="t", grasper_part=BodyPart.RIGHT_HAND,
        target_id="s", target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.DEEP,
        strength=0.8, established_tick=0,
    )
    assert e.grip_type == GripType.HIGH_COLLAR
    assert e.depth == 1.0


def test_legacy_grip_type_maps_pocket_to_pocket() -> None:
    e = GripEdge(
        grasper_id="t", grasper_part=BodyPart.RIGHT_HAND,
        target_id="s", target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.SLEEVE_HIGH, depth_level=GripDepth.POCKET,
        strength=0.8, established_tick=0,
    )
    assert e.grip_type == GripType.POCKET


# ---------------------------------------------------------------------------
# HAJ-138 — net-zero oscillation coalescing
# ---------------------------------------------------------------------------
def test_oscillation_coalescing_drops_both_deepen_and_degrade() -> None:
    """When a tick contains both a successful DEEPEN and a degrade that
    return an edge to its pre-tick depth, neither event should appear in
    the log. Pre-fix, the GRIP_DEGRADE was dropped but the GRIP_DEEPEN
    was kept, producing 20+ ticks of asymmetric "Tanaka deepens
    LAPEL_HIGH → STANDARD" lines while nothing actually changed.
    """
    from match import Match
    from referee import build_suzuki
    from grip_graph import Event as _Event

    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())

    edge = GripEdge(
        grasper_id=t.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=s.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.POCKET,
        strength=1.0, established_tick=0,
    )
    m.grip_graph.add_edge(edge)

    pre_tick_depths = {id(edge): GripDepth.POCKET}
    events: list[_Event] = [
        _Event(tick=10, event_type="GRIP_DEEPEN",
               description="[grip] t deepens LAPEL_HIGH → STANDARD",
               data={"edge_id": id(edge), "from": "POCKET", "to": "STANDARD"}),
        _Event(tick=10, event_type="GRIP_DEGRADE",
               description="[grip] t right_hand LAPEL_HIGH → POCKET",
               data={"edge_id": id(edge)}),
    ]
    # Edge ended the tick at POCKET (pre-tick depth) — pure oscillation.
    edge.depth_level = GripDepth.POCKET

    progress = m._coalesce_grip_oscillation(events, pre_tick_depths)
    assert progress is False, "no real grip progress made"
    assert not any(ev.event_type in ("GRIP_DEEPEN", "GRIP_DEGRADE")
                   for ev in events), \
        "both oscillating events should be coalesced away"


def test_oscillation_does_not_reset_stalemate_counter() -> None:
    """Pre-fix, two fighters infinitely cancelling each other's grips
    reset the stalemate counter every tick (any DEEPEN/STRIP action
    counted as progress), so matte never fired even though nothing was
    actually changing. Post-fix, only events that survive
    `_coalesce_grip_oscillation` count as progress.
    """
    from match import Match
    from referee import build_suzuki
    from actions import deepen, strip

    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())

    fake_t_edge = GripEdge(
        grasper_id=t.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=s.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.POCKET,
        strength=1.0, established_tick=0,
    )
    fake_s_edge = GripEdge(
        grasper_id=s.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=t.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.POCKET,
        strength=1.0, established_tick=0,
    )
    m.grip_graph.add_edge(fake_t_edge)
    m.grip_graph.add_edge(fake_s_edge)

    actions_a = [deepen(fake_t_edge), strip("left_hand", fake_s_edge)]
    actions_b = [deepen(fake_s_edge), strip("left_hand", fake_t_edge)]

    m.stalemate_ticks = 5
    # Net-zero: simulate by passing net_grip_progress=False directly.
    m._update_stalemate_counter(
        actions_a, actions_b, a_kuzushi=False, b_kuzushi=False,
        net_grip_progress=False,
    )
    assert m.stalemate_ticks == 6, \
        "oscillation alone should not reset the stalemate counter"

    # Real progress (an event that survived coalescing) does reset.
    m._update_stalemate_counter(
        actions_a, actions_b, a_kuzushi=False, b_kuzushi=False,
        net_grip_progress=True,
    )
    assert m.stalemate_ticks == 0


def test_real_deepen_progress_still_emits_event() -> None:
    """Sanity: when a deepen takes an edge POCKET → STANDARD with no
    matching degrade, the event must survive coalescing — otherwise we
    silence real grip progress along with the oscillation."""
    from match import Match
    from referee import build_suzuki
    from grip_graph import Event as _Event

    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())

    edge = GripEdge(
        grasper_id=t.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=s.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.STANDARD,
        strength=1.0, established_tick=0,
    )
    m.grip_graph.add_edge(edge)

    pre_tick_depths = {id(edge): GripDepth.POCKET}
    events: list[_Event] = [
        _Event(tick=10, event_type="GRIP_DEEPEN",
               description="[grip] t deepens LAPEL_HIGH → STANDARD",
               data={"edge_id": id(edge), "from": "POCKET", "to": "STANDARD"}),
    ]
    progress = m._coalesce_grip_oscillation(events, pre_tick_depths)
    assert progress is True
    assert len(events) == 1
    assert events[0].event_type == "GRIP_DEEPEN"


# ---------------------------------------------------------------------------
# Integration — match still runs end-to-end
# ---------------------------------------------------------------------------
def test_match_still_runs_end_to_end_with_part_2_wiring() -> None:
    import random as _r
    from match import Match
    from referee import build_suzuki

    _r.seed(42)
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    Match(fighter_a=t, fighter_b=s, referee=build_suzuki()).run()


if __name__ == "__main__":
    import traceback
    passed = 0
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                passed += 1
                print(f"PASS  {name}")
            except Exception:
                failed += 1
                print(f"FAIL  {name}")
                traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
