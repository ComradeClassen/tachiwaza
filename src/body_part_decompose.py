# body_part_decompose.py
# HAJ-145 — decomposition of engine actions into BodyPartEvent sequences.
#
# Each `decompose_*` function takes the engine state of one event (a grip
# change, a kuzushi-bearing force action, a counter, a throw commit) and
# returns the structured BodyPartEvent list that event reduces to. The
# functions are pure: no Match mutation, no I/O. The Match wires them in
# at every emission site and stores the result both on the parent Event's
# `data["body_part_events"]` and on Match.body_part_events.
#
# This module is the bridge between the simulation's mechanical vocabulary
# (REACH / DEEPEN / PULL / COMMIT_THROW / kuzushi events) and the narrative
# vocabulary the prose layer will speak in. The mapping is deliberately
# data-driven — Couple throws decompose by reading their force-grips and
# body-part requirement; Lever throws read their fulcrum and required-forces
# tuple; foot attacks decompose from the action kind and direction. New
# throws, new actions, new kuzushi sources slot in by adding a decomposer,
# not by editing the prose layer.

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from body_part_events import (
    BodyPartEvent, BodyPartHigh, Side, BodyPartVerb, BodyPartTarget,
    Modifiers, Commitment,
    GripIntent, SteerDirection,
    compute_modifiers, side_for_hand, side_for_foot, side_for_body_part,
    target_from_grip_target, target_from_grip_type_v2,
    grip_holds_by_default, steer_direction_from_kuzushi,
)
from enums import BodyPart, GripDepth

if TYPE_CHECKING:
    from judoka import Judoka
    from grip_graph import GripEdge
    from throw_templates import (
        ThrowTemplate, CoupleBodyPartRequirement, LeverBodyPartRequirement,
    )


# ===========================================================================
# GRIP CHANGES
# ===========================================================================

def decompose_grip_establish(
    edge: "GripEdge", attacker: "Judoka", tick: int,
) -> list[BodyPartEvent]:
    """A new edge has seated. Emit one HANDS-GRIP event with the target
    collapsed onto the seven-element BodyPartTarget vocabulary."""
    grip_axis = _grip_axis_for(edge)
    mods = compute_modifiers(
        attacker, execution_axis=grip_axis,
        commitment=Commitment.COMMITTING,
    )
    target = (
        target_from_grip_target(edge.target_location.value)
        or target_from_grip_type_v2(edge.grip_type_v2.name)
    )
    # HAJ-146 — a freshly-seated grip has no kuzushi vector yet, so we
    # don't pick a steer direction here; the engine will set STEER and
    # the direction set when the first PULL through this edge fires.
    # Skilled fighters seat with non-HOLD intent (POST — establishing
    # control); below the skill threshold the grip emits as HOLD.
    intent = (GripIntent.HOLD
              if grip_holds_by_default(attacker, grip_axis)
              else GripIntent.POST)
    _set_edge_intent(edge, intent)
    return [BodyPartEvent(
        tick=tick, actor=attacker.identity.name,
        part=BodyPartHigh.HANDS,
        side=side_for_body_part(edge.grasper_part.value),
        verb=BodyPartVerb.GRIP, target=target,
        modifiers=mods, source="GRIP_ESTABLISH",
        intent=intent,
    )]


def decompose_grip_deepen(
    edge: "GripEdge", prior_depth: GripDepth, attacker: "Judoka", tick: int,
) -> list[BodyPartEvent]:
    """A grip seated more deeply. The narrative beat is the grasper hand
    *pulling* the grip closer to the body — same hand-part, distinct verb
    (PULL is the closest fit on the initial hand vocabulary; HAJ-147 may
    introduce a dedicated DEEPEN verb if prose needs it). Emitting PULL
    here lets §13.8 self-cancel detection treat a deepen-while-stepping
    pattern as a contradiction in the same way it treats a force PULL."""
    grip_axis = _grip_axis_for(edge)
    mods = compute_modifiers(
        attacker, execution_axis=grip_axis,
        commitment=Commitment.COMMITTING,
    )
    target = (
        target_from_grip_target(edge.target_location.value)
        or target_from_grip_type_v2(edge.grip_type_v2.name)
    )
    # HAJ-146 — a deepen IS the grasper improving control; STEER for any
    # fighter at-or-above grip threshold, HOLD below it.
    intent = (GripIntent.HOLD
              if grip_holds_by_default(attacker, grip_axis)
              else GripIntent.STEER)
    steer = (frozenset({SteerDirection.FORWARD})
             if intent is GripIntent.STEER else None)
    _set_edge_intent(edge, intent, steer)
    return [BodyPartEvent(
        tick=tick, actor=attacker.identity.name,
        part=BodyPartHigh.HANDS,
        side=side_for_body_part(edge.grasper_part.value),
        verb=BodyPartVerb.PULL, target=target,
        modifiers=mods, source="GRIP_DEEPEN",
        intent=intent, steer_direction=steer,
    )]


