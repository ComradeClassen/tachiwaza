# intent.py
# HAJ-135 — multi-tick planning / sequence intent.
#
# Spec: design-notes/grip-as-cause.md §3.6 (Combo Pulls and Sequence
# Composition).
#
# Pre-fix action selection was purely tick-local: each tick re-decided
# from scratch. Real fighters hold a multi-tick plan ("lapel pull → sleeve
# pull → foot attack → commit") that strings combo components within the
# kuzushi decay window so events stack into a throw-supporting compromised
# state. Elite fighters land the components on consecutive ticks; novices
# mistime them so events decay before composing.
#
# This module owns the data structure (Plan + PlanStep + templates) and
# the resolution helpers (form_plan / next_plan_action / should_abandon).
# action_selection.py wires it into the existing ladder: a plan's next
# step preempts the default secondary action when one is active.

from __future__ import annotations
import random
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Optional

from actions import (
    Action, ActionKind, deepen, foot_sweep_setup, leg_attack_setup,
    disruptive_step, pull,
)
from enums import GripDepth, GripTypeV2, DominantSide
from throws import ThrowID

if TYPE_CHECKING:
    from judoka import Judoka
    from grip_graph import GripGraph, GripEdge


# ---------------------------------------------------------------------------
# PLAN STEP
# ---------------------------------------------------------------------------
# A plan is a sequence of declared intents; each step resolves to a
# concrete Action at execution time. Keeping steps abstract (PULL_LAPEL
# vs. "pull this specific edge") lets the same plan template adapt to
# whichever lapel grip is live this tick.
class PlanStep(Enum):
    PULL_LAPEL       = auto()
    PULL_SLEEVE      = auto()
    DEEPEN_LAPEL     = auto()
    DEEPEN_SLEEVE    = auto()
    FOOT_SWEEP       = auto()
    LEG_ATTACK       = auto()
    DISRUPTIVE_STEP  = auto()
    COMMIT_THROW     = auto()


# ---------------------------------------------------------------------------
# PLAN
# ---------------------------------------------------------------------------
@dataclass
class Plan:
    """A sequence intent a fighter formed at `formed_at_tick` and is
    executing across subsequent ticks.

    `step_index` advances when a step actually fires (a high-precision
    tick); skipped/delayed ticks leave it unchanged. Plans complete
    when `step_index >= len(sequence)`. Abandonment is decided externally
    by `should_abandon_plan`; this dataclass is pure state.
    """
    target_throw_id: ThrowID
    sequence:        list[PlanStep]
    step_index:      int = 0
    formed_at_tick:  int = 0
    last_advanced_tick: int = 0

    def is_complete(self) -> bool:
        return self.step_index >= len(self.sequence)

    def current_step(self) -> Optional[PlanStep]:
        if self.is_complete():
            return None
        return self.sequence[self.step_index]


# ---------------------------------------------------------------------------
# TEMPLATES
# ---------------------------------------------------------------------------
# Per-throw plan blueprints. v0.1 ships 4 templates per the ticket scope
# ("3-5 patterns, rest can be added incrementally"). Each template's
# ordered sequence reflects the canonical setup for the named throw;
# event composition + decay does the rest of the work.
PLAN_TEMPLATES: dict[ThrowID, list[PlanStep]] = {
    ThrowID.UCHI_MATA: [
        PlanStep.DEEPEN_LAPEL,
        PlanStep.PULL_SLEEVE,
        PlanStep.LEG_ATTACK,
        PlanStep.COMMIT_THROW,
    ],
    ThrowID.O_SOTO_GARI: [
        PlanStep.PULL_LAPEL,
        PlanStep.DISRUPTIVE_STEP,
        PlanStep.FOOT_SWEEP,
        PlanStep.COMMIT_THROW,
    ],
    ThrowID.SEOI_NAGE: [
        PlanStep.DEEPEN_LAPEL,
        PlanStep.PULL_LAPEL,
        PlanStep.PULL_SLEEVE,
        PlanStep.COMMIT_THROW,
    ],
    ThrowID.DE_ASHI_HARAI: [
        PlanStep.DISRUPTIVE_STEP,
        PlanStep.PULL_SLEEVE,
        PlanStep.FOOT_SWEEP,
        PlanStep.COMMIT_THROW,
    ],
}


