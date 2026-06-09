# tests/test_cross_grip.py
# HAJ-238 Phase 2 — cross-grip + pistol cascade seating (kenka-yotsu).
#
# Covers the grip-target election (cross_grip.select_lead_grip /
# select_defensive_frame / lead_grip_placement), its wiring into the grip
# cascade (Match._seat_grips_for / _apply_engaged_response), and the four
# acceptance behaviors: CROSS/PISTOL seated in MIRRORED at a believable rate,
# the unconventional shido clock firing on an un-attacked cross, the
# disruptor + experienced-counter pair, and PISTOL's defensive-frame + sode
# offensive roles.

from __future__ import annotations
import io
import os
import random
import sys
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from body_state import place_judoka
from enums import (
    BodyArchetype, DominantSide, GripTarget, GripTypeV2, Stance, StanceMatchup,
)
from referee import build_suzuki
import main as main_module
import cross_grip as cg
from cross_grip import (
    PLAN_CROSS, PLAN_ORTHODOX, PLAN_PISTOL,
    lead_grip_placement, select_defensive_frame, select_lead_grip,
)
from stance import AXIS_KENKA_YOTSU, AXIS_ORTHODOX, AXIS_SOUTHPAW


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _pair():
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    return t, s


def _kenka_capable(j, kenka=0.9, iq=9):
    """Make a fighter fluent in the inside fight."""
    j.state.stance_comfort = {
        AXIS_ORTHODOX: 0.9, AXIS_SOUTHPAW: 0.9, AXIS_KENKA_YOTSU: kenka,
    }
    j.capability.fight_iq = iq
    return j


def _plan_rate(fighter, opp, *, matchup, pressure=0.0, facing=False, n=3000):
    from collections import Counter
    c = Counter()
    for i in range(n):
        ch = select_lead_grip(
            fighter, opp, matchup=matchup, grip_pressure=pressure,
            facing_unconventional=facing, rng=random.Random(i),
        )
        c[ch.plan] += 1
    return {k: v / n for k, v in c.items()}


# ---------------------------------------------------------------------------
# lead_grip_placement — pure target/grip resolution
# ---------------------------------------------------------------------------
def test_placement_orthodox_right_dominant():
    grip, target, hand = lead_grip_placement(PLAN_ORTHODOX, DominantSide.RIGHT)
    assert grip == GripTypeV2.LAPEL_HIGH
    assert target == GripTarget.LEFT_LAPEL   # opposite lapel tsurite
    assert hand == "right_hand"


def test_placement_cross_reaches_same_side_lapel():
    # The cross is the "wrong"-hand reach to the SAME-side lapel.
    grip, target, hand = lead_grip_placement(PLAN_CROSS, DominantSide.RIGHT)
    assert grip == GripTypeV2.CROSS
    assert target == GripTarget.RIGHT_LAPEL
    grip_l, target_l, _ = lead_grip_placement(PLAN_CROSS, DominantSide.LEFT)
    assert target_l == GripTarget.LEFT_LAPEL


def test_placement_pistol_clamps_sleeve():
    grip, target, hand = lead_grip_placement(PLAN_PISTOL, DominantSide.RIGHT)
    assert grip == GripTypeV2.PISTOL
    assert target == GripTarget.LEFT_SLEEVE


# ---------------------------------------------------------------------------
# select_lead_grip — the election
# ---------------------------------------------------------------------------
def test_matched_stance_is_always_orthodox():
    # The cross-grip game is MIRRORED-only — MATCHED never elects it.
    t, s = _pair()
    _kenka_capable(t)
    rate = _plan_rate(t, s, matchup=StanceMatchup.MATCHED)
    assert rate.get(PLAN_ORTHODOX, 0.0) == 1.0


def test_mirrored_kenka_fighter_reaches_for_cross():
    t, s = _pair()
    _kenka_capable(t)
    rate = _plan_rate(t, s, matchup=StanceMatchup.MIRRORED)
    # Orthodox stays the majority default, but the cross is a real minority.
    assert rate.get(PLAN_CROSS, 0.0) > 0.1
    assert rate.get(PLAN_ORTHODOX, 0.0) > 0.4