def decompose_grip_strip(
    stripper: "Judoka", target_edge: "GripEdge", tick: int,
    had_effect: bool,
) -> list[BodyPartEvent]:
    """Stripping pressure was applied to an opponent's edge.

    The narrative beat is the stripper's hand *breaking* the grip (when the
    strip had any mechanical effect — degraded a level or removed it) or
    *snapping* at it fruitlessly (when the grip held with no effect). HAJ-225
    — `had_effect` discriminates: pre-fix a partial degrade emitted a SNAP
    that the mat-side narrator read as "can't budge it," misreporting a
    successful partial strip as a failure. Now SNAP is reserved for the
    genuine no-effect case; partial and full strips carry BREAK and are
    narrated off the GRIP_DEGRADE / GRIP_STRIPPED engine events.

    HAJ-146 — strip events always carry intent=BREAK regardless of skill:
    that's the structural purpose of a strip."""
    mods = compute_modifiers(
        stripper, execution_axis="stripping",
        commitment=Commitment.COMMITTING,
    )
    verb = BodyPartVerb.BREAK if had_effect else BodyPartVerb.SNAP
    target = (
        target_from_grip_target(target_edge.target_location.value)
        or target_from_grip_type_v2(target_edge.grip_type_v2.name)
    )
    # The opposing edge being attacked has its current_intent flipped to
    # BREAK so the head-as-output computation drops it from active steerers.
    _set_edge_intent(target_edge, GripIntent.BREAK)
    return [BodyPartEvent(
        tick=tick, actor=stripper.identity.name,
        part=BodyPartHigh.HANDS, side=Side.NONE,
        verb=verb, target=target,
        modifiers=mods, source="GRIP_STRIP",
        intent=GripIntent.BREAK,
    )]


def decompose_grip_release(
    edge: "GripEdge", attacker: "Judoka", tick: int,
) -> list[BodyPartEvent]:
    mods = compute_modifiers(
        attacker, execution_axis=_grip_axis_for(edge),
        commitment=Commitment.TENTATIVE,
    )
    target = (
        target_from_grip_target(edge.target_location.value)
        or target_from_grip_type_v2(edge.grip_type_v2.name)
    )
    return [BodyPartEvent(
        tick=tick, actor=attacker.identity.name,
        part=BodyPartHigh.HANDS,
        side=side_for_body_part(edge.grasper_part.value),
        verb=BodyPartVerb.RELEASE, target=target,
        modifiers=mods, source="GRIP_RELEASE",
        # No intent — the grip is being let go, not used.
    )]


def decompose_reach(
    attacker: "Judoka", hand: str, target_loc: Optional[str], tick: int,
) -> list[BodyPartEvent]:
    """The attacker is closing distance / committing the hand toward a grip.
    Emitted when REACH fires; no edge yet exists."""
    axis = "lapel_grip" if (target_loc and "lapel" in target_loc.lower()) else "sleeve_grip"
    mods = compute_modifiers(
        attacker, execution_axis=axis, commitment=Commitment.COMMITTING,
    )
    target = target_from_grip_target(target_loc or "") if target_loc else None
    # A reach is committing-to-grip: skilled fighters reach with a target
    # control vector (POST as a placeholder until the grip seats and the
    # action context picks the real intent); novices reach to hold.
    intent = (GripIntent.HOLD if grip_holds_by_default(attacker, axis)
              else GripIntent.POST)
    return [BodyPartEvent(
        tick=tick, actor=attacker.identity.name,
        part=BodyPartHigh.HANDS, side=side_for_hand(hand),
        verb=BodyPartVerb.REACH, target=target,
        modifiers=mods, source="REACH", intent=intent,
    )]


# ===========================================================================
# KUZUSHI-BEARING FORCE ACTIONS
# ===========================================================================

