# ne_waza.py
# The ne-waza (ground work) system.
# Manages: position progressions, osaekomi clock, commitment chains, escapes.
#
# Phase 2 Session 2 ships:
#   - OsaekomiClock: pin clock with WAZA_ARI at 10 ticks, IPPON at 20
#   - NewazaResolver: per-tick ne-waza logic — choke, armbar, pin, escape rolls
#   - Commitment chains: okuri-eri-jime (choke), juji-gatame (armbar)
#   - Pin types: kesa-gatame, yoko-shiho-gatame
#   - Counter-actions available each tick (FRAME, HIP_OUT, BRIDGE, etc.)
#
# Design discipline: the bottom fighter always has something to do each tick.
# A choke is not a cutscene — it is contested edge-by-edge resolution where
# the defender fights for their life and the top fighter commits real resources.

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, TYPE_CHECKING

from enums import Position, CounterAction
from grip_graph import Event

if TYPE_CHECKING:
    from judoka import Judoka
    from grip_graph import GripGraph
    from referee import ScoreResult


# ---------------------------------------------------------------------------
# NE-WAZA TECHNIQUE STATE
# Tracks which ground technique is in progress and how far along the chain.
# ---------------------------------------------------------------------------
class NeWazaTechniqueState(Enum):
    """Stages within a submission chain."""
    # Choke chain (okuri-eri-jime)
    CHOKE_INITIATING   = auto()   # establishing neck edge (ticks 0–2)
    CHOKE_SETTING      = auto()   # setting choke configuration (ticks 3–6)
    CHOKE_TIGHTENING   = auto()   # pressure applied, escape rolls happening
    CHOKE_RESOLVED     = auto()   # either tap or failed

    # Armbar chain (juji-gatame)
    ARMBAR_ISOLATING   = auto()   # isolate arm, establish wrist/elbow edges
    ARMBAR_POSITIONING = auto()   # legs across body, hip onto shoulder
    ARMBAR_EXTENDING   = auto()   # extension phase — tap-or-escape
    ARMBAR_RESOLVED    = auto()   # tap or failed

    # Pin — no chain, just the clock
    PIN_HOLDING        = auto()   # osaekomi active
    PIN_BROKEN         = auto()   # escape succeeded


@dataclass
class ActiveTechnique:
    """State machine for a single in-progress ne-waza technique."""
    name: str                          # display name for logging
    technique_state: NeWazaTechniqueState
    aggressor_id: str                  # who is applying the technique
    defender_id: str
    chain_tick: int = 0                # ticks spent in the current state


# ---------------------------------------------------------------------------
# OSAEKOMI CLOCK
# Tracks the pin clock. The referee announces Osaekomi when the clock starts;
# it runs until escape or the time threshold is reached.
# ---------------------------------------------------------------------------
class OsaekomiClock:
    """Pin clock. 10 ticks = WAZA_ARI; 20 ticks = IPPON (IJF rules: 10s/20s)."""

    WAZA_ARI_TICKS: int = 10
    IPPON_TICKS:    int = 20

    def __init__(self) -> None:
        self.holder_id:    Optional[str]      = None
        self.position:     Optional[Position] = None
        self.ticks_held:   int = 0
        self.is_running:   bool = False

    def start(self, holder_id: str, position: Position) -> None:
        """Start or restart the osaekomi clock."""
        self.holder_id  = holder_id
        self.position   = position
        self.ticks_held = 0
        self.is_running = True

    def tick(self) -> Optional[str]:
        """Advance the clock by one tick. Returns 'WAZA_ARI', 'IPPON', or None."""
        if not self.is_running:
            return None
        self.ticks_held += 1
        if self.ticks_held >= self.IPPON_TICKS:
            self.is_running = False
            return "IPPON"
        if self.ticks_held == self.WAZA_ARI_TICKS:
            return "WAZA_ARI"
        return None

    def break_pin(self) -> None:
        """Escape! Stop the clock without a score."""
        self.is_running = False
        self.holder_id  = None
        self.ticks_held = 0

    @property
    def active(self) -> bool:
        return self.is_running


