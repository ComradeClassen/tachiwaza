# match.py
# Phase 2 Session 2: Match as the conductor.
#
# The Match class now orchestrates all subsystems each tick:
#   1. Body fatigue decay + stun_ticks
#   2. Grip graph tick update (edge aging, force-breaks)
#   3. Sub-loop state machine (ENGAGEMENT → TUG_OF_WAR → KUZUSHI_WINDOW → ...)
#   4. Position transitions (via PositionMachine)
#   5. Throw resolution (grip-graph gated, through Referee scoring)
#   6. Ne-waza (NewazaResolver + OsaekomiClock)
#   7. Referee Matte decisions
#   8. Passivity tracking
#
# What's NOT here:
#   - Coach instructions (Ring 2)
#   - Cultural layer grip selection (Ring 2)
#   - Full prose templating (Phase 4)
#   - Combo chains wired into the sub-loop (Phase 3)
#   - Golden score / tiebreaker (Phase 3)

import random
from dataclasses import dataclass, field
from typing import Optional

from enums import (
    BodyArchetype, DominantSide, MatteReason, Position, Posture, StanceMatchup,
    SubLoopState, LandingProfile,
)
from judoka import Judoka
from throws import ThrowID, ThrowDef, THROW_REGISTRY, THROW_DEFS
from grip_graph import GripGraph, Event
from position_machine import PositionMachine
from referee import Referee, MatchState, ThrowLanding, ScoreResult
from ne_waza import OsaekomiClock, NewazaResolver


# ---------------------------------------------------------------------------
# TUNING CONSTANTS
# All calibration knobs in one place. Phase 3 will tune these after watching
# many matches.
# ---------------------------------------------------------------------------

# Sub-loop timing
KUZUSHI_THRESHOLD:        float = 0.45  # grip_delta above which a window opens
KUZUSHI_MIN_CONSECUTIVE:  int   = 2     # ticks of grip_delta above threshold to open window
STALEMATE_THRESHOLD:      float = 0.12  # grip_delta band considered stalemate
STALEMATE_DURATION:       int   = 18    # ticks of stalemate before STIFLED_RESET
RESET_RECOVERY_TICKS_MIN: int   = 2
RESET_RECOVERY_TICKS_MAX: int   = 4
ENGAGEMENT_TICKS_NEEDED:  int   = 2     # ticks before initial grips form

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