def decompose_pull(
    attacker: "Judoka", edge: "GripEdge",
    direction: tuple[float, float], magnitude: float,
    tick: int, *, overcommitted: bool = False,
    timing_hint: Optional[str] = None,
) -> list[BodyPartEvent]:
    """A PULL action delivering force through `edge`. The narrative beat is
    the hand pulling on its target with a direction; the elbow's tightness
    follows the actor's pull_execution axis. Emits TWO events: HANDS-PULL
    (carrying the kuzushi vector for §13.8 detection downstream) and
    ELBOWS-TIGHT/FLARE (driven by the same axis)."""
    commitment = Commitment.OVERCOMMITTED if overcommitted else Commitment.COMMITTING
    mods = compute_modifiers(
        attacker, execution_axis="pull_execution",
        commitment=commitment, timing_hint=timing_hint,
    )
    target = (
        target_from_grip_target(edge.target_location.value)
        or target_from_grip_type_v2(edge.grip_type_v2.name)
    )
    side = side_for_body_part(edge.grasper_part.value)
    # HAJ-146 — driving force through a grip IS steering. Below the grip
    # threshold a fighter still emits HOLD (mechanically the force is real,
    # but the prose layer should read it as "pulling on the grip" rather
    # than "driving uke's head"). Steer direction comes from the kuzushi
    # vector — sleeve pulls and collar pulls produce different downstream
    # head verbs, so we derive direction from the actual force vector.
    grip_axis = _grip_axis_for(edge)
    if grip_holds_by_default(attacker, grip_axis):
        intent = GripIntent.HOLD
        steer = None
    else:
        intent = GripIntent.STEER
        steer = steer_direction_from_kuzushi(direction)
    _set_edge_intent(edge, intent, steer)
    return [
        BodyPartEvent(
            tick=tick, actor=attacker.identity.name,
            part=BodyPartHigh.HANDS, side=side,
            verb=BodyPartVerb.PULL, target=target,
            direction=(direction[0], direction[1]),
            modifiers=mods, source="PULL",
            intent=intent, steer_direction=steer,
        ),
        BodyPartEvent(
            tick=tick, actor=attacker.identity.name,
            part=BodyPartHigh.ELBOWS, side=side,
            # Tightness modifier already encodes which side of the spectrum
            # the elbow is on; the verb mirrors it for downstream readers
            # that key on the verb alone.
            verb=(BodyPartVerb.TIGHT if (mods.tightness and mods.tightness.name == "TIGHT")
                  else BodyPartVerb.FLARE),
            modifiers=mods, source="PULL",
        ),
    ]


def decompose_foot_attack(
    attacker: "Judoka", action_kind_name: str, foot: str,
    direction: tuple[float, float], magnitude: float, tick: int,
) -> list[BodyPartEvent]:
    """FOOT_SWEEP_SETUP / LEG_ATTACK_SETUP / DISRUPTIVE_STEP. The narrative
    beat is the foot REAPing / HOOKing / STEPping with a direction vector
    that carries the kuzushi push."""
    if action_kind_name == "FOOT_SWEEP_SETUP":
        verb = BodyPartVerb.REAP
        axis = "foot_sweeps"
    elif action_kind_name == "LEG_ATTACK_SETUP":
        verb = BodyPartVerb.HOOK
        axis = "leg_attacks"
    elif action_kind_name == "DISRUPTIVE_STEP":
        verb = BodyPartVerb.STEP
        axis = "disruptive_stepping"
    else:
        verb = BodyPartVerb.STEP
        axis = "tsugi_ashi"
    mods = compute_modifiers(
        attacker, execution_axis=axis, commitment=Commitment.COMMITTING,
    )
    return [BodyPartEvent(
        tick=tick, actor=attacker.identity.name,
        part=BodyPartHigh.FEET, side=side_for_foot(foot),
        verb=verb, direction=(direction[0], direction[1]),
        modifiers=mods, source=action_kind_name,
    )]


def decompose_step(
    actor: "Judoka", foot: str,
    direction: tuple[float, float], magnitude: float, tick: int,
    *, source: str = "STEP",
) -> list[BodyPartEvent]:
    """A locomotion STEP. Emitted alongside PULLs so §13.8 detection can
    score the dot product between hand-pull and base-step directions."""
    mods = compute_modifiers(
        actor, execution_axis="tsugi_ashi", commitment=Commitment.TENTATIVE,
    )
    return [BodyPartEvent(
        tick=tick, actor=actor.identity.name,
        part=BodyPartHigh.FEET, side=side_for_foot(foot),
        verb=BodyPartVerb.STEP, direction=(direction[0], direction[1]),
        modifiers=mods, source=source,
    )]


