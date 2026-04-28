# tests/test_intent_planning.py
# HAJ-135 — multi-tick planning / sequence intent.
#
# Pre-fix action selection was purely tick-local: each tick re-decided
# from scratch, so combos were emergent only via tick-local heuristics
# (HAJ-133 foot-attack stalemate substitution). Real fighters hold a
# multi-tick plan ("lapel pull → sleeve pull → foot attack → commit")
# that strings combo components within the kuzushi decay window so
# events stack into a throw-supporting compromised state.
#
# Post-fix:
#   - Plan dataclass + per-throw templates.
#   - Judoka.current_plan tracks active intent across ticks.
#   - sequencing_precision (stubbed from fight_iq) gates step firing:
#     high → events stack inside the kuzushi decay window;
#     low  → events decay between firings, throw fails on weak kuzushi.
#   - Plan abandonment when grips collapse or stun fires.

from __future__ import annotations
import os
import random as _r
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from body_state import place_judoka
from enums import (
    BodyPart, GripTarget, GripTypeV2, GripDepth, Position,
)
from grip_graph import GripEdge
from match import Match
from referee import build_suzuki
from actions import ActionKind, FOOT_ATTACK_KINDS
from intent import (
    Plan, PlanStep, PLAN_TEMPLATES,
    PLAN_FORMATION_CLOCK_MIN, PLAN_MIN_FIGHT_IQ,
    sequencing_precision, should_form_plan, should_abandon_plan,
    next_plan_action,
)
from kuzushi import compromised_state
from throws import ThrowID
import main as main_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _pair_match():
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())
    return t, s, m


def _seat_grips(m, owner, target):
    m.grip_graph.add_edge(GripEdge(
        grasper_id=owner.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=target.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.STANDARD,
        strength=0.8, established_tick=0,
    ))
    m.grip_graph.add_edge(GripEdge(
        grasper_id=owner.identity.name, grasper_part=BodyPart.LEFT_HAND,
        target_id=target.identity.name, target_location=GripTarget.RIGHT_SLEEVE,
        grip_type_v2=GripTypeV2.SLEEVE_HIGH, depth_level=GripDepth.STANDARD,
        strength=0.8, established_tick=0,
    ))


# ---------------------------------------------------------------------------
# 1. Plan templates exist and look sensible.
# ---------------------------------------------------------------------------
def test_at_least_three_throw_templates_exist() -> None:
    """Spec scope: 3-5 patterns at v0.1."""
    assert len(PLAN_TEMPLATES) >= 3
    # Each template must end in COMMIT_THROW (the marker that triggers
    # plan completion + lets the standard commit rung fire).
    for tid, steps in PLAN_TEMPLATES.items():
        assert steps[-1] == PlanStep.COMMIT_THROW, (
            f"{tid.name} template missing COMMIT_THROW finisher"
        )


def test_uchi_mata_template_has_setup_components() -> None:
    """Uchi-mata's canonical setup is lapel control + sleeve pull +
    leg attack + commit — verify the template captures that pattern."""
    steps = PLAN_TEMPLATES[ThrowID.UCHI_MATA]
    assert PlanStep.PULL_SLEEVE in steps
    assert PlanStep.LEG_ATTACK in steps
    assert PlanStep.COMMIT_THROW in steps


# ---------------------------------------------------------------------------
# 2. Sequencing precision is the dedicated skill axis (HAJ-137).
# ---------------------------------------------------------------------------
def test_sequencing_precision_scales_with_axis() -> None:
    t = main_module.build_tanaka()
    t.skill_vector.sequencing_precision = 1.0
    high = sequencing_precision(t)
    t.skill_vector.sequencing_precision = 0.5
    mid = sequencing_precision(t)
    t.skill_vector.sequencing_precision = 0.1
    low = sequencing_precision(t)
    assert high > mid > low
    assert 0.0 <= low and high <= 1.0


# ---------------------------------------------------------------------------
# 3. Plan formation gate.
# ---------------------------------------------------------------------------
def test_no_plan_below_clock_threshold() -> None:
    """Below PLAN_FORMATION_CLOCK_MIN, plans don't form."""
    t, s, m = _pair_match()
    _seat_grips(m, t, s)
    plan = should_form_plan(
        t, s, m.grip_graph, kumi_kata_clock=PLAN_FORMATION_CLOCK_MIN - 1,
    )
    assert plan is None


