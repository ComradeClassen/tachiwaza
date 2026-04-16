# referee.py
# The Referee class: personality variables driving Matte timing and scoring.
#
# A referee is not neutral — their personality shapes which landings get IPPON,
# how long they let ne-waza breathe, and how quickly they reset stalemates.
# Phase 2 ships with two hand-built personalities: Suzuki-sensei (Japanese-style)
# and Petrov (European / sambo-influenced). Phase 3 calibration tunes the defaults.
#
# The Referee does NOT own the OsaekomiClock — that lives on Match (it's match state).
# The Referee reads the osaekomi ticks from MatchState to make scoring decisions.

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional

from enums import (
    LandingProfile, MatteReason, Position, SubLoopState,
)
from grip_graph import Event


# ---------------------------------------------------------------------------
# SCORE RESULT
# Returned by referee.score_throw() — tells the match what happened.
# ---------------------------------------------------------------------------
@dataclass
class ScoreResult:
    """The referee's scoring verdict on a throw landing."""
    award: str                  # "IPPON", "WAZA_ARI", or "NO_SCORE"
    technique_quality: float    # 0–1; affects composure drop on defender
    landing_angle: float        # degrees — 0 = flat back (ippon ideal)
    control_maintained: bool    # did tori stay on their feet and in control?


# ---------------------------------------------------------------------------
# THROW LANDING
# Passed to referee.score_throw(). Computed by match._resolve_throw().
# ---------------------------------------------------------------------------
@dataclass
class ThrowLanding:
    """Physics description of how a throw resolved."""
    landing_profile: LandingProfile
    net_score: float          # attack_strength − defender_resistance + noise
    window_quality: float     # 0 = forced attempt; 1 = perfect kuzushi window
    control_maintained: bool


# ---------------------------------------------------------------------------
# SHIDO CALL
# ---------------------------------------------------------------------------
@dataclass
class ShidoCall:
    fighter_id: str
    reason: str
    tick: int


# ---------------------------------------------------------------------------
# MATCH STATE SNAPSHOT
# A read-only view of the match passed to the referee each tick.
# The Referee must not modify any match state — it only reads and returns verdicts.
# ---------------------------------------------------------------------------
@dataclass
class MatchState:
    """Snapshot of match state for referee evaluation."""
    tick: int
    position: Position
    sub_loop_state: SubLoopState
    fighter_a_id: str
    fighter_b_id: str
    fighter_a_score: dict
    fighter_b_score: dict
    fighter_a_last_attack_tick: int
    fighter_b_last_attack_tick: int
    fighter_a_shidos: int
    fighter_b_shidos: int
    ne_waza_active: bool
    osaekomi_holder_id: Optional[str]
    osaekomi_ticks: int
    stalemate_ticks: int         # how long the sub-loop has been in stalemate
    stuffed_throw_tick: int      # tick when last stuffed throw occurred (0 = none)


