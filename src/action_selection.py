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
    GripTypeV2, GripDepth, GripTarget, GripMode, DominantSide, StanceMatchup,
    PositionalStyle,
)
from throws import THROW_DEFS, ThrowID
from grip_presence_gate import evaluate_gate, GateResult, REASON_OK
from compromised_state import is_desperation_state
from commit_motivation import CommitMotivation

if TYPE_CHECKING:
    from judoka import Judoka
    from grip_graph import GripGraph, GripEdge


# Tuning constants (calibration stubs).
# HAJ-128 — bumped from 0.65 to 0.78. Pre-bump, throws fired in close
# succession because the perceived signature crossed the threshold often
# during grip-fighting; viewer feedback was "more throw attempts than
# actual grip attempts." A higher threshold means the grip war has to
# actually produce a high-quality opening before a throw fires, so
# grip work dominates the tick budget the way it does in real judo.
COMMIT_THRESHOLD:             float = 0.78  # perceived signature must clear this to commit
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
    desperation_jitter: Optional[dict] = None,
    current_tick: int = 0,
) -> list[Action]:
    """Return the judoka's chosen actions for this tick.

    Implements the Part 3.3 priority ladder. Returns 1-2 Actions, or a
    single-element list containing COMMIT_THROW. HAJ-128 may append a
    STEP locomotion action to the result when positional intent fires.
    """
    r = rng if rng is not None else random
    actions = _select_grip_actions(
        judoka, opponent, graph, kumi_kata_clock, r,
        defensive_desperation=defensive_desperation,
        opponent_kumi_kata_clock=opponent_kumi_kata_clock,
        opponent_in_progress_throw=opponent_in_progress_throw,
        desperation_jitter=desperation_jitter,
        current_tick=current_tick,
    )
    # HAJ-128 — locomotion is additive, never replaces grip work. Skip
    # when a commit is in flight (commits are exclusive in the ladder)
    # or when the fighter is stunned.
    if any(a.kind == ActionKind.COMMIT_THROW for a in actions):
        return actions
    if judoka.state.stun_ticks > 0:
        return actions
    step_action = _maybe_emit_step(judoka, opponent, graph, r)
    if step_action is not None:
        actions = list(actions) + [step_action]
    return actions