def test_plan_forms_when_gate_passes() -> None:
    t, s, m = _pair_match()
    _seat_grips(m, t, s)
    plan = should_form_plan(
        t, s, m.grip_graph, kumi_kata_clock=PLAN_FORMATION_CLOCK_MIN + 2,
    )
    assert plan is not None
    assert plan.target_throw_id in PLAN_TEMPLATES
    assert plan.step_index == 0


def test_low_iq_fighter_does_not_plan() -> None:
    t, s, m = _pair_match()
    t.capability.fight_iq = PLAN_MIN_FIGHT_IQ - 1   # below threshold
    _seat_grips(m, t, s)
    plan = should_form_plan(
        t, s, m.grip_graph, kumi_kata_clock=PLAN_FORMATION_CLOCK_MIN + 5,
    )
    assert plan is None


def test_no_plan_without_grips() -> None:
    t, s, m = _pair_match()
    # No grips seated.
    plan = should_form_plan(
        t, s, m.grip_graph, kumi_kata_clock=PLAN_FORMATION_CLOCK_MIN + 5,
    )
    assert plan is None


# ---------------------------------------------------------------------------
# 4. Step resolution materializes concrete actions.
# ---------------------------------------------------------------------------
def test_pull_lapel_step_produces_pull_action() -> None:
    t, s, m = _pair_match()
    _seat_grips(m, t, s)
    plan = Plan(
        target_throw_id=ThrowID.SEOI_NAGE,
        sequence=[PlanStep.PULL_LAPEL, PlanStep.COMMIT_THROW],
    )
    rng = _r.Random(0)
    # Force high-precision so the step always fires.
    t.skill_vector.sequencing_precision = 1.0
    action, outcome = next_plan_action(plan, t, s, m.grip_graph, rng)
    assert outcome == "fire"
    assert action is not None
    assert action.kind == ActionKind.PULL


def test_foot_sweep_step_produces_foot_attack_action() -> None:
    t, s, m = _pair_match()
    _seat_grips(m, t, s)
    plan = Plan(
        target_throw_id=ThrowID.O_SOTO_GARI,
        sequence=[PlanStep.FOOT_SWEEP, PlanStep.COMMIT_THROW],
    )
    rng = _r.Random(0)
    t.capability.fight_iq = 10
    action, outcome = next_plan_action(plan, t, s, m.grip_graph, rng)
    assert outcome == "fire"
    assert action is not None
    assert action.kind in FOOT_ATTACK_KINDS


def test_commit_step_returns_complete() -> None:
    """COMMIT_THROW step is a marker — plan completes; the regular
    commit rung in _try_commit handles the actual commit firing."""
    t, s, m = _pair_match()
    _seat_grips(m, t, s)
    plan = Plan(
        target_throw_id=ThrowID.SEOI_NAGE,
        sequence=[PlanStep.COMMIT_THROW],
    )
    rng = _r.Random(0)
    t.capability.fight_iq = 10
    action, outcome = next_plan_action(plan, t, s, m.grip_graph, rng)
    assert outcome == "complete"
    assert action is None


# ---------------------------------------------------------------------------
# 5. Elite-vs-novice combo emergence (the §3.6 acceptance test).
# ---------------------------------------------------------------------------
def _run_plan(judoka, opponent, graph, plan, ticks: int, rng_seed: int) -> int:
    """Run a plan for `ticks` ticks against the given dyad. Returns the
    number of fired steps."""
    rng = _r.Random(rng_seed)
    fires = 0
    for tick in range(ticks):
        if plan.is_complete():
            break
        action, outcome = next_plan_action(
            plan, judoka, opponent, graph, rng, current_tick=tick,
        )
        if outcome == "fire":
            fires += 1
            plan.step_index += 1
        elif outcome == "drop":
            plan.step_index += 1
        elif outcome == "complete":
            break
    return fires


