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
    from ne_waza_catalog import NeWazaCatalog


# ---------------------------------------------------------------------------
# NE-WAZA STATE MACHINE — HAJ-185
# The ground game has three coarse states with different rules and different
# scoring paths. They are MUTUALLY EXCLUSIVE: a submission attempt is not an
# osaekomi position, and the engine must not run the osaekomi clock during a
# submission.
#
#   OSAEKOMI            — top fighter has bottom held in a recognized
#                         osaekomi position (kesa, yoko-shiho, kami-shiho,
#                         tate-shiho, ura, kata). Osaekomi clock runs.
#                         Resolves to waza-ari at 10s, ippon at 20s, or to
#                         TRANSITIONAL on escape / boundary / reverse.
#   SUBMISSION_ATTEMPT  — top fighter applying a joint lock or strangle.
#                         No osaekomi clock. Binary resolution: tap or
#                         escape (or referee-called matte after stalemate).
#   TRANSITIONAL        — neither pin nor submission active: turtle defense,
#                         half-guard scramble, recovery, etc. No clock.
#                         Resolves to one of the other two states or back
#                         to tachiwaza.
#
# Boundary cases (e.g. a kuzure-kami-shiho-gatame setup escalated into a
# juji-gatame) are modeled as TRANSITIONS between states, not as a single
# conflated state. When the top fighter abandons a pin to attempt a sub the
# osaekomi is broken (per IJF rules: pause is rare, cancel is the default).
# ---------------------------------------------------------------------------
class NeWazaState(Enum):
    """Coarse ne-waza phase. Mutually exclusive."""
    TRANSITIONAL       = auto()
    OSAEKOMI           = auto()
    SUBMISSION_ATTEMPT = auto()


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
    """Pin clock. 10 ticks = WAZA_ARI; 20 ticks = IPPON (IJF rules: 10s/20s).

    HAJ-220 — `technique_id` records which ne-waza catalog entry the
    engine timed when Stage 2 committed to a pin. Pre-HAJ-220 pin
    bookkeeping tracked time at the broad-position level (e.g. "pin
    accumulating in SIDE_CONTROL"); the catalog substrate names the
    specific Kodokan variant (hon_kesa_gatame, kuzure_kami_shiho_gatame,
    etc.). Legacy callers that don't supply a technique_id keep the
    None default and the field is purely informational.
    """

    WAZA_ARI_TICKS: int = 10
    IPPON_TICKS:    int = 20

    def __init__(self) -> None:
        self.holder_id:    Optional[str]      = None
        self.position:     Optional[Position] = None
        self.ticks_held:   int = 0
        self.is_running:   bool = False
        # HAJ-220 — set when Stage 2 commits to a pin technique. None on
        # the legacy non-catalog path.
        self.technique_id: Optional[str] = None

    def start(
        self,
        holder_id: str,
        position: Position,
        technique_id: Optional[str] = None,
    ) -> None:
        """Start or restart the osaekomi clock.

        HAJ-220 — `technique_id` is the catalog entry the engine is now
        timing. Defaults to None for the legacy path.
        """
        self.holder_id    = holder_id
        self.position     = position
        self.ticks_held   = 0
        self.is_running   = True
        self.technique_id = technique_id

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
        self.is_running   = False
        self.holder_id    = None
        self.ticks_held   = 0
        self.technique_id = None

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
    #
    # HAJ-129 — escape rates were too generous. Pre-fix, BASE=0.08 + up to
    # +0.25 skill bonus produced an escape probability of ~0.30-0.40 per
    # tick for an elite from open guard, so a typical bottom fighter was
    # back to standing within 2-4 ticks. Real judo: escapes from dominant
    # positions are rare; most ne-waza resolves to pin/sub or to ref-called
    # matte after a stalemate window. Post-fix base 0.025 + 0.008/skill →
    # roughly 0.10 escape prob for an elite, 0.04 for a median fighter,
    # which mostly times out into matte rather than into a re-engagement.
    #
    # HAJ-231 — the per-tick rates above are calibrated for a *settled*
    # ground position. Pre-fix, _roll_escape ran from the very first ground
    # tick, so a fighter could pop straight back to standing on the tick
    # they hit the mat (triage 2026-06-04, Cluster 4.1: GUARD_TOP at t012 →
    # standing at t013). MIN_GROUND_TICKS_BEFORE_ESCAPE is a settle gate:
    # no escape roll fires until the dyad has been on the ground for more
    # than this many ticks, so an escape is never resolved on the entry
    # tick and ground exchanges last a believable number of ticks. The gate
    # lives at the tick_resolve call sites (not inside _roll_escape) so the
    # roll itself stays a pure per-tick probability that unit tests can
    # sample directly.
    BASE_ESCAPE_PROB:        float = 0.025  # per-tick baseline escape probability
    SKILL_ESCAPE_BONUS:      float = 0.008  # bonus per point of ne_waza_skill
    CARDIO_ESCAPE_MULT:      float = 0.6    # escape prob scales with cardio
    MIN_GROUND_TICKS_BEFORE_ESCAPE: int = 3  # settle window; no escape until past it
    CHOKE_BASE_TIGHTEN_PROB: float = 0.7    # per-tick chance choke advances
    ARMBAR_BASE_EXTEND_PROB: float = 0.65
    TECHNIQUE_ATTEMPT_PROB:  float = 0.25   # chance top fighter initiates a technique

    def __init__(self) -> None:
        self.active_technique: Optional[ActiveTechnique] = None
        # HAJ-220 — catalog-aware ground consumption state. None when no
        # ne-waza catalog has been supplied, in which case tick_resolve
        # falls back to the legacy (Phase 2 Session 2) hardcoded
        # choke/armbar chain. Set via set_catalog() from Match.__init__.
        self._ne_waza_catalog: Optional["NeWazaCatalog"] = None
        # Imported lazily inside set_catalog so unit tests of the legacy
        # path don't drag the consumption module in.
        self._connection_graph = None
        self._last_ground_position: Optional[Position] = None
        self._dominant_position_id: Optional[str] = None
        self._submission_attempt = None
        # HAJ-231 — ticks the dyad has spent on the ground since entry.
        # Incremented once per tick_resolve; gates the escape roll behind
        # MIN_GROUND_TICKS_BEFORE_ESCAPE. Reset on ground entry and reset().
        self._ground_ticks: int = 0
        # Pending log events from the most recent commit_pin /
        # commit_submission decision. tick_resolve drains and emits them
        # so the caller's events list stays the single emission point.
        self._pending_catalog_events: list[Event] = []

    # -----------------------------------------------------------------------
    # HAJ-220 — CATALOG WIRING
    # -----------------------------------------------------------------------
    def set_catalog(self, catalog: Optional["NeWazaCatalog"]) -> None:
        """Hand the resolver a NeWazaCatalog. None puts the resolver in
        legacy mode (Phase 2 Session 2 hardcoded chains)."""
        self._ne_waza_catalog = catalog
        if catalog is not None:
            from ne_waza_consumption import GroundConnectionGraph
            self._connection_graph = GroundConnectionGraph()

    def on_ground_entry(self, position: Position) -> None:
        """Called by Match when sub_loop_state transitions to NE_WAZA.
        Initializes the baseline ConnectionEdge set for the entered
        position so Stage 1 has something to filter against on the very
        first ne-waza tick. No-op in legacy mode.

        The settle counter is reset here unconditionally (before the
        legacy-mode early return) so the HAJ-231 escape gate restarts on
        every fresh ground entry in both the legacy and catalog paths."""
        self._ground_ticks = 0
        if self._ne_waza_catalog is None:
            return
        from ne_waza_consumption import baseline_graph_for
        self._connection_graph = baseline_graph_for(position)
        self._last_ground_position = position
        self._dominant_position_id = None
        self._submission_attempt = None
        self._pending_catalog_events = []

    # -----------------------------------------------------------------------
    # STATE MACHINE — HAJ-185
    # The current coarse state is derived from osaekomi.active and
    # active_technique. We keep the derivation, not a separate explicit
    # field, so the two can never desync. Callers (match.py, tests) read
    # `state(osaekomi)` to know which phase the ground game is in.
    # -----------------------------------------------------------------------
    def state(self, osaekomi: "OsaekomiClock") -> NeWazaState:
        """Return the current coarse ne-waza phase.

        Submission attempts win over pins because once a sub starts the
        osaekomi has already been broken (by tick_resolve, before the
        submission was initiated). If both ever appear active simultaneously
        that is a state-machine violation — see HAJ-185.
        """
        if self.active_technique is not None:
            return NeWazaState.SUBMISSION_ATTEMPT
        if osaekomi.active:
            return NeWazaState.OSAEKOMI
        return NeWazaState.TRANSITIONAL

    def reset(self, osaekomi: "OsaekomiClock") -> None:
        """Clear all ne-waza state. Called by match.py when ne-waza ends
        (escape, score, matte) so the next ground entry starts clean."""
        self.active_technique = None
        if osaekomi.active:
            osaekomi.break_pin()
        # HAJ-220 — also clear catalog-aware state. on_ground_entry seeds
        # a fresh ConnectionGraph on the next ne-waza entry.
        self._submission_attempt = None
        self._dominant_position_id = None
        self._last_ground_position = None
        self._pending_catalog_events = []
        self._ground_ticks = 0
        if self._connection_graph is not None:
            self._connection_graph.clear()

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

        HAJ-140 — pre-fix probabilities sat around ~0.10-0.20 each, so
        stuffed throws stayed standing ~75% of the time and the aggressor
        + defender both kept firing desperation commits in the next tick.
        Real judo: a stuffed throw is a near-instant transition to ne-waza
        because the aggressor is on a knee / off-balance and the defender
        capitalizes immediately. The defender is heavily favored — their
        posture is intact, they've absorbed the throw force, and the
        ground window is wide open. The aggressor sometimes commits too
        (sacrifice scramble for top position).

        Defender is the dominant dispatcher; aggressor is opportunistic.
        Both probabilities scale with ne_waza_skill so a no-ne-waza fighter
        still occasionally lets the dyad reset (and then the referee's
        STUFFED_MATTE_TICKS window catches it).
        """
        agg_nw  = aggressor.capability.ne_waza_skill / 10.0
        def_nw  = defender.capability.ne_waza_skill / 10.0
        agg_fat = 1.0 - (aggressor.state.cardio_current * 0.5 +
                         0.5 * (1.0 - aggressor.state.body["core"].fatigue))
        def_fat = 1.0 - (defender.state.cardio_current * 0.5 +
                         0.5 * (1.0 - defender.state.body["core"].fatigue))

        # Defender: heavy baseline (0.65) + skill bonus up to +0.30, lightly
        # modulated by fatigue. A median-skill, average-fatigued defender
        # commits ~0.85 of the time; an elite ne-waza specialist nearly
        # always commits.
        def_commit_prob = (
            0.65 + 0.30 * def_nw - 0.15 * def_fat
        )
        # Aggressor: still sometimes commits (sacrifice scramble for top
        # position). Modest baseline (0.30) + skill bonus, scaled by
        # window quality so a clean stuff (worse aggressor positioning)
        # means less follow-through.
        agg_commit_prob = (
            0.30 + 0.30 * agg_nw - 0.15 * agg_fat
        ) * max(0.5, window_quality)

        # Clamp to [0.0, 0.98] so a stuffed throw is never a guaranteed
        # transition — there's always a small chance both fighters reset
        # and the referee's STUFFED_MATTE_TICKS handles it.
        def_commit_prob = max(0.0, min(0.98, def_commit_prob))
        agg_commit_prob = max(0.0, min(0.98, agg_commit_prob))

        return (random.random() < def_commit_prob
                or random.random() < agg_commit_prob)

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
        """One tick of ne-waza. Returns events for anything notable.

        HAJ-220 — when a NeWazaCatalog has been set via set_catalog(),
        Stage 1 / Stage 2 commit logic supersedes the legacy hardcoded
        choke/armbar chain. Counter-action and escape rolls still run
        in both paths (those are tori-vs-uke physics, independent of
        which catalog entry is being timed).
        """
        events: list[Event] = []
        top_fighter, bottom_fighter = self._determine_top_bottom(position, fighters)

        if top_fighter is None:
            return events

        # HAJ-231 — count ground ticks for the escape settle gate. Done here,
        # before the catalog dispatch, so both resolution paths share one
        # counter (the catalog path reads self._ground_ticks too).
        self._ground_ticks += 1

        if self._ne_waza_catalog is not None:
            return self._tick_resolve_catalog(
                position, graph, fighters, osaekomi, current_tick,
                top_fighter, bottom_fighter,
            )

        # --- Counter-action available to bottom fighter each tick ---
        counter = self._pick_counter_action(bottom_fighter)
        counter_success = self._resolve_counter(counter, bottom_fighter, top_fighter)

        # --- Escape attempt (gated by the HAJ-231 settle window so a
        #     fighter can't pop back to standing on the entry tick) ---
        escaped = (
            self._ground_ticks > self.MIN_GROUND_TICKS_BEFORE_ESCAPE
            and self._roll_escape(bottom_fighter, top_fighter, position)
        )
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
        # HAJ-185 — when a submission is in progress we are in
        # NeWazaState.SUBMISSION_ATTEMPT. The osaekomi clock must be off;
        # any attempt to start a pin during a sub is rejected below.
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
                    # HAJ-185 — boundary case: top fighter abandons a pin
                    # to escalate into a submission (kuzure-kami-shiho into
                    # juji-gatame, kata-gatame into a strangle, etc.). The
                    # osaekomi is broken before the submission begins so
                    # the pin clock and the sub never co-run.
                    if osaekomi.active:
                        ticks_held = osaekomi.ticks_held
                        osaekomi.break_pin()
                        events.append(Event(
                            tick=current_tick,
                            event_type="OSAEKOMI_TO_SUBMISSION",
                            description=(
                                f"[ne-waza] {top_fighter.identity.name} "
                                f"abandons hold for {tech.name} attempt — "
                                f"osaekomi clock stops at {ticks_held}s."
                            ),
                            data={
                                "former_holder": top_fighter.identity.name,
                                "technique": tech.name,
                                "ticks_held": ticks_held,
                            },
                        ))
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
                # Start a pin if none active. (Pin start is gated on
                # active_technique=None by the surrounding else branch, so
                # NeWazaState.SUBMISSION_ATTEMPT cannot transition into
                # OSAEKOMI accidentally — a sub must resolve first.)
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
    # HAJ-220 — CATALOG-AWARE TICK
    # Parallel to tick_resolve; runs when set_catalog() supplied a
    # NeWazaCatalog. Replaces the hardcoded choke/armbar chain with
    # Stage 1 / Stage 2 commit logic against the catalog. Counter-action
    # and escape rolls still run (those are tori-vs-uke physics,
    # independent of which catalog entry is being timed). The legacy
    # path stays in place for tests that don't supply a catalog.
    # -----------------------------------------------------------------------
    def _tick_resolve_catalog(
        self,
        position: Position,
        graph: "GripGraph",
        fighters: tuple["Judoka", "Judoka"],
        osaekomi: OsaekomiClock,
        current_tick: int,
        top_fighter: "Judoka",
        bottom_fighter: "Judoka",
    ) -> list[Event]:
        from ne_waza_consumption import (
            baseline_graph_for, ne_waza_stage1_available_techniques,
            recognize_dominant_position, stage2_select_commit,
            pin_still_satisfied, submission_tick,
            SubmissionAttempt,
        )
        from ne_waza_catalog import ScoreMechanism

        events: list[Event] = []

        # If the engine position changed since the last tick (e.g. SCRAMBLE
        # → SIDE_CONTROL after a stuffed throw), re-seed the connection
        # baseline so Stage 1 has the right substrate.
        if position != self._last_ground_position:
            self._connection_graph = baseline_graph_for(position)
            self._last_ground_position = position
            self._dominant_position_id = None

        catalog = self._ne_waza_catalog
        # Defensive: set_catalog should always be paired with a graph,
        # but if a caller skipped on_ground_entry we seed one here.
        if self._connection_graph is None:
            self._connection_graph = baseline_graph_for(position)

        # --- Counter-action available to bottom fighter each tick ---
        counter = self._pick_counter_action(bottom_fighter)
        counter_success = self._resolve_counter(
            counter, bottom_fighter, top_fighter,
        )

        # --- Escape attempt (gated by the HAJ-231 settle window so a
        #     fighter can't pop back to standing on the entry tick) ---
        escaped = (
            self._ground_ticks > self.MIN_GROUND_TICKS_BEFORE_ESCAPE
            and self._roll_escape(bottom_fighter, top_fighter, position)
        )
        if escaped:
            if osaekomi.active:
                ticks_held = osaekomi.ticks_held
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
            self._submission_attempt = None
            self.active_technique = None
            return events

        if counter_success:
            events.append(Event(
                tick=current_tick,
                event_type="COUNTER_ACTION",
                description=(
                    f"[ne-waza] {bottom_fighter.identity.name} "
                    f"{counter.name.lower().replace('_', '-')} — partial success."
                ),
            ))

        # --- Dominant-position recognition. Fires every tick so a
        # recognized position can drop back to None once the substrate
        # tuning loop removes a required ConnectionEdge.
        self._dominant_position_id = recognize_dominant_position(
            self._connection_graph, catalog.positions, position,
        )

        # --- Submission attempt in progress? Run the tap-check loop. ---
        if self._submission_attempt is not None:
            outcome = submission_tick(
                self._submission_attempt, top_fighter, bottom_fighter,
                random,
            )
            if outcome == "tap":
                tid = self._submission_attempt.technique_id
                events.append(Event(
                    tick=current_tick,
                    event_type="SUBMISSION_VICTORY",
                    description=(
                        f"[sub] uke tapped — ippon by {tid}"
                    ),
                    data={
                        "winner":       top_fighter.identity.name,
                        "loser":        bottom_fighter.identity.name,
                        "technique_id": tid,
                        # Legacy compatibility for match.py listeners that
                        # still read "technique" off the event payload.
                        "technique":    tid,
                    },
                ))
                self._submission_attempt = None
                self._apply_ne_waza_fatigue(top_fighter, bottom_fighter)
                return events
            if outcome == "release":
                tid = self._submission_attempt.technique_id
                events.append(Event(
                    tick=current_tick,
                    event_type="SUBMISSION_RELEASED",
                    description=(
                        f"[sub] {tid} released — Matte"
                    ),
                    data={"technique_id": tid},
                ))
                self._submission_attempt = None
                self._apply_ne_waza_fatigue(top_fighter, bottom_fighter)
                return events
            # "continue" — attempt persists to next tick.
            self._apply_ne_waza_fatigue(top_fighter, bottom_fighter)
            return events

        # --- Pin in progress? Check that Stage 1 requirements still hold. ---
        if osaekomi.active and osaekomi.technique_id is not None:
            pin_def = catalog.techniques.get(osaekomi.technique_id)
            if pin_def is not None and not pin_still_satisfied(
                self._connection_graph, pin_def,
            ):
                tid = osaekomi.technique_id
                ticks_held = osaekomi.ticks_held
                osaekomi.break_pin()
                events.append(Event(
                    tick=current_tick,
                    event_type="OSAEKOMI_BROKEN",
                    description=(
                        f"[pin] {tid} broken at {ticks_held}s"
                    ),
                    data={"technique_id": tid, "ticks_held": ticks_held},
                ))
                self._apply_ne_waza_fatigue(top_fighter, bottom_fighter)
                return events

        # --- No active commit — run Stage 1 / Stage 2 selection. ---
        if not osaekomi.active and self._submission_attempt is None:
            available = ne_waza_stage1_available_techniques(
                self._connection_graph, position, top_fighter, bottom_fighter,
                catalog.techniques, catalog.positions,
                dominant_position_id=self._dominant_position_id,
            )
            chosen_tid = stage2_select_commit(
                available, self._connection_graph, catalog.techniques,
            )
            if chosen_tid is not None:
                chosen_def = catalog.techniques[chosen_tid]
                if chosen_def.score_mechanism is ScoreMechanism.PIN_TIME_ACCUMULATION:
                    osaekomi.start(
                        top_fighter.identity.name,
                        position,
                        technique_id=chosen_tid,
                    )
                    events.append(Event(
                        tick=current_tick,
                        event_type="OSAEKOMI_BEGIN",
                        description=(
                            f"[pin] {chosen_tid} committed"
                        ),
                        data={
                            "technique_id": chosen_tid,
                            "holder":       top_fighter.identity.name,
                        },
                    ))
                else:
                    self._submission_attempt = SubmissionAttempt(
                        technique_id=chosen_tid,
                        aggressor_id=top_fighter.identity.name,
                        defender_id=bottom_fighter.identity.name,
                    )
                    events.append(Event(
                        tick=current_tick,
                        event_type="SUBMISSION_COMMITTED",
                        description=(
                            f"[sub] {chosen_tid} committed"
                        ),
                        data={
                            "technique_id": chosen_tid,
                            "aggressor":    top_fighter.identity.name,
                            "defender":     bottom_fighter.identity.name,
                        },
                    ))

        # --- Pin accumulation log line — emit at 5-second intervals so
        # the visible stream gets a recognizable scoring-clock heartbeat
        # without spamming every tick.
        if (osaekomi.active and osaekomi.technique_id is not None
                and osaekomi.ticks_held > 0
                and osaekomi.ticks_held % 5 == 0
                and osaekomi.ticks_held < OsaekomiClock.IPPON_TICKS):
            events.append(Event(
                tick=current_tick,
                event_type="OSAEKOMI_ACCUMULATING",
                description=(
                    f"[score] osaekomi accumulating "
                    f"({osaekomi.technique_id}, {osaekomi.ticks_held}s)"
                ),
                data={
                    "technique_id": osaekomi.technique_id,
                    "ticks_held":   osaekomi.ticks_held,
                },
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

        # Position difficulty multiplies the escape probability, so a LOWER
        # value means a harder escape. The axis is top-fighter dominance:
        # the more control the top fighter has, the lower the multiplier.
        # Back control is hardest to escape; side control is the 1.0
        # reference. HAJ-231 — guard was previously 1.5, which *raised*
        # escape odds and made guard-top easier to escape than side control
        # (the opposite of intent). The top fighter inside guard is the
        # least dominant top position, so guard is pinned at the side-control
        # reference (1.0): no easier to escape than side control, never the
        # cheapest escape on the board.
        position_difficulty = {
            Position.SIDE_CONTROL: 1.0,
            Position.MOUNT:        0.7,
            Position.BACK_CONTROL: 0.5,
            Position.GUARD_TOP:    1.0,
            Position.GUARD_BOTTOM: 1.0,
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
