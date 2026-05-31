# compromised_state.py
# Physics-substrate Part 6.3: failed-throw compromised state specification.
#
# Spec: design-notes/physics-substrate.md, Part 6.3.
#
# A failed throw does not reset tori to neutral — tori enters a named,
# specific BodyState configuration that leaves them vulnerable to particular
# counters. This module provides:
#
#   - CompromisedStateConfig — body-state mutations + counter vulnerabilities
#   - COMPROMISED_STATE_CONFIGS — the seven named tori states from spec 6.3
#     plus empty configs for non-compromised FailureOutcomes (STANCE_RESET,
#     PARTIAL_THROW, UKE_VOLUNTARY_NEWAZA)
#   - apply_compromised_body_state — mutate tori's BodyState per the config
#   - counter_bonus_for — per-state counter-vulnerability multiplier
#   - is_desperation_state / apply_desperation_overlay — the Part 6.3
#     TORI_DESPERATION_STATE overlay that stacks on top of a primary state
#     when the attacker was panicked + kumi-kata clock near expiry
#
# The recovery duration per state is owned by failure_resolution's
# RECOVERY_TICKS_BY_OUTCOME — that's the tick budget Match.stun_ticks burns
# down while tori is compromised. This module is about *what* the state
# looks like, not how long it lasts.

from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from throws import ThrowID
from throw_templates import FailureOutcome

if TYPE_CHECKING:
    from judoka import Judoka
    from body_state import FootContactState as _FootContactState
    from failure_resolution import FailureResolution


# ---------------------------------------------------------------------------
# TUNING (calibration stubs; Phase 3 tunes against telemetry)
# ---------------------------------------------------------------------------
DESPERATION_COMPOSURE_FRAC: float = 0.30   # composure/ceiling below which desperation fires
DESPERATION_CLOCK_TICKS:    int   = 22     # kumi_kata_clock at/above which desperation fires
# HAJ-35 — secondary trigger: the kumi-kata clock itself, when it's about to
# fire a passivity shido, is pressure enough to push a fighter into
# desperation regardless of composure. A fighter in real judo, one tick away
# from a penalty for not attacking, will commit to *anything*. This unblocks
# bootstrapping: early-match matches where nobody has scored yet (so nobody's
# composure has dropped) still produce commits before shidos stack up.
# Tuned one tick below KUMI_KATA_SHIDO_TICKS (30) so the fighter has a
# chance to throw before the shido actually fires.
DESPERATION_IMMINENT_SHIDO_TICKS: int = 29
DESPERATION_RECOVERY_BONUS: int   = 2      # extra recovery ticks per Part 6.3
DESPERATION_COMPOSURE_DROP: float = 0.15   # additional composure hit beyond base


# ---------------------------------------------------------------------------
# COMPROMISED STATE CONFIG
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CompromisedStateConfig:
    """Body-state mutations and counter-vulnerabilities for one named state.

    All angle fields are in RADIANS. `set_foot_*` overrides the contact_state
    on that foot; `weight_fraction_*` overrides the weight fraction. Leaving
    a field None means "don't touch." Mutations are additive where additive
    makes sense (trunk angles, com_height delta) and replace-style for foot
    state (kneeling is a snap, not a drift).

    `counter_bonuses` maps counter ThrowIDs to additive probability bonuses
    applied on top of the base counter-fire probability when uke targets a
    tori in this state. Spec 6.3 lists which throws exploit which state —
    these numbers are the mechanical expression of that narrative.
    """
    trunk_sagittal_add:     float = 0.0
    trunk_frontal_add:      float = 0.0
    com_height_delta:       float = 0.0
    set_foot_left:          Optional["_FootContactState"] = None
    set_foot_right:         Optional["_FootContactState"] = None
    weight_fraction_left:   Optional[float] = None
    weight_fraction_right:  Optional[float] = None
    counter_bonuses:        dict[ThrowID, float] = field(default_factory=dict)

    # Self-inflicted kuzushi folded into the decaying buffer.
    # `kuzushi_vector_rel` is a (forward, lateral) unit-ish vector in tori's
    # FACING-relative frame: +x = pitched forward over the toes, +y = toward
    # tori's left (so an airborne RIGHT foot reads as -y). It is rotated into
    # the mat frame at emit time via tori's facing. `kuzushi_severity` in
    # [0, 1] scales BASE_SELF_INFLICTED_KUZUSHI_FORCE. Severity 0 (the
    # default, and every reset / clean-counter outcome) emits no event — the
    # compromised-state body mutation still applies, but the buffer stays
    # untouched.
    kuzushi_vector_rel:     tuple[float, float] = (0.0, 0.0)
    kuzushi_severity:       float = 0.0