# ---------------------------------------------------------------------------
# PLAN FORMATION
# ---------------------------------------------------------------------------
# When a fighter has seated grips and a tactical motivation to pursue a
# specific throw, action_selection asks `should_form_plan`. v0.1 keeps
# the criteria simple: pick a target throw the fighter has a template
# for + can plausibly attempt (in vocabulary, owns relevant grips), and
# only form when no plan is active and the kumi-kata clock has been
# advancing (signal that grip-fighting alone isn't producing kuzushi).

# Earliest kumi-kata clock value at which a plan can be formed. Mirrors
# the foot-attack stalemate gate from HAJ-133 so plans and foot-attack
# substitutions become available around the same time.
PLAN_FORMATION_CLOCK_MIN: int = 4

# Below this fight_iq, fighters don't plan multi-tick sequences — they
# just react tick-locally. White / yellow belts.
PLAN_MIN_FIGHT_IQ: int = 4


def should_form_plan(
    judoka: "Judoka",
    opponent: "Judoka",
    graph: "GripGraph",
    kumi_kata_clock: int,
    rng: Optional[random.Random] = None,
) -> Optional[Plan]:
    """If `judoka` should form a new plan this tick, return it. Else None.

    Gate: no current plan, fight_iq above the planning threshold, kumi-
    kata clock past the stalemate floor, the fighter has at least one
    grip seated, and a planable target throw exists in their vocabulary.

    The returned Plan picks the highest-priority target from the
    fighter's signature throws that has a template; falls back to the
    first templated throw in their vocabulary.
    """
    if judoka.current_plan is not None:
        return None
    if judoka.capability.fight_iq < PLAN_MIN_FIGHT_IQ:
        return None
    if kumi_kata_clock < PLAN_FORMATION_CLOCK_MIN:
        return None
    if not graph.edges_owned_by(judoka.identity.name):
        return None
    target = _pick_plan_target(judoka)
    if target is None:
        return None
    template = PLAN_TEMPLATES[target]
    return Plan(
        target_throw_id=target,
        sequence=list(template),
        step_index=0,
    )


def _pick_plan_target(judoka: "Judoka") -> Optional[ThrowID]:
    """Pick a throw to plan toward. Signature throws first; then any
    templated throw in the vocabulary."""
    vocab = set(judoka.capability.throw_vocabulary)
    for tid in judoka.capability.signature_throws:
        if tid in vocab and tid in PLAN_TEMPLATES:
            return tid
    for tid in PLAN_TEMPLATES:
        if tid in vocab:
            return tid
    return None


# ---------------------------------------------------------------------------
# SEQUENCING PRECISION (skill modulator)
# ---------------------------------------------------------------------------
# Per-tick gates that determine whether the planned step actually fires
# this tick. Modulated by `sequencing_precision` which v0.1 stubs from
# fight_iq (HAJ-136 will replace with the dedicated skill axis).
#
# Three regimes:
#   high (>= 0.75): step nearly always fires; plan completes within 4-5
#                   ticks → events stack inside the kuzushi decay window
#                   → throw commits on composed kuzushi.
#   mid  (0.45-0.74): occasional 1-2 tick delay; events partially decay.
#   low  (< 0.45):  frequent delays / drops / out-of-order firing;
#                   events fully decay between firings → throw fails on
#                   barely-compromised uke (existing failure model).
HIGH_PRECISION_THRESHOLD: float = 0.75
MID_PRECISION_THRESHOLD:  float = 0.45

# Per-tick fire / delay / drop probabilities by regime.
HIGH_FIRE_PROB:   float = 0.95
MID_FIRE_PROB:    float = 0.65
LOW_FIRE_PROB:    float = 0.40
LOW_DROP_PROB:    float = 0.20   # low-skill chance to drop the step entirely


def sequencing_precision(judoka: "Judoka") -> float:
    """Derive sequencing precision in [0, 1].

    HAJ-137 — reads `sequencing_precision` off the skill vector, with
    fight_iq/10 fallback for legacy fixtures via skill_vector.axis().
    """
    from skill_vector import axis
    return max(0.0, min(1.0, axis(judoka, "sequencing_precision")))