def _select_grip_actions(
    judoka: "Judoka",
    opponent: "Judoka",
    graph: "GripGraph",
    kumi_kata_clock: int,
    r: random.Random,
    *,
    defensive_desperation: bool = False,
    opponent_kumi_kata_clock: int = 0,
    opponent_in_progress_throw: Optional[ThrowID] = None,
    desperation_jitter: Optional[dict] = None,
    current_tick: int = 0,
) -> list[Action]:
    """The grip / commit / probe priority ladder. Pre-HAJ-128 this was
    the body of select_actions; locomotion now wraps it.

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
    offensive_desperation = is_desperation_state(
        judoka, kumi_kata_clock, jitter=desperation_jitter,
    )
    commit = _try_commit(
        judoka, opponent, graph, r,
        offensive_desperation=offensive_desperation,
        defensive_desperation=defensive_desperation,
        kumi_kata_clock=kumi_kata_clock,
        opponent_kumi_kata_clock=opponent_kumi_kata_clock,
        current_tick=current_tick,
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
        # HAJ-138 — rotate which shallow edge to deepen. Pre-fix, this
        # always picked own_edges[0] (the lapel, created first at
        # engagement), so the sleeve never advanced and the log was an
        # endless string of "deepens LAPEL_HIGH" lines. Rotate through
        # the shallow edges by tick so both hands get a turn, with the
        # established_tick as a stable secondary key so the order is
        # deterministic across calls.
        shallow_sorted = sorted(
            own_edges,
            key=lambda e: (e.depth_level.modifier(), e.established_tick),
        )
        edge_to_deepen = shallow_sorted[current_tick % len(shallow_sorted)]
        out: list[Action] = [deepen(edge_to_deepen)]
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
    current_tick: int = 0,
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
        actual = actual_signature_match(tid, judoka, opponent, graph,
                                        current_tick=current_tick)
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
    # HAJ-51 — feed the current matchup so dominance reflects per-grip
    # stance leverage. A pistol-grip-heavy opponent looks less dominant
    # in matched stance than in mirrored, even at the same depth/strength.
    matchup = StanceMatchup.of(
        judoka.state.current_stance, opponent.state.current_stance
    )
    delta_opp_over_tori = graph.compute_grip_delta(opponent, judoka, matchup)
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


# ---------------------------------------------------------------------------
# LOCOMOTION (HAJ-128)
# ---------------------------------------------------------------------------
# Tactical mat positioning. Three styles drive different intents:
#   - PRESSURE: drive opponent toward edge by stepping toward them
#   - DEFENSIVE_EDGE: retreat toward center when own perceived edge is close
#   - HOLD_CENTER: stay near center; only step toward center when far drift
#
# Magnitudes are intentionally small (per-tick step is part of a
# weight-transfer phase, not a full body move). Step gates with grip range:
# heavy opponent grips drag the fighter and reduce step magnitude.

# Per-tick STEP magnitude in meters. A real judo step is ~30-50 cm; we
# pick the lower end so per-tick motion is calm but visibly cumulative
# across a 4-minute match on the 8 m contest area. CoM advances at half
# the foot magnitude (one tick = one weight-transfer phase).
STEP_MAGNITUDE_M:           float = 0.30
STEP_MAGNITUDE_REDUCED_M:   float = 0.14   # under heavy opponent grips

# How frequently each style attempts a step (per-tick probability gates).
PRESSURE_BASE_STEP_PROB:    float = 0.55   # PRESSURE keeps the heat on
PRESSURE_RAMP_PROB_PER_M:   float = 0.10   # extra prob per meter opp is from edge
DEFENSIVE_EDGE_TRIGGER_M:   float = 1.6    # perceived edge < this → retreat
DEFENSIVE_EDGE_STEP_PROB:   float = 0.85   # high — retreat is urgent
HOLD_CENTER_DRIFT_M:        float = 0.6    # |com| > this → small recentering step
HOLD_CENTER_STEP_PROB:      float = 0.30

# Grip-range gating: if any opponent grip on this fighter has depth ≥ DEEP,
# consider the fighter "tied" and reduce step magnitude.
def _opponent_grip_drag(judoka: "Judoka", graph: "GripGraph") -> bool:
    """True when the opponent has a deep grip on this fighter — heavy drag
    means the fighter can't take a clean step."""
    for e in graph.edges_targeting(judoka.identity.name):
        if e.depth_level == GripDepth.DEEP:
            return True
    return False


def _trailing_step_foot(
    judoka: "Judoka", direction: tuple[float, float],
) -> str:
    """Pick which foot to step with — the trailing one. Real walking
    moves the foot that's currently behind the body in the direction of
    travel; the leading foot stays planted as the new pivot. We pick
    whichever foot has the smaller dot-product with the step direction
    relative to the body's CoM (i.e. is further behind).

    This avoids the pre-fix bug where one foot kept stepping forward and
    the other was abandoned at the start position, splitting the dots.
    """
    bs = judoka.state.body_state
    cx, cy = bs.com_position
    dx, dy = direction
    lx, ly = bs.foot_state_left.position
    rx, ry = bs.foot_state_right.position
    # Project each foot's offset-from-CoM onto the step direction. The
    # foot with the SMALLER projection is the trailing foot — pick it.
    left_proj  = (lx - cx) * dx + (ly - cy) * dy
    right_proj = (rx - cx) * dx + (ry - cy) * dy
    return "left_foot" if left_proj < right_proj else "right_foot"


