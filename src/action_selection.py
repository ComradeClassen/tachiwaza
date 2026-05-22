# action_selection.py
# Physics-substrate Part 3.3: the v0.1 priority ladder.
#
# A deliberately-simple hardcoded decision function. Later rings (Ring 2
# coach instructions, Ring 3 cultural bias, Ring 4 opponent memory) layer
# on top by rewriting or filtering the ladder's output.
#
# The ladder produces up to two Actions per tick, or a single COMMIT_THROW
# compound action that supersedes the two-action cap.

from __future__ import annotations
import random
from typing import Optional, TYPE_CHECKING

from actions import (
    Action, ActionKind,
    reach, deepen, strip, release, pull, push, hold_connective, step, commit_throw,
    block_hip,
    foot_sweep_setup, leg_attack_setup, disruptive_step,
    TACTICAL_INTENT_PRESSURE, TACTICAL_INTENT_GIVE_GROUND,
    TACTICAL_INTENT_CIRCLE, TACTICAL_INTENT_HOLD_CENTER,
    TACTICAL_INTENT_CLOSING,
    TACTICAL_INTENT_CIRCLE_CLOSING, TACTICAL_INTENT_LATERAL_APPROACH,
    TACTICAL_INTENT_BAIT_RETREAT,
)
from enums import (
    GripTypeV2, GripDepth, GripTarget, GripMode, DominantSide, StanceMatchup,
    PositionalStyle, Position,
)
from throws import THROW_DEFS, ThrowID
from grip_presence_gate import evaluate_gate, GateResult, REASON_OK
from compromised_state import is_desperation_state
from commit_motivation import CommitMotivation
from availability import (
    THROW_TO_TECHNIQUE_ID, stage1_available_techniques,
    stage2_select_technique,
)

if TYPE_CHECKING:
    from judoka import Judoka
    from grip_graph import GripGraph, GripEdge
    from technique_catalog import TechniqueDefinition


# Tuning constants (calibration stubs).
# HAJ-128 — bumped from 0.65 to 0.78. Pre-bump, throws fired in close
# succession because the perceived signature crossed the threshold often
# during grip-fighting; viewer feedback was "more throw attempts than
# actual grip attempts." A higher threshold means the grip war has to
# actually produce a high-quality opening before a throw fires, so
# grip work dominates the tick budget the way it does in real judo.
COMMIT_THRESHOLD:             float = 0.78  # perceived signature must clear this to commit
DESPERATION_KUMI_CLOCK:       int   = 22    # tick count that triggers ladder rung 5
HIGH_FATIGUE_THRESHOLD:       float = 0.65  # hand-fatigue at which rung 6 prefers connective
DRIVE_MAGNITUDE_N:            float = 400.0 # PULL/PUSH force a non-desperation drive issues
PROBE_MAGNITUDE_N:            float = 120.0 # default-rung probing force
# Side-effect: match feeds us the grasper's kumi-kata clock; it's not
# visible on the Judoka itself because it belongs to the Match.

# HAJ-49 / HAJ-67 — non-scoring commit motivations.
#
# Four motivations fire the same low-signature drop-variant commit path but
# for different tactical reasons. Each has its own gate predicates and a
# per-tick probability scalar so multiple motivations don't cumulatively
# fire every eligible tick. See src/commit_motivation.py for the enum and
# narration templates; physics-substrate.md Part 3.3.1 for the spec text.
#
# Priority order when two motivations' gates both pass: CLOCK_RESET first
# (widest disposition coverage), then STAMINA_DESPERATION, GRIP_ESCAPE,
# SHIDO_FARMING. The first matching motivation wins.

# -- CLOCK_RESET (HAJ-49 legacy; gating unchanged) --
FALSE_ATTACK_CLOCK_MIN: int = 18   # earliest clock tick the tactical fake fires
FALSE_ATTACK_CLOCK_MAX: int = 29   # latest — strictly below imminent-shido (29) so
                                    # desperation (which fires at 29) takes precedence
FALSE_ATTACK_MIN_FIGHT_IQ: int = 4  # white/yellow belts don't game the clock; they panic
FALSE_ATTACK_TENDENCY_KEY: str = "false_attack_tendency"  # Identity.style_dna key
FALSE_ATTACK_TENDENCY_THRESHOLD: float = 0.40
FALSE_ATTACK_TENDENCY_DEFAULT:   float = 0.50
FALSE_ATTACK_PER_TICK_SCALE:     float = 0.10

# -- GRIP_ESCAPE --
# Fires when tori is losing the grip war, tori's own grips are shallow or
# missing, and composure has slipped below a moderate-panic threshold. The
# tactical fake is cover to reset the dyad.
# Calibration note: grip-delta values stay moderate in real exchanges
# because both fighters typically own 2 grips at similar depths. 0.30
# keeps the "opponent dominant" intent while remaining reachable.
GRIP_ESCAPE_DELTA_THRESHOLD:  float = 0.30
GRIP_ESCAPE_COMPOSURE_FRAC:   float = 0.60   # a little looser — composure slips before it shatters
GRIP_ESCAPE_PER_TICK_PROB:    float = 0.15

# -- SHIDO_FARMING --
# Fires when the opponent has been passive (their kumi-kata clock climbing)
# and tori has no real scoring opportunity. Tori throws a pose-attack to
# nudge the referee toward shido against uke. Style-biased.
# Calibration note: opp clock at ~10 ticks already represents a meaningful
# stretch of uke not attacking relative to match tempo.
SHIDO_FARMING_OPP_CLOCK:        int   = 7
SHIDO_FARMING_NO_SCORING_MAX:   float = 0.40
SHIDO_FARMING_TENDENCY_KEY:     str   = "shido_farming_tendency"
SHIDO_FARMING_TENDENCY_THRESHOLD: float = 0.45
SHIDO_FARMING_TENDENCY_DEFAULT:   float = 0.30
SHIDO_FARMING_PER_TICK_PROB:    float = 0.10

# -- STAMINA_DESPERATION --
# Fires when tori is cardio-cooked, has eaten at least one shido, and can't
# physically generate kuzushi this tick (hand/grip output is low). A tired,
# already-penalized fighter will fall into anything to buy a breather.
# Calibration note: 0.40 cardio puts tori in the bottom third. Below that,
# the fighter is visibly gassed — real judo condition for this motivation.
STAMINA_DESPERATION_CARDIO_MAX:  float = 0.50
STAMINA_DESPERATION_MIN_SHIDOS:  int   = 1
STAMINA_DESPERATION_HAND_FAT_MIN: float = 0.40
STAMINA_DESPERATION_PER_TICK_PROB: float = 0.20

# HAJ-74 — Golden-score relaxes the gates. The match clock is gone, the
# fighters know the next score (or third shido) ends it, and a low-conditioned
# judoka starts forcing desperate ippon attempts even without the regulation
# shido prerequisite. Composure is suppressed in the GS-low-stamina window —
# represented here as relaxed gates and a higher per-tick probability.
GS_STAMINA_DESPERATION_CARDIO_MAX:  float = 0.65
GS_STAMINA_DESPERATION_MIN_SHIDOS:  int   = 0
GS_STAMINA_DESPERATION_HAND_FAT_MIN: float = 0.25
GS_STAMINA_DESPERATION_PER_TICK_PROB: float = 0.40

# HAJ-74 — Golden-score damps SHIDO_FARMING. The v2 spec calls for
# "tactical behavior shifts away from defensive shido-baiting and toward
# technique commitment." A real fighter in golden score does not pose-attack
# to fish for opponent passivity shidos; they commit. We multiply the per-
# tick probability by this factor (and zero the threshold-based tendency
# floor) so farming still has a residual chance for low-IQ habit but the
# population behavior shifts toward real commits.
GS_SHIDO_FARMING_DAMPER: float = 0.20

# Priority order of drop-variant throws for any non-scoring motivation, most
# preferred first. Lowest-commitment entries in standard vocabularies: fast
# recovery-to-stance is the whole point, so shin-block (TAI_OTOSHI),
# foot-sweep (KO_UCHI_GARI), drop-seoi, and inner-reap (O_UCHI_GARI) over
# hip-fulcrum or high-amplitude throws.
FALSE_ATTACK_PREFERENCES: tuple[ThrowID, ...] = (
    ThrowID.TAI_OTOSHI,
    ThrowID.KO_UCHI_GARI,
    ThrowID.SEOI_NAGE,
    ThrowID.O_UCHI_GARI,
)

# Gate-bypass reason string for the commit log — read by match.py into the
# same tag-suffix pipeline the desperation path already uses.
REASON_INTENTIONAL_FALSE_ATTACK: str = "intentional_false_attack"

# HAJ-57 — uke's hip-block defensive rung tuning. Fire probability scales
# with fight_iq so a high-IQ defender reliably blocks while a low-IQ one
# may fail to read tori's commit and eat the throw. Posture-gated:
# trunk_sagittal must be <= 0 (upright or back-leaning — not bent forward).
HIP_BLOCK_FIRE_PROB_AT_FULL_IQ: float = 0.85