# ---------------------------------------------------------------------------
# CONFIG TABLE (Part 6.3)
# ---------------------------------------------------------------------------
def _configs() -> dict[FailureOutcome, CompromisedStateConfig]:
    # Lazy construction so body_state import (which needs enums at module load)
    # doesn't tangle with this module's import-time evaluation.
    from body_state import FootContactState
    return {
        # Tori's trunk sharply forward, both grips still engaged. Uke can
        # pitch tori backward (O-soto-gari) or hook the exposed forward leg
        # (O-uchi-gari / Ko-soto-gari).
        FailureOutcome.TORI_COMPROMISED_FORWARD_LEAN: CompromisedStateConfig(
            trunk_sagittal_add=math.radians(30),
            counter_bonuses={
                ThrowID.O_SOTO_GARI:  0.40,
                ThrowID.O_UCHI_GARI:  0.30,
                ThrowID.KO_UCHI_GARI: 0.20,
            },
            # Pitched sharply forward over the toes — strong forward break.
            kuzushi_vector_rel=(1.0, 0.0),
            kuzushi_severity=0.70,
        ),

        # One foot AIRBORNE, other planted carrying full weight — the failed
        # reap / foot sweep. Uke can throw against the supporting leg.
        FailureOutcome.TORI_COMPROMISED_SINGLE_SUPPORT: CompromisedStateConfig(
            set_foot_right=FootContactState.AIRBORNE,
            weight_fraction_right=0.0,
            weight_fraction_left=1.0,
            counter_bonuses={
                ThrowID.O_SOTO_GARI: 0.35,
                ThrowID.O_UCHI_GARI: 0.35,
                ThrowID.UCHI_MATA:   0.25,
            },
            # Right foot airborne, balanced on the left leg — break is toward
            # the unsupported (right = -y) side with a slight forward lean.
            kuzushi_vector_rel=(0.3, -0.95),
            kuzushi_severity=0.60,
        ),

        # Seoi-nage specific: back turned, hips above uke's, spine flexed
        # with uke draped. Uke pulls tori down or fires Ura-nage (we use
        # SUMI_GAESHI as the sacrifice-counter stand-in).
        FailureOutcome.TORI_STUCK_WITH_UKE_ON_BACK: CompromisedStateConfig(
            trunk_sagittal_add=math.radians(45),
            counter_bonuses={
                ThrowID.SUMI_GAESHI: 0.55,
                ThrowID.TAI_OTOSHI:  0.30,
            },
            # Bent hard forward with uke draped on the back — heavily loaded
            # forward break, near the top of the severity range.
            kuzushi_vector_rel=(1.0, 0.0),
            kuzushi_severity=0.85,
        ),

        # Lever-specific stall: fulcrum engaged but lift failed, bent forward
        # with uke partially lifted. Redirection counters (kaeshi-waza) fire.
        FailureOutcome.TORI_BENT_FORWARD_LOADED: CompromisedStateConfig(
            trunk_sagittal_add=math.radians(25),
            counter_bonuses={
                ThrowID.SUMI_GAESHI: 0.40,
                ThrowID.O_SOTO_GARI: 0.30,
            },
            # Fulcrum engaged, lift stalled, bent forward — moderate forward
            # break.
            kuzushi_vector_rel=(1.0, 0.0),
            kuzushi_severity=0.60,
        ),

        # Seoi-nage drop one-knee: CoM down, one knee on the mat. Uke
        # transitions to osaekomi or Ura-nage against a kneeling tori.
        FailureOutcome.TORI_ON_KNEE_UKE_STANDING: CompromisedStateConfig(
            com_height_delta=-0.20,
            weight_fraction_left=0.4,
            weight_fraction_right=0.4,
            counter_bonuses={
                ThrowID.SUMI_GAESHI: 0.45,
                ThrowID.O_SOTO_GARI: 0.25,
            },
            # CoM dropped onto one knee — the collapse is mostly vertical
            # (not representable as a horizontal vector), so a modest forward
            # component carries direction and severity carries the magnitude.
            kuzushi_vector_rel=(0.7, 0.0),
            kuzushi_severity=0.70,
        ),

        # Seoi-nage drop two-knee: CoM way down, both knees on the mat.
        # Maximum vulnerability — direct osaekomi transitions available.
        FailureOutcome.TORI_ON_BOTH_KNEES_UKE_STANDING: CompromisedStateConfig(
            com_height_delta=-0.35,
            weight_fraction_left=0.2,
            weight_fraction_right=0.2,
            counter_bonuses={
                ThrowID.SUMI_GAESHI: 0.60,
                ThrowID.O_SOTO_GARI: 0.30,
                ThrowID.TAI_OTOSHI:  0.35,
            },
            # Both knees down — maximum vulnerability. Top of the severity
            # range; small forward component for direction.
            kuzushi_vector_rel=(0.5, 0.0),
            kuzushi_severity=0.95,
        ),

        # Foot-sweep rebound: sweeping leg met a planted foot and bounced.
        # Lightest compromised state. Uke can fire a direct foot sweep
        # exploiting tori's brief rebalance.
        FailureOutcome.TORI_SWEEP_BOUNCES_OFF: CompromisedStateConfig(
            set_foot_right=FootContactState.AIRBORNE,
            weight_fraction_right=0.0,
            weight_fraction_left=1.0,
            counter_bonuses={
                ThrowID.DE_ASHI_HARAI: 0.35,
                ThrowID.KO_UCHI_GARI:  0.25,
            },
            # Sweeping leg rebounded off a planted foot — lightest state.
            # Brief lateral wobble toward the airborne (right = -y) side.
            kuzushi_vector_rel=(0.2, -0.98),
            kuzushi_severity=0.40,
        ),

        # HAJ-49 / HAJ-50 — tactical drop reset. Tori's CoM was never over
        # the fulcrum and the knee contact was a feint, not a committed
        # drop. The physical signature is essentially "dipped briefly, now
        # rising". Counter-bonuses are EMPTY (HAJ-50): uke cannot score an
        # osaekomi transition against a tori who is already standing back
        # up, and there is no loaded body to scoop under for Ura-nage. The
        # only real cost is one tick of no-offense (recovery, set in
        # failure_resolution.RECOVERY_TICKS_BY_OUTCOME) and the grip-graph
        # edge-fatigue roll that runs every tick regardless.
        FailureOutcome.TACTICAL_DROP_RESET: CompromisedStateConfig(
            com_height_delta=-0.05,
            weight_fraction_left=0.55,
            weight_fraction_right=0.45,
            counter_bonuses={},
            # kuzushi_severity left at 0: tori's CoM was never over the
            # fulcrum, the drop was a feint. No self-inflicted kuzushi to
            # fold (mirrors HAJ-50's empty counter_bonuses).
        ),

        # Non-compromised outcomes — no body-state reconfig, no counter bonus.
        FailureOutcome.STANCE_RESET:         CompromisedStateConfig(),
        FailureOutcome.PARTIAL_THROW:        CompromisedStateConfig(),
        FailureOutcome.UKE_VOLUNTARY_NEWAZA: CompromisedStateConfig(),
        # HAJ-57 — uke denied the hip-loading geometry. Tori's stance is
        # intact (the throw never set up); no body-state mutation, no
        # counter window. Clean reset to grip battle.
        FailureOutcome.BLOCKED_BY_HIP:       CompromisedStateConfig(),

        # Clean-counter outcomes — the FailureSpec's secondary branches. The
        # counter throw itself has already fired (via Part 6.2 or the
        # failure-resolution secondary roll), so tori's body state changes
        # are subtle: mid-commit trunk attitude, nothing more.
        FailureOutcome.UCHI_MATA_SUKASHI:    CompromisedStateConfig(
            trunk_sagittal_add=math.radians(20),
        ),
        FailureOutcome.OSOTO_GAESHI:         CompromisedStateConfig(
            trunk_sagittal_add=math.radians(-10),
        ),
        FailureOutcome.URA_NAGE:             CompromisedStateConfig(),
        FailureOutcome.KAESHI_WAZA_GENERIC:  CompromisedStateConfig(),
    }


