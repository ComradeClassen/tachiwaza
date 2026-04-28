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
    compute_modifiers, side_for_hand, side_for_foot, side_for_body_part,
    target_from_grip_target, target_from_grip_type_v2,
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
    mods = compute_modifiers(
        attacker, execution_axis=_grip_axis_for(edge),
        commitment=Commitment.COMMITTING,
    )
    target = (
        target_from_grip_target(edge.target_location.value)
        or target_from_grip_type_v2(edge.grip_type_v2.name)
    )
    return [BodyPartEvent(
        tick=tick, actor=attacker.identity.name,
        part=BodyPartHigh.HANDS,
        side=side_for_body_part(edge.grasper_part.value),
        verb=BodyPartVerb.GRIP, target=target,
        modifiers=mods, source="GRIP_ESTABLISH",
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
    mods = compute_modifiers(
        attacker, execution_axis=_grip_axis_for(edge),
        commitment=Commitment.COMMITTING,
    )
    target = (
        target_from_grip_target(edge.target_location.value)
        or target_from_grip_type_v2(edge.grip_type_v2.name)
    )
    return [BodyPartEvent(
        tick=tick, actor=attacker.identity.name,
        part=BodyPartHigh.HANDS,
        side=side_for_body_part(edge.grasper_part.value),
        verb=BodyPartVerb.PULL, target=target,
        modifiers=mods, source="GRIP_DEEPEN",
    )]


def decompose_grip_strip(
    stripper: "Judoka", target_edge: "GripEdge", tick: int,
    succeeded: bool,
) -> list[BodyPartEvent]:
    """Stripping pressure was applied to an opponent's edge. The narrative
    beat is the stripper's hand *breaking* (succeeded) or *snapping*
    (still alive) the opponent's grip."""
    mods = compute_modifiers(
        stripper, execution_axis="stripping",
        commitment=Commitment.COMMITTING,
    )
    verb = BodyPartVerb.BREAK if succeeded else BodyPartVerb.SNAP
    target = (
        target_from_grip_target(target_edge.target_location.value)
        or target_from_grip_type_v2(target_edge.grip_type_v2.name)
    )
    return [BodyPartEvent(
        tick=tick, actor=stripper.identity.name,
        part=BodyPartHigh.HANDS, side=Side.NONE,
        verb=verb, target=target,
        modifiers=mods, source="GRIP_STRIP",
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
    return [BodyPartEvent(
        tick=tick, actor=attacker.identity.name,
        part=BodyPartHigh.HANDS, side=side_for_hand(hand),
        verb=BodyPartVerb.REACH, target=target,
        modifiers=mods, source="REACH",
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
    return [
        BodyPartEvent(
            tick=tick, actor=attacker.identity.name,
            part=BodyPartHigh.HANDS, side=side,
            verb=BodyPartVerb.PULL, target=target,
            direction=(direction[0], direction[1]),
            modifiers=mods, source="PULL",
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
    # Hikite hand is the sleeve-grip hand on the canonical worked-throws
    # (left_hand on the right-dominant instances). Read it off the first
    # SLEEVE force-grip; fall back to LEFT if absent.
    hikite_hand = _hikite_hand_from(template)
    events.append(BodyPartEvent(
        tick=tick, actor=a_name,
        part=BodyPartHigh.HANDS, side=side_for_hand(hikite_hand),
        verb=BodyPartVerb.PULL, target=BodyPartTarget.SLEEVE,
        direction=kuzushi_dir, modifiers=pull_mods, source=source,
    ))

    # 2. Tsurite (lapel/collar/belt hand) — the second pulling/lifting hand.
    tsurite_hand, tsurite_target = _tsurite_from(template)
    if tsurite_hand is not None:
        events.append(BodyPartEvent(
            tick=tick, actor=a_name,
            part=BodyPartHigh.HANDS, side=side_for_hand(tsurite_hand),
            verb=BodyPartVerb.PULL, target=tsurite_target,
            direction=kuzushi_dir,
            modifiers=pull_mods, source=source,
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
# HELPERS
# ===========================================================================

def _grip_axis_for(edge: "GripEdge") -> str:
    """SkillVector axis driving execution quality of work on this edge."""
    name = edge.grip_type_v2.name.upper()
    if "SLEEVE" in name:
        return "sleeve_grip"
    if "LAPEL" in name or name in ("COLLAR",):
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
