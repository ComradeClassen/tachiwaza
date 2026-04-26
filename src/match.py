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
import re
from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

from enums import (
    BodyArchetype, DominantSide, Position, StanceMatchup,
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
from skill_compression import (
    SubEvent, SUB_EVENT_LABELS, compression_n_for, sub_event_schedule,
)
from counter_windows import (
    CounterWindow, actual_counter_window, perceived_counter_window,
    has_counter_resources, select_counter_throw, counter_fire_probability,
    attacker_vulnerability_for,
)
from defensive_desperation import DefensivePressureTracker
from compromised_state import is_desperation_state
from execution_quality import (
    compute_execution_quality, commit_threshold_for, band_for,
    force_transfer_multiplier, narration_for,
)
from commit_motivation import (
    CommitMotivation, debug_tag_for as motivation_debug_tag,
    narration_for as motivation_narration_for,
)


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

# ---------------------------------------------------------------------------
# MAT COORDINATE CONVENTION (HAJ-124)
#
# Single source of truth for the spatial unit used throughout the simulator.
# Every consumer that interprets a coordinate, displacement, or distance —
# the OOB boundary check, the top-down viewer, future locomotion — should
# reference this declaration rather than re-deriving it from physics
# constants.
#
#   - body_state.com_position is in MAT-FRAME METERS, origin at mat center.
#   - Match-start positions: fighter_a at (-0.5, 0.0); fighter_b at (+0.5, 0.0).
#     One meter apart, centered on the origin.
#   - DISPLACEMENT_GAIN is in m/N·tick. force / mass × gain → meters of
#     CoM displacement per tick (after FRICTION_DAMPING).
#   - IJF reference geometry: contest area is 8 × 8 m; safety border is
#     ≥ 3 m wide on all sides; total mat is ≥ 14 × 14 m. Sim half-widths
#     should be derived from these numbers, not hard-coded.
#
# This convention is load-bearing for HAJ-125 (viewer) and HAJ-127 (OOB).
# ---------------------------------------------------------------------------
MAT_COORDINATE_UNIT: str = "meters"

# HAJ-128 — locomotion: per-step cardio cost. Stepping isn't free; over
# the course of a 4-minute match a pressure-fighter who steps every
# few ticks should accumulate measurable cardio drain.
STEP_CARDIO_COST: float = 0.0015

# HAJ-127 / HAJ-128 — out-of-bounds boundary, IJF reference half-width.
#
# 4.0 m matches the IJF 8 × 8 m contest area, centered on the mat origin.
# HAJ-128 added autonomous locomotion (PRESSURE / DEFENSIVE_EDGE / HOLD_CENTER
# styles emit STEP actions), so fighters can actually traverse the contest
# area now — OOB no longer needs the tighter 1.5 m stop-gap.
MAT_HALF_WIDTH: float = 4.0


def is_out_of_bounds(judoka: Judoka) -> bool:
    """HAJ-127 — True when the fighter's CoM is outside the contest area.

    Uses |x| > half_width OR |y| > half_width (a square boundary). The
    contest area is centered on the mat origin per HAJ-124.
    """
    x, y = judoka.state.body_state.com_position
    return abs(x) > MAT_HALF_WIDTH or abs(y) > MAT_HALF_WIDTH

# Part 3 force-model calibration stubs. Phase 3 telemetry will tune these.
JUDOKA_MASS_KG:           float = 80.0   # v0.1 uniform; Part 6 can pull from identity.
FRICTION_DAMPING:         float = 0.55   # fraction of velocity surviving a tick (planted feet)
DISPLACEMENT_GAIN:        float = 0.00006 # meters-per-Newton-tick on CoM (with DAMPING)
TRUNK_ANGLE_GAIN:         float = 0.00008 # radians per N·m of net torque (stubbed moment arm)
TRUNK_RESTORATION:        float = 0.15   # passive + active return-to-vertical each tick
FORCE_NOISE_PCT:          float = 0.10   # ±10% uniform on applied force magnitudes (3.8)
TRUNK_NOISE_PCT:          float = 0.05   # ±5% uniform on trunk angle updates (3.8)

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

# HAJ-48 — desperation state ENTER/EXIT lines only emit if the underlying
# state has persisted for at least this many ticks. Short-lived flicker
# (state on for one or two ticks around a single failed throw) produces
# no announcement and therefore no orphan EXIT either.
STATE_ANNOUNCE_MIN_TICKS: int = 3

# Background fatigue per tick
CARDIO_DRAIN_PER_TICK: float = 0.002
HAND_FATIGUE_PER_TICK: float = 0.0003

# HAJ-56 — posture-driven continuous stamina drain. Bent-over fighters burn
# cardio compensating muscularly for what the skeleton handles when upright.
# Triggers when forward lean exceeds body_state.UPRIGHT_LIMIT_RAD (the same
# 15° boundary that splits Posture.UPRIGHT from SLIGHTLY_BENT). Forward-only:
# back-lean is the evasion posture and shouldn't be taxed.
# Magnitude: 0.001/tick = ~0.24 cardio over a 4-min (240-tick) match — a
# meaningful surcharge on top of CARDIO_DRAIN_PER_TICK without dominating it.
POSTURE_BENT_CARDIO_DRAIN: float = 0.001

# Composure drops on scoring events
COMPOSURE_DROP_WAZA_ARI: float = 0.5
COMPOSURE_DROP_IPPON:    float = 2.0

# Throws that require hand/forearm as primary muscles (not leg-dominant)
GRIP_DOMINANT_THROWS: frozenset[ThrowID] = frozenset({
    ThrowID.SEOI_NAGE,
    ThrowID.TAI_OTOSHI,
})


# ---------------------------------------------------------------------------
# FAILURE-OUTCOME DISPLAY STRINGS
# Keep these keyed by the throw_templates.FailureOutcome enum but expressed
# as plain coach-stream prose. _format_failure_events consumes these; event
# data still carries the raw enum name for debug / downstream consumers.
# ---------------------------------------------------------------------------
def _failure_display_tables() -> tuple[dict, dict]:
    from throw_templates import FailureOutcome
    compromise = {
        FailureOutcome.TORI_COMPROMISED_FORWARD_LEAN:   "forward lean, out of posture",
        FailureOutcome.TORI_COMPROMISED_SINGLE_SUPPORT: "off-balance on one leg",
        FailureOutcome.TORI_STUCK_WITH_UKE_ON_BACK:     "stuck with uke loaded on back",
        FailureOutcome.TORI_BENT_FORWARD_LOADED:        "bent forward, loaded",
        FailureOutcome.TORI_ON_KNEE_UKE_STANDING:       "on one knee, uke standing",
        FailureOutcome.TORI_ON_BOTH_KNEES_UKE_STANDING: "on both knees, uke standing",
        FailureOutcome.TORI_SWEEP_BOUNCES_OFF:          "sweep bounces off",
        FailureOutcome.TACTICAL_DROP_RESET:             "tactical drop, clock reset",
        FailureOutcome.PARTIAL_THROW:                   "partial throw, no score",
        FailureOutcome.STANCE_RESET:                    "stance reset",
        FailureOutcome.UKE_VOLUNTARY_NEWAZA:            "uke pulls guard to ne-waza",
    }
    counters = {
        FailureOutcome.UCHI_MATA_SUKASHI:   "reads the uchi-mata and steps through — sukashi",
        FailureOutcome.OSOTO_GAESHI:        "catches the osoto and redirects — osoto-gaeshi",
        FailureOutcome.URA_NAGE:            "scoops under and counters — ura-nage",
        FailureOutcome.KAESHI_WAZA_GENERIC: "turns the attempt — kaeshi-waza",
    }
    return compromise, counters


_FAILURE_TAGS, _COUNTER_NARRATIONS = _failure_display_tables()


# ---------------------------------------------------------------------------
# LOG STREAM SEPARATION (HAJ-65)
# Two named streams share the same underlying tick events:
#   - "debug":  engineer-facing — tick numbers, physics variables, grip edge
#               transitions, execution_quality, failed_dimension, handles
#               (F#/G#/T#) from the debug inspector.
#   - "prose":  reader-facing — throw lines, referee calls, compromised-state
#               narration, score announcements. No tick prefix, no handles,
#               and debug-only numerics like `(eq=…)` are stripped from
#               descriptions.
# `_print_events` consults the active stream to decide what to emit.
# ---------------------------------------------------------------------------

VALID_STREAMS: frozenset[str] = frozenset({"debug", "prose", "both"})

# Event types that belong only to the debug stream — grip edge churn, raw
# physics beats, and skill-compression sub-events. The prose stream drops
# these entirely; debug and both keep them.
_DEBUG_ONLY_EVENT_TYPES: frozenset[str] = frozenset({
    "GRIP_ESTABLISH",
    "GRIP_STRIPPED",
    "GRIP_DEGRADE",
    "GRIP_BREAK",
    "GRIPS_RESET",
    "KUZUSHI_INDUCED",
    "THROW_ABORTED",
})

# Also debug-only: any event whose event_type begins with SUB_ (the skill-
# compression sub-events REACH_KUZUSHI / KUZUSHI_ACHIEVED / TSUKURI /
# KAKE_COMMIT). These describe mechanics, not narrative beats.
def _is_debug_only_event(event_type: str) -> bool:
    return event_type in _DEBUG_ONLY_EVENT_TYPES or event_type.startswith("SUB_")


# Strip numeric (eq=0.72) parentheticals — execution_quality is a debug
# value per HAJ-65. Handles both the bare form and the "(ref downgraded,
# eq=0.72)" composite from THROW_LANDING no-score lines.
_EQ_PAREN_RE = re.compile(r"\s*\([^()]*eq=\d+(?:\.\d+)?[^()]*\)")


def _render_prose(desc: str) -> str:
    """Rewrite a debug-ish description for the prose stream: remove the
    (eq=...) parentheticals that mix numeric debug into otherwise readable
    sentences. Tick prefix and debug handles are handled by the caller."""
    return _EQ_PAREN_RE.sub("", desc)


# ---------------------------------------------------------------------------
# SIDE-BY-SIDE LAYOUT (HAJ-65 extension)
# Two columns for stream="both": engineer tick-prefixed view on the left,
# prose-with-match-clock on the right, sharing one row per emitted event.
# The left column has a tNNN: prefix so readers can cross-reference against
# the prose clock (tick is seconds elapsed; clock is seconds remaining).
# Tests depend on tNNN: appearing at the start of each default-stream line,
# so the engineer side is always printed first.
# ---------------------------------------------------------------------------
SBS_LEFT_COL_WIDTH: int = 80       # engineer column width; overflow is truncated
SBS_SEPARATOR:      str = "  │  "  # vertical rule between the two columns


def _format_match_clock(ticks_remaining: int) -> str:
    """Render a countdown match clock as 'M:SS'. One tick = one second.

    Negative values (golden-score overtime, not yet wired) render with a
    leading '+'. Clamps to 0:00 floor at exactly zero.
    """
    if ticks_remaining < 0:
        m, s = divmod(-ticks_remaining, 60)
        return f"+{m}:{s:02d}"
    m, s = divmod(ticks_remaining, 60)
    return f"{m}:{s:02d}"


def _render_side_by_side(debug_line: str, prose_line: str) -> str:
    """Compose one side-by-side row. Left column is fixed-width (padded or
    truncated with '…'); right column flows freely. When the prose column
    is empty (debug-only event), the separator is suppressed and the row
    is just the padded engineer line — still aligned with prose-bearing
    rows above and below for a clean vertical scan.
    """
    if len(debug_line) > SBS_LEFT_COL_WIDTH:
        left = debug_line[:SBS_LEFT_COL_WIDTH - 1] + "…"
    else:
        left = debug_line.ljust(SBS_LEFT_COL_WIDTH)
    if not prose_line:
        return left.rstrip()
    return f"{left}{SBS_SEPARATOR}{prose_line}"


# ---------------------------------------------------------------------------
# THROW IN PROGRESS (Part 6.1 — multi-tick attempt state)
# One instance per attacker mid-attempt. Cleared when KAKE_COMMIT resolves or
# the attempt is aborted (stun, grip collapse, counter).
# ---------------------------------------------------------------------------
@dataclass
class _ThrowInProgress:
    attacker_name:  str
    defender_name:  str
    throw_id:       ThrowID
    start_tick:     int
    compression_n:  int
    schedule:       dict[int, list[SubEvent]]
    commit_actual:  float                          # signature match at commit time
    # Part 4.2.1 — execution quality at commit time. Counter-window fire
    # probability reads this for in-progress attempts; kake recomputes a
    # fresh eq from the updated signature match when resolving.
    commit_execution_quality: float = 0.0
    last_sub_event: Optional[SubEvent] = None      # most recent emitted — drives Part 6.2 window region

    def offset(self, current_tick: int) -> int:
        return current_tick - self.start_tick

    def is_last_tick(self, current_tick: int) -> bool:
        return self.offset(current_tick) >= self.compression_n - 1


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
    execution_quality: float = 1.0,
) -> tuple[str, float]:
    """Resolve one throw attempt.

    Returns:
        (outcome, net_score) where outcome is 'IPPON' | 'WAZA_ARI' | 'STUFFED' | 'FAILED'
        and net_score is the raw computed value.

    `execution_quality` ∈ [0, 1] (Part 4.2.1) modulates force transfer: the
    attack_strength is multiplied by force_transfer_multiplier(eq). A
    barely-committed throw (eq→0) still delivers force at the FLOOR level;
    a clean finish (eq=1) delivers 100%. The default 1.0 preserves legacy
    call-site behaviour for tests that don't wire eq.

    The formula:
        1. Throw effectiveness from attacker's side
        2. Stance matchup modifier
        3. Attacker body condition
        4. Execution-quality force scaling (Part 4.2.1 point 1)
        5. Defender resistance
        6. Gaussian noise
        7. Threshold comparison
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

    # Part 4.2.1 — execution quality scales force transfer (kake delivery).
    # Newton 3 preserved: the reaction forces on tori are computed in the
    # per-tick force model from the same delivered magnitudes, so scaling
    # the delivery also scales the reaction.
    attack_strength *= force_transfer_multiplier(execution_quality)

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
# RENDERER PROTOCOL (HAJ-125)
#
# A Renderer is a read-only observer attached to Match. The match calls
# update(...) once per tick after the post-tick housekeeping; the renderer
# reads state and draws — never mutates the match.
#
# Match itself depends only on this protocol, not on pygame or any other
# rendering tech. The pygame implementation lives in match_viewer.py and
# is loaded only when --viewer is passed; the test suite uses lightweight
# fakes that record calls without opening windows.
# ===========================================================================
@runtime_checkable
class Renderer(Protocol):
    """Hook for visual / inspection surfaces attached to a running Match.

    Two flavors:

    1. Push-style (default). Match owns the loop and calls update(...)
       once per tick. Used by passive observers like RecordingRenderer.

    2. Driver-style (HAJ-126). The renderer owns the wall-clock loop so
       it can implement pause / step / speed scrub. Match.run() detects
       this via drives_loop() and hands control to run_interactive(...).
       update(...) is still called from inside Match.step() so events
       can be buffered for the on-screen ticker."""

    def start(self) -> None:
        """Called once before the first tick. Window creation, etc."""

    def update(self, tick: int, match: "Match", events: "list[Event]") -> None:
        """Called once per tick after _post_tick housekeeping."""

    def stop(self) -> None:
        """Called once after the last tick. Window teardown, etc."""

    def is_open(self) -> bool:
        """Return False when the user has closed the viewer; the Match
        loop reads this each tick and ends gracefully if the window is gone."""

    # NOTE — driver-style hooks (HAJ-126) `drives_loop()` and
    # `run_interactive(match)` are NOT in the Protocol body so that
    # @runtime_checkable still accepts push-only renderers like
    # RecordingRenderer. Match probes them via getattr at run time.


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
        debug=None,
        seed: Optional[int] = None,
        stream: str = "both",
        renderer: Optional["Renderer"] = None,
    ) -> None:
        if stream not in VALID_STREAMS:
            raise ValueError(
                f"stream must be one of {sorted(VALID_STREAMS)}, got {stream!r}"
            )
        self.fighter_a = fighter_a
        self.fighter_b = fighter_b
        self.referee   = referee
        self.max_ticks = max_ticks
        self.seed      = seed
        self._debug = debug
        self._stream = stream
        # HAJ-125 — optional viewer hook. None during normal/test runs.
        self._renderer = renderer
        if self._debug is not None:
            self._debug.bind_match(self)

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

        # Part 6.1 — in-progress throw attempts, keyed by attacker name. A
        # throw committed with N>1 unfolds across N ticks, with sub-events
        # (REACH_KUZUSHI → KUZUSHI_ACHIEVED → TSUKURI → KAKE_COMMIT) emitted
        # per the compression schedule. Resolution happens on KAKE_COMMIT.
        self._throws_in_progress: dict[str, "_ThrowInProgress"] = {}

        # Part 6.3 — named compromised-state tracker keyed by fighter name.
        # Set when a failed throw mutates tori's BodyState; cleared when
        # stun_ticks decays to zero (end of the recovery window). Uke's
        # counter-fire probability reads this for per-state vulnerability
        # bonuses.
        self._compromised_states: dict[str, object] = {}

        # Part 6.3 — kumi-kata clock snapshot taken at commit start, before
        # the attack resets the clock. Consumed by _resolve_failed_commit to
        # evaluate is_desperation_state against the clock value that existed
        # when the throw was actually decided on.
        self._commit_kumi_kata_snapshot: dict[str, int] = {}

        # HAJ-49 / HAJ-67 — per-fighter commit motivation snapshot. None
        # for normal and desperation commits; one of CommitMotivation's
        # four values for non-scoring commits. Set in _resolve_commit_throw,
        # consumed in _resolve_failed_commit to force TACTICAL_DROP_RESET
        # and pick the motivation-specific prose template. Cleared when
        # the attempt resolves.
        self._commit_motivation: dict[str, Optional[CommitMotivation]] = {}

        # For MatchState snapshots
        self._a_score: dict = {"waza_ari": 0, "ippon": False}
        self._b_score: dict = {"waza_ari": 0, "ippon": False}

        # HAJ-46 — retain scoring events so the end-of-match narrative can
        # name the decisive technique(s). Cheap: at most a handful of
        # entries per match.
        self._scoring_events: list[Event] = []

        # HAJ-47 — per-fighter desperation-trigger jitter. Symmetric fighters
        # in symmetric states would otherwise enter desperation on the same
        # tick. A small offset from a stable per-fighter seed (name + match
        # seed) breaks that symmetry while staying reproducible across
        # replays. Offsets are intentionally small: they shift entry timing
        # by a few ticks, not the trigger semantics.
        seed_basis = self.seed if self.seed is not None else 0
        self._desperation_jitter: dict[str, dict] = {}
        for name in (fighter_a.identity.name, fighter_b.identity.name):
            r = random.Random(f"haj47:{name}:{seed_basis}")
            self._desperation_jitter[name] = {
                "composure_frac": r.uniform(-0.05, 0.05),
                "clock_ticks":    r.randint(-2, 2),
                "imminent_ticks": r.randint(-1, 1),
                # Defensive-tracker entry/exit threshold offsets (score units).
                "def_entry":      r.uniform(-0.5, 0.5),
                "def_exit":       r.uniform(-0.3, 0.3),
            }

        # HAJ-35 — defensive desperation trackers + last-known state flags
        # (edge-triggered logging). HAJ-47 — each tracker carries a per-
        # fighter threshold offset so the entry/exit predicate diverges
        # for two symmetric fighters.
        self._defensive_pressure: dict[str, DefensivePressureTracker] = {
            name: DefensivePressureTracker(
                entry_threshold_offset=self._desperation_jitter[name]["def_entry"],
                exit_threshold_offset=self._desperation_jitter[name]["def_exit"],
            )
            for name in (fighter_a.identity.name, fighter_b.identity.name)
        }
        self._offensive_desperation_active: dict[str, bool] = {
            fighter_a.identity.name: False,
            fighter_b.identity.name: False,
        }
        self._defensive_desperation_active: dict[str, bool] = {
            fighter_a.identity.name: False,
            fighter_b.identity.name: False,
        }
        # HAJ-48 — emit-on-confirmed-duration trackers for desperation
        # state announcements. The underlying flags above always reflect the
        # mechanic; these only gate the [state] event lines so that flicker
        # under STATE_ANNOUNCE_MIN_TICKS produces no log noise. Per fighter
        # per kind: tick the state went active (None when inactive) and
        # whether ENTER has been announced for the current active phase.
        names = (fighter_a.identity.name, fighter_b.identity.name)
        self._desp_state_started: dict[str, dict[str, Optional[int]]] = {
            n: {"defensive": None, "offensive": None} for n in names
        }
        self._desp_enter_announced: dict[str, dict[str, bool]] = {
            n: {"defensive": False, "offensive": False} for n in names
        }

    # -----------------------------------------------------------------------
    # RUN
    # -----------------------------------------------------------------------
    def run(self) -> None:
        # HAJ-126 — when an interactive renderer is attached (one that owns
        # the wall-clock loop for pause/step/scrub), Match hands the loop
        # off and lets the renderer drive begin/step/end. Non-interactive
        # renderers and headless runs use the in-line loop below.
        if self._renderer is not None and self._renderer_drives_loop():
            self._renderer.start()
            try:
                self._renderer.run_interactive(self)
            finally:
                self._renderer.stop()
            return

        self._print_header()
        if self._debug is not None:
            self._debug.print_banner()
        if self._renderer is not None:
            self._renderer.start()

        try:
            self.begin()
            while not self.is_done():
                self.step()
                if self._debug is not None and self._debug.quit_requested():
                    print("[debug] match aborted by inspector.")
                    break
            self.end()
        finally:
            if self._renderer is not None:
                self._renderer.stop()

    # -----------------------------------------------------------------------
    # PUBLIC LOOP API (HAJ-126)
    # External drivers (the pygame viewer's interactive loop) call these
    # instead of run(). Non-driver renderers and headless runs let run()
    # call them in sequence.
    # -----------------------------------------------------------------------
    def begin(self) -> None:
        """Pre-loop work: header, banner, Hajime announcement, optional
        tick-0 paint. Idempotent in the sense that calling it twice is
        a programming error — the caller owns the loop lifecycle."""
        self._print_header()
        if self._debug is not None:
            self._debug.print_banner()
        # Hajime — route through the event emitter so the Hajime call
        # participates in side-by-side rendering (HAJ-65 extension).
        hajime = self.referee.announce_hajime(tick=0)
        self._print_events([hajime])
        # HAJ-125 — first frame at tick 0 so the viewer paints the
        # starting positions before any motion.
        if self._renderer is not None:
            self._renderer.update(0, self, [hajime])
        print()

    def step(self) -> None:
        """Advance the match by exactly one tick. Pause/step in the
        viewer is just "don't call step()" / "call step() once." The
        per-tick path is unchanged so paused-then-stepped state is
        identical to running uninterrupted."""
        if self.is_done():
            return
        self.ticks_run += 1
        self._tick(self.ticks_run)

    def end(self) -> None:
        """Post-loop resolution: decision/draw fallback, narrative summary."""
        self._resolve_match()

    def is_done(self) -> bool:
        """True when the match has ended (score, time-up, or external
        signal such as the viewer window closing)."""
        return self.match_over or self.ticks_run >= self.max_ticks

    def _renderer_drives_loop(self) -> bool:
        """Optional capability check on the renderer protocol. Defaults
        to False so existing renderers (RecordingRenderer, future
        non-interactive viewers) continue to receive update() pushes."""
        drives = getattr(self._renderer, "drives_loop", None)
        return bool(drives()) if callable(drives) else False

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

        # Part 6.1 — advance any in-progress multi-tick throws BEFORE action
        # selection. Sub-events emit at their scheduled offsets; KAKE_COMMIT
        # resolves the throw via the same landing path as single-tick commits.
        advance_events = self._advance_throws_in_progress(tick)
        events.extend(advance_events)
        if self.match_over:
            self._post_tick(tick, events)
            return
        if self.sub_loop_state == SubLoopState.NE_WAZA:
            self._post_tick(tick, events)
            return

        # Part 6.2 — counter-window opportunities. Each tick, check whether
        # either fighter's dyad state lets them fire a counter against the
        # other. At most one counter fires per tick; a counter aborts any
        # in-progress attempt it preempts.
        counter_events = self._check_counter_opportunities(tick)
        events.extend(counter_events)
        if self.match_over:
            self._post_tick(tick, events)
            return
        if self.sub_loop_state == SubLoopState.NE_WAZA:
            self._post_tick(tick, events)
            return

        # HAJ-35 — defensive-pressure: record composure each tick so the
        # rolling-window drop signal has data to work from, then recompute
        # each fighter's active state and emit transition events.
        self._update_defensive_desperation(tick, events)

        # Action selection (Part 3.3). Each judoka picks up to two actions
        # based on the priority ladder; COMMIT_THROW supersedes the cap.
        # HAJ-57 — pass each defender the throw_id of any in-progress attack
        # by their opponent so the defensive hip-block rung can fire.
        a_opp_tip = self._throws_in_progress.get(self.fighter_b.identity.name)
        b_opp_tip = self._throws_in_progress.get(self.fighter_a.identity.name)
        a_opp_throw = a_opp_tip.throw_id if a_opp_tip is not None else None
        b_opp_throw = b_opp_tip.throw_id if b_opp_tip is not None else None

        actions_a = select_actions(
            self.fighter_a, self.fighter_b, self.grip_graph,
            self.kumi_kata_clock[self.fighter_a.identity.name],
            defensive_desperation=self._defensive_desperation_active[
                self.fighter_a.identity.name
            ],
            opponent_kumi_kata_clock=self.kumi_kata_clock[
                self.fighter_b.identity.name
            ],
            opponent_in_progress_throw=a_opp_throw,
            desperation_jitter=self._desperation_jitter.get(
                self.fighter_a.identity.name
            ),
        )
        actions_b = select_actions(
            self.fighter_b, self.fighter_a, self.grip_graph,
            self.kumi_kata_clock[self.fighter_b.identity.name],
            defensive_desperation=self._defensive_desperation_active[
                self.fighter_b.identity.name
            ],
            opponent_kumi_kata_clock=self.kumi_kata_clock[
                self.fighter_a.identity.name
            ],
            opponent_in_progress_throw=b_opp_throw,
            desperation_jitter=self._desperation_jitter.get(
                self.fighter_b.identity.name
            ),
        )
        # A fighter mid-attempt must not re-commit — strip any COMMIT_THROW
        # the ladder re-proposes this tick.
        actions_a = self._strip_commits_if_in_progress(
            self.fighter_a.identity.name, actions_a,
        )
        actions_b = self._strip_commits_if_in_progress(
            self.fighter_b.identity.name, actions_b,
        )

        # HAJ-57 — resolve any defensive hip-block actions. If a fighter
        # picked BLOCK_HIP and the opponent has a hip-loading throw mid-
        # flight, abort the throw with BLOCKED_BY_HIP and clean reset.
        hip_block_events = self._check_hip_blocks(
            actions_a, actions_b, tick,
        )
        events.extend(hip_block_events)

        # Step 1 — grip state updates (REACH/DEEPEN/STRIP/RELEASE/...).
        # Snapshot pre-action depths so we can coalesce intra-tick
        # strip/deepen oscillation (fighter_a silently deepens POCKET→STANDARD,
        # fighter_b's strip selected against the pre-tick snapshot then
        # drops it back to POCKET). Without this, a degrade event fires
        # every tick for a grip whose net depth never changed.
        pre_tick_depths = {id(e): e.depth_level for e in self.grip_graph.edges}
        self._apply_grip_actions(self.fighter_a, actions_a, tick, events)
        self._apply_grip_actions(self.fighter_b, actions_b, tick, events)
        self._coalesce_grip_degrades(events, pre_tick_depths)

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

        # HAJ-128 — re-aim each fighter's facing vector at the opponent
        # after motion. Real judoka stay squared up to each other; without
        # this, the facing arrow stays pinned at its Hajime-time direction
        # while the dot drifts around the mat.
        self._reorient_facing(self.fighter_a, self.fighter_b)
        self._reorient_facing(self.fighter_b, self.fighter_a)

        # Step 9 — kuzushi check (post-update state).
        a_kuzushi = self._is_kuzushi(self.fighter_a)
        b_kuzushi = self._is_kuzushi(self.fighter_b)
        if a_kuzushi and not self._a_was_kuzushi_last_tick:
            events.append(Event(
                tick=tick, event_type="KUZUSHI_INDUCED",
                description=f"[physics] {self.fighter_a.identity.name} off-balance.",
            ))
            self._defensive_pressure[self.fighter_a.identity.name].record_kuzushi(tick)
        if b_kuzushi and not self._b_was_kuzushi_last_tick:
            events.append(Event(
                tick=tick, event_type="KUZUSHI_INDUCED",
                description=f"[physics] {self.fighter_b.identity.name} off-balance.",
            ))
            self._defensive_pressure[self.fighter_b.identity.name].record_kuzushi(tick)
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
                    offensive_desperation=act.offensive_desperation,
                    defensive_desperation=act.defensive_desperation,
                    gate_bypass_reason=act.gate_bypass_reason,
                    gate_bypass_kind=act.gate_bypass_kind,
                    commit_motivation=act.commit_motivation,
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

        if self._debug is not None:
            self._debug.maybe_pause(tick, events)

        # HAJ-125 — push the same tick state to the viewer (read-only).
        if self._renderer is not None:
            self._renderer.update(tick, self, events)
            if not self._renderer.is_open():
                # User closed the viewer window — bail out cleanly so the
                # match loop's per-tick guard can exit on the next iteration.
                self.match_over = True

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
                self.win_method = "ippon (submission)"
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

    def _coalesce_grip_degrades(
        self, events: list[Event], pre_tick_depths: dict,
    ) -> None:
        """Drop GRIP_DEGRADE events whose edge ended the tick at its pre-tick
        depth. Both fighters deepen-then-strip each other's grips every tick
        in the shallow-grips branch of the action ladder; the strip fires a
        degrade event even when the grasper's own DEEPEN this tick already
        reversed it. Net-zero transitions are log noise.
        """
        live_edges = {id(e): e for e in self.grip_graph.edges}
        filtered: list[Event] = []
        for ev in events:
            if ev.event_type != "GRIP_DEGRADE":
                filtered.append(ev)
                continue
            edge_id = ev.data.get("edge_id")
            edge = live_edges.get(edge_id) if edge_id is not None else None
            if edge is None:
                filtered.append(ev)
                continue
            pre = pre_tick_depths.get(edge_id)
            if pre is not None and edge.depth_level == pre:
                continue  # net-zero oscillation
            filtered.append(ev)
        events[:] = filtered

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
                data={"edge_id": id(edge)},
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
        # HAJ-51 — read the current matchup once per call; per-edge multiplier
        # comes from FORCE_ENVELOPES[grip_type].stance_parity below.
        stance_matchup = self._compute_stance_matchup()

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

            # HAJ-51 — apply per-grip stance parity to envelope authority.
            # Lapel-high / collar lose authority in mirrored stance; pistol /
            # cross gain it. Multiplier is bounded to the [0.7, 1.3] band by
            # the StanceParity declarations themselves.
            stance_parity_mod = env.stance_parity.multiplier(stance_matchup)

            # Calibration pipeline (Part 2.4):
            #   delivered = min(requested, env_max) × depth × strength × fatigue × composure × noise × stance_parity
            depth_mod     = edge.depth_level.modifier()
            strength_mod  = _grip_strength(attacker)
            hand_fatigue  = max(0.0, 1.0 - attacker.state.body[act.hand].fatigue)
            ceiling       = max(1.0, float(attacker.capability.composure_ceiling))
            composure_mod = max(0.0, min(1.0, attacker.state.composure_current / ceiling))
            noise         = 1.0 + random.uniform(-FORCE_NOISE_PCT, FORCE_NOISE_PCT)

            requested = min(act.magnitude, env_max)
            delivered = (requested * depth_mod * strength_mod * hand_fatigue
                         * composure_mod * noise * stance_parity_mod)

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
    def _reorient_facing(self, judoka: Judoka, opponent: Judoka) -> None:
        """HAJ-128 — point this judoka's facing unit-vector at the opponent.
        Called once per tick after CoM updates so the viewer arrow tracks
        body orientation. Bails out if the two fighters share a position."""
        sx, sy = judoka.state.body_state.com_position
        ox, oy = opponent.state.body_state.com_position
        dx, dy = ox - sx, oy - sy
        norm = (dx * dx + dy * dy) ** 0.5
        if norm < 1e-6:
            return
        judoka.state.body_state.facing = (dx / norm, dy / norm)

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
            # HAJ-128 — tactical-step semantics. The fighter's center of
            # mass advances with the foot at half the step magnitude (one
            # tick = one weight-transfer phase, not a full body shift).
            # The OTHER foot trails behind at zero — natural rest stance
            # is restored by the next step. CoM movement is what makes
            # locomotion visible and what drives OOB / mat positioning.
            cx, cy = bs.com_position
            bs.com_position = (cx + dx * mag * 0.5, cy + dy * mag * 0.5)
            # Small cardio cost: stepping spends fuel. Calibrated to be
            # noticeable across many ticks but not dominant.
            judoka.state.cardio_current = max(
                0.0, judoka.state.cardio_current - STEP_CARDIO_COST
            )

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
    # STEPS 10-11 — COMMIT_THROW RESOLUTION (Part 6.1 skill-compression aware)
    # -----------------------------------------------------------------------
    def _resolve_commit_throw(
        self, attacker: Judoka, defender: Judoka, throw_id: ThrowID, tick: int,
        *,
        offensive_desperation: bool = False,
        defensive_desperation: bool = False,
        gate_bypass_reason: Optional[str] = None,
        gate_bypass_kind: Optional[str] = None,
        commit_motivation: Optional["CommitMotivation"] = None,
    ) -> list[Event]:
        """Entry point for a COMMIT_THROW action.

        Branches on compression N (spec 6.1):
          - N == 1  → resolve immediately; emits THROW_ENTRY + all sub-events
            in a single tick, then resolve_throw + _apply_throw_result.
          - N  > 1  → start a multi-tick attempt. Emit tick-0 sub-events and
            the THROW_ENTRY event. Resolution is deferred to the KAKE_COMMIT
            tick, driven by _advance_throws_in_progress.
        """
        # Reject a second commit from the same attacker while one is in-flight.
        if attacker.identity.name in self._throws_in_progress:
            return []

        # HAJ-127 — start-of-attack OOB gate. A fighter already over the
        # boundary cannot legally fire a throw — denies edge cheese (foot
        # already over the line, fire a tomoe-nage). The standing-OOB
        # check inside should_call_matte will fire next tick to formalize
        # it as Matte. Distinct from the in-flight grace: that grace
        # protects throws that *started* inside; this gate prevents
        # commits from outside.
        if is_out_of_bounds(attacker):
            return [Event(
                tick=tick,
                event_type="THROW_DENIED_OOB",
                description=(
                    f"[throw] {attacker.identity.name} commit denied — "
                    f"already out of bounds."
                ),
                data={"attacker": attacker.identity.name,
                      "throw_id": throw_id.name},
            )]

        # HAJ-35 — the defender has now officially taken an incoming throw;
        # feed their rolling-window counter. We do this before the resolve
        # path so a sequence of attacks accumulates even if they're all N=1.
        self._defensive_pressure[defender.identity.name].record_opponent_commit(tick)

        actual = actual_signature_match(throw_id, attacker, defender, self.grip_graph)
        commit_threshold = commit_threshold_for(throw_id)
        eq = compute_execution_quality(actual, commit_threshold)
        n = compression_n_for(attacker, throw_id)
        schedule = sub_event_schedule(n)
        throw_name = THROW_REGISTRY[throw_id].name

        # Passivity / attack-registration fires at commit start regardless of N.
        self._last_attack_tick[attacker.identity.name] = tick
        self.grip_graph.register_attack(attacker.identity.name)
        # Snapshot the kumi-kata clock before reset so Part 6.3 desperation
        # can evaluate against the pre-attack clock value.
        self._commit_kumi_kata_snapshot[attacker.identity.name] = (
            self.kumi_kata_clock.get(attacker.identity.name, 0)
        )
        self.kumi_kata_clock[attacker.identity.name] = 0

        # N=1 suppresses the four sub-event lines (they'd all land on the same
        # tick as the outcome); the THROW_ENTRY stays visible so a successful
        # elite throw still has a [throw] commit line preceding its [score].
        collapse_n1 = n <= 1

        # HAJ-49 / HAJ-67 — stash the commit-time motivation so
        # _resolve_failed_commit can route the outcome to TACTICAL_DROP_RESET
        # and render the motivation-specific compact prose. Stored keyed
        # by attacker name so it survives the multi-tick attempt window.
        self._commit_motivation[attacker.identity.name] = commit_motivation

        # HAJ-35 / HAJ-49 / HAJ-67 — surface commit-time motivation +
        # grip-gate-bypass on the [throw] line. Normal commits have no tag;
        # offensive desperation keeps its legacy tag; non-scoring motivations
        # surface via `commit_motivation: <name>` so downstream log-parsing
        # and the 20-match QA can count each motivation distinctly.
        tags: list[str] = []
        if offensive_desperation:
            tags.append("offensive desperation")
        if defensive_desperation:
            tags.append("defensive desperation")
        if commit_motivation is not None:
            tags.append(
                f"commit motivation: {motivation_debug_tag(commit_motivation)}"
            )
        elif gate_bypass_reason is not None:
            # Genuine gate-bypass reason only surfaces when the commit isn't
            # already tagged as a non-scoring motivation (which shares the
            # bypass slot but is more informative on its own).
            tags.append(f"gate bypassed: {gate_bypass_reason}")
        tag_suffix = f"  ({'; '.join(tags)})" if tags else ""
        events: list[Event] = [Event(
            tick=tick, event_type="THROW_ENTRY",
            description=(
                f"[throw] {attacker.identity.name} commits — {throw_name} "
                f"(eq={eq:.2f}).{tag_suffix}"
            ),
            data={
                "throw_id": throw_id.name,
                "compression_n": n,
                "actual_match": actual,
                "commit_threshold": commit_threshold,
                "execution_quality": eq,
                "offensive_desperation": offensive_desperation,
                "defensive_desperation": defensive_desperation,
                "gate_bypass_reason":    gate_bypass_reason,
                "gate_bypass_kind":      gate_bypass_kind,
                "commit_motivation": (
                    commit_motivation.name if commit_motivation else None
                ),
            },
        )]

        # Emit tick-0 sub-events.
        events.extend(self._emit_sub_events(
            attacker, throw_name, schedule.get(0, []), tick,
            silent=collapse_n1,
        ))

        if n <= 1:
            # Single-tick resolution — the historical path.
            events.extend(self._resolve_kake(
                attacker, defender, throw_id, actual, tick,
            ))
            return events

        # Multi-tick: stash state and return. _advance_throws_in_progress
        # handles subsequent ticks.
        self._throws_in_progress[attacker.identity.name] = _ThrowInProgress(
            attacker_name=attacker.identity.name,
            defender_name=defender.identity.name,
            throw_id=throw_id,
            start_tick=tick,
            compression_n=n,
            schedule=schedule,
            commit_actual=actual,
            commit_execution_quality=eq,
        )
        return events

    # -----------------------------------------------------------------------
    # PER-TICK ADVANCEMENT OF IN-PROGRESS THROWS (Part 6.1)
    # -----------------------------------------------------------------------
    def _advance_throws_in_progress(self, tick: int) -> list[Event]:
        """Advance every in-progress throw by one tick, emit sub-events,
        and resolve any that reached KAKE_COMMIT.

        Returns a combined event list. Iterates over a snapshot so that
        resolution / abort during iteration doesn't mutate mid-loop.
        """
        events: list[Event] = []
        for attacker_name, tip in list(self._throws_in_progress.items()):
            offset = tip.offset(tick)
            if offset < 1:
                # First tick was handled by _resolve_commit_throw itself.
                continue

            attacker = self._fighter_by_name(attacker_name)
            defender = self._fighter_by_name(tip.defender_name)
            if attacker is None or defender is None:
                del self._throws_in_progress[attacker_name]
                continue

            # Interrupt check: a stun, ippon loss of grips, or ne-waza
            # transition aborts the attempt mid-stride.
            abort_reason = self._should_abort_attempt(tip, attacker)
            if abort_reason is not None:
                events.extend(self._abort_throw_in_progress(
                    tip, attacker, defender, tick, abort_reason,
                ))
                continue

            sub_events = tip.schedule.get(offset, [])
            throw_name = THROW_REGISTRY[tip.throw_id].name
            events.extend(self._emit_sub_events(
                attacker, throw_name, sub_events, tick,
            ))

            if SubEvent.KAKE_COMMIT in sub_events:
                # Recompute signature at KAKE time — the match state has
                # changed over the attempt. resolve_throw uses the window
                # quality and is_forced flag derived from this fresh value.
                kake_actual = actual_signature_match(
                    tip.throw_id, attacker, defender, self.grip_graph,
                )
                events.extend(self._resolve_kake(
                    attacker, defender, tip.throw_id, kake_actual, tick,
                ))
                del self._throws_in_progress[attacker_name]

        return events

    def _emit_sub_events(
        self, attacker: Judoka, throw_name: str,
        sub_events: list[SubEvent], tick: int,
        silent: bool = False,
    ) -> list[Event]:
        events: list[Event] = []
        for sub in sub_events:
            label = SUB_EVENT_LABELS.get(sub, sub.name.lower())
            events.append(Event(
                tick=tick, event_type=f"SUB_{sub.name}",
                description=(
                    f"[throw] {attacker.identity.name} — {throw_name}: {label}."
                ),
                data={"sub_event": sub.name, "throw_name": throw_name,
                      "silent": silent},
            ))
        # Part 6.2 region classification reads the most recent sub-event.
        if sub_events:
            tip = self._throws_in_progress.get(attacker.identity.name)
            if tip is not None:
                tip.last_sub_event = sub_events[-1]
        return events

    def _resolve_kake(
        self, attacker: Judoka, defender: Judoka, throw_id: ThrowID,
        actual: float, tick: int,
    ) -> list[Event]:
        """Execute the KAKE_COMMIT resolution: resolve_throw + apply result.
        Factored out of _resolve_commit_throw so both N==1 and multi-tick
        paths share the same landing logic.

        Part 4.2.1 — eq is recomputed from the *kake-time* signature match so
        a multi-tick attempt that degrades between commit and kake reflects
        the worse execution in force transfer and landing severity.
        """
        matchup = self._compute_stance_matchup()
        window_q = max(0.0, actual - 0.5) * 2.0   # 0.5→0.0, 1.0→1.0
        is_forced = actual < 0.5
        commit_threshold = commit_threshold_for(throw_id)
        eq = compute_execution_quality(actual, commit_threshold)
        outcome, net = resolve_throw(
            attacker, defender, throw_id, matchup,
            window_quality=window_q, is_forced=is_forced,
            execution_quality=eq,
        )
        return list(self._apply_throw_result(
            attacker, defender, throw_id, outcome, net, window_q, tick,
            is_forced=is_forced, execution_quality=eq,
        ))

    def _should_abort_attempt(
        self, tip: "_ThrowInProgress", attacker: Judoka,
    ) -> Optional[str]:
        """Return a reason string if the in-progress attempt must abort,
        else None. Called each tick before emitting sub-events.
        """
        if attacker.state.stun_ticks > 0:
            return "stunned"
        # If attacker has lost all grips mid-attempt, they can't drive the
        # throw to completion.
        if not self.grip_graph.edges_owned_by(attacker.identity.name):
            return "grips collapsed"
        # Ne-waza transition mid-attempt — the standing attempt is moot.
        if self.sub_loop_state == SubLoopState.NE_WAZA:
            return "ground phase"
        return None

    def _abort_throw_in_progress(
        self, tip: "_ThrowInProgress", attacker: Judoka, defender: Judoka,
        tick: int, reason: str,
    ) -> list[Event]:
        """Route an aborted multi-tick attempt through the failed-commit
        pipeline so FailureOutcome selection still applies.
        """
        throw_name = THROW_REGISTRY[tip.throw_id].name
        events: list[Event] = [Event(
            tick=tick, event_type="THROW_ABORTED",
            description=(
                f"[throw] {attacker.identity.name} — {throw_name}: "
                f"aborted at tick {tip.offset(tick)} of {tip.compression_n} "
                f"({reason})."
            ),
            data={"reason": reason, "offset": tip.offset(tick),
                  "throw_id": tip.throw_id.name},
        )]
        events.extend(self._resolve_failed_commit(
            attacker, defender, tip.throw_id, throw_name,
            net=-1.0, tick=tick,
        ))
        del self._throws_in_progress[attacker.identity.name]
        return events

    def _fighter_by_name(self, name: str) -> Optional[Judoka]:
        if self.fighter_a.identity.name == name:
            return self.fighter_a
        if self.fighter_b.identity.name == name:
            return self.fighter_b
        return None

    def _strip_commits_if_in_progress(
        self, fighter_name: str, actions: list[Action],
    ) -> list[Action]:
        if fighter_name not in self._throws_in_progress:
            return actions
        return [a for a in actions if a.kind != ActionKind.COMMIT_THROW]

    def _check_hip_blocks(
        self,
        actions_a: list[Action],
        actions_b: list[Action],
        tick: int,
    ) -> list[Event]:
        """HAJ-57 — resolve BLOCK_HIP defensive actions.

        For each fighter who chose BLOCK_HIP, abort the opponent's in-
        progress throw if it's hip-loading. Throw fails with BLOCKED_BY_HIP
        outcome (clean stance reset, zero recovery, no compromised state).
        """
        events: list[Event] = []
        for blocker, target_actions, attacker_name in (
            (self.fighter_a, actions_a, self.fighter_b.identity.name),
            (self.fighter_b, actions_b, self.fighter_a.identity.name),
        ):
            if not any(a.kind == ActionKind.BLOCK_HIP for a in target_actions):
                continue
            tip = self._throws_in_progress.get(attacker_name)
            if tip is None:
                continue
            from worked_throws import worked_template_for
            template = worked_template_for(tip.throw_id)
            if template is None:
                continue
            bpr = getattr(template, "body_part_requirement", None)
            if bpr is None or not getattr(bpr, "hip_loading", False):
                continue
            attacker = self._fighter_by_name(attacker_name)
            if attacker is None:
                continue
            events.extend(self._abort_throw_blocked_by_hip(
                tip, attacker, blocker, tick,
            ))
        return events

    def _abort_throw_blocked_by_hip(
        self, tip: "_ThrowInProgress", attacker: Judoka, blocker: Judoka,
        tick: int,
    ) -> list[Event]:
        """HAJ-57 — terminate a hip-loading throw with BLOCKED_BY_HIP. No
        compromised state for tori, zero recovery — uke denied the geometry
        before tsukuri completed; fall back to grip battle next tick."""
        from failure_resolution import (
            FailureResolution, apply_failure_resolution, RECOVERY_TICKS_BY_OUTCOME,
        )
        from throw_templates import FailureOutcome

        throw_name = THROW_REGISTRY[tip.throw_id].name
        events: list[Event] = [Event(
            tick=tick, event_type="THROW_BLOCKED_BY_HIP",
            description=(
                f"[throw] {attacker.identity.name} → {throw_name}: "
                f"hip-blocked by {blocker.identity.name} — stance reset."
            ),
            data={"throw_id": tip.throw_id.name,
                  "blocker": blocker.identity.name,
                  "offset": tip.offset(tick),
                  "compression_n": tip.compression_n},
        )]
        # Clean reset: empty CompromisedStateConfig, zero recovery. Side
        # effects are limited to clearing the in-progress tip; tori's body
        # state is untouched. Drop the commit-time bookkeeping so we don't
        # leak state into the next attempt.
        # No dimension failed — uke just denied the geometry. Use sentinel
        # values so downstream consumers (which expect str/float) don't
        # explode; the BLOCKED_BY_HIP outcome itself carries the meaning.
        resolution = FailureResolution(
            outcome=FailureOutcome.BLOCKED_BY_HIP,
            recovery_ticks=RECOVERY_TICKS_BY_OUTCOME[FailureOutcome.BLOCKED_BY_HIP],
            failed_dimension="",
            dimension_score=0.0,
        )
        # No composure cost — the throw was prevented, not blown. Tori's
        # read was reasonable; uke just had the right defense available.
        apply_failure_resolution(resolution, attacker, composure_drop=0.0)
        a_name = attacker.identity.name
        self._commit_motivation.pop(a_name, None)
        self._commit_kumi_kata_snapshot.pop(a_name, 0)
        self._compromised_states[a_name] = resolution.outcome
        del self._throws_in_progress[a_name]
        return events

    # -----------------------------------------------------------------------
    # COUNTER-WINDOW OPPORTUNITIES (Part 6.2)
    # Gives each fighter a chance to fire a counter against the OTHER fighter
    # given the current dyad-region. At most one counter fires per tick.
    # -----------------------------------------------------------------------
    def _check_counter_opportunities(
        self, tick: int, rng: Optional[random.Random] = None,
    ) -> list[Event]:
        r = rng if rng is not None else random
        events: list[Event] = []
        for defender, attacker in (
            (self.fighter_a, self.fighter_b),
            (self.fighter_b, self.fighter_a),
        ):
            # A fighter already mid-attempt themselves can't counter.
            if defender.identity.name in self._throws_in_progress:
                continue
            fired = self._try_fire_counter(defender, attacker, tick, r)
            if fired is not None:
                events.extend(fired)
                # One counter per tick. A chain counter (tori counters uke's
                # counter) is a Ring-2+ concern.
                break
        return events

    def _try_fire_counter(
        self, defender: Judoka, attacker: Judoka, tick: int,
        rng: random.Random,
    ) -> Optional[list[Event]]:
        tip = self._throws_in_progress.get(attacker.identity.name)
        last_sub = tip.last_sub_event if tip is not None else None
        attacker_throw_id = tip.throw_id if tip is not None else None

        actual = actual_counter_window(
            attacker, defender, self.grip_graph, tip, last_sub,
        )
        if actual == CounterWindow.NONE:
            return None

        # HAJ-35 — defensive desperation: tired eyes reading patterns let
        # the defender see real attacks more reliably, and the "break the
        # pattern" instinct bumps the counter-fire probability.
        def_desp = self._defensive_desperation_active.get(
            defender.identity.name, False,
        )
        perceived = perceived_counter_window(
            actual, defender, rng=rng,
            defensive_desperation=def_desp,
            attacker=attacker,
        )
        if perceived == CounterWindow.NONE:
            return None
        if not has_counter_resources(defender):
            return None

        # Pick a counter throw. Sen-sen-no-sen has no attacker throw_id yet;
        # use a defender-side default so select_counter_throw can still run.
        effective_throw_id = attacker_throw_id or ThrowID.DE_ASHI_HARAI
        counter_id = select_counter_throw(defender, perceived, effective_throw_id)
        if counter_id is None:
            return None

        vuln = attacker_vulnerability_for(effective_throw_id)
        tori_eq = tip.commit_execution_quality if tip is not None else None
        p = counter_fire_probability(
            defender, perceived, vuln,
            defensive_desperation=def_desp,
            tori_execution_quality=tori_eq,
        )
        # Part 6.3 — per-state counter-vulnerability bonus. When tori is
        # currently in a named compromised state, uke's fire probability
        # gets an additive bump for the specific counters that exploit it.
        from compromised_state import counter_bonus_for
        p += counter_bonus_for(
            self._compromised_states.get(attacker.identity.name), counter_id,
        )
        if rng.random() >= p:
            return None

        # Counter fires.
        events: list[Event] = [Event(
            tick=tick, event_type="COUNTER_COMMIT",
            description=(
                f"[counter] {defender.identity.name} reads {perceived.name} — "
                f"fires {THROW_REGISTRY[counter_id].name} against "
                f"{attacker.identity.name}."
            ),
            data={
                "window":          perceived.name,
                "actual_window":   actual.name,
                "counter_throw":   counter_id.name,
                "attacker_throw":  effective_throw_id.name,
                "attacker":        attacker.identity.name,
                "defender":        defender.identity.name,
            },
        )]

        # If tori was mid-attempt, abort it — the counter preempts.
        if tip is not None:
            events.extend(self._abort_throw_in_progress(
                tip, attacker, defender, tick, reason="countered",
            ))

        # Route the defender's counter through the standard commit path. They
        # get the same skill-compression treatment as any other commit, so
        # an elite resolves immediately; a non-elite enters a fresh
        # multi-tick attempt (and could theoretically be countered in turn).
        events.extend(self._resolve_commit_throw(
            defender, attacker, counter_id, tick,
        ))
        return events

    # -----------------------------------------------------------------------
    # COMPOSURE / STALEMATE HELPERS
    # -----------------------------------------------------------------------
    def _update_defensive_desperation(
        self, tick: int, events: list[Event],
    ) -> None:
        """HAJ-35 — recompute each fighter's defensive-desperation flag and
        emit edge-triggered [state] events on entry/exit. Also surfaces
        edge-triggered offensive-desperation transitions using the same
        predicate consulted by compromised_state.
        """
        for f in (self.fighter_a, self.fighter_b):
            name = f.identity.name
            tracker = self._defensive_pressure[name]
            # Feed composure this tick (tracker prunes old entries itself).
            tracker.record_composure(tick, f.state.composure_current)
            was_def_active = self._defensive_desperation_active[name]
            is_def_active = tracker.update(tick)

            def_payload = lambda: {
                "type": "defensive",
                "description": (lambda br: (
                    f"[state] {name} enters defensive desperation "
                    f"(pressure={br['score']:.1f}; "
                    f"{br['opp_commits']} commits, "
                    f"{br['kuzushi']} kuzushi, "
                    f"composure -{br['composure_drop']:.2f} "
                    f"in {br['window_ticks']} ticks)."
                ))(tracker.breakdown(tick)),
                "data": tracker.breakdown(tick),
                "exit_description": f"[state] {name} exits defensive desperation.",
                "enter_event_type": "DEFENSIVE_DESPERATION_ENTER",
                "exit_event_type":  "DEFENSIVE_DESPERATION_EXIT",
            }
            self._emit_desperation_state_event(
                name, "defensive", was_def_active, is_def_active,
                tick, events, def_payload,
            )
            self._defensive_desperation_active[name] = is_def_active

            # Offensive desperation transitions — same predicate the commit
            # path uses, surfaced as an edge-triggered [state] line so the
            # reader sees it without waiting for a failed throw.
            off_active = is_desperation_state(
                f, self.kumi_kata_clock.get(name, 0),
                jitter=self._desperation_jitter.get(name),
            )
            was_off_active = self._offensive_desperation_active[name]
            off_payload = lambda: {
                "type": "offensive",
                "description": (
                    f"[state] {name} enters offensive desperation "
                    f"(composure {f.state.composure_current:.2f}/"
                    f"{f.capability.composure_ceiling}, "
                    f"kumi-kata clock {self.kumi_kata_clock.get(name, 0)})."
                ),
                "data": None,
                "exit_description": f"[state] {name} exits offensive desperation.",
                "enter_event_type": "OFFENSIVE_DESPERATION_ENTER",
                "exit_event_type":  "OFFENSIVE_DESPERATION_EXIT",
            }
            self._emit_desperation_state_event(
                name, "offensive", was_off_active, off_active,
                tick, events, off_payload,
            )
            self._offensive_desperation_active[name] = off_active

    def _emit_desperation_state_event(
        self, name: str, kind: str,
        was_active: bool, is_active: bool,
        tick: int, events: list[Event],
        payload_fn,
    ) -> None:
        """HAJ-48 — gate ENTER on STATE_ANNOUNCE_MIN_TICKS of confirmed
        duration; only emit EXIT if the matching ENTER was announced.

        Edge cases:
          - Flicker (active < N ticks): no ENTER, no EXIT, no log noise.
          - Long-lived: ENTER fires on the Nth tick of continuous activity;
            EXIT fires when the state releases.
          - Mid-state: payload composed at announce time so the description
            reflects the state when the reader sees it, not first transition.
        """
        started = self._desp_state_started[name][kind]
        announced = self._desp_enter_announced[name][kind]

        if is_active and not was_active:
            # Underlying state just turned on — start the confirmation clock.
            self._desp_state_started[name][kind] = tick
            self._desp_enter_announced[name][kind] = False
        elif (not is_active) and was_active:
            # Underlying state turned off — emit EXIT only if ENTER was logged.
            if announced:
                events.append(Event(
                    tick=tick,
                    event_type=payload_fn()["exit_event_type"],
                    description=payload_fn()["exit_description"],
                ))
            self._desp_state_started[name][kind] = None
            self._desp_enter_announced[name][kind] = False
        elif is_active and not announced and started is not None:
            # Continuously active — fire ENTER once duration confirmed.
            if tick - started >= STATE_ANNOUNCE_MIN_TICKS - 1:
                p = payload_fn()
                ev_kwargs = dict(
                    tick=tick,
                    event_type=p["enter_event_type"],
                    description=p["description"],
                )
                if p["data"] is not None:
                    ev_kwargs["data"] = p["data"]
                events.append(Event(**ev_kwargs))
                self._desp_enter_announced[name][kind] = True

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
        """Increment the stalemate counter unless *progress* was made this
        tick. Progress is any of: a commit, a kuzushi event, OR an active
        grip action (DEEPEN / STRIP) from either fighter.

        HAJ-36 surfaced a pre-existing bug: before the grip-presence gate,
        low-quality commits fired constantly from POCKET grips and reset
        this counter for free. With the gate, matches that are genuinely
        doing grip-fighting work looked identical to a dead hold — because
        the counter only counted commits. Grip contests now count.
        """
        committed = any(
            act.kind == ActionKind.COMMIT_THROW
            for act in (actions_a + actions_b)
        )
        active_grip_fight = any(
            act.kind in (ActionKind.DEEPEN, ActionKind.STRIP,
                         ActionKind.STRIP_TWO_ON_ONE, ActionKind.DEFEND_GRIP,
                         ActionKind.REPOSITION_GRIP)
            for act in (actions_a + actions_b)
        )
        if committed or a_kuzushi or b_kuzushi or active_grip_fight:
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
        execution_quality: float = 1.0,
    ) -> list[Event]:
        events: list[Event] = []
        a_name = attacker.identity.name
        d_name = defender.identity.name
        throw_name = THROW_REGISTRY[throw_id].name

        # Part 4.2.1 — quality band drives the narration tag on landing lines.
        band = band_for(execution_quality)
        band_prose = narration_for(throw_id, band)

        # Build landing for referee
        td = THROW_DEFS.get(throw_id)
        landing = ThrowLanding(
            landing_profile=td.landing_profile if td else LandingProfile.LATERAL,
            net_score=net,
            window_quality=window_quality,
            control_maintained=(outcome in ("IPPON", "WAZA_ARI")),
            execution_quality=execution_quality,
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
                score_ev = self.referee.announce_score(
                    outcome="IPPON",
                    scorer_id=a_name,
                    tick=tick,
                    source="throw",
                    technique=throw_name,
                    detail=band_prose,
                    execution_quality=execution_quality,
                    quality_band=band.name,
                )
                events.append(score_ev)
                self._scoring_events.append(score_ev)

            elif effective_award == "WAZA_ARI":
                attacker.state.score["waza_ari"] += 1
                wa_count = attacker.state.score["waza_ari"]
                score_ev = self.referee.announce_score(
                    outcome="WAZA_ARI",
                    scorer_id=a_name,
                    count=wa_count,
                    tick=tick,
                    source="throw",
                    technique=throw_name,
                    detail=band_prose,
                    execution_quality=execution_quality,
                    quality_band=band.name,
                )
                events.append(score_ev)
                self._scoring_events.append(score_ev)
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
                # HAJ-44 — single waza-ari is announced and play continues.
                # Real judo does not call Matte here; the sub-loop carries
                # on, and should_call_matte will fire if the action stalls.

            else:  # NO_SCORE despite high raw net — ref downgraded it
                events.append(Event(
                    tick=tick,
                    event_type="THROW_LANDING",
                    description=(
                        f"[throw] {a_name} → {throw_name} → no score "
                        f"(ref downgraded, eq={execution_quality:.2f}) "
                        f"— {band_prose}."
                    ),
                    data={"execution_quality": execution_quality,
                          "quality_band": band.name},
                ))

        elif outcome == "STUFFED":
            # HAJ-49 / HAJ-67 — a STUFFED result on any non-scoring
            # motivation (CLOCK_RESET / GRIP_ESCAPE / SHIDO_FARMING /
            # STAMINA_DESPERATION) collapses to the FAILED path: the point
            # of the pathway is the cheap failure. Don't set the ne-waza
            # window (there was nothing to stuff) and don't apply the
            # heavy -0.30 stuffed composure hit. TACTICAL_DROP_RESET
            # override inside _resolve_failed_commit supplies the correct
            # compromised state and the lighter drop.
            if self._commit_motivation.get(a_name) is not None:
                events.extend(self._resolve_failed_commit(
                    attacker, defender, throw_id, throw_name, net, tick,
                ))
            else:
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
            events.extend(self._resolve_failed_commit(
                attacker, defender, throw_id, throw_name, net, tick,
            ))

        # HAJ-49 / HAJ-67 — janitor: clear the motivation snapshot for this
        # attacker. _resolve_failed_commit pops it on failure; this covers
        # IPPON / WAZA_ARI / no-score landings where the snapshot wasn't
        # consumed.
        self._commit_motivation.pop(a_name, None)

        return events

    # -----------------------------------------------------------------------
    # FAILED-COMMIT FAILURE-OUTCOME ROUTING (Part 4.5 / Part 6.3)
    # -----------------------------------------------------------------------
    def _resolve_failed_commit(
        self, attacker: Judoka, defender: Judoka, throw_id: ThrowID,
        throw_name: str, net: float, tick: int,
    ) -> list[Event]:
        events: list[Event] = []
        a_name = attacker.identity.name

        # Worked-template throws route through the FailureSpec selector.
        # Legacy throws fall through to a generic "failed" event as before.
        from worked_throws import worked_template_for
        template = worked_template_for(throw_id)
        if template is None:
            events.append(Event(
                tick=tick, event_type="FAILED",
                description=(
                    f"[throw] {a_name} → {throw_name} → failed "
                    f"(no commitment)."
                ),
            ))
            return events

        from failure_resolution import (
            select_failure_outcome, apply_failure_resolution,
            FailureResolution, RECOVERY_TICKS_BY_OUTCOME,
        )
        from compromised_state import (
            is_desperation_state, apply_desperation_overlay,
            DESPERATION_COMPOSURE_DROP,
        )
        from throw_templates import FailureOutcome
        # HAJ-50 — pass throw_id so the signature-based tactical-drop
        # discriminator can fire for low-signature drop-variant commits
        # (e.g. a desperation commit that happened to fire on TAI_OTOSHI
        # with near-zero kuzushi). Physics doesn't care about motivation.
        resolution = select_failure_outcome(
            template, attacker, defender, self.grip_graph,
            throw_id=throw_id,
        )

        # HAJ-49 / HAJ-67 — any non-None commit motivation forces the
        # outcome to TACTICAL_DROP_RESET even if the discriminator didn't
        # fire (e.g. a commit that coincidentally produced above-floor
        # signature). The motivation label wins here because the ladder
        # explicitly chose the fake, and the log prose should match.
        motivation = self._commit_motivation.pop(a_name, None)
        if motivation is not None and resolution.outcome != FailureOutcome.TACTICAL_DROP_RESET:
            resolution = FailureResolution(
                outcome=FailureOutcome.TACTICAL_DROP_RESET,
                recovery_ticks=RECOVERY_TICKS_BY_OUTCOME[
                    FailureOutcome.TACTICAL_DROP_RESET
                ],
                failed_dimension=resolution.failed_dimension,
                dimension_score=resolution.dimension_score,
            )

        # Part 6.3 — desperation overlay: tori was panicked AND near
        # kumi-kata shido at commit time. Extend recovery by +2 ticks and
        # stack an extra composure drop on top of the base failure cost.
        # We consult the snapshot taken at commit-start, not the current
        # clock (which was reset to 0 when the attack registered).
        # HAJ-50 — desperation overlay does NOT fire on a TACTICAL_DROP_RESET
        # outcome (whether label-driven or signature-driven): there's
        # nothing to extend recovery on and no composure to bleed.
        snapshot_clock = self._commit_kumi_kata_snapshot.pop(a_name, 0)
        is_tactical_drop = resolution.outcome == FailureOutcome.TACTICAL_DROP_RESET
        desperation = (
            not is_tactical_drop
            and is_desperation_state(
                attacker, snapshot_clock,
                jitter=self._desperation_jitter.get(a_name),
            )
        )
        if desperation:
            resolution = apply_desperation_overlay(resolution)
            apply_failure_resolution(
                resolution, attacker,
                composure_drop=0.10 + DESPERATION_COMPOSURE_DROP,
            )
        elif is_tactical_drop:
            # HAJ-50 — near-zero composure hit on the outcome itself.
            # Whether tori labelled this as an intentional fake or
            # stumbled into one via a low-signature commit, the cost is
            # a single tick of no-offense and nothing else.
            apply_failure_resolution(resolution, attacker, composure_drop=0.005)
        else:
            apply_failure_resolution(resolution, attacker)

        # Track the compromised-state tag so uke's counter attempts during
        # the recovery window get the per-state vulnerability bonus.
        self._compromised_states[a_name] = resolution.outcome

        events.extend(self._format_failure_events(
            attacker, defender, throw_name, resolution, desperation, tick,
            motivation=motivation,
        ))
        return events

    # -----------------------------------------------------------------------
    # FAILURE-EVENT FORMATTING
    # Splits clean-counter outcomes into a [throw] stuffed line plus a
    # [counter] line naming uke as the counter thrower, so a reader never
    # sees a raw FailureOutcome enum name in the coach stream. Compromise
    # outcomes collapse into a single [throw] failed line using a human-
    # readable tag. Debug tooling reads the enum from event data.
    # -----------------------------------------------------------------------
    def _format_failure_events(
        self, attacker: Judoka, defender: Judoka, throw_name: str,
        resolution, desperation: bool, tick: int,
        motivation: Optional["CommitMotivation"] = None,
    ) -> list[Event]:
        from throw_templates import FailureOutcome
        a_name = attacker.identity.name
        d_name = defender.identity.name
        outcome = resolution.outcome
        recovery = resolution.recovery_ticks
        data = {
            "outcome":          outcome.name,
            "recovery_ticks":   recovery,
            "failed_dimension": resolution.failed_dimension,
            "dimension_score":  resolution.dimension_score,
            "desperation":      desperation,
            "commit_motivation": motivation.name if motivation else None,
        }
        desp_tag = "; desperation" if desperation else ""

        counter_desc = _COUNTER_NARRATIONS.get(outcome)
        if counter_desc is not None:
            return [
                Event(
                    tick=tick, event_type="THROW_STUFFED",
                    description=f"[throw] {a_name} → {throw_name} stuffed.",
                    data={"throw_name": throw_name, "attacker": a_name},
                ),
                Event(
                    tick=tick, event_type="FAILED",
                    description=(
                        f"[counter] {d_name} {counter_desc} "
                        f"({a_name} recovers {recovery} tick(s){desp_tag})."
                    ),
                    data={**data, "counter_thrower": d_name},
                ),
            ]

        # HAJ-50 / HAJ-67 — compact register for a tactical drop reset.
        # Each non-scoring motivation has its own two-beat template so a
        # reader can tell at a glance why tori faked (reset the clock,
        # escape a grip war, farm a shido, or collapse from exhaustion).
        # When the discriminator routed us here without a motivation label
        # (a desperation commit that happened to fire on a drop variant
        # with near-zero signature), fall back to the CLOCK_RESET prose —
        # that's the original HAJ-50 compact register.
        if outcome == FailureOutcome.TACTICAL_DROP_RESET:
            effective_motivation = motivation or CommitMotivation.CLOCK_RESET
            return [Event(
                tick=tick, event_type="FAILED",
                description=motivation_narration_for(
                    effective_motivation, tori=a_name, throw=throw_name,
                ),
                data=data,
            )]

        tag = _FAILURE_TAGS.get(outcome, outcome.name.lower())
        return [Event(
            tick=tick, event_type="FAILED",
            description=(
                f"[throw] {a_name} → {throw_name} → failed "
                f"({tag}; recovery {recovery} tick(s){desp_tag})."
            ),
            data=data,
        )]

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
            score_ev = self.referee.announce_score(
                outcome="IPPON",
                scorer_id=holder_id,
                tick=tick,
                source="pin",
                detail=f"{self.osaekomi.ticks_held}s hold",
            )
            events.append(score_ev)
            self._scoring_events.append(score_ev)
        elif award == "WAZA_ARI":
            holder.state.score["waza_ari"] += 1
            wa_count = holder.state.score["waza_ari"]
            score_ev = self.referee.announce_score(
                outcome="WAZA_ARI",
                scorer_id=holder_id,
                count=wa_count,
                tick=tick,
                source="pin",
                detail=f"{self.osaekomi.ticks_held}s hold",
            )
            events.append(score_ev)
            self._scoring_events.append(score_ev)
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
        return StanceMatchup.of(
            self.fighter_a.state.current_stance,
            self.fighter_b.state.current_stance,
        )

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
            fighter_a_oob=is_out_of_bounds(self.fighter_a),
            fighter_b_oob=is_out_of_bounds(self.fighter_b),
            any_throw_in_flight=bool(self._throws_in_progress),
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
        from body_state import UPRIGHT_LIMIT_RAD
        s = judoka.state
        s.body["right_hand"].fatigue = min(1.0, s.body["right_hand"].fatigue + HAND_FATIGUE_PER_TICK)
        s.body["left_hand"].fatigue  = min(1.0, s.body["left_hand"].fatigue  + HAND_FATIGUE_PER_TICK)
        s.cardio_current = max(0.0, s.cardio_current - CARDIO_DRAIN_PER_TICK)
        if s.body_state.trunk_sagittal > UPRIGHT_LIMIT_RAD:
            s.cardio_current = max(0.0, s.cardio_current - POSTURE_BENT_CARDIO_DRAIN)

    def _decay_stun(self, judoka: Judoka) -> None:
        if judoka.state.stun_ticks > 0:
            judoka.state.stun_ticks -= 1
        # Part 6.3: clear the compromised-state tag once the recovery window
        # closes. Uke's per-state counter-bonus expires at the same moment.
        if judoka.state.stun_ticks == 0:
            self._compromised_states.pop(judoka.identity.name, None)

    def _update_grip_passivity(self, tick: int, events: list[Event]) -> None:
        """Part 2.6 passivity clocks.

        - Per-fighter kumi-kata clock: ticks while the fighter owns any grip;
          resets on an attack (throw commit). Shido at KUMI_KATA_SHIDO_TICKS.
        - Per-grip unconventional clock: lives on each GripEdge; ticked in
          grip_graph.tick_update(). Shido if any owned edge crosses
          UNCONVENTIONAL_SHIDO_TICKS.

        HAJ-43 — both clocks pause for any fighter with a throw mid-flight.
        A passivity penalty during an active commit is incoherent: the
        fighter IS attacking. The clock advances again the tick after the
        attempt resolves (success, failure, or block).
        """
        for fighter in (self.fighter_a, self.fighter_b):
            name = fighter.identity.name
            owned = self.grip_graph.edges_owned_by(name)

            # HAJ-43 — skip both clocks while this fighter is mid-throw.
            # The clock isn't reset, just paused; if it was at 25 going in,
            # it's still at 25 when the attempt ends.
            if name in self._throws_in_progress:
                continue

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
            if ev.data.get("silent"):
                continue
            if self._stream == "prose":
                if _is_debug_only_event(ev.event_type):
                    continue
                # Prose stream: no tick prefix, no debug handles, eq= stripped.
                print(_render_prose(ev.description))
                continue

            # Compose the engineer (debug) line — tick prefix + description +
            # optional debug-inspector handle suffix. Both "debug" and "both"
            # need it.
            suffix = ""
            if self._debug is not None:
                suffix = self._debug.annotate_event(ev)
            debug_line = f"t{ev.tick:03d}: {ev.description}{suffix}"

            if self._stream == "debug":
                print(debug_line)
                continue

            # "both" — side-by-side dual stream: engineer on the left with
            # tick numbers, prose on the right with a countdown match clock.
            # A reader can scan one side and read across to correlate.
            if _is_debug_only_event(ev.event_type):
                prose_line = ""
            else:
                clock = _format_match_clock(self.max_ticks - ev.tick)
                prose_line = f"{clock}  {_render_prose(ev.description)}"
            print(_render_side_by_side(debug_line, prose_line))

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
        # HAJ-51 — stance matchup is one of the most consequential setup
        # facts in a match (drives grip leverage and which throws fit), so
        # it gets a header line at tick 0.
        a_stance = self.fighter_a.state.current_stance.name.lower()
        b_stance = self.fighter_b.state.current_stance.name.lower()
        matchup = self._compute_stance_matchup()
        nickname = "ai-yotsu" if matchup == StanceMatchup.MATCHED else "kenka-yotsu"
        print(f"  Stance matchup: {matchup.name} "
              f"({a.name} {a_stance}, {b.name} {b_stance} — {nickname})")
        print(f"  Referee: {r.name} ({r.nationality}) — "
              f"patience {r.newaza_patience:.1f} / "
              f"strictness {r.ippon_strictness:.1f}")
        if self.seed is not None:
            print(f"  Seed: {self.seed}  (replay: --seed {self.seed})")
        print("=" * 65)
        print()

    def _resolve_match(self) -> None:
        # Resolve a draw / decision into self.winner / self.win_method first
        # so the narrative composer has consistent state to read.
        if self.winner is None:
            a, b = self.fighter_a, self.fighter_b
            a_wa = a.state.score["waza_ari"]
            b_wa = b.state.score["waza_ari"]
            if a_wa > b_wa:
                self.winner, self.win_method = a, "decision"
            elif b_wa > a_wa:
                self.winner, self.win_method = b, "decision"
            else:
                self.win_method = "draw"

        print()
        print("=" * 65)
        for line in self._compose_match_summary():
            print(f"  {line}")
        print("=" * 65)

        # HAJ-46 — numeric per-fighter dump moves behind the debug stream.
        # Engineers tuning physics get the numbers; readers get prose.
        if self._stream == "debug":
            self._print_final_state(self.fighter_a)
            self._print_final_state(self.fighter_b)

    def _compose_match_summary(self) -> list[str]:
        """HAJ-46 — produce 1-2 prose lines naming winner, decisive
        technique, and one causal element drawn from final state.

        Returns a list of lines. The first names the outcome; the second
        (when present) names a single causal hook (loser fatigue, shidos,
        composure) so the reader sees *why*, not just *what*."""
        a, b = self.fighter_a, self.fighter_b

        # Format the match clock as M:SS for the outcome line.
        def clock(tick: int) -> str:
            remaining = max(0, self.max_ticks - tick)
            return f"{remaining // 60}:{remaining % 60:02d}"

        if self.win_method == "draw":
            wa = a.state.score["waza_ari"]
            return [f"Match drawn {wa}-{wa}. Golden score pending (Phase 3)."]

        winner = self.winner
        loser  = b if winner is a else a
        wn = winner.identity.name
        ln = loser.identity.name

        outcome_line = self._compose_outcome_line(winner, loser, clock)
        causal_line = self._compose_causal_hook(loser, ln)

        out = [outcome_line]
        if causal_line:
            out.append(causal_line)
        return out

    def _compose_outcome_line(self, winner, loser, clock_fn) -> str:
        wn = winner.identity.name
        ln = loser.identity.name
        method = self.win_method
        wa_w = winner.state.score["waza_ari"]
        wa_l = loser.state.score["waza_ari"]

        if method == "ippon":
            # Throw ippon — pull the technique from the most recent IPPON
            # scoring event with source='throw'.
            tech = self._latest_ippon_technique(winner.identity.name, "throw")
            tail = f" — {tech}" if tech else ""
            tick = self._latest_ippon_tick(winner.identity.name)
            stamp = f" at {clock_fn(tick)}" if tick is not None else ""
            return f"{wn} won by ippon{tail}{stamp}."
        if method == "ippon (pin)":
            tick = self._latest_ippon_tick(winner.identity.name)
            stamp = f" at {clock_fn(tick)}" if tick is not None else ""
            return f"{wn} won by ippon (pin) — {self.osaekomi.ticks_held}s hold{stamp}."
        if method == "ippon (submission)":
            tick = self.ticks_run
            return f"{wn} won by ippon (submission) at {clock_fn(tick)}."
        if method == "two waza-ari":
            techs = [
                e.data.get("technique") for e in self._scoring_events
                if e.data.get("scorer") == winner.identity.name
                and e.data.get("outcome") == "WAZA_ARI"
            ]
            techs = [t for t in techs if t]
            if len(techs) >= 2:
                return f"{wn} won by two waza-ari — {techs[0]}, then {techs[1]}."
            if techs:
                return f"{wn} won by two waza-ari — {techs[0]} sealed it."
            return f"{wn} won by two waza-ari."
        if method == "decision":
            return (f"{wn} won the decision {wa_w}-{wa_l} on waza-ari — "
                    f"neither fighter found ippon.")
        return f"{wn} won by {method}."

    def _compose_causal_hook(self, loser, ln) -> str:
        """One short clause naming the dimension that broke for the loser.
        Order of preference: shidos → ne-waza-relevant fatigue → cardio →
        composure collapse. Returns "" if no signal stands out."""
        s = loser.state
        # Shido: most concrete cause — the ref had been warning them.
        if s.shidos >= 2:
            return f"{ln} had been warned {s.shidos} times on passivity."
        if s.shidos == 1:
            return f"{ln} was already on a shido for passivity."
        # Heavy fatigue on a load-bearing dimension.
        fatigues = {
            "right_leg":  s.body["right_leg"].fatigue,
            "core":       s.body["core"].fatigue,
            "right_hand": s.body["right_hand"].fatigue,
        }
        worst_part, worst_fat = max(fatigues.items(), key=lambda kv: kv[1])
        if worst_fat >= 0.70:
            return f"{ln}'s {worst_part} (fatigue {worst_fat:.2f}) had run dry."
        # Cardio: slower bleed; distinct cue.
        if s.cardio_current <= 0.40:
            return f"{ln}'s cardio (now {s.cardio_current:.2f}) had bottomed out."
        # Composure: last resort signal — only flag a true collapse.
        ceiling = max(1.0, float(loser.capability.composure_ceiling))
        comp_frac = s.composure_current / ceiling
        if comp_frac < 0.25:
            return f"{ln}'s composure had collapsed ({s.composure_current:.1f}/{ceiling:.0f})."
        return ""

    def _latest_ippon_technique(
        self, scorer: str, source: str,
    ) -> Optional[str]:
        for ev in reversed(self._scoring_events):
            d = ev.data
            if (d.get("scorer") == scorer and d.get("outcome") == "IPPON"
                    and d.get("source") == source):
                return d.get("technique")
        return None

    def _latest_ippon_tick(self, scorer: str) -> Optional[int]:
        for ev in reversed(self._scoring_events):
            d = ev.data
            if d.get("scorer") == scorer and d.get("outcome") == "IPPON":
                return ev.tick
        return None

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