def test_elite_completes_plan_within_decay_window() -> None:
    """A high-precision fighter fires plan steps on consecutive ticks so
    the 4-step plan completes within the 5-tick kuzushi decay half-life
    window. Events stack into a meaningful compromised state."""
    t, s, m = _pair_match()
    t.skill_vector.sequencing_precision = 1.0   # high precision
    _seat_grips(m, t, s)
    template = list(PLAN_TEMPLATES[ThrowID.UCHI_MATA])
    plan = Plan(target_throw_id=ThrowID.UCHI_MATA, sequence=template)
    fires = _run_plan(t, s, m.grip_graph, plan, ticks=8, rng_seed=0)
    # 4-step template; 1 step is COMMIT_THROW which doesn't 'fire' as
    # an action (it's a marker, completes the plan). So elite fires the
    # 3 setup steps + completes on the 4th tick.
    assert fires >= 2, f"elite should fire setup steps; fires={fires}"
    assert plan.is_complete() or plan.step_index >= 3


def test_low_skill_mistimes_plan() -> None:
    """A low-precision fighter delays/drops steps so the plan extends
    well beyond the kuzushi decay window. Even given many ticks, fewer
    setup steps fire than for the elite; some are dropped."""
    t, s, m = _pair_match()
    t.skill_vector.sequencing_precision = 0.1   # low precision
    _seat_grips(m, t, s)
    template = list(PLAN_TEMPLATES[ThrowID.UCHI_MATA])
    plan = Plan(target_throw_id=ThrowID.UCHI_MATA, sequence=template)
    # Same number of ticks the elite was given.
    fires = _run_plan(t, s, m.grip_graph, plan, ticks=8, rng_seed=0)
    # Compare against elite's fire count under same seed.
    elite = main_module.build_tanaka()
    elite.skill_vector.sequencing_precision = 1.0
    place_judoka(elite, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    plan2 = Plan(
        target_throw_id=ThrowID.UCHI_MATA,
        sequence=list(PLAN_TEMPLATES[ThrowID.UCHI_MATA]),
    )
    elite_fires = _run_plan(elite, s, m.grip_graph, plan2, ticks=8, rng_seed=0)
    assert fires <= elite_fires, (
        f"low-skill should fire ≤ elite; low={fires}, elite={elite_fires}"
    )


def test_elite_kuzushi_state_dominates_novice() -> None:
    """Run the same plan template against the same starting grip state
    twice — once at high precision, once at low — and verify the elite's
    accumulated kuzushi magnitude is meaningfully greater. This is the
    spec's §3.6 acceptance: 'a high-skill fighter's combo lands as 3-4
    events stacked within decay window'."""
    from kuzushi import record_kuzushi_event, foot_attack_kuzushi_event, pull_kuzushi_event

    def run_one(precision: float) -> float:
        t, s, m = _pair_match()
        t.skill_vector.sequencing_precision = precision
        # Also drive the per-axis kuzushi technique factors so the elite
        # vs novice difference shows up in event magnitudes (PULL reads
        # pull_execution; foot attacks read their own axes).
        t.skill_vector.pull_execution = precision
        t.skill_vector.foot_sweeps = precision
        t.skill_vector.leg_attacks = precision
        t.skill_vector.disruptive_stepping = precision
        _seat_grips(m, t, s)
        template = list(PLAN_TEMPLATES[ThrowID.UCHI_MATA])
        plan = Plan(target_throw_id=ThrowID.UCHI_MATA, sequence=template)
        rng = _r.Random(7)
        last_fire_tick = -1
        for tick in range(12):
            if plan.is_complete():
                break
            action, outcome = next_plan_action(
                plan, t, s, m.grip_graph, rng, current_tick=tick,
            )
            if outcome == "fire" and action is not None:
                # Emit the corresponding kuzushi event into uke's buffer
                # so we can measure composed state at the end.
                if action.kind == ActionKind.PULL:
                    edge = next(
                        (e for e in m.grip_graph.edges_owned_by(t.identity.name)
                         if e.grasper_part.value == action.hand), None,
                    )
                    if edge is not None:
                        ev = pull_kuzushi_event(
                            attacker=t, edge=edge, victim=s,
                            pull_direction=action.direction,
                            current_tick=tick,
                        )
                        if ev is not None:
                            record_kuzushi_event(s, ev)
                elif action.kind in FOOT_ATTACK_KINDS:
                    ev = foot_attack_kuzushi_event(
                        attacker=t, victim=s,
                        action_kind=action.kind,
                        attack_vector=action.direction,
                        current_tick=tick,
                    )
                    if ev is not None:
                        record_kuzushi_event(s, ev)
                plan.step_index += 1
                last_fire_tick = tick
            elif outcome == "drop":
                plan.step_index += 1
            elif outcome == "complete":
                break
        # Read the composed kuzushi state at the last tick the elite
        # would have committed (just past completion).
        eval_tick = max(last_fire_tick + 1, 1)
        state = compromised_state(s.kuzushi_events, current_tick=eval_tick)
        return state.magnitude

    elite_mag = run_one(precision=1.0)
    novice_mag = run_one(precision=0.1)
    # Elite's composed kuzushi should be meaningfully larger than novice's.
    assert elite_mag > novice_mag, (
        f"elite kuzushi {elite_mag:.2f} not greater than novice {novice_mag:.2f}"
    )


# ---------------------------------------------------------------------------
# 6. Plan abandonment.
# ---------------------------------------------------------------------------
def test_plan_abandoned_when_grips_collapse() -> None:
    """When the attacker has lost all grips mid-plan, abandon."""
    t, s, m = _pair_match()
    _seat_grips(m, t, s)
    plan = Plan(
        target_throw_id=ThrowID.UCHI_MATA,
        sequence=list(PLAN_TEMPLATES[ThrowID.UCHI_MATA]),
        step_index=1,
    )
    # Drop all of t's grips.
    for e in list(m.grip_graph.edges_owned_by(t.identity.name)):
        m.grip_graph.remove_edge(e)
    assert should_abandon_plan(plan, t, s, m.grip_graph, has_in_progress_throw=False)


def test_plan_abandoned_when_stunned() -> None:
    t, s, m = _pair_match()
    _seat_grips(m, t, s)
    plan = Plan(
        target_throw_id=ThrowID.UCHI_MATA,
        sequence=list(PLAN_TEMPLATES[ThrowID.UCHI_MATA]),
    )
    t.state.stun_ticks = 3
    assert should_abandon_plan(plan, t, s, m.grip_graph, has_in_progress_throw=False)


def test_plan_abandoned_when_in_progress_throw() -> None:
    t, s, m = _pair_match()
    _seat_grips(m, t, s)
    plan = Plan(
        target_throw_id=ThrowID.UCHI_MATA,
        sequence=list(PLAN_TEMPLATES[ThrowID.UCHI_MATA]),
    )
    assert should_abandon_plan(
        plan, t, s, m.grip_graph, has_in_progress_throw=True,
    )


def test_plan_persists_when_conditions_hold() -> None:
    t, s, m = _pair_match()
    _seat_grips(m, t, s)
    plan = Plan(
        target_throw_id=ThrowID.UCHI_MATA,
        sequence=list(PLAN_TEMPLATES[ThrowID.UCHI_MATA]),
    )
    assert not should_abandon_plan(
        plan, t, s, m.grip_graph, has_in_progress_throw=False,
    )


# ---------------------------------------------------------------------------
# 7. Integration with action selection.
# ---------------------------------------------------------------------------
def test_action_selection_forms_and_executes_plan() -> None:
    """Run select_actions across multiple ticks and verify the planner
    can form + advance a plan when conditions are right."""
    from action_selection import select_actions
    t, s, m = _pair_match()
    t.capability.fight_iq = 10
    _seat_grips(m, t, s)
    rng = _r.Random(0)
    formed = False
    advanced = False
    for tick in range(1, 30):
        actions = select_actions(
            t, s, m.grip_graph,
            kumi_kata_clock=tick,
            rng=rng, position=Position.GRIPPING, current_tick=tick,
        )
        if t.current_plan is not None:
            formed = True
            if t.current_plan.step_index > 0:
                advanced = True
                break
    assert formed, "elite should form a plan once stalemate gate fires"
    assert advanced, "elite should advance plan steps within a few ticks"


def test_low_iq_fighter_never_forms_plan_via_selection() -> None:
    """Below the IQ floor, planning is suppressed in the action ladder."""
    from action_selection import select_actions
    t, s, m = _pair_match()
    t.capability.fight_iq = 2   # below PLAN_MIN_FIGHT_IQ
    _seat_grips(m, t, s)
    rng = _r.Random(0)
    for tick in range(1, 30):
        actions = select_actions(
            t, s, m.grip_graph, kumi_kata_clock=tick,
            rng=rng, position=Position.GRIPPING, current_tick=tick,
        )
        assert t.current_plan is None


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