# ===========================================================================
# THROW COMMITS — full-body decomposition driven by template requirements
# ===========================================================================

# ---------------------------------------------------------------------------
# PER-THROW INTENT SPECS (HAJ-146)
# The five canonical throws have distinct hikite/tsurite intents per the
# ticket spec. Other throws fall back to a derived default — hikite =
# BREAK if the kuzushi vector pulls down, otherwise STEER toward the
# kuzushi direction; tsurite = STEER toward kuzushi.
#
# Each entry is keyed by template.name (matches what the worked-throw
# instances declare). The value is (hikite_spec, tsurite_spec) where each
# spec is (GripIntent, frozenset[SteerDirection] | None).
# ---------------------------------------------------------------------------
_HIKITE_TSURITE_INTENTS: dict[str, tuple] = {
    # Ko-uchi-gari: sleeve break snaps; lapel steer-forward drives uke.
    "Ko-uchi-gari": (
        (GripIntent.BREAK, None),
        (GripIntent.STEER, frozenset({SteerDirection.FORWARD})),
    ),
    # Uchi-mata: sleeve hold pulls across; lapel forward-corner-up drives
    # head up-and-forward.
    "Uchi-mata": (
        (GripIntent.HOLD,  None),
        (GripIntent.STEER, frozenset({
            SteerDirection.FORWARD, SteerDirection.CORNER, SteerDirection.UP,
        })),
    ),
    # Seoi-nage: sleeve hold (tight); lapel down-across drives head over
    # the shoulder.
    "Seoi-nage": (
        (GripIntent.HOLD,  None),
        (GripIntent.STEER, frozenset({
            SteerDirection.DOWN, SteerDirection.CORNER,
        })),
    ),
    # O-soto-gari: lapel back-down drives head back; sleeve hold to
    # support the couple. (Some senseis prefer tight sleeve break here;
    # we keep it HOLD to match the ticket's example.)
    "O-soto-gari": (
        (GripIntent.HOLD,  None),
        (GripIntent.STEER, frozenset({
            SteerDirection.BACK, SteerDirection.DOWN,
        })),
    ),
    # Sasae-tsurikomi-ashi: sleeve break pulls up-and-across; lapel
    # up-around produces the *tsuri* (fishing-up).
    "Sasae-tsurikomi-ashi": (
        (GripIntent.BREAK, None),
        (GripIntent.STEER, frozenset({
            SteerDirection.UP, SteerDirection.CORNER,
        })),
    ),
}


def _intents_for_throw(
    template: "ThrowTemplate",
) -> tuple[tuple, tuple]:
    """Look up per-throw hikite/tsurite intents, falling back to a derived
    default for throws not in the table."""
    spec = _HIKITE_TSURITE_INTENTS.get(template.name)
    if spec is not None:
        return spec
    # Default: tsurite steers toward the kuzushi direction; hikite holds.
    # The kuzushi vector lives on the template.
    kdir = template.kuzushi_requirement.direction
    tsurite_steer = steer_direction_from_kuzushi(kdir)
    return (
        (GripIntent.HOLD, None),
        (GripIntent.STEER, tsurite_steer),
    )


