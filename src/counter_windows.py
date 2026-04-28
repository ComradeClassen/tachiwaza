# counter_windows.py
# Physics-substrate Part 6.2: the three counter-windows as state regions.
#
# Spec: design-notes/physics-substrate.md, Part 6.2.
#
# Classical judo theory names three counter timings:
#   - Sen-sen no sen — preempt the attack before it forms
#   - Sen no sen     — strike at the moment of commit, before delivery
#   - Go no sen      — redirect the committed momentum (kaeshi-waza)
#
# The spec treats these not as time windows but as STATE REGIONS in the dyad's
# BodyState + grip + in-progress-attempt space. This module classifies the
# current dyad state into one of the three regions (or NONE), models the
# defender's noisy perception of which region they're in (Part 3.5 split
# reused), and scores counter viability for v0.1.
#
# Integration: Match._check_counter_opportunities runs this each tick against
# both fighters, aborts the original attempt if a counter fires, and routes
# the counter through the standard _resolve_commit_throw path with a
# counter-window quality bonus.

from __future__ import annotations
import random
from enum import Enum, auto
from math import hypot
from typing import TYPE_CHECKING, Optional

from enums import GripMode
from throws import ThrowID
from skill_compression import SubEvent

if TYPE_CHECKING:
    from judoka import Judoka
    from grip_graph import GripGraph
    from match import _ThrowInProgress


# ---------------------------------------------------------------------------
# COUNTER WINDOW
# ---------------------------------------------------------------------------
class CounterWindow(Enum):
    NONE            = auto()
    SEN_SEN_NO_SEN  = auto()  # Preempt the attack before it commits.
    SEN_NO_SEN      = auto()  # Strike at the moment of commit; symmetric counter.
    GO_NO_SEN       = auto()  # Redirect the committed momentum; kaeshi-waza.


# ---------------------------------------------------------------------------
# TUNING (calibration stubs; Phase 3 tunes against match telemetry)
# ---------------------------------------------------------------------------
SEN_SEN_APPROACH_SPEED:       float = 0.3    # m/s CoM toward opponent — sen-sen-no-sen gate
COUNTER_COMPOSURE_GATE:       float = 0.35   # fraction of ceiling below which counters won't fire
COUNTER_FATIGUE_GATE:         float = 0.70   # leg/hand fatigue above which counters won't fire
COUNTER_PERCEPTION_FLIP_PROB: float = 0.25   # base misperception for iq=0, clamped at iq=10 to 0.02
COUNTER_BASE_PROBABILITY:     float = 0.30   # baseline fire chance for iq=10, fresh, vuln=1.0
COUNTER_WINDOW_QUALITY_BONUS: float = 0.15   # bonus to window_quality when counter lands

# HAJ-134 — multiplier on counter-fire probability per unit of total
# attacker commitment_cost across all active vulnerability windows. With
# the typical PULL+DEEPEN load (~0.85), this lifts the fire prob ~25%
# above the legacy baseline; a fully-loaded foot-attack stack (~1.2)
# lifts it ~35%. Calibration stub; HAJ-A.7 will tune.
COMMITMENT_FIRE_BONUS:        float = 0.30

# HAJ-58 — stiffness telegraphing. A bent-over attacker broadcasts intent
# through grip tension before commit; the defender feels the attack coming
# early, so reduce the misperception flip probability. Threshold reuses
# body_state.UPRIGHT_LIMIT_RAD (the same boundary HAJ-56 taxes for stamina);
# the bonus is small — a nudge, not a free read.
ATTACKER_STIFFNESS_PERCEPTION_BONUS: float = 0.05

# Starter counter-option tables (Part 6.2 narrative examples). Defenders pick
# the first entry that exists in their throw_vocabulary; SEN_NO_SEN has an
# additional "symmetric" pass where defender tries attacker's own throw_id
# first. GO_NO_SEN redirections favor backward-rotating throws.
COUNTER_OPTIONS: dict[CounterWindow, tuple[ThrowID, ...]] = {
    CounterWindow.SEN_SEN_NO_SEN: (
        ThrowID.DE_ASHI_HARAI,     # "catches tori mid-step-in" per spec
        ThrowID.KO_UCHI_GARI,
    ),
    CounterWindow.SEN_NO_SEN: (
        # Populated dynamically with attacker's throw_id (symmetric) — see
        # select_counter_throw. Falls back to these if symmetric unavailable.
        ThrowID.O_UCHI_GARI,
        ThrowID.KO_UCHI_GARI,
    ),
    CounterWindow.GO_NO_SEN: (
        ThrowID.O_SOTO_GARI,       # O-soto-gaeshi ≈ O-soto back at tori
        ThrowID.SUMI_GAESHI,       # Ura-nage stand-in (sacrifice counter)
        ThrowID.TAI_OTOSHI,
    ),
}


