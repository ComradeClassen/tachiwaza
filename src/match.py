# match.py
# Physics-substrate Part 3: the tick update is the match.
#
# The old ENGAGEMENT/TUG_OF_WAR/KUZUSHI_WINDOW/STIFLED_RESET state machine
# is gone. Flow now emerges from the 12-step force model (spec 3.4):
#   1. Grip state updates        — REACH / DEEPEN / STRIP / RELEASE actions
#   2. Force accumulation        — sum driving-mode forces through grips
#   3. Force application         — Newton 3 counter-forces on tori
#   4. Net torque / translation  — per-fighter net_force + net_torque
#   5. CoM velocity update
#   6. CoM position update
#   7. Trunk angle update
#   8. BoS update                — STEP / SWEEP_LEG
#   9. Kuzushi check             — polygon test from Part 1.5
#  10. Throw signature match     — actual in [0, 1]
#  11. Compound action resolve   — COMMIT_THROW
#  12. Fatigue / composure / clocks
#
# Each judoka's actions are chosen by action_selection.select_actions (3.3).
# Perception of signature match goes through perception.perceive (3.5).

import random
import math
from dataclasses import dataclass, field
from typing import Optional

from enums import (
    BodyArchetype, DominantSide, MatteReason, Position, StanceMatchup,
    SubLoopState, LandingProfile, GripMode,
)
from judoka import Judoka
from throws import ThrowID, ThrowDef, THROW_REGISTRY, THROW_DEFS
from grip_graph import GripGraph, GripEdge, Event
from position_machine import PositionMachine
from referee import Referee, MatchState, ThrowLanding, ScoreResult
from ne_waza import OsaekomiClock, NewazaResolver
from actions import (
    Action, ActionKind,
    GRIP_KINDS, FORCE_KINDS, BODY_KINDS, DRIVING_FORCE_KINDS,
)
from action_selection import select_actions
from perception import actual_signature_match, perceive


# ---------------------------------------------------------------------------
# TUNING CONSTANTS
# All calibration knobs in one place. Phase 3 will tune these after watching
# many matches.
# ---------------------------------------------------------------------------

# Engagement (Part 2.7): baseline floor; actual duration is max of
# reach_ticks_for(a) and reach_ticks_for(b), enforced from the graph.
ENGAGEMENT_TICKS_FLOOR: int = 2

# Part 2.6 passivity clocks (1 tick = 1 second in v0.1).
KUMI_KATA_SHIDO_TICKS:        int = 30   # grip-to-attack threshold
UNCONVENTIONAL_SHIDO_TICKS:   int = 5    # BELT/PISTOL/CROSS immediate-attack threshold

# Part 3 force-model calibration stubs. Phase 3 telemetry will tune these.
JUDOKA_MASS_KG:           float = 80.0   # v0.1 uniform; Part 6 can pull from identity.
FRICTION_DAMPING:         float = 0.55   # fraction of velocity surviving a tick (planted feet)
DISPLACEMENT_GAIN:        float = 0.00006 # meters-per-Newton-tick on CoM (with DAMPING)
TRUNK_ANGLE_GAIN:         float = 0.00008 # radians per N·m of net torque (stubbed moment arm)
TRUNK_RESTORATION:        float = 0.15   # passive + active return-to-vertical each tick
FORCE_NOISE_PCT:          float = 0.10   # ±10% uniform on applied force magnitudes (3.8)
TRUNK_NOISE_PCT:          float = 0.05   # ±5% uniform on trunk angle updates (3.8)
STALEMATE_NO_PROGRESS_TICKS: int = 45    # ticks with no kuzushi signal before matte-eligible

# Throw resolution
NOISE_STD:           float = 2.0
IPPON_THRESHOLD:     float = 4.0
WAZA_ARI_THRESHOLD:  float = 1.5
STUFFED_THRESHOLD:   float = -2.0
FORCE_ATTEMPT_MULT:  float = 0.15  # effectiveness penalty on forced attempts

MIRRORED_PENALTY:           float = 0.85
SUMI_GAESHI_MIRRORED_BONUS: float = 1.20

THROW_FATIGUE: dict[str, float] = {
    "IPPON":    0.015,
    "WAZA_ARI": 0.018,
    "STUFFED":  0.025,
    "FAILED":   0.030,
}

# Background fatigue per tick
CARDIO_DRAIN_PER_TICK: float = 0.002
HAND_FATIGUE_PER_TICK: float = 0.0003

# Composure drops on scoring events
COMPOSURE_DROP_WAZA_ARI: float = 0.5
COMPOSURE_DROP_IPPON:    float = 2.0

# Throws that require hand/forearm as primary muscles (not leg-dominant)
GRIP_DOMINANT_THROWS: frozenset[ThrowID] = frozenset({
    ThrowID.SEOI_NAGE,
    ThrowID.TAI_OTOSHI,
})


# ---------------------------------------------------------------------------
# THROW RESOLUTION (module-level, testable without a Match object)
# ---------------------------------------------------------------------------