# How often a fighter in a KUZUSHI_WINDOW commits to throw
WINDOW_COMMIT_BASE:   float = 0.65  # probability base per window tick
FORCE_COMMIT_PROB:    float = 0.025  # desperate attempt if no window (~1 per 40 ticks)

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

        # Sub-loop state machine
        self.sub_loop_state = SubLoopState.ENGAGEMENT

        # Sub-loop tracking counters
        self.engagement_ticks    = 0    # ticks spent in ENGAGEMENT
        self.tug_of_war_ticks    = 0    # ticks spent in TUG_OF_WAR
        self.stalemate_ticks     = 0    # ticks grip_delta has been in stalemate band
        self._kuzushi_consecutive = 0   # consecutive ticks above kuzushi threshold
        self.kuzushi_window_ticks  = 0  # ticks spent in KUZUSHI_WINDOW
        self.kuzushi_window_max    = 0  # total ticks available in this window
        self.reset_ticks           = 0  # recovery ticks after stifled reset
        self._reset_duration       = 3

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

        # 1. Body fatigue: background drain + stun_ticks decay
        self._accumulate_base_fatigue(self.fighter_a)
        self._accumulate_base_fatigue(self.fighter_b)
        self._decay_stun(self.fighter_a)
        self._decay_stun(self.fighter_b)

        # 2. Grip graph tick update (age edges, force-break cooked hands)
        if self.sub_loop_state not in (SubLoopState.STIFLED_RESET, SubLoopState.ENGAGEMENT):
            graph_events = self.grip_graph.tick_update(tick, self.fighter_a, self.fighter_b)
            events.extend(graph_events)

        # 3. Sub-loop state machine advance
        sub_events = self._advance_sub_loop(tick)
        events.extend(sub_events)
        if self.match_over:
            self._print_events(events)
            return

        # 4. Position machine: implicit transitions
        new_pos = PositionMachine.determine_transition(
            self.position,
            self.sub_loop_state,
            self.grip_graph,
            self.fighter_a,
            self.fighter_b,
            events,
        )
        if new_pos and new_pos != self.position:
            trans_events = self.grip_graph.transform_for_position(
                self.position, new_pos, tick
            )
            events.extend(trans_events)
            self.position = new_pos

        # 5. Osaekomi clock (if pin is active)
        if self.osaekomi.active:
            score_str = self.osaekomi.tick()
            if score_str:
                pin_events = self._apply_pin_score(
                    score_str, self.osaekomi.holder_id, tick
                )
                events.extend(pin_events)
                if self.match_over:
                    self._print_events(events)
                    return

        # 6. Referee: should Matte be called?
        matte_reason = self.referee.should_call_matte(
            self._build_match_state(tick), tick
        )
        if matte_reason:
            matte_event = self.referee.announce_matte(matte_reason, tick)
            events.append(matte_event)
            self._handle_matte(tick)

        # 7. Passivity
        self._update_passivity(tick, events)

        # 8. Print events
        self._print_events(events)

    # -----------------------------------------------------------------------
    # SUB-LOOP STATE MACHINE
    # -----------------------------------------------------------------------
    def _advance_sub_loop(self, tick: int) -> list[Event]:
        events: list[Event] = []

        state = self.sub_loop_state

        # -----------------------------------------------------------------
        if state == SubLoopState.ENGAGEMENT:
            self.engagement_ticks += 1
            if self.engagement_ticks >= ENGAGEMENT_TICKS_NEEDED:
                new_edges = self.grip_graph.attempt_engagement(
                    self.fighter_a, self.fighter_b, tick
                )
                if new_edges:
                    for edge in new_edges:
                        events.append(Event(
                            tick=tick,
                            event_type="GRIP_ESTABLISH",
                            description=(
                                f"[grip] {edge.grasper_id} "
                                f"({edge.grasper_part.value}) → "
                                f"{edge.target_id} "
                                f"({edge.target_location.value}, "
                                f"{edge.grip_type.name}, "
                                f"depth {edge.depth:.2f})"
                            ),
                        ))
                    self.sub_loop_state  = SubLoopState.TUG_OF_WAR
                    self.position        = Position.GRIPPING
                    self.tug_of_war_ticks = 0
                    self.stalemate_ticks  = 0
                    self._kuzushi_consecutive = 0

        # -----------------------------------------------------------------
        elif state == SubLoopState.TUG_OF_WAR:
            self.tug_of_war_ticks += 1
            grip_delta = self.grip_graph.compute_grip_delta(
                self.fighter_a, self.fighter_b
            )

            if abs(grip_delta) < STALEMATE_THRESHOLD:
                # Stalemate band
                self._kuzushi_consecutive = 0
                self.stalemate_ticks += 1
                if self.stalemate_ticks >= STALEMATE_DURATION:
                    # STIFLED_RESET
                    broken = self.grip_graph.break_all_edges()
                    events.append(Event(
                        tick=tick,
                        event_type="STIFLED_RESET",
                        description=(
                            f"[grip] Stifled reset — {len(broken)} edge(s) broken. "
                            f"Both fighters step back."
                        ),
                    ))
                    self.sub_loop_state  = SubLoopState.STIFLED_RESET
                    self.position        = Position.STANDING_DISTANT
                    self.stalemate_ticks = 0
                    self.reset_ticks     = 0
                    self._reset_duration = random.randint(
                        RESET_RECOVERY_TICKS_MIN, RESET_RECOVERY_TICKS_MAX
                    )

            elif grip_delta > KUZUSHI_THRESHOLD or grip_delta < -KUZUSHI_THRESHOLD:
                # Above threshold — accumulate consecutive ticks
                self.stalemate_ticks = 0
                self._kuzushi_consecutive += 1
                if self._kuzushi_consecutive >= KUZUSHI_MIN_CONSECUTIVE:
                    # Window opens
                    window_size = random.randint(1, 3)
                    self.kuzushi_window_ticks = 0
                    self.kuzushi_window_max   = window_size
                    self.sub_loop_state = SubLoopState.KUZUSHI_WINDOW
                    self.position       = Position.ENGAGED
                    leader = (
                        self.fighter_a if grip_delta > 0 else self.fighter_b
                    )
                    events.append(Event(
                        tick=tick,
                        event_type="KUZUSHI_WINDOW_OPENED",
                        description=(
                            f"[grip] Kuzushi window — "
                            f"{leader.identity.name} dominant "
                            f"(delta {grip_delta:+.2f}). "
                            f"Window: {window_size} tick(s)."
                        ),
                    ))
            else:
                self.stalemate_ticks = 0
                self._kuzushi_consecutive = 0

            # Occasionally attempt a forced throw (desperation)
            if (self.sub_loop_state == SubLoopState.TUG_OF_WAR
                    and random.random() < FORCE_COMMIT_PROB):
                attacker, defender = self._pick_attacker()
                force_events = self._try_forced_throw(attacker, defender, tick)
                events.extend(force_events)

        # -----------------------------------------------------------------
        elif state == SubLoopState.KUZUSHI_WINDOW:
            self.kuzushi_window_ticks += 1

            # Which fighter has the grip advantage?
            grip_delta = self.grip_graph.compute_grip_delta(
                self.fighter_a, self.fighter_b
            )
            attacker = self.fighter_a if grip_delta > 0 else self.fighter_b
            defender = self.fighter_b if grip_delta > 0 else self.fighter_a
            window_q = min(1.0, abs(grip_delta) / 4.0)

            # Roll for commitment each tick of the window
            commit_prob = min(
                0.92,
                WINDOW_COMMIT_BASE + window_q * 0.3
            )
            if random.random() < commit_prob:
                throw_events = self._try_throw_from_window(
                    attacker, defender, tick, window_q
                )
                events.extend(throw_events)
                if self.match_over:
                    return events
                # After any throw attempt the window is consumed
                self.sub_loop_state      = SubLoopState.TUG_OF_WAR
                self._kuzushi_consecutive = 0
            elif self.kuzushi_window_ticks >= self.kuzushi_window_max:
                # Window expired — opportunity wasted
                events.append(Event(
                    tick=tick,
                    event_type="KUZUSHI_WINDOW_CLOSED",
                    description=(
                        f"[grip] Kuzushi window closed — "
                        f"{attacker.identity.name} didn't commit."
                    ),
                ))
                self.sub_loop_state      = SubLoopState.TUG_OF_WAR
                self._kuzushi_consecutive = 0

        # -----------------------------------------------------------------
        elif state == SubLoopState.STIFLED_RESET:
            self.reset_ticks += 1
            if self.reset_ticks >= self._reset_duration:
                self.engagement_ticks = 0
                self.sub_loop_state   = SubLoopState.ENGAGEMENT
                events.append(Event(
                    tick=tick,
                    event_type="ENGAGEMENT_BEGUN",
                    description=(
                        f"[engage] {self.fighter_a.identity.name} and "
                        f"{self.fighter_b.identity.name} re-engage."
                    ),
                ))

        # -----------------------------------------------------------------
        elif state == SubLoopState.NE_WAZA:
            ne_events = self.ne_waza_resolver.tick_resolve(
                position=self.position,
                graph=self.grip_graph,
                fighters=(self._ne_waza_top(), self._ne_waza_bottom()),
                osaekomi=self.osaekomi,
                current_tick=tick,
            )
            events.extend(ne_events)

            # Check for match-ending ne-waza events
            for ev in ne_events:
                if ev.event_type == "SUBMISSION_VICTORY":
                    winner_name = ev.data.get("winner", "")
                    self.winner   = (self.fighter_a
                                     if self.fighter_a.identity.name == winner_name
                                     else self.fighter_b)
                    self.match_over = True
                    return events

                if ev.event_type == "ESCAPE_SUCCESS":
                    # Transition back to standing
                    self.ne_waza_resolver.active_technique = None
                    self.osaekomi.break_pin()
                    reset_events = self.grip_graph.transform_for_position(
                        self.position, Position.STANDING_DISTANT, tick
                    )
                    events.extend(reset_events)
                    self.position       = Position.STANDING_DISTANT
                    self.sub_loop_state = SubLoopState.ENGAGEMENT
                    self.engagement_ticks = 0
                    self.ne_waza_top_id   = None
                    break

        return events

    # -----------------------------------------------------------------------
    # THROW RESOLUTION — from kuzushi window
    # -----------------------------------------------------------------------
    def _try_throw_from_window(
        self,
        attacker: Judoka,
        defender: Judoka,
        tick: int,
        window_quality: float,
    ) -> list[Event]:
        events: list[Event] = []

        # Pick a throw satisfying the current graph
        throw_id = self._pick_throw_for_graph(attacker)
        if throw_id is None:
            # No throw in vocabulary satisfies the graph — window closes wasted
            events.append(Event(
                tick=tick,
                event_type="KUZUSHI_WINDOW_WASTED",
                description=(
                    f"[grip] Window open but no throw fits "
                    f"{attacker.identity.name}'s current grip config."
                ),
            ))
            return events

        throw_name = THROW_REGISTRY[throw_id].name
        events.append(Event(
            tick=tick,
            event_type="THROW_ENTRY",
            description=(
                f"[throw] {attacker.identity.name} commits — "
                f"{throw_name}."
            ),
        ))

        matchup = self._compute_stance_matchup()
        outcome, net = resolve_throw(
            attacker, defender, throw_id, matchup, window_quality
        )

        result_events = self._apply_throw_result(
            attacker, defender, throw_id, outcome, net, window_quality, tick
        )
        events.extend(result_events)

        # Update last-attack tick
        self._last_attack_tick[attacker.identity.name] = tick

        return events

    # -----------------------------------------------------------------------
    # FORCED THROW ATTEMPT (no window, desperation)
    # -----------------------------------------------------------------------
    def _try_forced_throw(
        self, attacker: Judoka, defender: Judoka, tick: int
    ) -> list[Event]:
        events: list[Event] = []

        # Forced throws don't check prerequisites — they are the "sloppy" attempt
        throw_id = self._pick_throw(attacker)
        throw_name = THROW_REGISTRY[throw_id].name

        matchup  = self._compute_stance_matchup()
        outcome, net = resolve_throw(
            attacker, defender, throw_id, matchup,
            window_quality=0.0, is_forced=True
        )

        events.append(Event(
            tick=tick,
            event_type="THROW_FORCED",
            description=(
                f"[throw] {attacker.identity.name} forces {throw_name} "
                f"(no window) — {outcome}."
            ),
        ))

        result_events = self._apply_throw_result(
            attacker, defender, throw_id, outcome, net, 0.0, tick,
            is_forced=True
        )
        events.extend(result_events)

        self._last_attack_tick[attacker.identity.name] = tick
        return events

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
        # Reset sub-loop
        self._stuffed_throw_tick = 0
        self.sub_loop_state      = SubLoopState.ENGAGEMENT
        self.engagement_ticks    = 0
        self.tug_of_war_ticks    = 0
        self.stalemate_ticks     = 0
        self._kuzushi_consecutive = 0
        self.position = Position.STANDING_DISTANT
        # Reset postures
        self.fighter_a.state.posture = Posture.UPRIGHT
        self.fighter_b.state.posture = Posture.UPRIGHT

    # -----------------------------------------------------------------------
    # HELPERS
    # -----------------------------------------------------------------------
    def _pick_throw_for_graph(self, judoka: Judoka) -> Optional[ThrowID]:
        """Pick a throw whose prerequisites are satisfied by the current grip graph."""
        # Signature throws first
        for throw_id in judoka.capability.signature_throws:
            td = THROW_DEFS.get(throw_id)
            if td and self.grip_graph.satisfies(
                td.requires, judoka.identity.name, judoka.identity.dominant_side
            ):
                if judoka.capability.throw_profiles.get(throw_id):
                    return throw_id

        # Full vocabulary
        candidates = [
            t for t in judoka.capability.throw_vocabulary
            if (td := THROW_DEFS.get(t)) is not None
            and self.grip_graph.satisfies(
                td.requires, judoka.identity.name, judoka.identity.dominant_side
            )
            and judoka.capability.throw_profiles.get(t) is not None
        ]
        return random.choice(candidates) if candidates else None

    def _pick_throw(self, judoka: Judoka) -> ThrowID:
        """Pick any throw from vocabulary (ignoring prerequisites)."""
        sig = judoka.capability.signature_throws
        if sig and random.random() < 0.65:
            return random.choice(sig)
        return random.choice(judoka.capability.throw_vocabulary)

    def _pick_attacker(self) -> tuple[Judoka, Judoka]:
        """Randomly select which fighter attacks this tick."""
        if random.random() < 0.5:
            return self.fighter_a, self.fighter_b
        return self.fighter_b, self.fighter_a

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