# ---------------------------------------------------------------------------
# ACTUAL REGION CLASSIFICATION
# ---------------------------------------------------------------------------
def actual_counter_window(
    attacker: "Judoka",
    defender: "Judoka",
    graph: "GripGraph",
    tip: Optional["_ThrowInProgress"],
    last_sub_event: Optional[SubEvent],
    current_tick: Optional[int] = None,
) -> CounterWindow:
    """Return the counter-window region the dyad currently occupies from the
    defender's vantage point. Rules mirror spec 6.2 region definitions.

    `tip` is the attacker's in-progress attempt (None if they haven't
    committed). `last_sub_event` is the most recent sub-event emitted by
    that attempt. `current_tick` is needed for HAJ-134's window-data read
    (legacy callers can omit it; behavior falls back to the pre-HAJ-134
    heuristic).
    """
    if tip is None:
        return _sen_sen_region(
            attacker, defender, graph, current_tick=current_tick,
        )

    # An attempt is mid-flight.
    if last_sub_event in (SubEvent.TSUKURI, SubEvent.KAKE_COMMIT):
        return CounterWindow.GO_NO_SEN
    if last_sub_event in (SubEvent.REACH_KUZUSHI, SubEvent.KUZUSHI_ACHIEVED):
        return CounterWindow.SEN_NO_SEN
    # No sub-event yet this tick — the attempt just began. Treat the first
    # tick as sen-no-sen since tori has committed.
    return CounterWindow.SEN_NO_SEN


def _sen_sen_region(
    attacker: "Judoka", defender: "Judoka", graph: "GripGraph",
    current_tick: Optional[int] = None,
) -> CounterWindow:
    """Pre-commit region test.

    HAJ-134 — primary signal is now the attacker's `active_windows`
    list (vulnerability windows declared by their own actions). When
    any window is active, the attacker is in sen-sen-no-sen — uke can
    read the load and counter pre-commit. Pre-HAJ-134 this used a
    driving-grip + approach-speed heuristic that missed setup-action
    vulnerabilities (foot-attack setups, deepen on a strong grip);
    the data-driven check covers all of those uniformly.

    Legacy fallback: when `current_tick` is None (older test callers
    that didn't thread the tick through), preserve the pre-HAJ-134
    heuristic so existing tests don't drift.
    """
    if current_tick is not None:
        from vulnerability_window import has_active_window
        if has_active_window(attacker, current_tick):
            return CounterWindow.SEN_SEN_NO_SEN
        return CounterWindow.NONE

    # Pre-HAJ-134 heuristic preserved for tick-less callers.
    has_driving = any(
        e.mode == GripMode.DRIVING
        for e in graph.edges_owned_by(attacker.identity.name)
    )
    if not has_driving:
        return CounterWindow.NONE
    if _approach_speed(attacker, defender) < SEN_SEN_APPROACH_SPEED:
        return CounterWindow.NONE
    return CounterWindow.SEN_SEN_NO_SEN


def _approach_speed(attacker: "Judoka", defender: "Judoka") -> float:
    """Component of attacker's CoM velocity pointing toward the defender (m/s)."""
    ax, ay = attacker.state.body_state.com_position
    dx, dy = defender.state.body_state.com_position
    to_def = (dx - ax, dy - ay)
    norm = hypot(*to_def)
    if norm < 1e-9:
        return 0.0
    ux, uy = to_def[0] / norm, to_def[1] / norm
    vx, vy = attacker.state.body_state.com_velocity
    return ux * vx + uy * vy


