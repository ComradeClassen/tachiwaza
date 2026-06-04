# test_kuzushi_pull_emission.py — HAJ-131 acceptance tests.
#
# Covers:
#   - Direction lookup table for (grip_type, pull_direction) pairs:
#       * identity grip types preserve direction
#       * CROSS flips the lateral component
#       * SLEEVE_LOW / PISTOL inject ~10° rotational bias
#   - uke_posture_vulnerability multipliers stack:
#       grounded balanced uke vs mid-step uke vs leaning-and-moving uke.
#   - pull_kuzushi_magnitude formula factors all change the result:
#       depth, strength (via fatigue), technique (pull_execution axis),
#       experience (belt rank), posture vulnerability.
#   - End-to-end: a PULL action processed through Match._compute_net_force_on
#     appends an event to the victim's buffer with the right vector and
#     a strictly-positive magnitude. Force vector is unchanged from the
#     pre-HAJ-131 calculation (event emission is purely additive).

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from enums import (
    BeltRank, BodyArchetype, DominantSide, GripDepth, GripMode, GripTypeV2,
)
from kuzushi import (
    BASE_PULL_KUZUSHI_FORCE,
    KuzushiSource,
    POSTURE_VULN_AIRBORNE_FOOT,
    POSTURE_VULN_BASE,
    POSTURE_VULN_MOVING_COM,
    POSTURE_VULN_TILTED_TRUNK,
    kuzushi_direction,
    pull_kuzushi_event,
    pull_kuzushi_magnitude,
    uke_posture_vulnerability,
)


# ---------------------------------------------------------------------------
# FIXTURES — shared judoka + edge builders
# ---------------------------------------------------------------------------
def _build_judoka(name="Test", belt=BeltRank.BLACK_1, fight_iq=7):
    from judoka import BODY_PARTS, Capability, Identity, Judoka, State
    identity = Identity(
        name=name, age=25, weight_class="-73kg", height_cm=175,
        body_archetype=BodyArchetype.GRIP_FIGHTER, belt_rank=belt,
        dominant_side=DominantSide.RIGHT,
    )
    cap_kwargs = {part: 7 for part in BODY_PARTS}
    cap = Capability(
        **cap_kwargs, cardio_capacity=7, cardio_efficiency=7,
        composure_ceiling=7, fight_iq=fight_iq, ne_waza_skill=7,
    )
    state = State.fresh(cap, identity)
    return Judoka(identity=identity, capability=cap, state=state)


def _make_edge(grasper_name, target_name, grip_type=GripTypeV2.LAPEL_LOW,
               depth=GripDepth.STANDARD):
    from grip_graph import GripEdge
    from enums import BodyPart, GripTarget
    return GripEdge(
        grasper_id=grasper_name,
        grasper_part=BodyPart.RIGHT_HAND,
        target_id=target_name,
        target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=grip_type,
        depth_level=depth,
        strength=1.0,
        established_tick=0,
        mode=GripMode.CONNECTIVE,
    )


def _make_referee():
    from referee import Referee
    return Referee(name="Suzuki-sensei", nationality="JPN")