def test_grip_fighter_reaches_more_than_motor():
    t, s = _pair()
    gf = _kenka_capable(main_module.build_tanaka())
    gf.identity.body_archetype = BodyArchetype.GRIP_FIGHTER
    mo = _kenka_capable(main_module.build_sato())
    mo.identity.body_archetype = BodyArchetype.MOTOR
    gf_rate = _plan_rate(gf, s, matchup=StanceMatchup.MIRRORED)
    mo_rate = _plan_rate(mo, t, matchup=StanceMatchup.MIRRORED)
    assert gf_rate.get(PLAN_CROSS, 0.0) > mo_rate.get(PLAN_CROSS, 0.0)


def test_novice_does_not_cross_grip():
    # Clumsy in the stance + low IQ ⇒ no fluent cross-gripping.
    t, s = _pair()
    t.state.stance_comfort = {
        AXIS_ORTHODOX: 0.9, AXIS_SOUTHPAW: 0.05, AXIS_KENKA_YOTSU: 0.1,
    }
    t.capability.fight_iq = 2
    rate = _plan_rate(t, s, matchup=StanceMatchup.MIRRORED)
    assert rate.get(PLAN_ORTHODOX, 0.0) == 1.0


def test_disruptor_elevates_cross_under_pressure():
    # A dominated fighter reaches for the disruptor cross more than a fighter
    # under no pressure — and the cross carries the disruptor flag.
    t, s = _pair()
    _kenka_capable(t)
    calm = _plan_rate(t, s, matchup=StanceMatchup.MIRRORED, pressure=0.0)
    pressed = _plan_rate(t, s, matchup=StanceMatchup.MIRRORED, pressure=1.8)
    assert pressed.get(PLAN_CROSS, 0.0) > calm.get(PLAN_CROSS, 0.0)

    # Find a seed that elects a cross under pressure and confirm the flag.
    for i in range(2000):
        ch = select_lead_grip(
            t, s, matchup=StanceMatchup.MIRRORED, grip_pressure=1.8,
            facing_unconventional=False, rng=random.Random(i),
        )
        if ch.plan == PLAN_CROSS:
            assert ch.disruptor is True
            break
    else:
        raise AssertionError("expected at least one disruptor cross")


def test_experienced_counter_converts_back_to_preferred_grip():
    # Facing the opponent's cross, a skilled fighter routes back to orthodox
    # (converts) rather than trading cross for cross.
    t, s = _pair()
    _kenka_capable(t, kenka=0.9, iq=9)        # clearly skilled
    ch = select_lead_grip(
        t, s, matchup=StanceMatchup.MIRRORED, grip_pressure=0.0,
        facing_unconventional=True, rng=random.Random(0),
    )
    assert ch.plan == PLAN_ORTHODOX
    assert ch.converts is True


def test_unskilled_fighter_does_not_convert():
    t, s = _pair()
    # Low (iq × kenka) — gets tangled in the cross rather than routing through.
    t.state.stance_comfort = {
        AXIS_ORTHODOX: 0.9, AXIS_SOUTHPAW: 0.3, AXIS_KENKA_YOTSU: 0.25,
    }
    t.capability.fight_iq = 4
    ch = select_lead_grip(
        t, s, matchup=StanceMatchup.MIRRORED, grip_pressure=0.0,
        facing_unconventional=True, rng=random.Random(0),
    )
    assert ch.converts is False


def test_sode_player_elects_pistol():
    t, s = _pair()
    sode = _kenka_capable(main_module.build_tanaka())
    sode.identity.style_dna = {"sode_setup_tendency": 0.9}
    rate = _plan_rate(sode, s, matchup=StanceMatchup.MIRRORED)
    plain = _plan_rate(_kenka_capable(main_module.build_tanaka()), s,
                       matchup=StanceMatchup.MIRRORED)
    assert rate.get(PLAN_PISTOL, 0.0) > plain.get(PLAN_PISTOL, 0.0)
    assert rate.get(PLAN_PISTOL, 0.0) > 0.1


