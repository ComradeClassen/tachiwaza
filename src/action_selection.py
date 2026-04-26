# action_selection.py
# Physics-substrate Part 3.3: the v0.1 priority ladder.
#
# A deliberately-simple hardcoded decision function. Later rings (Ring 2
# coach instructions, Ring 3 cultural bias, Ring 4 opponent memory) layer
# on top by rewriting or filtering the ladder's output.
#
# The ladder produces up to two Actions per tick, or a single COMMIT_THROW
# compound action that supersedes the two-action cap.

from __future__ import annotations
import random
from typing import Optional, TYPE_CHECKING

from actions import (
    Action, ActionKind,
    reach, deepen, strip, release, pull, push, hold_connective, step, commit_throw,
    block_hip,
)
from enums import (
    GripTypeV2, GripDepth, GripTarget, GripMode, DominantSide,
)
from throws import THROW_DEFS, ThrowID
from grip_presence_gate import evaluate_gate, GateResult, REASON_OK
from compromised_state import is_desperation_state
from commit_motivation import CommitMotivation

if TYPE_CHECKING:
    from judoka import Judoka
    from grip_graph import GripGraph, GripEdge


# Tuning constants (calibration stubs).
COMMIT_THRESHOLD:             float = 0.65  # perceived signature must clear this to commit
DESPERATION_KUMI_CLOCK:       int   = 22    # tick count that triggers ladder rung 5
HIGH_FATIGUE_THRESHOLD:       float = 0.65  # hand-fatigue at which rung 6 prefers connective
DRIVE_MAGNITUDE_N:            float = 400.0 # PULL/PUSH force a non-desperation drive issues
PROBE_MAGNITUDE_N:            float = 120.0 # default-rung probing force
# Side-effect: match feeds us the grasper's kumi-kata clock; it's not
# visible on the Judoka itself because it belongs to the Match.

# HAJ-49 / HAJ-67 — non-scoring commit motivations.
#
# Four motivations fire the same low-signature drop-variant commit path but
# for different tactical reasons. Each has its own gate predicates and a
# per-tick probability scalar so multiple motivations don't cumulatively
# fire every eligible tick. See src/commit_motivation.py for the enum and
# narration templates; physics-substrate.md Part 3.3.1 for the spec text.
#
# Priority order when two motivations' gates both pass: CLOCK_RESET first
# (widest disposition coverage), then STAMINA_DESPERATION, GRIP_ESCAPE,
# SHIDO_FARMING. The first matching motivation wins.

# -- CLOCK_RESET (HAJ-49 legacy; gating unchanged) --
FALSE_ATTACK_CLOCK_MIN: int = 18   # earliest clock tick the tactical fake fires
FALSE_ATTACK_CLOCK_MAX: int = 29   # latest — strictly below imminent-shido (29) so
                                    # desperation (which fires at 29) takes precedence
FALSE_ATTACK_MIN_FIGHT_IQ: int = 4  # white/yellow belts don't game the clock; they panic
FALSE_ATTACK_TENDENCY_KEY: str = "false_attack_tendency"  # Identity.style_dna key
FALSE_ATTACK_TENDENCY_THRESHOLD: float = 0.40
FALSE_ATTACK_TENDENCY_DEFAULT:   float = 0.50
FALSE_ATTACK_PER_TICK_SCALE:     float = 0.10

# -- GRIP_ESCAPE --
# Fires when tori is losing the grip war, tori's own grips are shallow or
# missing, and composure has slipped below a moderate-panic threshold. The
# tactical fake is cover to reset the dyad.
# Calibration note: grip-delta values stay moderate in real exchanges
# because both fighters typically own 2 grips at similar depths. 0.30
# keeps the "opponent dominant" intent while remaining reachable.
GRIP_ESCAPE_DELTA_THRESHOLD:  float = 0.30
GRIP_ESCAPE_COMPOSURE_FRAC:   float = 0.60   # a little looser — composure slips before it shatters
GRIP_ESCAPE_PER_TICK_PROB:    float = 0.15

# -- SHIDO_FARMING --
# Fires when the opponent has been passive (their kumi-kata clock climbing)
# and tori has no real scoring opportunity. Tori throws a pose-attack to
# nudge the referee toward shido against uke. Style-biased.
# Calibration note: opp clock at ~10 ticks already represents a meaningful
# stretch of uke not attacking relative to match tempo.
SHIDO_FARMING_OPP_CLOCK:        int   = 7
SHIDO_FARMING_NO_SCORING_MAX:   float = 0.40
SHIDO_FARMING_TENDENCY_KEY:     str   = "shido_farming_tendency"
SHIDO_FARMING_TENDENCY_THRESHOLD: float = 0.45
SHIDO_FARMING_TENDENCY_DEFAULT:   float = 0.30
SHIDO_FARMING_PER_TICK_PROB:    float = 0.10