def decompose_commit(
    attacker: "Judoka", defender: "Judoka",
    template: "ThrowTemplate", tick: int, *,
    overcommitted: bool = False, source: str = "COMMIT",
) -> list[BodyPartEvent]:
    """The committing action — the visible sequence the prose layer will
    eventually narrate. Walks the template's four signature dimensions and
    emits one BodyPartEvent per body-part beat:

      - kuzushi dimension      → HANDS-PULL (hikite, primary kuzushi vector)
      - force-grips dimension  → HANDS-PULL on each force-grip hand,
                                 directioned toward kuzushi vector
      - body-parts dimension   → FEET / KNEES / HIPS / SHOULDERS / POSTURE
                                 events specific to Couple vs Lever
      - posture dimension      → POSTURE-{verb} on uke (defender)

    The vocabulary is the same regardless of how the engine ultimately
    resolves the commit. HAJ-147 will refine prose register; here the
    structured stream is what matters.
    """
    from throw_templates import CoupleThrow, LeverThrow

    a_name = attacker.identity.name
    d_name = defender.identity.name
    commitment = Commitment.OVERCOMMITTED if overcommitted else Commitment.COMMITTING
    events: list[BodyPartEvent] = []

    # Resolve modifier bundles once per major axis.
    pull_mods = compute_modifiers(
        attacker, execution_axis="pull_execution", commitment=commitment,
    )
    timing_mods = compute_modifiers(
        attacker, execution_axis="timing", commitment=commitment,
    )

    # 1. Kuzushi vector — the directional pull tori is delivering through
    #    hikite. The kuzushi requirement direction is in uke's body frame;
    #    we surface it as the BPE direction so §13.8 can compose it against
    #    base-step directions.
    kuzushi_dir = template.kuzushi_requirement.direction
    # HAJ-146 — per-throw hikite/tsurite intents. The five canonical
    # worked throws have explicit specs from the ticket; everything else
    # derives from kuzushi direction.
    (hikite_intent, hikite_steer), (tsurite_intent, tsurite_steer) = (
        _intents_for_throw(template)
    )
    # Hikite hand is the sleeve-grip hand on the canonical worked-throws
    # (left_hand on the right-dominant instances). Read it off the first
    # SLEEVE force-grip; fall back to LEFT if absent.
    hikite_hand = _hikite_hand_from(template)
    # The hikite *verb* depends on intent: a BREAK intent reads as a SNAP
    # of the gripped sleeve; HOLD / STEER stay as PULL.
    hikite_verb = (BodyPartVerb.SNAP
                   if hikite_intent is GripIntent.BREAK
                   else BodyPartVerb.PULL)
    events.append(BodyPartEvent(
        tick=tick, actor=a_name,
        part=BodyPartHigh.HANDS, side=side_for_hand(hikite_hand),
        verb=hikite_verb, target=BodyPartTarget.SLEEVE,
        direction=kuzushi_dir, modifiers=pull_mods, source=source,
        intent=hikite_intent, steer_direction=hikite_steer,
    ))

    # 2. Tsurite (lapel/collar/belt hand) — the second pulling/lifting hand.
    tsurite_hand, tsurite_target = _tsurite_from(template)
    if tsurite_hand is not None:
        tsurite_verb = (BodyPartVerb.SNAP
                        if tsurite_intent is GripIntent.BREAK
                        else BodyPartVerb.PULL)
        events.append(BodyPartEvent(
            tick=tick, actor=a_name,
            part=BodyPartHigh.HANDS, side=side_for_hand(tsurite_hand),
            verb=tsurite_verb, target=tsurite_target,
            direction=kuzushi_dir,
            modifiers=pull_mods, source=source,
            intent=tsurite_intent, steer_direction=tsurite_steer,
        ))

    # 3. Body-parts dimension — branches Couple vs Lever.
    if isinstance(template, CoupleThrow):
        events.extend(_couple_body_events(
            attacker, template.body_part_requirement, kuzushi_dir,
            tick, source, commitment,
        ))
    elif isinstance(template, LeverThrow):
        events.extend(_lever_body_events(
            attacker, template.body_part_requirement, tick, source, commitment,
        ))

    # 4. Posture dimension — what the throw is doing to uke's posture.
    posture_verb = _posture_verb_for_kuzushi(kuzushi_dir)
    events.append(BodyPartEvent(
        tick=tick, actor=d_name,
        part=BodyPartHigh.POSTURE, side=Side.NONE,
        verb=posture_verb,
        modifiers=Modifiers(timing=timing_mods.timing),
        source=source,
    ))

    return events