# ---------------------------------------------------------------------------
# NE-WAZA RESOLVER
# Per-tick resolution of ground work.
# ---------------------------------------------------------------------------
class NewazaResolver:
    """Drives ground work each tick. Called by match._tick() when in NE_WAZA."""

    # Tuning knobs — Phase 3 calibration
    BASE_ESCAPE_PROB:        float = 0.08   # per-tick baseline escape probability
    SKILL_ESCAPE_BONUS:      float = 0.025  # bonus per point of ne_waza_skill
    CARDIO_ESCAPE_MULT:      float = 0.6    # escape prob scales with cardio
    CHOKE_BASE_TIGHTEN_PROB: float = 0.7    # per-tick chance choke advances
    ARMBAR_BASE_EXTEND_PROB: float = 0.65
    TECHNIQUE_ATTEMPT_PROB:  float = 0.25   # chance top fighter initiates a technique

    def __init__(self) -> None:
        self.active_technique: Optional[ActiveTechnique] = None

    # -----------------------------------------------------------------------
    # ATTEMPT GROUND COMMIT
    # Called when a throw is stuffed. Rolls for whether either fighter drives
    # to the ground. Returns True if the ground transition happens.
    # -----------------------------------------------------------------------
    def attempt_ground_commit(
        self,
        aggressor: "Judoka",
        defender: "Judoka",
        window_quality: float,
    ) -> bool:
        """Roll whether the fighters go to the ground after a stuffed throw.

        Either fighter committing transitions both to NE_WAZA.
        The fighter with higher ne_waza_skill and lower fatigue is more
        likely to commit — they see the ground window and go for it.
        """
        agg_nw  = aggressor.capability.ne_waza_skill / 10.0
        def_nw  = defender.capability.ne_waza_skill / 10.0
        agg_fat = 1.0 - (aggressor.state.cardio_current * 0.5 +
                         0.5 * (1.0 - aggressor.state.body["core"].fatigue))
        def_fat = 1.0 - (defender.state.cardio_current * 0.5 +
                         0.5 * (1.0 - defender.state.body["core"].fatigue))

        # Either fighter committing is enough
        agg_commit_prob = agg_nw * (1.0 - agg_fat) * window_quality * 0.6
        def_commit_prob = def_nw * (1.0 - def_fat) * 0.5   # defender opportunistic

        return (random.random() < agg_commit_prob
                or random.random() < def_commit_prob)

    # -----------------------------------------------------------------------
    # PER-TICK RESOLUTION
    # -----------------------------------------------------------------------
    def tick_resolve(
        self,
        position: Position,
        graph: "GripGraph",
        fighters: tuple["Judoka", "Judoka"],
        osaekomi: OsaekomiClock,
        current_tick: int,
    ) -> list[Event]:
        """One tick of ne-waza. Returns events for anything notable."""
        events: list[Event] = []
        top_fighter, bottom_fighter = self._determine_top_bottom(position, fighters)

        if top_fighter is None:
            return events

        # --- Counter-action available to bottom fighter each tick ---
        counter = self._pick_counter_action(bottom_fighter)
        counter_success = self._resolve_counter(counter, bottom_fighter, top_fighter)

        # --- Escape attempt ---
        escaped = self._roll_escape(bottom_fighter, top_fighter, position)
        if escaped:
            if osaekomi.active:
                ticks_held = osaekomi.ticks_held  # read before break_pin() resets it
                osaekomi.break_pin()
                events.append(Event(
                    tick=current_tick,
                    event_type="OSAEKOMI_BROKEN",
                    description=(
                        f"[ne-waza] {bottom_fighter.identity.name} breaks the pin! "
                        f"Clock stopped at {ticks_held} ticks."
                    ),
                ))
            events.append(Event(
                tick=current_tick,
                event_type="ESCAPE_SUCCESS",
                description=(
                    f"[ne-waza] {bottom_fighter.identity.name} escapes — "
                    f"back to standing."
                ),
                data={"escapee": bottom_fighter.identity.name},
            ))
            self.active_technique = None
            return events

        # Log counter-action if it was notable
        if counter_success:
            events.append(Event(
                tick=current_tick,
                event_type="COUNTER_ACTION",
                description=(
                    f"[ne-waza] {bottom_fighter.identity.name} "
                    f"{counter.name.lower().replace('_', '-')} — partial success."
                ),
            ))

        # --- Active technique chain ---
        if self.active_technique:
            tech_events = self._advance_technique(
                self.active_technique, top_fighter, bottom_fighter, current_tick
            )
            events.extend(tech_events)
        else:
            # --- Initiate a new technique ---
            if random.random() < self.TECHNIQUE_ATTEMPT_PROB:
                tech = self._choose_technique(
                    top_fighter, bottom_fighter, position, current_tick
                )
                if tech:
                    self.active_technique = tech
                    events.append(Event(
                        tick=current_tick,
                        event_type=f"{tech.name.upper().replace('-','_').replace(' ','_')}_INITIATED",
                        description=(
                            f"[ne-waza] {top_fighter.identity.name} initiates "
                            f"{tech.name}."
                        ),
                    ))
            elif not osaekomi.active and position in (
                    Position.SIDE_CONTROL, Position.MOUNT, Position.BACK_CONTROL):
                # Start a pin if none active
                osaekomi.start(top_fighter.identity.name, position)
                events.append(Event(
                    tick=current_tick,
                    event_type="OSAEKOMI_BEGIN",
                    description=(
                        f"[ne-waza] {top_fighter.identity.name} establishes hold — "
                        f"osaekomi begins."
                    ),
                    data={"holder": top_fighter.identity.name},
                ))

        # --- Fatigue accumulation ---
        self._apply_ne_waza_fatigue(top_fighter, bottom_fighter)

        return events

    # -----------------------------------------------------------------------
    # TECHNIQUE CHAIN ADVANCEMENT
    # -----------------------------------------------------------------------
    def _advance_technique(
        self,
        tech: ActiveTechnique,
        top: "Judoka",
        bottom: "Judoka",
        tick: int,
    ) -> list[Event]:
        events: list[Event] = []
        tech.chain_tick += 1

        # --- CHOKE CHAIN ---
        if tech.technique_state in (
            NeWazaTechniqueState.CHOKE_INITIATING,
            NeWazaTechniqueState.CHOKE_SETTING,
            NeWazaTechniqueState.CHOKE_TIGHTENING,
        ):
            events.extend(self._advance_choke(tech, top, bottom, tick))

        # --- ARMBAR CHAIN ---
        elif tech.technique_state in (
            NeWazaTechniqueState.ARMBAR_ISOLATING,
            NeWazaTechniqueState.ARMBAR_POSITIONING,
            NeWazaTechniqueState.ARMBAR_EXTENDING,
        ):
            events.extend(self._advance_armbar(tech, top, bottom, tick))

        return events

    def _advance_choke(
        self, tech: ActiveTechnique, top: "Judoka", bottom: "Judoka", tick: int
    ) -> list[Event]:
        events: list[Event] = []
        ct = tech.chain_tick

        if tech.technique_state == NeWazaTechniqueState.CHOKE_INITIATING:
            if ct >= 3:
                tech.technique_state = NeWazaTechniqueState.CHOKE_SETTING
                events.append(Event(tick, "CHOKE_SETTING",
                    f"[ne-waza] {top.identity.name} sets the collar — "
                    f"choke configuration established."))

        elif tech.technique_state == NeWazaTechniqueState.CHOKE_SETTING:
            if ct >= 6:
                tech.technique_state = NeWazaTechniqueState.CHOKE_TIGHTENING
                events.append(Event(tick, "CHOKE_TIGHTENING",
                    f"[ne-waza] {top.identity.name} begins tightening the choke."))

        elif tech.technique_state == NeWazaTechniqueState.CHOKE_TIGHTENING:
            # Each tick: roll for tap vs roll for survival
            top_nw    = top.capability.ne_waza_skill / 10.0
            bottom_nw = bottom.capability.ne_waza_skill / 10.0
            cardio_factor = bottom.state.cardio_current

            tighten_success = random.random() < (
                self.CHOKE_BASE_TIGHTEN_PROB * top_nw / max(bottom_nw * cardio_factor, 0.1)
            )
            if tighten_success:
                events.append(Event(tick, "CHOKE_TIGHTENING",
                    f"[ne-waza] Choke tightens — {bottom.identity.name} running out of time."))

                # After 6+ ticks of tightening: submission
                if ct >= 12:
                    tech.technique_state = NeWazaTechniqueState.CHOKE_RESOLVED
                    events.append(Event(tick, "SUBMISSION_VICTORY",
                        f"[ne-waza] {bottom.identity.name} taps! "
                        f"Ippon — {top.identity.name} wins by submission.",
                        data={"winner": top.identity.name,
                              "loser": bottom.identity.name,
                              "technique": "okuri-eri-jime"}))
                    self.active_technique = None
            else:
                # Choke failed to tighten — bottom fighter survives this tick
                if ct >= 12 and random.random() < 0.4:
                    tech.technique_state = NeWazaTechniqueState.CHOKE_RESOLVED
                    events.append(Event(tick, "CHOKE_FAILED",
                        f"[ne-waza] {bottom.identity.name} survives the choke — "
                        f"position lost."))
                    self.active_technique = None

        return events

    def _advance_armbar(
        self, tech: ActiveTechnique, top: "Judoka", bottom: "Judoka", tick: int
    ) -> list[Event]:
        events: list[Event] = []
        ct = tech.chain_tick

        if tech.technique_state == NeWazaTechniqueState.ARMBAR_ISOLATING:
            if ct >= 3:
                tech.technique_state = NeWazaTechniqueState.ARMBAR_POSITIONING
                events.append(Event(tick, "ARMBAR_POSITIONING",
                    f"[ne-waza] {top.identity.name} positions legs across "
                    f"{bottom.identity.name}'s body."))

        elif tech.technique_state == NeWazaTechniqueState.ARMBAR_POSITIONING:
            if ct >= 6:
                tech.technique_state = NeWazaTechniqueState.ARMBAR_EXTENDING
                events.append(Event(tick, "ARMBAR_EXTENDING",
                    f"[ne-waza] {top.identity.name} begins extending — "
                    f"juji-gatame threat."))

        elif tech.technique_state == NeWazaTechniqueState.ARMBAR_EXTENDING:
            top_nw    = top.capability.ne_waza_skill / 10.0
            bottom_nw = bottom.capability.ne_waza_skill / 10.0
            extend_prob = self.ARMBAR_BASE_EXTEND_PROB * (top_nw / max(bottom_nw, 0.1))

            if random.random() < extend_prob:
                if ct >= 10:
                    tech.technique_state = NeWazaTechniqueState.ARMBAR_RESOLVED
                    events.append(Event(tick, "SUBMISSION_VICTORY",
                        f"[ne-waza] {bottom.identity.name} taps! "
                        f"Ippon — {top.identity.name} wins by juji-gatame.",
                        data={"winner": top.identity.name,
                              "loser": bottom.identity.name,
                              "technique": "juji-gatame"}))
                    self.active_technique = None
                else:
                    events.append(Event(tick, "ARMBAR_EXTENDING",
                        f"[ne-waza] {top.identity.name} extends further — "
                        f"arm under pressure."))
            else:
                if ct >= 10 and random.random() < 0.35:
                    tech.technique_state = NeWazaTechniqueState.ARMBAR_RESOLVED
                    events.append(Event(tick, "ARMBAR_FAILED",
                        f"[ne-waza] {bottom.identity.name} defends the armbar — "
                        f"grip maintained."))
                    self.active_technique = None

        return events

    # -----------------------------------------------------------------------
    # ESCAPE ROLL
    # -----------------------------------------------------------------------
    def _roll_escape(
        self, bottom: "Judoka", top: "Judoka", position: Position
    ) -> bool:
        """Roll whether the bottom fighter escapes this tick."""
        skill_bonus = bottom.capability.ne_waza_skill * self.SKILL_ESCAPE_BONUS
        cardio_mod  = bottom.state.cardio_current ** self.CARDIO_ESCAPE_MULT
        composure_mod = bottom.state.composure_current / max(
            float(bottom.capability.composure_ceiling), 1.0
        )

        # Position difficulty: back control is hardest to escape
        position_difficulty = {
            Position.SIDE_CONTROL: 1.0,
            Position.MOUNT:        0.7,
            Position.BACK_CONTROL: 0.5,
            Position.GUARD_TOP:    1.5,
            Position.GUARD_BOTTOM: 1.5,
            Position.TURTLE_TOP:   0.8,
            Position.TURTLE_BOTTOM: 1.2,
        }.get(position, 1.0)

        escape_prob = (
            (self.BASE_ESCAPE_PROB + skill_bonus)
            * cardio_mod
            * composure_mod
            * position_difficulty
        )
        return random.random() < escape_prob

    # -----------------------------------------------------------------------
    # COUNTER-ACTION RESOLUTION
    # -----------------------------------------------------------------------
    def _pick_counter_action(self, bottom: "Judoka") -> CounterAction:
        """Choose the most likely counter-action based on ne_waza_skill."""
        skill = bottom.capability.ne_waza_skill
        if skill >= 7:
            # Skilled fighters have a wider repertoire
            return random.choice([
                CounterAction.HAND_FIGHT, CounterAction.FRAME,
                CounterAction.HIP_OUT, CounterAction.SHRIMP,
                CounterAction.BRIDGE,
            ])
        elif skill >= 4:
            return random.choice([
                CounterAction.FRAME, CounterAction.HIP_OUT,
                CounterAction.SHRIMP,
            ])
        else:
            return random.choice([CounterAction.FRAME, CounterAction.BRIDGE])

    def _resolve_counter(
        self, counter: CounterAction, bottom: "Judoka", top: "Judoka"
    ) -> bool:
        """Returns True if the counter action had a notable effect."""
        effectiveness = {
            CounterAction.HAND_FIGHT: bottom.effective_body_part("right_hand") / 10,
            CounterAction.FRAME:      bottom.effective_body_part("right_forearm") / 10,
            CounterAction.HIP_OUT:    bottom.effective_body_part("core") / 10,
            CounterAction.BRIDGE:     bottom.effective_body_part("lower_back") / 10,
            CounterAction.TURNOVER:   bottom.effective_body_part("right_thigh") / 10,
            CounterAction.SHRIMP:     bottom.effective_body_part("right_hip") / 10,
        }.get(counter, 0.5)

        return random.random() < effectiveness * 0.4

    # -----------------------------------------------------------------------
    # TECHNIQUE SELECTION
    # -----------------------------------------------------------------------
    def _choose_technique(
        self,
        top: "Judoka",
        bottom: "Judoka",
        position: Position,
        tick: int,
    ) -> Optional[ActiveTechnique]:
        """Decide which ground technique to attempt based on position and skill."""
        nw = top.capability.ne_waza_skill

        pos_name = position.name

        # Choke: available from back/side control, requires skill >= 4
        can_choke = (nw >= 4
                     and pos_name in ("BACK_CONTROL", "SIDE_CONTROL"))

        # Armbar: available from guard top, side, mount, requires skill >= 5
        can_armbar = (nw >= 5
                      and pos_name in ("GUARD_TOP", "SIDE_CONTROL", "MOUNT"))

        options = []
        if can_choke:   options.append("choke")
        if can_armbar:  options.append("armbar")

        if not options:
            return None

        choice = random.choice(options)
        if choice == "choke":
            return ActiveTechnique(
                name="Okuri-eri-jime",
                technique_state=NeWazaTechniqueState.CHOKE_INITIATING,
                aggressor_id=top.identity.name,
                defender_id=bottom.identity.name,
            )
        else:
            return ActiveTechnique(
                name="Juji-gatame",
                technique_state=NeWazaTechniqueState.ARMBAR_ISOLATING,
                aggressor_id=top.identity.name,
                defender_id=bottom.identity.name,
            )

    # -----------------------------------------------------------------------
    # HELPERS
    # -----------------------------------------------------------------------
    def _determine_top_bottom(
        self, position: Position, fighters: tuple["Judoka", "Judoka"]
    ) -> tuple[Optional["Judoka"], Optional["Judoka"]]:
        """Return (top_fighter, bottom_fighter) or (None, None) if ambiguous."""
        a, b = fighters
        # The position context tells us who is on top
        # For SIDE_CONTROL / MOUNT / BACK_CONTROL: fighter_a is top (the scorer)
        # This is tracked in match.py via ne_waza_top_id; for now use a heuristic
        if position in (Position.SIDE_CONTROL, Position.MOUNT, Position.BACK_CONTROL,
                        Position.TURTLE_TOP, Position.GUARD_TOP):
            return a, b
        elif position in (Position.GUARD_BOTTOM, Position.TURTLE_BOTTOM):
            return b, a
        return a, b   # default

    def set_top_fighter(self, top_id: str, fighters: tuple["Judoka", "Judoka"]) -> None:
        """Called by match.py to tell the resolver who is on top."""
        self._top_id = top_id

    def _apply_ne_waza_fatigue(
        self, top: "Judoka", bottom: "Judoka"
    ) -> None:
        """Both fighters fatigue during ne-waza, differently by role."""
        # Top fighter: core and hips doing the work
        for part in ("core", "right_hip", "left_hip"):
            top.state.body[part].fatigue = min(
                1.0, top.state.body[part].fatigue + 0.003
            )
        # Bottom fighter: whole body working to escape
        for part in ("core", "lower_back", "right_arm", "left_arm"):
            body_part = bottom.state.body.get(part)
            if body_part:
                body_part.fatigue = min(1.0, body_part.fatigue + 0.004)

        # Cardio drain for both
        top.state.cardio_current    = max(0.0, top.state.cardio_current    - 0.003)
        bottom.state.cardio_current = max(0.0, bottom.state.cardio_current - 0.004)