# -- STAMINA_DESPERATION --
# Fires when tori is cardio-cooked, has eaten at least one shido, and can't
# physically generate kuzushi this tick (hand/grip output is low). A tired,
# already-penalized fighter will fall into anything to buy a breather.
# Calibration note: 0.40 cardio puts tori in the bottom third. Below that,
# the fighter is visibly gassed — real judo condition for this motivation.
STAMINA_DESPERATION_CARDIO_MAX:  float = 0.50
STAMINA_DESPERATION_MIN_SHIDOS:  int   = 1
STAMINA_DESPERATION_HAND_FAT_MIN: float = 0.40
STAMINA_DESPERATION_PER_TICK_PROB: float = 0.20

# Priority order of drop-variant throws for any non-scoring motivation, most
# preferred first. Lowest-commitment entries in standard vocabularies: fast
# recovery-to-stance is the whole point, so shin-block (TAI_OTOSHI),
# foot-sweep (KO_UCHI_GARI), drop-seoi, and inner-reap (O_UCHI_GARI) over
# hip-fulcrum or high-amplitude throws.
FALSE_ATTACK_PREFERENCES: tuple[ThrowID, ...] = (
    ThrowID.TAI_OTOSHI,
    ThrowID.KO_UCHI_GARI,
    ThrowID.SEOI_NAGE,
    ThrowID.O_UCHI_GARI,
)

# Gate-bypass reason string for the commit log — read by match.py into the
# same tag-suffix pipeline the desperation path already uses.
REASON_INTENTIONAL_FALSE_ATTACK: str = "intentional_false_attack"

# HAJ-57 — uke's hip-block defensive rung tuning. Fire probability scales
# with fight_iq so a high-IQ defender reliably blocks while a low-IQ one
# may fail to read tori's commit and eat the throw. Posture-gated:
# trunk_sagittal must be <= 0 (upright or back-leaning — not bent forward).
HIP_BLOCK_FIRE_PROB_AT_FULL_IQ: float = 0.85