# Resolved once per run — configs are immutable, so a cached dict is fine.
COMPROMISED_STATE_CONFIGS: dict[FailureOutcome, CompromisedStateConfig] = _configs()


# ---------------------------------------------------------------------------
# APPLY BODY-STATE RECONFIGURATION
# ---------------------------------------------------------------------------
def apply_compromised_body_state(
    attacker: "Judoka", outcome: FailureOutcome,
) -> None:
    """Mutate tori's BodyState to match the named compromised-state config.

    No-op for outcomes with an empty config. Called from
    failure_resolution.apply_failure_resolution after stun_ticks are set.
    """
    cfg = COMPROMISED_STATE_CONFIGS.get(outcome)
    if cfg is None:
        return
    bs = attacker.state.body_state
    if cfg.trunk_sagittal_add:
        bs.trunk_sagittal += cfg.trunk_sagittal_add
    if cfg.trunk_frontal_add:
        bs.trunk_frontal += cfg.trunk_frontal_add
    if cfg.com_height_delta:
        bs.com_height = max(0.4, bs.com_height + cfg.com_height_delta)
    if cfg.set_foot_left is not None:
        bs.foot_state_left.contact_state = cfg.set_foot_left
    if cfg.set_foot_right is not None:
        bs.foot_state_right.contact_state = cfg.set_foot_right
    if cfg.weight_fraction_left is not None:
        bs.foot_state_left.weight_fraction = cfg.weight_fraction_left
    if cfg.weight_fraction_right is not None:
        bs.foot_state_right.weight_fraction = cfg.weight_fraction_right