# ---------------------------------------------------------------------------
# TOP-LEVEL ENTRY POINT
# ---------------------------------------------------------------------------
def select_actions(
    judoka: "Judoka",
    opponent: "Judoka",
    graph: "GripGraph",
    kumi_kata_clock: int,
    rng: random.Random | None = None,
    defensive_desperation: bool = False,
    opponent_kumi_kata_clock: int = 0,
    opponent_in_progress_throw: Optional[ThrowID] = None,
    desperation_jitter: Optional[dict] = None,
    current_tick: int = 0,
    position: Optional[Position] = None,
    golden_score: bool = False,
    catalog: Optional[dict[str, "TechniqueDefinition"]] = None,
) -> list[Action]:
    """Return the judoka's chosen actions for this tick.

    Implements the Part 3.3 priority ladder. Returns 1-2 Actions, or a
    single-element list containing COMMIT_THROW. HAJ-128 may append a
    STEP locomotion action to the result when positional intent fires.

    HAJ-141 — `position` lets the ladder skip the commit/grip-sub-loop
    rungs entirely while the dyad is in STANDING_DISTANT (closing phase).
    No grip exists, no commit is reachable; the only legal output is the
    REACH pair that drives engagement. None preserves legacy behavior
    for tests that call select_actions directly without a Match context.

    HAJ-159 — closing-phase output now also includes a STEP_IN action
    toward the opponent (tactical_intent=closing) when the fighters are
    still outside engagement distance, so the per-tick MOVE event surfaces
    and the viewer sees CoMs converging instead of teleporting.

    HAJ-163 — STEP_IN is no longer the only closing action. The
    closing-phase selector picks among STEP_IN, CIRCLE_CLOSING,
    LATERAL_APPROACH, BAIT_RETREAT based on fighter attributes
    (aggressive / technical facets, fight_iq, positional_style) so
    the closing trajectory varies match-to-match instead of always
    being a head-on car crash.

    HAJ-207 — when `catalog` is supplied, the commit rung consults
    `stage1_available_techniques` against the catalog's per-technique
    grip signatures before firing a throw. The Stage 1 set replaces
    the priority-laddered grip-presence checks: an empty available
    set means no throw fires this tick regardless of perceived
    signature, which is the gating mechanism that resolves HAJ-199
    (heavy opponent grip configurations producing inappropriate
    commits). When `catalog` is None the legacy gate path is used.
    """
    # HAJ-141 — closing-phase short-circuit. During STANDING_DISTANT the
    # only legal action is to reach for engagement; the commit / drive /
    # rung-2-bypass paths assume an established dyad and must not fire.
    # HAJ-163 — pick a closing-phase trajectory variant via the
    # attribute-driven selector. REACH still fires every tick so the
    # engagement_ticks counter advances even when the chosen step is
    # a pure-lateral or bait-retreat.
    if position == Position.STANDING_DISTANT:
        actions = _reach_actions(judoka)
        r = rng if rng is not None else random
        closing = _select_closing_step_action(judoka, opponent, r)
        if closing is not None:
            actions = list(actions) + [closing]
        return actions

    r = rng if rng is not None else random
    actions = _select_grip_actions(
        judoka, opponent, graph, kumi_kata_clock, r,
        defensive_desperation=defensive_desperation,
        opponent_kumi_kata_clock=opponent_kumi_kata_clock,
        opponent_in_progress_throw=opponent_in_progress_throw,
        desperation_jitter=desperation_jitter,
        current_tick=current_tick,
        golden_score=golden_score,
        catalog=catalog,
    )
    # HAJ-128 — locomotion is additive, never replaces grip work. Skip
    # when a commit is in flight (commits are exclusive in the ladder)
    # or when the fighter is stunned.
    if any(a.kind == ActionKind.COMMIT_THROW for a in actions):
        return actions
    if judoka.state.stun_ticks > 0:
        return actions
    # HAJ-135 — multi-tick plan integration. After the standard ladder
    # has produced its actions, consult the fighter's current plan (or
    # form one if eligible). When a plan step fires, substitute it for
    # the secondary slot so the kuzushi events stack inside the decay
    # window. Sequencing-precision modulation is what produces the
    # elite-vs-novice combo emergence: high-skill fighters fire the
    # next step almost every tick; low-skill fighters delay/drop.
    actions = _apply_plan_layer(
        judoka, opponent, graph, kumi_kata_clock, r, actions, current_tick,
    )
    step_action = _maybe_emit_step(
        judoka, opponent, graph, r,
        current_tick=current_tick,
        opponent_in_progress_throw=opponent_in_progress_throw,
    )
    if step_action is not None:
        actions = list(actions) + [step_action]
    return actions


def _apply_plan_layer(
    judoka: "Judoka",
    opponent: "Judoka",
    graph: "GripGraph",
    kumi_kata_clock: int,
    rng: random.Random,
    actions: list[Action],
    current_tick: int,
) -> list[Action]:
    """HAJ-135 — plan formation + step execution layer.

    Three responsibilities per tick:
      1. Abandon any active plan whose preconditions broke.
      2. Form a new plan when the gate fires (no plan, fight_iq above
         threshold, kumi-kata clock past stalemate floor).
      3. Resolve the current plan's next step. On 'fire', substitute
         the secondary action slot. On 'drop' / 'complete', advance or
         clear the plan and leave actions untouched.

    Plans never preempt the primary action (the standard PULL drive)
    so an elite fighter's combo runs as drive + planned-step-of-tick,
    accumulating both the physics force and the plan-stage event.
    """
    from intent import (
        Plan, should_form_plan, should_abandon_plan, next_plan_action,
    )

    # 1. Abandonment.
    has_in_progress = False  # action_selection layer doesn't see throws_in_progress;
    #    Match's own _strip_commits_if_in_progress already drops re-commits, so
    #    plans on a fighter mid-throw will be cleared the next tick by stun
    #    or by their commit rung exclusion. Pass False here.
    if judoka.current_plan is not None and should_abandon_plan(
        judoka.current_plan, judoka, opponent, graph, has_in_progress,
    ):
        judoka.current_plan = None

    # 2. Formation.
    if judoka.current_plan is None:
        new_plan = should_form_plan(
            judoka, opponent, graph, kumi_kata_clock, rng=rng,
        )
        if new_plan is not None:
            new_plan.formed_at_tick = current_tick
            new_plan.last_advanced_tick = current_tick
            judoka.current_plan = new_plan

    # 3. Step resolution.
    plan = judoka.current_plan
    if plan is None:
        return actions
    action, outcome = next_plan_action(
        plan, judoka, opponent, graph, rng, current_tick=current_tick,
    )
    if outcome == "fire":
        # Substitute the secondary slot. Primary (PULL drive) is preserved.
        plan.step_index += 1
        plan.last_advanced_tick = current_tick
        if action is not None:
            new_actions = [actions[0]] if actions else []
            new_actions.append(action)
            return new_actions
        return actions
    if outcome == "drop":
        plan.step_index += 1
        plan.last_advanced_tick = current_tick
        return actions
    if outcome == "complete":
        judoka.current_plan = None
        return actions
    # 'delay' — leave plan and actions untouched.
    return actions


def _select_grip_actions(
    judoka: "Judoka",
    opponent: "Judoka",
    graph: "GripGraph",
    kumi_kata_clock: int,
    r: random.Random,
    *,
    defensive_desperation: bool = False,
    opponent_kumi_kata_clock: int = 0,
    opponent_in_progress_throw: Optional[ThrowID] = None,
    desperation_jitter: Optional[dict] = None,
    current_tick: int = 0,
    golden_score: bool = False,
    catalog: Optional[dict[str, "TechniqueDefinition"]] = None,
) -> list[Action]:
    """The grip / commit / probe priority ladder. Pre-HAJ-128 this was
    the body of select_actions; locomotion now wraps it.

    HAJ-35/36: `defensive_desperation` is computed Match-side (requires
    cross-tick history the ladder can't see) and bypasses the grip-
    presence gate when True. Offensive desperation is derived locally
    from composure + kumi_kata_clock.

    HAJ-57: `opponent_in_progress_throw` is the throw_id the opponent
    has mid-flight (None if no attempt active). When set and the throw
    is hip-loading, the defensive-block rung fires BLOCK_HIP before any
    grip/commit work — provided the judoka is upright (posture gate)
    and a fight_iq-scaled perception roll succeeds.
    """

    # Rung 1: stunned → defensive-only (v0.1: just idle).
    if judoka.state.stun_ticks > 0:
        return _defensive_fallback(judoka)

    # HAJ-57 — defensive hip-block. Fires before grip/commit work because
    # interrupting an in-progress hip-loading throw is the highest-priority
    # defensive action available. Posture-gated: bent-over uke can't drive
    # hips forward.
    if opponent_in_progress_throw is not None:
        block = _try_hip_block(judoka, opponent_in_progress_throw, r)
        if block is not None:
            return [block]

    own_edges = graph.edges_owned_by(judoka.identity.name)
    opp_edges = graph.edges_owned_by(opponent.identity.name)

    # Engagement precedes commit: a throw requires at least pocket contact.
    # Without this, low-fight_iq perception noise on a Couple throw's always-
    # on body/posture dimensions lifts the perceived signature over the commit
    # threshold before any grip exists, and the novice throws from thin air.
    if not own_edges and not defensive_desperation:
        return _reach_actions(judoka)

    # Rung 2: commit if a throw is perceived available AND the grip-presence
    # gate passes (or desperation bypasses it).
    offensive_desperation = is_desperation_state(
        judoka, kumi_kata_clock, jitter=desperation_jitter,
    )
    commit = _try_commit(
        judoka, opponent, graph, r,
        offensive_desperation=offensive_desperation,
        defensive_desperation=defensive_desperation,
        kumi_kata_clock=kumi_kata_clock,
        opponent_kumi_kata_clock=opponent_kumi_kata_clock,
        current_tick=current_tick,
        golden_score=golden_score,
        catalog=catalog,
    )
    if commit is not None:
        return [commit]

    # No edges + no commit path open (e.g. defensive desperation that
    # couldn't find a throw) — fall back to reach.
    if not own_edges:
        return _reach_actions(judoka)

    # Rung 5: kumi-kata clock nearing shido → escalate.
    escalated = (kumi_kata_clock >= DESPERATION_KUMI_CLOCK)

    # If every grip is still shallow (POCKET/SLIPPING), spend both actions
    # seating them — deepen primary, strip the opponent's strongest grip.
    deep_enough = [e for e in own_edges
                   if e.depth_level in (GripDepth.STANDARD, GripDepth.DEEP)]
    if not deep_enough:
        # HAJ-138 — rotate which shallow edge to deepen. Pre-fix, this
        # always picked own_edges[0] (the lapel, created first at
        # engagement), so the sleeve never advanced and the log was an
        # endless string of "deepens LAPEL_HIGH" lines. Rotate through
        # the shallow edges by tick so both hands get a turn, with the
        # established_tick as a stable secondary key so the order is
        # deterministic across calls.
        shallow_sorted = sorted(
            own_edges,
            key=lambda e: (e.depth_level.modifier(), e.established_tick),
        )
        edge_to_deepen = shallow_sorted[current_tick % len(shallow_sorted)]
        out: list[Action] = [deepen(edge_to_deepen)]
        if opp_edges:
            target = max(opp_edges, key=lambda e: e.depth_level.modifier())
            strip_hand = _free_hand(judoka) or "right_hand"
            out.append(strip(strip_hand, target))
        else:
            out.append(hold_connective(_primary_hand(judoka)))
        return out

    # Rung 6: fatigued + composed → recover connective.
    hand_fat = _avg_hand_fatigue(judoka)
    if hand_fat > HIGH_FATIGUE_THRESHOLD and not escalated:
        return [
            hold_connective("right_hand"),
            hold_connective("left_hand"),
        ]

    # Rungs 4/5 overlap: drive through the seated grip toward kuzushi.
    drive_mag = DRIVE_MAGNITUDE_N if not escalated else DRIVE_MAGNITUDE_N * 1.3

    # Direction convention: actions carry a force vector in world frame that
    # acts ON THE OPPONENT. PULL draws opponent toward attacker → opp→me;
    # PUSH drives opponent away → me→opp.
    attacker_to_opp = _direction_toward(judoka, opponent)
    pull_dir = (-attacker_to_opp[0], -attacker_to_opp[1])
    push_dir = attacker_to_opp

    primary = deep_enough[0]

    # HAJ-133 — when the grip war is stalemated (seated grips but no
    # progress), substitute the secondary drive for a foot-attack setup
    # at fight_iq-gated probability. Per grip-as-cause.md §3.5: when you
    # can't win the grip war directly, change the question — force uke
    # to defend the legs so attention shifts off the grip exchange.
    foot_attack = _maybe_emit_foot_attack(
        judoka, opponent, kumi_kata_clock, r, attacker_to_opp,
    )

    # Secondary action: deepen a shallow grip if any, else push with 2nd hand.
    shallow = [e for e in own_edges if e.depth_level != GripDepth.DEEP
               and e is not primary]
    out = [pull(primary.grasper_part.value, pull_dir, drive_mag)]
    if foot_attack is not None:
        # Foot attack takes the secondary slot — it's a parallel kuzushi
        # generator, not a replacement for the primary pull.
        out.append(foot_attack)
    elif shallow:
        out.append(deepen(shallow[0]))
    elif len(own_edges) > 1:
        secondary = own_edges[1] if own_edges[0] is primary else own_edges[0]
        out.append(push(secondary.grasper_part.value, push_dir, drive_mag * 0.5))
    return out