# ===========================================================================
# REFEREE
# ===========================================================================
class Referee:
    """Models a single referee with personality variables driving all decisions.

    All five personality values are 0.0–1.0 floats.
    A value of 0.5 represents the IJF standard default.
    Higher values mean MORE of what the label says.
    """

    def __init__(
        self,
        name: str,
        nationality: str,
        newaza_patience: float = 0.5,
        stuffed_throw_tolerance: float = 0.5,
        match_energy_read: float = 0.5,
        grip_initiative_strictness: float = 0.5,
        ippon_strictness: float = 0.5,
        waza_ari_strictness: float = 0.5,
    ) -> None:
        self.name = name
        self.nationality = nationality

        # --- Personality parameters ---
        # newaza_patience: how long they let ground work breathe before calling Matte
        # High = let it cook; Low = quick reset after stuffed throws
        self.newaza_patience = newaza_patience

        # stuffed_throw_tolerance: how long after a stuffed throw they wait before Matte
        # High = gives the scramble time to develop; Low = resets fast
        self.stuffed_throw_tolerance = stuffed_throw_tolerance

        # match_energy_read: sensitivity to stalemate; calls Matte faster when low
        self.match_energy_read = match_energy_read

        # grip_initiative_strictness: how quickly they warn for passivity
        # High = strict; Low = lets fighters take time in grip war
        self.grip_initiative_strictness = grip_initiative_strictness

        # ippon_strictness: how clean a landing needs to be for IPPON vs WAZA_ARI
        # High = very strict (IJF standard); Low = generous (sambo-influenced)
        self.ippon_strictness = ippon_strictness

        # waza_ari_strictness: how clean for WAZA_ARI vs NO_SCORE
        self.waza_ari_strictness = waza_ari_strictness

        # --- Internal state ---
        self._cumulative_passive_ticks: dict[str, int] = {}
        self._last_attack_tick: dict[str, int] = {}

        # Matte timing constants (modulated by personality)
        # Base values; personality scales them
        self._STALEMATE_MATTE_TICKS   = int(20 - match_energy_read * 10)    # 10–20 ticks
        self._STUFFED_MATTE_TICKS     = int(8  - stuffed_throw_tolerance * 6)  # 2–8 ticks
        self._NEWAZA_MATTE_TICKS      = int(30 + newaza_patience * 30)      # 30–60 ticks
        self._PASSIVITY_SHIDO_TICKS   = int(120 - grip_initiative_strictness * 60)  # 60–120 ticks

    # -----------------------------------------------------------------------
    # SHOULD CALL MATTE
    # Checked every tick. Returns a MatteReason if Matte should fire, else None.
    # -----------------------------------------------------------------------
    def should_call_matte(
        self,
        state: MatchState,
        current_tick: int,
    ) -> Optional[MatteReason]:
        """Decide whether to call Matte this tick. Returns reason or None."""

        # Ne-waza: check if we've been on the ground too long
        if state.ne_waza_active:
            # If osaekomi is running, the clock is live — don't interrupt
            if state.osaekomi_holder_id is not None:
                return None
            # Otherwise count against newaza patience window
            if state.stalemate_ticks >= self._NEWAZA_MATTE_TICKS:
                return MatteReason.STALEMATE

        # After a stuffed throw: check stuffed_throw_tolerance window
        if state.stuffed_throw_tick > 0:
            ticks_since_stuff = current_tick - state.stuffed_throw_tick
            if (not state.ne_waza_active
                    and ticks_since_stuff >= self._STUFFED_MATTE_TICKS):
                return MatteReason.STUFFED_THROW_TIMEOUT

        # Standing stalemate: sub-loop has been stuck too long
        if (state.sub_loop_state == SubLoopState.TUG_OF_WAR
                and state.stalemate_ticks >= self._STALEMATE_MATTE_TICKS):
            return MatteReason.STALEMATE

        return None

    # -----------------------------------------------------------------------
    # SCORE THROW
    # Called after a throw lands. Returns a ScoreResult based on physics +
    # personality. The match applies the score; the referee just makes the call.
    # -----------------------------------------------------------------------
    def score_throw(self, landing: ThrowLanding, tick: int) -> ScoreResult:
        """Determine IPPON or WAZA_ARI based on landing quality and personality.

        NOTE: Called only when the match engine has determined a throw scored
        (resolve_throw returned IPPON or WAZA_ARI). The referee decides the
        precise level — confirms IPPON or downgrades to WAZA_ARI — but never
        strips a scored throw to NO_SCORE. That gate lives in resolve_throw().
        """
        net  = landing.net_score
        wq   = landing.window_quality
        ctrl = landing.control_maintained

        # Landing profile: FORWARD_ROTATIONAL and HIGH_FORWARD_ROTATIONAL produce
        # the cleanest flat-back landings and are required for IPPON confirmation.
        clean_profile = landing.landing_profile in (
            LandingProfile.FORWARD_ROTATIONAL,
            LandingProfile.HIGH_FORWARD_ROTATIONAL,
            LandingProfile.REAR_ROTATIONAL,
        )

        # IPPON threshold in net-score units (same scale as resolve_throw uses).
        # ippon_strictness 0.5 = IJF standard (net ≥ 4.0)
        # ippon_strictness 1.0 = very strict  (net ≥ 4.75)
        # ippon_strictness 0.0 = generous      (net ≥ 3.25)
        ippon_net_threshold = 4.0 + (self.ippon_strictness - 0.5) * 1.5

        # Sacrifice throws harder to confirm as IPPON (uke can roll through)
        if landing.landing_profile == LandingProfile.SACRIFICE:
            ippon_net_threshold += 1.0

        # No control → can't be IPPON
        if not ctrl:
            ippon_net_threshold += 0.5

        # Perfect kuzushi window gives a small benefit of the doubt
        effective_net = net + wq * 0.5

        # Referee inconsistency noise in net-score units (~0.3 std dev)
        effective_net += random.gauss(0, 0.3)

        if effective_net >= ippon_net_threshold and clean_profile and ctrl:
            award = "IPPON"
        else:
            award = "WAZA_ARI"

        # Technique quality for composure effects: 0 at waza-ari floor, 1 at net=6.5
        raw_quality = min(1.0, max(0.0, (net - 1.5) / 5.0))

        return ScoreResult(
            award=award,
            technique_quality=raw_quality,
            landing_angle=90.0 * (1.0 - raw_quality),
            control_maintained=ctrl,
        )

    # -----------------------------------------------------------------------
    # PASSIVITY / SHIDO
    # -----------------------------------------------------------------------
    def update_passivity(
        self,
        fighter_id: str,
        was_active: bool,
        current_tick: int,
    ) -> Optional[ShidoCall]:
        """Track passive ticks and issue shido if threshold exceeded."""
        if was_active:
            self._cumulative_passive_ticks[fighter_id] = 0
            self._last_attack_tick[fighter_id] = current_tick
        else:
            self._cumulative_passive_ticks[fighter_id] = (
                self._cumulative_passive_ticks.get(fighter_id, 0) + 1
            )
            if self._cumulative_passive_ticks[fighter_id] >= self._PASSIVITY_SHIDO_TICKS:
                self._cumulative_passive_ticks[fighter_id] = 0
                return ShidoCall(fighter_id=fighter_id, reason="passivity", tick=current_tick)
        return None

    # -----------------------------------------------------------------------
    # ANNOUNCEMENTS
    # -----------------------------------------------------------------------
    def announce_hajime(self, tick: int = 0) -> Event:
        return Event(
            tick=tick,
            event_type="HAJIME_CALLED",
            description=f"[ref: {self.name}] Hajime!",
        )

    def announce_matte(self, reason: MatteReason, tick: int = 0) -> Event:
        reason_text = {
            MatteReason.SCORING:               "score awarded",
            MatteReason.STALEMATE:             "stalemate",
            MatteReason.OUT_OF_BOUNDS:         "out of bounds",
            MatteReason.PASSIVITY:             "passivity",
            MatteReason.STUFFED_THROW_TIMEOUT: "stuffed throw — reset",
            MatteReason.INJURY:                "injury",
            MatteReason.OSAEKOMI_DECISION:     "osaekomi decision",
        }.get(reason, reason.name)
        return Event(
            tick=tick,
            event_type="MATTE_CALLED",
            description=f"[ref: {self.name}] Matte! ({reason_text})",
            data={"reason": reason.name},
        )

    def announce_ippon(self, winner_id: str, tick: int = 0) -> Event:
        return Event(
            tick=tick,
            event_type="IPPON_AWARDED",
            description=f"[ref: {self.name}] Ippon! {winner_id} wins.",
        )

    def announce_waza_ari(self, scorer_id: str, count: int, tick: int = 0) -> Event:
        return Event(
            tick=tick,
            event_type="WAZA_ARI_AWARDED",
            description=f"[ref: {self.name}] Waza-ari! {scorer_id} ({count}/2).",
        )

    def announce_osaekomi(self, holder_id: str, tick: int = 0) -> Event:
        return Event(
            tick=tick,
            event_type="OSAEKOMI_BEGIN",
            description=f"[ref: {self.name}] Osaekomi! {holder_id} holding.",
        )

    def announce_toketa(self, tick: int = 0) -> Event:
        return Event(
            tick=tick,
            event_type="OSAEKOMI_BROKEN",
            description=f"[ref: {self.name}] Toketa!",
        )