# ---------------------------------------------------------------------------
# TOP-LEVEL ENTRY POINT
# ---------------------------------------------------------------------------
def select_actions(
    judoka: "Judoka",
    opponent: "Judoka",
    graph: "GripGraph",
    kumi_kata_clock: int,
    rng: random.Random | None = None,
    defensive_desperation: bool = False,
    opponent_kumi_kata_clock: int = 0,
    opponent_in_progress_throw: Optional[ThrowID] = None,
) -> list[Action]:
    """Return the judoka's chosen actions for this tick.

    Implements the Part 3.3 priority ladder. Returns 1-2 Actions, or a
    single-element list containing COMMIT_THROW.

    HAJ-35/36: `defensive_desperation` is computed Match-side (requires
    cross-tick history the ladder can't see) and bypasses the grip-
    presence gate when True. Offensive desperation is derived locally
    from composure + kumi_kata_clock.

    HAJ-57: `opponent_in_progress_throw` is the throw_id the opponent
    has mid-flight (None if no attempt active). When set and the throw
    is hip-loading, the defensive-block rung fires BLOCK_HIP before any
    grip/commit work — provided the judoka is upright (posture gate)
    and a fight_iq-scaled perception roll succeeds.
    """
    r = rng if rng is not None else random

    # Rung 1: stunned → defensive-only (v0.1: just idle).
    if judoka.state.stun_ticks > 0:
        return _defensive_fallback(judoka)

    # HAJ-57 — defensive hip-block. Fires before grip/commit work because
    # interrupting an in-progress hip-loading throw is the highest-priority
    # defensive action available. Posture-gated: bent-over uke can't drive
    # hips forward.
    if opponent_in_progress_throw is not None:
        block = _try_hip_block(judoka, opponent_in_progress_throw, r)
        if block is not None:
            return [block]

    own_edges = graph.edges_owned_by(judoka.identity.name)
    opp_edges = graph.edges_owned_by(opponent.identity.name)

    # Engagement precedes commit: a throw requires at least pocket contact.
    # Without this, low-fight_iq perception noise on a Couple throw's always-
    # on body/posture dimensions lifts the perceived signature over the commit
    # threshold before any grip exists, and the novice throws from thin air.
    if not own_edges and not defensive_desperation:
        return _reach_actions(judoka)

    # Rung 2: commit if a throw is perceived available AND the grip-presence
    # gate passes (or desperation bypasses it).
    offensive_desperation = is_desperation_state(judoka, kumi_kata_clock)
    commit = _try_commit(
        judoka, opponent, graph, r,
        offensive_desperation=offensive_desperation,
        defensive_desperation=defensive_desperation,
        kumi_kata_clock=kumi_kata_clock,
        opponent_kumi_kata_clock=opponent_kumi_kata_clock,
    )
    if commit is not None:
        return [commit]

    # No edges + no commit path open (e.g. defensive desperation that
    # couldn't find a throw) — fall back to reach.
    if not own_edges:
        return _reach_actions(judoka)

    # Rung 5: kumi-kata clock nearing shido → escalate.
    escalated = (kumi_kata_clock >= DESPERATION_KUMI_CLOCK)

    # If every grip is still shallow (POCKET/SLIPPING), spend both actions
    # seating them — deepen primary, strip the opponent's strongest grip.
    deep_enough = [e for e in own_edges
                   if e.depth_level in (GripDepth.STANDARD, GripDepth.DEEP)]
    if not deep_enough:
        out: list[Action] = [deepen(own_edges[0])]
        if opp_edges:
            target = max(opp_edges, key=lambda e: e.depth_level.modifier())
            strip_hand = _free_hand(judoka) or "right_hand"
            out.append(strip(strip_hand, target))
        else:
            out.append(hold_connective(_primary_hand(judoka)))
        return out

    # Rung 6: fatigued + composed → recover connective.
    hand_fat = _avg_hand_fatigue(judoka)
    if hand_fat > HIGH_FATIGUE_THRESHOLD and not escalated:
        return [
            hold_connective("right_hand"),
            hold_connective("left_hand"),
        ]

    # Rungs 4/5 overlap: drive through the seated grip toward kuzushi.
    drive_mag = DRIVE_MAGNITUDE_N if not escalated else DRIVE_MAGNITUDE_N * 1.3

    # Direction convention: actions carry a force vector in world frame that
    # acts ON THE OPPONENT. PULL draws opponent toward attacker → opp→me;
    # PUSH drives opponent away → me→opp.
    attacker_to_opp = _direction_toward(judoka, opponent)
    pull_dir = (-attacker_to_opp[0], -attacker_to_opp[1])
    push_dir = attacker_to_opp

    primary = deep_enough[0]
    # Secondary action: deepen a shallow grip if any, else push with 2nd hand.
    shallow = [e for e in own_edges if e.depth_level != GripDepth.DEEP
               and e is not primary]
    out = [pull(primary.grasper_part.value, pull_dir, drive_mag)]
    if shallow:
        out.append(deepen(shallow[0]))
    elif len(own_edges) > 1:
        secondary = own_edges[1] if own_edges[0] is primary else own_edges[0]
        out.append(push(secondary.grasper_part.value, push_dir, drive_mag * 0.5))
    return out


# ---------------------------------------------------------------------------
# RUNGS / HELPERS
# ---------------------------------------------------------------------------
def _defensive_fallback(judoka: "Judoka") -> list[Action]:
    # Stunned: minimal-fatigue action.
    return [hold_connective("right_hand"), hold_connective("left_hand")]


def _try_hip_block(
    judoka: "Judoka", opponent_throw_id: ThrowID, rng: random.Random,
) -> Optional[Action]:
    """HAJ-57 — return a BLOCK_HIP Action if uke can and chooses to block
    a hip-loading throw this tick, else None.

    Three gates, all must pass:
      1. Throw is hip-loading. Reads `body_part_requirement.hip_loading`
         off the worked template; legacy throws (no template) can't be
         blocked.
      2. Posture: trunk_sagittal <= 0 (upright or back-leaning). A
         bent-over uke's hips are out of position — they can't drive
         them forward into tori's hip line.
      3. Perception roll: fight_iq-scaled probability. iq=10 fires at
         HIP_BLOCK_FIRE_PROB_AT_FULL_IQ; iq=0 never fires.
    """
    from worked_throws import worked_template_for
    template = worked_template_for(opponent_throw_id)
    if template is None:
        return None
    bpr = getattr(template, "body_part_requirement", None)
    if bpr is None or not getattr(bpr, "hip_loading", False):
        return None
    if judoka.state.body_state.trunk_sagittal > 0.0:
        return None
    iq = max(0.0, min(10.0, float(judoka.capability.fight_iq))) / 10.0
    fire_p = HIP_BLOCK_FIRE_PROB_AT_FULL_IQ * iq
    if rng.random() >= fire_p:
        return None
    return block_hip()