def resolve_throw(
    attacker: Judoka,
    defender: Judoka,
    throw_id: ThrowID,
    stance_matchup: StanceMatchup,
    window_quality: float = 0.0,
    is_forced: bool = False,
) -> tuple[str, float]:
    """Resolve one throw attempt.

    Returns:
        (outcome, net_score) where outcome is 'IPPON' | 'WAZA_ARI' | 'STUFFED' | 'FAILED'
        and net_score is the raw computed value.

    The formula (unchanged from Session 1, now with window_quality bonus):
        1. Throw effectiveness from attacker's side
        2. Stance matchup modifier
        3. Attacker body condition
        4. Defender resistance
        5. Gaussian noise
        6. Threshold comparison
    """
    profile = attacker.capability.throw_profiles.get(throw_id)
    if profile is None:
        return "FAILED", -99.0

    # 1. Effectiveness from current attacking side
    attacking_dominant = (
        (attacker.identity.dominant_side == DominantSide.RIGHT
         and attacker.state.current_stance.name == "ORTHODOX")
        or
        (attacker.identity.dominant_side == DominantSide.LEFT
         and attacker.state.current_stance.name == "SOUTHPAW")
    )
    effectiveness = (
        profile.effectiveness_dominant if attacking_dominant
        else profile.effectiveness_off_side
    )

    # 2. Stance matchup modifier
    if stance_matchup == StanceMatchup.MIRRORED:
        stance_mod = (SUMI_GAESHI_MIRRORED_BONUS if throw_id == ThrowID.SUMI_GAESHI
                      else MIRRORED_PENALTY)
    else:
        stance_mod = 1.0

    # 3. Attacker body condition
    dom = attacker.identity.dominant_side
    if throw_id in GRIP_DOMINANT_THROWS:
        key_parts = (
            ["right_hand", "right_forearm", "core", "lower_back"]
            if dom == DominantSide.RIGHT
            else ["left_hand", "left_forearm", "core", "lower_back"]
        )
    else:
        key_parts = (
            ["right_leg", "core", "lower_back"]
            if dom == DominantSide.RIGHT
            else ["left_leg", "core", "lower_back"]
        )
    attacker_body_avg = (
        sum(attacker.effective_body_part(p) for p in key_parts) / len(key_parts)
    )
    attacker_body_mod = 0.5 + 0.5 * (attacker_body_avg / 10.0)

    attack_strength = effectiveness * stance_mod * attacker_body_mod

    # Window quality bonus: a clean kuzushi window boosts the attack
    attack_strength += window_quality * 2.0

    # Forced attempt penalty
    if is_forced:
        attack_strength *= FORCE_ATTEMPT_MULT

    # 4. Defender resistance
    defender_parts = ["right_leg", "left_leg", "core", "neck"]
    defender_avg   = (
        sum(defender.effective_body_part(p) for p in defender_parts) / len(defender_parts)
    )
    defender_body_mod   = 0.5 + 0.5 * (defender_avg / 10.0)
    defender_resistance = defender_avg * defender_body_mod

    # 5. Noise
    noise = random.gauss(0, NOISE_STD)

    # 6. Outcome
    net = attack_strength - defender_resistance + noise

    if net >= IPPON_THRESHOLD:
        return "IPPON", net
    elif net >= WAZA_ARI_THRESHOLD:
        return "WAZA_ARI", net
    elif net >= STUFFED_THRESHOLD:
        return "STUFFED", net
    else:
        return "FAILED", net