# ---------------------------------------------------------------------------
# PERCEIVED REGION (defender's noisy read)
# ---------------------------------------------------------------------------
def perceived_counter_window(
    actual: CounterWindow,
    defender: "Judoka",
    rng: Optional[random.Random] = None,
    *,
    defensive_desperation: bool = False,
    attacker: Optional["Judoka"] = None,
) -> CounterWindow:
    """Return the defender's perception of the current region.

    Per spec 6.2: a low-IQ defender may perceive sen-no-sen when the dyad
    is actually in go-no-sen (tries to resist committed momentum, eats the
    throw) or may perceive go-no-sen when in sen-no-sen (attempts a
    redirection counter with no momentum to redirect).

    v0.1 model: with probability scaled by (10 - fight_iq)/10, flip the
    perceived region to an adjacent one. NONE flips to SEN_NO_SEN (reads
    a nonexistent attack); SEN_SEN_NO_SEN/SEN_NO_SEN/GO_NO_SEN misread as
    their neighbors.

    HAJ-35 — defensive desperation reduces the flip probability on real
    (non-NONE) windows: a defender pinned in attack after attack starts
    reading the pattern. NONE misreads are unaffected — a desperate
    defender doesn't hallucinate attacks that aren't there.

    HAJ-58 — a bent-over attacker telegraphs intent through grip tension
    before commit. When `attacker` is supplied and their trunk_sagittal
    exceeds UPRIGHT_LIMIT_RAD (forward bend only), reduce flip_p by
    ATTACKER_STIFFNESS_PERCEPTION_BONUS. NONE windows are unaffected by
    symmetry with the desperation rule — stiffness on no-attack reads
    shouldn't summon ghost attacks.
    """
    r = rng if rng is not None else random
    # HAJ-137 — perception flip rate now reads counter_window_reading
    # off the skill vector instead of fight_iq. The "novice misreads
    # the region" effect is now a function of the dedicated perception
    # axis, so a fighter can be cardio-strong but counter-blind (or
    # vice-versa) — what makes brown-belt fight-IQ structurally
    # different from black-belt fight-IQ §5.1.
    from skill_vector import axis
    skill = max(0.0, min(1.0, axis(defender, "counter_window_reading")))
    novice_w = 1.0 - skill
    flip_p = max(0.02, COUNTER_PERCEPTION_FLIP_PROB * novice_w)
    if defensive_desperation and actual != CounterWindow.NONE:
        from defensive_desperation import CW_PERCEPTION_BONUS
        flip_p = max(0.0, flip_p - CW_PERCEPTION_BONUS)
    if attacker is not None and actual != CounterWindow.NONE:
        from body_state import UPRIGHT_LIMIT_RAD
        if attacker.state.body_state.trunk_sagittal > UPRIGHT_LIMIT_RAD:
            flip_p = max(0.0, flip_p - ATTACKER_STIFFNESS_PERCEPTION_BONUS)
    if r.random() >= flip_p:
        return actual
    return _adjacent_region(actual, r)


def _adjacent_region(
    region: CounterWindow, rng: random.Random,
) -> CounterWindow:
    neighbors: dict[CounterWindow, tuple[CounterWindow, ...]] = {
        CounterWindow.NONE:           (CounterWindow.SEN_SEN_NO_SEN,
                                       CounterWindow.SEN_NO_SEN),
        CounterWindow.SEN_SEN_NO_SEN: (CounterWindow.NONE,
                                       CounterWindow.SEN_NO_SEN),
        CounterWindow.SEN_NO_SEN:     (CounterWindow.SEN_SEN_NO_SEN,
                                       CounterWindow.GO_NO_SEN),
        CounterWindow.GO_NO_SEN:      (CounterWindow.SEN_NO_SEN,
                                       CounterWindow.NONE),
    }
    choices = neighbors.get(region, (region,))
    return rng.choice(choices)


# ---------------------------------------------------------------------------
# RESOURCE GATE
# ---------------------------------------------------------------------------
def has_counter_resources(defender: "Judoka") -> bool:
    """Per spec 6.2: counters cost force, cardio, composure. A tired or
    panicked defender may perceive the window but cannot commit."""
    ceiling = max(1.0, float(defender.capability.composure_ceiling))
    composure_frac = defender.state.composure_current / ceiling
    if composure_frac < COUNTER_COMPOSURE_GATE:
        return False
    # Fatigue across the four parts that drive a counter-throw.
    body = defender.state.body
    parts = ("right_leg", "left_leg", "right_hand", "left_hand")
    fatigues = [body[p].fatigue for p in parts if p in body]
    avg_fat = sum(fatigues) / len(fatigues) if fatigues else 0.0
    return avg_fat <= COUNTER_FATIGUE_GATE