# ---------------------------------------------------------------------------
# HAJ-133 — FOOT_ATTACK FAMILY (parallel kuzushi generator)
# ---------------------------------------------------------------------------
# A grip-stalemated fighter (seated grips, kumi-kata clock advancing,
# no commit-quality signature) can substitute a foot attack for the
# secondary drive. Real-judo strategy: force uke to defend the legs so
# attention shifts off the grip exchange and strip windows open.
#
# Activation gate (cumulative): grip war is stalemated AND fight_iq is
# above threshold AND a per-tick probability roll fires. Stalemate proxy:
# kumi-kata clock has been advancing for at least STALEMATE_CLOCK_TICKS,
# which means own grips have existed without an attack for a while.

# Earliest clock tick at which foot attacks become available — gives the
# initial grip exchange a few ticks before stalemate logic kicks in.
# Tuned to fire after grips seat and 2-3 deepening ticks have elapsed
# without a commit-quality signature; calibration target for HAJ-A.7 once
# more match telemetry exists.
FOOT_ATTACK_STALEMATE_CLOCK_MIN: int = 3
# Below this fight_iq value, foot-attack setups are too sophisticated;
# white belts rely on grip-only drives.
FOOT_ATTACK_MIN_FIGHT_IQ: int = 4
# Per-tick base probability (when stalemate gate is met). Modulated up
# by fight_iq so a high-IQ fighter changes the question more readily.
FOOT_ATTACK_BASE_PROB: float = 0.12
FOOT_ATTACK_IQ_PROB_BONUS: float = 0.04   # per fight_iq point above min


def _maybe_emit_foot_attack(
    judoka: "Judoka",
    opponent: "Judoka",
    kumi_kata_clock: int,
    rng: random.Random,
    attacker_to_opp: tuple[float, float],
) -> Optional[Action]:
    """Return a FOOT_ATTACK family Action if this tick passes the
    stalemate gate and the fight_iq-scaled probability roll. Else None.

    The foot is the trailing one (so the action is a deliberate stretch
    of the rear leg, not the planted lead). The kind rotates among the
    three setup variants based on the kumi-kata clock so a stalemated
    fighter cycles through different threats rather than spamming one.
    """
    if kumi_kata_clock < FOOT_ATTACK_STALEMATE_CLOCK_MIN:
        return None
    if judoka.capability.fight_iq < FOOT_ATTACK_MIN_FIGHT_IQ:
        return None
    iq_excess = max(0, judoka.capability.fight_iq - FOOT_ATTACK_MIN_FIGHT_IQ)
    prob = min(0.6, FOOT_ATTACK_BASE_PROB + iq_excess * FOOT_ATTACK_IQ_PROB_BONUS)
    if rng.random() >= prob:
        return None
    # Pick the trailing foot so the lead foot stays planted (the same
    # convention HAJ-128 locomotion uses). The attack vector is forward
    # and lateral — toward the opponent with a half-perpendicular twist
    # so the sweep crosses uke's centerline rather than chasing them.
    fx, fy = attacker_to_opp
    # Lateral component alternates per-tick via the clock for variety.
    side = 1.0 if (kumi_kata_clock % 2 == 0) else -1.0
    perp_x, perp_y = -fy * side, fx * side
    attack_vec = (fx * 0.7 + perp_x * 0.5, fy * 0.7 + perp_y * 0.5)

    bs = judoka.state.body_state
    cx, cy = bs.com_position
    dx, dy = attack_vec
    # Trailing foot relative to attack direction (smaller projection).
    lx, ly = bs.foot_state_left.position
    rx, ry = bs.foot_state_right.position
    left_proj  = (lx - cx) * dx + (ly - cy) * dy
    right_proj = (rx - cx) * dx + (ry - cy) * dy
    foot = "left_foot" if left_proj < right_proj else "right_foot"

    # Cycle through the three setup kinds based on the clock tick.
    # Foot sweep on even ticks, leg attack on every-third, disruptive
    # step otherwise — produces a plausible mix without a separate RNG.
    kind_index = kumi_kata_clock % 3
    if kind_index == 0:
        return foot_sweep_setup(foot, attack_vec, magnitude=0.25)
    if kind_index == 1:
        return leg_attack_setup(foot, attack_vec, magnitude=0.25)
    return disruptive_step(foot, attack_vec, magnitude=0.25)


# ---------------------------------------------------------------------------
# RUNGS / HELPERS
# ---------------------------------------------------------------------------
def _defensive_fallback(judoka: "Judoka") -> list[Action]:
    # Stunned: minimal-fatigue action.
    return [hold_connective("right_hand"), hold_connective("left_hand")]


def _try_hip_block(
    judoka: "Judoka", opponent_throw_id: ThrowID, rng: random.Random,
) -> Optional[Action]:
    """HAJ-57 — return a BLOCK_HIP Action if uke can and chooses to block
    a hip-loading throw this tick, else None.

    Three gates, all must pass:
      1. Throw is hip-loading. Reads `body_part_requirement.hip_loading`
         off the worked template; legacy throws (no template) can't be
         blocked.
      2. Posture: trunk_sagittal <= 0 (upright or back-leaning). A
         bent-over uke's hips are out of position — they can't drive
         them forward into tori's hip line.
      3. Perception roll: fight_iq-scaled probability. iq=10 fires at
         HIP_BLOCK_FIRE_PROB_AT_FULL_IQ; iq=0 never fires.
    """
    from worked_throws import worked_template_for
    template = worked_template_for(opponent_throw_id)
    if template is None:
        return None
    bpr = getattr(template, "body_part_requirement", None)
    if bpr is None or not getattr(bpr, "hip_loading", False):
        return None
    if judoka.state.body_state.trunk_sagittal > 0.0:
        return None
    iq = max(0.0, min(10.0, float(judoka.capability.fight_iq))) / 10.0
    fire_p = HIP_BLOCK_FIRE_PROB_AT_FULL_IQ * iq
    if rng.random() >= fire_p:
        return None
    return block_hip()


def _reach_actions(judoka: "Judoka") -> list[Action]:
    dom = judoka.identity.dominant_side
    is_right = dom == DominantSide.RIGHT
    lapel_target  = GripTarget.LEFT_LAPEL if is_right else GripTarget.RIGHT_LAPEL
    sleeve_target = GripTarget.RIGHT_SLEEVE if is_right else GripTarget.LEFT_SLEEVE
    return [
        reach("right_hand" if is_right else "left_hand", GripTypeV2.LAPEL_HIGH, lapel_target),
        # HAJ-53 — default sleeve reach is HIGH (elbow/tricep): the standard
        # hikite grip preferred by Seoi-nage, Uchi-mata, harai/hip throws,
        # and the rest of the vocabulary. Tai-otoshi specialists who want
        # SLEEVE_LOW will need a Ring-2 coach instruction layer.
        reach("left_hand"  if is_right else "right_hand", GripTypeV2.SLEEVE_HIGH, sleeve_target),
    ]


# HAJ-159 — closing-phase STEP_IN constants. STANDING_DISTANT pose seats
# fighters ~3 m apart (CoM to CoM); engagement is treated as ~1 m; the
# per-tick STEP_IN closes the gap. With both fighters stepping toward
# each other, total per-tick closure ≈ CLOSING_STEP_MAGNITUDE_M, so a
# 0.66 m base step + 3 closing-phase ticks covers the ~2 m of distance
# without overshoot. Once the gap is at engagement distance the helper
# returns None and only the REACH pair fires.
ENGAGEMENT_DISTANCE_M:    float = 1.0
CLOSING_STEP_MAGNITUDE_M: float = 0.66