# ---------------------------------------------------------------------------
# SELF-INFLICTED KUZUSHI (failed-throw state folded into the buffer)
# ---------------------------------------------------------------------------
# A failed throw leaves tori off-balance in their OWN right — no opponent
# pull is behind it. Previously this lived only as a body_state mutation (see
# apply_compromised_body_state above) plus the _compromised_states tag in
# match.py, invisible to the decaying kuzushi buffer that the signature-match
# layer reads. This emitter folds it in as a SELF_INFLICTED contribution so
# uke's counter-selection sees tori's broken posture through the same channel
# as a pull or a foot attack.
#
# Calibration stub (HAJ-A.7 tunes): a severity-1.0 state delivers
# BASE_SELF_INFLICTED_KUZUSHI_FORCE units. Tuned so a forward-lean (0.70) and
# the kneeling states land above the ~40-unit throwable threshold while a
# sweep rebound (0.40) stays a light, fast-decaying wobble.
BASE_SELF_INFLICTED_KUZUSHI_FORCE: float = 80.0


def _rotate_rel_to_mat(
    rel: tuple[float, float], facing: tuple[float, float],
) -> tuple[float, float]:
    """Rotate a (forward, lateral) facing-relative vector into the mat frame.

    Forward axis = `facing` (unit); lateral +y axis = facing rotated +90°
    (counterclockwise), i.e. (-fy, fx). Returns a unit vector, or (0, 0) if
    the inputs collapse to zero length.
    """
    rx, ry = rel
    fx, fy = facing
    fmag = math.hypot(fx, fy)
    if fmag < 1e-9:
        return (0.0, 0.0)
    fx, fy = fx / fmag, fy / fmag
    # forward * facing + lateral * (facing rotated +90°)
    mx = rx * fx + ry * (-fy)
    my = rx * fy + ry * (fx)
    m = math.hypot(mx, my)
    if m < 1e-9:
        return (0.0, 0.0)
    return (mx / m, my / m)


