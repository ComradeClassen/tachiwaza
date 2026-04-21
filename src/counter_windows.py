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
) -> CounterWindow:
    """Return the counter-window region the dyad currently occupies from the
    defender's vantage point. Rules mirror spec 6.2 region definitions.

    `tip` is the attacker's in-progress attempt (None if they haven't
    committed). `last_sub_event` is the most recent sub-event emitted by
    that attempt.
    """
    if tip is None:
        return _sen_sen_region(attacker, defender, graph)

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
) -> CounterWindow:
    """Pre-commit region test. Tori has at least one driving grip AND is
    moving toward defender above the approach-speed gate.
    """
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
    """
    r = rng if rng is not None else random
    iq = max(0.0, min(10.0, float(defender.capability.fight_iq)))
    novice_w = (10.0 - iq) / 10.0
    flip_p = max(0.02, COUNTER_PERCEPTION_FLIP_PROB * novice_w)
    if defensive_desperation and actual != CounterWindow.NONE:
        from defensive_desperation import CW_PERCEPTION_BONUS
        flip_p = max(0.0, flip_p - CW_PERCEPTION_BONUS)
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