def _reach_actions(judoka: "Judoka") -> list[Action]:
    dom = judoka.identity.dominant_side
    is_right = dom == DominantSide.RIGHT
    lapel_target  = GripTarget.LEFT_LAPEL if is_right else GripTarget.RIGHT_LAPEL
    sleeve_target = GripTarget.RIGHT_SLEEVE if is_right else GripTarget.LEFT_SLEEVE
    return [
        reach("right_hand" if is_right else "left_hand", GripTypeV2.LAPEL_HIGH, lapel_target),
        # HAJ-53 — default sleeve reach is HIGH (elbow/tricep): the standard
        # hikite grip preferred by Seoi-nage, Uchi-mata, harai/hip throws,
        # and the rest of the vocabulary. Tai-otoshi specialists who want
        # SLEEVE_LOW will need a Ring-2 coach instruction layer.
        reach("left_hand"  if is_right else "right_hand", GripTypeV2.SLEEVE_HIGH, sleeve_target),
    ]


def _try_commit(
    judoka: "Judoka",
    opponent: "Judoka",
    graph: "GripGraph",
    rng: random.Random,
    *,
    offensive_desperation: bool = False,
    defensive_desperation: bool = False,
    kumi_kata_clock: int = 0,
    opponent_kumi_kata_clock: int = 0,
) -> Optional[Action]:
    """If there's a throw whose *perceived* signature clears the commit
    threshold AND the formal grip-presence gate allows it (or is bypassed
    by desperation), return a COMMIT_THROW Action for it. Otherwise, try
    each of the four non-scoring motivation pathways (HAJ-67).

    Pathway priority (first match wins):
      1. Normal signature-clears-threshold commit — the classical path.
      2. Offensive desperation — handled via the grip-presence gate bypass
         inside the main ranked-candidates loop.
      3. CLOCK_RESET         — HAJ-49 legacy; kumi-kata clock in pre-shido zone.
      4. STAMINA_DESPERATION — cooked fighter, already penalized, can't drive.
      5. GRIP_ESCAPE         — grip war lost, composure slipping.
      6. SHIDO_FARMING       — pressure a passive opponent into their own shido.

    Perceived-signature cache (dict[ThrowID, float]) is built once from the
    ranked candidates and shared across motivation predicates so we don't
    recompute the same scores four times per tick.

    The returned Action carries the motivation label so Match can surface
    it on the commit log line and the failure-outcome router can route to
    TACTICAL_DROP_RESET (HAJ-50).
    """
    from perception import actual_signature_match, perceive

    # Try signature throws first, then full vocabulary.
    candidates: list[ThrowID] = list(judoka.capability.signature_throws)
    for t in judoka.capability.throw_vocabulary:
        if t not in candidates:
            candidates.append(t)

    # Rank candidates by perceived signature; we'll walk in descending order
    # and pick the first that clears both the threshold AND the grip gate.
    perceived_by_throw: dict[ThrowID, float] = {}
    ranked: list[tuple[float, ThrowID]] = []
    for tid in candidates:
        td = THROW_DEFS.get(tid)
        if td is None:
            continue
        if judoka.capability.throw_profiles.get(tid) is None:
            continue
        actual = actual_signature_match(tid, judoka, opponent, graph)
        perceived = perceive(actual, judoka, rng=rng)
        # Small bonus for signature throws — tokui-waza bias.
        if tid in judoka.capability.signature_throws:
            perceived += 0.05
        perceived_by_throw[tid] = perceived
        ranked.append((perceived, tid))
    ranked.sort(key=lambda pair: pair[0], reverse=True)

    for perceived, tid in ranked:
        if perceived < COMMIT_THRESHOLD:
            break   # ranked descending; nothing below will clear either
        td = THROW_DEFS[tid]
        gate = evaluate_gate(
            judoka, td, graph,
            offensive_desperation=offensive_desperation,
            defensive_desperation=defensive_desperation,
        )
        if not gate.allowed:
            continue   # try the next throw
        return commit_throw(
            tid,
            offensive_desperation=offensive_desperation,
            defensive_desperation=defensive_desperation,
            gate_bypass_reason=gate.reason if gate.bypassed else None,
            gate_bypass_kind=gate.bypass_kind,
        )

    # HAJ-67 — non-scoring motivation dispatch. Skipped when either
    # desperation flag is already firing; those have higher precedence.
    if offensive_desperation or defensive_desperation:
        return None

    motivation = _select_non_scoring_motivation(
        judoka, opponent, graph, rng,
        kumi_kata_clock=kumi_kata_clock,
        opponent_kumi_kata_clock=opponent_kumi_kata_clock,
        perceived_by_throw=perceived_by_throw,
    )
    if motivation is None:
        return None

    tid = _select_false_attack_throw(judoka, graph)
    if tid is None:
        return None
    return commit_throw(
        tid,
        commit_motivation=motivation,
        gate_bypass_reason=REASON_INTENTIONAL_FALSE_ATTACK,
        gate_bypass_kind="false_attack",
    )