def _closing_step_action(
    judoka: "Judoka", opponent: "Judoka",
) -> Optional[Action]:
    """HAJ-159 — STEP_IN toward the opponent during STANDING_DISTANT.

    Returns a STEP action with tactical_intent=closing, sized so the
    last step lands the dyad at engagement distance rather than past it.
    Returns None when the fighters are already inside engagement
    distance (the closing-phase REACH alone is enough; no point firing
    a zero-magnitude step that still pays the cardio cost).
    """
    bs = judoka.state.body_state
    cx, cy = bs.com_position
    ox, oy = opponent.state.body_state.com_position
    dx, dy = ox - cx, oy - cy
    dist = (dx * dx + dy * dy) ** 0.5
    gap  = dist - ENGAGEMENT_DISTANCE_M
    if gap <= 0.0:
        return None
    # HAJ-142 — edge pressure. When the opponent is in the WARNING
    # band and the actor's fight_iq is high enough to weaponize it,
    # shift the closing direction off the dyad axis and toward the
    # opponent's nearest edge: the goal becomes "drive them out,"
    # not just "close on their CoM."
    if _edge_pressure_active(judoka, opponent):
        dx, dy = _edge_pressure_step_direction(opponent, (dx, dy))
    base_mag = min(CLOSING_STEP_MAGNITUDE_M, gap)
    return _step_action(
        judoka, (dx, dy), base_mag,
        tactical_intent=TACTICAL_INTENT_CLOSING,
    )


# HAJ-142 — edge-pressure gates. fight_iq threshold reflects the
# ticket: white belts don't use edge pressure consciously. The bias
# is only applied when the opponent has already drifted into WARNING
# (the "yellow" band); WORKING / CENTER opponents don't need it.
EDGE_PRESSURE_FIGHT_IQ_THRESHOLD: int = 6


def _edge_pressure_active(actor: "Judoka", opponent: "Judoka") -> bool:
    """HAJ-142 — True when `actor` should weaponize edge geometry on
    this STEP. Conditions:
      - opponent's current region is WARNING
      - actor's fight_iq >= EDGE_PRESSURE_FIGHT_IQ_THRESHOLD
    Reads the live engine state every call (pure)."""
    from match import region_of
    from enums import MatRegion
    if region_of(opponent) is not MatRegion.WARNING:
        return False
    iq = getattr(actor.capability, "fight_iq", 0)
    return iq >= EDGE_PRESSURE_FIGHT_IQ_THRESHOLD


def _edge_pressure_step_direction(
    opponent: "Judoka", base_dxdy: tuple[float, float],
) -> tuple[float, float]:
    """HAJ-142 — compose the closing direction with a bias toward the
    opponent's nearest edge. Half closing-axis (so the actor still
    closes the gap) and half edge-direction (so the opponent gets
    pushed further out instead of recovering toward center). Returns a
    non-normalized vector — magnitude is set by the caller."""
    from match import MAT_HALF_WIDTH
    bx, by = base_dxdy
    base_norm = (bx * bx + by * by) ** 0.5 or 1.0
    bx_n, by_n = bx / base_norm, by / base_norm
    ox, oy = opponent.state.body_state.com_position
    # Edge direction: same sign as opponent's CoM, magnitude scaled to
    # the boundary distance. A larger excursion → stronger bias.
    edge_x = (1.0 if ox >= 0.0 else -1.0) * (
        abs(ox) / MAT_HALF_WIDTH if MAT_HALF_WIDTH > 0 else 0.0
    )
    edge_y = (1.0 if oy >= 0.0 else -1.0) * (
        abs(oy) / MAT_HALF_WIDTH if MAT_HALF_WIDTH > 0 else 0.0
    )
    edge_norm = (edge_x * edge_x + edge_y * edge_y) ** 0.5 or 1.0
    edge_x /= edge_norm
    edge_y /= edge_norm
    return (
        bx_n * 0.5 + edge_x * 0.5,
        by_n * 0.5 + edge_y * 0.5,
    )


# HAJ-163 — closing-phase trajectory siblings to STEP_IN. Each takes
# the dyad-axis vector (judoka → opponent) and produces a STEP whose
# direction blends closing and lateral components in a different mix:
#
#   CIRCLE_CLOSING    : 60% closing + 40% lateral — diagonal arc
#   LATERAL_APPROACH  : 0% closing + 100% lateral — pure side-step
#   BAIT_RETREAT      : negative closing — small step away from opponent
#
# The lateral side (left or right of the closing vector) is randomized
# so consecutive matches with the same fighter pair don't reproduce
# identical closing trajectories.

CIRCLE_CLOSING_FORWARD_FRAC: float = 0.6   # closing component weight
CIRCLE_CLOSING_LATERAL_FRAC: float = 0.4   # lateral component weight
LATERAL_APPROACH_MAGNITUDE_M: float = 0.55  # foot-meters per pure-lateral step
BAIT_RETREAT_MAGNITUDE_M:    float = 0.30  # foot-meters per backward step
BAIT_RETREAT_MIN_GAP_M:      float = 1.5   # only fire when there's room to retreat


def _lateral_unit(
    closing_unit: tuple[float, float], rng: random.Random,
) -> tuple[float, float]:
    """Pick a unit vector perpendicular to the closing direction.
    Side (left vs right) is random so consecutive matches don't
    reproduce identical trajectories."""
    cx, cy = closing_unit
    # Two perpendiculars: (-cy, cx) is the +90° rotation; (cy, -cx) is -90°.
    if rng.random() < 0.5:
        return (-cy, cx)
    return (cy, -cx)


def _closing_unit(
    judoka: "Judoka", opponent: "Judoka",
) -> Optional[tuple[float, float, float]]:
    """Return (unit_x, unit_y, dist) for the judoka → opponent vector,
    or None if the two CoMs coincide."""
    bs = judoka.state.body_state
    cx, cy = bs.com_position
    ox, oy = opponent.state.body_state.com_position
    dx, dy = ox - cx, oy - cy
    dist = (dx * dx + dy * dy) ** 0.5
    if dist <= 0.0:
        return None
    return (dx / dist, dy / dist, dist)


def _circle_closing_step_action(
    judoka: "Judoka", opponent: "Judoka", rng: random.Random,
) -> Optional[Action]:
    """HAJ-163 — diagonal close. Step vector blends closing and lateral
    components so the fighter arcs into engagement instead of charging
    straight in. Returns None inside engagement distance (same gating
    as STEP_IN — once close enough, the diagonal arc no longer makes
    spatial sense)."""
    cu = _closing_unit(judoka, opponent)
    if cu is None:
        return None
    ux, uy, dist = cu
    gap = dist - ENGAGEMENT_DISTANCE_M
    if gap <= 0.0:
        return None
    lx, ly = _lateral_unit((ux, uy), rng)
    blend_x = CIRCLE_CLOSING_FORWARD_FRAC * ux + CIRCLE_CLOSING_LATERAL_FRAC * lx
    blend_y = CIRCLE_CLOSING_FORWARD_FRAC * uy + CIRCLE_CLOSING_LATERAL_FRAC * ly
    base_mag = min(CLOSING_STEP_MAGNITUDE_M, gap)
    return _step_action(
        judoka, (blend_x, blend_y), base_mag,
        tactical_intent=TACTICAL_INTENT_CIRCLE_CLOSING,
    )


def _lateral_approach_step_action(
    judoka: "Judoka", opponent: "Judoka", rng: random.Random,
) -> Optional[Action]:
    """HAJ-163 — pure lateral step. Finds a better angle without
    reducing the dyad-axis distance. Closing happens on subsequent
    ticks (or via the opponent's STEP_IN); engagement still fires
    after the reach-tick counter completes."""
    cu = _closing_unit(judoka, opponent)
    if cu is None:
        return None
    ux, uy, _dist = cu
    lx, ly = _lateral_unit((ux, uy), rng)
    return _step_action(
        judoka, (lx, ly), LATERAL_APPROACH_MAGNITUDE_M,
        tactical_intent=TACTICAL_INTENT_LATERAL_APPROACH,
    )


def _bait_retreat_step_action(
    judoka: "Judoka", opponent: "Judoka",
) -> Optional[Action]:
    """HAJ-163 — small backward step. Used by counter-fighters to draw
    the opponent into a committed approach. Caps at small magnitude
    (smaller than STEP_IN) and only fires when there's room to retreat
    without crowding the boundary."""
    cu = _closing_unit(judoka, opponent)
    if cu is None:
        return None
    ux, uy, dist = cu
    if dist < BAIT_RETREAT_MIN_GAP_M:
        # Already at or near engagement — no point retreating.
        return None
    return _step_action(
        judoka, (-ux, -uy), BAIT_RETREAT_MAGNITUDE_M,
        tactical_intent=TACTICAL_INTENT_BAIT_RETREAT,
    )


# Closing-phase selector weights. Base weights are baseline preference
# for each variant; per-fighter modulators add on top. The total is
# normalized at random-pick time, so absolute values don't matter —
# only the ratios do.
_CLOSING_SELECTOR_BASE_WEIGHTS: dict[str, float] = {
    "STEP_IN":          0.40,
    "CIRCLE_CLOSING":   0.20,
    "LATERAL_APPROACH": 0.10,
    "BAIT_RETREAT":     0.05,
}