def _step_outcome(
    precision: float, rng: random.Random,
) -> str:
    """Roll the per-tick outcome for a plan step. Returns one of:
      'fire'  — step fires this tick; advance the plan.
      'delay' — step doesn't fire this tick; plan stays put, fall back
                to default ladder behavior for this tick.
      'drop'  — step is dropped from the plan; advance the plan without
                firing (low-skill mistiming where the component is just
                forgotten).
    """
    if precision >= HIGH_PRECISION_THRESHOLD:
        fire_p = HIGH_FIRE_PROB
        drop_p = 0.0
    elif precision >= MID_PRECISION_THRESHOLD:
        fire_p = MID_FIRE_PROB
        drop_p = 0.0
    else:
        fire_p = LOW_FIRE_PROB
        drop_p = LOW_DROP_PROB
    roll = rng.random()
    if roll < fire_p:
        return "fire"
    if roll < fire_p + drop_p:
        return "drop"
    return "delay"


# ---------------------------------------------------------------------------
# STEP → ACTION RESOLUTION
# ---------------------------------------------------------------------------
def next_plan_action(
    plan:      Plan,
    judoka:    "Judoka",
    opponent:  "Judoka",
    graph:     "GripGraph",
    rng:       random.Random,
    current_tick: int = 0,
) -> tuple[Optional[Action], str]:
    """Resolve the plan's current step into a concrete Action for this
    tick. Returns (action, outcome) where outcome is 'fire' | 'delay' |
    'drop' | 'complete'. Caller mutates the plan based on the outcome.

    'fire' returns the Action to append to the ladder's output.
    'delay' returns None and leaves the plan untouched.
    'drop' returns None and the caller should advance step_index.
    'complete' returns None and the caller should clear the plan.
    """
    if plan.is_complete():
        return None, "complete"
    precision = sequencing_precision(judoka)
    outcome = _step_outcome(precision, rng)
    step = plan.current_step()
    if outcome != "fire":
        return None, outcome
    # COMMIT_THROW step: don't synthesize an Action here — the regular
    # commit rung in _try_commit handles the actual commit firing if the
    # composed kuzushi state lifts the perceived signature past the
    # commit threshold. Plan's job was to set up that state.
    if step == PlanStep.COMMIT_THROW:
        return None, "complete"
    action = _build_step_action(step, judoka, opponent, graph)
    if action is None:
        # Step couldn't be materialized (no qualifying grip etc.) — treat
        # as a drop so the plan progresses rather than spinning forever.
        return None, "drop"
    return action, "fire"


def _build_step_action(
    step:     PlanStep,
    judoka:   "Judoka",
    opponent: "Judoka",
    graph:    "GripGraph",
) -> Optional[Action]:
    """Materialize a plan step into a concrete Action. Returns None when
    no usable resource exists for the step (e.g. PULL_LAPEL with no
    lapel edge)."""
    own_edges = graph.edges_owned_by(judoka.identity.name)

    if step in (PlanStep.PULL_LAPEL, PlanStep.DEEPEN_LAPEL):
        edge = _find_edge(own_edges, _is_lapel)
        if edge is None:
            return None
        if step == PlanStep.PULL_LAPEL:
            return _pull_through(edge, judoka, opponent)
        return deepen(edge)

    if step in (PlanStep.PULL_SLEEVE, PlanStep.DEEPEN_SLEEVE):
        edge = _find_edge(own_edges, _is_sleeve)
        if edge is None:
            return None
        if step == PlanStep.PULL_SLEEVE:
            return _pull_through(edge, judoka, opponent)
        return deepen(edge)

    if step == PlanStep.FOOT_SWEEP:
        return _emit_foot_attack(judoka, opponent, ActionKind.FOOT_SWEEP_SETUP)

    if step == PlanStep.LEG_ATTACK:
        return _emit_foot_attack(judoka, opponent, ActionKind.LEG_ATTACK_SETUP)

    if step == PlanStep.DISRUPTIVE_STEP:
        return _emit_foot_attack(judoka, opponent, ActionKind.DISRUPTIVE_STEP)

    if step == PlanStep.COMMIT_THROW:
        # v0.1 — defer the actual commit to the existing _try_commit
        # machinery in action_selection so the grip-presence gate and
        # signature-perception layer still apply. We signal "commit
        # intent" by returning None; the caller observes a 'fire'
        # outcome at COMMIT_THROW and lets the regular commit rung run
        # this tick instead of wrapping the foot-attack/pull substitution.
        return None

    return None