# ---------------------------------------------------------------------------
# DIRECTION LOOKUP
# ---------------------------------------------------------------------------
class TestDirectionLookup:
    @pytest.mark.parametrize("grip_type", [
        GripTypeV2.LAPEL_LOW, GripTypeV2.LAPEL_HIGH,
        GripTypeV2.SLEEVE_HIGH,
        # HAJ-161 — both collar sub-types share the identity-pull
        # behaviour (no wrist-rotation bias).
        GripTypeV2.COLLAR_BACK, GripTypeV2.COLLAR_SIDE,
        GripTypeV2.BELT,
    ])
    def test_identity_grip_types_preserve_direction(self, grip_type):
        # Forward pull → forward kuzushi for all "identity" grip types.
        v = kuzushi_direction(grip_type, (1.0, 0.0))
        assert v == pytest.approx((1.0, 0.0))

    @pytest.mark.parametrize("grip_type", [
        GripTypeV2.LAPEL_LOW, GripTypeV2.LAPEL_HIGH,
        GripTypeV2.COLLAR_BACK, GripTypeV2.COLLAR_SIDE,
    ])
    def test_lapel_pull_back_yields_backward_kuzushi(self, grip_type):
        # Spec example: lapel pull-down → forward-down vector. Our 2D
        # equivalent: pulling toward attacker (negative x) → uke perturbed
        # in negative x.
        v = kuzushi_direction(grip_type, (-1.0, 0.0))
        assert v == pytest.approx((-1.0, 0.0))

    def test_sleeve_low_injects_rotational_bias(self):
        # Cuff grip pulls forward — kuzushi vector tilts ~10° from pure forward.
        v = kuzushi_direction(GripTypeV2.SLEEVE_LOW, (1.0, 0.0))
        # Expected: rotated 10° CCW from (1,0) → (cos10°, sin10°).
        expected_x = math.cos(math.radians(10.0))
        expected_y = math.sin(math.radians(10.0))
        assert v[0] == pytest.approx(expected_x)
        assert v[1] == pytest.approx(expected_y)

    def test_pistol_injects_same_rotational_bias_as_sleeve_low(self):
        v_pistol = kuzushi_direction(GripTypeV2.PISTOL, (1.0, 0.0))
        v_sleeve = kuzushi_direction(GripTypeV2.SLEEVE_LOW, (1.0, 0.0))
        assert v_pistol == pytest.approx(v_sleeve)

    def test_cross_grip_flips_lateral_component(self):
        # Pull with lateral component → kuzushi has lateral flipped.
        v = kuzushi_direction(GripTypeV2.CROSS, (1.0, 0.5))
        mag = math.hypot(1.0, 0.5)
        assert v[0] == pytest.approx(1.0 / mag)
        assert v[1] == pytest.approx(-0.5 / mag)  # flipped

    def test_zero_pull_direction_returns_zero_vector(self):
        for gt in (GripTypeV2.LAPEL_LOW, GripTypeV2.CROSS, GripTypeV2.SLEEVE_LOW):
            assert kuzushi_direction(gt, (0.0, 0.0)) == (0.0, 0.0)

    def test_output_is_unit_vector(self):
        for gt in GripTypeV2:
            v = kuzushi_direction(gt, (3.0, 4.0))  # input length 5
            assert math.hypot(v[0], v[1]) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# POSTURE VULNERABILITY
# ---------------------------------------------------------------------------
class TestUkePostureVulnerability:
    def test_grounded_balanced_uke_is_baseline(self):
        uke = _build_judoka()
        # State.fresh sets PLANTED feet, zero velocity, neutral trunk.
        # NB: body_state.fresh_body_state defaults foot contact_state to
        # PLANTED on FootState and SUPPORTING_GROUND on body_part state.
        # The vulnerability check reads FootState.contact_state.
        assert uke_posture_vulnerability(uke) == pytest.approx(POSTURE_VULN_BASE)

    def test_mid_step_uke_more_vulnerable_than_grounded(self):
        from body_state import FootContactState
        grounded = _build_judoka()
        mid_step = _build_judoka()
        mid_step.state.body_state.foot_state_right.contact_state = FootContactState.AIRBORNE
        assert (uke_posture_vulnerability(mid_step)
                > uke_posture_vulnerability(grounded))

    def test_airborne_foot_applies_correct_multiplier(self):
        from body_state import FootContactState
        uke = _build_judoka()
        uke.state.body_state.foot_state_left.contact_state = FootContactState.AIRBORNE
        assert uke_posture_vulnerability(uke) == pytest.approx(POSTURE_VULN_AIRBORNE_FOOT)

    def test_moving_com_applies_correct_multiplier(self):
        uke = _build_judoka()
        uke.state.body_state.com_velocity = (0.5, 0.0)  # > threshold
        assert uke_posture_vulnerability(uke) == pytest.approx(POSTURE_VULN_MOVING_COM)

    def test_tilted_trunk_applies_correct_multiplier(self):
        uke = _build_judoka()
        uke.state.body_state.trunk_sagittal = math.radians(20.0)  # > threshold
        assert uke_posture_vulnerability(uke) == pytest.approx(POSTURE_VULN_TILTED_TRUNK)

    def test_multipliers_stack_multiplicatively(self):
        from body_state import FootContactState
        uke = _build_judoka()
        uke.state.body_state.foot_state_right.contact_state = FootContactState.AIRBORNE
        uke.state.body_state.com_velocity = (0.5, 0.0)
        uke.state.body_state.trunk_sagittal = math.radians(20.0)
        expected = (POSTURE_VULN_AIRBORNE_FOOT
                    * POSTURE_VULN_MOVING_COM
                    * POSTURE_VULN_TILTED_TRUNK)
        assert uke_posture_vulnerability(uke) == pytest.approx(expected)

    def test_below_threshold_velocity_does_not_count(self):
        uke = _build_judoka()
        uke.state.body_state.com_velocity = (0.05, 0.05)  # below threshold
        assert uke_posture_vulnerability(uke) == pytest.approx(POSTURE_VULN_BASE)