def _select_closing_step_action(
    judoka: "Judoka", opponent: "Judoka", rng: random.Random,
) -> Optional[Action]:
    """HAJ-163 — pick one closing-phase step variant for this fighter
    on this tick.

    Weighting is attribute-driven:
      - aggressive facet → STEP_IN (head-on) and CIRCLE_CLOSING (arc).
      - technical facet → CIRCLE_CLOSING (find the angle, then close).
      - high fight_iq → LATERAL_APPROACH and BAIT_RETREAT (read the
        opponent, set up a counter or angle).
      - positional_style:
          PRESSURE       → strong STEP_IN bias (drive forward)
          DEFENSIVE_EDGE → BAIT_RETREAT and LATERAL bias (counter setup)
          HOLD_CENTER    → CIRCLE_CLOSING bias (work the angles)

    Falls back to STEP_IN when the chosen variant returns None
    (typically because the helper's distance gate fires) so the
    closing phase always emits *some* MOVE event when there's gap to
    cover.
    """
    facets    = judoka.identity.personality_facets
    aggressive = float(facets.get("aggressive", 5))
    technical  = float(facets.get("technical", 5))
    iq         = float(judoka.capability.fight_iq)
    style      = judoka.identity.positional_style

    weights = dict(_CLOSING_SELECTOR_BASE_WEIGHTS)
    weights["STEP_IN"]          += 0.06 * aggressive
    weights["CIRCLE_CLOSING"]   += 0.04 * aggressive + 0.06 * technical
    weights["LATERAL_APPROACH"] += 0.05 * iq
    weights["BAIT_RETREAT"]     += 0.04 * iq

    if style == PositionalStyle.PRESSURE:
        weights["STEP_IN"] += 0.50
    elif style == PositionalStyle.DEFENSIVE_EDGE:
        weights["BAIT_RETREAT"]     += 0.30
        weights["LATERAL_APPROACH"] += 0.20
    elif style == PositionalStyle.HOLD_CENTER:
        weights["CIRCLE_CLOSING"] += 0.20

    # Distance-aware bias: when the dyad is wide, down-weight the
    # non-closing variants so spatial convergence keeps pace with the
    # tick-counter engagement gate. Scaled smoothly so trajectory
    # variety survives at moderate distances — this just suppresses
    # the pathological "both fighters pick lateral every tick" pattern
    # that would let grips seat across an unclosed gap.
    #
    # HAJ-164 follow-up — strengthened ramp (0.6 → 0.9) so non-closing
    # variants near-zero out at the full distant pose. Pre-fix at full
    # distant the lateral / bait weights still cleared 5–8 % each, so
    # two consecutive bait_retreats within the engagement window were
    # not rare; combined with the new gap-gate on grip seating they
    # could push first-seat ticks past the safety-max bound. Killing
    # almost all non-closing weight at >2.5 m gap lets the 0.9 ramp
    # carry the convergence guarantee.
    cu = _closing_unit(judoka, opponent)
    dist = cu[2] if cu is not None else ENGAGEMENT_DISTANCE_M
    if dist > ENGAGEMENT_DISTANCE_M:
        # 0 at engagement, 1.0 at the full distant pose (~3 m).
        closing_pressure = max(0.0, min(1.0,
            (dist - ENGAGEMENT_DISTANCE_M) / 2.0,
        ))
        non_closing_scale = 1.0 - 0.9 * closing_pressure
        weights["LATERAL_APPROACH"] *= non_closing_scale
        weights["BAIT_RETREAT"]     *= non_closing_scale

    total = sum(weights.values())
    if total <= 0.0:
        return _closing_step_action(judoka, opponent)
    pick = rng.random() * total
    cumulative = 0.0
    chosen = "STEP_IN"
    for kind, w in weights.items():
        cumulative += w
        if pick <= cumulative:
            chosen = kind
            break

    if chosen == "STEP_IN":
        action = _closing_step_action(judoka, opponent)
    elif chosen == "CIRCLE_CLOSING":
        action = _circle_closing_step_action(judoka, opponent, rng)
    elif chosen == "LATERAL_APPROACH":
        action = _lateral_approach_step_action(judoka, opponent, rng)
    elif chosen == "BAIT_RETREAT":
        action = _bait_retreat_step_action(judoka, opponent)
    else:
        action = _closing_step_action(judoka, opponent)

    # Fallback to STEP_IN when the chosen variant declined (typically
    # because of its own distance gate). Keeps the MOVE-events-during-
    # closing invariant intact.
    if action is None:
        action = _closing_step_action(judoka, opponent)
    return action


def _try_commit(
    judoka: "Judoka",
    opponent: "Judoka",
    graph: "GripGraph",
    rng: random.Random,
    *,
    offensive_desperation: bool = False,
    defensive_desperation: bool = False,
    kumi_kata_clock: int = 0,
    opponent_kumi_kata_clock: int = 0,
    current_tick: int = 0,
    golden_score: bool = False,
    catalog: Optional[dict[str, "TechniqueDefinition"]] = None,
) -> Optional[Action]:
    """If there's a throw whose *perceived* signature clears the commit
    threshold AND the formal grip-presence gate allows it (or is bypassed
    by desperation), return a COMMIT_THROW Action for it. Otherwise, try
    each of the four non-scoring motivation pathways (HAJ-67).

    Pathway priority (first match wins):
      1. Normal signature-clears-threshold commit — the classical path.
      2. Offensive desperation — handled via the grip-presence gate bypass
         inside the main ranked-candidates loop.
      3. CLOCK_RESET         — HAJ-49 legacy; kumi-kata clock in pre-shido zone.
      4. STAMINA_DESPERATION — cooked fighter, already penalized, can't drive.
      5. GRIP_ESCAPE         — grip war lost, composure slipping.
      6. SHIDO_FARMING       — pressure a passive opponent into their own shido.

    Perceived-signature cache (dict[ThrowID, float]) is built once from the
    ranked candidates and shared across motivation predicates so we don't
    recompute the same scores four times per tick.

    The returned Action carries the motivation label so Match can surface
    it on the commit log line and the failure-outcome router can route to
    TACTICAL_DROP_RESET (HAJ-50).

    HAJ-207 — when `catalog` is supplied, the path becomes:
      a. Compute stage1_available_techniques against the catalog.
      b. If the available set is empty, no scoring commit fires this
         tick (regardless of perceived signature). Non-scoring
         motivations are still considered for the false-attack path.
      c. Otherwise rank candidates by perceived signature as before
         and additionally filter by Stage 1 membership.
      d. Among Stage-1 survivors above COMMIT_THRESHOLD, Stage 2
         picks one via kuzushi-vector match + proficiency weighting +
         a fight-IQ / cardio stochastic gate.
    Desperation flags keep their grip-presence gate bypass — the
    catalog filter is suppressed in that case so a cornered fighter
    can still attempt a low-signature drop variant.
    """
    from perception import actual_signature_match, perceive

    # Try signature throws first, then full vocabulary.
    candidates: list[ThrowID] = list(judoka.capability.signature_throws)
    for t in judoka.capability.throw_vocabulary:
        if t not in candidates:
            candidates.append(t)

    # HAJ-207 — Stage 1 availability. Catalog gating only applies when a
    # catalog is supplied AND we aren't in a desperation bypass. With no
    # catalog, behavior is the legacy grip-presence-gate path.
    catalog_active = catalog is not None and not (
        offensive_desperation or defensive_desperation
    )
    available_techniques: set[str] = set()
    if catalog_active:
        available_techniques = stage1_available_techniques(
            graph, judoka, opponent, catalog,
        )
        if not available_techniques:
            # No throw can fire this tick. Skip directly to non-scoring
            # motivations (false-attack pathways are not gated by the
            # catalog because they're tactical fakes, not scoring commits).
            return _try_false_attack_commit(
                judoka, opponent, graph, rng,
                offensive_desperation=offensive_desperation,
                defensive_desperation=defensive_desperation,
                kumi_kata_clock=kumi_kata_clock,
                opponent_kumi_kata_clock=opponent_kumi_kata_clock,
                perceived_by_throw={},
                golden_score=golden_score,
            )

    # Rank candidates by perceived signature; we'll walk in descending order
    # and pick the first that clears both the threshold AND the grip gate.
    perceived_by_throw: dict[ThrowID, float] = {}
    ranked: list[tuple[float, ThrowID]] = []
    for tid in candidates:
        td = THROW_DEFS.get(tid)
        if td is None:
            continue
        if judoka.capability.throw_profiles.get(tid) is None:
            continue
        actual = actual_signature_match(tid, judoka, opponent, graph,
                                        current_tick=current_tick)
        perceived = perceive(actual, judoka, rng=rng)
        # Small bonus for signature throws — tokui-waza bias.
        if tid in judoka.capability.signature_throws:
            perceived += 0.05
        perceived_by_throw[tid] = perceived
        ranked.append((perceived, tid))
    ranked.sort(key=lambda pair: pair[0], reverse=True)

    if catalog_active:
        chosen = _stage2_commit_from_ranked(
            judoka, opponent, ranked, available_techniques,
            catalog, rng, current_tick,
        )
        if chosen is not None:
            tid, _gate = chosen
            return commit_throw(
                tid,
                offensive_desperation=offensive_desperation,
                defensive_desperation=defensive_desperation,
                gate_bypass_reason=None,
                gate_bypass_kind=None,
            )
    else:
        for perceived, tid in ranked:
            if perceived < COMMIT_THRESHOLD:
                break   # ranked descending; nothing below will clear either
            td = THROW_DEFS[tid]
            gate = evaluate_gate(
                judoka, td, graph,
                offensive_desperation=offensive_desperation,
                defensive_desperation=defensive_desperation,
            )
            if not gate.allowed:
                continue   # try the next throw
            return commit_throw(
                tid,
                offensive_desperation=offensive_desperation,
                defensive_desperation=defensive_desperation,
                gate_bypass_reason=gate.reason if gate.bypassed else None,
                gate_bypass_kind=gate.bypass_kind,
            )

    return _try_false_attack_commit(
        judoka, opponent, graph, rng,
        offensive_desperation=offensive_desperation,
        defensive_desperation=defensive_desperation,
        kumi_kata_clock=kumi_kata_clock,
        opponent_kumi_kata_clock=opponent_kumi_kata_clock,
        perceived_by_throw=perceived_by_throw,
        golden_score=golden_score,
    )


def _try_false_attack_commit(
    judoka: "Judoka",
    opponent: "Judoka",
    graph: "GripGraph",
    rng: random.Random,
    *,
    offensive_desperation: bool,
    defensive_desperation: bool,
    kumi_kata_clock: int,
    opponent_kumi_kata_clock: int,
    perceived_by_throw: dict[ThrowID, float],
    golden_score: bool,
) -> Optional[Action]:
    """HAJ-67 non-scoring motivation dispatch, factored out so the
    HAJ-207 Stage-1-empty path can reach it without re-ranking
    candidates. Skipped when either desperation flag is already firing
    (those have higher precedence)."""
    if offensive_desperation or defensive_desperation:
        return None

    motivation = _select_non_scoring_motivation(
        judoka, opponent, graph, rng,
        kumi_kata_clock=kumi_kata_clock,
        opponent_kumi_kata_clock=opponent_kumi_kata_clock,
        perceived_by_throw=perceived_by_throw,
        golden_score=golden_score,
    )
    if motivation is None:
        return None

    tid = _select_false_attack_throw(judoka, graph)
    if tid is None:
        return None
    return commit_throw(
        tid,
        commit_motivation=motivation,
        gate_bypass_reason=REASON_INTENTIONAL_FALSE_ATTACK,
        gate_bypass_kind="false_attack",
    )