# ---------------------------------------------------------------------------
# HAJ-67 — non-scoring commit motivation: dispatcher + per-motivation gates
# ---------------------------------------------------------------------------
def _select_non_scoring_motivation(
    judoka: "Judoka",
    opponent: "Judoka",
    graph: "GripGraph",
    rng: random.Random,
    *,
    kumi_kata_clock: int,
    opponent_kumi_kata_clock: int,
    perceived_by_throw: dict[ThrowID, float],
) -> Optional[CommitMotivation]:
    """Dispatch to the first non-scoring motivation whose gate fires.

    Each predicate is self-contained and performs its own hard gates plus
    per-tick probability roll. Priority order: CLOCK_RESET, then
    STAMINA_DESPERATION, GRIP_ESCAPE, SHIDO_FARMING.
    """
    # All four motivations pick from drop-variant preferences; if the
    # fighter has none, skip the whole dispatch.
    if not any(tid in judoka.capability.throw_vocabulary
               for tid in FALSE_ATTACK_PREFERENCES):
        return None

    if _should_fire_clock_reset(judoka, kumi_kata_clock, rng):
        return CommitMotivation.CLOCK_RESET
    if _should_fire_stamina_desperation(judoka, rng):
        return CommitMotivation.STAMINA_DESPERATION
    if _should_fire_grip_escape(judoka, opponent, graph, rng):
        return CommitMotivation.GRIP_ESCAPE
    if _should_fire_shido_farming(
        judoka, opponent_kumi_kata_clock, perceived_by_throw, rng,
    ):
        return CommitMotivation.SHIDO_FARMING
    return None


def _should_fire_clock_reset(
    judoka: "Judoka", kumi_kata_clock: int,
    rng: Optional[random.Random] = None,
) -> bool:
    """CLOCK_RESET — HAJ-49 legacy. Fighter with composure and style-dna
    disposition fires a tactical fake in the pre-shido window to reset
    their own kumi-kata clock.
    """
    if not (FALSE_ATTACK_CLOCK_MIN <= kumi_kata_clock < FALSE_ATTACK_CLOCK_MAX):
        return False
    if judoka.capability.fight_iq < FALSE_ATTACK_MIN_FIGHT_IQ:
        return False
    tendency = judoka.identity.style_dna.get(
        FALSE_ATTACK_TENDENCY_KEY, FALSE_ATTACK_TENDENCY_DEFAULT,
    )
    if tendency < FALSE_ATTACK_TENDENCY_THRESHOLD:
        return False
    if rng is None:
        return True
    return rng.random() < tendency * FALSE_ATTACK_PER_TICK_SCALE


def _should_fire_stamina_desperation(
    judoka: "Judoka", rng: Optional[random.Random] = None,
) -> bool:
    """STAMINA_DESPERATION — tori is cardio-cooked, has eaten at least one
    shido, and can't drive force through grips (proxy: hand fatigue above
    threshold). A cooked, penalized fighter falls into anything to buy
    time on the mat.
    """
    if judoka.state.cardio_current > STAMINA_DESPERATION_CARDIO_MAX:
        return False
    if judoka.state.shidos < STAMINA_DESPERATION_MIN_SHIDOS:
        return False
    if _avg_hand_fatigue(judoka) < STAMINA_DESPERATION_HAND_FAT_MIN:
        return False
    if rng is None:
        return True
    return rng.random() < STAMINA_DESPERATION_PER_TICK_PROB