# ===========================================================================
# MATCH
# The conductor. Owns all match-level state and coordinates all subsystems.
# ===========================================================================
class Match:
    """Runs a single judo match: sub-loop state machine driving all subsystems."""

    def __init__(
        self,
        fighter_a: Judoka,
        fighter_b: Judoka,
        referee: Referee,
        max_ticks: int = 240,
    ) -> None:
        self.fighter_a = fighter_a
        self.fighter_b = fighter_b
        self.referee   = referee
        self.max_ticks = max_ticks

        # Match-level state
        self.grip_graph   = GripGraph()
        self.position     = Position.STANDING_DISTANT
        self.osaekomi     = OsaekomiClock()
        self.ne_waza_resolver = NewazaResolver()

        # Phase of live match time. Part 3 physics owns STANDING. NE_WAZA
        # branches out to NewazaResolver.
        self.sub_loop_state = SubLoopState.STANDING

        # Engagement timer — counts ticks while both hands are REACHING and
        # no edges exist; attempt_engagement fires once both fighters have
        # completed their belt-based reach.
        self.engagement_ticks = 0

        # Stalemate tracking (feeds referee): ticks with no kuzushi signal
        # and no committed attack.
        self.stalemate_ticks = 0

        # Kuzushi transition tracking (edge-trigger KUZUSHI_INDUCED events).
        self._a_was_kuzushi_last_tick = False
        self._b_was_kuzushi_last_tick = False

        # Ne-waza tracking
        self.ne_waza_top_id: Optional[str] = None   # which fighter is on top

        # Match flow
        self.match_over  = False
        self.winner:  Optional[Judoka] = None
        self.win_method: str = ""      # "ippon", "two waza-ari", "decision", "hansoku-make", "draw"
        self.ticks_run   = 0

        # Passivity tracking
        self._last_attack_tick: dict[str, int] = {
            fighter_a.identity.name: 0,
            fighter_b.identity.name: 0,
        }

        # Part 2.6 kumi-kata clock — per-fighter counter that starts once
        # the fighter has any grip edge and resets on a driving-mode attack.
        # Shido issued when it reaches KUMI_KATA_SHIDO_TICKS.
        self.kumi_kata_clock: dict[str, int] = {
            fighter_a.identity.name: 0,
            fighter_b.identity.name: 0,
        }

        # Stuffed throw tracking (for referee Matte timing)
        self._stuffed_throw_tick: int = 0

        # For MatchState snapshots
        self._a_score: dict = {"waza_ari": 0, "ippon": False}
        self._b_score: dict = {"waza_ari": 0, "ippon": False}

    # -----------------------------------------------------------------------
    # RUN
    # -----------------------------------------------------------------------
    def run(self) -> None:
        self._print_header()

        # Hajime
        hajime = self.referee.announce_hajime(tick=0)
        print(hajime.description)
        print()

        for tick in range(1, self.max_ticks + 1):
            self.ticks_run = tick
            self._tick(tick)
            if self.match_over:
                break

        self._resolve_match()

    # -----------------------------------------------------------------------
    # TICK — the heart of the match
    # -----------------------------------------------------------------------
    def _tick(self, tick: int) -> None:
        events: list[Event] = []

        # Background: fatigue drain + stun decay (Step 12 partial; we do it
        # first so action selection sees the up-to-date state).
        self._accumulate_base_fatigue(self.fighter_a)
        self._accumulate_base_fatigue(self.fighter_b)
        self._decay_stun(self.fighter_a)
        self._decay_stun(self.fighter_b)

        # Ne-waza branches to the ground resolver; no standup physics this tick.
        if self.sub_loop_state == SubLoopState.NE_WAZA:
            self._tick_newaza(tick, events)
            self._post_tick(tick, events)
            return

        # ------------------------------------------------------------------
        # STANDING — Part 3 12-step update
        # ------------------------------------------------------------------

        # Action selection (Part 3.3). Each judoka picks up to two actions
        # based on the priority ladder; COMMIT_THROW supersedes the cap.
        actions_a = select_actions(
            self.fighter_a, self.fighter_b, self.grip_graph,
            self.kumi_kata_clock[self.fighter_a.identity.name],
        )
        actions_b = select_actions(
            self.fighter_b, self.fighter_a, self.grip_graph,
            self.kumi_kata_clock[self.fighter_b.identity.name],
        )

        # Step 1 — grip state updates (REACH/DEEPEN/STRIP/RELEASE/...).
        self._apply_grip_actions(self.fighter_a, actions_a, tick, events)
        self._apply_grip_actions(self.fighter_b, actions_b, tick, events)

        # If still pre-engagement (no edges) and both fighters issued REACH
        # this tick, accumulate engagement_ticks. Seat POCKET grips once the
        # slower fighter's belt-based reach completes.
        self._resolve_engagement(actions_a, actions_b, tick, events)

        # Steps 2-4 — force accumulation + Newton-3 application. Produces
        # per-fighter net force (2D) from all driving actions issued this tick.
        net_force_a = self._compute_net_force_on(
            victim=self.fighter_a, attacker=self.fighter_b, attacker_actions=actions_b,
        )
        net_force_b = self._compute_net_force_on(
            victim=self.fighter_b, attacker=self.fighter_a, attacker_actions=actions_a,
        )

        # Steps 5-7 — CoM velocity/position + trunk angle updates.
        self._apply_physics_update(self.fighter_a, net_force_a)
        self._apply_physics_update(self.fighter_b, net_force_b)

        # Step 8 — BoS update (STEP/SWEEP_LEG are v0.1 stubs).
        self._apply_body_actions(self.fighter_a, actions_a)
        self._apply_body_actions(self.fighter_b, actions_b)

        # Step 9 — kuzushi check (post-update state).
        a_kuzushi = self._is_kuzushi(self.fighter_a)
        b_kuzushi = self._is_kuzushi(self.fighter_b)
        if a_kuzushi and not self._a_was_kuzushi_last_tick:
            events.append(Event(
                tick=tick, event_type="KUZUSHI_INDUCED",
                description=f"[physics] {self.fighter_a.identity.name} off-balance.",
            ))
        if b_kuzushi and not self._b_was_kuzushi_last_tick:
            events.append(Event(
                tick=tick, event_type="KUZUSHI_INDUCED",
                description=f"[physics] {self.fighter_b.identity.name} off-balance.",
            ))
        self._a_was_kuzushi_last_tick = a_kuzushi
        self._b_was_kuzushi_last_tick = b_kuzushi

        # Steps 10 & 11 — compound COMMIT_THROW resolution. Actor iterates
        # both fighters; resolution uses the actual signature for the throw.
        for actor, opp, acts in (
            (self.fighter_a, self.fighter_b, actions_a),
            (self.fighter_b, self.fighter_a, actions_b),
        ):
            for act in acts:
                if act.kind != ActionKind.COMMIT_THROW or act.throw_id is None:
                    continue
                commit_events = self._resolve_commit_throw(
                    actor, opp, act.throw_id, tick,
                )
                events.extend(commit_events)
                if self.match_over:
                    self._post_tick(tick, events)
                    return
                if self.sub_loop_state == SubLoopState.NE_WAZA:
                    # Commit went to ground; stop standing processing.
                    self._post_tick(tick, events)
                    return

        # Step 12 — grip-edge fatigue/clock maintenance (Part 2.4-2.6).
        graph_events = self.grip_graph.tick_update(
            tick, self.fighter_a, self.fighter_b
        )
        events.extend(graph_events)

        # Composure drift from kuzushi states.
        self._update_composure_from_kuzushi(a_kuzushi, b_kuzushi)

        # Stalemate counter: increments on ticks with no kuzushi on either
        # fighter and no commit — referee Matte hinges on this.
        self._update_stalemate_counter(actions_a, actions_b, a_kuzushi, b_kuzushi)

        # Part 2.6 + legacy passivity clocks.
        self._update_grip_passivity(tick, events)
        self._update_passivity(tick, events)

        # Position machine (implicit transitions only in the new model).
        new_pos = PositionMachine.determine_transition(
            self.position, self.sub_loop_state, self.grip_graph,
            self.fighter_a, self.fighter_b, events,
        )
        if new_pos and new_pos != self.position:
            trans_events = self.grip_graph.transform_for_position(
                self.position, new_pos, tick
            )
            events.extend(trans_events)
            self.position = new_pos

        self._post_tick(tick, events)

    # -----------------------------------------------------------------------
    # POST-TICK — osaekomi + matte + emit.
    # -----------------------------------------------------------------------
    def _post_tick(self, tick: int, events: list[Event]) -> None:
        # Osaekomi clock (runs in NE_WAZA only).
        if self.osaekomi.active:
            score_str = self.osaekomi.tick()
            if score_str:
                pin_events = self._apply_pin_score(
                    score_str, self.osaekomi.holder_id, tick
                )
                events.extend(pin_events)

        # Referee: Matte?
        if not self.match_over:
            matte_reason = self.referee.should_call_matte(
                self._build_match_state(tick), tick
            )
            if matte_reason:
                matte_event = self.referee.announce_matte(matte_reason, tick)
                events.append(matte_event)
                self._handle_matte(tick)

        self._print_events(events)

    # -----------------------------------------------------------------------
    # NE-WAZA BRANCH
    # -----------------------------------------------------------------------
    def _tick_newaza(self, tick: int, events: list[Event]) -> None:
        ne_events = self.ne_waza_resolver.tick_resolve(
            position=self.position,
            graph=self.grip_graph,
            fighters=(self._ne_waza_top(), self._ne_waza_bottom()),
            osaekomi=self.osaekomi,
            current_tick=tick,
        )
        events.extend(ne_events)

        for ev in ne_events:
            if ev.event_type == "SUBMISSION_VICTORY":
                winner_name = ev.data.get("winner", "")
                self.winner = (self.fighter_a
                               if self.fighter_a.identity.name == winner_name
                               else self.fighter_b)
                self.match_over = True
                return
            if ev.event_type == "ESCAPE_SUCCESS":
                self.ne_waza_resolver.active_technique = None
                self.osaekomi.break_pin()
                reset_events = self.grip_graph.transform_for_position(
                    self.position, Position.STANDING_DISTANT, tick
                )
                events.extend(reset_events)
                self.position         = Position.STANDING_DISTANT
                self.sub_loop_state   = SubLoopState.STANDING
                self.engagement_ticks = 0
                self.ne_waza_top_id   = None
                break

    # -----------------------------------------------------------------------
    # STEP 1 — GRIP STATE UPDATES
    # -----------------------------------------------------------------------
    def _apply_grip_actions(
        self, judoka: Judoka, actions: list[Action], tick: int,
        events: list[Event],
    ) -> None:
        """REACH / DEEPEN / STRIP / RELEASE / HOLD_CONNECTIVE resolve here.

        REPOSITION_GRIP / DEFEND_GRIP / STRIP_TWO_ON_ONE are defined in the
        action space but v0.1 treats them as no-ops; Parts 4-5 wire them.
        """
        from body_state import ContactState as _CS
        from force_envelope import FORCE_ENVELOPES, grip_strength as _grip_strength

        for act in actions:
            if act.kind not in GRIP_KINDS and act.kind != ActionKind.HOLD_CONNECTIVE:
                continue

            if act.kind == ActionKind.REACH and act.hand is not None:
                ps = judoka.state.body.get(act.hand)
                if ps is not None and ps.contact_state == _CS.FREE:
                    ps.contact_state = _CS.REACHING

            elif act.kind == ActionKind.DEEPEN and act.edge is not None:
                if act.edge in self.grip_graph.edges:
                    self.grip_graph.deepen_grip(act.edge, judoka)

            elif act.kind == ActionKind.STRIP and act.edge is not None:
                if act.edge not in self.grip_graph.edges:
                    continue
                # Stripping force is a driving-class action issued by the
                # stripping hand; magnitude scales with grasper strength.
                strip_force = (
                    FORCE_ENVELOPES[act.edge.grip_type_v2].strip_resistance
                    * 1.1 * _grip_strength(judoka)
                )
                result = self.grip_graph.apply_strip_pressure(
                    act.edge, strip_force, grasper=self._owner(act.edge),
                )
                if result is not None:
                    result.tick = tick
                    events.append(result)

            elif act.kind == ActionKind.RELEASE and act.edge is not None:
                if act.edge in self.grip_graph.edges:
                    self.grip_graph.remove_edge(act.edge)
                    key = act.edge.grasper_part.value
                    if not key.startswith("__"):
                        ps = judoka.state.body.get(key)
                        if ps is not None:
                            ps.contact_state = _CS.FREE

            elif act.kind == ActionKind.HOLD_CONNECTIVE and act.hand is not None:
                # Find any owned edge on this hand and ensure CONNECTIVE mode.
                for edge in self.grip_graph.edges_owned_by(judoka.identity.name):
                    if edge.grasper_part.value == act.hand:
                        edge.mode = GripMode.CONNECTIVE

    def _owner(self, edge: GripEdge) -> Judoka:
        return (self.fighter_a
                if edge.grasper_id == self.fighter_a.identity.name
                else self.fighter_b)

    # -----------------------------------------------------------------------
    # ENGAGEMENT RESOLUTION — both fighters reaching, no edges → seat POCKETs
    # -----------------------------------------------------------------------
    def _resolve_engagement(
        self, actions_a: list[Action], actions_b: list[Action],
        tick: int, events: list[Event],
    ) -> None:
        if self.grip_graph.edge_count() > 0:
            self.engagement_ticks = 0
            return

        a_reaching = any(act.kind == ActionKind.REACH for act in actions_a)
        b_reaching = any(act.kind == ActionKind.REACH for act in actions_b)
        if not (a_reaching and b_reaching):
            self.engagement_ticks = 0
            return

        self.engagement_ticks += 1
        required = max(
            self.grip_graph.reach_ticks_for(self.fighter_a),
            self.grip_graph.reach_ticks_for(self.fighter_b),
            ENGAGEMENT_TICKS_FLOOR,
        )
        if self.engagement_ticks < required:
            return

        new_edges = self.grip_graph.attempt_engagement(
            self.fighter_a, self.fighter_b, tick
        )
        self.engagement_ticks = 0
        for edge in new_edges:
            events.append(Event(
                tick=tick, event_type="GRIP_ESTABLISH",
                description=(
                    f"[grip] {edge.grasper_id} ({edge.grasper_part.value}) → "
                    f"{edge.target_id} ({edge.target_location.value}, "
                    f"{edge.grip_type_v2.name} @ {edge.depth_level.name})"
                ),
            ))
        if new_edges:
            self.position = Position.GRIPPING

    # -----------------------------------------------------------------------
    # STEPS 2-4 — FORCE ACCUMULATION
    # Sum driving-mode forces issued by `attacker` through `attacker`'s grips.
    # Returns a 2D net force vector (Newtons) acting on `victim`'s CoM, in
    # world frame. Newton's 3rd law (Step 3) is applied as a reaction force
    # on the attacker's CoM inside _apply_physics_update via the victim=self
    # recursive pass — actually simpler to return the vector and let the
    # caller apply the reaction.
    # -----------------------------------------------------------------------
    def _compute_net_force_on(
        self,
        victim: Judoka,
        attacker: Judoka,
        attacker_actions: list[Action],
    ) -> tuple[float, float]:
        from force_envelope import (
            FORCE_ENVELOPES, grip_strength as _grip_strength,
        )
        fx = fy = 0.0

        for act in attacker_actions:
            if act.kind not in DRIVING_FORCE_KINDS or act.hand is None:
                continue
            if act.direction is None:
                continue

            # Find the grip this hand is driving through. No grip → no force.
            edge = None
            for e in self.grip_graph.edges_owned_by(attacker.identity.name):
                if e.grasper_part.value == act.hand and e.target_id == victim.identity.name:
                    edge = e
                    break
            if edge is None:
                continue

            # Flip the edge to DRIVING for this tick (affects Part 2.5 fatigue).
            edge.mode = GripMode.DRIVING

            env = FORCE_ENVELOPES[edge.grip_type_v2]
            if act.kind == ActionKind.PUSH:
                env_max = env.max_push_force
            elif act.kind == ActionKind.LIFT:
                env_max = env.max_lift_force
            else:  # PULL, COUPLE, FEINT default to pull envelope
                env_max = env.max_pull_force

            # Calibration pipeline (Part 2.4):
            #   delivered = min(requested, env_max) × depth × strength × fatigue × composure × noise
            depth_mod     = edge.depth_level.modifier()
            strength_mod  = _grip_strength(attacker)
            hand_fatigue  = max(0.0, 1.0 - attacker.state.body[act.hand].fatigue)
            ceiling       = max(1.0, float(attacker.capability.composure_ceiling))
            composure_mod = max(0.0, min(1.0, attacker.state.composure_current / ceiling))
            noise         = 1.0 + random.uniform(-FORCE_NOISE_PCT, FORCE_NOISE_PCT)

            requested = min(act.magnitude, env_max)
            delivered = (requested * depth_mod * strength_mod * hand_fatigue
                         * composure_mod * noise)

            dx, dy = act.direction
            fx += dx * delivered
            fy += dy * delivered

        return (fx, fy)

    # -----------------------------------------------------------------------
    # STEPS 5-7 — CoM + TRUNK UPDATE
    # -----------------------------------------------------------------------
    def _apply_physics_update(self, judoka: Judoka, net_force: tuple[float, float]) -> None:
        fx, fy = net_force
        bs = judoka.state.body_state

        # CoM velocity update with friction damping.
        vx, vy = bs.com_velocity
        vx = vx * FRICTION_DAMPING + (fx / JUDOKA_MASS_KG) * DISPLACEMENT_GAIN * 1000.0
        vy = vy * FRICTION_DAMPING + (fy / JUDOKA_MASS_KG) * DISPLACEMENT_GAIN * 1000.0
        bs.com_velocity = (vx, vy)

        # CoM position update.
        px, py = bs.com_position
        bs.com_position = (px + vx, py + vy)

        # Trunk angle update — stubbed moment arm, maps force-into-sagittal.
        # Force toward the fighter (negative dot with their facing) leans
        # them backward; away-from-fighter force leans them forward. For
        # v0.1 we take fx sign vs facing_x as a crude proxy.
        face_x, face_y = bs.facing
        noise = 1.0 + random.uniform(-TRUNK_NOISE_PCT, TRUNK_NOISE_PCT)
        # Dot of force with facing gives the "forward lean" torque component.
        forward_push = (fx * face_x + fy * face_y)
        bs.trunk_sagittal += forward_push * TRUNK_ANGLE_GAIN * noise
        # Passive + active restoration toward vertical. State.posture is an
        # @property derived from these angles (Part 1.3), so no manual sync.
        bs.trunk_sagittal *= (1.0 - TRUNK_RESTORATION)
        bs.trunk_frontal  *= (1.0 - TRUNK_RESTORATION)

    # -----------------------------------------------------------------------
    # STEP 8 — BoS UPDATE (STEP / SWEEP_LEG)
    # -----------------------------------------------------------------------
    def _apply_body_actions(self, judoka: Judoka, actions: list[Action]) -> None:
        for act in actions:
            if act.kind != ActionKind.STEP or act.foot is None or act.direction is None:
                continue
            bs = judoka.state.body_state
            foot = (bs.foot_state_right if act.foot == "right_foot"
                    else bs.foot_state_left)
            dx, dy = act.direction
            mag = max(0.0, act.magnitude)
            fx, fy = foot.position
            foot.position = (fx + dx * mag, fy + dy * mag)

    # -----------------------------------------------------------------------
    # STEP 9 — KUZUSHI CHECK
    # -----------------------------------------------------------------------
    def _is_kuzushi(self, judoka: Judoka) -> bool:
        from body_state import is_kuzushi
        leg_strength = min(
            judoka.effective_body_part("right_leg"),
            judoka.effective_body_part("left_leg"),
        ) / 10.0
        leg_fatigue = 0.5 * (
            judoka.state.body["right_leg"].fatigue
            + judoka.state.body["left_leg"].fatigue
        )
        ceiling = max(1.0, float(judoka.capability.composure_ceiling))
        composure = max(0.0, min(1.0, judoka.state.composure_current / ceiling))
        return is_kuzushi(
            judoka.state.body_state,
            leg_strength=leg_strength,
            fatigue=leg_fatigue,
            composure=composure,
        )

    # -----------------------------------------------------------------------
    # STEPS 10-11 — COMMIT_THROW RESOLUTION
    # -----------------------------------------------------------------------
    def _resolve_commit_throw(
        self, attacker: Judoka, defender: Judoka, throw_id: ThrowID, tick: int,
    ) -> list[Event]:
        events: list[Event] = []
        actual = actual_signature_match(throw_id, attacker, defender, self.grip_graph)
        throw_name = THROW_REGISTRY[throw_id].name

        events.append(Event(
            tick=tick, event_type="THROW_ENTRY",
            description=(
                f"[throw] {attacker.identity.name} commits — {throw_name} "
                f"(actual match {actual:.2f})."
            ),
        ))

        matchup = self._compute_stance_matchup()
        window_q = max(0.0, actual - 0.5) * 2.0   # 0.5→0.0, 1.0→1.0
        is_forced = actual < 0.5
        outcome, net = resolve_throw(
            attacker, defender, throw_id, matchup,
            window_quality=window_q, is_forced=is_forced,
        )

        events.extend(self._apply_throw_result(
            attacker, defender, throw_id, outcome, net, window_q, tick,
            is_forced=is_forced,
        ))
        self._last_attack_tick[attacker.identity.name] = tick
        self.grip_graph.register_attack(attacker.identity.name)
        self.kumi_kata_clock[attacker.identity.name] = 0
        return events

    # -----------------------------------------------------------------------
    # COMPOSURE / STALEMATE HELPERS
    # -----------------------------------------------------------------------
    def _update_composure_from_kuzushi(
        self, a_kuzushi: bool, b_kuzushi: bool
    ) -> None:
        # Being in kuzushi drops composure; inducing it on the opponent
        # raises yours. Small per-tick deltas — the spec calls for tick
        # outcomes to drive composure (Part 3.4 Step 12).
        drift = 0.05
        if a_kuzushi:
            self.fighter_a.state.composure_current = max(
                0.0, self.fighter_a.state.composure_current - drift
            )
        if b_kuzushi:
            self.fighter_b.state.composure_current = max(
                0.0, self.fighter_b.state.composure_current - drift
            )

    def _update_stalemate_counter(
        self, actions_a: list[Action], actions_b: list[Action],
        a_kuzushi: bool, b_kuzushi: bool,
    ) -> None:
        committed = any(
            act.kind == ActionKind.COMMIT_THROW
            for act in (actions_a + actions_b)
        )
        if committed or a_kuzushi or b_kuzushi:
            self.stalemate_ticks = 0
        else:
            self.stalemate_ticks += 1

    # -----------------------------------------------------------------------
    # APPLY THROW RESULT
    # -----------------------------------------------------------------------
    def _apply_throw_result(
        self,
        attacker: Judoka,
        defender: Judoka,
        throw_id: ThrowID,
        outcome: str,
        net: float,
        window_quality: float,
        tick: int,
        is_forced: bool = False,
    ) -> list[Event]:
        events: list[Event] = []
        a_name = attacker.identity.name
        d_name = defender.identity.name
        throw_name = THROW_REGISTRY[throw_id].name

        # Build landing for referee
        td = THROW_DEFS.get(throw_id)
        landing = ThrowLanding(
            landing_profile=td.landing_profile if td else LandingProfile.LATERAL,
            net_score=net,
            window_quality=window_quality,
            control_maintained=(outcome in ("IPPON", "WAZA_ARI")),
        )

        # Apply throw fatigue to attacker
        self._apply_throw_fatigue(attacker, throw_id, outcome)

        if outcome in ("IPPON", "WAZA_ARI"):
            # Ask referee for the score
            score_result = self.referee.score_throw(landing, tick)
            effective_award = score_result.award

            if effective_award == "IPPON":
                attacker.state.score["ippon"] = True
                self._a_score = attacker.state.score.copy() if attacker is self.fighter_a else self._a_score
                self._b_score = defender.state.score.copy() if defender is self.fighter_b else self._b_score
                self.winner     = attacker
                self.win_method = "ippon"
                self.match_over = True
                ippon_ev = self.referee.announce_ippon(a_name, tick)
                events.append(ippon_ev)
                events.append(self.referee.announce_matte(MatteReason.SCORING, tick))
                events.append(Event(
                    tick=tick,
                    event_type="THROW_LANDING",
                    description=(
                        f"[score] {a_name} → {throw_name} → IPPON "
                        f"(net {net:+.2f}, quality {score_result.technique_quality:.2f})"
                    ),
                ))

            elif effective_award == "WAZA_ARI":
                attacker.state.score["waza_ari"] += 1
                wa_count = attacker.state.score["waza_ari"]
                wa_ev = self.referee.announce_waza_ari(a_name, wa_count, tick)
                events.append(wa_ev)
                events.append(Event(
                    tick=tick,
                    event_type="THROW_LANDING",
                    description=(
                        f"[score] {a_name} → {throw_name} → waza-ari "
                        f"({wa_count}/2, net {net:+.2f})"
                    ),
                ))
                # Composure hit on defender
                defender.state.composure_current = max(
                    0.0,
                    defender.state.composure_current - COMPOSURE_DROP_WAZA_ARI
                )
                if wa_count >= 2:
                    self.winner     = attacker
                    self.win_method = "two waza-ari"
                    self.match_over = True
                    events.append(Event(
                        tick=tick,
                        event_type="IPPON_AWARDED",
                        description=f"[ref: {self.referee.name}] Two waza-ari — Ippon! {a_name} wins.",
                    ))
                else:
                    # Matte after score
                    events.append(self.referee.announce_matte(
                        __import__('enums').MatteReason.SCORING, tick
                    ))
                    self._handle_matte(tick)

            else:  # NO_SCORE despite high raw net — ref downgraded it
                events.append(Event(
                    tick=tick,
                    event_type="THROW_LANDING",
                    description=(
                        f"[throw] {a_name} → {throw_name} → no score "
                        f"(net {net:+.2f}, ref downgraded)"
                    ),
                ))

        elif outcome == "STUFFED":
            self._stuffed_throw_tick = tick
            events.append(Event(
                tick=tick,
                event_type="STUFFED",
                description=(
                    f"[throw] {a_name} stuffed on {throw_name} — "
                    f"{d_name} defends. Ne-waza window open."
                ),
            ))
            # Composure hit on attacker for being stuffed
            attacker.state.composure_current = max(
                0.0,
                attacker.state.composure_current - 0.3
            )
            # Roll for ne-waza commitment
            stuffed_events = self._resolve_newaza_transition(
                attacker, defender, tick
            )
            events.extend(stuffed_events)

        else:  # FAILED
            events.append(Event(
                tick=tick,
                event_type="FAILED",
                description=(
                    f"[throw] {a_name} → {throw_name} → failed "
                    f"(no commitment, net {net:+.2f})"
                ),
            ))

        return events

    # -----------------------------------------------------------------------
    # NE-WAZA TRANSITION (after stuffed throw)
    # -----------------------------------------------------------------------
    def _resolve_newaza_transition(
        self, aggressor: Judoka, defender: Judoka, tick: int
    ) -> list[Event]:
        events: list[Event] = []
        window_q = 0.5  # moderate quality after a stuffed throw

        commits = self.ne_waza_resolver.attempt_ground_commit(
            aggressor, defender, window_q
        )
        if commits:
            # Determine starting position
            start_pos = PositionMachine.ne_waza_start_position(
                was_stuffed=True, aggressor=aggressor, defender=defender
            )
            trans_events = self.grip_graph.transform_for_position(
                self.position, start_pos, tick
            )
            events.extend(trans_events)
            self.position       = start_pos
            self.sub_loop_state = SubLoopState.NE_WAZA
            self._stuffed_throw_tick = 0  # clear — ne-waza is live

            # Set who is on top
            if start_pos == Position.SIDE_CONTROL:
                # Defender is on top (absorbed the throw)
                self.ne_waza_top_id = defender.identity.name
            else:
                self.ne_waza_top_id = aggressor.identity.name

            self.ne_waza_resolver.set_top_fighter(
                self.ne_waza_top_id, (self.fighter_a, self.fighter_b)
            )
            events.append(Event(
                tick=tick,
                event_type="NEWAZA_TRANSITION",
                description=(
                    f"[ne-waza] Ground! {aggressor.identity.name} and "
                    f"{defender.identity.name} transition to "
                    f"{start_pos.name}."
                ),
            ))

        return events

    # -----------------------------------------------------------------------
    # PIN SCORING
    # -----------------------------------------------------------------------
    def _apply_pin_score(
        self, award: str, holder_id: Optional[str], tick: int
    ) -> list[Event]:
        events: list[Event] = []
        if not holder_id:
            return events

        holder = (self.fighter_a if self.fighter_a.identity.name == holder_id
                  else self.fighter_b)
        held   = (self.fighter_b if holder is self.fighter_a else self.fighter_a)

        if award == "IPPON":
            holder.state.score["ippon"] = True
            self.winner     = holder
            self.win_method = "ippon (pin)"
            self.match_over = True
            events.append(self.referee.announce_ippon(holder_id, tick))
            events.append(Event(
                tick=tick,
                event_type="IPPON_AWARDED",
                description=(
                    f"[score] Ippon by pin — {holder_id} wins "
                    f"({self.osaekomi.ticks_held}s hold)."
                ),
            ))
        elif award == "WAZA_ARI":
            holder.state.score["waza_ari"] += 1
            wa_count = holder.state.score["waza_ari"]
            events.append(self.referee.announce_waza_ari(holder_id, wa_count, tick))
            if wa_count >= 2:
                self.winner     = holder
                self.win_method = "two waza-ari"
                self.match_over = True
                events.append(Event(
                    tick=tick,
                    event_type="IPPON_AWARDED",
                    description=f"[score] Two waza-ari — {holder_id} wins.",
                ))
            # Composure hit
            held.state.composure_current = max(
                0.0, held.state.composure_current - COMPOSURE_DROP_WAZA_ARI
            )

        return events

    # -----------------------------------------------------------------------
    # MATTE HANDLING — resets match state for next exchange
    # -----------------------------------------------------------------------
    def _handle_matte(self, tick: int) -> None:
        """Reset the sub-loop for the next exchange after a Matte call."""
        # Break all edges
        self.grip_graph.break_all_edges()
        # Stop osaekomi if running
        if self.osaekomi.active:
            self.osaekomi.break_pin()
        # Reset ne-waza state
        self.ne_waza_resolver.active_technique = None
        self.ne_waza_top_id = None
        # Reset sub-loop to standing + physics state.
        self._stuffed_throw_tick = 0
        self.sub_loop_state      = SubLoopState.STANDING
        self.engagement_ticks    = 0
        self.stalemate_ticks     = 0
        self._a_was_kuzushi_last_tick = False
        self._b_was_kuzushi_last_tick = False
        self.position = Position.STANDING_DISTANT
        # Reset postures + CoM velocity/position for a clean re-engage.
        for i, f in enumerate((self.fighter_a, self.fighter_b)):
            f.state.body_state.trunk_sagittal = 0.0
            f.state.body_state.trunk_frontal  = 0.0
            f.state.body_state.com_velocity   = (0.0, 0.0)
            f.state.body_state.com_position   = (-0.5, 0.0) if i == 0 else (0.5, 0.0)

    # -----------------------------------------------------------------------
    # HELPERS
    # -----------------------------------------------------------------------
    def _compute_stance_matchup(self) -> StanceMatchup:
        a = self.fighter_a.state.current_stance
        b = self.fighter_b.state.current_stance
        return StanceMatchup.MATCHED if a == b else StanceMatchup.MIRRORED

    def _build_match_state(self, tick: int) -> MatchState:
        return MatchState(
            tick=tick,
            position=self.position,
            sub_loop_state=self.sub_loop_state,
            fighter_a_id=self.fighter_a.identity.name,
            fighter_b_id=self.fighter_b.identity.name,
            fighter_a_score=self.fighter_a.state.score,
            fighter_b_score=self.fighter_b.state.score,
            fighter_a_last_attack_tick=self._last_attack_tick.get(
                self.fighter_a.identity.name, 0),
            fighter_b_last_attack_tick=self._last_attack_tick.get(
                self.fighter_b.identity.name, 0),
            fighter_a_shidos=self.fighter_a.state.shidos,
            fighter_b_shidos=self.fighter_b.state.shidos,
            ne_waza_active=(self.sub_loop_state == SubLoopState.NE_WAZA),
            osaekomi_holder_id=self.osaekomi.holder_id,
            osaekomi_ticks=self.osaekomi.ticks_held,
            stalemate_ticks=self.stalemate_ticks,
            stuffed_throw_tick=self._stuffed_throw_tick,
        )

    def _ne_waza_top(self) -> Judoka:
        if self.ne_waza_top_id == self.fighter_b.identity.name:
            return self.fighter_b
        return self.fighter_a

    def _ne_waza_bottom(self) -> Judoka:
        if self.ne_waza_top_id == self.fighter_b.identity.name:
            return self.fighter_a
        return self.fighter_b

    def _apply_throw_fatigue(
        self, attacker: Judoka, throw_id: ThrowID, outcome: str
    ) -> None:
        delta = THROW_FATIGUE.get(outcome, 0.025)
        dom   = attacker.identity.dominant_side
        if throw_id in GRIP_DOMINANT_THROWS:
            parts = (
                ["right_hand", "right_forearm", "core", "lower_back"]
                if dom == DominantSide.RIGHT
                else ["left_hand", "left_forearm", "core", "lower_back"]
            )
        else:
            parts = (
                ["right_leg", "core", "lower_back"]
                if dom == DominantSide.RIGHT
                else ["left_leg", "core", "lower_back"]
            )
        for part in parts:
            attacker.state.body[part].fatigue = min(
                1.0, attacker.state.body[part].fatigue + delta
            )

    def _accumulate_base_fatigue(self, judoka: Judoka) -> None:
        s = judoka.state
        s.body["right_hand"].fatigue = min(1.0, s.body["right_hand"].fatigue + HAND_FATIGUE_PER_TICK)
        s.body["left_hand"].fatigue  = min(1.0, s.body["left_hand"].fatigue  + HAND_FATIGUE_PER_TICK)
        s.cardio_current = max(0.0, s.cardio_current - CARDIO_DRAIN_PER_TICK)

    def _decay_stun(self, judoka: Judoka) -> None:
        if judoka.state.stun_ticks > 0:
            judoka.state.stun_ticks -= 1

    def _update_grip_passivity(self, tick: int, events: list[Event]) -> None:
        """Part 2.6 passivity clocks.

        - Per-fighter kumi-kata clock: ticks while the fighter owns any grip;
          resets on an attack (throw commit). Shido at KUMI_KATA_SHIDO_TICKS.
        - Per-grip unconventional clock: lives on each GripEdge; ticked in
          grip_graph.tick_update(). Shido if any owned edge crosses
          UNCONVENTIONAL_SHIDO_TICKS.
        """
        for fighter in (self.fighter_a, self.fighter_b):
            name = fighter.identity.name
            owned = self.grip_graph.edges_owned_by(name)

            # Kumi-kata clock: advances only while this fighter is gripping.
            if owned:
                self.kumi_kata_clock[name] += 1
            else:
                self.kumi_kata_clock[name] = 0

            reason: Optional[str] = None
            if self.kumi_kata_clock[name] >= KUMI_KATA_SHIDO_TICKS:
                reason = "kumi-kata passivity"
                self.kumi_kata_clock[name] = 0

            # Unconventional-grip clock (per edge).
            for edge in owned:
                if edge.unconventional_clock >= UNCONVENTIONAL_SHIDO_TICKS:
                    reason = reason or (
                        f"unconventional grip ({edge.grip_type_v2.name}) without attack"
                    )
                    edge.unconventional_clock = 0

            if reason is None:
                continue

            fighter.state.shidos += 1
            events.append(Event(
                tick=tick,
                event_type="SHIDO_AWARDED",
                description=(
                    f"[ref: {self.referee.name}] Shido — "
                    f"{name} ({reason}). "
                    f"Total: {fighter.state.shidos}."
                ),
            ))
            if fighter.state.shidos >= 3:
                self.winner     = (self.fighter_b if fighter is self.fighter_a
                                   else self.fighter_a)
                self.win_method = "hansoku-make"
                self.match_over = True

    def _update_passivity(self, tick: int, events: list[Event]) -> None:
        # "Active" = fighter attempted a throw within the last 30 ticks
        for fighter in (self.fighter_a, self.fighter_b):
            was_active = self._last_attack_tick.get(fighter.identity.name, 0) >= tick - 30
            shido = self.referee.update_passivity(
                fighter.identity.name, was_active, tick
            )
            if shido:
                fighter.state.shidos += 1
                events.append(Event(
                    tick=tick,
                    event_type="SHIDO_AWARDED",
                    description=(
                        f"[ref: {self.referee.name}] Shido — "
                        f"{fighter.identity.name} ({shido.reason}). "
                        f"Total: {fighter.state.shidos}."
                    ),
                ))
                if fighter.state.shidos >= 3:
                    self.winner     = (self.fighter_b if fighter is self.fighter_a
                                       else self.fighter_a)
                    self.win_method = "hansoku-make"
                    self.match_over = True

    # -----------------------------------------------------------------------
    # OUTPUT
    # -----------------------------------------------------------------------
    def _print_events(self, events: list[Event]) -> None:
        for ev in events:
            print(f"t{ev.tick:03d}: {ev.description}")

    def _print_header(self) -> None:
        a = self.fighter_a.identity
        b = self.fighter_b.identity
        r = self.referee
        print()
        print("=" * 65)
        print(f"  MATCH: {a.name} (blue) vs {b.name} (white)")
        print(f"  {a.name}: {a.body_archetype.name}, age {a.age}, "
              f"{a.dominant_side.name}-dominant")
        print(f"  {b.name}: {b.body_archetype.name}, age {b.age}, "
              f"{b.dominant_side.name}-dominant")
        print(f"  Referee: {r.name} ({r.nationality}) — "
              f"patience {r.newaza_patience:.1f} / "
              f"strictness {r.ippon_strictness:.1f}")
        print("=" * 65)
        print()

    def _resolve_match(self) -> None:
        print()
        print("=" * 65)
        if self.winner:
            loser = (self.fighter_b if self.winner is self.fighter_a
                     else self.fighter_a)
            method = self.win_method or ("ippon" if self.winner.state.score["ippon"] else "decision")
            print(f"  MATCH OVER — {self.winner.identity.name} wins by {method}")
            print(f"  Score: {self.winner.identity.name} "
                  f"waza-ari={self.winner.state.score['waza_ari']} | "
                  f"{loser.identity.name} "
                  f"waza-ari={loser.state.score['waza_ari']}")
            print(f"  Ended at tick {self.ticks_run}/{self.max_ticks}")
        else:
            a = self.fighter_a
            b = self.fighter_b
            a_wa = a.state.score["waza_ari"]
            b_wa = b.state.score["waza_ari"]
            if a_wa > b_wa:
                self.winner     = a
                self.win_method = "decision"
                print(f"  MATCH OVER — {a.identity.name} wins by decision "
                      f"({a_wa}-{b_wa} waza-ari)")
            elif b_wa > a_wa:
                self.winner     = b
                self.win_method = "decision"
                print(f"  MATCH OVER — {b.identity.name} wins by decision "
                      f"({b_wa}-{a_wa} waza-ari)")
            else:
                self.win_method = "draw"
                print(f"  MATCH OVER — Draw ({a_wa}-{b_wa}). "
                      f"Golden score pending (Phase 3).")
        print("=" * 65)
        self._print_final_state(self.fighter_a)
        self._print_final_state(self.fighter_b)

    def _print_final_state(self, judoka: Judoka) -> None:
        ident = judoka.identity
        cap   = judoka.capability
        state = judoka.state

        print()
        print(f"  {ident.name} — end of match")
        print(f"    score:      waza-ari={state.score['waza_ari']}  "
              f"ippon={state.score['ippon']}  shidos={state.shidos}")
        print(f"    cardio:     {state.cardio_current:.3f}")
        print(f"    composure:  {state.composure_current:.2f} "
              f"/ {cap.composure_ceiling}")
        print(f"    right_hand: eff={judoka.effective_body_part('right_hand'):.2f}  "
              f"fat={state.body['right_hand'].fatigue:.3f}")
        print(f"    right_leg:  eff={judoka.effective_body_part('right_leg'):.2f}  "
              f"fat={state.body['right_leg'].fatigue:.3f}")
        print(f"    core:       eff={judoka.effective_body_part('core'):.2f}  "
              f"fat={state.body['core'].fatigue:.3f}")

        from throws import THROW_REGISTRY as TR
        sig = [TR[t].name for t in cap.signature_throws]
        print(f"    signature:  {', '.join(sig)}")
