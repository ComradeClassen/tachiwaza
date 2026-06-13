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
    BodyArchetype, DominantSide, Position, Stance, StanceMatchup,
    SubLoopState, LandingProfile, GripMode, MatteReason,
    BodyPart, GripTarget, GripTypeV2,
)
from judoka import Judoka
import stance as stance_mod
from throws import ThrowID, ThrowDef, THROW_REGISTRY, THROW_DEFS
from grip_graph import GripGraph, GripEdge, Event
from position_machine import PositionMachine
from referee import Referee, MatchState, ThrowLanding, ScoreResult
from ne_waza import OsaekomiClock, NewazaResolver
from actions import (
    Action, ActionKind,
    GRIP_KINDS, FORCE_KINDS, BODY_KINDS, DRIVING_FORCE_KINDS,
    FOOT_ATTACK_KINDS, SUBSTANTIVE_KINDS,
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
from body_part_events import BodyPartEvent
from body_part_decompose import (
    decompose_grip_establish, decompose_grip_deepen, decompose_grip_strip,
    decompose_grip_release, decompose_reach,
    decompose_pull, decompose_foot_attack, decompose_step,
    decompose_commit, decompose_counter, compute_head_state,
)
from narration import MatSideNarrator, MatchClockEntry
from significance import significance_for
from recognition import (
    recognition_score, recognition_band, recognized_name, name_lands_at,
)
from intent_signal import (
    IntentSignal, SETUP_THROW_COMMIT, SETUP_GRIP_STRIP, SETUP_NE_WAZA_INIT,
    SETUP_PULL, SETUP_FOOT_ATTACK, SETUP_DEFENSIVE_BLOCK,
)
from reaction_lag import (
    sample_lag, choose_response, disguise_for, PerceptionResponse,
)
from grip_initiative import (
    sample_initiative, select_response, clock_pressure_roles,
    GripResponseChoice,
    RESP_CONTEST, RESP_MATCH, RESP_PURSUE_OWN, RESP_DEFENSIVE, RESP_DISENGAGE,
    RESP_ACCEPT_BAIT,
)
from cross_grip import (
    select_lead_grip, select_defensive_frame, lead_grip_placement,
    lead_grip_coach_prose, defensive_frame_coach_prose,
    PLAN_ORTHODOX,
)
from chase_decision import (
    ChaseDecision, ChaseDecisionResult, make_chase_decision,
)
from ground_continuation import (
    GroundContinuation, GroundContinuationResult,
    make_ground_continuation_decision,
)
from defense_decision import (
    DefenseDecision, DefenseDecisionResult, make_defense_decision,
)


# ---------------------------------------------------------------------------
# TUNING CONSTANTS
# All calibration knobs in one place. Phase 3 will tune these after watching
# many matches.
# ---------------------------------------------------------------------------

# HAJ-207 — canonical technique catalog cache. Loaded lazily on the
# first Match construction so unit tests that don't touch select_actions
# don't pay the YAML parse cost; subsequent matches share the cached
# dict. Passing an explicit `technique_catalog=` to Match() bypasses the
# cache (used by tests to inject narrow synthetic catalogs).
_CACHED_TECHNIQUE_CATALOG: Optional[dict] = None


def _load_default_technique_catalog() -> dict:
    """Lazy-load and cache the canonical catalog (data/techniques.yaml)."""
    global _CACHED_TECHNIQUE_CATALOG
    if _CACHED_TECHNIQUE_CATALOG is not None:
        return _CACHED_TECHNIQUE_CATALOG
    from pathlib import Path
    from technique_catalog import load_catalog
    # src/match.py → project root → data/techniques.yaml
    repo_root = Path(__file__).resolve().parent.parent
    catalog_path = repo_root / "data" / "techniques.yaml"
    if not catalog_path.exists():
        # Defensive: tests / partial checkouts without the data dir get an
        # empty catalog, which behaves as "Stage 1 always empty" — and the
        # legacy grip-presence gate is bypassed by the catalog_active flag
        # only when a non-None catalog is passed, so callers that rely on
        # legacy behavior should pass technique_catalog={} (or accept the
        # empty stage-1 set, which produces no commits).
        _CACHED_TECHNIQUE_CATALOG = {}
    else:
        _CACHED_TECHNIQUE_CATALOG = load_catalog(catalog_path)
    return _CACHED_TECHNIQUE_CATALOG


# HAJ-220 — ne-waza catalog cache. Same lazy-load pattern as the
# tachiwaza catalog above. Passing an explicit `ne_waza_catalog=` to
# Match() bypasses the cache.
_CACHED_NE_WAZA_CATALOG = None


def _load_default_ne_waza_catalog():
    """Lazy-load and cache the canonical ne-waza catalog
    (data/ne_waza_techniques.yaml + data/ne_waza_positions.yaml +
    data/defensive_struts.yaml). Returns None if any file is missing —
    callers will fall back to the legacy non-catalog ne-waza path."""
    global _CACHED_NE_WAZA_CATALOG
    if _CACHED_NE_WAZA_CATALOG is not None:
        return _CACHED_NE_WAZA_CATALOG
    from pathlib import Path
    from ne_waza_catalog import load_ne_waza_catalog
    repo_root = Path(__file__).resolve().parent.parent
    techniques_path = repo_root / "data" / "ne_waza_techniques.yaml"
    positions_path  = repo_root / "data" / "ne_waza_positions.yaml"
    struts_path     = repo_root / "data" / "defensive_struts.yaml"
    if not (techniques_path.exists() and positions_path.exists()
            and struts_path.exists()):
        return None
    _CACHED_NE_WAZA_CATALOG = load_ne_waza_catalog(
        techniques_path, positions_path, struts_path,
    )
    return _CACHED_NE_WAZA_CATALOG


# Engagement (Part 2.7): baseline floor; actual duration is max of
# reach_ticks_for(a) and reach_ticks_for(b), enforced from the graph.
#
# HAJ-141 — this floor is the closing-phase tick window. Both fighters
# begin a match (and every matte resume) in Position.STANDING_DISTANT
# with no edges. While distant, the action ladder issues REACH and the
# locomotion intent steps the dyad into engagement range; first grip
# seating is held off until the floor elapses. v0.1 calibration: 1 tick
# = 1 second, so 3 ticks ≈ "fighters spend 1–3 seconds closing distance
# before the first grip attempt" from the issue's real-match observation.
ENGAGEMENT_TICKS_FLOOR: int = 3

# HAJ-159 — STANDING_DISTANT seating distance. CoM-to-CoM at the start
# of every closing phase (match start + every matte / post-score reset).
# Roughly 2.5–3× the ~1 m engagement distance so the rendered separation
# is unambiguously distinguishable from the engaged pose. Closing-phase
# STEP_IN actions (action_selection._closing_step_action) cover the gap
# over the next few ticks at CLOSING_STEP_MAGNITUDE_M per fighter per
# tick, hitting engagement distance just as the reach-tick window
# completes and grips seat.
STANDING_DISTANT_SEPARATION_M: float = 3.0

# HAJ-164 follow-up — distance gate on grip seating. The pre-fix
# engagement resolver fired the grip cascade after ENGAGEMENT_TICKS_FLOOR
# ticks of mutual REACH regardless of actual CoM-to-CoM gap. With
# HAJ-163's BAIT_RETREAT and LATERAL_APPROACH variants in the closing-
# phase trajectory mix, two fighters could spend 3 ticks doing pure
# lateral / reverse motion and seat grips with 2 m+ still between them
# (visible in the seed-1 Tanaka vs Sato playthrough). Adding the gap
# check below keeps the spec invariant — "engagement means within
# arm's reach" — while letting the variant trajectories survive.
ENGAGEMENT_GRIP_SEAT_GAP_M: float = 1.2
# Safety upper bound on how many ticks the gap gate may delay grip
# seating. The closing-phase weights bias toward STEP_IN/CIRCLE_CLOSING
# at wide distances so this should rarely fire, but a hard ceiling
# protects against pathological seeds where both fighters pick lateral
# every tick. 8 ticks gives the closing-step machinery roughly 2.5×
# the nominal closing window — enough slack for any reasonable
# trajectory mix to traverse the 3 m starting gap before fallback.
ENGAGEMENT_GRIP_SEAT_TICKS_MAX: int = 8

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

# HAJ-149 — anticipation cost. Each tick a fighter is *actively
# perceiving* opponent intent — meaning the opponent emitted at least
# one IntentSignal this tick AND the perceiver chose a non-NONE response
# — drains a small amount of stamina. Per the spec, v0.1 punts on a
# separate "mental fatigue" axis and folds the cost into general cardio
# with a calibration tag for the v0.2 refactor (open question 4).
ANTICIPATION_CARDIO_COST: float = 0.0008

# HAJ-151 — disengage stamina cost. The disengage response combines the
# perception cost with a movement / posture-shift cost; v0.1 ships a
# slightly larger drain than the bare perception cost, calibrated so
# repeated disengages add up across a match without dominating the
# fatigue budget.
DISENGAGE_CARDIO_COST: float = 0.003

# HAJ-151 — disengage shido pressure. Three or more disengages without
# an intervening grip-seat in the same closing-phase span register as
# non-combativity; the ref's grip_initiative_strictness already governs
# the threshold for issuing a passivity shido — this constant is the
# count at which Match asks the ref to consider it.
DISENGAGE_SHIDO_THRESHOLD_COUNT: int = 3

# HAJ-149 — composure cost when an elite fighter has to abort or
# re-plan in response to a perceived interrupt. Scaffolded but not
# wired in v0.1 (selector re-run is HAJ-150 / HAJ-152 work); kept here
# so calibration stays co-located with the other anticipation knobs.
ANTICIPATION_COMPOSURE_COST: float = 0.005

# HAJ-128 — stance leash. Maximum distance a foot can be from the body's
# CoM. Throws, ne-waza transitions, and accumulated step drift can leave
# feet stranded far from the body; this leash snaps them back to a
# realistic stance offset every tick. ~half a hip width is a natural
# resting separation; 0.45 m is generous enough to allow open stances.
STANCE_LEASH_M: float = 0.45

# HAJ-139 — post-score recovery bonus. After a non-match-ending waza-ari
# (or downgraded NO_SCORE landing), both fighters reset to STANDING_DISTANT
# for the closing-phase pause, plus this many extra ticks of recovery so
# the post-throw beat (getting up, walking back near the mark, gi adjust)
# isn't compressed into a single tick. Total pause before next grip seat:
# ENGAGEMENT_TICKS_FLOOR + POST_SCORE_RECOVERY_TICKS ≈ 5 ticks.
POST_SCORE_RECOVERY_TICKS: int = 2

# HAJ-140 — stun applied to a stuffed aggressor regardless of whether the
# stuffed dispatch transitioned to ne-waza. Real judo: the stuffed fighter
# is on a knee or worse, and cannot fire another commit on the very next
# tick. Pre-fix the stuffed aggressor's `defensive_desperation` flag
# bypassed the empty-grip rung and produced eq=0.00 commits the same tick
# they were stuffed (HAJ-140 example log). Stun blocks action selection
# entirely (it's the rung-1 gate in select_actions) so even desperation
# can't push through. Tunes for ~3 ticks of recovery, slightly less than
# a typical FAILED throw's recovery (those are deeper compromises).
STUFFED_AGGRESSOR_STUN_TICKS: int = 3

# HAJ-127 / HAJ-128 — out-of-bounds boundary, IJF reference half-width.
#
# 4.0 m matches the IJF 8 × 8 m contest area, centered on the mat origin.
# HAJ-128 added autonomous locomotion (PRESSURE / DEFENSIVE_EDGE / HOLD_CENTER
# styles emit STEP actions), so fighters can actually traverse the contest
# area now — OOB no longer needs the tighter 1.5 m stop-gap.
MAT_HALF_WIDTH: float = 4.0

# HAJ-156 — edge-zone bookkeeping. EDGE_ZONE_M is the buffer width
# inside the contest boundary considered "near edge"; SAFE_ZONE_M is
# the central area where the time_in_edge_zone counter resets.
#
# The push-out shido fires when a retreating fighter (last STEP with
# tactical_intent=GIVE_GROUND) accumulates time_in_edge_zone past the
# referee's `mat_edge_strictness` threshold. A pressing fighter who
# shares the zone but was last advancing isn't penalised — the shido
# follows non-combativity, not proximity.
EDGE_ZONE_M: float = 0.75   # within this many meters of any boundary → "edge zone"
SAFE_ZONE_M: float = 1.5    # outside this many meters of every boundary → counter resets

# HAJ-160 / triage 2026-05-02 — number of ticks the simulator pauses
# between a Matte call and the symmetric Hajime restart. The matte
# banner sits on screen for the duration; the hajime banner fires when
# the pause expires. 3 ticks lets the matte beat breathe (and is the
# slot where coach instructions will land in a future altitude reader)
# before the dyad restarts.
#
# HAJ-221 banner gating invariant: this pause MUST be >= the referee's
# `BANNER_DURATION_TICKS`. The viewer reads each banner event's
# `banner_duration_ticks` field to know how long to hold the banner on
# screen; the matte→hajime pause guarantees the matte banner finishes
# displaying before the hajime banner runs, so the two never overlap.
# If you lower this, lower BANNER_DURATION_TICKS in referee.py too.
MATTE_TO_HAJIME_PAUSE_TICKS: int = 3

# HAJ-151 / triage 2026-05-02 (Priority 3) — number of ticks between the
# leader seating their grips and the follower's response resolving. The
# original 1-tick lag (= 1 s of game time at default settings) was too
# tight for the viewer to read as a sequenced cascade — the follower's
# grips landed almost on top of the leader's. 2 ticks gives the leader
# a visible beat of "ahead" before the follower cascade fires.
GRIP_CASCADE_LAG_TICKS: int = 2

# HAJ-224 — single-hand first grip. At engagement the leader seats only the
# lead (dominant-hand lapel) grip; the off-hand sleeve grip follows this many
# ticks later. The window in between is contestable — the follower's cascade
# response resolves at GRIP_CASCADE_LAG_TICKS (2), so a lag of 3 lets the
# follower interpose (strip the lead grip, seat their own) before the leader
# completes the two-handed grip. This lengthens and contests the grip war;
# most throws need sleeve+lapel, so a one-grip-at-a-time leader reaches
# commit-eligibility a beat slower.
OFF_HAND_SEAT_LAG_TICKS: int = 3

# HAJ-224 — strip force factor. The STRIP action delivers a force of
# `strip_resistance × STRIP_FORCE_FACTOR × grip_strength(stripper)`, competed
# against the owner's depth-scaled resistance in apply_strip_pressure. The
# old value (1.1) made full removal of a DEEP grip unreachable — overshoot
# vs a DEEP grip (depth modifier 1.0) at comparable grip strength was only
# ~1.1, a single step. Raising it lets a strong strip overshoot the margin
# model far enough to drop multiple steps or break a grip outright, while
# shallow grips (POCKET 0.4 / SLIPPING 0.2) tear off readily.
STRIP_FORCE_FACTOR: float = 1.3


def _grip_label_for(edge: "GripEdge") -> str:
    """HAJ-225 — short human label for a grip ('lapel' / 'sleeve' / 'collar'
    / 'belt' / ...), used in mat-side strip prose. Derives from the target
    location, falling back to a spaced-out form of whatever it is."""
    loc = edge.target_location.value
    if loc.endswith("lapel"):
        return "lapel"
    if loc.endswith("sleeve"):
        return "sleeve"
    if "collar" in loc:
        return "collar"
    if loc == "belt":
        return "belt"
    if loc.endswith("back_gi"):
        return "back"
    return loc.strip("_").replace("_", " ")


def is_out_of_bounds(judoka: Judoka) -> bool:
    """HAJ-127 — True when the fighter's CoM is outside the contest area.

    Uses |x| > half_width OR |y| > half_width (a square boundary). The
    contest area is centered on the mat origin per HAJ-124.
    """
    x, y = judoka.state.body_state.com_position
    return abs(x) > MAT_HALF_WIDTH or abs(y) > MAT_HALF_WIDTH


# HAJ-142 — graded mat regions (CENTER / WORKING / WARNING / OUT_OF_BOUNDS).
# Concentric bands defined as percentages of MAT_HALF_WIDTH on the same
# Chebyshev (square-mat) metric is_out_of_bounds uses, so the boundary
# semantics line up. The 30/70 split is interim — calibration in v0.2;
# bands widen automatically with MAT_HALF_WIDTH.
MAT_REGION_CENTER_FRAC:  float = 0.30
MAT_REGION_WARNING_FRAC: float = 0.70


def region_of(judoka: Judoka) -> "MatRegion":
    """HAJ-142 — return the named region for `judoka`'s current CoM.

    Pure function of position; recompute each tick. Square-mat geometry,
    so the metric is `max(|x|, |y|)` — same Chebyshev distance the OOB
    helper uses. Returns one of CENTER / WORKING / WARNING /
    OUT_OF_BOUNDS.
    """
    from enums import MatRegion as _MR
    x, y = judoka.state.body_state.com_position
    chebyshev = max(abs(x), abs(y))
    if chebyshev > MAT_HALF_WIDTH:
        return _MR.OUT_OF_BOUNDS
    if chebyshev <= MAT_HALF_WIDTH * MAT_REGION_CENTER_FRAC:
        return _MR.CENTER
    if chebyshev <= MAT_HALF_WIDTH * MAT_REGION_WARNING_FRAC:
        return _MR.WORKING
    return _MR.WARNING


def _distance_to_nearest_edge(com: tuple[float, float]) -> float:
    """HAJ-156 — meters from the CoM to the nearest contest boundary.
    Negative when the fighter is outside the boundary."""
    x, y = com
    return MAT_HALF_WIDTH - max(abs(x), abs(y))


def _spatial_mismatch_penalty(
    attacker: Judoka, defender: Judoka, td: "ThrowDef",
) -> float:
    """HAJ-156 — penalty applied to a throw's actual signature when
    the spatial conditions don't match the throw's preferred entry
    direction.

    ADVANCING (forward-loading hip throws): tori needs forward room.
    Pressed against the edge (within EDGE_ZONE_M and pointing at the
    edge with no opponent space) → 0.15 penalty.

    RETREATING_THEN_DRIVING (foot sweeps): tori needs to draw uke
    forward. Uke pressed against the edge with no room to be drawn
    further → 0.10 penalty.

    ADVANCING_LATERAL (reaping throws): minor side-room penalty when
    tori is in a corner (within EDGE_ZONE_M of two adjacent edges).

    DROPPING (sacrifice throws): no penalty — the throw drops in
    place; spatial conditions don't apply.
    """
    from throws import EntryDirection
    direction = getattr(td, "entry_direction", EntryDirection.ADVANCING)
    if direction == EntryDirection.DROPPING:
        return 0.0
    a_com = attacker.state.body_state.com_position
    d_com = defender.state.body_state.com_position
    a_edge = _distance_to_nearest_edge(a_com)
    d_edge = _distance_to_nearest_edge(d_com)
    if direction == EntryDirection.ADVANCING:
        # Tori at the edge: no forward room to step in. The penalty
        # bites when the attacker's edge proximity is small AND the
        # opponent is on the centre side (not pinned against the
        # opposite line where the attacker could still step in).
        if a_edge <= EDGE_ZONE_M:
            return 0.15
        return 0.0
    if direction == EntryDirection.RETREATING_THEN_DRIVING:
        # Uke already at the line: nowhere to draw them forward.
        if d_edge <= EDGE_ZONE_M:
            return 0.10
        return 0.0
    if direction == EntryDirection.ADVANCING_LATERAL:
        # Cornered tori loses lateral options. Detect by checking if
        # both axes put tori in the edge zone (i.e. inside a corner).
        ax, ay = a_com
        if (MAT_HALF_WIDTH - abs(ax) <= EDGE_ZONE_M
                and MAT_HALF_WIDTH - abs(ay) <= EDGE_ZONE_M):
            return 0.10
        return 0.0
    return 0.0


def _step_direction_sign(
    com_before: tuple[float, float], com_after: tuple[float, float],
) -> int:
    """HAJ-156 — classify a step's direction relative to the mat
    centre. Returns -1 if the step moved the fighter further from
    centre (retreating), +1 if it brought them closer (advancing),
    0 if the move was lateral / negligible."""
    bx, by = com_before
    ax, ay = com_after
    before_dist = (bx * bx + by * by) ** 0.5
    after_dist  = (ax * ax + ay * ay) ** 0.5
    delta = after_dist - before_dist
    if delta > 0.05:
        return -1
    if delta < -0.05:
        return +1
    return 0


def _off_balance_cause_suffix(source) -> str:
    """B-3 — map the dominant kuzushi source behind an off-balance beat to a
    short narration suffix, so the KUZUSHI_INDUCED prose can name the cause.
    Returns '' for an unknown / absent source (defensive)."""
    from kuzushi import KuzushiSource
    return {
        KuzushiSource.PULL:             " (pulled off balance)",
        KuzushiSource.FOOT_ATTACK:      " (swept off balance)",
        KuzushiSource.SELF_INFLICTED:   " (over-committed)",
        KuzushiSource.THROW_RESOLUTION: " (driven by the throw)",
    }.get(source, "")


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

# HAJ-74 — Golden-score cardio escalation. The match clock has run out, the
# fighters have already paid a full regulation's drain, and now every action
# costs more. Drain accelerates linearly with elapsed GS time on top of a
# baseline GS surcharge: at GS entry the multiplier is BASE; it ramps to
# BASE + RAMP over GOLDEN_SCORE_RAMP_TICKS. Conditioning shaves the
# acceleration: high cardio_efficiency (1..10, 5 = neutral) reduces the
# effective multiplier so a high-conditioned judoka burns through GS more
# slowly than a low-conditioned one. This is the v2 spec's "conditioning's
# contribution to decision-making escalates" knob.
GOLDEN_SCORE_CARDIO_BASE_MULT:   float = 1.5
GOLDEN_SCORE_CARDIO_RAMP_MULT:   float = 1.5   # plus base = 3.0x at full ramp
GOLDEN_SCORE_RAMP_TICKS:         int   = 120

# HAJ-234 — golden-score termination policy: a CAPPED window with an
# explicit decision/draw fallback (chosen over unlimited sudden death so the
# headless calibration harness always terminates deterministically). The
# window runs `GOLDEN_SCORE_MAX_TICKS` ticks from GOLDEN_SCORE_START; first
# score or third shido ends it earlier. The escalating cardio drain
# (`golden_score_cardio_multiplier`, full 3.0x ramp by tick 120) is what
# forces an organic decision well inside this window in practice — the cap is
# the backstop. If the window expires with scores still level, the match is
# decided on shido count (fewer shidos wins); a level shido count is a draw.
GOLDEN_SCORE_MAX_TICKS:          int   = 360


def golden_score_cardio_multiplier(
    elapsed_gs_ticks: int, cardio_efficiency: int = 5,
) -> float:
    """Linear escalation of cardio drain in golden score, conditioning-scaled.

    elapsed_gs_ticks is the number of ticks since GOLDEN_SCORE_START.
    cardio_efficiency is the 1..10 capability stat (5 = neutral).
    Returns 1.0 outside golden score (caller responsibility) — but for
    elapsed_gs_ticks >= 0 it always returns >= BASE so the caller should
    only invoke this when match.golden_score is True.
    """
    ramp = min(1.0, max(0.0, elapsed_gs_ticks / float(GOLDEN_SCORE_RAMP_TICKS)))
    raw = GOLDEN_SCORE_CARDIO_BASE_MULT + ramp * GOLDEN_SCORE_CARDIO_RAMP_MULT
    # Conditioning shave: efficiency 10 reduces the *surplus* over 1.0 by 50%;
    # efficiency 1 inflates it by 50%. Neutral 5 = no change.
    surplus = raw - 1.0
    eff_factor = 1.0 + (5 - cardio_efficiency) * 0.10
    return max(1.0, 1.0 + surplus * eff_factor)

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
# LOG STREAM SEPARATION (HAJ-65, HAJ-221)
# Two named streams share the same underlying tick events:
#   - "debug":  engineer-facing — tick numbers, physics variables, grip edge
#               transitions, execution_quality, failed_dimension, handles
#               (F#/G#/T#) from the debug inspector.
#   - "coach":  reader-facing, Neil-Adams-voice — narrative-first phrasing
#               with the technical term in parentheses, body-part narration
#               for throw resolution phases, no tick prefix, no debug
#               handles, and debug-only numerics like `(eq=…)` stripped.
#               Events may carry a `coach_prose` data field that overrides
#               the engineer-facing description when this stream renders.
# `_print_events` consults the active stream to decide what to emit.
#
# `"prose"` is kept as a legacy alias for `"coach"` so older test fixtures
# and CLI invocations continue to work; both map to the same render path.
# ---------------------------------------------------------------------------

VALID_STREAMS: frozenset[str] = frozenset({"debug", "prose", "coach", "both"})


def _is_coach_stream(stream: str) -> bool:
    """True for the reader-facing single-stream renders (HAJ-221).
    `"prose"` is the legacy spelling; `"coach"` is the HAJ-221 preferred
    name. Both produce the same output."""
    return stream in ("prose", "coach")

# Event types that belong only to the debug stream — grip edge churn, raw
# physics beats, and skill-compression sub-events. The prose stream drops
# these entirely; debug and both keep them.
_DEBUG_ONLY_EVENT_TYPES: frozenset[str] = frozenset({
    "GRIP_ESTABLISH",
    "GRIP_STRIPPED",
    "GRIP_DEGRADE",
    "GRIP_BREAK",
    "GRIP_DEEPEN",
    "GRIPS_RESET",
    "KUZUSHI_INDUCED",
    "THROW_ABORTED",
    "COUNTER_NULLIFIED",
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
# HAJ-221 — NARRATIVE-FIRST PROSE HELPERS
# Catalogued in the ticket: counter cognition, grip-cascade response,
# chase / defense decision, defensive-desperation entry. Each helper
# returns a coach-stream string that leads with the narrative and parks
# the engine-enum vocabulary in parentheses (sen-sen-no-sen, contest,
# scramble, etc.). Used to populate `event.data["coach_prose"]` at
# emission time; the engineer description stays in the original form
# so the debug stream and downstream log-parsing tooling keep their
# substrate hooks.
# ---------------------------------------------------------------------------
def _counter_coach_prose(
    defender_name: str, window: "CounterWindow", counter_throw_name: str,
) -> str:
    """Counter cognition rendered as narrative + parenthesised term."""
    from counter_windows import CounterWindow as _CW
    if window is _CW.SEN_SEN_NO_SEN:
        narrative = "sees the attack forming and strikes first"
        tag = "sen-sen-no-sen"
    elif window is _CW.SEN_NO_SEN:
        narrative = "times the attack and meets it head-on"
        tag = "sen-no-sen"
    elif window is _CW.GO_NO_SEN:
        narrative = "reacts to the attack and counters"
        tag = "go-no-sen"
    else:
        # NONE / unknown — fall back to the engineer phrasing.
        narrative = f"reads {window.name.lower()}"
        tag = window.name.lower()
    return (
        f"[counter] {defender_name} {narrative} ({tag}) — "
        f"{counter_throw_name}."
    )


_GRIP_CASCADE_COACH_PROSE: dict[str, str] = {
    "MATCH":      "{follower} matches {leader}'s grip exchange ({kind}).",
    "PURSUE_OWN": "{follower} ignores the grip war and reaches for "
                  "their own grip ({kind}).",
    "CONTEST":    "{follower} contests the grip ({kind}).",
    "DEFENSIVE":  "{follower} fights defensively for the grip ({kind}).",
    "DISENGAGE":  "{follower} backs off the grip exchange ({kind}).",
    "ACCEPT_BAIT": "{follower} lets {leader} keep the grip and loads a "
                   "counter off the committed arm ({kind}).",
}


def _grip_cascade_coach_prose(
    leader_name: str, follower_name: str, kind: str,
) -> str:
    template = _GRIP_CASCADE_COACH_PROSE.get(
        kind, "{follower} responds to {leader}'s grip ({kind}).",
    )
    return template.format(
        follower=follower_name, leader=leader_name, kind=kind,
    )


_CHASE_COACH_NARRATIVE: dict[str, str] = {
    "CHASE":           "chases the score to the ground",
    "DEFENSIVE_CHASE": "follows the throw down to defend on the bottom",
    "STAND":           "stands off after the score",
}


def _chase_coach_prose(tori_name: str, decision_name: str) -> str:
    narrative = _CHASE_COACH_NARRATIVE.get(
        decision_name, f"chooses {decision_name.lower()}",
    )
    return f"{tori_name} {narrative} ({decision_name})."


_DEFENSE_COACH_NARRATIVE: dict[str, str] = {
    "SCRAMBLE": "scrambles to avoid the follow-up",
    "TURTLE":   "rolls into turtle to deny the pin",
    "FRAME":    "frames out to keep tori off",
    "GUARD":    "drops into guard to break tori's posture",
    "DEFENSIVE_CHASE": "follows the throw down to defend on the bottom",
}


def _defense_coach_prose(uke_name: str, decision_name: str) -> str:
    narrative = _DEFENSE_COACH_NARRATIVE.get(
        decision_name, f"chooses {decision_name.lower()}",
    )
    return f"{uke_name} {narrative} ({decision_name})."


def _defensive_desperation_coach_prose(name: str) -> str:
    """Narrative-first replacement for the [state] pressure dump.
    Numeric breakdown stays in the engineer description and on
    event.data for the debug stream and downstream tooling."""
    return (
        f"{name} is overwhelmed — backing onto his heels, reading every "
        f"move (defensive desperation)."
    )


def _offensive_desperation_coach_prose(name: str) -> str:
    return (
        f"{name} is past the point of patience — composure broken, "
        f"clock ticking (offensive desperation)."
    )


# HAJ-221 — coach-stream snapshot of one judoka's composure + cardio
# state. Used by the post-Matte context line. Banded into a small set
# of phrases so the reader sees the state at a glance rather than a
# percentage. Calibration: composure fraction is relative to the ceiling
# the fighter started with (Capability.composure_ceiling); cardio is
# already in [0, 1] on the state.
_COMPOSURE_FRESH_FRAC:    float = 0.85
_COMPOSURE_WORKING_FRAC:  float = 0.55
_CARDIO_FRESH:            float = 0.85
_CARDIO_WORKING:          float = 0.55
_CARDIO_BREATHING:        float = 0.30


def _judoka_state_phrase(judoka: "Judoka") -> str:
    """One-clause coach-stream summary of a judoka's composure + cardio.
    Stays short so the matte context line reads as a single beat."""
    ceiling = max(1.0, float(judoka.capability.composure_ceiling))
    composure_frac = max(0.0, min(
        1.0, judoka.state.composure_current / ceiling,
    ))
    cardio = max(0.0, min(1.0, float(judoka.state.cardio_current)))
    if cardio < _CARDIO_BREATHING:
        return "is gasping for air"
    if composure_frac < 0.30:
        return "looks rattled"
    if cardio < _CARDIO_WORKING:
        return "is breathing hard"
    if composure_frac >= _COMPOSURE_FRESH_FRAC and cardio >= _CARDIO_FRESH:
        return "looks fresh"
    if composure_frac >= _COMPOSURE_WORKING_FRAC and cardio >= _CARDIO_WORKING:
        return "looks composed"
    return "is working"


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
    # HAJ-143 — multi-tick throw-execution window. `execution_ticks` is
    # the throw template's drive duration (1 = snap). `drive_vector` is
    # the total mat-frame displacement applied to uke across the window,
    # baked at commit so a defender rotation can't redirect mid-drive
    # (v0.1 — open question 3 on the ticket). `drive_ticks_consumed`
    # tracks how many drive ticks have already applied displacement, so
    # the per-tick application doesn't fire twice on the same beat.
    # `drive_prose_emitted` is a one-shot guard so an o-uchi drive line
    # doesn't spam ("Sato drives… Sato drives…"); ticket open question 4.
    execution_ticks:        int                    = 1
    drive_vector:           tuple[float, float]    = (0.0, 0.0)
    drive_ticks_consumed:   int                    = 0
    drive_prose_emitted:    bool                   = False

    def offset(self, current_tick: int) -> int:
        return current_tick - self.start_tick

    def is_last_tick(self, current_tick: int) -> bool:
        return self.offset(current_tick) >= self.compression_n - 1


# ---------------------------------------------------------------------------
# CONSEQUENCE QUEUE (HAJ-148)
#
# Causal tick ordering: a substantive action's consequences resolve on the
# *next* tick, not synchronously inside the same tick. Each entry is a
# scheduled effect with a due_tick; the resolver pulls due entries at the
# top of every tick before action selection runs.
#
# v0.1 effects:
#   - "RESOLVE_KAKE_N1" — N=1 throw outcome deferred from the commit
#     tick to the tick after KAKE_COMMIT (T+3 of the commit, post-HAJ-157).
#     Payload carries attacker_name, defender_name, throw_id; resolution
#     recomputes signature and runs _resolve_kake. The N=1 schedule
#     (RK+KA at T, TS at T+1, KC at T+2) is walked by
#     _advance_throws_in_progress; RESOLVE_KAKE_N1 fires the outcome on
#     the tick after KC.
#   - "NEWAZA_TRANSITION_AFTER_STUFF" — ne-waza door from a stuffed
#     standing throw. Payload carries attacker_name, defender_name; the
#     resolver runs _resolve_newaza_transition at the deferred tick.
#   - "POST_SCORE_DECISION" — HAJ-152 follow-up window. Fires the tick
#     after a non-match-ending waza-ari. Payload carries tori_name,
#     uke_name, throw_id, score_tick. Computes the chase + defense
#     decisions, emits the engineering events, and either dispatches
#     to ne-waza (CHASE / DEFENSIVE_CHASE) or queues
#     POST_SCORE_FOLLOW_UP_MATTE for a clean stand-and-reset.
#   - "POST_SCORE_FOLLOW_UP_MATTE" — HAJ-152. Explicit matte announcement
#     after a stand-and-reset follow-up. The matte event AND the
#     SCORE_RESET that resets the dyad fire from this consequence so
#     the log always carries a [ref] Matte! line before any reset
#     after a score (HAJ-152 AC#8).
#
# Multi-tick (N>1) throws stay on the existing _throws_in_progress path —
# they already separate commit and KAKE_COMMIT across ticks naturally.
# ---------------------------------------------------------------------------
@dataclass
class _Consequence:
    due_tick: int
    kind: str
    payload: dict


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
        regulation_ticks: Optional[int] = None,
        golden_score_ticks: Optional[int] = None,
        technique_catalog: Optional[dict] = None,
        ne_waza_catalog: Optional["object"] = None,
        debug_kuzushi: bool = False,
    ) -> None:
        if stream not in VALID_STREAMS:
            raise ValueError(
                f"stream must be one of {sorted(VALID_STREAMS)}, got {stream!r}"
            )
        self.fighter_a = fighter_a
        self.fighter_b = fighter_b
        self.referee   = referee
        self.max_ticks = max_ticks
        # HAJ-93 — regulation length is normally the whole match window
        # (legacy behaviour: max_ticks == regulation, no golden score room).
        # Tests that exercise golden score pass a smaller regulation_ticks
        # so the match clock has room to continue past the boundary.
        self.regulation_ticks = (
            regulation_ticks if regulation_ticks is not None else max_ticks
        )
        # HAJ-234 — length of the golden-score window, measured in ticks from
        # golden_score_start_tick. Bounds sudden death so the match always
        # terminates even if neither fighter scores; see GOLDEN_SCORE_MAX_TICKS.
        self.golden_score_ticks = (
            golden_score_ticks if golden_score_ticks is not None
            else GOLDEN_SCORE_MAX_TICKS
        )
        self.seed      = seed
        self._debug = debug
        self._stream = stream
        # HAJ-227 — dedicated kuzushi-buffer verbosity gate. The raw per-tick
        # `[kuzushi] buf` dump is a deep-debug readout, so it stays off even
        # the engineer (`debug`) stream unless explicitly opted into.
        self._debug_kuzushi = debug_kuzushi
        # HAJ-125 — optional viewer hook. None during normal/test runs.
        self._renderer = renderer
        if self._debug is not None:
            self._debug.bind_match(self)

        # HAJ-207 — technique catalog. When supplied (non-None), the
        # action selector consults stage1_available_techniques against
        # the catalog before committing throws. Default is None so
        # existing tests preserve the legacy grip-presence-gate commit
        # path; production entry points (run_match.py, main.py) opt in
        # by loading data/techniques.yaml and passing it through.
        self.technique_catalog = technique_catalog

        # HAJ-220 — ne-waza catalog. When supplied (non-None), the
        # NewazaResolver consults Stage 1 / Stage 2 against the catalog
        # so ground positions render with Kodokan-named techniques.
        # Default is None so existing tests preserve the legacy
        # hardcoded choke/armbar chain; production entry points
        # (run_match.py, main.py) opt in by loading the ne-waza catalog
        # files and passing them through.
        self.ne_waza_catalog = ne_waza_catalog

        # Match-level state
        self.grip_graph   = GripGraph()
        self.position     = Position.STANDING_DISTANT
        self.osaekomi     = OsaekomiClock()
        self.ne_waza_resolver = NewazaResolver()
        self.ne_waza_resolver.set_catalog(self.ne_waza_catalog)

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
        # win_method strings (see _end_match): "ippon", "two waza-ari",
        # "decision", "hansoku-make", "draw", "ippon (pin)",
        # "ippon (submission)", and golden-score variants
        # "waza-ari (golden score)", "ippon (golden score)",
        # "decision (golden score)" (HAJ-234 GS time-cap shido tiebreak).
        self.win_method: str = ""
        self.ticks_run   = 0
        # HAJ-93 — golden-score state. golden_score flips at the regulation
        # boundary when waza-ari counts are tied; once true, any waza-ari /
        # ippon scored ends the match (sudden death) and shidos continue
        # to accumulate from regulation toward hansoku-make.
        self.golden_score: bool = False
        self.golden_score_start_tick: Optional[int] = None

        # HAJ-160 — restart-hajime emission. Set to
        # (matte_tick + MATTE_TO_HAJIME_PAUSE_TICKS) when _handle_matte
        # fires, so a later tick opens with a HAJIME_CALLED event that
        # mirrors the match-start announcement at every restart. The
        # viewer's hajime banner reads off these events.
        # HAJ-235 — the engine now ALSO gates off this slot: every tick
        # strictly before _pending_hajime_tick is a freeze (no action
        # selection / grip / throw staging). The pause is no longer purely
        # cosmetic — it is the matte→hajime dead time.
        self._pending_hajime_tick: Optional[int] = None

        # HAJ-237 — the match clock stops at Matte and resumes at Hajime,
        # as in real judo. The loop tick (`ticks_run`) keeps advancing
        # through the matte→hajime freeze so the banner/render beat still
        # plays, but those freeze ticks are *dead time* that must not burn
        # regulation budget. This counter accumulates every freeze tick;
        # regulation time = ticks_run - _frozen_ticks. Display clocks and
        # the match-end check (is_done) read regulation time, so the clock
        # visibly holds during the pause and the fighters get the paused
        # seconds back. (Referee clock-pressure heuristics intentionally
        # stay on the raw contest tick — a 2-3 tick offset is immaterial to
        # them, and threading regulation time there would shift seeded
        # trajectories for no behavioral gain.)
        self._frozen_ticks: int = 0

        # HAJ-235 — pending penalty shido. Passivity/non-combativity
        # detection runs in the tick body (_update_grip_passivity,
        # _update_passivity) but the award is deferred to _post_tick so it
        # lands as a real-judo ceremony: matte → shido announcement →
        # hajime restart, reusing the _pending_hajime_tick freeze. Stores
        # {"fighter": Judoka, "reason": str}; at most one penalty is
        # bracketed per tick (one matte per stoppage).
        self._pending_penalty: Optional[dict] = None

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

        # HAJ-148 — causal tick ordering. The consequence queue defers the
        # resolution of substantive actions to a future tick (typically N+1)
        # so cause and effect occupy distinct ticks. Each tick's first phase
        # is RESOLVE_CONSEQUENCES — pull due entries, fire their effects,
        # before action selection runs. See _Consequence above.
        self._consequence_queue: list["_Consequence"] = []
        # Per-fighter "last tick a ladder substantive action fired" tracker.
        # The action gate consults this to suppress substantive ladder
        # actions on the very next tick (the consequence-resolution tick),
        # satisfying the rule that the consequence is the fighter's
        # substantive event on tick N+1, not a fresh ladder pick.
        self._last_substantive_tick: dict[str, int] = {
            fighter_a.identity.name: -10,
            fighter_b.identity.name: -10,
        }

        # HAJ-149 — perception substrate. Append-only log of intent
        # signals emitted this match (one entry per substantive-action
        # commit) and per-fighter perception bookkeeping read by the
        # reaction-lag math.
        self._intent_signals: list[IntentSignal] = []
        # HAJ-189 — viewer-facing per-tick force state. The dev
        # viewer (capture layer in src/viewer_capture.py) needs the
        # *requested*
        # (intent) and *delivered* (actual) force vector per fighter so
        # it can render the gray-vs-solid arrow grammar. Populated by
        # _compute_net_force_on each tick; reset at the top of every
        # tick by _reset_per_tick_force so a fighter who issues no
        # driving action this tick has zero vectors and the viewer's
        # arrows fade. Stored on Match (not on Judoka) because they're
        # tick-scoped diagnostic state, not gameplay state.
        self._intent_force: dict[str, tuple[float, float]] = {
            fighter_a.identity.name: (0.0, 0.0),
            fighter_b.identity.name: (0.0, 0.0),
        }
        self._actual_force: dict[str, tuple[float, float]] = {
            fighter_a.identity.name: (0.0, 0.0),
            fighter_b.identity.name: (0.0, 0.0),
        }
        # Familiarity counter — how many times each fighter has seen
        # the opponent commit each throw class. Feeds reaction_lag's
        # familiarity modulator so the second uchi-mata of a match is
        # easier to read than the first.
        self._throw_familiarity: dict[tuple[str, ThrowID], int] = {}
        # Per-fighter active brace flag. Set by the perception phase
        # when a fighter chooses BRACE; consumed by the resolution path
        # next tick to bump defender resistance. Cleared after read.
        self._brace_active: dict[str, bool] = {
            fighter_a.identity.name: False,
            fighter_b.identity.name: False,
        }
        # Append-only log of perception responses chosen this match.
        # Tests assert against this directly (the AC-required "decision
        # is logged" requirement from HAJ-149 §"Full selector re-run").
        self._perception_log: list[PerceptionResponse] = []

        # HAJ-151 — grip cascade state. Set when the engagement floor
        # elapses and a grip race is staged: leader has seated, follower
        # is choosing a response on the next tick. Cleared when the
        # follower's response resolves (response seats / disengages).
        # Schema:
        #   {"leader_name": str, "follower_name": str,
        #    "stage_tick": int,
        #    "leader_init": float, "follower_init": float,
        #    "stance_matchup": StanceMatchup,
        #    "clock_pressure_role_follower": Optional[str]}
        self._grip_cascade: Optional[dict] = None
        # HAJ-224 — pending off-hand seat for the cascade leader. Shape:
        #   {"leader_name": str, "follower_name": str, "seat_tick": int}
        # Set when the leader seats their lead grip; consumed when the tick
        # reaches seat_tick (off-hand sleeve grip seats then). Cleared if the
        # leader loses all grips (full strip / disengage) before it fires.
        self._pending_off_hand: Optional[dict] = None
        # Append-only log of grip-race decisions for tests / inspector.
        self._grip_cascade_log: list[dict] = []
        # Per-fighter intra-match grip-race wins/losses tally — feeds the
        # familiarity weight on subsequent initiative rolls.
        self._grip_familiarity: dict[str, int] = {
            fighter_a.identity.name: 0,
            fighter_b.identity.name: 0,
        }
        # Per-fighter disengage counter inside the current closing-phase
        # span. Cleared when a grip seats (engagement actually completed)
        # or a matte fires; incremented on each DISENGAGE response.
        self._disengage_streak: dict[str, int] = {
            fighter_a.identity.name: 0,
            fighter_b.identity.name: 0,
        }

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

        # HAJ-70 — tick-order discipline. Names of attackers (tori) whose
        # throw reached a LANDED_OR_SCORING resolution *this tick* — populated
        # in _apply_throw_result, reset at the top of _tick. Once tori's throw
        # has fully resolved (Step 11), any uke counter against that tori is
        # firing "too late": uke is already on the mat / the score is in. The
        # counter check (Step 11 fresh counters) and the consequence queue
        # (a counter staged on a prior tick whose commit is due now) both
        # consult this set and discard the late counter rather than letting it
        # compromise tori post-hoc.
        self._throws_resolved_this_tick: set[str] = set()

        # HAJ-152 — post-score follow-up state. None when no follow-up is
        # active; otherwise a dict carrying the scorer (tori), the
        # scored-on (uke), the throw_id, the score-tick, and the chase
        # decision once it's been computed. The follow-up window opens
        # the tick after a non-match-ending waza-ari and closes when a
        # matte fires (either the explicit POST_SCORE_FOLLOW_UP_END
        # matte after STAND, or the standard ne-waza patience matte
        # after a chase that stalls).
        self._post_score_follow_up: Optional[dict] = None

        # HAJ-145 — flat append-only log of every BodyPartEvent emitted this
        # match. Each engine event that goes through the decomposition layer
        # (commits, kuzushi attempts, counters, grip changes) extends this
        # list AND attaches its slice to the parent Event's `data["bpe"]`
        # so altitude readers can either iterate the flat stream or walk
        # source-event-grouped slices. This is the substrate the prose
        # layer (HAJ-147) reads from.
        self.body_part_events: list[BodyPartEvent] = []

        # HAJ-147 — mat-side narration layer. Two outputs:
        #   - tick log (existing Match events): full fidelity, debug.
        #   - match clock log (this list): editorial prose, sampled at
        #     match-clock granularity per the five promotion rules.
        # The narrator is a stateful filter over the BPE + Event streams;
        # we run it from _post_tick once both have stabilized for the
        # current tick.
        self._narrator = MatSideNarrator()
        self.match_clock_log: list[MatchClockEntry] = []

        # HAJ-144 acceptance #11 — altitude persistence stub. The Match
        # remembers which altitude the player chose to occupy. v0.1 always
        # defaults to MAT_SIDE; the Ring 2 attendance-choice mechanic
        # writes the field at match start. Re-reading a cornered match
        # from a higher-resolution altitude than the player chose is not
        # permitted (HAJ-144 part E persistence rule); the field bounds
        # what the prose layer is allowed to render.
        self.altitude_chosen: str = "MAT_SIDE"

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
    # HAJ-145 — BodyPartEvent emission helper
    # -----------------------------------------------------------------------
    def _attach_bpe(
        self, parent: Optional[Event], bpes: list[BodyPartEvent],
    ) -> None:
        """Append decomposed BodyPartEvents to the match-level log AND
        embed their dict form on the parent Event's `data["bpe"]` slot so
        altitude readers can group by source. Safe to call with parent=None
        (e.g. for source-events that aren't surfaced as Engine `Event`s in
        the visible log — kuzushi-buffer emissions, locomotion steps)."""
        if not bpes:
            return
        self.body_part_events.extend(bpes)
        if parent is not None:
            slot = parent.data.setdefault("bpe", [])
            for b in bpes:
                slot.append(b.to_dict())

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
        # HAJ-159 — push the dyad to the wider STANDING_DISTANT pose so
        # the rendered separation is visibly distant. Closing-phase
        # STEP_IN actions over the next few ticks cover the gap into
        # engagement distance — and emit MOVE events so the viewer
        # interpolates the closing motion instead of teleporting.
        self._seat_at_distant_pose()
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
        signal such as the viewer window closing).

        HAJ-234 — once golden score is live the regulation/max_ticks clock no
        longer bounds the match: sudden death runs until a score, a third
        shido, or the GS cap. `_resolve_golden_score_cap` ends the match (sets
        match_over) when the cap is reached, so the GS branch here is a
        backstop using the same threshold in case that check is ever skipped.

        HAJ-237 — regulation ends after `max_ticks` of *live* time, not raw
        loop ticks: the matte→hajime freeze ticks are dead time and don't
        count, so a match with one or more matte pauses runs that many extra
        loop ticks before time-up. This keeps the displayed clock honest —
        it reaches 0:00 exactly at time-up — and gives fighters back the
        seconds the clock was stopped for.
        """
        if self.match_over:
            return True
        if self.golden_score:
            if self.golden_score_start_tick is None:
                return False
            elapsed = self.ticks_run - self.golden_score_start_tick
            return elapsed >= self.golden_score_ticks
        return (self.ticks_run - self._frozen_ticks) >= self.max_ticks

    def _clock_remaining(self, abs_tick: int) -> int:
        """HAJ-237 — regulation ticks remaining at loop tick `abs_tick`.
        Regulation time excludes matte→hajime freeze ticks
        (`_frozen_ticks`), so the match clock holds during a pause and
        resumes afterward. Single source of truth for every displayed
        clock; rendering is live and in tick order, so the running
        `_frozen_ticks` total is correct for the tick being rendered.

        Returned signed (NOT clamped): `_format_match_clock` renders a
        negative as golden-score overtime ('+M:SS'), so clamping here
        would erase the GS clock."""
        return self.max_ticks - (abs_tick - self._frozen_ticks)

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

        # HAJ-189 — reset per-tick viewer-facing force vectors. Each
        # tick starts with both intent and actual at zero; if a fighter
        # issues a driving action this tick, _compute_net_force_on
        # populates them. A tick with no action leaves them at zero so
        # the viewer's arrows fade per spec.
        for name in self._intent_force:
            self._intent_force[name] = (0.0, 0.0)
            self._actual_force[name] = (0.0, 0.0)

        # HAJ-70 — clear the per-tick throw-resolution set before any
        # consequence or in-progress throw resolves this tick. A landing /
        # score later in this method re-populates it; the counter paths read
        # it to enforce tick-order discipline (a counter that lands after the
        # throw it answers has already scored is discarded).
        self._throws_resolved_this_tick.clear()

        # HAJ-160 — restart-hajime emission. Fires MATTE_TO_HAJIME_PAUSE_TICKS
        # after a matte resolved, marking the start of the next exchange so
        # the viewer's hajime banner mirrors the match-start announcement.
        # HAJ-235 — clearing the slot here is what un-freezes the dyad: the
        # freeze gate below tests `tick < _pending_hajime_tick`, so once this
        # runs (slot → None) the hajime tick proceeds with a full update and
        # fighters resume.
        if self._pending_hajime_tick == tick:
            events.append(self.referee.announce_hajime(tick))
            self._pending_hajime_tick = None

        # Background: fatigue drain + stun decay (Step 12 partial; we do it
        # first so action selection sees the up-to-date state).
        self._accumulate_base_fatigue(self.fighter_a)
        self._accumulate_base_fatigue(self.fighter_b)
        self._decay_stun(self.fighter_a)
        self._decay_stun(self.fighter_b)
        # HAJ-232 — tick down the post-switch stance settling window.
        self._decay_stance_settling(self.fighter_a)
        self._decay_stance_settling(self.fighter_b)

        # HAJ-148 phase 1 — RESOLVE_CONSEQUENCES. Fire any deferred effects
        # whose due_tick has arrived (N=1 throw landings, post-stuff ne-waza
        # door, etc.) before selectors run. This ensures cause and effect
        # occupy distinct ticks: the commit fired silently on tick N-1, the
        # outcome prose lands here on tick N as the visible beat.
        self._resolve_consequences(tick, events)
        if self.match_over:
            self._post_tick(tick, events)
            return

        # Ne-waza branches to the ground resolver; no standup physics this tick.
        # A consequence may have just dispatched the dyad to NE_WAZA (post-
        # stuff door), so this branch must run AFTER consequences resolve.
        if self.sub_loop_state == SubLoopState.NE_WAZA:
            self._tick_newaza(tick, events)
            self._post_tick(tick, events)
            return

        # HAJ-152 — post-score follow-up window pending. While the
        # chase decision has resolved to STAND and the explicit
        # POST_SCORE_FOLLOW_UP_MATTE consequence is queued, suppress
        # standing-phase action selection so neither fighter can fire
        # a fresh substantive action between the score and the matte.
        # The match clock keeps ticking; this just gates the ladder.
        if (self._post_score_follow_up is not None
                and self._post_score_follow_up.get("stage") == "STANDING"):
            self._post_tick(tick, events)
            return

        # HAJ-235 — matte→hajime freeze. On every tick strictly between a
        # Matte call and its paired Hajime restart the dyad is parked at
        # STANDING_DISTANT and neither fighter may act. _handle_matte sets
        # _pending_hajime_tick = matte_tick + MATTE_TO_HAJIME_PAUSE_TICKS;
        # the hajime tick itself clears that slot at the top of this method
        # (so it is NOT frozen — fighters resume on hajime). The window in
        # between is a render beat (the matte banner sits on screen, coach
        # prose lands), not live wrestling time. Suppressing the whole
        # standing update here is what stops the [move]/grip work the
        # post-223 log showed leaking into the t077-t078 gap.
        #
        # HAJ-237 — the match clock is stopped for this dead time. Count
        # the freeze tick BEFORE rendering so the clock the pause renders
        # with already reflects the hold (regulation time = ticks_run -
        # _frozen_ticks); the displayed clock therefore sits still across
        # the whole matte→hajime window and resumes on the hajime tick.
        if (self._pending_hajime_tick is not None
                and tick < self._pending_hajime_tick):
            self._frozen_ticks += 1
            self._post_tick(tick, events)
            return

        # ------------------------------------------------------------------
        # STANDING — Part 3 12-step update
        # ------------------------------------------------------------------

        # HAJ-146 — reset every active grip edge's `current_intent` to HOLD
        # at the top of each tick. The decompose layer will re-set the
        # intent for any grip touched this tick (REACH/DEEPEN/STRIP/PULL
        # action handlers). Edges untouched this tick fall back to HOLD
        # so the head-as-output computation only sees grips that are
        # *actively* steering right now.
        for _e in self.grip_graph.edges:
            _e.current_intent = "HOLD"
            _e.steer_direction = None

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

        # HAJ-232 — dynamic stance. Evaluate whether either fighter shifts
        # stance this tick (deliberately, or rotated off by grip pressure)
        # before action selection reads current_stance / the live matchup.
        self._evaluate_stance_switches(tick, events)

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
            current_tick=tick,
            position=self.position,
            golden_score=self.golden_score,
            catalog=self.technique_catalog,
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
            current_tick=tick,
            position=self.position,
            golden_score=self.golden_score,
            catalog=self.technique_catalog,
        )
        # A fighter mid-attempt must not re-commit — strip any COMMIT_THROW
        # the ladder re-proposes this tick.
        actions_a = self._strip_commits_if_in_progress(
            self.fighter_a.identity.name, actions_a,
        )
        actions_b = self._strip_commits_if_in_progress(
            self.fighter_b.identity.name, actions_b,
        )
        # HAJ-148 — substantive-action gate. A fighter whose previous-tick
        # ladder fired a substantive action (or whose consequence is
        # resolving this tick from the queue) cannot fire another
        # substantive ladder action this tick. Non-substantive actions
        # (HOLD_CONNECTIVE, FEINT, posture micro-adjustments, locomotion)
        # pass through.
        actions_a = self._gate_substantive_actions(
            self.fighter_a.identity.name, tick, actions_a,
        )
        actions_b = self._gate_substantive_actions(
            self.fighter_b.identity.name, tick, actions_b,
        )
        # Record what survived the gate so the next tick can read it.
        self._record_substantive_actions(
            self.fighter_a.identity.name, tick, actions_a,
        )
        self._record_substantive_actions(
            self.fighter_b.identity.name, tick, actions_b,
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
        net_grip_progress = self._coalesce_grip_oscillation(
            events, pre_tick_depths,
        )

        # If still pre-engagement (no edges) and both fighters issued REACH
        # this tick, accumulate engagement_ticks. Seat POCKET grips once the
        # slower fighter's belt-based reach completes.
        self._resolve_engagement(actions_a, actions_b, tick, events)

        # Steps 2-4 — force accumulation + Newton-3 application. Produces
        # per-fighter net force (2D) from all driving actions issued this tick.
        net_force_a = self._compute_net_force_on(
            victim=self.fighter_a, attacker=self.fighter_b, attacker_actions=actions_b,
            tick=tick,
        )
        net_force_b = self._compute_net_force_on(
            victim=self.fighter_b, attacker=self.fighter_a, attacker_actions=actions_a,
            tick=tick,
        )

        # Steps 5-7 — CoM velocity/position + trunk angle updates.
        self._apply_physics_update(self.fighter_a, net_force_a)
        self._apply_physics_update(self.fighter_b, net_force_b)

        # Step 8 — BoS update (STEP/SWEEP_LEG are v0.1 stubs).
        self._apply_body_actions(self.fighter_a, actions_a, tick=tick, events=events)
        self._apply_body_actions(self.fighter_b, actions_b, tick=tick, events=events)

        # HAJ-133 — FOOT_ATTACK family emits KuzushiEvents into uke's
        # buffer (parallel to PULL emission inside _compute_net_force_on).
        # Resolved after physics so the event's posture-vulnerability
        # term reads the just-updated CoM/trunk state.
        self._apply_foot_attacks(self.fighter_a, self.fighter_b, actions_a, tick)
        self._apply_foot_attacks(self.fighter_b, self.fighter_a, actions_b, tick)

        # HAJ-134 — open vulnerability windows on each fighter for the
        # actions they committed this tick. Windows are first-class data
        # consumed by counter_windows.actual_counter_window in the next
        # tick's counter check. Expired windows from prior ticks are
        # purged before opening new ones so the active list stays small.
        self._update_vulnerability_windows(self.fighter_a, actions_a, tick)
        self._update_vulnerability_windows(self.fighter_b, actions_b, tick)

        # HAJ-128 — re-aim each fighter's facing vector at the opponent
        # after motion. Real judoka stay squared up to each other; without
        # this, the facing arrow stays pinned at its Hajime-time direction
        # while the dot drifts around the mat.
        self._reorient_facing(self.fighter_a, self.fighter_b)
        self._reorient_facing(self.fighter_b, self.fighter_a)

        # HAJ-128 — keep feet attached to the body. Throws and ne-waza
        # transitions can leave feet stranded far from where the CoM ends
        # up; the stance leash pulls any over-extended foot back to a
        # natural stance offset under the body. Without this the viewer's
        # foot dots drift away from the fighter dots after a few exchanges.
        self._enforce_stance_leash(self.fighter_a)
        self._enforce_stance_leash(self.fighter_b)

        # Step 9 — kuzushi check (post-update state). B-3 rewire: reads the
        # decaying kuzushi buffer instead of the CoM-envelope predicate.
        # Returns the per-fighter off-balance booleans for the downstream
        # composure-drift and stalemate-counter consumers.
        a_kuzushi, b_kuzushi = self._check_off_balance(tick, events)

        # Steps 10 & 11 — compound COMMIT_THROW handling. HAJ-154 splits
        # this into two phases: a staging tick that fires the pre-commit
        # IntentSignal NOW (so the opposing fighter's perception system
        # has at least one tick of advance notice), and a follow-up tick
        # where a queued FIRE_COMMIT_FROM_INTENT consequence pops the
        # placeholder _ThrowInProgress entry and runs the real
        # _resolve_commit_throw.
        for actor, opp, acts in (
            (self.fighter_a, self.fighter_b, actions_a),
            (self.fighter_b, self.fighter_a, actions_b),
        ):
            for act in acts:
                if act.kind != ActionKind.COMMIT_THROW or act.throw_id is None:
                    continue
                staged = self._stage_commit_intent(actor, opp, act, tick)
                events.extend(staged)
                if self.match_over:
                    self._post_tick(tick, events)
                    return
                if self.sub_loop_state == SubLoopState.NE_WAZA:
                    self._post_tick(tick, events)
                    return

        # Step 12 — grip-edge fatigue/clock maintenance (Part 2.4-2.6).
        graph_events = self.grip_graph.tick_update(
            tick, self.fighter_a, self.fighter_b
        )
        events.extend(graph_events)

        # HAJ-146 — head-as-output. Each tick, after all grip / force /
        # commit processing, compute the head state of each fighter from
        # the set of opposing grips with current_intent==STEER. Head verbs
        # (DRIVING / DOWN / UP / TURNED) become outputs of the steering
        # control vector rather than self-initiated; when no opposing grip
        # is steering a fighter, no head event emits and the head reverts
        # to owner control. The substrate feeds HAJ-147 prose; no Engine
        # event is surfaced for the head state itself (it'd be very noisy
        # — every tick, every fighter under steer).
        self._attach_bpe(None, compute_head_state(
            self.fighter_a, self.grip_graph, tick,
            grasper_resolver=self._fighter_by_name,
        ))
        self._attach_bpe(None, compute_head_state(
            self.fighter_b, self.grip_graph, tick,
            grasper_resolver=self._fighter_by_name,
        ))

        # Composure drift from kuzushi states.
        self._update_composure_from_kuzushi(a_kuzushi, b_kuzushi)

        # Stalemate counter: increments on ticks with no kuzushi on either
        # fighter and no commit — referee Matte hinges on this.
        self._update_stalemate_counter(
            actions_a, actions_b, a_kuzushi, b_kuzushi,
            net_grip_progress=net_grip_progress,
        )

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

        # HAJ-149 — perception phase. After substantive actions have
        # fired and emitted their intent signals this tick, each
        # fighter's perception system reads the opposing fighter's
        # signals, samples a reaction lag (signed), and chooses a
        # response. v0.1 implements BRACE-for-N+1 as the concrete
        # response; INTERRUPT and REPLAN are scaffolded for follow-up.
        self._perception_phase(tick, events)

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

        # HAJ-156 — push-out shido bookkeeping. Update each fighter's
        # time_in_edge_zone counter against the current CoM position;
        # when a retreating fighter accumulates enough time in the
        # edge zone past the ref's `mat_edge_strictness` threshold,
        # fire a non-combativity shido. Runs every tick (cheap),
        # before the matte check so an OOB matte still wins priority.
        if self.sub_loop_state == SubLoopState.STANDING and not self.match_over:
            self._update_edge_zone_counters_and_shido(tick, events)

        # HAJ-235 — bracket a passivity / non-combativity shido detected in
        # the tick body. The award is a matte → shido announcement → hajime
        # ceremony (real judo) rather than an inline mid-exchange line. This
        # calls _handle_matte itself, so the standard matte check below sees
        # a freshly-reset dyad and won't double-fire (should_call_matte
        # returns None on a clean STANDING_DISTANT reset).
        if self._pending_penalty is not None and not self.match_over:
            self._award_pending_penalty(tick, events)

        # Referee: Matte?
        if not self.match_over:
            matte_reason = self.referee.should_call_matte(
                self._build_match_state(tick), tick
            )
            if matte_reason:
                matte_event = self.referee.announce_matte(matte_reason, tick)
                events.append(matte_event)
                # HAJ-221 — emit a one-line state snapshot of both judoka
                # right after the matte announcement. The composure /
                # stamina state at the reset gives the player a sense of
                # who's tiring without forcing them to track tick-by-tick.
                # This is coach-stream prose only; the engineering [ref]
                # MATTE_CALLED line above carries the substrate data.
                events.append(self._build_matte_context_event(tick))
                self._handle_matte(tick)

        # HAJ-93 — regulation-end gate. Once the match clock has run out
        # the regulation period, transition to golden score (if waza-ari
        # tied) or resolve by decision. Fires before narrator/print so
        # GOLDEN_SCORE_START / MATCH_ENDED show up in this tick's stream.
        # `golden_score` guards against re-firing every tick after entry.
        # HAJ-237 — measured in regulation time (matte→hajime freeze ticks
        # excluded) so the boundary lands exactly when the displayed clock
        # reaches 0:00, not a few freeze-ticks early. Mirrors is_done.
        if (not self.match_over
                and not self.golden_score
                and (tick - self._frozen_ticks) >= self.regulation_ticks):
            self._check_regulation_end(tick, events)

        # HAJ-234 — golden-score cap. Sudden death normally ends on a score
        # or third shido (those route through _end_match elsewhere). If the
        # GS window expires with the match still live, fall back to a decision
        # on shido count (or a draw if level). Fires after the regulation-end
        # gate so a fresh GOLDEN_SCORE_START tick never also trips the cap.
        if (not self.match_over
                and self.golden_score
                and self.golden_score_start_tick is not None
                and tick - self.golden_score_start_tick
                    >= self.golden_score_ticks):
            self._resolve_golden_score_cap(tick, events)

        # HAJ-147 — run the mat-side narrator over this tick's events +
        # BPE slice. The narrator filter applies the five promotion rules
        # and returns MatchClockEntry records; we extend the per-match
        # clock log AND surface each entry as an Event in the visible
        # stream so the existing print / viewer-ticker pipeline shows them
        # without further wiring. Engine event_type "MATCH_CLOCK" sits
        # outside _DEBUG_ONLY_EVENT_TYPES so it flows on both debug and
        # prose streams. Source-tag is preserved on Event.data for the
        # viewer's future altitude reader.
        # HAJ-144 acceptance #1 — attach a significance score (0-10) to
        # every event before the narrator runs. The narrator and the
        # other altitude readers filter the tick log by significance
        # threshold; without the score they can't decide what to render.
        for ev in events:
            eq = ev.data.get("execution_quality")
            recog = ev.data.get("recognition_score")
            ev.significance = significance_for(
                ev.event_type, execution_quality=eq, recognition=recog,
            )

        bpe_slice = [
            b for b in self.body_part_events if b.tick == tick
        ]
        clock_entries = self._narrator.consume_tick(
            tick, events, bpe_slice, self,
        )
        # Sources that ECHO an existing engine event (the narrator copied
        # ev.description verbatim) live only in match_clock_log — emitting
        # them as MATCH_CLOCK Events would duplicate the visible line.
        # Sources that are NEW prose (self-cancel detection, intent-
        # outcome gap, modifier reveal, phase transition, sampled summary)
        # surface as MATCH_CLOCK Events so the existing print / viewer-
        # ticker pipeline shows them without further wiring.
        # `desperation` is NOT in the echo set — we WANT the body-part
        # rewrite (HAJ-144 acceptance #13) to surface as a new line.
        _ECHO_SOURCES = frozenset({
            "throw", "counter", "score", "matte", "newaza", "grip_kill",
        })
        for entry in clock_entries:
            self.match_clock_log.append(entry)
            if entry.source in _ECHO_SOURCES:
                continue
            events.append(Event(
                tick=tick, event_type="MATCH_CLOCK",
                description=entry.prose,
                data={"source": entry.source,
                      "actors": list(entry.actors)},
            ))

        self._print_events(events)
        self._print_kuzushi_buffer_debug(tick)

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

        # HAJ-142 — CRAWL_TOWARD_BOUNDARY. The bottom fighter, under
        # threat (active pin, choke, or armbar) and within the WORKING
        # / WARNING bands, can deliberately drift toward the nearest
        # boundary as a defensive escape — out-of-bounds → Matte → pin
        # broken → reset. Probability scales with bottom's ne_waza
        # skill (a more savvy bottom uses geometry on purpose) and
        # how close they already are to the line.
        events.extend(self._maybe_crawl_toward_boundary(tick))

        # HAJ-129 — track stalemate during ne-waza so the referee's
        # NEWAZA_MATTE_TICKS window can fire. Pre-fix the counter was only
        # incremented in the standing path, so should_call_matte's
        # stalemate-ticks branch never tripped during ne-waza no matter
        # how long the fighters sat in a non-progressing position.
        # Progress = active sub/choke technique, active pin, or any tick
        # event that signals real movement: technique initiated, pin
        # started, submission landed, a FULL escape to standing.
        #
        # NOTE: COUNTER_ACTION ("partial success" shrimp/frame/hip-out) is
        # deliberately NOT progress. A bottom fighter half-escaping every
        # tick without changing position or advancing toward a score is the
        # exact stall the matte exists to break — counting those as progress
        # reset the counter every tick, so the threshold was never reached
        # and the referee never stood a deadlocked guard battle up (seed
        # 1148955923: ~360 ticks of partial-success escapes, no matte). A
        # full ESCAPE_SUCCESS still resets, since that genuinely ends the
        # ground exchange.
        progress_event_types = {
            "OSAEKOMI_BEGIN", "OSAEKOMI_BROKEN", "OSAEKOMI_TO_SUBMISSION",
            "SUBMISSION_VICTORY", "ESCAPE_SUCCESS",
        }
        had_progress_event = any(
            ev.event_type in progress_event_types
            or ev.event_type.endswith("_INITIATED")
            for ev in ne_events
        )
        active_progress = (
            self.ne_waza_resolver.active_technique is not None
            or self.osaekomi.active
        )
        if had_progress_event or active_progress:
            self.stalemate_ticks = 0
        else:
            self.stalemate_ticks += 1

        for ev in ne_events:
            if ev.event_type == "SUBMISSION_VICTORY":
                winner_name = ev.data.get("winner", "")
                winner = (self.fighter_a
                          if self.fighter_a.identity.name == winner_name
                          else self.fighter_b)
                # HAJ-93 — submission ends the match in regulation or
                # golden score; tag method so consumers can distinguish.
                method = (
                    "ippon (submission, golden score)" if self.golden_score
                    else "ippon (submission)"
                )
                self._end_match(winner, method, tick, events)
                return
            if ev.event_type == "ESCAPE_SUCCESS":
                # HAJ-185 — atomic ne-waza reset on escape so the next
                # standing engagement doesn't carry ghost state.
                self._reset_to_standing_after_newaza(tick)
                break
            if ev.event_type == "SUBMISSION_RELEASED":
                # HAJ-220 — catalog-mode submission abandoned after the
                # failed-effectiveness threshold. Reset the dyad through
                # the same recovery path escape takes; the SUBMISSION_RELEASED
                # event itself carries the "Matte" narrative cue.
                self._reset_to_standing_after_newaza(tick)
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
                # HAJ-145 — surface the reach as a BodyPartEvent. No engine
                # Event is emitted (REACH is per-tick noise in the visible
                # log), but the BPE feeds the substrate.
                target_loc = (act.target_location.value
                              if act.target_location else None)
                self._attach_bpe(
                    None,
                    decompose_reach(judoka, act.hand, target_loc, tick),
                )

            elif act.kind == ActionKind.DEEPEN and act.edge is not None:
                if act.edge in self.grip_graph.edges:
                    pre_depth = act.edge.depth_level
                    if self.grip_graph.deepen_grip(act.edge, judoka):
                        # HAJ-128 — surface successful grip-deepening so
                        # the ticker / prose log shows the grip war is
                        # alive across the whole match, not just at the
                        # initial engagement.
                        ev = Event(
                            tick=tick, event_type="GRIP_DEEPEN",
                            description=(
                                f"[grip] {judoka.identity.name} deepens "
                                f"{act.edge.grip_type_v2.name} → "
                                f"{act.edge.depth_level.name}"
                            ),
                            data={"edge_id": id(act.edge),
                                  "from": pre_depth.name,
                                  "to": act.edge.depth_level.name},
                        )
                        events.append(ev)
                        self._attach_bpe(ev, decompose_grip_deepen(
                            act.edge, pre_depth, judoka, tick,
                        ))

            elif act.kind == ActionKind.STRIP and act.edge is not None:
                if act.edge not in self.grip_graph.edges:
                    continue
                # Stripping force is a driving-class action issued by the
                # stripping hand; magnitude scales with grasper strength.
                strip_force = (
                    FORCE_ENVELOPES[act.edge.grip_type_v2].strip_resistance
                    * STRIP_FORCE_FACTOR * _grip_strength(judoka)
                )
                # Snapshot whether the edge was alive before the strip
                # call — apply_strip_pressure removes the edge when it
                # collapses entirely, so the post-call membership read
                # tells us success.
                target_edge = act.edge
                pre_alive = target_edge in self.grip_graph.edges
                result = self.grip_graph.apply_strip_pressure(
                    target_edge, strip_force, grasper=self._owner(target_edge),
                )
                if result is not None:
                    result.tick = tick
                    # HAJ-225 — enrich the strip event so the mat-side
                    # narrator can author a plain-language line (the engine
                    # description is the raw debug form). The stripper is the
                    # acting judoka; the owner is the grip-holder.
                    owner = self._owner(target_edge)
                    result.data["stripper"] = judoka.identity.name
                    result.data["owner"] = (
                        owner.identity.name if owner is not None else ""
                    )
                    result.data["grip_label"] = _grip_label_for(target_edge)
                    result.data["new_depth"] = target_edge.depth_level.name
                    events.append(result)
                    # Both a partial degrade and a full strip "had effect" —
                    # the BPE carries BREAK so the failed-strip narrator
                    # (SNAP-only) doesn't misread them as "can't budge it".
                    self._attach_bpe(result, decompose_grip_strip(
                        judoka, target_edge, tick, had_effect=True,
                    ))
                else:
                    # No mechanical effect — the grip held. No engine Event
                    # (the graph didn't change), but emit a failed-attempt
                    # BPE so the mat-side narrator can still read the attempt
                    # as the genuine "can't budge it" failure. HAJ-225.
                    self._attach_bpe(None, decompose_grip_strip(
                        judoka, target_edge, tick, had_effect=False,
                    ))

            elif act.kind == ActionKind.RELEASE and act.edge is not None:
                if act.edge in self.grip_graph.edges:
                    released_edge = act.edge
                    self.grip_graph.remove_edge(released_edge)
                    key = released_edge.grasper_part.value
                    if not key.startswith("__"):
                        ps = judoka.state.body.get(key)
                        if ps is not None:
                            ps.contact_state = _CS.FREE
                    # HAJ-145 — surface the release as a BodyPartEvent. No
                    # engine Event is emitted today; the BPE substrate feeds
                    # downstream readers.
                    self._attach_bpe(None, decompose_grip_release(
                        released_edge, judoka, tick,
                    ))

            elif act.kind == ActionKind.HOLD_CONNECTIVE and act.hand is not None:
                # Find any owned edge on this hand and ensure CONNECTIVE mode.
                for edge in self.grip_graph.edges_owned_by(judoka.identity.name):
                    if edge.grasper_part.value == act.hand:
                        edge.mode = GripMode.CONNECTIVE

    def _owner(self, edge: GripEdge) -> Judoka:
        return (self.fighter_a
                if edge.grasper_id == self.fighter_a.identity.name
                else self.fighter_b)

    def _coalesce_grip_oscillation(
        self, events: list[Event], pre_tick_depths: dict,
    ) -> bool:
        """Drop GRIP_DEEPEN and GRIP_DEGRADE events whose edge ended the tick
        at its pre-tick depth. HAJ-138 — both fighters deepen-then-strip each
        other every tick in the shallow-grips branch of the action ladder;
        each edge ends back at its starting depth. The pre-fix code dropped
        only the degrade events, so the log read like one-sided endless
        deepening ("Tanaka deepens LAPEL_HIGH → STANDARD" repeating for
        20+ ticks) when in fact nothing was changing. We now drop the deepen
        too — net-zero transitions produce no log line.

        Returns True if any GRIP_DEEPEN / GRIP_DEGRADE / GRIP_STRIPPED event
        survived after coalescing — i.e. real grip progress happened this
        tick. The caller feeds this into the stalemate counter so endless
        oscillation no longer prevents matte.
        """
        live_edges = {id(e): e for e in self.grip_graph.edges}
        filtered: list[Event] = []
        net_progress = False
        for ev in events:
            if ev.event_type not in ("GRIP_DEEPEN", "GRIP_DEGRADE"):
                if ev.event_type == "GRIP_STRIPPED":
                    net_progress = True
                filtered.append(ev)
                continue
            edge_id = ev.data.get("edge_id")
            edge = live_edges.get(edge_id) if edge_id is not None else None
            if edge is None:
                # Edge went away (force-break, stripped past SLIPPING) — keep
                # the event; it represents a real change.
                filtered.append(ev)
                net_progress = True
                continue
            pre = pre_tick_depths.get(edge_id)
            if pre is not None and edge.depth_level == pre:
                continue  # net-zero oscillation — drop both directions
            filtered.append(ev)
            net_progress = True
        events[:] = filtered
        return net_progress

    # -----------------------------------------------------------------------
    # ENGAGEMENT RESOLUTION — both fighters reaching, no edges → seat POCKETs
    # -----------------------------------------------------------------------
    def _resolve_engagement(
        self, actions_a: list[Action], actions_b: list[Action],
        tick: int, events: list[Event],
    ) -> None:
        # HAJ-224 — seat the leader's off-hand grip if its lag has elapsed.
        # Processed before the cascade early-return so it fires even while a
        # follower response is still pending.
        self._seat_pending_off_hand(tick, events)

        # HAJ-151 — if a grip cascade is staged from a previous tick, the
        # follower picks a response now; the closing-phase counter is
        # paused while we resolve the cascade. The cascade resolver
        # consumes _grip_cascade and may seat the follower's grips
        # (MATCH/PURSUE_OWN), only some of them (CONTEST), none (DEFENSIVE),
        # or transition both fighters back to STANDING_DISTANT (DISENGAGE).
        # Triage 2026-05-02 (Priority 3) — wait GRIP_CASCADE_LAG_TICKS
        # before the follower's response so the leader is visibly "ahead"
        # in the viewer instead of the cascade collapsing onto a single
        # tick.
        if self._grip_cascade is not None:
            stage_tick = self._grip_cascade.get("stage_tick", tick)
            if tick - stage_tick >= GRIP_CASCADE_LAG_TICKS:
                self._resolve_grip_cascade(tick, events)
            return

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

        # HAJ-164 follow-up — distance gate. Tick floor alone isn't
        # enough: HAJ-163's lateral / bait-retreat closing variants
        # don't close the dyad axis, so 3 ticks of mutual REACH can
        # still leave 2 m between fighters. Hold off the cascade
        # until the CoM gap is within engagement reach. Hard ceiling
        # at ENGAGEMENT_GRIP_SEAT_TICKS_MAX keeps the resolver from
        # livelocking on a pathological lateral-every-tick seed.
        if self.engagement_ticks < ENGAGEMENT_GRIP_SEAT_TICKS_MAX:
            ax, ay = self.fighter_a.state.body_state.com_position
            bx, by = self.fighter_b.state.body_state.com_position
            gap = ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5
            if gap > ENGAGEMENT_GRIP_SEAT_GAP_M:
                return

        # HAJ-151 — closing phase has elapsed; stage the grip cascade.
        # Compute initiative for both fighters; the higher score reaches
        # first (their grips seat now). The follower will choose a
        # response on the next tick.
        self.engagement_ticks = 0
        self._stage_grip_cascade(tick, events)

    # -----------------------------------------------------------------------
    # HAJ-151 — GRIP CASCADE STAGING + RESOLUTION
    # -----------------------------------------------------------------------
    def _seat_pending_off_hand(self, tick: int, events: list[Event]) -> None:
        """HAJ-224 — seat the cascade leader's off-hand (sleeve) grip once its
        lag has elapsed, completing the two-handed grip the leader began with
        a single lead grip. Drops the pending seat if the leader lost their
        lead grip in the meantime (fully stripped / disengaged) — there is no
        partial grip left to build on."""
        pending = self._pending_off_hand
        if pending is None:
            return
        if tick < pending["seat_tick"]:
            return
        self._pending_off_hand = None

        leader = self._fighter_by_name(pending["leader_name"])
        follower = self._fighter_by_name(pending["follower_name"])
        if leader is None or follower is None:
            return
        # If the leader has no surviving grips, the lead grip was broken
        # before the off-hand could follow — abandon the second beat.
        if not self.grip_graph.edges_owned_by(leader.identity.name):
            return
        # Don't double-seat if the off-hand somehow already gripped.
        for edge in self.grip_graph.edges_owned_by(leader.identity.name):
            if edge.grip_type_v2 == GripTypeV2.SLEEVE_HIGH:
                return

        new_edges = self._seat_grips_for(leader, follower, tick, hands="off")
        for edge in new_edges:
            ev = Event(
                tick=tick, event_type="GRIP_ESTABLISH",
                description=(
                    f"[grip] {edge.grasper_id} ({edge.grasper_part.value}) → "
                    f"{edge.target_id} ({edge.target_location.value}, "
                    f"{edge.grip_type_v2.name} @ {edge.depth_level.name})"
                ),
                data={"edge_id": id(edge), "from_grip_cascade": "leader_off_hand"},
            )
            events.append(ev)
            self._attach_bpe(
                ev, decompose_grip_establish(edge, leader, tick),
            )

    def _stage_grip_cascade(self, tick: int, events: list[Event]) -> None:
        """Compute initiative for both fighters, seat the leader's
        grips this tick, and stage the follower's response for tick+1.

        Per the spec: this is the opening grip exchange and also fires
        on every post-matte / post-stuff / post-disengage re-engagement.
        """
        rng_a = random.Random(
            f"haj151:init:{self.fighter_a.identity.name}:{self.seed}:{tick}"
        )
        rng_b = random.Random(
            f"haj151:init:{self.fighter_b.identity.name}:{self.seed}:{tick}"
        )
        matchup = self._compute_stance_matchup()
        a_role, b_role = clock_pressure_roles(
            self.fighter_a, self.fighter_b,
            current_tick=tick, max_ticks=self.max_ticks,
            a_score=self._a_score, b_score=self._b_score,
        )
        a_fam = self._grip_familiarity.get(self.fighter_a.identity.name, 0)
        b_fam = self._grip_familiarity.get(self.fighter_b.identity.name, 0)
        a_init = sample_initiative(
            self.fighter_a, self.fighter_b,
            stance_matchup=matchup,
            clock_pressure_role=a_role,
            familiarity_delta=a_fam - b_fam,
            rng=rng_a,
        )
        b_init = sample_initiative(
            self.fighter_b, self.fighter_a,
            stance_matchup=matchup,
            clock_pressure_role=b_role,
            familiarity_delta=b_fam - a_fam,
            rng=rng_b,
        )
        # HAJ-232 — hybrid stance switch cost. A fighter who has just switched
        # (settling window) or who is standing in a low-comfort stance reaches
        # more slowly; in MIRRORED, low kenka-yotsu comfort adds to it.
        a_init -= stance_mod.stance_initiative_penalty(self.fighter_a, matchup)
        b_init -= stance_mod.stance_initiative_penalty(self.fighter_b, matchup)
        if a_init >= b_init:
            leader, follower = self.fighter_a, self.fighter_b
            leader_init, follower_init = a_init, b_init
            follower_role = b_role
        else:
            leader, follower = self.fighter_b, self.fighter_a
            leader_init, follower_init = b_init, a_init
            follower_role = a_role

        # Engineering event — AC#1 verifiable via [grip_init] log.
        events.append(Event(
            tick=tick, event_type="GRIP_INITIATIVE",
            description=(
                f"[grip_init] {leader.identity.name} ({leader_init:+.2f}) "
                f"reaches first vs {follower.identity.name} "
                f"({follower_init:+.2f})"
            ),
            data={
                "leader": leader.identity.name,
                "follower": follower.identity.name,
                "leader_init": leader_init,
                "follower_init": follower_init,
                "stance_matchup": matchup.name,
                "clock_pressure_role_leader": (
                    a_role if leader is self.fighter_a else b_role
                ),
                "clock_pressure_role_follower": follower_role,
                "prose_silent": True,
            },
        ))

        # HAJ-224 — seat only the leader's LEAD grip now (dominant-hand
        # lapel). The off-hand sleeve follows OFF_HAND_SEAT_LAG_TICKS later,
        # leaving a contestable window in between. Pre-HAJ-224 this seated
        # both hands atomically, which read as an instantaneous double grip.
        #
        # HAJ-238 — in kenka-yotsu the leader may reach across for a CROSS or
        # clamp a PISTOL sleeve-cuff instead of the orthodox tsurite. The
        # election reads the live matchup + grip-war state; orthodox is the
        # heavy default (MATCHED always returns orthodox).
        lead_choice = self._elect_lead_grip(leader, follower, matchup, tick)
        new_edges = self._seat_grips_for(
            leader, follower, tick, hands="lead", lead_plan=lead_choice.plan,
        )
        self._emit_lead_grip_narration(leader, lead_choice, tick, events)
        for edge in new_edges:
            ev = Event(
                tick=tick, event_type="GRIP_ESTABLISH",
                description=(
                    f"[grip] {edge.grasper_id} ({edge.grasper_part.value}) → "
                    f"{edge.target_id} ({edge.target_location.value}, "
                    f"{edge.grip_type_v2.name} @ {edge.depth_level.name})"
                ),
                data={"edge_id": id(edge), "from_grip_cascade": "leader"},
            )
            events.append(ev)
            self._attach_bpe(
                ev, decompose_grip_establish(edge, leader, tick),
            )
        if new_edges:
            self.position = Position.GRIPPING
            # Schedule the off-hand (second beat) to follow.
            self._pending_off_hand = {
                "leader_name": leader.identity.name,
                "follower_name": follower.identity.name,
                "seat_tick": tick + OFF_HAND_SEAT_LAG_TICKS,
            }

        # Stage the follower's response for the next tick.
        self._grip_cascade = {
            "leader_name": leader.identity.name,
            "follower_name": follower.identity.name,
            "stage_tick": tick,
            "leader_init": leader_init,
            "follower_init": follower_init,
            "stance_matchup": matchup,
            "clock_pressure_role_follower": follower_role,
        }

    def _emit_grip_init_recompute(
        self, survivor: Judoka, attacker: Judoka,
        tick: int, events: list[Event],
    ) -> None:
        """HAJ-158 — recompute grip initiative after a FAILED / STUFFED
        throw resolution. Same scoring machinery as the opening cascade
        (`_stage_grip_cascade`); does NOT seat grips or stage a follower
        response — the grip graph is whatever the failure left it as,
        and this is a re-roll of who-would-reach-first if a grip-fight
        phase started now.
        The fresh score reads current fatigue / composure (so the post-
        failure composure dip on tori expresses on this initiative roll)
        and the familiarity counter, which is bumped by +1 for the
        survivor before sampling — uke scouted tori's preference by
        surviving the attack (HAJ-158 open question 2).
        """
        # Survivor of the failed attack scouted the attacker's preference;
        # bump familiarity before sampling so the recomputed score
        # reflects the freshly-incremented count.
        survivor_name = survivor.identity.name
        self._grip_familiarity[survivor_name] = (
            self._grip_familiarity.get(survivor_name, 0) + 1
        )
        rng_a = random.Random(
            f"haj158:recompute:{self.fighter_a.identity.name}:"
            f"{self.seed}:{tick}"
        )
        rng_b = random.Random(
            f"haj158:recompute:{self.fighter_b.identity.name}:"
            f"{self.seed}:{tick}"
        )
        matchup = self._compute_stance_matchup()
        a_role, b_role = clock_pressure_roles(
            self.fighter_a, self.fighter_b,
            current_tick=tick, max_ticks=self.max_ticks,
            a_score=self._a_score, b_score=self._b_score,
        )
        a_fam = self._grip_familiarity.get(self.fighter_a.identity.name, 0)
        b_fam = self._grip_familiarity.get(self.fighter_b.identity.name, 0)
        a_init = sample_initiative(
            self.fighter_a, self.fighter_b,
            stance_matchup=matchup,
            clock_pressure_role=a_role,
            familiarity_delta=a_fam - b_fam,
            rng=rng_a,
        )
        b_init = sample_initiative(
            self.fighter_b, self.fighter_a,
            stance_matchup=matchup,
            clock_pressure_role=b_role,
            familiarity_delta=b_fam - a_fam,
            rng=rng_b,
        )
        # HAJ-232 — stance switch cost on the post-failure initiative re-roll
        # too (a fighter still settling reaches slower here as well).
        a_init -= stance_mod.stance_initiative_penalty(self.fighter_a, matchup)
        b_init -= stance_mod.stance_initiative_penalty(self.fighter_b, matchup)
        if a_init >= b_init:
            leader, follower = self.fighter_a, self.fighter_b
            leader_init, follower_init = a_init, b_init
            leader_role, follower_role = a_role, b_role
        else:
            leader, follower = self.fighter_b, self.fighter_a
            leader_init, follower_init = b_init, a_init
            leader_role, follower_role = b_role, a_role
        events.append(Event(
            tick=tick, event_type="GRIP_INITIATIVE",
            description=(
                f"[grip_init] {leader.identity.name} ({leader_init:+.2f}) "
                f"reaches first vs {follower.identity.name} "
                f"({follower_init:+.2f})"
            ),
            data={
                "leader": leader.identity.name,
                "follower": follower.identity.name,
                "leader_init": leader_init,
                "follower_init": follower_init,
                "stance_matchup": matchup.name,
                "clock_pressure_role_leader": leader_role,
                "clock_pressure_role_follower": follower_role,
                "from_recompute": True,
                "survivor": survivor_name,
                "failed_attacker": attacker.identity.name,
                "prose_silent": True,
            },
        ))

    def _seat_grips_for(
        self, attacker: Judoka, defender: Judoka, tick: int,
        hands: str = "both",
        lead_plan: str = PLAN_ORTHODOX,
    ) -> list[GripEdge]:
        """Seat the standard sleeve-and-lapel grip pair for one fighter
        only. Mirrors grip_graph.attempt_engagement's per-fighter logic
        without the symmetric loop.

        HAJ-224 — `hands` selects which grips to seat:
          - "both" (default): lead lapel + off-hand sleeve, atomically.
          - "lead": dominant-hand lapel only (the first grip a leader wins).
          - "off":  off-hand sleeve only (the second beat, seated later).

        HAJ-238 — `lead_plan` (cross_grip.PLAN_*) chooses the *lead-hand* grip:
        the orthodox opposite-lapel tsurite (default), a CROSS reach across to
        the same-side lapel, or a PISTOL sleeve-cuff clamp. The off-hand sleeve
        is unchanged — the unconventional grip is the dominant-hand election.
        """
        from enums import DominantSide as _DS
        dom = attacker.identity.dominant_side
        is_right = dom == _DS.RIGHT
        target_name = defender.identity.name
        new_edges: list[GripEdge] = []

        if hands in ("both", "lead"):
            grip_v2, lapel_target, dom_hand_key = lead_grip_placement(
                lead_plan, dom,
            )
            dom_hand_part = (BodyPart.RIGHT_HAND if is_right
                             else BodyPart.LEFT_HAND)
            dom_strength  = min(
                1.0, attacker.effective_body_part(dom_hand_key) / 10.0,
            )
            new_edges.append(self.grip_graph._new_pocket_edge(
                attacker=attacker,
                grasper_part=dom_hand_part,
                target_id=target_name,
                target_location=lapel_target,
                grip_type_v2=grip_v2,
                strength=dom_strength,
                current_tick=tick,
            ))

        if hands in ("both", "off"):
            non_hand_part = (BodyPart.LEFT_HAND if is_right
                             else BodyPart.RIGHT_HAND)
            non_hand_key  = "left_hand" if is_right else "right_hand"
            sleeve_target = (GripTarget.RIGHT_SLEEVE if is_right
                             else GripTarget.LEFT_SLEEVE)
            non_strength  = min(
                1.0, attacker.effective_body_part(non_hand_key) / 10.0,
            )
            new_edges.append(self.grip_graph._new_pocket_edge(
                attacker=attacker,
                grasper_part=non_hand_part,
                target_id=target_name,
                target_location=sleeve_target,
                grip_type_v2=GripTypeV2.SLEEVE_HIGH,
                strength=non_strength,
                current_tick=tick,
            ))
        return new_edges

    # -----------------------------------------------------------------------
    # HAJ-238 — CROSS / PISTOL lead-grip election (kenka-yotsu)
    # -----------------------------------------------------------------------
    def _elect_lead_grip(
        self, fighter: Judoka, opponent: Judoka, matchup: StanceMatchup,
        tick: int,
    ):
        """Decide which lead-hand grip `fighter` reaches for — orthodox lapel,
        the cross, or a pistol sleeve-cuff — given the live kenka-yotsu matchup,
        how badly they're losing the grip war (the disruptor signal), and
        whether the opponent already holds an unconventional grip (the
        experienced-counter signal). Seeded off its own RNG stream so the
        election never perturbs initiative / response rolls."""
        grip_pressure = self.grip_graph.compute_grip_delta(
            opponent, fighter, matchup,
        )
        facing_unconventional = any(
            e.grip_type_v2.is_unconventional()
            for e in self.grip_graph.edges_owned_by(opponent.identity.name)
        )
        rng = random.Random(
            f"haj238:leadgrip:{fighter.identity.name}:{self.seed}:{tick}"
        )
        return select_lead_grip(
            fighter, opponent,
            matchup=matchup,
            grip_pressure=grip_pressure,
            facing_unconventional=facing_unconventional,
            rng=rng,
        )

    def _emit_lead_grip_narration(
        self, fighter: Judoka, choice, tick: int, events: list[Event],
    ) -> None:
        """Surface a kenka-yotsu lead-grip election as the CROSS_GRIP event
        (§4.3 narration family). Orthodox elections with no conversion are
        silent — the standard cascade prose already covers them."""
        if choice.plan == PLAN_ORTHODOX and not choice.converts:
            return
        prose = lead_grip_coach_prose(fighter.identity.name, choice)
        if prose is None:
            return
        tag = ""
        if choice.disruptor:
            tag = " (disruptor)"
        elif choice.converts:
            tag = " (converts)"
        events.append(Event(
            tick=tick, event_type="CROSS_GRIP",
            description=(
                f"[kenka] {fighter.identity.name} elects {choice.plan} grip{tag}"
            ),
            data={
                "fighter": fighter.identity.name,
                "plan": choice.plan,
                "disruptor": choice.disruptor,
                "converts": choice.converts,
                "prose_silent": True,
                "coach_prose": prose,
            },
        ))

    def _resolve_grip_cascade(self, tick: int, events: list[Event]) -> None:
        """Follower picks one of six responses. v0.1 mechanical outcomes:

          - MATCH: follower's standard grip pair seats (symmetric config).
          - PURSUE_OWN: same as MATCH for v0.1 (follower seats their own
            preferred grips); the strategic difference is that the
            follower didn't try to contest the leader. Cascade log
            distinguishes them.
          - CONTEST: follower seats only their dominant-hand lapel grip
            (the reach that intercepts the leader's lead grip path).
            Models the contested grip race; the second hand drops.
          - DEFENSIVE: no grips seat for the follower; they're framing.
          - DISENGAGE: leader's grips break, both transition to
            STANDING_DISTANT, closing-phase counter restarts. Follower
            absorbs the disengage stamina cost.
          - ACCEPT_BAIT (HAJ-226): the counter-fighter who deliberately
            does NOT strip or contest. The leader's grip is left standing;
            the follower seats a single grip on the leader's *committed*
            (lead-grip) arm — "give them the grip, take the reaction."

        Selection is probabilistic per HAJ-151 spec §"response types" —
        weights modulated by archetype, facets, fight_iq, composure,
        fatigue, perception specificity (proxied via the leader's
        disguise), and clock-pressure role.
        """
        cascade = self._grip_cascade
        if cascade is None:  # defensive — should be guarded by caller
            return
        leader = self._fighter_by_name(cascade["leader_name"])
        follower = self._fighter_by_name(cascade["follower_name"])
        if leader is None or follower is None:
            self._grip_cascade = None
            return

        rng = random.Random(
            f"haj151:resp:{follower.identity.name}:{self.seed}:{tick}"
        )
        # Perception specificity — high disguise → vague signal → safer
        # responses. Reuses the HAJ-149 disguise model.
        leader_disguise = disguise_for(leader)
        perception_specificity = max(0.0, min(1.0, 1.0 - leader_disguise))

        choice = select_response(
            follower, leader,
            stance_matchup=cascade["stance_matchup"],
            clock_pressure_role=cascade["clock_pressure_role_follower"],
            perception_specificity=perception_specificity,
            rng=rng,
        )

        # Log the decision for tests / inspector.
        log_entry = {
            "tick": tick,
            "leader": leader.identity.name,
            "follower": follower.identity.name,
            "kind": choice.kind,
            "weights": dict(choice.weights),
            "stance_matchup": cascade["stance_matchup"].name,
            "clock_pressure_role_follower": cascade["clock_pressure_role_follower"],
        }
        self._grip_cascade_log.append(log_entry)

        # Surface as engineering event. HAJ-221 — debug stream keeps the
        # `[grip_cascade] follower → KIND vs leader` form; coach stream
        # gets a narrative-first rendering via coach_prose.
        events.append(Event(
            tick=tick, event_type="GRIP_CASCADE_RESPONSE",
            description=(
                f"[grip_cascade] {follower.identity.name} → {choice.kind} "
                f"vs {leader.identity.name}"
            ),
            data={
                **log_entry,
                "prose_silent": True,
                "coach_prose": _grip_cascade_coach_prose(
                    leader.identity.name, follower.identity.name, choice.kind,
                ),
            },
        ))

        # Apply outcome.
        if choice.kind == RESP_DISENGAGE:
            self._apply_disengage_response(leader, follower, tick, events)
        else:
            self._apply_engaged_response(
                leader, follower, choice.kind, tick, events,
                matchup=cascade["stance_matchup"],
            )

        # Familiarity tally — leader "won" the lead grip race; follower
        # "lost" it (but disengage flips the win/loss because the
        # follower successfully denied the leader's plan).
        if choice.kind == RESP_DISENGAGE:
            self._grip_familiarity[follower.identity.name] = (
                self._grip_familiarity.get(follower.identity.name, 0) + 1
            )
            self._grip_familiarity[leader.identity.name] = (
                self._grip_familiarity.get(leader.identity.name, 0) - 1
            )
        else:
            self._grip_familiarity[leader.identity.name] = (
                self._grip_familiarity.get(leader.identity.name, 0) + 1
            )
            self._grip_familiarity[follower.identity.name] = (
                self._grip_familiarity.get(follower.identity.name, 0) - 1
            )

        self._grip_cascade = None

    def _apply_engaged_response(
        self, leader: Judoka, follower: Judoka, kind: str, tick: int,
        events: list[Event],
        matchup: StanceMatchup = StanceMatchup.MATCHED,
    ) -> None:
        """Apply MATCH / PURSUE_OWN / CONTEST / DEFENSIVE / ACCEPT_BAIT
        outcomes. Disengage is a sibling path — see _apply_disengage_response.

        HAJ-226 — ACCEPT_BAIT is the counter-fighter's accept-and-load: no
        leader edge is contested or stripped; the follower seats a single grip
        on the leader's committed (lead-grip) arm. It is the only engaged
        response that grips the leader's loaded arm rather than seating the
        follower's own offensive grip pair.

        HAJ-238 — in kenka-yotsu the follower's grip can go unconventional too:
        MATCH / PURSUE_OWN / CONTEST may seat a CROSS or PISTOL lead grip (the
        dominated follower's disruptor, or the skilled follower routing back to
        their preferred grip), and the DEFENSIVE frame can be a strip-resistant
        PISTOL sode-tori frame instead of the plain sleeve."""
        # Reset disengage streaks — engagement actually completed (or
        # at least the follower didn't disengage).
        self._disengage_streak[leader.identity.name] = 0
        self._disengage_streak[follower.identity.name] = 0

        if kind == RESP_DEFENSIVE:
            # Defensive frame — the follower seats their off-hand sleeve
            # grip only. Models the "hand on the bicep / sleeve frame"
            # posture from the spec: the lapel reach is denied (no
            # offensive grip), but the sleeve frame gives the follower
            # *some* defensive structure so leader can't fire throws
            # unopposed. v0.1 mechanical proxy for "posture broken
            # forward, A's kuzushi opportunities reduced."
            #
            # HAJ-238 — a kenka-yotsu-capable follower frames with a PISTOL
            # (sode-tori) clamp instead: strip-resistant, it denies the entry
            # without conceding the inside (§4.5 defensive role).
            from enums import DominantSide as _DS
            dom = follower.identity.dominant_side
            is_right = dom == _DS.RIGHT
            sleeve_part = (BodyPart.LEFT_HAND if is_right
                           else BodyPart.RIGHT_HAND)
            sleeve_key  = "left_hand" if is_right else "right_hand"
            sleeve_target = (GripTarget.RIGHT_SLEEVE if is_right
                             else GripTarget.LEFT_SLEEVE)
            sleeve_strength = min(
                1.0, follower.effective_body_part(sleeve_key) / 10.0,
            )
            frame_rng = random.Random(
                f"haj238:frame:{follower.identity.name}:{self.seed}:{tick}"
            )
            frame_grip = select_defensive_frame(
                follower, matchup=matchup, rng=frame_rng,
            )
            sleeve_edge = self.grip_graph._new_pocket_edge(
                attacker=follower,
                grasper_part=sleeve_part,
                target_id=leader.identity.name,
                target_location=sleeve_target,
                grip_type_v2=frame_grip,
                strength=sleeve_strength,
                current_tick=tick,
            )
            frame_prose = defensive_frame_coach_prose(
                follower.identity.name, frame_grip,
            )
            if frame_prose is not None:
                events.append(Event(
                    tick=tick, event_type="CROSS_GRIP",
                    description=(
                        f"[kenka] {follower.identity.name} frames with a "
                        f"{frame_grip.name} grip"
                    ),
                    data={
                        "fighter": follower.identity.name,
                        "plan": frame_grip.name,
                        "defensive_frame": True,
                        "prose_silent": True,
                        "coach_prose": frame_prose,
                    },
                ))
            ev = Event(
                tick=tick, event_type="GRIP_ESTABLISH",
                description=(
                    f"[grip] {sleeve_edge.grasper_id} "
                    f"({sleeve_edge.grasper_part.value}) → "
                    f"{sleeve_edge.target_id} "
                    f"({sleeve_edge.target_location.value}, "
                    f"{sleeve_edge.grip_type_v2.name} @ "
                    f"{sleeve_edge.depth_level.name})"
                ),
                data={"edge_id": id(sleeve_edge),
                      "from_grip_cascade": "follower",
                      "cascade_kind": kind},
            )
            events.append(ev)
            self._attach_bpe(
                ev, decompose_grip_establish(sleeve_edge, follower, tick),
            )
            return

        if kind == RESP_ACCEPT_BAIT:
            # HAJ-226 — accept-and-bait. The counter-fighter deliberately does
            # NOT strip or contest: the leader's lead grip is left standing
            # (two grips on you is the exposure a counter exploits). Instead
            # the follower clamps a single grip onto the leader's *committed*
            # arm — the dominant-side sleeve carrying the lead lapel grip —
            # setting up off that commitment. "Give them the grip, take the
            # reaction." No leader edge is touched; this is the only response
            # that seats its grip on the leader's loaded arm by design.
            from enums import DominantSide as _DS
            leader_is_right = leader.identity.dominant_side == _DS.RIGHT
            committed_sleeve = (GripTarget.RIGHT_SLEEVE if leader_is_right
                                else GripTarget.LEFT_SLEEVE)
            follower_is_right = follower.identity.dominant_side == _DS.RIGHT
            grasp_part = (BodyPart.RIGHT_HAND if follower_is_right
                          else BodyPart.LEFT_HAND)
            grasp_key  = "right_hand" if follower_is_right else "left_hand"
            grasp_strength = min(
                1.0, follower.effective_body_part(grasp_key) / 10.0,
            )
            bait_edge = self.grip_graph._new_pocket_edge(
                attacker=follower,
                grasper_part=grasp_part,
                target_id=leader.identity.name,
                target_location=committed_sleeve,
                grip_type_v2=GripTypeV2.SLEEVE_HIGH,
                strength=grasp_strength,
                current_tick=tick,
            )
            ev = Event(
                tick=tick, event_type="GRIP_ESTABLISH",
                description=(
                    f"[grip] {bait_edge.grasper_id} "
                    f"({bait_edge.grasper_part.value}) → "
                    f"{bait_edge.target_id} "
                    f"({bait_edge.target_location.value}, "
                    f"{bait_edge.grip_type_v2.name} @ "
                    f"{bait_edge.depth_level.name})"
                ),
                data={"edge_id": id(bait_edge),
                      "from_grip_cascade": "follower",
                      "cascade_kind": kind,
                      "accept_bait": True},
            )
            events.append(ev)
            self._attach_bpe(
                ev, decompose_grip_establish(bait_edge, follower, tick),
            )
            return

        # HAJ-238 — the follower's lead-grip election. The follower lost the
        # initiative race and the leader holds a grip, so the follower is the
        # *dominated* fighter here — the disruptor cross is theirs to throw, and
        # a skilled follower facing the leader's cross routes back to their
        # preferred grip (the `converts` flag).
        lead_choice = self._elect_lead_grip(follower, leader, matchup, tick)

        # MATCH / PURSUE_OWN seat the follower's full grip pair.
        new_edges: list[GripEdge] = []
        if kind in (RESP_MATCH, RESP_PURSUE_OWN):
            new_edges = self._seat_grips_for(
                follower, leader, tick, lead_plan=lead_choice.plan,
            )
        elif kind == RESP_CONTEST:
            # Contested race: follower's dominant-hand lead grip seats
            # (the reach that interposed on the leader's lead path);
            # the off-hand sleeve drop is dropped. The lead grip honors the
            # kenka-yotsu election — a contested cross is the disruptor reach.
            grip_v2, lapel_target, dom_hand_key = lead_grip_placement(
                lead_choice.plan, follower.identity.dominant_side,
            )
            from enums import DominantSide as _DS
            is_right = follower.identity.dominant_side == _DS.RIGHT
            dom_hand_part = (BodyPart.RIGHT_HAND if is_right
                             else BodyPart.LEFT_HAND)
            dom_strength  = min(
                1.0, follower.effective_body_part(dom_hand_key) / 10.0,
            )
            new_edges.append(self.grip_graph._new_pocket_edge(
                attacker=follower,
                grasper_part=dom_hand_part,
                target_id=leader.identity.name,
                target_location=lapel_target,
                grip_type_v2=grip_v2,
                strength=dom_strength,
                current_tick=tick,
            ))

        self._emit_lead_grip_narration(follower, lead_choice, tick, events)

        for edge in new_edges:
            ev = Event(
                tick=tick, event_type="GRIP_ESTABLISH",
                description=(
                    f"[grip] {edge.grasper_id} ({edge.grasper_part.value}) → "
                    f"{edge.target_id} ({edge.target_location.value}, "
                    f"{edge.grip_type_v2.name} @ {edge.depth_level.name})"
                ),
                data={"edge_id": id(edge),
                      "from_grip_cascade": "follower",
                      "cascade_kind": kind},
            )
            events.append(ev)
            self._attach_bpe(
                ev, decompose_grip_establish(edge, follower, tick),
            )

    def _apply_disengage_response(
        self, leader: Judoka, follower: Judoka, tick: int,
        events: list[Event],
    ) -> None:
        """DISENGAGE — break leader's grips, transition both fighters
        back to STANDING_DISTANT. The follower absorbs the movement +
        perception stamina cost. Repeated disengages without intervening
        engagement count toward non-combativity (ref shido pressure)."""
        # Drain stamina for the disengage move.
        follower.state.cardio_current = max(
            0.0, follower.state.cardio_current - DISENGAGE_CARDIO_COST,
        )
        # Increment streak for the disengaging fighter. Don't touch the
        # leader's streak — they may have been the disengager in a prior
        # cycle (and thus carry their own non-zero streak); only an
        # actual completed engagement (handled in _apply_engaged_response)
        # zeroes streaks.
        self._disengage_streak[follower.identity.name] = (
            self._disengage_streak.get(follower.identity.name, 0) + 1
        )

        events.append(Event(
            tick=tick, event_type="GRIP_DISENGAGE",
            description=(
                f"[disengage] {follower.identity.name} backsteps — "
                f"{leader.identity.name}'s reach finds empty space."
            ),
            data={
                "follower": follower.identity.name,
                "leader":   leader.identity.name,
                "streak":   self._disengage_streak[follower.identity.name],
            },
        ))

        # Repeated disengages register as non-combativity — surface
        # as an event the ref's passivity machinery can read. The
        # actual shido issue is handled by the ref's existing passivity
        # path (kumi_kata_clock + grip_initiative_strictness threshold);
        # this event is the engineering signal that the threshold may
        # need to fire.
        if (self._disengage_streak[follower.identity.name]
                >= DISENGAGE_SHIDO_THRESHOLD_COUNT):
            events.append(Event(
                tick=tick, event_type="DISENGAGE_NON_COMBATIVE",
                description=(
                    f"[ref] {follower.identity.name} — repeated disengages "
                    f"(streak {self._disengage_streak[follower.identity.name]})."
                ),
                data={
                    "fighter": follower.identity.name,
                    "streak":  self._disengage_streak[follower.identity.name],
                },
            ))
            # Bump kumi-kata clock toward the shido threshold; the
            # ref's existing passivity path takes it from there. We add
            # a moderate bump (not the full shido threshold) so the
            # disengage stream needs to keep up to actually draw.
            self.kumi_kata_clock[follower.identity.name] = (
                self.kumi_kata_clock.get(follower.identity.name, 0)
                + KUMI_KATA_SHIDO_TICKS // 4
            )

        # Break leader's grips and transition both to STANDING_DISTANT.
        # Re-engagement begins immediately under the existing closing-
        # phase logic (engagement_ticks rebuilds from zero).
        self.grip_graph.break_all_edges()
        # HAJ-224 — the leader's lead grip just broke; cancel any pending
        # off-hand seat so it doesn't materialize out of a disengaged dyad.
        self._pending_off_hand = None
        self.position = Position.STANDING_DISTANT
        self.engagement_ticks = 0

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
        tick: int = 0,
    ) -> tuple[float, float]:
        from force_envelope import (
            FORCE_ENVELOPES, grip_strength as _grip_strength,
        )
        from kuzushi import pull_kuzushi_event, record_kuzushi_event
        fx = fy = 0.0
        # HAJ-189 — viewer-facing force accumulators. Intent = sum of
        # requested force vectors over all driving actions this tick
        # (what the attacker is *trying* to apply, before envelope /
        # depth / fatigue scaling). Actual = sum of delivered vectors
        # (what they're *succeeding* at delivering — same as fx, fy).
        intent_fx = intent_fy = 0.0
        # HAJ-51 — read the current matchup once per call; per-edge multiplier
        # comes from FORCE_ENVELOPES[grip_type].stance_parity below.
        stance_matchup = self._compute_stance_matchup()

        for act in attacker_actions:
            if act.kind not in DRIVING_FORCE_KINDS or act.hand is None:
                continue
            if act.direction is None:
                continue
            # HAJ-189 — accumulate intent BEFORE the gate that requires
            # an active grip. The viewer wants to see "X is trying to
            # pull in this direction" even when the attempt fails to
            # deliver because no grip backs it.
            i_dx, i_dy = act.direction
            intent_fx += i_dx * float(act.magnitude)
            intent_fy += i_dy * float(act.magnitude)

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

            # HAJ-136 — pull self-cancellation. A novice pulling while
            # stepping into uke moves their base under the force vector
            # and loses delivered force; a high-skill fighter braces and
            # pulls clean. Apply only to PULL — PUSH/LIFT/COUPLE/FEINT
            # have different geometry and aren't covered by §13.8 yet.
            if act.kind == ActionKind.PULL:
                from kuzushi import pull_self_cancellation_factor
                cancel_factor = pull_self_cancellation_factor(
                    attacker, act.direction,
                )
                delivered *= cancel_factor

            dx, dy = act.direction
            fx += dx * delivered
            fy += dy * delivered

            # HAJ-131 — emit a KuzushiEvent into uke's buffer alongside the
            # continuous physical force above. Only PULL emits in this
            # ticket; FOOT_ATTACK joins in HAJ-133, PUSH/LIFT/COUPLE/FEINT
            # are deferred (they don't carry the same kuzushi semantics).
            if act.kind == ActionKind.PULL:
                event = pull_kuzushi_event(
                    attacker=attacker, edge=edge, victim=victim,
                    pull_direction=act.direction, current_tick=tick,
                )
                if event is not None:
                    record_kuzushi_event(victim, event)
                # HAJ-145 — body-part decomposition of the PULL. Carries
                # the pull direction so §13.8 self-cancel detection can
                # compose against base-step directions emitted by
                # _apply_body_actions.
                self._attach_bpe(None, decompose_pull(
                    attacker, edge, act.direction, act.magnitude, tick,
                ))

        # HAJ-189 — stash this tick's intent + actual vectors for the
        # anatomical viewer. The attacker is the one applying force;
        # arrows render off the *attacker's* CoM. (The victim's net
        # force on themselves is the inverse — but the spec's intent /
        # actual arrows are the attacker's narrative, not the victim's.)
        if attacker.identity.name in self._intent_force:
            cur_int = self._intent_force[attacker.identity.name]
            self._intent_force[attacker.identity.name] = (
                cur_int[0] + intent_fx, cur_int[1] + intent_fy,
            )
            cur_act = self._actual_force[attacker.identity.name]
            self._actual_force[attacker.identity.name] = (
                cur_act[0] + fx, cur_act[1] + fy,
            )

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
    def _enforce_stance_leash(self, judoka: Judoka) -> None:
        """HAJ-128 — clamp each foot to be within STANCE_LEASH_M of CoM.
        Snaps stranded feet (post-throw, post-ne-waza, post-displacement)
        back to a realistic stance offset. Feet that are already inside
        the leash are untouched, so normal step dynamics aren't perturbed."""
        bs = judoka.state.body_state
        cx, cy = bs.com_position
        for foot in (bs.foot_state_left, bs.foot_state_right):
            fx, fy = foot.position
            dx, dy = fx - cx, fy - cy
            dist = (dx * dx + dy * dy) ** 0.5
            if dist > STANCE_LEASH_M:
                scale = STANCE_LEASH_M / dist
                foot.position = (cx + dx * scale, cy + dy * scale)

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

    # -----------------------------------------------------------------------
    # STEP 8c — VULNERABILITY WINDOWS (HAJ-134)
    # -----------------------------------------------------------------------
    def _update_vulnerability_windows(
        self, judoka: Judoka, actions: list[Action], tick: int,
    ) -> None:
        """Purge expired windows and open new ones for declared actions.

        Per HAJ-134 spec, every committing action declares a window via
        vulnerability_window.WINDOW_DECLARATIONS. The window's orientation
        comes from the action's `direction` when present; for grip
        actions without an explicit direction (DEEPEN), we substitute
        the attacker's facing so uke's counter logic still gets a usable
        orientation read.
        """
        from vulnerability_window import (
            purge_expired_windows, open_window_for_action, window_spec_for,
        )
        purge_expired_windows(judoka, tick)
        facing = judoka.state.body_state.facing
        for act in actions:
            if window_spec_for(act.kind) is None:
                continue
            # For force/foot actions with a direction, _orientation_for
            # reads it directly. For grip actions (DEEPEN, STRIP) without
            # a direction, fall back to the attacker's facing.
            override = None
            if getattr(act, "direction", None) is None:
                override = facing
            open_window_for_action(
                judoka, act, current_tick=tick, orientation_override=override,
            )

    # -----------------------------------------------------------------------
    # STEP 8b — FOOT_ATTACK FAMILY (HAJ-133)
    # -----------------------------------------------------------------------
    def _apply_foot_attacks(
        self, attacker: Judoka, victim: Judoka,
        actions: list[Action], tick: int,
    ) -> None:
        """Emit a KuzushiEvent into uke's buffer for each FOOT_ATTACK
        action issued by the attacker this tick.

        Parallel to PULL's emission inside _compute_net_force_on. Foot
        attacks don't drive force through a grip envelope (they hit uke's
        base directly), so v0.1 only models the kuzushi-event side; a
        physics-side CoM perturbation is v0.2 work. Side effects beyond
        the event:
          - Small leg fatigue cost on the attacking foot (the sweep leg
            does work).
          - Cardio drain similar to STEP_CARDIO_COST.
        """
        from kuzushi import foot_attack_kuzushi_event, record_kuzushi_event

        for act in actions:
            if act.kind not in FOOT_ATTACK_KINDS:
                continue
            if act.foot is None or act.direction is None:
                continue
            event = foot_attack_kuzushi_event(
                attacker=attacker, victim=victim,
                action_kind=act.kind, attack_vector=act.direction,
                current_tick=tick, intensity=max(0.0, act.magnitude / 0.25),
                attacker_facing=attacker.state.body_state.facing,
            )
            if event is not None:
                record_kuzushi_event(victim, event)
            # HAJ-145 — body-part decomposition of the foot attack.
            self._attach_bpe(None, decompose_foot_attack(
                attacker, act.kind.name, act.foot, act.direction,
                act.magnitude, tick,
            ))
            # Leg + cardio cost. Modest — foot attacks are setups, not
            # commits. The leg doing the work pays a per-attack fatigue
            # bump; both fighters' general cardio dips slightly.
            leg_key = ("right_leg" if act.foot == "right_foot"
                       else "left_leg")
            attacker.state.body[leg_key].fatigue = min(
                1.0, attacker.state.body[leg_key].fatigue + 0.01,
            )
            attacker.state.cardio_current = max(
                0.0, attacker.state.cardio_current - STEP_CARDIO_COST,
            )

    def _apply_body_actions(
        self, judoka: Judoka, actions: list[Action], tick: int = 0,
        events: Optional[list[Event]] = None,
    ) -> None:
        """Apply STEP actions selected by the action ladder.

        HAJ-156 additions on top of HAJ-128's existing CoM advancement:
          - Step magnitude is scaled by the per-fighter `foot_speed`
            (with leg-fatigue, age, and posture modifiers) so fast
            fighters traverse the mat faster than slow ones.
          - A `[move]` engine event fires for each STEP. The event
            carries the tactical_intent label, the direction, the
            magnitude, and the before/after CoM positions so prose,
            viewer, and HAJ-149 perception can read what kind of step
            it was.
          - last_move_direction_sign is updated on the fighter's State
            so the post-tick edge-zone check can identify who was
            retreating when the push-out shido decision fires.
        """
        from action_selection import effective_step_magnitude
        for act in actions:
            if act.kind != ActionKind.STEP or act.foot is None or act.direction is None:
                continue
            bs = judoka.state.body_state
            foot = (bs.foot_state_right if act.foot == "right_foot"
                    else bs.foot_state_left)
            dx, dy = act.direction
            base_mag = max(0.0, act.magnitude)
            # HAJ-156 — scale by effective foot-speed (foot_speed +
            # leg-fatigue + age + stance modifiers). The action
            # selector already chose the base magnitude (e.g.
            # STEP_MAGNITUDE_M); this scales it so per-fighter speed
            # finally has a per-tick consequence.
            mag = effective_step_magnitude(judoka, base_mag)
            fx, fy = foot.position
            foot.position = (fx + dx * mag, fy + dy * mag)
            # HAJ-145 — emit a FEET-STEP body-part event. Direction carries
            # the base-step vector so §13.8 self-cancel detection can score
            # the dot product against same-tick HAND-PULL directions.
            self._attach_bpe(None, decompose_step(
                judoka, act.foot, act.direction, mag, tick,
            ))
            # HAJ-128 — tactical-step semantics. The fighter's center of
            # mass advances with the foot at half the step magnitude (one
            # tick = one weight-transfer phase, not a full body shift).
            # The OTHER foot trails behind at zero — natural rest stance
            # is restored by the next step. CoM movement is what makes
            # locomotion visible and what drives OOB / mat positioning.
            cx, cy = bs.com_position
            new_com = (cx + dx * mag * 0.5, cy + dy * mag * 0.5)
            bs.com_position = new_com
            # Small cardio cost: stepping spends fuel. Calibrated to be
            # noticeable across many ticks but not dominant.
            judoka.state.cardio_current = max(
                0.0, judoka.state.cardio_current - STEP_CARDIO_COST
            )
            # HAJ-156 — record the step's direction sign so the post-tick
            # edge-zone check knows which fighter was retreating when both
            # land in the edge zone simultaneously. Sign is computed
            # against the line-from-origin: a step away from center is
            # GIVE_GROUND-class (-1); a step toward center / opponent is
            # PRESSURE-class (+1). Lateral steps register as 0.
            judoka.state.last_move_direction_sign = _step_direction_sign(
                (cx, cy), new_com,
            )
            # HAJ-156 — emit a MOVE engine event. Surfaces the
            # tactical intent and the position delta so prose,
            # viewer, and the HAJ-149 perception layer can read what
            # the fighter just did spatially. Marked prose_silent
            # because v0.1 narration doesn't yet promote MOVE events;
            # the engineering stream still shows them.
            if events is not None:
                events.append(Event(
                    tick=tick,
                    event_type="MOVE",
                    description=(
                        f"[move] {judoka.identity.name} → "
                        f"{act.tactical_intent or 'step'} "
                        f"({mag:.2f} m, dir=({dx:+.2f}, {dy:+.2f}))."
                    ),
                    data={
                        "fighter":         judoka.identity.name,
                        "tactical_intent": act.tactical_intent,
                        "direction":       (dx, dy),
                        "magnitude":       mag,
                        "base_magnitude":  base_mag,
                        "com_before":      (cx, cy),
                        "com_after":       new_com,
                        "prose_silent":    True,
                    },
                ))

    # -----------------------------------------------------------------------
    # STEP 9 — KUZUSHI CHECK (B-3: buffer-driven off-balance signal)
    # -----------------------------------------------------------------------
    def _check_off_balance(
        self, tick: int, events: list[Event],
    ) -> tuple[bool, bool]:
        """Fire KUZUSHI_INDUCED and feed defensive pressure when a fighter's
        decaying kuzushi buffer magnitude crosses the off-balance threshold.

        B-3 — replaces the per-tick `is_kuzushi` CoM-envelope predicate with
        a read of the accumulated, decayed kuzushi buffer
        (`compromised_state`). Edge-triggered per fighter via
        `_*_was_kuzushi_last_tick`, so the beat fires on the tick the buffer
        first crosses OFF_BALANCE_MAGNITUDE_THRESHOLD, not every tick it stays
        above. The resultant (post-cancellation) magnitude is the trigger —
        mirroring the directional notion of the old predicate — and the
        dominant source + direction are surfaced on the event for narration.

        Returns the per-fighter off-balance booleans (a, b) so the caller can
        feed the downstream composure-drift and stalemate-counter consumers,
        which key off the same off-balance signal.
        """
        from kuzushi import compromised_state, OFF_BALANCE_MAGNITUDE_THRESHOLD
        a_cs = compromised_state(self.fighter_a.kuzushi_events, tick)
        b_cs = compromised_state(self.fighter_b.kuzushi_events, tick)
        a_kuzushi = a_cs.magnitude >= OFF_BALANCE_MAGNITUDE_THRESHOLD
        b_kuzushi = b_cs.magnitude >= OFF_BALANCE_MAGNITUDE_THRESHOLD
        if a_kuzushi and not self._a_was_kuzushi_last_tick:
            self._emit_kuzushi_induced(self.fighter_a, a_cs, tick, events)
        if b_kuzushi and not self._b_was_kuzushi_last_tick:
            self._emit_kuzushi_induced(self.fighter_b, b_cs, tick, events)
        self._a_was_kuzushi_last_tick = a_kuzushi
        self._b_was_kuzushi_last_tick = b_kuzushi
        return a_kuzushi, b_kuzushi

    def _emit_kuzushi_induced(
        self, fighter: Judoka, cs, tick: int, events: list[Event],
    ) -> None:
        """Append a KUZUSHI_INDUCED event for `fighter` and record the kuzushi
        tick on their defensive-pressure tracker. `cs` is the fighter's
        CompromisedState this tick; its dominant source names the cause."""
        from kuzushi import dominant_kuzushi_source
        src = dominant_kuzushi_source(fighter.kuzushi_events, tick)
        events.append(Event(
            tick=tick, event_type="KUZUSHI_INDUCED",
            description=(
                f"[physics] {fighter.identity.name} "
                f"off-balance{_off_balance_cause_suffix(src)}."
            ),
            data={
                "fighter":   fighter.identity.name,
                "magnitude": cs.magnitude,
                "vector":    cs.vector,
                "source":    src.name if src is not None else None,
            },
        ))
        self._defensive_pressure[fighter.identity.name].record_kuzushi(tick)

    # Final migration — the CoM-envelope off-balance predicate (the former
    # _is_kuzushi wrapper over body_state.is_kuzushi) is fully retired. The
    # decaying kuzushi buffer (_check_off_balance) is now the sole off-balance
    # / kuzushi signal in the engine. body_state.is_kuzushi and the
    # recoverable-envelope geometry remain defined (CoM math, still unit-
    # tested in test_body_state) but are no longer wired as a match signal.

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

        # HAJ-141 — engagement-distance gate. A fighter cannot commit a
        # throw while the dyad is still in STANDING_DISTANT (closing phase
        # before grips have seated). Defense in depth: the action ladder
        # already routes to REACH when own_edges is empty, but the
        # defensive-desperation flag bypasses that path. This gate stops
        # the bypass from firing throws out of thin air at match start /
        # post-matte before the closing phase has elapsed.
        #
        # The own-edges check makes the gate a true closing-phase check
        # (no grips → no contact → no throw geometry). Tests that seat
        # edges manually for direct-resolve coverage flow through; only
        # genuinely pre-engagement commits are denied.
        if (self.position == Position.STANDING_DISTANT
                and not self.grip_graph.edges_owned_by(attacker.identity.name)):
            return [Event(
                tick=tick,
                event_type="THROW_DENIED_DISTANT",
                description=(
                    f"[throw] {attacker.identity.name} commit denied — "
                    f"still closing distance (no engagement yet)."
                ),
                data={"attacker": attacker.identity.name,
                      "throw_id": throw_id.name,
                      "reason": "standing_distant"},
            )]

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

        actual = actual_signature_match(throw_id, attacker, defender, self.grip_graph,
                                        current_tick=tick)
        # HAJ-156 — spatial-mismatch kuzushi penalty. An ADVANCING
        # throw fired with tori pinned against the edge (no forward
        # room) loses signature quality; same for a
        # RETREATING_THEN_DRIVING throw with the opponent already at
        # the line and unable to be drawn forward. SACRIFICE / lateral
        # entries are spatially flexible and incur no penalty.
        td_for_entry = THROW_DEFS.get(throw_id)
        spatial_penalty = 0.0
        if td_for_entry is not None:
            spatial_penalty = _spatial_mismatch_penalty(
                attacker, defender, td_for_entry,
            )
            if spatial_penalty > 0.0:
                actual = max(0.0, actual - spatial_penalty)
        commit_threshold = commit_threshold_for(throw_id)
        eq = compute_execution_quality(actual, commit_threshold)
        n = compression_n_for(attacker, throw_id)
        schedule = sub_event_schedule(n)
        throw_name = THROW_REGISTRY[throw_id].name

        # HAJ-143 — bake the throw-execution window. Snap throws stay at
        # exec_ticks=1 / drive=(0,0); drive throws (o-uchi-gari, ko-uchi-gari,
        # tomoe-nage, etc.) get a non-zero drive vector pointing from
        # attacker toward defender so the per-tick displacement walks uke
        # along the line of force. Computed once at commit (open question
        # 3 — defender rotation can't redirect the drive in v0.1).
        from worked_throws import (
            execution_ticks_for as _exec_ticks_for,
            drive_distance_for as _drive_dist_for,
        )
        exec_ticks = _exec_ticks_for(throw_id)
        drive_dist = _drive_dist_for(throw_id)
        drive_vec: tuple[float, float] = (0.0, 0.0)
        if exec_ticks > 1 and drive_dist > 0.0:
            ax, ay = attacker.state.body_state.com_position
            dx, dy = defender.state.body_state.com_position
            ddx, ddy = dx - ax, dy - ay
            norm = (ddx * ddx + ddy * ddy) ** 0.5
            if norm > 1e-6:
                drive_vec = (
                    ddx / norm * drive_dist,
                    ddy / norm * drive_dist,
                )
            else:
                # Co-located fighters (degenerate test setup): fall back to
                # attacker's facing so the drive still has a direction.
                fx, fy = attacker.state.body_state.facing
                drive_vec = (fx * drive_dist, fy * drive_dist)

        # Passivity / attack-registration fires at commit start regardless of N.
        self._last_attack_tick[attacker.identity.name] = tick
        self.grip_graph.register_attack(attacker.identity.name)
        # Snapshot the kumi-kata clock before reset so Part 6.3 desperation
        # can evaluate against the pre-attack clock value.
        self._commit_kumi_kata_snapshot[attacker.identity.name] = (
            self.kumi_kata_clock.get(attacker.identity.name, 0)
        )
        self.kumi_kata_clock[attacker.identity.name] = 0

        # HAJ-157 V1/V5 — N=1 throws now spread across 4 ticks (RK/KA on T,
        # TS on T+1, KC on T+2, outcome on T+3) instead of collapsing onto
        # the THROW_ENTRY tick. Sub-events are visible on the debug stream
        # at every belt rank; the prose stream filters SUB_* events
        # generally (debug-only per _is_debug_only_event).
        collapse_n1 = False

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
        # HAJ-144 acceptance #5/#6 — recognition runs *after commit only*.
        # The commit-time score reads the kuzushi vector + grips + posture
        # state at the moment tori chose to fire; HAJ-148+ may refine the
        # score during throw resolution as state evolves.
        from worked_throws import worked_template_for as _worked_template_for
        _commit_template = _worked_template_for(throw_id)
        recog = (
            recognition_score(
                _commit_template, attacker, defender, self.grip_graph, tick,
            )
            if _commit_template is not None else 0.0
        )
        recog_band = recognition_band(recog)
        # HAJ-144 acceptance #6 — name lands at score only when recognition
        # is `most_clean` or `all_clean`. THROW_ENTRY itself reads as a
        # technique commit at all bands so the player sees what tori is
        # *doing*; the name vs no-name decision lives at the score line
        # (HAJ-147 prose composition for IPPON / WAZA_ARI).
        # HAJ-144 acceptance #10 — eq= moves to debug-only metadata.
        # The visible THROW_ENTRY line is now pure body-part prose at the
        # commit beat; the numeric execution_quality lives in Event.data
        # and surfaces through the debug stream (HAJ-65 _is_debug_only)
        # via the inspector handle suffix and the explicit `(eq=…)` parse
        # done by the debug renderer. Tags (desperation, gate-bypass,
        # commit-motivation) keep their visible parenthetical.
        entry_event = Event(
            tick=tick, event_type="THROW_ENTRY",
            description=(
                f"[throw] {attacker.identity.name} commits — {throw_name}.{tag_suffix}"
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
                # HAJ-144 acceptance #5/#6 — surface the recognition score
                # and band so altitude readers can decide whether the
                # technique name should land at the score line.
                "recognition_score": recog,
                "recognition_band":  recog_band,
                "name_lands":        name_lands_at(recog_band),
            },
        )
        events: list[Event] = [entry_event]

        # HAJ-148 — commits are silent in prose. The engineering THROW_ENTRY
        # event still fires for bookkeeping (debug stream, BPE substrate,
        # _scoring_events bookkeeping downstream); the prose layer suppresses
        # it via the prose_silent flag. The visible prose lands on the
        # resolution tick (N+1 for N=1, KAKE for N>1) as part of the
        # outcome line ("…drives in for o-uchi but Sato sprawls" etc.).
        entry_event.data["prose_silent"] = True

        # HAJ-149 / HAJ-154 — the pre-commit IntentSignal was emitted
        # one tick earlier by _stage_commit_intent (when the action
        # selector chose COMMIT_THROW). _resolve_commit_throw runs from
        # the FIRE_COMMIT_FROM_INTENT consequence, so the perception
        # window has already happened. Direct test calls into
        # _resolve_commit_throw bypass the staging layer; they get no
        # intent signal, which is the correct behavior for unit tests
        # that drive throw-resolution mechanics directly without the
        # full tick pipeline.

        # HAJ-145 — body-part decomposition of the commit. Walks the
        # worked-throw template's four signature dimensions and produces
        # the structured event sequence (hikite pull, tsurite pull, fulcrum
        # / reaping limb, hip beat, posture beat). Throws on the legacy
        # ThrowDef path (no worked template) skip decomposition; HAJ-29
        # backfilled all v0.1 throws so this is a defensive fallthrough.
        if _commit_template is not None:
            self._attach_bpe(entry_event, decompose_commit(
                attacker, defender, _commit_template, tick,
                overcommitted=offensive_desperation or defensive_desperation,
                source="COMMIT",
            ))

        # Emit tick-0 sub-events. HAJ-221 — thread throw_id + defender +
        # quality straight through so the coach-stream narration lookup
        # works even though `_throws_in_progress[attacker]` is set BELOW
        # (the tip hasn't landed yet on this first emit path).
        events.extend(self._emit_sub_events(
            attacker, throw_name, schedule.get(0, []), tick,
            silent=collapse_n1,
            throw_id=throw_id,
            defender=defender,
            commit_execution_quality=eq,
        ))

        if n <= 1:
            # HAJ-148 + HAJ-157 — defer the landing to tick+3. Pre-HAJ-148,
            # N=1 commits resolved on the same tick as the commit, bunching
            # cause and effect into one logical instant. HAJ-148 split the
            # outcome onto tick+1; HAJ-157 V1/V5 spreads the four sub-event
            # phases across distinct ticks too (RK+KA at T, TS at T+1, KC
            # at T+2) so the kuzushi → tsukuri → kake → outcome chain is
            # visible in the engine event log instead of collapsing.
            #
            # _advance_throws_in_progress walks the schedule for offsets
            # 1+ (TS, then KC); the RESOLVE_KAKE_N1 consequence queued
            # here for tick+3 is what actually fires the outcome and pops
            # the in-progress tip.
            self._throws_in_progress[attacker.identity.name] = _ThrowInProgress(
                attacker_name=attacker.identity.name,
                defender_name=defender.identity.name,
                throw_id=throw_id,
                start_tick=tick,
                compression_n=1,
                schedule=schedule,
                commit_actual=actual,
                commit_execution_quality=eq,
                execution_ticks=exec_ticks,
                drive_vector=drive_vec,
            )
            # HAJ-143 — drive throws push the resolution out by
            # (exec_ticks - 1) ticks beyond the HAJ-157 T+3 baseline.
            # Snap throws (exec_ticks=1) keep T+3; the per-tick drive
            # displacement during the wait is applied by
            # _advance_throws_in_progress.
            self._consequence_queue.append(_Consequence(
                due_tick=tick + 3 + (exec_ticks - 1),
                kind="RESOLVE_KAKE_N1",
                payload={
                    "attacker_name": attacker.identity.name,
                    "defender_name": defender.identity.name,
                    "throw_id": throw_id,
                },
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
            execution_ticks=exec_ticks,
            drive_vector=drive_vec,
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
            # Defensive: HAJ-129 / HAJ-140's other-fighter cleanup paths
            # can drop entries mid-iteration when one fighter's resolve
            # triggers ne-waza dispatch and clears the other fighter's
            # tip. Skip stale snapshot entries.
            if attacker_name not in self._throws_in_progress:
                continue
            offset = tip.offset(tick)
            if offset < 1:
                # First tick was handled by _resolve_commit_throw itself.
                continue

            attacker = self._fighter_by_name(attacker_name)
            defender = self._fighter_by_name(tip.defender_name)
            if attacker is None or defender is None:
                self._throws_in_progress.pop(attacker_name, None)
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
                if tip.compression_n <= 1:
                    # HAJ-157 V1/V5 — N=1 throws spread across 4 ticks. The
                    # outcome (LANDED / STUFFED / FAILED) was deferred to
                    # T+3 via the RESOLVE_KAKE_N1 consequence queued at
                    # commit time. The tip stays in _throws_in_progress
                    # until the consequence fires; that handler pops it.
                    # HAJ-143 — drive throws extend the wait further; the
                    # consequence due_tick was already pushed out at commit.
                    events.extend(self._apply_drive_step(
                        tip, defender, throw_name, tick,
                    ))
                    continue
                # HAJ-143 — N>1 drive throws defer resolution by
                # (execution_ticks - 1) ticks beyond KC, applying per-tick
                # COM displacement to uke during the wait. Snap throws
                # (execution_ticks=1) keep the inline _resolve_kake path.
                if tip.execution_ticks > 1:
                    # Apply the first drive step on the KC tick itself so
                    # the displacement is visible from beat one.
                    events.extend(self._apply_drive_step(
                        tip, defender, throw_name, tick,
                    ))
                    self._consequence_queue.append(_Consequence(
                        due_tick=tick + (tip.execution_ticks - 1),
                        kind="RESOLVE_DRIVE_THROW",
                        payload={
                            "attacker_name": attacker_name,
                            "defender_name": tip.defender_name,
                            "throw_id":      tip.throw_id,
                        },
                    ))
                    continue
                # Recompute signature at KAKE time — the match state has
                # changed over the attempt. resolve_throw uses the window
                # quality and is_forced flag derived from this fresh value.
                kake_actual = actual_signature_match(
                    tip.throw_id, attacker, defender, self.grip_graph,
                    current_tick=tick,
                )
                events.extend(self._resolve_kake(
                    attacker, defender, tip.throw_id, kake_actual, tick,
                ))
                self._throws_in_progress.pop(attacker_name, None)
                continue

            # HAJ-143 — post-KC drive ticks for both N=1 and N>1 paths.
            # The KC sub-event has already fired on a prior tick, the tip
            # is still in progress (resolution consequence pending), and
            # this is one of the (execution_ticks - 1) drive ticks. Apply
            # per-tick displacement and let the consequence resolve later.
            if tip.execution_ticks > 1 and self._is_in_drive_window(tip, tick):
                events.extend(self._apply_drive_step(
                    tip, defender, throw_name, tick,
                ))

        return events

    def _is_in_drive_window(
        self, tip: "_ThrowInProgress", tick: int,
    ) -> bool:
        """HAJ-143 — True when `tick` falls inside the post-KC drive window.

        The window opens on the KAKE_COMMIT tick and stays open for
        `execution_ticks - 1` more ticks. KC fires at offset
        `compression_n - 1` for N>1 throws (or offset 2 for N=1 per the
        HAJ-157 spread layout). The drive window therefore runs from
        that offset through to KC + (execution_ticks - 1).
        """
        if tip.execution_ticks <= 1:
            return False
        kc_offset = max(tip.compression_n - 1, 2 if tip.compression_n == 1 else 0)
        offset = tip.offset(tick)
        return kc_offset <= offset < kc_offset + tip.execution_ticks

    def _apply_drive_step(
        self,
        tip: "_ThrowInProgress",
        defender: Judoka,
        throw_name: str,
        tick: int,
    ) -> list[Event]:
        """HAJ-143 — emit the in-progress drive prose hook the first time a
        drive step fires.

        Per the Priority-1 regression fix from the t-007 / t-042 playthrough:
        COM displacement is no longer applied per-tick. A failed or stuffed
        drive throw shouldn't walk uke 2 m across the mat. The full
        `drive_vector` lands as a one-shot displacement at the resolution
        tick *only when the throw lands* (IPPON / WAZA_ARI), inside
        `_resolve_kake`. This function still ticks `drive_ticks_consumed`
        so the in-progress window tracks correctly and emits the prose
        once per drive throw (open question 4).
        """
        events: list[Event] = []
        if tip.execution_ticks <= 1:
            return events
        if tip.drive_ticks_consumed >= tip.execution_ticks:
            return events
        tip.drive_ticks_consumed += 1
        if not tip.drive_prose_emitted:
            events.append(Event(
                tick=tick,
                event_type="THROW_DRIVE",
                description=(
                    f"[throw] {tip.attacker_name} drives "
                    f"{tip.defender_name} on {throw_name}."
                ),
                data={
                    "attacker": tip.attacker_name,
                    "defender": tip.defender_name,
                    "throw_id": tip.throw_id.name,
                    "execution_ticks": tip.execution_ticks,
                    "drive_distance": (
                        tip.drive_vector[0] ** 2 + tip.drive_vector[1] ** 2
                    ) ** 0.5,
                },
            ))
            tip.drive_prose_emitted = True
        return events

    def _emit_sub_events(
        self, attacker: Judoka, throw_name: str,
        sub_events: list[SubEvent], tick: int,
        silent: bool = False,
        *,
        throw_id: Optional[ThrowID] = None,
        defender: Optional[Judoka] = None,
        commit_execution_quality: Optional[float] = None,
    ) -> list[Event]:
        # HAJ-144 acceptance #7 — sub-event lines no longer carry the
        # technique name by default. The reader stops seeing
        # "O-soto-gari: kuzushi / O-soto-gari: tsukuri / O-soto-gari: kake"
        # — the body-part decomposition (HAJ-145 / HAJ-146 / HAJ-147)
        # already conveys what tori is doing, and the name (when earned
        # by recognition) lands at score time. The throw_name is retained
        # in Event.data for downstream debug / inspector use.
        #
        # HAJ-221 — coach stream attaches a body-part narration line per
        # sub-event drawn from data/throw_narration.yaml. The debug
        # stream keeps the existing `[throw] tori — phase.` form for
        # internal calibration work. The look-up reads the in-progress
        # tip for throw_id + quality band; both are stable across all
        # ticks of an attempt. The coach_prose rides on the SUB_*
        # event's data so the coach-stream gate in _print_events
        # promotes the line even though SUB_* is otherwise debug-only.
        #
        # The optional `throw_id`, `defender`, `commit_execution_quality`
        # kwargs let callers that emit tick-0 sub-events BEFORE the tip is
        # stashed in `_throws_in_progress` (e.g. `_resolve_commit_throw`'s
        # initial call) thread the resolved values straight through so
        # the narration fallback doesn't see a missing tip and render a
        # literal "uke" placeholder.
        import throw_narration as _tn
        events: list[Event] = []
        tip = self._throws_in_progress.get(attacker.identity.name)
        if throw_id is None and tip is not None:
            throw_id = tip.throw_id
        if defender is None and tip is not None:
            defender = self._fighter_by_name(tip.defender_name)
        if commit_execution_quality is None and tip is not None:
            commit_execution_quality = tip.commit_execution_quality
        narration_data = (
            _tn.get_default_data() if not silent else {}
        )
        for sub in sub_events:
            label = SUB_EVENT_LABELS.get(sub, sub.name.lower())
            coach_prose = self._coach_prose_for_sub_event(
                sub, attacker, defender, tick,
                throw_id=throw_id,
                quality=commit_execution_quality,
                start_tick=(tip.start_tick if tip is not None else tick),
                data=narration_data,
            ) if not silent else None
            data: dict = {
                "sub_event": sub.name, "throw_name": throw_name,
                "silent": silent,
            }
            if coach_prose:
                data["coach_prose"] = coach_prose
            events.append(Event(
                tick=tick, event_type=f"SUB_{sub.name}",
                description=(
                    f"[throw] {attacker.identity.name} — {label}."
                ),
                data=data,
            ))
        # Part 6.2 region classification reads the most recent sub-event.
        if sub_events:
            tip = self._throws_in_progress.get(attacker.identity.name)
            if tip is not None:
                tip.last_sub_event = sub_events[-1]
        return events

    def _coach_prose_for_sub_event(
        self, sub: SubEvent,
        attacker: Judoka,
        defender: Optional[Judoka],
        tick: int,
        *,
        throw_id: Optional[ThrowID],
        quality: Optional[float],
        start_tick: int,
        data,
    ) -> Optional[str]:
        """Pick the coach-stream body-part line for a single sub-event.
        Returns None when the throw has no narration data and no generic
        fallback fires (callers gracefully drop the line in that case)."""
        from skill_compression import SubEvent as _SE
        import throw_narration as _tn
        _PHASE_BY_SUB: dict = {
            _SE.REACH_KUZUSHI:    _tn.PHASE_REACH_KUZUSHI,
            _SE.KUZUSHI_ACHIEVED: _tn.PHASE_KUZUSHI,
            _SE.TSUKURI:          _tn.PHASE_TSUKURI,
            _SE.KAKE_COMMIT:      _tn.PHASE_KAKE,
        }
        phase = _PHASE_BY_SUB.get(sub)
        if phase is None:
            return None
        seed_token = f"{self.seed}:{attacker.identity.name}:{start_tick}"
        # {tori}/{uke} placeholders in authored narration resolve to the
        # live fighter names so the lexicon stays matchup-stable (HAJ-223).
        uke_name = (
            defender.identity.name if defender is not None
            else (
                self.fighter_b.identity.name
                if attacker is self.fighter_a
                else self.fighter_a.identity.name
            )
        )
        tori_name = attacker.identity.name
        if throw_id is not None:
            line = _tn.select_phase_line(
                data, throw_id, phase,
                quality=quality, seed=seed_token,
            )
            if line:
                return _tn.render_line(line, tori=tori_name, uke=uke_name)
        # Generic fallback so an unauthored throw still produces a
        # coach line per HAJ-221 AC.
        return _tn.generic_phase_line(
            phase, tori=tori_name, uke=uke_name,
        )

    def _resolve_kake(
        self, attacker: Judoka, defender: Judoka, throw_id: ThrowID,
        actual: float, tick: int,
        *,
        drive_vector: tuple[float, float] = (0.0, 0.0),
    ) -> list[Event]:
        """Execute the KAKE_COMMIT resolution: resolve_throw + apply result.
        Factored out of _resolve_commit_throw so both N==1 and multi-tick
        paths share the same landing logic.

        Part 4.2.1 — eq is recomputed from the *kake-time* signature match so
        a multi-tick attempt that degrades between commit and kake reflects
        the worse execution in force transfer and landing severity.

        HAJ-143 — `drive_vector` carries the multi-tick throw's mat-frame
        displacement. Applied to uke as a one-shot only when the outcome
        lands (IPPON / WAZA_ARI). Failed/stuffed throws apply zero drive
        — uke didn't get walked across the mat because the throw didn't
        deliver. Default zero preserves snap-throw behavior.
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
        if outcome in ("IPPON", "WAZA_ARI") and (
            drive_vector[0] != 0.0 or drive_vector[1] != 0.0
        ):
            bs = defender.state.body_state
            cx, cy = bs.com_position
            bs.com_position = (cx + drive_vector[0], cy + drive_vector[1])
            # Fold the landing drive into uke's kuzushi buffer so a
            # continuing sequence reads the just-driven state through the same
            # decaying channel as every other source. Failed/snap throws apply
            # zero drive and emit nothing (builder returns None).
            from kuzushi import (
                throw_resolution_kuzushi_event, record_kuzushi_event,
            )
            drive_event = throw_resolution_kuzushi_event(
                defender, drive_vector, tick,
            )
            if drive_event is not None:
                record_kuzushi_event(defender, drive_event)
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
        # Defensive: HAJ-129 / HAJ-140's other-fighter cleanup paths can
        # already have removed the entry if a stuffed-throw ne-waza
        # dispatch fired earlier in the same _advance_throws_in_progress
        # snapshot iteration.
        self._throws_in_progress.pop(attacker.identity.name, None)
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

    # -----------------------------------------------------------------------
    # HAJ-148 — CONSEQUENCE QUEUE + ACTION GATE
    # -----------------------------------------------------------------------
    def _has_pending_consequence_for(self, fighter_name: str, tick: int) -> bool:
        """True if any queued consequence for `fighter_name` is due at or
        before `tick`. Used by the action gate to suppress substantive
        ladder actions on the consequence-resolution tick (AC#1)."""
        return any(
            c.due_tick <= tick and c.payload.get("attacker_name") == fighter_name
            for c in self._consequence_queue
        )

    def _gate_substantive_actions(
        self, fighter_name: str, tick: int, actions: list[Action],
    ) -> list[Action]:
        """HAJ-148 action gate.

        Strip substantive actions from the ladder when the fighter has a
        pending consequence due this tick — the queued resolution *is*
        their substantive event for the tick; the ladder cannot fire
        another on top of it. This is the testable invariant from AC#1
        for all consequence-bearing substantive actions (throw commit,
        stuff → ne-waza door).

        Non-consequence substantive actions (grip deepens, PULLs, REACH
        during the closing phase) pass through; gating them every tick
        breaks normal kumi-kata cadence and the engagement closing-phase
        floor without buying narrative coherence — those events do not
        bunch the way commits do.

        Non-substantive actions (HOLD_CONNECTIVE, FEINT, posture micro-
        adjustments, locomotion) always pass through untouched."""
        if self._has_pending_consequence_for(fighter_name, tick):
            return [a for a in actions if a.kind not in SUBSTANTIVE_KINDS]
        return actions

    def _record_substantive_actions(
        self, fighter_name: str, tick: int, actions: list[Action],
    ) -> None:
        """Mark the fighter as having taken a substantive ladder action on
        `tick` (kept on Match for downstream readers; the gate itself
        keys off the consequence queue, not this tracker)."""
        if any(a.kind in SUBSTANTIVE_KINDS for a in actions):
            self._last_substantive_tick[fighter_name] = tick

    def _resolve_consequences(self, tick: int, events: list[Event]) -> None:
        """HAJ-148 phase 1 (RESOLVE_CONSEQUENCES).

        Pull every consequence whose due_tick <= `tick`, fire its effect,
        and mutate world state. Runs at the top of _tick (after fatigue /
        stun, before action selection) so the consequence's events are
        the *first* substantive entries of the tick — the visible
        cause-and-outcome prose beat.
        """
        if not self._consequence_queue:
            return
        due = [c for c in self._consequence_queue if c.due_tick <= tick]
        self._consequence_queue = [
            c for c in self._consequence_queue if c.due_tick > tick
        ]
        for c in due:
            self._fire_consequence(c, tick, events)
            if self.match_over:
                return

    # -----------------------------------------------------------------------
    # HAJ-149 — INTENT SIGNALS + PERCEPTION PHASE
    # -----------------------------------------------------------------------
    def _emit_intent_signal(
        self, fighter: Judoka, setup_class: str, tick: int,
        events: list[Event], *,
        throw_id: Optional[ThrowID] = None,
        source_event_type: Optional[str] = None,
        specificity: float = 0.5,
    ) -> None:
        """Emit a non-substantive IntentSignal for `fighter`'s setup.

        Intent signals are observable by the opposing fighter's
        perception system in the same tick they fire. v0.1 emits at
        the commit tick (the deferred-resolution gap from HAJ-148 is
        the perception window); the spec calls for N−2 / N−1
        anticipation signals, which require a planning-ahead selector
        rewrite that v0.1 punts on.
        """
        sig = IntentSignal(
            tick=tick,
            fighter=fighter.identity.name,
            setup_class=setup_class,
            throw_id=throw_id,
            specificity=specificity,
            disguise=disguise_for(fighter),
            source_event_type=source_event_type,
        )
        self._intent_signals.append(sig)
        # Also surface as a low-significance engineering event so the
        # debug stream / inspector can see the intent stream. The prose
        # stream skips it via prose_silent (intent signals are an
        # engineering substrate, not narrative beats — HAJ-153 will
        # author the prose layer that consumes them).
        ev = Event(
            tick=tick, event_type="INTENT_SIGNAL",
            description=(
                f"[intent] {fighter.identity.name} → {setup_class}"
                + (f" ({throw_id.name})" if throw_id is not None else "")
            ),
            data={
                "fighter": fighter.identity.name,
                "setup_class": setup_class,
                "throw_id": throw_id.name if throw_id is not None else None,
                "specificity": specificity,
                "disguise": sig.disguise,
                "prose_silent": True,
            },
        )
        events.append(ev)

    def _bump_familiarity(self, perceiver: Judoka, throw_id: ThrowID) -> None:
        """Increment the perceiver's intra-match familiarity with the
        attacker's throw — feeds reaction_lag's familiarity modulator
        on subsequent commits of the same throw class."""
        key = (perceiver.identity.name, throw_id)
        self._throw_familiarity[key] = self._throw_familiarity.get(key, 0) + 1

    def _perception_phase(self, tick: int, events: list[Event]) -> None:
        """HAJ-149 phase 3 sub-step. For each intent signal emitted on
        this tick, the *opposing* fighter's perception system samples a
        reaction lag (signed) and chooses a response (BRACE / NONE in
        v0.1; INTERRUPT and REPLAN scaffolded for HAJ-150 / HAJ-152).

        Active perception (any non-NONE response) costs a small amount
        of cardio — ANTICIPATION_CARDIO_COST per perception event. The
        cost folds into the general cardio pool for v0.1; v0.2 refactors
        this onto a separate mental-fatigue axis (open question 4).
        """
        if not self._intent_signals:
            return
        # Only consider signals emitted on this tick (perception is
        # tick-local for v0.1; cross-tick anticipation is the planning-
        # ahead extension flagged for follow-up).
        recent = [s for s in self._intent_signals if s.tick == tick]
        if not recent:
            return
        for sig in recent:
            attacker = self._fighter_by_name(sig.fighter)
            if attacker is None:
                continue
            perceiver = (self.fighter_b if attacker is self.fighter_a
                         else self.fighter_a)
            # Familiarity — count of prior signals of the same throw_id
            # the perceiver has seen this match.
            fam = 0
            if sig.throw_id is not None:
                fam = self._throw_familiarity.get(
                    (perceiver.identity.name, sig.throw_id), 0,
                )
            # Compromised + desperation flags off the engine state.
            compromised = perceiver.identity.name in self._compromised_states
            in_desp = (
                self._defensive_desperation_active.get(perceiver.identity.name, False)
                or self._offensive_desperation_active.get(perceiver.identity.name, False)
            )
            lag = sample_lag(
                perceiver, attacker,
                compromised=compromised,
                in_desperation=in_desp,
            )
            response = choose_response(
                perceiver, attacker,
                sampled_lag=lag, commit_tick=tick,
            )
            self._perception_log.append(response)
            # HAJ-142 — STEP_OUT_VOLUNTARY shido-eat. When the
            # perceiver is in WARNING and reading an imminent throw
            # commit, they may deliberately step over the line and
            # take an OOB shido instead of accepting the throw. The
            # gate is conservative: WARNING band + composure or
            # desperation pressure + savvy enough fight_iq to weigh
            # the cost-benefit. The action cancels the staged commit
            # and lets the existing HAJ-127 OOB Matte path fire on
            # the next tick (one shido beats a likely waza-ari).
            if self._maybe_step_out_voluntary(
                perceiver, attacker, sig, tick, events,
            ):
                continue
            if response.kind == "BRACE":
                self._brace_active[perceiver.identity.name] = True
                # Active perception costs cardio.
                perceiver.state.cardio_current = max(
                    0.0,
                    perceiver.state.cardio_current - ANTICIPATION_CARDIO_COST,
                )
                events.append(Event(
                    tick=tick, event_type="PERCEPTION_BRACE",
                    description=(
                        f"[perception] {perceiver.identity.name} reads "
                        f"{attacker.identity.name}'s {sig.setup_class} "
                        f"and braces (lag={lag:+d})"
                    ),
                    data={
                        "perceiver": perceiver.identity.name,
                        "actor": attacker.identity.name,
                        "lag": lag,
                        "response": "BRACE",
                        "setup_class": sig.setup_class,
                        "throw_id": (sig.throw_id.name
                                     if sig.throw_id is not None else None),
                        "prose_silent": True,
                    },
                ))
            # Bump familiarity for the next time the perceiver sees this
            # throw class — happens regardless of response (just having
            # observed the signal is enough to shave future lag).
            if sig.throw_id is not None:
                self._bump_familiarity(perceiver, sig.throw_id)

    # -----------------------------------------------------------------------
    # HAJ-154 — INTENT-FIRST COMMIT STAGING
    # -----------------------------------------------------------------------
    def _stage_commit_intent(
        self, actor: Judoka, opp: Judoka, act: Action, tick: int,
    ) -> list[Event]:
        """Stage a COMMIT_THROW selected this tick: fire its pre-commit
        IntentSignal NOW (so opposing perception has a tick of advance
        notice — the perception window the lag axis can express against),
        and queue the actual _resolve_commit_throw firing for tick+1
        via the consequence queue.

        Returns the events emitted on the staging tick (just the intent
        signal in v0.1; downstream HAJ-153 narration may add more).
        """
        events: list[Event] = []
        a_name = actor.identity.name
        # If the fighter already has an in-progress attempt (from a
        # multi-tick throw or a prior staged intent on the previous tick),
        # reject this commit selection silently.
        if a_name in self._throws_in_progress:
            return events

        # HAJ-152 — a post-score follow-up window is open. Neither
        # fighter should be staging a fresh COMMIT_THROW between the
        # score and the post-score-decision tick (uke is on the mat;
        # tori is owed the chase decision). Pre-fix, action selection
        # could fire on the score tick AFTER the throw resolved and
        # produce a stranded commit on tick+1.
        if self._post_score_follow_up is not None:
            return events

        # Pre-commit intent signal (HAJ-149 AC2 — emitted *before* the
        # commit fires, not on the same tick).
        attacker_disguise = disguise_for(actor)
        signal_specificity = max(0.0, min(1.0, 1.0 - attacker_disguise))
        self._emit_intent_signal(
            actor, SETUP_THROW_COMMIT, tick, events,
            throw_id=act.throw_id,
            source_event_type="THROW_ENTRY",
            specificity=signal_specificity,
        )

        # Stash a placeholder _ThrowInProgress so the action gate /
        # re-commit guard treat the fighter as mid-attempt for tick+1.
        # The placeholder is popped when FIRE_COMMIT_FROM_INTENT runs;
        # the real entry is created inside _resolve_commit_throw at that
        # point with the correct compression_n / schedule.
        self._throws_in_progress[a_name] = _ThrowInProgress(
            attacker_name=a_name,
            defender_name=opp.identity.name,
            throw_id=act.throw_id,
            start_tick=tick,
            compression_n=2,
            schedule={},
            commit_actual=0.0,
        )

        # Schedule the actual commit firing for tick+1.
        self._consequence_queue.append(_Consequence(
            due_tick=tick + 1,
            kind="FIRE_COMMIT_FROM_INTENT",
            payload={
                "attacker_name": a_name,
                "defender_name": opp.identity.name,
                "throw_id": act.throw_id,
                "offensive_desperation": act.offensive_desperation,
                "defensive_desperation": act.defensive_desperation,
                "gate_bypass_reason":    act.gate_bypass_reason,
                "gate_bypass_kind":      act.gate_bypass_kind,
                "commit_motivation":     act.commit_motivation,
            },
        ))
        return events

    def _fire_consequence(
        self, c: "_Consequence", tick: int, events: list[Event],
    ) -> None:
        if c.kind == "FIRE_COMMIT_FROM_INTENT":
            attacker = self._fighter_by_name(c.payload["attacker_name"])
            defender = self._fighter_by_name(c.payload["defender_name"])
            # HAJ-70 — tick-order discipline. This staged commit targets
            # `defender_name`; if that fighter already resolved a throw to
            # LANDED_OR_SCORING earlier this same tick, this commit is a uke
            # counter that fired too late (tori threw first, uke is on the
            # mat). Discard it before _resolve_commit_throw can start a fresh
            # attempt against the already-resolved state. Pop the placeholder
            # TIP the staging layer left so the counter-fighter isn't stuck
            # mid-attempt, and leave a debug breadcrumb.
            if c.payload["defender_name"] in self._throws_resolved_this_tick:
                self._throws_in_progress.pop(c.payload["attacker_name"], None)
                events.append(Event(
                    tick=tick, event_type="COUNTER_NULLIFIED",
                    description=(
                        f"[counter] {c.payload['attacker_name']}'s queued "
                        f"counter against {c.payload['defender_name']} "
                        f"nullified — {c.payload['defender_name']}'s throw "
                        f"already resolved this tick (tick-order discipline)."
                    ),
                    data={
                        "defender": c.payload["attacker_name"],
                        "attacker": c.payload["defender_name"],
                        "reason":   "throw_resolved_this_tick",
                        "from_consequence_queue": True,
                        "prose_silent": True,
                    },
                ))
                return
            # Pop the placeholder TIP so _resolve_commit_throw's
            # "already in progress?" guard doesn't reject this firing.
            self._throws_in_progress.pop(c.payload["attacker_name"], None)
            if attacker is None or defender is None:
                return
            commit_events = self._resolve_commit_throw(
                attacker, defender, c.payload["throw_id"], tick,
                offensive_desperation=c.payload["offensive_desperation"],
                defensive_desperation=c.payload["defensive_desperation"],
                gate_bypass_reason=c.payload["gate_bypass_reason"],
                gate_bypass_kind=c.payload["gate_bypass_kind"],
                commit_motivation=c.payload["commit_motivation"],
            )
            for ev in commit_events:
                ev.data.setdefault("from_consequence_queue", True)
            events.extend(commit_events)
            return
        if c.kind == "RESOLVE_KAKE_N1" or c.kind == "RESOLVE_DRIVE_THROW":
            attacker = self._fighter_by_name(c.payload["attacker_name"])
            defender = self._fighter_by_name(c.payload["defender_name"])
            throw_id = c.payload["throw_id"]
            # HAJ-143 — pass the tip's drive_vector through to _resolve_kake
            # so the multi-tick drive landing is conditional on outcome.
            # The drive only walks uke across the mat on a successful
            # throw (IPPON / WAZA_ARI); failed / stuffed throws apply zero
            # drive — pre-fix this teleported uke 2-3 m even when the
            # throw failed, leaking GRIPPING-state fighters across half
            # the contest area.
            tip = self._throws_in_progress.get(c.payload["attacker_name"])
            drive_vector = tip.drive_vector if tip is not None else (0.0, 0.0)
            # Drop the in-progress entry now so _resolve_kake's downstream
            # paths (e.g. ne-waza dispatch on STUFFED) see a clean slate
            # for this attacker.
            self._throws_in_progress.pop(c.payload["attacker_name"], None)
            if attacker is None or defender is None:
                return
            # Recompute signature at the resolution tick — between commit and
            # resolution the world has moved; mirrors the multi-tick KAKE
            # path's fresh signature read.
            kake_actual = actual_signature_match(
                throw_id, attacker, defender, self.grip_graph,
                current_tick=tick,
            )
            kake_events = self._resolve_kake(
                attacker, defender, throw_id, kake_actual, tick,
                drive_vector=drive_vector,
            )
            for ev in kake_events:
                ev.data.setdefault("from_consequence_queue", True)
            events.extend(kake_events)
        elif c.kind == "NEWAZA_TRANSITION_AFTER_STUFF":
            attacker = self._fighter_by_name(c.payload["attacker_name"])
            defender = self._fighter_by_name(c.payload["defender_name"])
            if attacker is None or defender is None:
                return
            # HAJ-155 / HAJ-236 — sacrifice-throw failures and stuffed
            # standing throws that spilled to the floor both seat the
            # stuffed aggressor on the bottom (the probabilistic
            # ne_waza_start_position roll doesn't apply). The enqueuing
            # site sets `aggressor_on_bottom` explicitly; fall back to the
            # throw-class check for any legacy payload that omitted it.
            aggressor_on_bottom = c.payload.get(
                "aggressor_on_bottom",
                c.payload.get("throw_class") == "SACRIFICE",
            )
            source = c.payload.get("source")
            ne_events = self._resolve_newaza_transition(
                attacker, defender, tick,
                aggressor_on_bottom=aggressor_on_bottom,
            )
            for ev in ne_events:
                ev.data.setdefault("from_consequence_queue", True)
                # Tag the entry path so altitude readers can group
                # standing-scramble entries (HAJ-236) apart from the
                # sacrifice door (HAJ-155) and the post-score chase.
                if ev.event_type == "NEWAZA_TRANSITION" and source:
                    ev.data["source"] = source
            events.extend(ne_events)
        elif c.kind == "POST_SCORE_DECISION":
            decision_events = self._fire_post_score_decision(c, tick)
            for ev in decision_events:
                ev.data.setdefault("from_consequence_queue", True)
            events.extend(decision_events)
        elif c.kind == "POST_SCORE_FOLLOW_UP_MATTE":
            matte_events = self._fire_post_score_follow_up_matte(c, tick)
            for ev in matte_events:
                ev.data.setdefault("from_consequence_queue", True)
            events.extend(matte_events)
        elif c.kind == "GRIP_INIT_RECOMPUTE":
            survivor = self._fighter_by_name(c.payload["survivor_name"])
            failed_attacker = self._fighter_by_name(
                c.payload["failed_attacker_name"]
            )
            if survivor is None or failed_attacker is None:
                return
            recompute_events: list[Event] = []
            self._emit_grip_init_recompute(
                survivor, failed_attacker, tick, recompute_events,
            )
            for ev in recompute_events:
                ev.data.setdefault("from_consequence_queue", True)
            events.extend(recompute_events)

    # -----------------------------------------------------------------------
    # HAJ-152 — POST-SCORE FOLLOW-UP WINDOW
    # -----------------------------------------------------------------------
    def _open_post_score_follow_up(
        self, tori: Judoka, uke: Judoka, throw_id: ThrowID, tick: int,
        reason: str, *, force_stand: bool = False,
    ) -> list[Event]:
        """Open the post-score follow-up window after a non-match-ending
        landing. Stashes the follow-up bookkeeping and queues a
        POST_SCORE_DECISION consequence for tick+1.

        `force_stand` forces tori's branch to STAND without rolling
        the chase decision — used by the NO_SCORE-downgrade path,
        where there's no waza-ari to convert.
        """
        # Cancel any pending FIRE_COMMIT_FROM_INTENT consequences. A
        # waza-ari on the same tick as a freshly-staged commit (from
        # action selection earlier this tick or the prior tick) means
        # the staged commit should not actually fire — uke is on the
        # mat, the dyad has a follow-up window to resolve. Pre-fix the
        # staged commits ran on tick+1 and Sato kept committing fresh
        # uchi-matas a tick after scoring.
        self._consequence_queue = [
            c for c in self._consequence_queue
            if c.kind != "FIRE_COMMIT_FROM_INTENT"
        ]
        # Drop placeholder _ThrowInProgress entries that the staging
        # layer left behind for those cancelled consequences.
        for name in (tori.identity.name, uke.identity.name):
            tip = self._throws_in_progress.get(name)
            if tip is not None and tip.start_tick == tick:
                self._throws_in_progress.pop(name, None)
        # Defensive: clobbering an existing follow-up would leak state.
        # In practice this can't happen (only one waza-ari can land per
        # tick), but a guard keeps the test surface honest.
        self._post_score_follow_up = {
            "tori_name":    tori.identity.name,
            "uke_name":     uke.identity.name,
            "throw_id":     throw_id,
            "score_tick":   tick,
            "reason":       reason,
            "force_stand":  force_stand,
            "decision":     None,
            "stage":        "PENDING_DECISION",
        }
        self._consequence_queue.append(_Consequence(
            due_tick=tick + 1,
            kind="POST_SCORE_DECISION",
            payload={
                "tori_name": tori.identity.name,
                "uke_name":  uke.identity.name,
                "throw_id":  throw_id,
                "score_tick": tick,
            },
        ))
        return [Event(
            tick=tick,
            event_type="POST_SCORE_FOLLOW_UP_OPEN",
            description=(
                f"[follow-up] {tori.identity.name} scored {reason} on "
                f"{uke.identity.name} — chase decision pending."
            ),
            data={
                "tori":      tori.identity.name,
                "uke":       uke.identity.name,
                "throw_id":  throw_id.name,
                "reason":    reason,
                "prose_silent": True,
            },
        )]

    def _fire_post_score_decision(
        self, c: "_Consequence", tick: int,
    ) -> list[Event]:
        """Resolve the chase decision (tori) and defense decision (uke)
        for the post-score follow-up window. Either dispatches into
        ne-waza (CHASE / DEFENSIVE_CHASE) or queues the
        POST_SCORE_FOLLOW_UP_MATTE consequence for an explicit
        stand-and-reset matte."""
        events: list[Event] = []
        follow_up = self._post_score_follow_up
        tori = self._fighter_by_name(c.payload["tori_name"])
        uke  = self._fighter_by_name(c.payload["uke_name"])
        throw_id = c.payload["throw_id"]
        if follow_up is None or tori is None or uke is None:
            # State got cleared (match end?). Fall back to a clean
            # matte sequence so the dyad can't get stranded.
            self._consequence_queue.append(_Consequence(
                due_tick=tick + 1,
                kind="POST_SCORE_FOLLOW_UP_MATTE",
                payload={"reason": "stand"},
            ))
            return events

        td = THROW_DEFS.get(throw_id)
        chase_advantage = (
            td.post_score_chase_advantage if td is not None else 0.5
        )
        landing_profile = (
            td.landing_profile if td is not None else LandingProfile.LATERAL
        )

        # score_diff_before: tori's waza-ari count minus uke's, BEFORE
        # this waza-ari was awarded. The award has already mutated the
        # scoreboard, so subtract one from tori's current count.
        # `force_stand` paths (NO_SCORE downgrade) skip the arithmetic
        # because nothing was awarded.
        if follow_up.get("force_stand"):
            score_diff_before = (
                tori.state.score["waza_ari"] - uke.state.score["waza_ari"]
            )
        else:
            score_diff_before = (
                (tori.state.score["waza_ari"] - 1)
                - uke.state.score["waza_ari"]
            )
        clock_remaining = max(0, self.max_ticks - tick)

        # Tori's chase decision (or forced STAND on NO_SCORE).
        if follow_up.get("force_stand"):
            chase_result = ChaseDecisionResult(
                decision=ChaseDecision.STAND,
                probability=0.0,
                factors={"force_stand": 1.0},
            )
        else:
            chase_rng = random.Random(
                f"haj152:chase:{tori.identity.name}:{self.seed}:{tick}"
            )
            chase_result = make_chase_decision(
                tori, throw_id,
                landing_profile=landing_profile,
                chase_advantage=chase_advantage,
                score_diff_before=score_diff_before,
                clock_remaining=clock_remaining,
                rng=chase_rng,
            )

        events.append(Event(
            tick=tick,
            event_type="CHASE_DECISION",
            description=(
                f"[chase_decision] {tori.identity.name} → "
                f"{chase_result.decision.name} "
                f"(p={chase_result.probability:.2f})"
            ),
            data={
                "tori":        tori.identity.name,
                "uke":         uke.identity.name,
                "throw_id":    throw_id.name,
                "decision":    chase_result.decision.name,
                "probability": chase_result.probability,
                "factors":     dict(chase_result.factors),
                "prose_silent": True,
                "coach_prose": _chase_coach_prose(
                    tori.identity.name, chase_result.decision.name,
                ),
            },
        ))

        # Uke's defense decision.
        tori_chasing = chase_result.decision != ChaseDecision.STAND
        # uke's score_diff_before is the negation of tori's.
        defense_rng = random.Random(
            f"haj152:defense:{uke.identity.name}:{self.seed}:{tick}"
        )
        defense_result = make_defense_decision(
            uke,
            landing_profile=landing_profile,
            score_diff_before=-score_diff_before,
            clock_remaining=clock_remaining,
            tori_chasing=tori_chasing,
            rng=defense_rng,
        )
        events.append(Event(
            tick=tick,
            event_type="DEFENSE_DECISION",
            description=(
                f"[defense_decision] {uke.identity.name} → "
                f"{defense_result.decision.name}"
            ),
            data={
                "uke":      uke.identity.name,
                "tori":     tori.identity.name,
                "decision": defense_result.decision.name,
                "factors":  dict(defense_result.factors),
                "prose_silent": True,
                "coach_prose": _defense_coach_prose(
                    uke.identity.name, defense_result.decision.name,
                ),
            },
        ))

        follow_up["decision"]         = chase_result.decision.name
        follow_up["defense_decision"] = defense_result.decision.name

        if chase_result.decision in (
            ChaseDecision.CHASE, ChaseDecision.DEFENSIVE_CHASE,
        ):
            # Dispatch into ne-waza via the existing transition helper.
            # DEFENSIVE_CHASE means tori is on the bottom (sacrifice
            # throw); pass the orientation through so the position
            # machine seats GUARD_BOTTOM / SIDE_CONTROL appropriately.
            follow_up["stage"] = "NE_WAZA_LIVE"
            ne_events = self._dispatch_post_score_newaza(
                tori, uke, tick,
                defensive_chase=(
                    chase_result.decision == ChaseDecision.DEFENSIVE_CHASE
                ),
            )
            events.extend(ne_events)
            # If the ne-waza dispatch didn't actually land (resolver
            # declined), fall back to STAND-and-reset so the dyad
            # can't be stranded without an exit path.
            dispatched = any(
                ev.event_type == "NEWAZA_TRANSITION" for ev in ne_events
            )
            if not dispatched:
                follow_up["stage"] = "STANDING"
                self._consequence_queue.append(_Consequence(
                    due_tick=tick + 2,
                    kind="POST_SCORE_FOLLOW_UP_MATTE",
                    payload={"reason": "stand"},
                ))
        else:
            # STAND path: tori opts out, uke also stands. Queue the
            # explicit matte for tick+2 so the rhythm is
            # decision (T+1) → stand (T+2) → matte (T+2 from the
            # consequence; ref reset follows).
            follow_up["stage"] = "STANDING"
            self._consequence_queue.append(_Consequence(
                due_tick=tick + 2,
                kind="POST_SCORE_FOLLOW_UP_MATTE",
                payload={"reason": "stand"},
            ))

        return events

    def _dispatch_post_score_newaza(
        self, tori: Judoka, uke: Judoka, tick: int, *,
        defensive_chase: bool,
    ) -> list[Event]:
        """Route the chase into the existing ne-waza substrate. Mirrors
        `_resolve_newaza_transition` but tagged source="POST_SCORE_CHASE"
        so altitude readers can group it. The ne-waza substrate handles
        unfolding, escape, conversion to ippon, and the standard
        ne-waza-patience matte from there on.
        """
        events: list[Event] = []
        # Aggressor / defender pair: forward chase puts tori on top,
        # defensive chase puts tori on bottom.
        if defensive_chase:
            aggressor, defender = uke, tori
        else:
            aggressor, defender = tori, uke
        ne_events = self._resolve_newaza_transition(aggressor, defender, tick)
        # Tag the transition event so the post-score path is traceable
        # in the log; the existing NEWAZA_TRANSITION shape is preserved
        # for downstream consumers.
        for ev in ne_events:
            if ev.event_type == "NEWAZA_TRANSITION":
                ev.data["source"]              = "POST_SCORE_CHASE"
                ev.data["defensive_chase"]     = defensive_chase
                ev.data["scorer"]              = tori.identity.name
        events.extend(ne_events)
        return events

    def _fire_post_score_follow_up_matte(
        self, c: "_Consequence", tick: int,
    ) -> list[Event]:
        """Explicit matte announcement at the end of a STAND-path
        post-score follow-up. Emits the matte event AND the SCORE_RESET
        that resets the dyad — no reset path can fire after a score
        without going through this matte (HAJ-152 AC#8)."""
        events: list[Event] = []
        if self.match_over:
            return events
        events.append(self.referee.announce_matte(
            MatteReason.POST_SCORE_FOLLOW_UP_END, tick,
        ))
        # HAJ-221 — matte context line fires after every matte
        # announcement, including the post-score follow-up matte.
        events.append(self._build_matte_context_event(tick))
        reason = (
            self._post_score_follow_up.get("reason", "post-score reset")
            if self._post_score_follow_up is not None
            else "post-score reset"
        )
        events.extend(self._post_score_reset(tick, reason))
        # Close the follow-up window.
        self._post_score_follow_up = None
        return events

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
        apply_failure_resolution(resolution, attacker, composure_drop=0.0,
                                 current_tick=tick)
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
            current_tick=tick,
        )
        if actual == CounterWindow.NONE:
            return None

        # HAJ-70 — tick-order discipline. The counter window above is read
        # against the attacker's mid-throw vulnerability, but if the
        # attacker's throw already resolved to LANDED_OR_SCORING earlier this
        # same tick, that window is stale: tori has completed the throw and
        # uke is on the mat. A counter fired now is the Match-4 Ura-nage that
        # "doesn't count" — the throw was already resolved. Discard it (no
        # COUNTER_COMMIT, no abort of the now-finished attempt) and leave a
        # debug breadcrumb noting the nullification.
        if attacker.identity.name in self._throws_resolved_this_tick:
            return [Event(
                tick=tick, event_type="COUNTER_NULLIFIED",
                description=(
                    f"[counter] {defender.identity.name}'s counter against "
                    f"{attacker.identity.name} nullified — "
                    f"{attacker.identity.name}'s throw already resolved this "
                    f"tick (tick-order discipline)."
                ),
                data={
                    "defender": defender.identity.name,
                    "attacker": attacker.identity.name,
                    "reason":   "throw_resolved_this_tick",
                    "prose_silent": True,
                },
            )]

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
        # HAJ-134 — read attacker's total commitment from active windows.
        from vulnerability_window import total_commitment
        commitment = total_commitment(attacker, tick)
        p = counter_fire_probability(
            defender, perceived, vuln,
            defensive_desperation=def_desp,
            tori_execution_quality=tori_eq,
            attacker_commitment=commitment,
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
        #
        # HAJ-221 — the engineer description keeps the bare enum read
        # (`reads SEN_SEN_NO_SEN`) so the debug stream remains a clean
        # substrate dump. The coach stream gets a narrative-first
        # rendering of the same counter cognition, with the technical
        # term parenthesised so the player can map prose to vocabulary
        # over time. `_counter_coach_prose` owns the per-window phrasing.
        counter_throw_name = THROW_REGISTRY[counter_id].name
        counter_event = Event(
            tick=tick, event_type="COUNTER_COMMIT",
            description=(
                f"[counter] {defender.identity.name} reads {perceived.name} — "
                f"fires {counter_throw_name} against "
                f"{attacker.identity.name}."
            ),
            data={
                "window":          perceived.name,
                "actual_window":   actual.name,
                "counter_throw":   counter_id.name,
                "attacker_throw":  effective_throw_id.name,
                "attacker":        attacker.identity.name,
                "defender":        defender.identity.name,
                "coach_prose":     _counter_coach_prose(
                    defender.identity.name, perceived, counter_throw_name,
                ),
            },
        )
        # HAJ-145 — body-part decomposition of the counter commit. Routed
        # through the same template-walk used by direct commits, but tagged
        # source="COUNTER_COMMIT" so altitude readers can group it.
        from worked_throws import worked_template_for as _worked_template_for
        _counter_template = _worked_template_for(counter_id)
        if _counter_template is not None:
            self._attach_bpe(counter_event, decompose_counter(
                defender, attacker, _counter_template, tick,
            ))
        events: list[Event] = [counter_event]

        # If tori was mid-attempt, abort it — the counter preempts.
        if tip is not None:
            events.extend(self._abort_throw_in_progress(
                tip, attacker, defender, tick, reason="countered",
            ))

        # HAJ-157 V2 — counter throws route through the staging layer so
        # the counter intent fires this tick and the counter commit fires
        # on tick+1 from the consequence queue. Pre-fix, _try_fire_counter
        # called _resolve_commit_throw directly, producing a counter that
        # resolved on the same tick as the action being countered (the
        # exact pattern HAJ-149 / HAJ-154's intent contract was meant to
        # dissolve). _stage_commit_intent emits the pre-commit IntentSignal
        # synchronously and queues FIRE_COMMIT_FROM_INTENT for tick+1, so
        # the counter is now temporally separated from its trigger.
        counter_action = Action(
            kind=ActionKind.COMMIT_THROW,
            throw_id=counter_id,
        )
        events.extend(self._stage_commit_intent(
            defender, attacker, counter_action, tick,
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
                # HAJ-221 — narrative-first coach line; numbers stay in
                # data + the engineer description for the debug stream.
                "coach_prose": _defensive_desperation_coach_prose(name),
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
                # HAJ-221 — narrative-first coach line.
                "coach_prose": _offensive_desperation_coach_prose(name),
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
                data = p.get("data") or {}
                # HAJ-221 — thread the coach narration onto event.data so
                # _print_events can surface it on the coach stream while
                # the debug stream keeps the numeric description.
                if p.get("coach_prose"):
                    data = dict(data)
                    data["coach_prose"] = p["coach_prose"]
                if data:
                    ev_kwargs["data"] = data
                events.append(Event(**ev_kwargs))
                self._desp_enter_announced[name][kind] = True

    def _update_composure_from_kuzushi(
        self, a_kuzushi: bool, b_kuzushi: bool
    ) -> None:
        # Being in kuzushi drops composure; inducing it on the opponent
        # raises yours. Small per-tick deltas — the spec calls for tick
        # outcomes to drive composure (Part 3.4 Step 12).
        #
        # HAJ-222 — per-tick drift reduced from 0.05 to 0.02. At the
        # pre-fix rate, fifteen ticks of intermittent kuzushi could
        # bleed composure 0.5 (out of a ceiling typically ≤ 10), which
        # combined with the defensive-pressure tracker's 0.8 weight
        # to push fighters into desperation 25 seconds into a match.
        # The reduced drift keeps the directional pressure but moves
        # the time-to-desperation into the 90–120s band the ticket
        # calls for.
        drift = 0.02
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
        net_grip_progress: bool = False,
    ) -> None:
        """Increment the stalemate counter unless *progress* was made this
        tick. Progress is any of: a commit, a kuzushi event, OR a grip
        change that survived oscillation coalescing.

        HAJ-36 surfaced a pre-existing bug: before the grip-presence gate,
        low-quality commits fired constantly from POCKET grips and reset
        this counter for free. With the gate, matches that are genuinely
        doing grip-fighting work looked identical to a dead hold — because
        the counter only counted commits. Grip contests now count.

        HAJ-138 follow-on: pre-fix, ANY DEEPEN/STRIP action attempt reset
        the counter, so two fighters infinitely cancelling each other's
        grips never tripped matte. We now require *net* grip progress
        (an event that survived `_coalesce_grip_oscillation`). Action
        attempts that nullify each other count as stalemate.
        """
        committed = any(
            act.kind == ActionKind.COMMIT_THROW
            for act in (actions_a + actions_b)
        )
        defensive_grip_work = any(
            act.kind in (ActionKind.DEFEND_GRIP, ActionKind.STRIP_TWO_ON_ONE,
                         ActionKind.REPOSITION_GRIP)
            for act in (actions_a + actions_b)
        )
        if (committed or a_kuzushi or b_kuzushi
                or net_grip_progress or defensive_grip_work):
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
            # HAJ-70 — the kake sequence resolved to a landing this tick.
            # Mark tori so the counter paths (Step 11 fresh counters + any
            # counter commit queued for this same tick) discard a uke counter
            # that fired too late: the throw is already scored / uke is on the
            # mat, so a counter resolved against the mid-throw state must not
            # compromise tori post-hoc. Covers IPPON, WAZA_ARI, and the
            # ref-downgraded no-score landing (all reached inside this block).
            self._throws_resolved_this_tick.add(a_name)
            # Ask referee for the score
            score_result = self.referee.score_throw(landing, tick)
            effective_award = score_result.award

            if effective_award == "IPPON":
                attacker.state.score["ippon"] = True
                self._a_score = attacker.state.score.copy() if attacker is self.fighter_a else self._a_score
                self._b_score = defender.state.score.copy() if defender is self.fighter_b else self._b_score
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
                # HAJ-93 — route end through _end_match so the unified
                # MATCH_ENDED event fires after the score line.
                self._end_match(
                    attacker,
                    "ippon (golden score)" if self.golden_score else "ippon",
                    tick,
                    events,
                )

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
                # HAJ-93 — sudden death: any waza-ari in golden score
                # ends the match for the scorer regardless of count.
                if self.golden_score:
                    events.append(Event(
                        tick=tick,
                        event_type="IPPON_AWARDED",
                        description=(
                            f"[ref: {self.referee.name}] Golden score — "
                            f"waza-ari! {a_name} wins."
                        ),
                    ))
                    self._end_match(
                        attacker, "waza-ari (golden score)", tick, events,
                    )
                elif wa_count >= 2:
                    events.append(Event(
                        tick=tick,
                        event_type="IPPON_AWARDED",
                        description=f"[ref: {self.referee.name}] Two waza-ari — Ippon! {a_name} wins.",
                    ))
                    self._end_match(attacker, "two waza-ari", tick, events)
                else:
                    # HAJ-152 — single waza-ari opens the post-score
                    # follow-up window. Pre-fix this dispatched directly
                    # through `_post_score_reset` on the same tick as
                    # the score, with no chase decision and no matte —
                    # producing the t017–t018 narrative break (waza-ari
                    # → same-tick reset). Post-fix the score fires
                    # silently here and a POST_SCORE_DECISION
                    # consequence runs on tick+1; tori chooses chase or
                    # stand, uke chooses defense, and ne-waza unfolds
                    # in the existing substrate. Reset only happens
                    # after an explicit matte (either the STAND-path
                    # POST_SCORE_FOLLOW_UP_MATTE or the standard
                    # ne-waza patience clock).
                    events.extend(self._open_post_score_follow_up(
                        attacker, defender, throw_id, tick, "waza-ari",
                    ))

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
                # HAJ-139 + HAJ-152 — a downgraded landing put a fighter
                # on the mat, but the score didn't actually award; tori
                # has no waza-ari to convert, so there's no chase
                # decision. Open the follow-up window with chase
                # forced to STAND so the matte sequence still fires
                # explicitly (HAJ-152 AC#8 — every reset after a
                # landing must carry an intervening matte).
                events.extend(self._open_post_score_follow_up(
                    attacker, defender, throw_id, tick,
                    "no-score landing", force_stand=True,
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
                # HAJ-155 — only sacrifice throws open the ne-waza door
                # on stuff. Standing throws reset to standing (per the
                # ticket: a stuffed O-uchi-gari should not look
                # mechanically identical to a stuffed Tomoe-nage). The
                # prose for the STUFFED event diverges accordingly so
                # the log is honest about the routing.
                from throws import is_sacrifice_throw
                is_sacrifice = is_sacrifice_throw(throw_id)
                self._stuffed_throw_tick = tick
                # HAJ-236 — a stuffed STANDING throw no longer always
                # resets. Roll the ground-continuation decision: reaping
                # throws and ground-hungry fighters sometimes tangle to
                # the floor (stuffed aggressor underneath, defender on
                # top) instead of resetting. Sacrifice throws skip the
                # roll — they always open the door (HAJ-155 geometry).
                continue_to_ground = False
                gc_result = None
                if not is_sacrifice:
                    gc_result = self._roll_ground_continuation(
                        attacker, defender, throw_id, tick,
                    )
                    continue_to_ground = (
                        gc_result.decision
                        == GroundContinuation.CONTINUE_TO_GROUND
                    )
                if is_sacrifice:
                    stuff_desc = (
                        f"[throw] {a_name} stuffed on {throw_name} — "
                        f"{d_name} defends. Ne-waza window open."
                    )
                elif continue_to_ground:
                    stuff_desc = (
                        f"[throw] {a_name} stuffed on {throw_name} — "
                        f"{d_name} defends, but they tangle to the mat. "
                        f"Ne-waza scramble."
                    )
                else:
                    stuff_desc = (
                        f"[throw] {a_name} stuffed on {throw_name} — "
                        f"{d_name} defends. Resetting to standing."
                    )
                events.append(Event(
                    tick=tick,
                    event_type="STUFFED",
                    description=stuff_desc,
                    data={"throw_class": (
                        "SACRIFICE" if is_sacrifice else "STANDING"
                    )},
                ))
                # HAJ-236 — surface the ground-continuation roll on the
                # engineering stream (prose-silent) so the debug overlay
                # and tests can see why a stuffed standing throw did or
                # did not spill to the ground. Mirrors CHASE_DECISION.
                if gc_result is not None:
                    events.append(Event(
                        tick=tick,
                        event_type="GROUND_CONTINUATION",
                        description=(
                            f"[ground_continuation] {a_name} stuffed → "
                            f"{gc_result.decision.name} "
                            f"(p={gc_result.probability:.2f})"
                        ),
                        data={
                            "attacker":    a_name,
                            "defender":    d_name,
                            "throw_id":    throw_id.name,
                            "decision":    gc_result.decision.name,
                            "probability": gc_result.probability,
                            "factors":     dict(gc_result.factors),
                            "prose_silent": True,
                        },
                    ))
                # Composure hit on attacker for being stuffed
                attacker.state.composure_current = max(
                    0.0,
                    attacker.state.composure_current - 0.3
                )
                # HAJ-140 — stun the stuffed aggressor so they can't fire
                # another commit on the very next tick. Action selection's
                # rung-1 stun gate blocks even defensive-desperation pushes.
                # Stun applies regardless of whether ne-waza dispatch fires;
                # if it does, the stun is moot (sub_loop_state goes NE_WAZA);
                # if it doesn't, this is what holds the stuffed fighter from
                # firing a fresh throw inside the STUFFED_MATTE window.
                attacker.state.stun_ticks = max(
                    attacker.state.stun_ticks, STUFFED_AGGRESSOR_STUN_TICKS,
                )
                # HAJ-148 — defer the ne-waza door to tick+1. The stuff
                # event itself fires this tick (the visible prose beat);
                # the door (NEWAZA_TRANSITION) is the consequence of the
                # stuff and lands on the next tick, distributing the
                # cause-effect chain across two ticks instead of one.
                #
                # HAJ-157 V3 — dedupe at the STUFFED branch. When both
                # fighters stuff on the same tick, both _apply_throw_result
                # invocations would otherwise enqueue a separate
                # NEWAZA_TRANSITION_AFTER_STUFF, and the dyad's ne-waza
                # door would fire twice. Skip the enqueue if a door is
                # already queued for the same target tick — the dyad is
                # shared between the two stuffs, so a single transition
                # covers both.
                #
                # HAJ-155 / HAJ-236 — gate the door on throw class plus the
                # ground-continuation roll. Sacrifice throws commit tori to
                # the ground and always open the door (standing back up
                # isn't available). Standing throws open it only when the
                # HAJ-236 roll says the scramble spilled to the floor;
                # otherwise they reset to standing. Both routings seat the
                # stuffed aggressor on the bottom (defender on top) — the
                # aggressor over-committed and ends up underneath either
                # way. The HAJ-158 grip-init recompute below still fires
                # regardless (post-stuff is a fresh grip-fight beat).
                if is_sacrifice or continue_to_ground:
                    already_queued = any(
                        c.kind == "NEWAZA_TRANSITION_AFTER_STUFF"
                        and c.due_tick == tick + 1
                        for c in self._consequence_queue
                    )
                    if not already_queued:
                        self._consequence_queue.append(_Consequence(
                            due_tick=tick + 1,
                            kind="NEWAZA_TRANSITION_AFTER_STUFF",
                            payload={
                                "attacker_name": attacker.identity.name,
                                "defender_name": defender.identity.name,
                                "throw_class": (
                                    "SACRIFICE" if is_sacrifice
                                    else "STANDING"
                                ),
                                # Both paths put the stuffed aggressor on
                                # the bottom. The handler reads this flag
                                # directly so the standing-scramble path
                                # gets the same GUARD_TOP / defender-on-top
                                # geometry as the sacrifice path.
                                "aggressor_on_bottom": True,
                                "source": (
                                    "SACRIFICE_STUFF" if is_sacrifice
                                    else "STANDING_SCRAMBLE"
                                ),
                            },
                        ))

        else:  # FAILED
            events.extend(self._resolve_failed_commit(
                attacker, defender, throw_id, throw_name, net, tick,
            ))
            # HAJ-155 — sacrifice-throw failures open the ne-waza door
            # (tori is geometrically committed to the ground; standing
            # back up cleanly isn't available). Standing-throw failures
            # stay on _resolve_failed_commit's reset path. Mirrors the
            # STUFFED-without-motivation gate above.
            from throws import is_sacrifice_throw
            if is_sacrifice_throw(throw_id):
                already_queued = any(
                    c.kind == "NEWAZA_TRANSITION_AFTER_STUFF"
                    and c.due_tick == tick + 1
                    for c in self._consequence_queue
                )
                if not already_queued:
                    self._consequence_queue.append(_Consequence(
                        due_tick=tick + 1,
                        kind="NEWAZA_TRANSITION_AFTER_STUFF",
                        payload={
                            "attacker_name": attacker.identity.name,
                            "defender_name": defender.identity.name,
                            "throw_class": "SACRIFICE",
                        },
                    ))

        # HAJ-49 / HAJ-67 — janitor: clear the motivation snapshot for this
        # attacker. _resolve_failed_commit pops it on failure; this covers
        # IPPON / WAZA_ARI / no-score landings where the snapshot wasn't
        # consumed.
        self._commit_motivation.pop(a_name, None)

        # HAJ-158 — every FAILED / STUFFED resolution opens a fresh
        # grip-fight beat: tori has expended energy, telegraphed a
        # preference, and lost a tick of tempo; uke survived an attack.
        # HAJ-151's spec calls for an initiative recompute on every
        # post-failure / post-stuff re-engagement, but the engagement
        # path only fires when grips break (edge_count==0). Schedule
        # the recompute here as a consequence on tick+1 (HAJ-148 N+1
        # contract); the handler emits a fresh [grip_init] event with
        # current state so the composure dip from failure expresses.
        if outcome in ("FAILED", "STUFFED") and not self.match_over:
            self._consequence_queue.append(_Consequence(
                due_tick=tick + 1,
                kind="GRIP_INIT_RECOMPUTE",
                payload={
                    "survivor_name": d_name,
                    "failed_attacker_name": a_name,
                },
            ))

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
            throw_id=throw_id, current_tick=tick,
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
                current_tick=tick,
            )
        elif is_tactical_drop:
            # HAJ-50 — near-zero composure hit on the outcome itself.
            # Whether tori labelled this as an intentional fake or
            # stumbled into one via a low-signature commit, the cost is
            # a single tick of no-offense and nothing else.
            apply_failure_resolution(resolution, attacker, composure_drop=0.005,
                                     current_tick=tick)
        else:
            apply_failure_resolution(resolution, attacker, current_tick=tick)

        # Track the compromised-state tag so uke's counter attempts during
        # the recovery window get the per-state vulnerability bonus.
        self._compromised_states[a_name] = resolution.outcome

        events.extend(self._format_failure_events(
            attacker, defender, throw_name, resolution, desperation, tick,
            motivation=motivation, throw_id=throw_id,
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
    def _authored_failure_prose(
        self, throw_id: Optional[ThrowID], outcome, tick: int,
        *, tori: str, uke: str,
    ) -> Optional[str]:
        """HAJ-223 — the body-part failure narration line for this
        (throw, FailureOutcome), with {tori}/{uke} resolved to live names.
        Returns None when the throw is unauthored or has no entry for this
        outcome, so the caller keeps the engineer-facing fallback phrasing
        (_FAILURE_TAGS / _COUNTER_NARRATIONS). Mirrors the phase-line wiring
        in _coach_prose_for_sub_event."""
        if throw_id is None:
            return None
        import throw_narration as _tn
        line = _tn.select_failure_line(
            _tn.get_default_data(), throw_id, outcome.name,
            seed=f"{self.seed}:{tori}:{tick}",
        )
        if not line:
            return None
        return _tn.render_line(line, tori=tori, uke=uke)

    def _format_failure_events(
        self, attacker: Judoka, defender: Judoka, throw_name: str,
        resolution, desperation: bool, tick: int,
        motivation: Optional["CommitMotivation"] = None,
        throw_id: Optional[ThrowID] = None,
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

        # HAJ-223 — authored body-part failure narration overrides the
        # engineer-facing tag on the coach stream when an entry exists.
        authored = self._authored_failure_prose(
            throw_id, outcome, tick, tori=a_name, uke=d_name,
        )

        counter_desc = _COUNTER_NARRATIONS.get(outcome)
        if counter_desc is not None:
            counter_data = {**data, "counter_thrower": d_name}
            if authored is not None:
                counter_data["coach_prose"] = authored
            return [
                Event(
                    tick=tick, event_type="THROW_STUFFED",
                    description=f"[throw] {a_name} → {throw_name} stuffed.",
                    data={
                        "throw_name": throw_name, "attacker": a_name,
                        # Suppress the bare "stuffed" beat on the coach
                        # stream when an authored counter line follows —
                        # the authored line is the full narrative beat.
                        **({"prose_silent": True} if authored is not None else {}),
                    },
                ),
                Event(
                    tick=tick, event_type="FAILED",
                    description=(
                        f"[counter] {d_name} {counter_desc} "
                        f"({a_name} recovers {recovery} tick(s){desp_tag})."
                    ),
                    data=counter_data,
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
            # The motivation prose already reads as a narrative beat; only
            # override it when the throw authored a tactical_drop_reset line.
            drop_data = dict(data)
            if authored is not None:
                drop_data["coach_prose"] = authored
            return [Event(
                tick=tick, event_type="FAILED",
                description=motivation_narration_for(
                    effective_motivation, tori=a_name, throw=throw_name,
                ),
                data=drop_data,
            )]

        tag = _FAILURE_TAGS.get(outcome, outcome.name.lower())
        failed_data = dict(data)
        if authored is not None:
            failed_data["coach_prose"] = authored
        return [Event(
            tick=tick, event_type="FAILED",
            description=(
                f"[throw] {a_name} → {throw_name} → failed "
                f"({tag}; recovery {recovery} tick(s){desp_tag})."
            ),
            data=failed_data,
        )]

    # -----------------------------------------------------------------------
    # HAJ-236 — STUFFED-STANDING-THROW GROUND-CONTINUATION ROLL
    # -----------------------------------------------------------------------
    def _roll_ground_continuation(
        self, attacker: Judoka, defender: Judoka, throw_id: ThrowID,
        tick: int,
    ) -> GroundContinuationResult:
        """Decide whether a stuffed STANDING throw spills into ne-waza
        instead of resetting to standing (HAJ-236).

        The throw's `post_score_chase_advantage` doubles as the scramble-
        tendency signal — reaping / leg throws tangle to the floor, clean
        hip throws bounce off. The RNG is seeded off the match seed, the
        stuffed aggressor, and the tick so the roll is reproducible and a
        re-run of the same seed lands the same way. Exposed as a method so
        tests can force the branch (mirrors how the ne-waza resolver's
        `attempt_ground_commit` is patched in the HAJ-155 suite).
        """
        td = THROW_DEFS.get(throw_id)
        chase_advantage = (
            td.post_score_chase_advantage if td is not None else 0.5
        )
        gc_rng = random.Random(
            f"haj236:ground:{attacker.identity.name}:{self.seed}:{tick}"
        )
        return make_ground_continuation_decision(
            attacker, defender,
            throw_id=throw_id,
            chase_advantage=chase_advantage,
            rng=gc_rng,
        )

    # -----------------------------------------------------------------------
    # NE-WAZA TRANSITION (after stuffed throw)
    # -----------------------------------------------------------------------
    def _resolve_newaza_transition(
        self, aggressor: Judoka, defender: Judoka, tick: int,
        *, aggressor_on_bottom: bool = False,
    ) -> list[Event]:
        events: list[Event] = []
        window_q = 0.5  # moderate quality after a stuffed throw

        commits = self.ne_waza_resolver.attempt_ground_commit(
            aggressor, defender, window_q
        )
        if commits:
            # Determine starting position. HAJ-155 — sacrifice throw
            # failures route tori onto the bottom (they committed to
            # the ground geometrically); we force GUARD_TOP with
            # defender-on-top instead of rolling the probabilistic
            # ne_waza_start_position (which can put tori on top, the
            # wrong geometry for a stuffed sacrifice throw).
            if aggressor_on_bottom:
                start_pos = Position.GUARD_TOP
            else:
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
            # HAJ-129 — drop any other-fighter throws that were mid-flight
            # when ne-waza started. _advance_throws_in_progress doesn't run
            # during NE_WAZA, so without this clear the stranded throw
            # would re-emerge as a "grips collapsed" abort line on the
            # first standing tick after escape. The attacker's own entry
            # is left intact for the caller (_advance_throws_in_progress)
            # to delete once _apply_throw_result returns.
            for name in list(self._throws_in_progress.keys()):
                if name != aggressor.identity.name:
                    del self._throws_in_progress[name]
            # Reset stalemate counter — ne-waza just started, no stalemate.
            self.stalemate_ticks = 0

            # Set who is on top. HAJ-155 — sacrifice failures put the
            # defender on top regardless of the start position (tori is
            # geometrically committed to the bottom).
            if aggressor_on_bottom:
                self.ne_waza_top_id = defender.identity.name
            elif start_pos == Position.SIDE_CONTROL:
                # Defender is on top (absorbed the throw)
                self.ne_waza_top_id = defender.identity.name
            else:
                self.ne_waza_top_id = aggressor.identity.name

            self.ne_waza_resolver.set_top_fighter(
                self.ne_waza_top_id, (self.fighter_a, self.fighter_b)
            )
            # HAJ-220 — seed the catalog-aware ground connection graph
            # for the entered position. No-op when no ne-waza catalog
            # was supplied (legacy resolver path).
            self.ne_waza_resolver.on_ground_entry(start_pos)
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

        # HAJ-220 — catalog-mode pins carry a technique_id; surface it in
        # the detail string and the score event's data payload so the log
        # stream + downstream tooling see which Kodokan variant scored.
        technique_id = self.osaekomi.technique_id
        if award == "IPPON":
            holder.state.score["ippon"] = True
            detail = (
                f"{technique_id}, {self.osaekomi.ticks_held}s"
                if technique_id
                else f"{self.osaekomi.ticks_held}s hold"
            )
            score_ev = self.referee.announce_score(
                outcome="IPPON",
                scorer_id=holder_id,
                tick=tick,
                source="pin",
                detail=detail,
            )
            if technique_id is not None:
                score_ev.data["technique_id"] = technique_id
            events.append(score_ev)
            self._scoring_events.append(score_ev)
            # HAJ-93 — pin ippon ends the match in regulation or golden
            # score; tag the method so consumers can distinguish.
            method = (
                "ippon (pin, golden score)" if self.golden_score
                else "ippon (pin)"
            )
            self._end_match(holder, method, tick, events)
        elif award == "WAZA_ARI":
            holder.state.score["waza_ari"] += 1
            wa_count = holder.state.score["waza_ari"]
            detail = (
                f"{technique_id}, {self.osaekomi.ticks_held}s"
                if technique_id
                else f"{self.osaekomi.ticks_held}s hold"
            )
            score_ev = self.referee.announce_score(
                outcome="WAZA_ARI",
                scorer_id=holder_id,
                count=wa_count,
                tick=tick,
                source="pin",
                detail=detail,
            )
            if technique_id is not None:
                score_ev.data["technique_id"] = technique_id
            events.append(score_ev)
            self._scoring_events.append(score_ev)
            # HAJ-93 — sudden death in golden score; otherwise the usual
            # two-waza-ari rule.
            if self.golden_score:
                events.append(Event(
                    tick=tick,
                    event_type="IPPON_AWARDED",
                    description=(
                        f"[score] Golden score — waza-ari, {holder_id} wins."
                    ),
                ))
                self._end_match(
                    holder, "waza-ari (golden score)", tick, events,
                )
            elif wa_count >= 2:
                events.append(Event(
                    tick=tick,
                    event_type="IPPON_AWARDED",
                    description=f"[score] Two waza-ari — {holder_id} wins.",
                ))
                self._end_match(holder, "two waza-ari", tick, events)
            # Composure hit
            held.state.composure_current = max(
                0.0, held.state.composure_current - COMPOSURE_DROP_WAZA_ARI
            )

        return events

    # -----------------------------------------------------------------------
    # HAJ-221 — MATTE CONTEXT LINE
    # One-line state snapshot of both judoka right after a Matte call.
    # The composure/stamina state at the reset gives the player a sense of
    # who's tiring without having to track tick-by-tick numerics. Coach
    # stream only; the engineering [ref] MATTE_CALLED line carries the
    # substrate data.
    # -----------------------------------------------------------------------
    def _build_matte_context_event(self, tick: int) -> Event:
        a = self.fighter_a
        b = self.fighter_b
        a_phrase = _judoka_state_phrase(a)
        b_phrase = _judoka_state_phrase(b)
        prose = (
            f"{a.identity.name} {a_phrase}; "
            f"{b.identity.name} {b_phrase}."
        )
        return Event(
            tick=tick,
            event_type="MATTE_CONTEXT",
            description=f"[matte_context] {prose}",
            data={
                "prose_silent": True,
                "coach_prose":  prose,
                "fighter_a":    a.identity.name,
                "fighter_b":    b.identity.name,
                "a_composure":  a.state.composure_current,
                "b_composure":  b.state.composure_current,
                "a_cardio":     a.state.cardio_current,
                "b_cardio":     b.state.cardio_current,
            },
        )

    # -----------------------------------------------------------------------
    # MATTE HANDLING — resets match state for next exchange
    # -----------------------------------------------------------------------
    def _handle_matte(self, tick: int) -> None:
        """Reset the sub-loop for the next exchange after a Matte call.

        HAJ-139 — delegates to _reset_dyad_to_distant. Matte uses the
        baseline closing phase (no extra recovery): the matte announcement
        itself is the prose beat, and the standard 3-tick floor handles
        the walk-back rhythm.

        HAJ-129 — also drops any stranded throws_in_progress so the post-
        matte standing tick doesn't fire stale "grips collapsed" abort
        lines for a throw that was parked when ne-waza started. A matte
        cleanly ends the prior exchange.

        HAJ-152 — close any active post-score follow-up window. Matte
        from the standard ne-waza patience clock (called via the
        post-tick check) is one of the three ne-waza exits the
        follow-up routes through; clearing the bookkeeping here keeps
        the state from leaking into the next exchange. Drop any
        queued POST_SCORE_FOLLOW_UP_MATTE consequence too — the matte
        we're handling now satisfies the same beat.

        HAJ-222 — drop every pending throw-resolution consequence
        for both judoka. Pre-fix, only POST_SCORE_FOLLOW_UP_MATTE
        was filtered, which meant a RESOLVE_KAKE_N1 / RESOLVE_DRIVE_THROW
        consequence queued at commit time could fire several ticks after
        matte and emit a stale "throw failed" event for an attempt the
        referee had already declared dead (the t035 stray failure event
        from seed 1974183401). Also drop FIRE_COMMIT_FROM_INTENT and
        NEWAZA_TRANSITION_AFTER_STUFF: once the dyad has reset, neither
        the commit nor the ne-waza door should fire from the prior
        exchange's intent.

        HAJ-235 — also drop GRIP_INIT_RECOMPUTE. It is queued when an
        attack fails so grip initiative is recomputed a tick or two later;
        but if a matte intervenes (e.g. the stuffed-throw reset that
        *follows* the same failed attack), the dyad is already broken back
        to STANDING_DISTANT and a pending recompute is stale. Pre-fix it
        fired during the matte→hajime freeze and emitted a `[grip_init]`
        line in the dead window (seed 1, t076).
        """
        self._throws_in_progress.clear()
        self._post_score_follow_up = None
        _DROPPED_ON_MATTE = {
            "POST_SCORE_FOLLOW_UP_MATTE",
            "RESOLVE_KAKE_N1",
            "RESOLVE_DRIVE_THROW",
            "FIRE_COMMIT_FROM_INTENT",
            "NEWAZA_TRANSITION_AFTER_STUFF",
            "GRIP_INIT_RECOMPUTE",
        }
        self._consequence_queue = [
            c for c in self._consequence_queue
            if c.kind not in _DROPPED_ON_MATTE
        ]
        self._reset_dyad_to_distant(tick, recovery_bonus=0)
        # HAJ-160 — queue the restart-hajime announcement so the viewer's
        # hajime banner fires at every restart, not only at match start.
        # Triage 2026-05-02 (Priority 2 fix from playthrough): the gap
        # between matte and hajime was 1 tick (≈1 s of game time) which
        # left no breathing room — the matte banner never sat on screen
        # before hajime overwrote it. Stretching to 3 ticks gives the
        # matte banner a real beat where coach instructions could land
        # later, and a clean hajime restart after.
        self._pending_hajime_tick = tick + MATTE_TO_HAJIME_PAUSE_TICKS

    def _reset_to_standing_after_newaza(self, tick: int) -> None:
        """HAJ-185 / HAJ-228 — atomic reset to standing after a ne-waza exit
        that is NOT a submission victory: escape-to-standing (ESCAPE_SUCCESS)
        or catalog submission released/abandoned (SUBMISSION_RELEASED).

        Resets the ne-waza resolver, drops any standing throw parked when
        ne-waza began (so the next standing tick doesn't fire a stale
        "grips collapsed" abort), closes any post-score follow-up window,
        and seats the dyad at STANDING_DISTANT with the post-score recovery
        bonus — getting up off the mat eats real time before the next grip
        can seat.

        HAJ-228 — schedules the restart Hajime (and the HAJ-235 matte→hajime
        freeze) the same way a referee-called matte does. Pre-fix this reset
        seated the dyad at distance and the narrator emitted the ne_waza→
        closing phase line "Matte — they're back on their feet", but no
        Hajime was ever scheduled, so the match silently resumed with no
        restart call (2026-06-04 triage, Cluster 2.2, t013).

        HAJ-152 AC#7 — the post-score-chase escape still "resumes tachi-waza
        without matte" in the sense that no POST_SCORE_FOLLOW_UP_MATTE
        consequence is queued; clearing `_post_score_follow_up` here keeps
        that bookkeeping clean. The restart Hajime is the symmetric beat for
        the "Matte — back on their feet" line, not a post-score-end matte.
        """
        self.ne_waza_resolver.reset(self.osaekomi)
        self._throws_in_progress.clear()
        self._post_score_follow_up = None
        self._reset_dyad_to_distant(
            tick, recovery_bonus=POST_SCORE_RECOVERY_TICKS,
        )
        self.ne_waza_top_id = None
        self._pending_hajime_tick = tick + MATTE_TO_HAJIME_PAUSE_TICKS

    def _post_score_reset(self, tick: int, reason: str) -> list[Event]:
        """HAJ-139 — reset the dyad to STANDING_DISTANT after a non-match-
        ending score landing (waza-ari, downgraded NO_SCORE).

        Emits a SCORE_RESET event for prose visibility and dispatches
        through the shared _reset_dyad_to_distant helper with the
        post-score recovery bonus so the closing-phase pause is a beat
        longer than first-engagement (gi adjust, walk back to mark).
        """
        self._reset_dyad_to_distant(
            tick, recovery_bonus=POST_SCORE_RECOVERY_TICKS,
        )
        return [Event(
            tick=tick,
            event_type="SCORE_RESET",
            description=(
                f"[reset] Both fighters return to engagement distance "
                f"after {reason}."
            ),
            data={"reason": reason,
                  "recovery_bonus": POST_SCORE_RECOVERY_TICKS},
        )]

    # -----------------------------------------------------------------------
    # HAJ-159 — STANDING_DISTANT seating helper
    # -----------------------------------------------------------------------
    def _seat_at_distant_pose(self) -> None:
        """Place both fighters at STANDING_DISTANT_SEPARATION_M apart,
        facing each other across the mat origin.

        Called from `begin()` (match start) and `_reset_dyad_to_distant`
        (every matte / post-score reset). The closing-phase STEP_IN
        action in action_selection covers the gap into engagement
        distance over the next few ticks; the wider seating is what
        gives the closing motion something visible to traverse.
        """
        from body_state import place_judoka as _place
        half = STANDING_DISTANT_SEPARATION_M / 2.0
        _place(self.fighter_a, com_position=(-half, 0.0), facing=(1.0, 0.0))
        _place(self.fighter_b, com_position=(+half, 0.0), facing=(-1.0, 0.0))

    # -----------------------------------------------------------------------
    # POST-SCORE / POST-MATTE — shared dyad reset to STANDING_DISTANT
    # -----------------------------------------------------------------------
    def _clear_kuzushi_buffers(self) -> None:
        """HAJ-227 — drop every fighter's decaying kuzushi buffer.

        The buffer (`Judoka.kuzushi_events`) only ages via the deque cap and
        the 5-tick half-life decay, so without an explicit clear, impulses
        from the prior exchange persist into the next phase and surface as
        ghost off-balance state on the ground, after a matte, after the match
        ends, and before the first grip of the next exchange. Called on every
        hard boundary — matte / post-score / reset-to-standing (all via
        `_reset_dyad_to_distant`) and match end (`_end_match`) — so each new
        exchange starts from a clean off-balance state.
        """
        self.fighter_a.kuzushi_events.clear()
        self.fighter_b.kuzushi_events.clear()

    def _reset_dyad_to_distant(self, tick: int, recovery_bonus: int = 0) -> None:
        """Reset the dyad to STANDING_DISTANT and seed the closing phase.

        HAJ-139 — extracted from _handle_matte so post-score awards
        (waza-ari, NO_SCORE-downgraded landings) can dispatch through the
        same path. Match-side dispatch points:

          - _handle_matte (recovery_bonus=0)
          - _apply_throw_result post-WAZA_ARI / post-NO_SCORE
            (recovery_bonus=POST_SCORE_RECOVERY_TICKS)

        recovery_bonus pre-decrements engagement_ticks below zero so the
        closing-phase floor takes that many extra ticks to clear before
        the next grip can seat. With STANDING_DISTANT short-circuiting
        select_actions to REACH (HAJ-141), engagement_ticks accumulates
        monotonically and the bonus is honored.
        """
        # Break all edges
        self.grip_graph.break_all_edges()
        # HAJ-224 — drop any pending off-hand seat; the leader's lead grip
        # is gone, so there is nothing for the second beat to build on.
        self._pending_off_hand = None
        # HAJ-185 — single ne-waza reset surface. The resolver clears its
        # own active_technique and breaks the osaekomi atomically so the
        # next ground entry starts in NeWazaState.TRANSITIONAL.
        self.ne_waza_resolver.reset(self.osaekomi)
        self.ne_waza_top_id = None
        # Reset sub-loop to standing + physics state.
        self._stuffed_throw_tick = 0
        self.sub_loop_state      = SubLoopState.STANDING
        self.engagement_ticks    = -recovery_bonus
        self.stalemate_ticks     = 0
        self._a_was_kuzushi_last_tick = False
        self._b_was_kuzushi_last_tick = False
        # HAJ-227 — clear the decaying kuzushi buffer on the reset. Without
        # this the deque only ages via maxlen + 5-tick half-life, so prior-
        # exchange impulses bleed ~4-5 ticks into the next phase (the ground,
        # post-matte, and pre-first-grip "kuzushi with no grips" ghosts). This
        # is the shared boundary for matte, post-score, and reset-to-standing.
        self._clear_kuzushi_buffers()
        self.position = Position.STANDING_DISTANT
        # Reset postures + CoM velocity/position for a clean re-engage.
        # HAJ-128 — also reset feet via place_judoka so a reset after a
        # throw / ne-waza chunk doesn't leave foot dots stranded where
        # the displacement happened.
        # HAJ-159 — seat the dyad at STANDING_DISTANT_SEPARATION_M
        # (~3 m), not the legacy ~1 m, so the rendered post-matte resume
        # actually shows a gap. Closing-phase STEP_IN actions cover the
        # distance over the recovery + reach-tick window.
        for f in (self.fighter_a, self.fighter_b):
            f.state.body_state.trunk_sagittal = 0.0
            f.state.body_state.trunk_frontal  = 0.0
            f.state.body_state.com_velocity   = (0.0, 0.0)
        self._seat_at_distant_pose()

    # -----------------------------------------------------------------------
    # HELPERS
    # -----------------------------------------------------------------------
    def _compute_stance_matchup(self) -> StanceMatchup:
        return StanceMatchup.of(
            self.fighter_a.state.current_stance,
            self.fighter_b.state.current_stance,
        )

    def _evaluate_stance_switches(self, tick: int, events: list[Event]) -> None:
        """HAJ-232 Phase 1 — per-tick dynamic stance.

        For each fighter, decide whether they shift stance this tick: either
        deliberately (to deny the opponent their matchup / open their own
        kenka-yotsu game) or rotated off involuntarily by losing the grip war.
        Each decision draws from its own seeded RNG so it never perturbs the
        other RNG streams. A switch flips `current_stance`, opens the settling
        window, and emits a STANCE_CHANGE event into the live stance thread.
        """
        matchup = self._compute_stance_matchup()
        for fighter, opponent in (
            (self.fighter_a, self.fighter_b),
            (self.fighter_b, self.fighter_a),
        ):
            # Opponent's grip advantage over this fighter — positive means this
            # fighter is losing the grip war (the forced-switch pressure signal).
            grip_delta_against = self.grip_graph.compute_grip_delta(
                opponent, fighter, matchup
            )
            rng = random.Random(
                f"haj232:stance:{fighter.identity.name}:{self.seed}:{tick}"
            )
            decision = stance_mod.evaluate_switch(
                fighter, opponent,
                matchup=matchup,
                grip_delta_against=grip_delta_against,
                rng=rng,
            )
            if decision is None:
                continue
            self._apply_stance_switch(fighter, decision, tick, events)
            # Recompute so the second fighter's decision reads the live matchup
            # this tick rather than the pre-switch one.
            matchup = self._compute_stance_matchup()

    def _apply_stance_switch(
        self, fighter: Judoka, decision, tick: int, events: list[Event],
    ) -> None:
        """Apply a stance switch: flip the stance, open the settling window,
        and emit the stance-thread event (debug line + mat-side prose)."""
        old_stance = fighter.state.current_stance
        fighter.state.current_stance = decision.target
        fighter.state.stance_settling_ticks = stance_mod.STANCE_SETTLING_TICKS
        matchup_after = self._compute_stance_matchup()
        nickname = stance_mod.matchup_nickname(matchup_after)
        name = fighter.identity.name
        events.append(Event(
            tick=tick, event_type="STANCE_CHANGE",
            description=(
                f"[stance] {name} switches to {decision.target.name.lower()} "
                f"({decision.reason}) — now {matchup_after.name} ({nickname})"
            ),
            data={
                "fighter": name,
                "old_stance": old_stance.name,
                "new_stance": decision.target.name,
                "reason": decision.reason,
                "matchup_after": matchup_after.name,
                "coach_prose": stance_mod.stance_change_coach_prose(
                    name, decision.target, matchup_after, decision.reason,
                ),
            },
            significance=4,
        ))

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
            fighter_a_region=region_of(self.fighter_a).name,
            fighter_b_region=region_of(self.fighter_b).name,
            golden_score=self.golden_score,
        )

    def _ne_waza_top(self) -> Judoka:
        if self.ne_waza_top_id == self.fighter_b.identity.name:
            return self.fighter_b
        return self.fighter_a

    def _ne_waza_bottom(self) -> Judoka:
        if self.ne_waza_top_id == self.fighter_b.identity.name:
            return self.fighter_a
        return self.fighter_b

    def _maybe_step_out_voluntary(
        self, perceiver: Judoka, attacker: Judoka,
        sig, tick: int, events: list[Event],
    ) -> bool:
        """HAJ-142 — voluntary OOB step as a shido-eat. Fires when:

          - perceiver is in WARNING
          - the intent signal is a throw_commit
          - perceiver is under composure / desperation pressure
            (low composure OR defensive desperation active)
          - perceiver has enough fight_iq to weigh shido vs throw

        Effect: perceiver's CoM lands just past the nearest boundary,
        the staged commit is cancelled (FIRE_COMMIT_FROM_INTENT
        dropped), the placeholder _ThrowInProgress entry is freed,
        and a STEP_OUT_VOLUNTARY engine event fires. The OOB Matte
        + shido on the next tick falls out of the existing HAJ-127
        path. Returns True if the step-out fires (caller should skip
        the regular BRACE / NONE response handling)."""
        from enums import MatRegion as _MR
        from intent_signal import SETUP_THROW_COMMIT as _SETUP_TC
        if sig.setup_class != _SETUP_TC:
            return False
        if region_of(perceiver) is not _MR.WARNING:
            return False
        in_def_desp = self._defensive_desperation_active.get(
            perceiver.identity.name, False,
        )
        composure_ratio = (
            perceiver.state.composure_current
            / max(1.0, float(perceiver.capability.composure_ceiling))
        )
        if not (in_def_desp or composure_ratio < 0.4):
            return False
        iq = getattr(perceiver.capability, "fight_iq", 0)
        # Lower IQ → can't read the threat / weigh the trade. The
        # gate sits above white-belt territory; v0.2 calibration may
        # shift this up or down.
        if iq < 6:
            return False
        rng = random.Random(
            f"haj142:stepout:{perceiver.identity.name}:{self.seed}:{tick}"
        )
        # Probabilistic so it doesn't fire every time the gate opens —
        # ~50% under desperation, ~25% under low-composure-only.
        prob = 0.5 if in_def_desp else 0.25
        if rng.random() > prob:
            return False
        # Place perceiver just past the nearest boundary on whichever
        # axis they're closer to the line on.
        bx, by = perceiver.state.body_state.com_position
        ax = MAT_HALF_WIDTH - abs(bx)
        ay = MAT_HALF_WIDTH - abs(by)
        epsilon = 0.05  # land clearly OOB (visible to the OOB check).
        if ax <= ay:
            sx = (MAT_HALF_WIDTH + epsilon) * (1.0 if bx >= 0 else -1.0)
            sy = by
        else:
            sx = bx
            sy = (MAT_HALF_WIDTH + epsilon) * (1.0 if by >= 0 else -1.0)
        perceiver.state.body_state.com_position = (sx, sy)
        # Cancel the attacker's staged commit. Pre-fix the throw would
        # still fire on N+1 even though the dyad is heading to Matte;
        # v0.1 cleanly cancels the FIRE_COMMIT_FROM_INTENT consequence
        # and frees the placeholder entry so the engine doesn't carry
        # phantom in-progress state into the reset.
        a_name = attacker.identity.name
        self._consequence_queue = [
            c for c in self._consequence_queue
            if not (
                c.kind == "FIRE_COMMIT_FROM_INTENT"
                and c.payload.get("attacker_name") == a_name
            )
        ]
        self._throws_in_progress.pop(a_name, None)
        events.append(Event(
            tick=tick, event_type="STEP_OUT_VOLUNTARY",
            description=(
                f"[shido-eat] {perceiver.identity.name} steps over the "
                f"line — voluntary OOB rather than face "
                f"{attacker.identity.name}'s {sig.setup_class}."
            ),
            data={
                "perceiver": perceiver.identity.name,
                "attacker": a_name,
                "throw_id": (sig.throw_id.name
                             if sig.throw_id is not None else None),
                "voluntary": True,
            },
        ))
        return True

    def _maybe_crawl_toward_boundary(self, tick: int) -> list[Event]:
        """HAJ-142 — bottom-fighter ne-waza geometry as defense.

        Real bottom-game judo: when pinned or under threat, a savvy
        bottom fighter uses position to escape — crawl toward the line
        until you slide out and Matte breaks the hold. The engine had
        no representation of this. Here: when the bottom is in the
        WORKING or WARNING band, probabilistically nudge their CoM
        (and the top fighter's, since the dyad is tangled) toward the
        nearest boundary. Probability scales with ne-waza skill and
        boundary closeness; exiting OOB triggers the existing HAJ-127
        Matte path, breaking the pin.

        Out of scope here: a deliberate per-tick action ladder pick.
        v0.1 ships this as a per-tick CoM drift; v0.2 can promote it
        to an explicit selectable action.
        """
        from enums import MatRegion as _MR
        bottom = self._ne_waza_bottom()
        if bottom is None:
            return []
        # Only crawl when there's something to escape from — pin,
        # active sub, or technique chain. A neutral guard exchange
        # doesn't motivate a crawl.
        under_threat = (
            self.osaekomi.active
            or self.ne_waza_resolver.active_technique is not None
        )
        if not under_threat:
            return []
        region = region_of(bottom)
        if region not in (_MR.WORKING, _MR.WARNING):
            return []
        bx, by = bottom.state.body_state.com_position
        # Probability: warning band gets a higher base; ne-waza skill
        # bumps it further. White belts (skill 0-3) crawl ~5%; elite
        # (skill 9-10) crawl ~30% per tick in WARNING.
        ne_skill = getattr(bottom.capability, "ne_waza_skill", 5) / 10.0
        if region is _MR.WARNING:
            prob = 0.10 + ne_skill * 0.20
        else:
            prob = 0.03 + ne_skill * 0.07
        rng = random.Random(
            f"haj142:crawl:{bottom.identity.name}:{self.seed}:{tick}"
        )
        if rng.random() > prob:
            return []
        # Direction: nearest boundary on whichever axis the bottom is
        # closer to the line on. Move both fighters together since the
        # dyad is tangled.
        ax = MAT_HALF_WIDTH - abs(bx)
        ay = MAT_HALF_WIDTH - abs(by)
        if ax <= ay:
            sx = 1.0 if bx >= 0 else -1.0
            sy = 0.0
        else:
            sx = 0.0
            sy = 1.0 if by >= 0 else -1.0
        # Crawl distance per tick — small but accumulates. ~0.20 m
        # means ~2-4 ticks from WARNING to OOB depending on starting
        # position.
        crawl_distance = 0.20
        for f in (bottom, self._ne_waza_top()):
            if f is None:
                continue
            cx, cy = f.state.body_state.com_position
            f.state.body_state.com_position = (
                cx + sx * crawl_distance,
                cy + sy * crawl_distance,
            )
        return [Event(
            tick=tick,
            event_type="CRAWL_TOWARD_BOUNDARY",
            description=(
                f"[ne-waza] {bottom.identity.name} inches toward the line."
            ),
            data={
                "fighter": bottom.identity.name,
                "region": region.name,
                "direction": (sx, sy),
                "distance": crawl_distance,
            },
        )]

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
        # HAJ-74 — in golden score, cardio drain escalates linearly with
        # elapsed GS time, shaved by cardio_efficiency. Posture surcharge
        # is multiplied too: bending forward in overtime is even costlier.
        mult = self._cardio_drain_multiplier(judoka)
        s.cardio_current = max(0.0, s.cardio_current - CARDIO_DRAIN_PER_TICK * mult)
        if s.body_state.trunk_sagittal > UPRIGHT_LIMIT_RAD:
            s.cardio_current = max(0.0, s.cardio_current - POSTURE_BENT_CARDIO_DRAIN * mult)

    def _cardio_drain_multiplier(self, judoka: Judoka) -> float:
        """HAJ-74 — golden-score drain multiplier for `judoka` this tick.

        Returns 1.0 in regulation. In golden score, returns the linear
        escalator from `golden_score_cardio_multiplier`, indexed by elapsed
        GS ticks and the fighter's cardio_efficiency stat.
        """
        if not self.golden_score or self.golden_score_start_tick is None:
            return 1.0
        elapsed = max(0, self.ticks_run - self.golden_score_start_tick)
        return golden_score_cardio_multiplier(
            elapsed_gs_ticks=elapsed,
            cardio_efficiency=judoka.capability.cardio_efficiency,
        )

    def _decay_stun(self, judoka: Judoka) -> None:
        if judoka.state.stun_ticks > 0:
            judoka.state.stun_ticks -= 1
        # Part 6.3: clear the compromised-state tag once the recovery window
        # closes. Uke's per-state counter-bonus expires at the same moment.
        if judoka.state.stun_ticks == 0:
            self._compromised_states.pop(judoka.identity.name, None)

    def _decay_stance_settling(self, judoka: Judoka) -> None:
        """HAJ-232 — tick down the post-switch settling window. While it is
        positive the fighter pays the flat grip-initiative penalty and is
        locked out of switching again."""
        if judoka.state.stance_settling_ticks > 0:
            judoka.state.stance_settling_ticks -= 1

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

        HAJ-141 — the `if owned` gate is what anchors the kumi-kata clock
        to first-grip-seated rather than to hajime. While the dyad is in
        STANDING_DISTANT (no edges have seated yet), no fighter owns any
        grip, so the clock stays at 0 across the whole closing phase. The
        first tick the fighter can be passive about kumi-kata is the tick
        their first grip exists — which is the spec's intent (Part 2.6:
        "from the moment a judoka establishes any grip, they have 30
        seconds to make an attack").
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

            # HAJ-235 — defer the award to the matte→shido→hajime ceremony
            # resolved in _post_tick instead of emitting it inline mid-
            # exchange. Detection (and the clock resets above) stays here;
            # the stoppage, shido announcement, and hajime restart land
            # together. One penalty is bracketed per tick, so stop here.
            self._queue_penalty_shido(fighter, reason)
            break

    def _queue_penalty_shido(self, fighter: Judoka, reason: str) -> None:
        """HAJ-235 — stash a passivity / non-combativity shido for the
        matte→shido→hajime ceremony resolved in `_award_pending_penalty`
        from `_post_tick`.

        Detection sites (`_update_grip_passivity`, `_update_passivity`)
        run in the tick body and call this in place of emitting the shido
        inline. At most one penalty is bracketed per tick — a stoppage can
        carry only one matte — so the first detected this tick wins.
        """
        if self._pending_penalty is None:
            self._pending_penalty = {"fighter": fighter, "reason": reason}

    def _award_pending_penalty(self, tick: int, events: list[Event]) -> None:
        """HAJ-235 — resolve a deferred penalty shido as a real-judo
        ceremony: Matte (stop the action) → shido announcement → Hajime
        (restart). Called from `_post_tick` after a tick whose body queued
        a penalty via `_queue_penalty_shido`.

        The matte announcement + `_handle_matte` reset reuse the Part 1
        freeze: `_handle_matte` sets `_pending_hajime_tick`, so the dyad
        is frozen at STANDING_DISTANT through the pause and Hajime fires at
        the end of it. A third shido is hansoku-make — the match ends and
        no restart is queued.
        """
        penalty = self._pending_penalty
        self._pending_penalty = None
        if penalty is None:
            return
        fighter = penalty["fighter"]
        reason  = penalty["reason"]
        name    = fighter.identity.name

        # Matte first — the action stops before the penalty is announced.
        events.append(self.referee.announce_matte(MatteReason.PENALTY, tick))
        # Then the shido itself.
        fighter.state.shidos += 1
        events.append(Event(
            tick=tick,
            event_type="SHIDO_AWARDED",
            description=(
                f"[ref: {self.referee.name}] Shido — "
                f"{name} ({reason}). "
                f"Total: {fighter.state.shidos}."
            ),
            data={"fighter": name, "reason": reason, "ceremony": True},
        ))
        # Third shido = hansoku-make: the match ends here, no restart.
        if fighter.state.shidos >= 3:
            opponent = (self.fighter_b if fighter is self.fighter_a
                        else self.fighter_a)
            self._end_match(opponent, "hansoku-make", tick, events)
            return
        # Otherwise reset the dyad and queue the Hajime restart (the
        # Part 1 freeze covers the matte→hajime gap).
        events.append(self._build_matte_context_event(tick))
        self._handle_matte(tick)

    def _update_edge_zone_counters_and_shido(
        self, tick: int, events: list[Event],
    ) -> None:
        """HAJ-156 push-out shido bookkeeping.

        For each fighter:
          - If they're inside the edge zone (within EDGE_ZONE_M of any
            boundary), increment time_in_edge_zone and stash the entry
            tick for the "who got there first" tie-break.
          - If they're back in the safe zone (>SAFE_ZONE_M from every
            boundary), reset the counter and entry-tick.
          - Otherwise (in the no-man's-land between EDGE_ZONE_M and
            SAFE_ZONE_M), hold the counter steady — neither retreating
            into edge nor recovering to centre.

        Shido fires when a fighter's time_in_edge_zone exceeds the
        ref's `_PUSH_OUT_SHIDO_TICKS` threshold AND that fighter's
        last STEP was retreating-class. The shido goes to the
        retreating fighter, not the pressing one — IJF non-combativity
        rule: backing yourself toward the boundary is the punished
        behaviour, not pressuring someone else there.
        """
        for fighter in (self.fighter_a, self.fighter_b):
            com = fighter.state.body_state.com_position
            edge_dist = _distance_to_nearest_edge(com)
            if edge_dist <= EDGE_ZONE_M:
                # Inside the edge zone. First entry stamps the tick;
                # subsequent ticks accumulate the counter.
                if fighter.state.edge_zone_entry_tick < 0:
                    fighter.state.edge_zone_entry_tick = tick
                fighter.state.time_in_edge_zone += 1
            elif edge_dist >= SAFE_ZONE_M:
                # Back in the safe central area — reset.
                fighter.state.time_in_edge_zone = 0
                fighter.state.edge_zone_entry_tick = -1
            # Else: between EDGE_ZONE_M and SAFE_ZONE_M; hold counter.

        # Decide the shido. Walk both fighters; emit at most one shido
        # per tick (the retreating fighter at threshold). When both
        # fighters are at threshold simultaneously, the earlier-
        # arriving fighter eats it — they were the one being driven.
        threshold = self.referee._PUSH_OUT_SHIDO_TICKS
        candidates = [
            f for f in (self.fighter_a, self.fighter_b)
            if f.state.time_in_edge_zone >= threshold
            and f.state.last_move_direction_sign < 0
        ]
        if not candidates:
            return
        # Pick the earliest entrant.
        candidates.sort(key=lambda f: f.state.edge_zone_entry_tick)
        retreater = candidates[0]
        # Emit the shido through the same path the existing passivity
        # code uses so accumulation toward hansoku-make is consistent.
        retreater.state.shidos += 1
        events.append(Event(
            tick=tick,
            event_type="SHIDO_AWARDED",
            description=(
                f"[ref: {self.referee.name}] Shido — "
                f"{retreater.identity.name} (push-out / non-combativity at edge). "
                f"Total: {retreater.state.shidos}."
            ),
            data={
                "fighter": retreater.identity.name,
                "reason":  "push_out",
                "time_in_edge_zone": retreater.state.time_in_edge_zone,
            },
        ))
        # Reset the counter so the same fighter doesn't draw a second
        # shido on the very next tick — they get one shido per
        # sustained edge stay; if they don't move out and back in,
        # the counter is back at zero now anyway.
        retreater.state.time_in_edge_zone = 0
        retreater.state.edge_zone_entry_tick = -1
        if retreater.state.shidos >= 3:
            opponent = (self.fighter_b if retreater is self.fighter_a
                        else self.fighter_a)
            self._end_match(opponent, "hansoku-make", tick, events)

    def _update_passivity(self, tick: int, events: list[Event]) -> None:
        # "Active" = fighter attempted a throw within the last 30 ticks
        for fighter in (self.fighter_a, self.fighter_b):
            was_active = self._last_attack_tick.get(fighter.identity.name, 0) >= tick - 30
            shido = self.referee.update_passivity(
                fighter.identity.name, was_active, tick
            )
            if shido:
                # HAJ-235 — defer to the matte→shido→hajime ceremony
                # (_award_pending_penalty in _post_tick) rather than
                # emitting inline. One penalty is bracketed per tick.
                self._queue_penalty_shido(fighter, shido.reason)
                break

    # -----------------------------------------------------------------------
    # OUTPUT
    # -----------------------------------------------------------------------
    def _print_events(self, events: list[Event]) -> None:
        for ev in events:
            if ev.data.get("silent"):
                continue
            # HAJ-148 — events flagged prose_silent surface only on the
            # engineer (debug) stream; the prose stream and the prose half
            # of the side-by-side view skip them. Used by THROW_ENTRY so
            # commits are silent in prose (the resolution prose on tick
            # N+1 carries the visible beat).
            #
            # HAJ-221 — a `coach_prose` override on the event lets the
            # coach stream render a narrative-first phrasing while the
            # debug stream keeps the engineering description. The override
            # also wins over `prose_silent`: events like GRIP_CASCADE_RESPONSE
            # are silent in the legacy prose path by description, but the
            # coach_prose narrative line is exactly what the coach stream
            # should surface.
            prose_silent = bool(ev.data.get("prose_silent"))
            coach_prose  = ev.data.get("coach_prose")
            if _is_coach_stream(self._stream):
                # HAJ-221 — coach_prose wins regardless of debug-only /
                # prose_silent flagging. Throw sub-events (SUB_*) are
                # debug-only by default; the body-part narration line
                # rides on the same event so we surface it here.
                #
                # Each coach line is prefixed with the countdown match
                # clock (M:SS), matching the format the "both" stream
                # uses on its prose column. The clock lets the reader
                # correlate beats with match time without losing the
                # uncluttered narrative read.
                clock = _format_match_clock(self._clock_remaining(ev.tick))
                if coach_prose:
                    print(f"{clock}  {_render_prose(str(coach_prose))}")
                    continue
                if _is_debug_only_event(ev.event_type):
                    continue
                if prose_silent:
                    continue
                print(f"{clock}  {_render_prose(ev.description)}")
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
            # HAJ-221 — coach_prose wins over the debug-only / prose_silent
            # filters here too, so sub-event body-part narration shows up
            # on the prose side while the engineer-side label stays put.
            if coach_prose:
                clock = _format_match_clock(self._clock_remaining(ev.tick))
                prose_line = f"{clock}  {_render_prose(str(coach_prose))}"
            elif _is_debug_only_event(ev.event_type) or prose_silent:
                prose_line = ""
            else:
                clock = _format_match_clock(self._clock_remaining(ev.tick))
                prose_line = f"{clock}  {_render_prose(ev.description)}"
            print(_render_side_by_side(debug_line, prose_line))

    def _print_kuzushi_buffer_debug(self, tick: int) -> None:
        """Instrumentation — surface the decaying kuzushi buffer's internals on
        the debug stream so the kuzushi model is observable tick-by-tick.

        Read-only: this method computes nothing that feeds back into the sim
        (it re-reads the same `compromised_state` / `dominant_kuzushi_source`
        the off-balance signal already consumes). It emits two line kinds,
        both `[kuzushi]`-tagged and tick-stamped like the engineer event lines:

          * a DEPOSIT line for each event emitted THIS tick
            (``tick_emitted == tick``) — its source, raw magnitude
            contribution, and unit vector — so a deposit and its subsequent
            decay across following ticks are both legible; and
          * a per-fighter BUFFER readout on ticks where the buffer is
            non-empty: the resultant (threshold-compared) magnitude `mag`, the
            uncancelled total `tot`, the resultant unit direction `dir`, the
            dominant source `dom`, and the live-event count `n`.

        Debug stream only — the coach/prose streams are untouched, and `both`
        is left alone so its side-by-side layout stays aligned.

        HAJ-227 — the dump is gated hard. Beyond the engineer stream it
        requires the dedicated `--debug-kuzushi` verbosity flag, and it is
        suppressed everywhere the readout is noise or a ghost rather than a
        live signal: after the match is over, off the feet (the off-balance
        signal isn't even computed in ne-waza, so any line there is pure
        debug noise), and with no grips established (decayed impulses from a
        prior exchange that no longer describe a live contest).
        """
        if self._stream != "debug" or not self._debug_kuzushi:
            return
        if self.match_over:
            return
        if self.sub_loop_state != SubLoopState.STANDING:
            return
        if self.grip_graph.edge_count() == 0:
            return
        from kuzushi import compromised_state, dominant_kuzushi_source
        for fighter in (self.fighter_a, self.fighter_b):
            name = fighter.identity.name
            buf = fighter.kuzushi_events
            # Deposit lines: events stamped this tick (a fresh contribution).
            for ev in buf:
                if ev.tick_emitted == tick:
                    vx, vy = ev.vector
                    print(
                        f"t{tick:03d}: [kuzushi] {name} +{ev.source_kind.name} "
                        f"mag={ev.magnitude:.1f} vec=({vx:+.2f},{vy:+.2f})"
                    )
            # Buffer readout: only on ticks where the buffer holds events.
            if not buf:
                continue
            cs = compromised_state(buf, tick)
            rx, ry = cs.vector
            rmag = math.hypot(rx, ry)
            if rmag > 1e-9:
                dir_s = f"({rx / rmag:+.2f},{ry / rmag:+.2f})"
            else:
                dir_s = "(net-cancelled)"
            dom = dominant_kuzushi_source(buf, tick)
            dom_s = dom.name if dom is not None else "-"
            print(
                f"t{tick:03d}: [kuzushi] {name} buf "
                f"mag={cs.magnitude:.1f} tot={cs.total_decayed_magnitude:.1f} "
                f"dir={dir_s} dom={dom_s} n={len(buf)}"
            )

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
        # HAJ-232 — this is now the *opening* state of a live stance thread:
        # the matchup can change mid-match as fighters switch stance, each
        # shift emitting a STANCE_CHANGE event into the stream.
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

    # -----------------------------------------------------------------------
    # HAJ-93 — match-end + golden score
    # -----------------------------------------------------------------------
    def _end_match(
        self,
        winner: Optional[Judoka],
        method: str,
        tick: int,
        events: list[Event],
    ) -> None:
        """Centralized match-end helper.

        Sets winner / win_method / match_over and emits a single
        MATCH_ENDED Event with a uniform payload (winner, method, tick,
        golden_score, score state). Every code path that ends the match
        (throw IPPON, two waza-ari, golden-score waza-ari, pin scores,
        third shido / hansoku-make, ne-waza submission, regulation-end
        decision) routes through here so downstream consumers get a
        consistent end-of-match signal.
        """
        # First-writer-wins: if some other path already ended the match
        # this tick, don't overwrite or double-emit.
        if self.match_over:
            return
        self.winner = winner
        self.win_method = method
        self.match_over = True
        # HAJ-227 — clear the kuzushi buffer at match end so no stale
        # off-balance state lingers past the final whistle (the print is
        # already gated on `match_over`, but clearing keeps any post-match
        # buffer read clean and matches the other hard boundaries).
        self._clear_kuzushi_buffers()
        a, b = self.fighter_a, self.fighter_b
        if winner is not None:
            desc = (
                f"[ref: {self.referee.name}] Match ends — "
                f"{winner.identity.name} wins by {method}."
            )
        else:
            desc = f"[ref: {self.referee.name}] Match ends — draw."
        events.append(Event(
            tick=tick,
            event_type="MATCH_ENDED",
            description=desc,
            data={
                "winner":       winner.identity.name if winner else None,
                "method":       method,
                "tick":         tick,
                "golden_score": self.golden_score,
                "a_waza_ari":   a.state.score["waza_ari"],
                "b_waza_ari":   b.state.score["waza_ari"],
                "a_shidos":     a.state.shidos,
                "b_shidos":     b.state.shidos,
            },
        ))

    def _check_regulation_end(self, tick: int, events: list[Event]) -> None:
        """HAJ-95 + HAJ-93 — at the regulation boundary, emit a single
        `TIME_EXPIRED` event (HAJ-95) and route the match into golden
        score (if waza-ari counts are tied) or resolve by decision (if
        unequal — HAJ-93 / HAJ-68 paths 3, 4). Called once from
        `_post_tick` when `tick >= regulation_ticks` and the match is
        still live.

        Tie includes 0-0: per IJF rules, a scoreless regulation enters
        golden score, not a draw. Decision uses waza-ari counts only;
        ippon at this point would already have ended the match earlier.
        TIME_EXPIRED fires before either branch so coach-stream readers
        always see the regulation-end beat as its own visible line.
        """
        if self.match_over or self.golden_score:
            return
        a, b = self.fighter_a, self.fighter_b
        a_wa = a.state.score["waza_ari"]
        b_wa = b.state.score["waza_ari"]
        # HAJ-95 — single regulation-end beat. Both downstream paths
        # (decision, golden-score transition) follow this; consumers can
        # latch off TIME_EXPIRED to know the regulation clock has
        # stopped.
        events.append(Event(
            tick=tick,
            event_type="TIME_EXPIRED",
            description=(
                f"[ref: {self.referee.name}] Time! Regulation expires "
                f"at {a_wa}-{b_wa}."
            ),
            data={
                "tick":       tick,
                "a_waza_ari": a_wa,
                "b_waza_ari": b_wa,
            },
        ))
        if a_wa == b_wa:
            self.golden_score = True
            self.golden_score_start_tick = tick
            events.append(Event(
                tick=tick,
                event_type="GOLDEN_SCORE_START",
                description=(
                    f"[ref: {self.referee.name}] Scores level — golden "
                    f"score begins. First score or third shido decides it."
                ),
                data={
                    "a_waza_ari": a_wa,
                    "b_waza_ari": b_wa,
                    "tick":       tick,
                },
            ))
            # Regulation→golden-score is a stop-and-restart, not a
            # continuous roll. Pre-fix this only flipped `golden_score`
            # True, so if the bell caught the fighters in ne-waza the GS
            # clock simply started under them and the ground scramble ran
            # on with no break (seed 1148955923: t242 time expires mid-
            # scramble, ne-waza rolls straight into GS for ~360 ticks).
            # Route through the standard matte reset so GS always opens
            # from a clean STANDING_DISTANT dyad: the TIME_EXPIRED "Time!"
            # line above is the stop beat, _handle_matte breaks the dyad
            # back to standing (clearing any ne-waza / osaekomi state) and
            # schedules the restart Hajime (MATTE_TO_HAJIME_PAUSE_TICKS
            # freeze). Matte → golden score → Hajime.
            self._handle_matte(tick)
            return
        winner = a if a_wa > b_wa else b
        self._end_match(winner, "decision", tick, events)

    def _resolve_golden_score_cap(self, tick: int, events: list[Event]) -> None:
        """HAJ-234 — golden-score window expired with no score.

        Termination policy (capped GS, documented on GOLDEN_SCORE_MAX_TICKS):
        decide on shido count — the fighter carrying fewer shidos out of
        regulation+GS is the more positively-contesting one and takes the
        decision. A level shido count is a genuine draw. Both paths route
        through `_end_match` so consumers get the usual MATCH_ENDED signal.
        """
        if self.match_over or not self.golden_score:
            return
        a, b = self.fighter_a, self.fighter_b
        a_sh = a.state.shidos
        b_sh = b.state.shidos
        if a_sh != b_sh:
            winner = a if a_sh < b_sh else b
            events.append(Event(
                tick=tick,
                event_type="GOLDEN_SCORE_DECISION",
                description=(
                    f"[ref: {self.referee.name}] Golden score time cap — "
                    f"decision to {winner.identity.name} on fewer shidos "
                    f"({min(a_sh, b_sh)} to {max(a_sh, b_sh)})."
                ),
                data={
                    "winner":   winner.identity.name,
                    "a_shidos": a_sh,
                    "b_shidos": b_sh,
                    "tick":     tick,
                },
            ))
            self._end_match(winner, "decision (golden score)", tick, events)
        else:
            events.append(Event(
                tick=tick,
                event_type="GOLDEN_SCORE_DRAW",
                description=(
                    f"[ref: {self.referee.name}] Golden score time cap — "
                    f"scores and shidos level. Match drawn."
                ),
                data={
                    "a_shidos": a_sh,
                    "b_shidos": b_sh,
                    "tick":     tick,
                },
            ))
            self._end_match(None, "draw", tick, events)

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
        # HAJ-237 — read regulation time (excludes matte→hajime freeze
        # ticks) so the finish time matches the clock that was on screen.
        # The match is over here, so the running `_frozen_ticks` total is
        # the count as of the deciding tick.
        def clock(tick: int) -> str:
            remaining = max(0, self._clock_remaining(tick))
            return f"{remaining // 60}:{remaining % 60:02d}"

        if self.win_method == "draw":
            wa = a.state.score["waza_ari"]
            # HAJ-234 — a draw is now reachable only via the golden-score cap
            # (regulation ties enter golden score, they no longer draw).
            if self.golden_score:
                return [
                    f"Match drawn {wa}-{wa} — golden score reached the time "
                    f"cap with scores and shidos level."
                ]
            return [f"Match drawn {wa}-{wa}."]

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
        if method == "decision (golden score)":
            wn_sh = winner.state.shidos
            ln_sh = loser.state.shidos
            return (f"{wn} won in golden score on the time cap — decided on "
                    f"fewer shidos ({wn_sh} to {ln_sh}).")
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