def _should_fire_grip_escape(
    judoka: "Judoka", opponent: "Judoka", graph: "GripGraph",
    rng: Optional[random.Random] = None,
) -> bool:
    """GRIP_ESCAPE — opponent is dominant in the grip war, tori's own
    grips are shallow/few, and composure has slipped. The tactical fake
    is cover to rip off the dyad and try to reset grips.
    """
    # Opponent grip dominance.
    delta_opp_over_tori = graph.compute_grip_delta(opponent, judoka)
    if delta_opp_over_tori < GRIP_ESCAPE_DELTA_THRESHOLD:
        return False
    # Tori's own grip integrity compromised: no edge deeper than POCKET.
    own_edges = graph.edges_owned_by(judoka.identity.name)
    deepest = max(
        (e.depth_level for e in own_edges),
        default=GripDepth.SLIPPING,
        key=lambda d: d.modifier(),
    )
    if deepest.modifier() > GripDepth.POCKET.modifier():
        return False
    # Composure below escape threshold.
    ceiling = max(1.0, float(judoka.capability.composure_ceiling))
    composure_frac = judoka.state.composure_current / ceiling
    if composure_frac >= GRIP_ESCAPE_COMPOSURE_FRAC:
        return False
    if rng is None:
        return True
    return rng.random() < GRIP_ESCAPE_PER_TICK_PROB


def _should_fire_shido_farming(
    judoka: "Judoka", opponent_kumi_kata_clock: int,
    perceived_by_throw: dict[ThrowID, float],
    rng: Optional[random.Random] = None,
) -> bool:
    """SHIDO_FARMING — opponent has been passive (their kumi-kata clock is
    elevated), tori has no real scoring opportunity, and tori's style
    tolerates grinding the referee for the opposing shido. Tori poses an
    attack to keep themselves above the passivity bar while forcing uke
    to either escalate or eat a shido of their own.
    """
    if opponent_kumi_kata_clock < SHIDO_FARMING_OPP_CLOCK:
        return False
    # No meaningful scoring opportunity: best-perceived signature is below
    # the "could-almost-score" threshold.
    if perceived_by_throw:
        best = max(perceived_by_throw.values())
        if best >= SHIDO_FARMING_NO_SCORING_MAX:
            return False
    tendency = judoka.identity.style_dna.get(
        SHIDO_FARMING_TENDENCY_KEY, SHIDO_FARMING_TENDENCY_DEFAULT,
    )
    if tendency < SHIDO_FARMING_TENDENCY_THRESHOLD:
        return False
    if rng is None:
        return True
    return rng.random() < SHIDO_FARMING_PER_TICK_PROB


def _select_false_attack_throw(
    judoka: "Judoka", graph: "GripGraph",
) -> Optional[ThrowID]:
    """Pick the most-preferred drop variant that's (a) in the fighter's
    vocabulary, (b) has a registered THROW_DEFS entry, and (c) passes
    minimal grip-presence: at least one owned edge exists (the `not
    own_edges` rung 1 check already enforced this upstream, but being
    explicit here keeps the helper self-contained).

    Returns None if no candidate qualifies — caller falls through.
    """
    own_edges = graph.edges_owned_by(judoka.identity.name)
    if not own_edges:
        return None
    for tid in FALSE_ATTACK_PREFERENCES:
        if tid not in judoka.capability.throw_vocabulary:
            continue
        if tid not in THROW_DEFS:
            continue
        return tid
    return None


def _direction_toward(judoka: "Judoka", opponent: "Judoka") -> tuple[float, float]:
    """Unit vector from judoka's CoM toward opponent's CoM, in world frame."""
    ax, ay = judoka.state.body_state.com_position
    bx, by = opponent.state.body_state.com_position
    dx, dy = bx - ax, by - ay
    norm = (dx * dx + dy * dy) ** 0.5
    if norm < 1e-9:
        return (1.0, 0.0)
    return (dx / norm, dy / norm)


def _avg_hand_fatigue(judoka: "Judoka") -> float:
    rh = judoka.state.body.get("right_hand")
    lh = judoka.state.body.get("left_hand")
    if rh is None or lh is None:
        return 0.0
    return 0.5 * (rh.fatigue + lh.fatigue)


def _primary_hand(judoka: "Judoka") -> str:
    return ("right_hand"
            if judoka.identity.dominant_side == DominantSide.RIGHT
            else "left_hand")


def _free_hand(judoka: "Judoka") -> Optional[str]:
    from body_state import ContactState as _CS
    for key in ("right_hand", "left_hand"):
        ps = judoka.state.body.get(key)
        if ps is not None and ps.contact_state != _CS.GRIPPING_UKE:
            return key
    return None