def self_inflicted_kuzushi_event(
    attacker: "Judoka", outcome: FailureOutcome, current_tick: int,
):
    """Build the SELF_INFLICTED KuzushiEvent for tori's failed-throw state.

    Reads the outcome's CompromisedStateConfig: rotates `kuzushi_vector_rel`
    into the mat frame via tori's facing and scales
    BASE_SELF_INFLICTED_KUZUSHI_FORCE by `kuzushi_severity`.

    Returns None when the outcome carries no self-inflicted kuzushi
    (severity 0, zero vector, or an unconfigured outcome) — e.g. clean
    resets, clean counters, and TACTICAL_DROP_RESET. Callers append
    unconditionally and skip the None.
    """
    from kuzushi import KuzushiEvent, KuzushiSource
    cfg = COMPROMISED_STATE_CONFIGS.get(outcome)
    if cfg is None or cfg.kuzushi_severity <= 0.0:
        return None
    facing = attacker.state.body_state.facing
    vector = _rotate_rel_to_mat(cfg.kuzushi_vector_rel, facing)
    if vector == (0.0, 0.0):
        return None
    magnitude = BASE_SELF_INFLICTED_KUZUSHI_FORCE * cfg.kuzushi_severity
    if magnitude <= 0.0:
        return None
    return KuzushiEvent(
        tick_emitted=current_tick,
        vector=vector,
        magnitude=magnitude,
        source_kind=KuzushiSource.SELF_INFLICTED,
    )


# ---------------------------------------------------------------------------
# COUNTER-VULNERABILITY BONUS LOOKUP
# ---------------------------------------------------------------------------
def counter_bonus_for(
    outcome: Optional[FailureOutcome], counter_throw_id: ThrowID,
) -> float:
    """Additive probability bonus when uke fires `counter_throw_id` against
    tori while tori is in the given compromised state. Returns 0.0 if the
    state isn't configured or tori isn't in one.
    """
    if outcome is None:
        return 0.0
    cfg = COMPROMISED_STATE_CONFIGS.get(outcome)
    if cfg is None:
        return 0.0
    return cfg.counter_bonuses.get(counter_throw_id, 0.0)


# ---------------------------------------------------------------------------
# DESPERATION OVERLAY (Part 6.3 — TORI_DESPERATION_STATE)
# ---------------------------------------------------------------------------
def is_desperation_state(
    attacker: "Judoka",
    kumi_kata_clock: int,
    jitter: Optional[dict] = None,
) -> bool:
    """True when the attacker is in offensive desperation.

    Two independent triggers (OR semantics):

    1. Panic + pressure (Part 6.3 spec). Composure has collapsed below
       DESPERATION_COMPOSURE_FRAC of ceiling AND the kumi-kata clock is
       near shido (>= DESPERATION_CLOCK_TICKS). This is the primary
       trigger the failure path consults for the desperation overlay.

    2. Imminent-shido (HAJ-35). The kumi-kata clock alone has reached
       DESPERATION_IMMINENT_SHIDO_TICKS, one tick before the passivity
       shido actually fires. At that point the fighter will throw
       anything to reset the clock — composure is irrelevant.

    HAJ-47 — `jitter` is an optional per-fighter offset dict applied to
    the three thresholds. Symmetric fighters with different identities
    cross the trigger on different ticks, ending the prior behavior
    where two matched fighters always entered desperation simultaneously.
    Jitter is computed deterministically Match-side, so a replay with
    the same seed reproduces the same desperation timing.
    """
    j_composure = (jitter or {}).get("composure_frac", 0.0)
    j_clock     = (jitter or {}).get("clock_ticks", 0)
    j_imminent  = (jitter or {}).get("imminent_ticks", 0)

    ceiling = max(1.0, float(attacker.capability.composure_ceiling))
    composure_frac = attacker.state.composure_current / ceiling
    panic_trigger = (
        composure_frac < DESPERATION_COMPOSURE_FRAC + j_composure
        and kumi_kata_clock >= DESPERATION_CLOCK_TICKS + j_clock
    )
    imminent_shido_trigger = (
        kumi_kata_clock >= DESPERATION_IMMINENT_SHIDO_TICKS + j_imminent
    )
    return panic_trigger or imminent_shido_trigger


def apply_desperation_overlay(
    resolution: "FailureResolution",
) -> "FailureResolution":
    """Return a FailureResolution with extended recovery. Composure drop is
    applied separately in failure_resolution.apply_failure_resolution.
    """
    from failure_resolution import FailureResolution
    return FailureResolution(
        outcome=resolution.outcome,
        recovery_ticks=resolution.recovery_ticks + DESPERATION_RECOVERY_BONUS,
        failed_dimension=resolution.failed_dimension,
        dimension_score=resolution.dimension_score,
    )