# ---------------------------------------------------------------------------
# Couple body-events: supporting foot PROPS, attacking limb REAPs / HOOKs,
# hips LOAD if hip-loading, knees BEND on the supporting leg.
# ---------------------------------------------------------------------------
def _couple_body_events(
    attacker: "Judoka", req: "CoupleBodyPartRequirement",
    kuzushi_dir: tuple[float, float],
    tick: int, source: str, commitment: Commitment,
) -> list[BodyPartEvent]:
    a_name = attacker.identity.name
    events: list[BodyPartEvent] = []

    # Supporting foot — plants. PROP captures the specific propping geometry
    # (Sasae-tsurikomi-ashi: tori's foot lands AGAINST uke's lead-foot
    # instep to deny the step), distinguished from a sweep / reap that
    # pulls uke's foot AWAY (de-ashi-harai, ko-uchi-gari). The discriminator
    # is the kuzushi vector: a forward-direction kuzushi with a foot-timing
    # window IS the propping geometry; backward/lateral kuzushi with a
    # timing window is a sweep / reap.
    is_propping = (
        req.timing_window is not None and kuzushi_dir[0] > 0.5
    )
    foot_axis = "foot_sweeps" if (req.timing_window is not None) else "tsugi_ashi"
    foot_mods = compute_modifiers(
        attacker, execution_axis=foot_axis, commitment=commitment,
    )
    events.append(BodyPartEvent(
        tick=tick, actor=a_name,
        part=BodyPartHigh.FEET, side=side_for_foot(req.tori_supporting_foot),
        verb=BodyPartVerb.PROP if is_propping else BodyPartVerb.STEP,
        modifiers=foot_mods, source=source,
    ))

    # Attacking limb — REAP for foot-class throws (de-ashi, ko-uchi),
    # HOOK for leg-attack throws (uchi-mata, o-soto, o-uchi), STEP/PROP
    # for prop-class.
    attacking = req.tori_attacking_limb
    if attacking.endswith("_foot"):
        if is_propping:
            verb = BodyPartVerb.PROP
        else:
            verb = BodyPartVerb.REAP
        side = side_for_foot(attacking)
        part = BodyPartHigh.FEET
        attack_axis = "foot_sweeps"
    else:
        # *_leg attacking limb — uchi-mata / o-soto family. Reap with the leg.
        verb = BodyPartVerb.REAP
        side = side_for_body_part(attacking)
        part = BodyPartHigh.FEET   # narrative-layer: the foot end of the leg
        attack_axis = "leg_attacks"
    attack_mods = compute_modifiers(
        attacker, execution_axis=attack_axis, commitment=commitment,
    )
    events.append(BodyPartEvent(
        tick=tick, actor=a_name,
        part=part, side=side, verb=verb,
        modifiers=attack_mods, source=source,
    ))

    # Hip-loading throws (uchi-mata's hip-line proximity, harai-goshi's hip
    # load). The hip beat is LOAD when hip_loading is True, TURN_IN otherwise.
    hip_axis = "pivots"
    hip_mods = compute_modifiers(
        attacker, execution_axis=hip_axis, commitment=commitment,
    )
    events.append(BodyPartEvent(
        tick=tick, actor=a_name,
        part=BodyPartHigh.HIPS, side=Side.NONE,
        verb=BodyPartVerb.LOAD if req.hip_loading else BodyPartVerb.TURN_IN,
        modifiers=hip_mods, source=source,
    ))

    # Supporting-knee bend — the planted leg flexes to absorb the reap
    # reaction. CUT_INSIDE for ko-uchi-style inside-line attacks.
    knee_axis = "base_recovery"
    knee_mods = compute_modifiers(
        attacker, execution_axis=knee_axis, commitment=commitment,
    )
    knee_verb = BodyPartVerb.CUT_INSIDE if (
        attacking == req.tori_supporting_foot.replace("left", "right").replace("right", "left")
        and req.contact_point_on_uke in (BodyPart.LEFT_FOOT, BodyPart.RIGHT_FOOT)
    ) else BodyPartVerb.BEND
    events.append(BodyPartEvent(
        tick=tick, actor=a_name,
        part=BodyPartHigh.KNEES, side=side_for_foot(req.tori_supporting_foot),
        verb=knee_verb,
        modifiers=knee_mods, source=source,
    ))

    return events


