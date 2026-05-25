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


# HAJ-74 — golden-score scaling for the ne-waza stalemate matte threshold.
# Spec: "STALEMATE_DURATION threshold scaled up 20-30% in GS." Mid of band.
GOLDEN_SCORE_STALEMATE_SCALE: float = 1.25


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
    # Part 4.2.1 — execution quality at kake time. Gates IPPON/WAZA_ARI/
    # NO_SCORE alongside landing position. Default 1.0 preserves legacy
    # caller behaviour for tests that don't wire execution_quality.
    execution_quality: float = 1.0


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
    # HAJ-127 — out-of-bounds flags + in-flight grace.
    # The viewer / log surface these per fighter; should_call_matte uses
    # any_throw_in_flight to skip the OOB check while a throw is mid-flight,
    # so a throw that started inside but lands outside resolves first.
    fighter_a_oob: bool = False
    fighter_b_oob: bool = False
    any_throw_in_flight: bool = False
    # HAJ-142 — named mat regions (CENTER / WORKING / WARNING / OUT_OF_BOUNDS).
    # Computed once per tick from each fighter's CoM. Tests, viewer pill,
    # and prose narrator all read this for region-aware behavior /
    # narration. Optional to keep legacy unit tests that hand-construct
    # MatchState compiling.
    fighter_a_region: Optional[str] = None
    fighter_b_region: Optional[str] = None
    # HAJ-74 — golden-score flag. The match is past regulation, sudden
    # death is live. Referee uses this to scale the ne-waza stalemate
    # matte threshold up: real refs let golden-score ground exchanges
    # cook a little longer before resetting, since a reset wastes the
    # only time-pressured commitment in the match.
    golden_score: bool = False


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
        mat_edge_strictness: float = 0.5,
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

        # HAJ-156 — mat_edge_strictness: how quickly the ref calls
        # non-combativity / push-out shido on a fighter who's been
        # driven to (or backed themselves into) the edge zone.
        # High = strict (8 ticks); Low = generous (15 ticks).
        self.mat_edge_strictness = mat_edge_strictness

        # --- Internal state ---
        self._cumulative_passive_ticks: dict[str, int] = {}
        self._last_attack_tick: dict[str, int] = {}

        # Matte timing constants (modulated by personality)
        # Base values; personality scales them
        self._STUFFED_MATTE_TICKS     = int(8  - stuffed_throw_tolerance * 6)  # 2–8 ticks
        self._NEWAZA_MATTE_TICKS      = int(30 + newaza_patience * 30)      # 30–60 ticks
        self._PASSIVITY_SHIDO_TICKS   = int(120 - grip_initiative_strictness * 60)  # 60–120 ticks
        # HAJ-156 — push-out shido threshold in ticks. Strict ref
        # (mat_edge_strictness=1.0) shidos at 8 ticks; generous ref
        # (mat_edge_strictness=0.0) at 15.
        self._PUSH_OUT_SHIDO_TICKS    = int(15 - mat_edge_strictness * 7)

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

        # HAJ-127 — out-of-bounds. Real judo: stepping outside is an
        # immediate Matte. In-flight grace mirrors HAJ-43: throws that
        # started inside resolve normally even if they land outside;
        # OOB then fires on the post-resolution tick if the landing
        # position is still outside.
        if not state.any_throw_in_flight:
            if state.fighter_a_oob or state.fighter_b_oob:
                return MatteReason.OUT_OF_BOUNDS

        # Ne-waza: check if we've been on the ground too long
        if state.ne_waza_active:
            # If osaekomi is running, the clock is live — don't interrupt
            if state.osaekomi_holder_id is not None:
                return None
            # Otherwise count against newaza patience window. HAJ-74 — in
            # golden score, scale the threshold up 25% so referees give the
            # only score-deciding ground exchange more rope before resetting.
            threshold = self._NEWAZA_MATTE_TICKS
            if state.golden_score:
                threshold = int(round(threshold * GOLDEN_SCORE_STALEMATE_SCALE))
            if state.stalemate_ticks >= threshold:
                return MatteReason.STALEMATE

        # After a stuffed throw: check stuffed_throw_tolerance window.
        #
        # HAJ-222 — defer matte while any throw resolution is still
        # in flight. Pre-fix the stuffed_throw_tick from a prior
        # exchange could fire matte on the same tick as a fresh
        # commit's reach-kuzushi / kuzushi sub-events, declaring the
        # in-progress throw "stuffed" before resolution had a chance
        # to play out. The OOB matte branch already guards on
        # `any_throw_in_flight`; mirror that here so the stuffed
        # matte waits one more tick if a throw is mid-resolution.
        if state.stuffed_throw_tick > 0:
            ticks_since_stuff = current_tick - state.stuffed_throw_tick
            if (not state.ne_waza_active
                    and not state.any_throw_in_flight
                    and ticks_since_stuff >= self._STUFFED_MATTE_TICKS):
                return MatteReason.STUFFED_THROW_TIMEOUT

        # No standing-stalemate Matte. Real judo doesn't reset a slow grip
        # exchange — it punishes inactivity with a shido for passivity
        # (handled by update_passivity → ShidoCall). The only standing event
        # that triggers Matte is out-of-bounds, which is enforced elsewhere.
        return None

    # -----------------------------------------------------------------------
    # SCORE THROW
    # Called after a throw lands. Returns a ScoreResult based on physics +
    # personality. The match applies the score; the referee just makes the call.
    # -----------------------------------------------------------------------
    def score_throw(self, landing: ThrowLanding, tick: int) -> ScoreResult:
        """Determine IPPON / WAZA_ARI / NO_SCORE based on landing quality,
        execution quality (Part 4.2.1), and referee personality.

        Called after resolve_throw returned IPPON or WAZA_ARI on raw net.
        The referee's job:
          - Confirm IPPON if landing profile is clean AND eq ≥ IPPON_MIN_EQ.
          - Else award WAZA_ARI if eq ≥ WAZA_ARI_MIN_EQ.
          - Else NO_SCORE: tori hit the net-score threshold on raw power but
            the execution wasn't clean enough — uke recovers.
        """
        from execution_quality import IPPON_MIN_EQ, WAZA_ARI_MIN_EQ

        net  = landing.net_score
        wq   = landing.window_quality
        ctrl = landing.control_maintained
        eq   = landing.execution_quality

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

        # Part 4.2.1 — execution quality gates the award level.
        if eq < WAZA_ARI_MIN_EQ:
            award = "NO_SCORE"
        elif (eq >= IPPON_MIN_EQ
              and effective_net >= ippon_net_threshold
              and clean_profile and ctrl):
            award = "IPPON"
        else:
            award = "WAZA_ARI"

        # Technique quality for composure effects: 0 at waza-ari floor, 1 at net=6.5.
        # Multiplied by eq so a low-quality waza-ari drops the defender's composure
        # less than a clean one.
        raw_quality = min(1.0, max(0.0, (net - 1.5) / 5.0)) * eq

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
    # HAJ-221 — Hajime / Matte events carry a viewer-facing banner block
    # so the renderer can gate banner display: each banner stays on screen
    # for `banner_duration_ticks`, and the engine guarantees a Matte banner
    # always clears before a follow-up Hajime banner runs (the
    # `MATTE_TO_HAJIME_PAUSE_TICKS` window in match.py is what enforces the
    # gap on the engine side; viewers can read these fields directly).
    BANNER_DURATION_TICKS: int = 2

    def announce_hajime(self, tick: int = 0) -> Event:
        return Event(
            tick=tick,
            event_type="HAJIME_CALLED",
            description=f"[ref: {self.name}] Hajime!",
            data={
                "banner":                "hajime",
                "banner_duration_ticks": self.BANNER_DURATION_TICKS,
                "banner_blocking":       True,
            },
        )

    def announce_matte(self, reason: MatteReason, tick: int = 0) -> Event:
        reason_text = {
            MatteReason.STALEMATE:             "stalemate",
            MatteReason.OUT_OF_BOUNDS:         "out of bounds",
            MatteReason.STUFFED_THROW_TIMEOUT: "stuffed throw — reset",
            MatteReason.INJURY:                "injury",
            MatteReason.OSAEKOMI_DECISION:     "osaekomi decision",
            MatteReason.POST_SCORE_FOLLOW_UP_END: "post-score reset",
        }.get(reason, reason.name)
        return Event(
            tick=tick,
            event_type="MATTE_CALLED",
            description=f"[ref: {self.name}] Matte! ({reason_text})",
            data={
                "reason":                reason.name,
                "banner":                "matte",
                "banner_duration_ticks": self.BANNER_DURATION_TICKS,
                "banner_blocking":       True,
            },
        )

    def announce_score(
        self,
        outcome: str,
        scorer_id: str,
        tick: int = 0,
        count: Optional[int] = None,
        source: str = "throw",
        technique: Optional[str] = None,
        detail: Optional[str] = None,
        execution_quality: Optional[float] = None,
        quality_band: Optional[str] = None,
    ) -> Event:
        """HAJ-45 — single unified scoring event covering both throw and pin
        sources. Replaces the prior `[score]` + `[ref] Waza-ari!` two-line
        pattern and the matching pin asymmetry."""
        if outcome == "IPPON":
            head = f"[ref: {self.name}] Ippon! {scorer_id} wins"
            event_type = "IPPON_AWARDED"
        else:  # WAZA_ARI
            head = (f"[ref: {self.name}] Waza-ari! {scorer_id} "
                    f"({count}/2)")
            event_type = "WAZA_ARI_AWARDED"

        if source == "pin":
            tail = f" by pin ({detail})." if detail else " by pin."
        else:  # throw
            parts = [p for p in (technique, detail) if p]
            tail = f" — {', '.join(parts)}." if parts else "."

        data: dict = {"outcome": outcome, "scorer": scorer_id, "source": source}
        if count is not None:
            data["count"] = count
        if technique is not None:
            data["technique"] = technique
        if execution_quality is not None:
            data["execution_quality"] = execution_quality
        if quality_band is not None:
            data["quality_band"] = quality_band

        return Event(
            tick=tick,
            event_type=event_type,
            description=head + tail,
            data=data,
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