def _stage2_commit_from_ranked(
    judoka: "Judoka",
    opponent: "Judoka",
    ranked: list[tuple[float, ThrowID]],
    available_techniques: set[str],
    catalog: dict[str, "TechniqueDefinition"],
    rng: random.Random,
    current_tick: int,
) -> Optional[tuple[ThrowID, None]]:
    """HAJ-207 Stage 2: pick one technique from Stage-1 survivors that
    also clear COMMIT_THRESHOLD on perceived signature.

    Returns (throw_id, None) on a fire, or None to skip. The trailing
    `None` mirrors the `gate` element the legacy path returns so the
    caller's tuple-unpack stays symmetric (future wiring may surface
    Stage 2 telemetry there).
    """
    from kuzushi import compromised_state

    perceived_by_tech: dict[str, float] = {}
    throw_by_tech: dict[str, ThrowID] = {}
    for perceived, tid in ranked:
        if perceived < COMMIT_THRESHOLD:
            break
        technique_id = THROW_TO_TECHNIQUE_ID.get(tid)
        if technique_id is None or technique_id not in available_techniques:
            continue
        # First entry per technique_id wins (ranked is descending).
        if technique_id not in perceived_by_tech:
            perceived_by_tech[technique_id] = perceived
            throw_by_tech[technique_id] = tid
    if not throw_by_tech:
        return None

    cs = compromised_state(opponent.kuzushi_events, current_tick)
    chosen_tech = stage2_select_technique(
        available=set(throw_by_tech.keys()),
        catalog=catalog,
        tori=judoka,
        kuzushi_vector=cs.vector,
        uke_facing=opponent.state.body_state.facing,
        perceived_signature=perceived_by_tech,
        rng=rng,
    )
    if chosen_tech is None:
        return None
    return throw_by_tech[chosen_tech], None


# ---------------------------------------------------------------------------
# HAJ-67 — non-scoring commit motivation: dispatcher + per-motivation gates
# ---------------------------------------------------------------------------
def _select_non_scoring_motivation(
    judoka: "Judoka",
    opponent: "Judoka",
    graph: "GripGraph",
    rng: random.Random,
    *,
    kumi_kata_clock: int,
    opponent_kumi_kata_clock: int,
    perceived_by_throw: dict[ThrowID, float],
    golden_score: bool = False,
) -> Optional[CommitMotivation]:
    """Dispatch to the first non-scoring motivation whose gate fires.

    Each predicate is self-contained and performs its own hard gates plus
    per-tick probability roll. Priority order: CLOCK_RESET, then
    STAMINA_DESPERATION, GRIP_ESCAPE, SHIDO_FARMING.

    HAJ-74 — `golden_score` relaxes the STAMINA_DESPERATION gates and
    damps SHIDO_FARMING; the v2 spec calls for technique commitment over
    shido-baiting once the regulation clock is gone.
    """
    # All four motivations pick from drop-variant preferences; if the
    # fighter has none, skip the whole dispatch.
    if not any(tid in judoka.capability.throw_vocabulary
               for tid in FALSE_ATTACK_PREFERENCES):
        return None

    if _should_fire_clock_reset(judoka, kumi_kata_clock, rng):
        return CommitMotivation.CLOCK_RESET
    if _should_fire_stamina_desperation(
        judoka, rng, golden_score=golden_score,
    ):
        return CommitMotivation.STAMINA_DESPERATION
    if _should_fire_grip_escape(judoka, opponent, graph, rng):
        return CommitMotivation.GRIP_ESCAPE
    if _should_fire_shido_farming(
        judoka, opponent_kumi_kata_clock, perceived_by_throw, rng,
        golden_score=golden_score,
    ):
        return CommitMotivation.SHIDO_FARMING
    return None


def _should_fire_clock_reset(
    judoka: "Judoka", kumi_kata_clock: int,
    rng: Optional[random.Random] = None,
) -> bool:
    """CLOCK_RESET — HAJ-49 legacy. Fighter with composure and style-dna
    disposition fires a tactical fake in the pre-shido window to reset
    their own kumi-kata clock.
    """
    if not (FALSE_ATTACK_CLOCK_MIN <= kumi_kata_clock < FALSE_ATTACK_CLOCK_MAX):
        return False
    if judoka.capability.fight_iq < FALSE_ATTACK_MIN_FIGHT_IQ:
        return False
    tendency = judoka.identity.style_dna.get(
        FALSE_ATTACK_TENDENCY_KEY, FALSE_ATTACK_TENDENCY_DEFAULT,
    )
    if tendency < FALSE_ATTACK_TENDENCY_THRESHOLD:
        return False
    if rng is None:
        return True
    return rng.random() < tendency * FALSE_ATTACK_PER_TICK_SCALE


def _should_fire_stamina_desperation(
    judoka: "Judoka", rng: Optional[random.Random] = None,
    *, golden_score: bool = False,
) -> bool:
    """STAMINA_DESPERATION — tori is cardio-cooked, has eaten at least one
    shido, and can't drive force through grips (proxy: hand fatigue above
    threshold). A cooked, penalized fighter falls into anything to buy
    time on the mat.

    HAJ-74 — in golden score, the gates relax and the per-tick probability
    rises. The shido prerequisite drops away (the regulation-shido signal
    of "this fighter has been forced into desperation" is no longer the
    only license; the GS clock itself is the license), the cardio ceiling
    rises (a fighter at 0.6 cardio in GS is more cooked relative to what
    they'll need than a fighter at 0.6 in regulation), and the hand-fatigue
    floor drops. Composure suppression is modeled here: even fighters who
    would have ridden out regulation start forcing desperate ippon attempts
    once they realize the next score wins.
    """
    if golden_score:
        cardio_max = GS_STAMINA_DESPERATION_CARDIO_MAX
        min_shidos = GS_STAMINA_DESPERATION_MIN_SHIDOS
        hand_min   = GS_STAMINA_DESPERATION_HAND_FAT_MIN
        prob       = GS_STAMINA_DESPERATION_PER_TICK_PROB
    else:
        cardio_max = STAMINA_DESPERATION_CARDIO_MAX
        min_shidos = STAMINA_DESPERATION_MIN_SHIDOS
        hand_min   = STAMINA_DESPERATION_HAND_FAT_MIN
        prob       = STAMINA_DESPERATION_PER_TICK_PROB
    if judoka.state.cardio_current > cardio_max:
        return False
    if judoka.state.shidos < min_shidos:
        return False
    if _avg_hand_fatigue(judoka) < hand_min:
        return False
    if rng is None:
        return True
    return rng.random() < prob


def _should_fire_grip_escape(
    judoka: "Judoka", opponent: "Judoka", graph: "GripGraph",
    rng: Optional[random.Random] = None,
) -> bool:
    """GRIP_ESCAPE — opponent is dominant in the grip war, tori's own
    grips are shallow/few, and composure has slipped. The tactical fake
    is cover to rip off the dyad and try to reset grips.
    """
    # HAJ-51 — feed the current matchup so dominance reflects per-grip
    # stance leverage. A pistol-grip-heavy opponent looks less dominant
    # in matched stance than in mirrored, even at the same depth/strength.
    matchup = StanceMatchup.of(
        judoka.state.current_stance, opponent.state.current_stance
    )
    delta_opp_over_tori = graph.compute_grip_delta(opponent, judoka, matchup)
    if delta_opp_over_tori < GRIP_ESCAPE_DELTA_THRESHOLD:
        return False
    # Tori's own grip integrity compromised: no edge deeper than POCKET.
    own_edges = graph.edges_owned_by(judoka.identity.name)
    deepest = max(
        (e.depth_level for e in own_edges),
        default=GripDepth.SLIPPING,
        key=lambda d: d.modifier(),
    )
    if deepest.modifier() > GripDepth.POCKET.modifier():
        return False
    # Composure below escape threshold.
    ceiling = max(1.0, float(judoka.capability.composure_ceiling))
    composure_frac = judoka.state.composure_current / ceiling
    if composure_frac >= GRIP_ESCAPE_COMPOSURE_FRAC:
        return False
    if rng is None:
        return True
    return rng.random() < GRIP_ESCAPE_PER_TICK_PROB


def _should_fire_shido_farming(
    judoka: "Judoka", opponent_kumi_kata_clock: int,
    perceived_by_throw: dict[ThrowID, float],
    rng: Optional[random.Random] = None,
    *, golden_score: bool = False,
) -> bool:
    """SHIDO_FARMING — opponent has been passive (their kumi-kata clock is
    elevated), tori has no real scoring opportunity, and tori's style
    tolerates grinding the referee for the opposing shido. Tori poses an
    attack to keep themselves above the passivity bar while forcing uke
    to either escalate or eat a shido of their own.

    HAJ-74 — in golden score the per-tick probability is damped by
    GS_SHIDO_FARMING_DAMPER (0.20x). The v2 spec calls for tactical
    behavior to shift away from defensive shido-baiting toward technique
    commitment once regulation is over; pose-attacks for opposing shidos
    do not match that. A small residual chance survives so habituated /
    low-IQ fighters still occasionally do the wrong thing.
    """
    if opponent_kumi_kata_clock < SHIDO_FARMING_OPP_CLOCK:
        return False
    # No meaningful scoring opportunity: best-perceived signature is below
    # the "could-almost-score" threshold.
    if perceived_by_throw:
        best = max(perceived_by_throw.values())
        if best >= SHIDO_FARMING_NO_SCORING_MAX:
            return False
    tendency = judoka.identity.style_dna.get(
        SHIDO_FARMING_TENDENCY_KEY, SHIDO_FARMING_TENDENCY_DEFAULT,
    )
    if tendency < SHIDO_FARMING_TENDENCY_THRESHOLD:
        return False
    if rng is None:
        return True
    prob = SHIDO_FARMING_PER_TICK_PROB
    if golden_score:
        prob *= GS_SHIDO_FARMING_DAMPER
    return rng.random() < prob


def _select_false_attack_throw(
    judoka: "Judoka", graph: "GripGraph",
) -> Optional[ThrowID]:
    """Pick the most-preferred drop variant that's (a) in the fighter's
    vocabulary, (b) has a registered THROW_DEFS entry, and (c) passes
    minimal grip-presence: at least one owned edge exists (the `not
    own_edges` rung 1 check already enforced this upstream, but being
    explicit here keeps the helper self-contained).

    Returns None if no candidate qualifies — caller falls through.
    """
    own_edges = graph.edges_owned_by(judoka.identity.name)
    if not own_edges:
        return None
    for tid in FALSE_ATTACK_PREFERENCES:
        if tid not in judoka.capability.throw_vocabulary:
            continue
        if tid not in THROW_DEFS:
            continue
        return tid
    return None