def _step_action(judoka: "Judoka", direction: tuple[float, float],
                 magnitude: float) -> Optional[Action]:
    """Build a STEP action in `direction` of `magnitude`, picking the
    trailing foot for the chosen direction so the pair walks naturally
    instead of abandoning the off-side foot."""
    nx, ny = direction
    norm = (nx * nx + ny * ny) ** 0.5
    if norm == 0:
        return None
    unit = (nx / norm, ny / norm)
    foot = _trailing_step_foot(judoka, unit)
    return step(foot, unit, magnitude)


# Grip-war evasion: every fighter, regardless of positional style,
# circles laterally during active grip exchanges. Real judo: grip
# fighting is constant lateral motion — angling, breaking line, evading
# the next reach. Without this, fighters who aren't PRESSURE-styled
# stand still while throws fire on top of them. Probability is modest
# so style-driven motion still dominates when it fires.
GRIP_WAR_EVASION_PROB:      float = 0.30
GRIP_WAR_EVASION_MAG_M:     float = 0.18


def _maybe_emit_step(
    judoka: "Judoka", opponent: "Judoka", graph: "GripGraph",
    rng: random.Random,
) -> Optional[Action]:
    """Decide whether to emit a STEP action this tick based on the
    fighter's positional style. Returns the Action or None.

    Reads perceived edge distance via perception.perceive_edge_distance,
    so fight_iq / fatigue / composure all modulate the decision through
    the same noise model the throw-signature path uses.
    """
    from perception import perceive_edge_distance
    from match import MAT_HALF_WIDTH

    style = getattr(judoka.identity, "positional_style", PositionalStyle.HOLD_CENTER)

    # Magnitude attenuates under deep opponent grips.
    mag = (STEP_MAGNITUDE_REDUCED_M if _opponent_grip_drag(judoka, graph)
           else STEP_MAGNITUDE_M)

    # HAJ-128 — grip-war evasion. When both fighters have edges (active
    # grip war), every fighter takes occasional small lateral steps to
    # angle / break line. Fires before the style-specific intent so the
    # constant tactical motion is visible on the viewer regardless of
    # whether the style is PRESSURE.
    own_edges = graph.edges_owned_by(judoka.identity.name)
    opp_edges = graph.edges_owned_by(opponent.identity.name)
    if own_edges and opp_edges and rng.random() < GRIP_WAR_EVASION_PROB:
        evade = _grip_war_evasion_direction(judoka, opponent, rng)
        if evade is not None:
            return _step_action(judoka, evade, GRIP_WAR_EVASION_MAG_M)

    if style == PositionalStyle.HOLD_CENTER:
        # Only step toward center when the fighter has drifted noticeably.
        x, y = judoka.state.body_state.com_position
        if abs(x) <= HOLD_CENTER_DRIFT_M and abs(y) <= HOLD_CENTER_DRIFT_M:
            return None
        if rng.random() > HOLD_CENTER_STEP_PROB:
            return None
        return _step_action(judoka, (-x, -y), mag)

    if style == PositionalStyle.DEFENSIVE_EDGE:
        # Retreat toward center when own perceived edge is close.
        own_edge = perceive_edge_distance(judoka, MAT_HALF_WIDTH, rng)
        if own_edge >= DEFENSIVE_EDGE_TRIGGER_M:
            return None
        if rng.random() > DEFENSIVE_EDGE_STEP_PROB:
            return None
        x, y = judoka.state.body_state.com_position
        if abs(x) < 1e-6 and abs(y) < 1e-6:
            return None
        return _step_action(judoka, (-x, -y), mag)

    if style == PositionalStyle.PRESSURE:
        # Drive opponent toward the edge by stepping into them. Probability
        # ramps up as opponent's PERCEIVED edge distance shrinks — pressure
        # builds when the prey nears the rope.
        opp_edge = perceive_edge_distance(opponent, MAT_HALF_WIDTH, rng)
        proximity_term = max(0.0, MAT_HALF_WIDTH - opp_edge) * PRESSURE_RAMP_PROB_PER_M
        prob = min(0.95, PRESSURE_BASE_STEP_PROB + proximity_term)
        if rng.random() > prob:
            return None
        return _step_action(judoka, _pressure_direction(judoka, opponent, rng), mag)

    return None