# ---------------------------------------------------------------------------
# Lever body-events: fulcrum SHOULDER (or HIPS for hip-fulcrum) LIFT/LOAD,
# both feet POST in double support.
# ---------------------------------------------------------------------------
def _lever_body_events(
    attacker: "Judoka", req: "LeverBodyPartRequirement",
    tick: int, source: str, commitment: Commitment,
) -> list[BodyPartEvent]:
    a_name = attacker.identity.name
    events: list[BodyPartEvent] = []

    # Fulcrum part — SHOULDERS for seoi-nage, HIPS for o-goshi / harai-goshi
    # classical, KNEES for tai-otoshi, FEET for tomoe-nage / sumi-gaeshi.
    fulcrum_part = req.fulcrum_body_part
    pn = fulcrum_part.value
    if "shoulder" in pn:
        bp = BodyPartHigh.SHOULDERS
        side = side_for_body_part(pn)
        verb = BodyPartVerb.LIFT
    elif "hip" in pn or "lower_back" in pn:
        bp = BodyPartHigh.HIPS
        side = Side.NONE
        verb = BodyPartVerb.LOAD
    elif "knee" in pn:
        bp = BodyPartHigh.KNEES
        side = side_for_body_part(pn)
        verb = BodyPartVerb.BLOCK
    elif "foot" in pn or "leg" in pn:
        bp = BodyPartHigh.FEET
        side = side_for_body_part(pn)
        verb = BodyPartVerb.POST
    else:
        bp = BodyPartHigh.HIPS
        side = Side.NONE
        verb = BodyPartVerb.LOAD
    fulcrum_mods = compute_modifiers(
        attacker, execution_axis="pivots", commitment=commitment,
    )
    events.append(BodyPartEvent(
        tick=tick, actor=a_name,
        part=bp, side=side, verb=verb,
        modifiers=fulcrum_mods, source=source,
    ))

    # Base / supporting feet
    base_mods = compute_modifiers(
        attacker, execution_axis="base_recovery", commitment=commitment,
    )
    events.append(BodyPartEvent(
        tick=tick, actor=a_name,
        part=BodyPartHigh.BASE, side=Side.NONE,
        verb=BodyPartVerb.POST,
        modifiers=base_mods, source=source,
    ))

    return events


# ---------------------------------------------------------------------------
# COUNTER COMMIT
# A counter is just another commit by the *defender*; we route through
# decompose_commit but tag the source so altitude readers can group it.
# ---------------------------------------------------------------------------
def decompose_counter(
    counter_actor: "Judoka", counter_target: "Judoka",
    counter_template: Optional["ThrowTemplate"], tick: int,
) -> list[BodyPartEvent]:
    if counter_template is None:
        return []
    return decompose_commit(
        counter_actor, counter_target, counter_template, tick,
        source="COUNTER_COMMIT",
    )


# ===========================================================================
# HEAD AS OUTPUT (HAJ-146)
# Head state on each fighter is computed from the set of active steering
# grips on them. Sensei's framing — "if you have the collar, you are the
# head; the body will follow" — is mechanically correct: head verbs are
# rarely self-initiated; they are consequences of grips with intent.
#
# This function is called once per tick after force application. Returns
# zero or one BodyPartEvent per fighter:
#   - If any opposing grip on `victim` carries intent=STEER → emit one
#     HEAD event for victim with verb=DRIVING (or DOWN/UP/TURNED based on
#     the union of steer directions). Direction modifiers compose: a
#     forward-and-up steer produces a head event with DRIVING verb whose
#     steer_direction = {FORWARD, UP}.
#   - If no opposing grip is steering → no event. The head reverts to
#     owner control (which is the absence of an event in this layer).
#
# Multiple steering grips on the same victim union their directions —
# this captures the "two-on-one" head control that decides forward vs
# corner throws.
# ===========================================================================
def compute_head_state(
    victim: "Judoka", grip_graph, tick: int,
    grasper_resolver=None,
) -> list[BodyPartEvent]:
    """Return the HEAD body-part events for `victim` this tick. Empty
    when no opposing grip is steering. `grasper_resolver`, when supplied,
    is a `Callable[[str], Judoka]` that maps grasper_id to the Judoka
    object so modifier computation reads the right SkillVector. When
    omitted the head event still emits, just with default modifiers —
    callers running purely off the graph (unit tests) don't need to
    plumb the resolver."""
    v_name = victim.identity.name
    steerers: list = []
    union_dirs: set[SteerDirection] = set()
    for edge in grip_graph.edges:
        if edge.target_id != v_name:
            continue
        if edge.current_intent != "STEER":
            continue
        # HAJ-161 — head-as-output is mechanically *only* a collar-grip
        # output. A LAPEL_HIGH steers the torso, not the head; the
        # pre-fix path emitted "Renard's head is steered" off a lapel
        # grip, which was mechanically dishonest. Only COLLAR_BACK and
        # COLLAR_SIDE drive the HEAD body-part state. Other STEER-intent
        # edges still steer their own targets (torso, sleeve) — they
        # just don't aggregate into the head event.
        if not edge.grip_type_v2.is_collar():
            continue
        steerers.append(edge)
        if edge.steer_direction:
            for d_name in edge.steer_direction:
                try:
                    union_dirs.add(SteerDirection[d_name])
                except KeyError:
                    pass
    if not steerers:
        return []
    # Verb selection — DRIVING when any direction is set; DOWN / UP collapse
    # if the steer set is purely vertical; TURNED when only CORNER (no
    # forward/back). DOWN is a special-case render: collar-down-across
    # produces a head-down event without a vertical-only kuzushi vector.
    if not union_dirs:
        verb = BodyPartVerb.DRIVING
    elif union_dirs == {SteerDirection.DOWN}:
        verb = BodyPartVerb.DOWN
    elif union_dirs == {SteerDirection.UP}:
        verb = BodyPartVerb.UP
    elif union_dirs == {SteerDirection.CORNER}:
        verb = BodyPartVerb.TURNED
    else:
        verb = BodyPartVerb.DRIVING
    # The head event lives on the victim; modifiers reflect the grasper's
    # (i.e. the steerer's) execution quality. Where multiple steerers
    # exist we read the first one — v0.1; HAJ-147 may aggregate.
    primary = steerers[0]
    grasper = grasper_resolver(primary.grasper_id) if grasper_resolver else None
    if grasper is None:
        mods = Modifiers()
    else:
        mods = compute_modifiers(
            grasper, execution_axis=_grip_axis_for(primary),
            commitment=Commitment.COMMITTING,
        )
    return [BodyPartEvent(
        tick=tick, actor=v_name,
        part=BodyPartHigh.HEAD, side=Side.NONE,
        verb=verb,
        steer_direction=frozenset(union_dirs) if union_dirs else None,
        modifiers=mods, source="HEAD_AS_OUTPUT",
    )]