# ---------------------------------------------------------------------------
# COUNTER-THROW SELECTION
# ---------------------------------------------------------------------------
def select_counter_throw(
    defender: "Judoka",
    window: CounterWindow,
    attacker_throw_id: ThrowID,
) -> Optional[ThrowID]:
    """Pick a counter throw for the defender given the window.

    Symmetric counter (same throw back) gets priority inside SEN_NO_SEN —
    that's where Uchi-mata-sukashi lives. Otherwise fall through to the
    window's canonical options, then the defender's signature throws. Only
    throws the defender actually has in their vocabulary are considered.
    """
    if window == CounterWindow.NONE:
        return None
    vocab = set(defender.capability.throw_vocabulary)

    # Symmetric pass for sen-no-sen: uke mirrors tori.
    if window == CounterWindow.SEN_NO_SEN and attacker_throw_id in vocab:
        return attacker_throw_id

    for candidate in COUNTER_OPTIONS.get(window, ()):
        if candidate in vocab:
            return candidate

    for sig in defender.capability.signature_throws:
        if sig in vocab:
            return sig
    return None


# ---------------------------------------------------------------------------
# FIRE PROBABILITY
# ---------------------------------------------------------------------------
def counter_fire_probability(
    defender: "Judoka",
    window: CounterWindow,
    attacker_vulnerability: float,
    *,
    defensive_desperation: bool = False,
    tori_execution_quality: Optional[float] = None,
    attacker_commitment: float = 0.0,
) -> float:
    """Per-tick probability the defender actually commits the counter.

    Scales with fight_iq, composure, and the attacker's throw-specific
    vulnerability (sukashi for Couple, counter for Lever). A fatigued
    defender's probability collapses per has_counter_resources — that's
    checked before this is called, so here we assume resources are OK.

    HAJ-35 — when the defender is in defensive desperation they're more
    willing to fire a risky counter: the base probability is multiplied
    by CW_FIRE_PROB_MULT (>1). This amplifies the normal composure/iq
    gates without bypassing them entirely.

    HAJ-62 (Part 4.2.1 point 3) — a low-quality committed throw leaves
    tori more exploitable: `tori_execution_quality` (only meaningful for
    GO_NO_SEN / SEN_NO_SEN against an in-progress attempt) multiplies the
    base probability by counter_vulnerability_multiplier(eq). Passing None
    preserves legacy behaviour (no eq-aware adjustment).

    HAJ-134 — `attacker_commitment` is the sum of commitment_cost across
    tori's currently-active vulnerability windows. A heavier load
    (multiple open windows, a force action with strong cost) widens the
    counter window. Modeled as a 1.0 + commitment * COMMITMENT_FIRE_BONUS
    multiplier so 0.0 commitment leaves the prob unchanged (legacy
    callers) and a fully-committed action ladder lifts the fire prob
    meaningfully without dominating the iq/composure terms.
    """
    if window == CounterWindow.NONE:
        return 0.0
    iq = max(0.0, min(10.0, float(defender.capability.fight_iq))) / 10.0
    ceiling = max(1.0, float(defender.capability.composure_ceiling))
    comp = max(0.0, min(1.0, defender.state.composure_current / ceiling))
    vuln = max(0.0, min(1.0, attacker_vulnerability))
    # Sen-sen-no-sen is rarer than mid-commit counters — the attack isn't
    # fully committed yet, so the opportunity is narrower.
    window_mod = 0.5 if window == CounterWindow.SEN_SEN_NO_SEN else 1.0
    base = COUNTER_BASE_PROBABILITY * iq * comp * vuln * window_mod
    if defensive_desperation:
        from defensive_desperation import CW_FIRE_PROB_MULT
        base *= CW_FIRE_PROB_MULT
    if tori_execution_quality is not None and window in (
        CounterWindow.SEN_NO_SEN, CounterWindow.GO_NO_SEN,
    ):
        from execution_quality import counter_vulnerability_multiplier
        base *= counter_vulnerability_multiplier(tori_execution_quality)
    if attacker_commitment > 0.0:
        base *= 1.0 + attacker_commitment * COMMITMENT_FIRE_BONUS
    return min(1.0, base)


# ---------------------------------------------------------------------------
# ATTACKER VULNERABILITY LOOKUP
# Resolves to the template's sukashi/counter vulnerability when the throw
# has a Part-5 worked template; otherwise a mild default.
# ---------------------------------------------------------------------------
def attacker_vulnerability_for(throw_id: ThrowID) -> float:
    from worked_throws import worked_template_for
    template = worked_template_for(throw_id)
    if template is None:
        return 0.30   # mild default for legacy throws
    if hasattr(template, "counter_vulnerability"):
        return float(getattr(template, "counter_vulnerability"))
    return float(getattr(template, "sukashi_vulnerability", 0.30))