def _grip_war_evasion_direction(
    judoka: "Judoka", opponent: "Judoka", rng: random.Random,
) -> Optional[tuple[float, float]]:
    """HAJ-128 — pick a lateral evasion direction during active grip
    fighting. Step perpendicular to the line of attack, randomized side
    per tick so the fighter circles. Pressure-fighters bias forward
    along that perpendicular; defenders / hold-center bias rearward."""
    sx, sy = judoka.state.body_state.com_position
    ox, oy = opponent.state.body_state.com_position
    dx, dy = ox - sx, oy - sy
    norm = (dx * dx + dy * dy) ** 0.5
    if norm < 1e-6:
        return None
    fx, fy = dx / norm, dy / norm
    # 90° rotation: perpendicular to line of attack.
    perp_x, perp_y = -fy, fx
    # Randomize side.
    if rng.random() < 0.5:
        perp_x, perp_y = -perp_x, -perp_y
    # Style bias: PRESSURE leans into the opponent while circling;
    # defenders lean away. HOLD_CENTER stays purely lateral.
    style = getattr(judoka.identity, "positional_style", PositionalStyle.HOLD_CENTER)
    forward_bias = 0.0
    if style == PositionalStyle.PRESSURE:
        forward_bias = +0.4
    elif style == PositionalStyle.DEFENSIVE_EDGE:
        forward_bias = -0.4
    return (perp_x + fx * forward_bias, perp_y + fy * forward_bias)


def _pressure_direction(
    judoka: "Judoka", opponent: "Judoka", rng: random.Random,
) -> tuple[float, float]:
    """HAJ-128 — pressure-fighter step direction.

    Pure "step toward opponent" produces 1D forward/back movement: with
    fighters starting on the x-axis, every step is along x and the match
    plays in a horizontal stripe. Real pressure-fighters angle their
    opponent toward a corner — the line of attack tilts off-axis.

    Direction is a blend of:
      1. Toward the opponent's CoM (60%) — keep applying pressure.
      2. Toward the corner the opponent is closest to (40%) — angle them
         into the rope. Per-axis: pick whichever edge the opponent is
         closer to in x and in y; sum drives the diagonal.

    Pressure-fighter alternates lateral side via a small per-tick jitter
    so the motion isn't perfectly straight even when both fighters sit
    on the x-axis.
    """
    from match import MAT_HALF_WIDTH

    sx, sy = judoka.state.body_state.com_position
    ox, oy = opponent.state.body_state.com_position
    base_dx, base_dy = (ox - sx), (oy - sy)
    base_norm = (base_dx * base_dx + base_dy * base_dy) ** 0.5 or 1.0
    base_dx /= base_norm
    base_dy /= base_norm

    # Corner the opponent is currently angling toward (per axis).
    # Tie-break with a small jitter so two fighters on the x-axis pick
    # a side instead of trying to step purely +x and stuttering.
    edge_x = MAT_HALF_WIDTH if ox >= -1e-6 else -MAT_HALF_WIDTH
    edge_y = MAT_HALF_WIDTH if oy >= 0 else -MAT_HALF_WIDTH
    if abs(oy) < 0.1:
        # Roughly on the x-axis — randomize the lateral side (left vs right).
        edge_y = MAT_HALF_WIDTH if rng.random() < 0.5 else -MAT_HALF_WIDTH

    corner_dx = edge_x - ox
    corner_dy = edge_y - oy
    cn = (corner_dx * corner_dx + corner_dy * corner_dy) ** 0.5 or 1.0
    corner_dx /= cn
    corner_dy /= cn

    return (
        base_dx * 0.60 + corner_dx * 0.40,
        base_dy * 0.60 + corner_dy * 0.40,
    )