# ===========================================================================
# HELPERS
# ===========================================================================

def _set_edge_intent(
    edge: "GripEdge", intent: GripIntent,
    steer: Optional[frozenset[SteerDirection]] = None,
) -> None:
    """Mirror a freshly-computed intent onto the edge so head-as-output
    state and the inspector can read the live value. Stored as strings to
    avoid a circular import between grip_graph and body_part_events."""
    edge.current_intent = intent.name
    if intent is GripIntent.STEER and steer:
        edge.steer_direction = frozenset(d.name for d in steer)
    else:
        edge.steer_direction = None


def _grip_axis_for(edge: "GripEdge") -> str:
    """SkillVector axis driving execution quality of work on this edge.
    HAJ-161 — both COLLAR sub-types share the lapel-grip skill axis (no
    separate "collar_grip" axis in v0.1; the SkillVector wraps both in
    one upper-torso-pull dimension)."""
    name = edge.grip_type_v2.name.upper()
    if "SLEEVE" in name:
        return "sleeve_grip"
    if "LAPEL" in name or "COLLAR" in name:
        return "lapel_grip"
    return "lapel_grip"


def _hikite_hand_from(template: "ThrowTemplate") -> str:
    """Return the sleeve-grip hand from a worked template — the canonical
    hikite. Falls back to 'left_hand' on right-dominant instances when no
    sleeve grip is required (rare; e.g. cross-grip variants)."""
    for g in template.force_grips:
        for gt in g.grip_type:
            if gt.name.startswith("SLEEVE"):
                return g.hand
    return "left_hand"


def _tsurite_from(
    template: "ThrowTemplate",
) -> tuple[Optional[str], Optional[BodyPartTarget]]:
    """The tsurite (lift hand) is the lapel/collar/belt grip if present.
    Returns (hand, collapsed-target) or (None, None)."""
    for g in template.force_grips:
        for gt in g.grip_type:
            if gt.name.startswith("LAPEL") or gt.name == "COLLAR":
                return g.hand, target_from_grip_type_v2(gt.name)
            if gt.name == "BELT":
                return g.hand, BodyPartTarget.BELT
    return None, None


def _posture_verb_for_kuzushi(direction: tuple[float, float]) -> BodyPartVerb:
    """Map kuzushi direction in uke's body frame onto a posture verb.
    Forward (+X) → BROKEN_FORWARD; backward (-X) → BROKEN_BACK; lateral
    dominant → BROKEN_SIDE; near-zero → BENT."""
    dx, dy = direction
    if abs(dx) < 0.2 and abs(dy) < 0.2:
        return BodyPartVerb.BENT
    if abs(dx) >= abs(dy):
        return BodyPartVerb.BROKEN_FORWARD if dx > 0 else BodyPartVerb.BROKEN_BACK
    return BodyPartVerb.BROKEN_SIDE