def _find_edge(edges, predicate) -> Optional["GripEdge"]:
    for e in edges:
        if predicate(e):
            return e
    return None


def _is_lapel(edge: "GripEdge") -> bool:
    return edge.grip_type_v2 in (
        GripTypeV2.LAPEL_HIGH, GripTypeV2.LAPEL_LOW, GripTypeV2.COLLAR,
    )


def _is_sleeve(edge: "GripEdge") -> bool:
    return edge.grip_type_v2 in (
        GripTypeV2.SLEEVE_HIGH, GripTypeV2.SLEEVE_LOW, GripTypeV2.PISTOL,
    )


def _pull_through(
    edge: "GripEdge", judoka: "Judoka", opponent: "Judoka",
) -> Action:
    """Build a PULL action through `edge`, drawing opponent toward
    judoka along the dyad axis. Magnitude mirrors action_selection's
    DRIVE_MAGNITUDE_N."""
    from action_selection import DRIVE_MAGNITUDE_N
    ax, ay = judoka.state.body_state.com_position
    ox, oy = opponent.state.body_state.com_position
    dx, dy = ox - ax, oy - ay
    norm = (dx * dx + dy * dy) ** 0.5 or 1.0
    # Pull direction draws opponent → me, so opp_to_me.
    pull_dir = (-dx / norm, -dy / norm)
    return pull(edge.grasper_part.value, pull_dir, DRIVE_MAGNITUDE_N)


def _emit_foot_attack(
    judoka: "Judoka", opponent: "Judoka", kind: ActionKind,
) -> Action:
    """Build a foot-attack action toward `opponent`. Picks the trailing
    foot for the attack vector (mirrors action_selection's locomotion
    convention)."""
    bs = judoka.state.body_state
    ox, oy = opponent.state.body_state.com_position
    cx, cy = bs.com_position
    dx, dy = ox - cx, oy - cy
    norm = (dx * dx + dy * dy) ** 0.5 or 1.0
    attack_vec = (dx / norm, dy / norm)
    # Trailing foot.
    lx, ly = bs.foot_state_left.position
    rx, ry = bs.foot_state_right.position
    left_proj  = (lx - cx) * attack_vec[0] + (ly - cy) * attack_vec[1]
    right_proj = (rx - cx) * attack_vec[0] + (ry - cy) * attack_vec[1]
    foot = "left_foot" if left_proj < right_proj else "right_foot"
    if kind == ActionKind.FOOT_SWEEP_SETUP:
        return foot_sweep_setup(foot, attack_vec, magnitude=0.25)
    if kind == ActionKind.LEG_ATTACK_SETUP:
        return leg_attack_setup(foot, attack_vec, magnitude=0.25)
    return disruptive_step(foot, attack_vec, magnitude=0.25)


# ---------------------------------------------------------------------------
# PLAN ABANDONMENT
# ---------------------------------------------------------------------------
# A plan is abandoned when circumstances change: the attacker lost their
# grips, the opponent landed a counter, an in-progress throw was started
# or aborted, etc. The caller (action_selection) drops the plan and the
# fighter returns to tick-local decision-making until something triggers
# a new plan formation.

def should_abandon_plan(
    plan:        Plan,
    judoka:      "Judoka",
    opponent:    "Judoka",
    graph:       "GripGraph",
    has_in_progress_throw: bool,
) -> bool:
    """Return True if the plan should be dropped this tick.

    Triggers:
      - Attacker has no grips left (something stripped or matte fired).
      - Attacker is stunned (rung-1 in select_actions blocks anyway, but
        we drop the plan so it doesn't resume mid-recovery).
      - Attacker has an in-progress throw (the commit started; either
        this plan completed or another commit fired ahead of it).
      - Plan is older than the kuzushi decay buffer's useful window
        (events would have decayed even at high precision).
    """
    if judoka.state.stun_ticks > 0:
        return True
    if not graph.edges_owned_by(judoka.identity.name):
        return True
    if has_in_progress_throw:
        return True
    return False