# ===========================================================================
# PRE-BUILT REFEREE PERSONALITIES
# ===========================================================================

def build_suzuki() -> Referee:
    """Suzuki-sensei — Japanese-style referee.

    High newaza_patience: lets ground work breathe.
    Low stuffed_throw_tolerance: resets fast after stuffed throws.
    High ippon_strictness: wants the throw clean and controlled.
    Average grip_initiative_strictness: classical IJF standard.
    """
    return Referee(
        name="Suzuki-sensei",
        nationality="Japanese",
        newaza_patience=0.7,
        stuffed_throw_tolerance=0.3,
        match_energy_read=0.5,
        grip_initiative_strictness=0.5,
        ippon_strictness=0.8,
        waza_ari_strictness=0.5,
    )


def build_petrov() -> Referee:
    """Petrov — European / sambo-influenced referee.

    Moderate newaza_patience: lets things develop but not forever.
    High stuffed_throw_tolerance: gives the scramble real time.
    Low ippon_strictness: generous on landing angle and control.
    Low grip_initiative_strictness: tolerates defensive gripping.
    """
    return Referee(
        name="Petrov",
        nationality="Russian",
        newaza_patience=0.5,
        stuffed_throw_tolerance=0.7,
        match_energy_read=0.4,
        grip_initiative_strictness=0.3,
        ippon_strictness=0.5,
        waza_ari_strictness=0.4,
    )