def _direction_toward(judoka: "Judoka", opponent: "Judoka") -> tuple[float, float]:
    """Unit vector from judoka's CoM toward opponent's CoM, in world frame."""
    ax, ay = judoka.state.body_state.com_position
    bx, by = opponent.state.body_state.com_position
    dx, dy = bx - ax, by - ay
    norm = (dx * dx + dy * dy) ** 0.5
    if norm < 1e-9:
        return (1.0, 0.0)
    return (dx / norm, dy / norm)


def _avg_hand_fatigue(judoka: "Judoka") -> float:
    rh = judoka.state.body.get("right_hand")
    lh = judoka.state.body.get("left_hand")
    if rh is None or lh is None:
        return 0.0
    return 0.5 * (rh.fatigue + lh.fatigue)


def _primary_hand(judoka: "Judoka") -> str:
    return ("right_hand"
            if judoka.identity.dominant_side == DominantSide.RIGHT
            else "left_hand")


def _free_hand(judoka: "Judoka") -> Optional[str]:
    from body_state import ContactState as _CS
    for key in ("right_hand", "left_hand"):
        ps = judoka.state.body.get(key)
        if ps is not None and ps.contact_state != _CS.GRIPPING_UKE:
            return key
    return None


# ---------------------------------------------------------------------------
# LOCOMOTION (HAJ-128)
# ---------------------------------------------------------------------------
# Tactical mat positioning. Three styles drive different intents:
#   - PRESSURE: drive opponent toward edge by stepping toward them
#   - DEFENSIVE_EDGE: retreat toward center when own perceived edge is close
#   - HOLD_CENTER: stay near center; only step toward center when far drift
#
# Magnitudes are intentionally small (per-tick step is part of a
# weight-transfer phase, not a full body move). Step gates with grip range:
# heavy opponent grips drag the fighter and reduce step magnitude.

# Per-tick STEP magnitude in meters. A real judo step is ~30-50 cm; we
# pick the lower end so per-tick motion is calm but visibly cumulative
# across a 4-minute match on the 8 m contest area. CoM advances at half
# the foot magnitude (one tick = one weight-transfer phase).
STEP_MAGNITUDE_M:           float = 0.30
STEP_MAGNITUDE_REDUCED_M:   float = 0.14   # under heavy opponent grips


# HAJ-156 — per-fighter effective foot-speed scaler. The action ladder
# picks a base magnitude (STEP_MAGNITUDE_M / STEP_MAGNITUDE_REDUCED_M
# / GRIP_WAR_EVASION_MAG_M); this scales it by the fighter's
# `foot_speed` attribute and the leg-fatigue / age / posture modifiers
# the spec calls for. The output is the magnitude actually applied
# to the foot + CoM on this tick.
def effective_foot_speed_factor(judoka: "Judoka") -> float:
    """0.4–1.4 multiplier on the action selector's base step magnitude.

    foot_speed=5 (the default) yields ~1.0 (no change). foot_speed=9 →
    ~1.3, foot_speed=2 → ~0.55. Modulators:
      - leg_fatigue_modifier: average leg fatigue eats up to half the
        speed when both legs are exhausted.
      - age_modifier: identity-driven; peaks 22–24, declines after 30.
      - stance_modifier: small reduction when bent / kuzushi-shaped,
        small bonus when upright.
    """
    cap = judoka.capability
    foot_speed = max(0, min(10, int(getattr(cap, "foot_speed", 5))))
    # Map 0..10 → 0.4..1.4 linearly. foot_speed=5 → 0.9; the leg-
    # fatigue / age / stance modifiers below carry the rest of the
    # variance, so a fresh foot_speed=5 fighter still steps at ~1.0
    # of the base magnitude.
    base = 0.4 + foot_speed * 0.10
    body = judoka.state.body
    leg_fat = 0.5 * (
        body["right_leg"].fatigue + body["left_leg"].fatigue
    ) if "right_leg" in body and "left_leg" in body else 0.0
    leg_modifier = max(0.5, 1.0 - 0.5 * leg_fat)
    age = getattr(judoka.identity, "age", 26)
    if age <= 22:
        age_modifier = 1.0
    elif age <= 30:
        age_modifier = 1.0 - (age - 22) * 0.01
    else:
        age_modifier = max(0.7, 0.92 - (age - 30) * 0.012)
    bs = judoka.state.body_state
    bend = abs(bs.trunk_sagittal) + abs(bs.trunk_frontal)
    if bend < 0.05:
        stance_modifier = 1.05
    elif bend < 0.20:
        stance_modifier = 1.0
    else:
        stance_modifier = max(0.7, 1.0 - bend * 0.5)
    factor = base * leg_modifier * age_modifier * stance_modifier
    # The base STEP_MAGNITUDE_M (0.30 m) was calibrated for a
    # neutral fighter pre-HAJ-156, so a factor of 1.0 should reproduce
    # the legacy magnitude. Apply a normalising fudge so foot_speed=5
    # + leg_fat=0 + age=26 lands almost exactly at 1.0.
    return factor / 0.9


def effective_step_magnitude(
    judoka: "Judoka", base_magnitude: float,
) -> float:
    """Apply the foot-speed scaler to a base STEP magnitude. Floored
    at zero so a thoroughly cooked / panicked fighter still nudges
    forward instead of producing a negative-distance step."""
    return max(0.0, base_magnitude * effective_foot_speed_factor(judoka))

# How frequently each style attempts a step (per-tick probability gates).
PRESSURE_BASE_STEP_PROB:    float = 0.55   # PRESSURE keeps the heat on
PRESSURE_RAMP_PROB_PER_M:   float = 0.10   # extra prob per meter opp is from edge
DEFENSIVE_EDGE_TRIGGER_M:   float = 1.6    # perceived edge < this → retreat
DEFENSIVE_EDGE_STEP_PROB:   float = 0.85   # high — retreat is urgent
HOLD_CENTER_DRIFT_M:        float = 0.6    # |com| > this → small recentering step
HOLD_CENTER_STEP_PROB:      float = 0.30

# Grip-range gating: if any opponent grip on this fighter has depth ≥ DEEP,
# consider the fighter "tied" and reduce step magnitude.
def _opponent_grip_drag(judoka: "Judoka", graph: "GripGraph") -> bool:
    """True when the opponent has a deep grip on this fighter — heavy drag
    means the fighter can't take a clean step."""
    for e in graph.edges_targeting(judoka.identity.name):
        if e.depth_level == GripDepth.DEEP:
            return True
    return False


def _trailing_step_foot(
    judoka: "Judoka", direction: tuple[float, float],
) -> str:
    """Pick which foot to step with — the trailing one. Real walking
    moves the foot that's currently behind the body in the direction of
    travel; the leading foot stays planted as the new pivot. We pick
    whichever foot has the smaller dot-product with the step direction
    relative to the body's CoM (i.e. is further behind).

    This avoids the pre-fix bug where one foot kept stepping forward and
    the other was abandoned at the start position, splitting the dots.
    """
    bs = judoka.state.body_state
    cx, cy = bs.com_position
    dx, dy = direction
    lx, ly = bs.foot_state_left.position
    rx, ry = bs.foot_state_right.position
    # Project each foot's offset-from-CoM onto the step direction. The
    # foot with the SMALLER projection is the trailing foot — pick it.
    left_proj  = (lx - cx) * dx + (ly - cy) * dy
    right_proj = (rx - cx) * dx + (ry - cy) * dy
    return "left_foot" if left_proj < right_proj else "right_foot"


def _step_action(
    judoka: "Judoka", direction: tuple[float, float],
    magnitude: float,
    *, tactical_intent: Optional[str] = None,
) -> Optional[Action]:
    """Build a STEP action in `direction` of `magnitude`, picking the
    trailing foot for the chosen direction so the pair walks naturally
    instead of abandoning the off-side foot.

    HAJ-156 — accepts a `tactical_intent` string so the engine event
    log, viewer state pill, and HAJ-149 perception layer can read what
    kind of step the fighter took on this tick.
    """
    nx, ny = direction
    norm = (nx * nx + ny * ny) ** 0.5
    if norm == 0:
        return None
    unit = (nx / norm, ny / norm)
    foot = _trailing_step_foot(judoka, unit)
    return step(foot, unit, magnitude, tactical_intent=tactical_intent)


# Grip-war evasion: every fighter, regardless of positional style,
# circles laterally during active grip exchanges. Real judo: grip
# fighting is constant lateral motion — angling, breaking line, evading
# the next reach. Without this, fighters who aren't PRESSURE-styled
# stand still while throws fire on top of them.
#
# HAJ-164 — engagement-phase frequency calibration. Pre-fix, the
# 0.30 base probability paired with HOLD_CENTER fighters who only
# stepped when drifted past 0.6 m yielded ~1 [move] event per 22
# engaged ticks (Renard vs Sato playthrough). Real grip-fighting
# between elite judoka produces footwork roughly every 2–3 seconds;
# at ~1 sec/tick the engaged window should emit STEP every 2–3 ticks
# per fighter. Fix is two-piece: lift the base probability for
# low-stakes engaged ticks, and suppress to a near-zero floor on
# high-stakes ticks (opponent mid-throw, or judoka actively staging
# their own multi-tick plan) so footwork doesn't interrupt sequences.
GRIP_WAR_EVASION_MAG_M:     float = 0.18
ENGAGED_STEP_PROB_LOW_STAKES:    float = 0.45
ENGAGED_STEP_PROB_HIGH_STAKES:   float = 0.05
# Probability that an engaged step takes its style-primary intent label
# (PRESSURE / GIVE_GROUND / CIRCLE) versus its secondary (CIRCLE for
# directional styles, HOLD_CENTER for HOLD_CENTER). Tuned so each style
# still emits some CIRCLE for visible angle-finding without losing the
# style-distinctive bias.
ENGAGED_STEP_INTENT_PRIMARY_PROB: float = 0.70

# Backwards-compat: tests / external callers still reference
# GRIP_WAR_EVASION_PROB. After HAJ-164 it tracks the low-stakes prob.
GRIP_WAR_EVASION_PROB:      float = ENGAGED_STEP_PROB_LOW_STAKES