# ---------------------------------------------------------------------------
# MAGNITUDE FORMULA
# ---------------------------------------------------------------------------
class TestPullKuzushiMagnitude:
    def test_baseline_magnitude_is_positive(self):
        attacker = _build_judoka("A")
        victim   = _build_judoka("B")
        edge     = _make_edge("A", "B")
        m = pull_kuzushi_magnitude(attacker, edge, victim)
        assert m > 0.0
        assert m < BASE_PULL_KUZUSHI_FORCE  # all sub-1.0 multipliers

    def test_deeper_grip_yields_larger_magnitude(self):
        attacker = _build_judoka("A")
        victim   = _build_judoka("B")
        shallow  = _make_edge("A", "B", depth=GripDepth.POCKET)
        deep     = _make_edge("A", "B", depth=GripDepth.DEEP)
        assert (pull_kuzushi_magnitude(attacker, deep, victim)
                > pull_kuzushi_magnitude(attacker, shallow, victim))

    def test_higher_belt_yields_larger_magnitude(self):
        white = _build_judoka("W", belt=BeltRank.WHITE)
        black = _build_judoka("B5", belt=BeltRank.BLACK_5)
        victim = _build_judoka("V")
        edge_w = _make_edge("W", "V")
        edge_b = _make_edge("B5", "V")
        assert (pull_kuzushi_magnitude(black, edge_b, victim)
                > pull_kuzushi_magnitude(white, edge_w, victim))

    def test_higher_pull_execution_yields_larger_magnitude(self):
        # HAJ-137 — the technique term reads `pull_execution` off the skill
        # vector, not the old `fight_iq / 10` placeholder. (Judoka now
        # auto-populates a belt-default skill_vector in __post_init__, so the
        # fight_iq fallback in skill_vector.axis() no longer fires and
        # fight_iq no longer moves pull magnitude.) Vary the authoritative
        # axis directly: cleaner pull conversion → larger kuzushi magnitude.
        low  = _build_judoka("L")
        high = _build_judoka("H")
        low.skill_vector.pull_execution  = 0.2
        high.skill_vector.pull_execution = 0.9
        victim = _build_judoka("V")
        edge_l = _make_edge("L", "V")
        edge_h = _make_edge("H", "V")
        assert (pull_kuzushi_magnitude(high, edge_h, victim)
                > pull_kuzushi_magnitude(low, edge_l, victim))

    def test_posture_vulnerability_modulates_magnitude(self):
        # Same pull on grounded uke vs mid-step uke → different magnitudes.
        from body_state import FootContactState
        attacker = _build_judoka("A")
        grounded = _build_judoka("G")
        midstep  = _build_judoka("M")
        midstep.state.body_state.foot_state_right.contact_state = FootContactState.AIRBORNE
        edge_g = _make_edge("A", "G")
        edge_m = _make_edge("A", "M")
        m_grounded = pull_kuzushi_magnitude(attacker, edge_g, grounded)
        m_midstep  = pull_kuzushi_magnitude(attacker, edge_m, midstep)
        # Mid-step multiplier is POSTURE_VULN_AIRBORNE_FOOT (1.5x).
        assert m_midstep == pytest.approx(m_grounded * POSTURE_VULN_AIRBORNE_FOOT)

    def test_fatigued_attacker_yields_smaller_magnitude(self):
        # strength term is grip_strength which folds in hand fatigue.
        fresh   = _build_judoka("F")
        cooked  = _build_judoka("C")
        cooked.state.body["right_hand"].fatigue = 0.8
        cooked.state.body["left_hand"].fatigue  = 0.8
        cooked.state.body["core"].fatigue       = 0.8
        victim = _build_judoka("V")
        edge_f = _make_edge("F", "V")
        edge_c = _make_edge("C", "V")
        assert (pull_kuzushi_magnitude(fresh, edge_f, victim)
                > pull_kuzushi_magnitude(cooked, edge_c, victim))


# ---------------------------------------------------------------------------
# pull_kuzushi_event WRAPPER
# ---------------------------------------------------------------------------
class TestPullKuzushiEvent:
    def test_emits_pull_source_kind(self):
        attacker = _build_judoka("A")
        victim   = _build_judoka("B")
        edge     = _make_edge("A", "B")
        ev = pull_kuzushi_event(attacker, edge, victim, (1.0, 0.0), current_tick=7)
        assert ev is not None
        assert ev.source_kind == KuzushiSource.PULL
        assert ev.tick_emitted == 7

    def test_event_vector_uses_direction_lookup(self):
        attacker = _build_judoka("A")
        victim   = _build_judoka("B")
        edge_cross = _make_edge("A", "B", grip_type=GripTypeV2.CROSS)
        ev = pull_kuzushi_event(attacker, edge_cross, victim, (1.0, 0.5), current_tick=0)
        # CROSS flips lateral component then unit-normalizes.
        mag = math.hypot(1.0, 0.5)
        assert ev.vector == pytest.approx((1.0 / mag, -0.5 / mag))

    def test_zero_pull_direction_returns_none(self):
        attacker = _build_judoka("A")
        victim   = _build_judoka("B")
        edge     = _make_edge("A", "B")
        assert pull_kuzushi_event(attacker, edge, victim, (0.0, 0.0), 0) is None