# ---------------------------------------------------------------------------
# select_defensive_frame — PISTOL defensive role
# ---------------------------------------------------------------------------
def test_defensive_frame_matched_is_plain_sleeve():
    t, _ = _pair()
    _kenka_capable(t)
    frames = {
        select_defensive_frame(t, matchup=StanceMatchup.MATCHED,
                               rng=random.Random(i))
        for i in range(50)
    }
    assert frames == {GripTypeV2.SLEEVE_HIGH}


def test_defensive_frame_low_comfort_is_plain_sleeve():
    t, _ = _pair()
    t.state.stance_comfort = {
        AXIS_ORTHODOX: 0.9, AXIS_SOUTHPAW: 0.1, AXIS_KENKA_YOTSU: 0.1,
    }
    frames = {
        select_defensive_frame(t, matchup=StanceMatchup.MIRRORED,
                               rng=random.Random(i))
        for i in range(50)
    }
    assert frames == {GripTypeV2.SLEEVE_HIGH}


def test_defensive_frame_kenka_capable_can_pistol():
    t, _ = _pair()
    _kenka_capable(t)
    frames = [
        select_defensive_frame(t, matchup=StanceMatchup.MIRRORED,
                               rng=random.Random(i))
        for i in range(200)
    ]
    assert GripTypeV2.PISTOL in frames        # the strip-resistant sode frame
    assert GripTypeV2.SLEEVE_HIGH in frames   # still mixes in the plain frame


# ---------------------------------------------------------------------------
# Narration helpers
# ---------------------------------------------------------------------------
def test_lead_grip_coach_prose_variants():
    disruptor = cg.LeadGripChoice(plan=PLAN_CROSS, grip_type=GripTypeV2.CROSS,
                                  disruptor=True)
    assert "disruptor" in cg.lead_grip_coach_prose("Sato", disruptor)
    fluent = cg.LeadGripChoice(plan=PLAN_CROSS, grip_type=GripTypeV2.CROSS)
    assert "cross grip" in cg.lead_grip_coach_prose("Sato", fluent)
    pistol = cg.LeadGripChoice(plan=PLAN_PISTOL, grip_type=GripTypeV2.PISTOL)
    assert "pistol" in cg.lead_grip_coach_prose("Sato", pistol).lower()
    converts = cg.LeadGripChoice(plan=PLAN_ORTHODOX,
                                 grip_type=GripTypeV2.LAPEL_HIGH, converts=True)
    assert "scramble" in cg.lead_grip_coach_prose("Sato", converts)
    orthodox = cg.LeadGripChoice(plan=PLAN_ORTHODOX,
                                 grip_type=GripTypeV2.LAPEL_HIGH)
    assert cg.lead_grip_coach_prose("Sato", orthodox) is None


# ---------------------------------------------------------------------------
# Match wiring — _seat_grips_for honors the lead plan
# ---------------------------------------------------------------------------
def _match():
    from match import Match
    t, s = _pair()
    return Match(fighter_a=t, fighter_b=s, referee=build_suzuki(),
                 max_ticks=50, seed=1), t, s


def test_seat_grips_for_seats_cross_edge():
    m, t, s = _match()
    edges = m._seat_grips_for(t, s, tick=3, hands="lead", lead_plan=PLAN_CROSS)
    assert len(edges) == 1
    assert edges[0].grip_type_v2 == GripTypeV2.CROSS
    assert edges[0].target_location == GripTarget.RIGHT_LAPEL  # right-dominant cross


def test_seat_grips_for_seats_pistol_edge():
    m, t, s = _match()
    edges = m._seat_grips_for(t, s, tick=3, hands="lead", lead_plan=PLAN_PISTOL)
    assert edges[0].grip_type_v2 == GripTypeV2.PISTOL
    assert edges[0].target_location == GripTarget.LEFT_SLEEVE


def test_seat_grips_for_defaults_to_orthodox():
    m, t, s = _match()
    edges = m._seat_grips_for(t, s, tick=3, hands="lead")
    assert edges[0].grip_type_v2 == GripTypeV2.LAPEL_HIGH