def _is_engaged_high_stakes(
    judoka: "Judoka",
    opponent: "Judoka",
    current_tick: int,
    opponent_in_progress_throw: Optional[ThrowID],
) -> bool:
    """HAJ-164 — true when the engaged tick is mid-sequence and footwork
    should be suppressed.

    Two signals are reliable; each routine PULL/DEEPEN tick already opens
    a vulnerability window and emits a kuzushi event, so those are too
    noisy to use as high-stakes proxies. The reliable signals:

      - `opponent_in_progress_throw` is set — opponent is mid-throw and
        judoka is the defender; a footwork tangent now is a step away
        from the resolution window.
      - judoka's own multi-tick plan is past stage 0 — the fighter is
        actively staging a combo and inserting footwork would break the
        sequence's tick-locking that produces emergent throws.
    """
    if opponent_in_progress_throw is not None:
        return True
    plan = getattr(judoka, "current_plan", None)
    if plan is not None and getattr(plan, "step_index", 0) > 0:
        return True
    return False


# Style → (primary, secondary) intent labels for an engaged step. The
# direction-of-step (forward/back/lateral) is computed by
# `_grip_war_evasion_direction`, which already applies a style-keyed
# forward bias; the label here makes the MOVE event mix readable in
# logs / viewer / narration so a PRESSURE fighter shows visibly more
# PRESSURE-tagged steps than a DEFENSIVE_EDGE fighter.
_ENGAGED_STEP_INTENT_BY_STYLE: dict = {
    PositionalStyle.PRESSURE:       (TACTICAL_INTENT_PRESSURE,    TACTICAL_INTENT_CIRCLE),
    PositionalStyle.DEFENSIVE_EDGE: (TACTICAL_INTENT_GIVE_GROUND, TACTICAL_INTENT_CIRCLE),
    PositionalStyle.HOLD_CENTER:    (TACTICAL_INTENT_CIRCLE,      TACTICAL_INTENT_HOLD_CENTER),
}


def _engaged_step_intent(
    style: PositionalStyle, rng: random.Random,
) -> str:
    primary, secondary = _ENGAGED_STEP_INTENT_BY_STYLE.get(
        style, (TACTICAL_INTENT_CIRCLE, TACTICAL_INTENT_HOLD_CENTER),
    )
    if rng.random() < ENGAGED_STEP_INTENT_PRIMARY_PROB:
        return primary
    return secondary


def _maybe_emit_step(
    judoka: "Judoka", opponent: "Judoka", graph: "GripGraph",
    rng: random.Random,
    current_tick: int = 0,
    opponent_in_progress_throw: Optional[ThrowID] = None,
) -> Optional[Action]:
    """Decide whether to emit a STEP action this tick based on the
    fighter's positional style. Returns the Action or None.

    Reads perceived edge distance via perception.perceive_edge_distance,
    so fight_iq / fatigue / composure all modulate the decision through
    the same noise model the throw-signature path uses.
    """
    from perception import perceive_edge_distance
    from match import MAT_HALF_WIDTH

    style = getattr(judoka.identity, "positional_style", PositionalStyle.HOLD_CENTER)

    # Magnitude attenuates under deep opponent grips.
    mag = (STEP_MAGNITUDE_REDUCED_M if _opponent_grip_drag(judoka, graph)
           else STEP_MAGNITUDE_M)

    # HAJ-128 / HAJ-164 — engagement-phase step. When both fighters
    # have edges (active grip war), fire a tactical step probabilistically
    # so constant footwork is visible regardless of style. The probability
    # is high during low-stakes ticks and suppressed during high-stakes
    # ticks (recent kuzushi event, vulnerability window, or opponent
    # mid-throw) so the selector doesn't insert footwork tangents into
    # throw sequences.
    own_edges = graph.edges_owned_by(judoka.identity.name)
    opp_edges = graph.edges_owned_by(opponent.identity.name)
    if own_edges and opp_edges:
        high_stakes = _is_engaged_high_stakes(
            judoka, opponent, current_tick, opponent_in_progress_throw,
        )
        prob = (ENGAGED_STEP_PROB_HIGH_STAKES if high_stakes
                else ENGAGED_STEP_PROB_LOW_STAKES)
        if rng.random() < prob:
            evade = _grip_war_evasion_direction(judoka, opponent, rng)
            if evade is not None:
                intent = _engaged_step_intent(style, rng)
                return _step_action(
                    judoka, evade, GRIP_WAR_EVASION_MAG_M,
                    tactical_intent=intent,
                )

    if style == PositionalStyle.HOLD_CENTER:
        # Only step toward center when the fighter has drifted noticeably.
        x, y = judoka.state.body_state.com_position
        if abs(x) <= HOLD_CENTER_DRIFT_M and abs(y) <= HOLD_CENTER_DRIFT_M:
            return None
        if rng.random() > HOLD_CENTER_STEP_PROB:
            return None
        return _step_action(
            judoka, (-x, -y), mag,
            tactical_intent=TACTICAL_INTENT_HOLD_CENTER,
        )

    if style == PositionalStyle.DEFENSIVE_EDGE:
        # Retreat toward center when own perceived edge is close.
        own_edge = perceive_edge_distance(judoka, MAT_HALF_WIDTH, rng)
        if own_edge >= DEFENSIVE_EDGE_TRIGGER_M:
            return None
        if rng.random() > DEFENSIVE_EDGE_STEP_PROB:
            return None
        x, y = judoka.state.body_state.com_position
        if abs(x) < 1e-6 and abs(y) < 1e-6:
            return None
        # The "retreat to center" step is itself a give-ground move
        # from the edge perspective — surface the intent so push-out
        # shido bookkeeping can read it.
        return _step_action(
            judoka, (-x, -y), mag,
            tactical_intent=TACTICAL_INTENT_GIVE_GROUND,
        )

    if style == PositionalStyle.PRESSURE:
        # Drive opponent toward the edge by stepping into them. Probability
        # ramps up as opponent's PERCEIVED edge distance shrinks — pressure
        # builds when the prey nears the rope.
        opp_edge = perceive_edge_distance(opponent, MAT_HALF_WIDTH, rng)
        proximity_term = max(0.0, MAT_HALF_WIDTH - opp_edge) * PRESSURE_RAMP_PROB_PER_M
        prob = min(0.95, PRESSURE_BASE_STEP_PROB + proximity_term)
        if rng.random() > prob:
            return None
        return _step_action(
            judoka, _pressure_direction(judoka, opponent, rng), mag,
            tactical_intent=TACTICAL_INTENT_PRESSURE,
        )

    return None


def _grip_war_evasion_direction(
    judoka: "Judoka", opponent: "Judoka", rng: random.Random,
) -> Optional[tuple[float, float]]:
    """HAJ-128 — pick a lateral evasion direction during active grip
    fighting. Step perpendicular to the line of attack, randomized side
    per tick so the fighter circles. Pressure-fighters bias forward
    along that perpendicular; defenders / hold-center bias rearward."""
    sx, sy = judoka.state.body_state.com_position
    ox, oy = opponent.state.body_state.com_position
    dx, dy = ox - sx, oy - sy
    norm = (dx * dx + dy * dy) ** 0.5
    if norm < 1e-6:
        return None
    fx, fy = dx / norm, dy / norm
    # 90° rotation: perpendicular to line of attack.
    perp_x, perp_y = -fy, fx
    # Randomize side.
    if rng.random() < 0.5:
        perp_x, perp_y = -perp_x, -perp_y
    # Style bias: PRESSURE leans into the opponent while circling;
    # defenders lean away. HOLD_CENTER stays purely lateral.
    style = getattr(judoka.identity, "positional_style", PositionalStyle.HOLD_CENTER)
    forward_bias = 0.0
    if style == PositionalStyle.PRESSURE:
        forward_bias = +0.4
    elif style == PositionalStyle.DEFENSIVE_EDGE:
        forward_bias = -0.4
    return (perp_x + fx * forward_bias, perp_y + fy * forward_bias)


def _pressure_direction(
    judoka: "Judoka", opponent: "Judoka", rng: random.Random,
) -> tuple[float, float]:
    """HAJ-128 — pressure-fighter step direction.

    Pure "step toward opponent" produces 1D forward/back movement: with
    fighters starting on the x-axis, every step is along x and the match
    plays in a horizontal stripe. Real pressure-fighters angle their
    opponent toward a corner — the line of attack tilts off-axis.

    Direction is a blend of:
      1. Toward the opponent's CoM (60%) — keep applying pressure.
      2. Toward the corner the opponent is closest to (40%) — angle them
         into the rope. Per-axis: pick whichever edge the opponent is
         closer to in x and in y; sum drives the diagonal.

    Pressure-fighter alternates lateral side via a small per-tick jitter
    so the motion isn't perfectly straight even when both fighters sit
    on the x-axis.
    """
    from match import MAT_HALF_WIDTH

    sx, sy = judoka.state.body_state.com_position
    ox, oy = opponent.state.body_state.com_position
    base_dx, base_dy = (ox - sx), (oy - sy)
    base_norm = (base_dx * base_dx + base_dy * base_dy) ** 0.5 or 1.0
    base_dx /= base_norm
    base_dy /= base_norm

    # Corner the opponent is currently angling toward (per axis).
    # Tie-break with a small jitter so two fighters on the x-axis pick
    # a side instead of trying to step purely +x and stuttering.
    edge_x = MAT_HALF_WIDTH if ox >= -1e-6 else -MAT_HALF_WIDTH
    edge_y = MAT_HALF_WIDTH if oy >= 0 else -MAT_HALF_WIDTH
    if abs(oy) < 0.1:
        # Roughly on the x-axis — randomize the lateral side (left vs right).
        edge_y = MAT_HALF_WIDTH if rng.random() < 0.5 else -MAT_HALF_WIDTH

    corner_dx = edge_x - ox
    corner_dy = edge_y - oy
    cn = (corner_dx * corner_dx + corner_dy * corner_dy) ** 0.5 or 1.0
    corner_dx /= cn
    corner_dy /= cn

    return (
        base_dx * 0.60 + corner_dx * 0.40,
        base_dy * 0.60 + corner_dy * 0.40,
    )