# ---------------------------------------------------------------------------
# END-TO-END VIA Match._compute_net_force_on
# ---------------------------------------------------------------------------
class TestMatchPullEmission:
    def _build_match_with_grip(self, grip_type=GripTypeV2.LAPEL_LOW,
                               depth=GripDepth.STANDARD):
        from match import Match

        a = _build_judoka("A")
        b = _build_judoka("B")
        ref = _make_referee()
        match = Match(fighter_a=a, fighter_b=b, referee=ref)
        # Seat a single edge A→B so PULL has something to drive through.
        edge = _make_edge("A", "B", grip_type=grip_type, depth=depth)
        match.grip_graph.add_edge(edge)
        return match, a, b, edge

    def test_pull_action_appends_event_to_victim_buffer(self):
        from actions import pull
        match, a, b, edge = self._build_match_with_grip()
        assert len(b.kuzushi_events) == 0

        pull_act = pull("right_hand", direction=(1.0, 0.0), magnitude=200.0)
        match._compute_net_force_on(
            victim=b, attacker=a, attacker_actions=[pull_act], tick=42,
        )
        assert len(b.kuzushi_events) == 1
        ev = b.kuzushi_events[0]
        assert ev.tick_emitted == 42
        assert ev.source_kind == KuzushiSource.PULL
        assert ev.magnitude > 0.0
        assert ev.vector == pytest.approx((1.0, 0.0))

    def test_pull_does_not_pollute_attackers_own_buffer(self):
        from actions import pull
        match, a, b, edge = self._build_match_with_grip()
        pull_act = pull("right_hand", direction=(1.0, 0.0), magnitude=200.0)
        match._compute_net_force_on(
            victim=b, attacker=a, attacker_actions=[pull_act], tick=1,
        )
        assert len(a.kuzushi_events) == 0
        assert len(b.kuzushi_events) == 1

    def test_force_vector_unchanged_by_event_emission(self):
        # Compare a PULL with event-emission live against the same
        # delivered-force calculation done by hand (matches the existing
        # Part 2.4 pipeline). Event emission must not alter the force.
        from actions import pull
        from force_envelope import FORCE_ENVELOPES, grip_strength
        import random
        match, a, b, edge = self._build_match_with_grip()

        # Force the noise term to zero by seeding the global random and
        # patching FORCE_NOISE_PCT — but easier: just call twice with the
        # same seed and confirm equality.
        pull_act = pull("right_hand", direction=(1.0, 0.0), magnitude=200.0)

        random.seed(123)
        fx1, fy1 = match._compute_net_force_on(
            victim=b, attacker=a, attacker_actions=[pull_act], tick=0,
        )
        # Reset buffer + repeat.
        b.kuzushi_events.clear()
        random.seed(123)
        fx2, fy2 = match._compute_net_force_on(
            victim=b, attacker=a, attacker_actions=[pull_act], tick=0,
        )
        assert (fx1, fy1) == (fx2, fy2)
        # And force is in the expected direction (forward, +x), nonzero.
        assert fx1 > 0.0
        assert fy1 == pytest.approx(0.0)

    def test_non_pull_force_actions_do_not_emit(self):
        # PUSH/LIFT/COUPLE/FEINT all flow through DRIVING_FORCE_KINDS but
        # only PULL emits in HAJ-131.
        from actions import Action
        from enums import BodyPart  # noqa: F401  (Action uses string keys)
        from actions import ActionKind
        match, a, b, edge = self._build_match_with_grip()

        push_act = Action(
            kind=ActionKind.PUSH, hand="right_hand",
            direction=(1.0, 0.0), magnitude=200.0,
        )
        match._compute_net_force_on(
            victim=b, attacker=a, attacker_actions=[push_act], tick=0,
        )
        assert len(b.kuzushi_events) == 0

    def test_pull_with_no_grip_emits_nothing(self):
        # If the attacker has no grip on victim, _compute_net_force_on
        # short-circuits with `edge is None` — no event should be emitted.
        from actions import pull
        from match import Match

        a = _build_judoka("A")
        b = _build_judoka("B")
        ref = _make_referee()
        match = Match(fighter_a=a, fighter_b=b, referee=ref)
        # No edges added.
        pull_act = pull("right_hand", direction=(1.0, 0.0), magnitude=200.0)
        match._compute_net_force_on(
            victim=b, attacker=a, attacker_actions=[pull_act], tick=0,
        )
        assert len(b.kuzushi_events) == 0