# ---------------------------------------------------------------------------
# AC#1 — stance_parity advantage expresses in compute_grip_delta
# ---------------------------------------------------------------------------
def test_cross_grip_delta_rewards_mirrored():
    m, t, s = _match()
    m._seat_grips_for(t, s, tick=1, hands="lead", lead_plan=PLAN_CROSS)
    mirrored = m.grip_graph.compute_grip_delta(t, s, StanceMatchup.MIRRORED)
    matched = m.grip_graph.compute_grip_delta(t, s, StanceMatchup.MATCHED)
    # CROSS stance_parity is 1.25 mirrored / 0.80 matched — the same edge is
    # worth more to its owner in kenka-yotsu.
    assert mirrored > matched > 0.0


# ---------------------------------------------------------------------------
# AC#2 — unconventional shido clock fires on an un-attacked cross
# ---------------------------------------------------------------------------
def test_cross_edge_runs_unconventional_clock_then_shido():
    from match import UNCONVENTIONAL_SHIDO_TICKS
    m, t, s = _match()
    (edge,) = m._seat_grips_for(t, s, tick=0, hands="lead", lead_plan=PLAN_CROSS)
    assert edge.grip_type_v2.is_unconventional()

    # The per-grip clock advances each tick the cross goes un-attacked.
    start = edge.unconventional_clock
    for tk in range(1, 4):
        m.grip_graph.tick_update(tk, t, s)
    assert edge.unconventional_clock > start

    # Once it crosses the threshold, the passivity pass queues a shido naming
    # the unconventional grip.
    edge.unconventional_clock = UNCONVENTIONAL_SHIDO_TICKS
    m._pending_penalty = None
    m._update_grip_passivity(tick=10, events=[])
    assert m._pending_penalty is not None
    assert m._pending_penalty["fighter"] is t
    assert "unconventional" in m._pending_penalty["reason"]


# ---------------------------------------------------------------------------
# AC#1/#3/#4 — end-to-end: a kenka-yotsu match actually seats CROSS/PISTOL
# ---------------------------------------------------------------------------
def _run_kenka_match(seed, max_ticks=250):
    from match import Match
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    # Force kenka-yotsu from the opening bell: Sato fights southpaw.
    s.state.base_stance = Stance.SOUTHPAW
    s.state.current_stance = Stance.SOUTHPAW
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki(),
              max_ticks=max_ticks, seed=seed)
    buf = io.StringIO()
    with redirect_stdout(buf):
        m.run()
    return buf.getvalue()


def test_mirrored_match_seats_unconventional_grips():
    seen_cross = seen_pistol = seen_kenka_prose = 0
    for seed in range(30):
        out = _run_kenka_match(seed)
        if ", CROSS @" in out:
            seen_cross += 1
        if ", PISTOL @" in out:
            seen_pistol += 1
        if "[kenka]" in out:
            seen_kenka_prose += 1
    # Across 30 kenka-yotsu matches the engine seats cross grips at a believable
    # rate, and the kenka-yotsu narration family fires.
    assert seen_cross > 0
    assert seen_pistol > 0
    assert seen_kenka_prose > 0


def test_matched_match_never_seats_cross_or_pistol():
    # A vanilla ai-yotsu match (both orthodox, no stance switch reaching
    # MIRRORED) should not seat any cross/pistol grips.
    from match import Match
    saw_unconventional = False
    for seed in range(20):
        t = main_module.build_tanaka()
        s = main_module.build_sato()
        # Pin both fighters stance-static so no switch reaches MIRRORED.
        t.state.stance_comfort = {}
        s.state.stance_comfort = {}
        place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
        place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
        m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki(),
                  max_ticks=200, seed=seed)
        buf = io.StringIO()
        with redirect_stdout(buf):
            m.run()
        out = buf.getvalue()
        if ", CROSS @" in out or ", PISTOL @" in out:
            saw_unconventional = True
            break
    assert saw_unconventional is False
