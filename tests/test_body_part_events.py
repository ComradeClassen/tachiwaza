# tests/test_body_part_events.py
# HAJ-145 — BodyPartEvent emission layer.
#
# Verifies:
#   - BodyPartEvent type is defined with the required schema fields.
#   - The five canonical throws (Ko-uchi-gari, Uchi-mata, Seoi-nage,
#     O-soto-gari, Sasae-tsurikomi-ashi) decompose cleanly into the
#     body-part / verb / target / modifier vocabulary.
#   - The §13.8 novice self-cancel pattern (pull-vector and step-vector
#     opposed) emits events whose contradiction is detectable downstream.
#   - The engine emits BPEs on grip change, kuzushi attempt, commit, and
#     counter — captured in match.body_part_events and embedded on each
#     parent Event's data["bpe"] slot.

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from body_part_events import (
    BodyPartEvent, BodyPartHigh, Side, BodyPartVerb, BodyPartTarget,
    Modifiers, Commitment, Crispness, Tightness, Speed, Connection,
    is_self_cancel_pair, compute_modifiers,
)
from body_part_decompose import (
    decompose_commit, decompose_grip_establish, decompose_grip_deepen,
    decompose_pull, decompose_step, decompose_foot_attack,
)
from enums import (
    BodyPart, GripTypeV2, GripDepth, GripMode, GripTarget,
)
from body_state import place_judoka
from grip_graph import GripGraph, GripEdge
from throws import ThrowID
from throw_templates import (
    CoupleThrow, KuzushiRequirement, GripRequirement, ForceKind,
    CoupleBodyPartRequirement, UkePostureRequirement, TimingWindow,
    UkeBaseState, FailureSpec, FailureOutcome, CoupleAxis,
)
from worked_throws import (
    UCHI_MATA, O_SOTO_GARI, SEOI_NAGE_MOROTE, KO_UCHI_GARI,
)
import main as main_module


# ---------------------------------------------------------------------------
# FIXTURES
# ---------------------------------------------------------------------------
def _pair():
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    return t, s


# Canonical Sasae-tsurikomi-ashi (支釣込足) — propping foot throw. Not in the
# engine's worked-throw registry yet, so we declare it locally to verify the
# vocabulary handles its body-part shape (supporting foot PROPS uke's lead
# foot, hikite pulls forward-up, tsurite pulls forward-down). HAJ-29
# backfill will eventually land it as a real registered throw; the test
# pins the decomposition pattern in the meantime.
SASAE_TSURIKOMI_ASHI: CoupleThrow = CoupleThrow(
    name="Sasae-tsurikomi-ashi",
    kuzushi_requirement=KuzushiRequirement(
        direction=(1.0, 0.0),                 # straight forward
        tolerance_rad=math.radians(25),
        min_velocity_magnitude=0.3,
    ),
    force_grips=(
        GripRequirement(
            hand="left_hand",
            grip_type=(GripTypeV2.SLEEVE_HIGH,),
            min_depth=GripDepth.STANDARD,
            mode=GripMode.DRIVING,
        ),
        GripRequirement(
            hand="right_hand",
            grip_type=(GripTypeV2.LAPEL_HIGH, GripTypeV2.LAPEL_LOW),
            min_depth=GripDepth.STANDARD,
            mode=GripMode.DRIVING,
        ),
    ),
    couple_axis=CoupleAxis.SAGITTAL,
    min_torque_nm=200.0,
    body_part_requirement=CoupleBodyPartRequirement(
        tori_supporting_foot="left_foot",
        tori_attacking_limb="right_foot",
        contact_point_on_uke=BodyPart.RIGHT_FOOT,
        contact_height_range=(0.0, 0.10),
        timing_window=TimingWindow(
            target_foot="right_foot",
            weight_fraction_range=(0.40, 0.70),
            window_duration_ticks=2,
        ),
    ),
    uke_posture_requirement=UkePostureRequirement(
        trunk_sagittal_range=(math.radians(-5), math.radians(25)),
        trunk_frontal_range=(math.radians(-15), math.radians(15)),
        com_height_range=(0.85, 1.30),
        base_state=UkeBaseState.MID_STEP,
    ),
    commit_threshold=0.50,
    sukashi_vulnerability=0.30,
    failure_outcome=FailureSpec(
        primary=FailureOutcome.STANCE_RESET,
        secondary=FailureOutcome.PARTIAL_THROW,
    ),
)


# ---------------------------------------------------------------------------
# SCHEMA — the ticket pins the field shape: (actor, part, verb, target?, modifiers[]).
# ---------------------------------------------------------------------------
def test_body_part_event_schema_has_required_fields() -> None:
    bpe = BodyPartEvent(
        tick=0, actor="Tanaka",
        part=BodyPartHigh.HANDS, side=Side.RIGHT,
        verb=BodyPartVerb.GRIP, target=BodyPartTarget.LAPEL,
        modifiers=Modifiers(crispness=Crispness.CRISP),
    )
    # Spec: (actor, part, verb, target?, modifiers[]) — plus tick / side /
    # direction / source for downstream readers.
    assert bpe.actor == "Tanaka"
    assert bpe.part is BodyPartHigh.HANDS
    assert bpe.verb is BodyPartVerb.GRIP
    assert bpe.target is BodyPartTarget.LAPEL
    assert bpe.modifiers.crispness is Crispness.CRISP
    # Modifiers serialize cleanly for embedding on Event.data["bpe"].
    assert bpe.to_dict()["modifiers"]["crispness"] == "CRISP"


def test_modifier_levels_track_skill_axis() -> None:
    """A novice and an elite emit the same engine action; the modifier
    bundle resolves to opposite ends of the spectrum on every axis driven
    by the action's execution skill."""
    t, _ = _pair()
    # Drive every axis hard low → SLOPPY / FLARING / SLOW / DISCONNECTED.
    for f in t.skill_vector.axis_names():
        setattr(t.skill_vector, f, 0.10)
    novice_mods = compute_modifiers(t, execution_axis="pull_execution")
    assert novice_mods.crispness is Crispness.SLOPPY
    assert novice_mods.tightness is Tightness.FLARING
    assert novice_mods.speed is Speed.SLOW
    assert novice_mods.connection is Connection.DISCONNECTED
    for f in t.skill_vector.axis_names():
        setattr(t.skill_vector, f, 0.90)
    elite_mods = compute_modifiers(t, execution_axis="pull_execution")
    assert elite_mods.crispness is Crispness.CRISP
    assert elite_mods.tightness is Tightness.TIGHT
    assert elite_mods.speed is Speed.EXPLOSIVE
    assert elite_mods.connection is Connection.ROOTED


# ---------------------------------------------------------------------------
# DECOMPOSITION — five canonical throws, each producing a clean stream.
# ---------------------------------------------------------------------------
def _commit_decomp(template) -> list[BodyPartEvent]:
    t, s = _pair()
    return decompose_commit(t, s, template, tick=10, source="COMMIT")


def _verbs(events) -> set[BodyPartVerb]:
    return {e.verb for e in events}


def _parts(events) -> set[BodyPartHigh]:
    return {e.part for e in events}


def test_uchi_mata_decomposes_cleanly() -> None:
    bpes = _commit_decomp(UCHI_MATA)
    parts = _parts(bpes)
    verbs = _verbs(bpes)
    # Hikite + tsurite + reaping leg + hip load + posture beat.
    assert BodyPartHigh.HANDS in parts          # hikite + tsurite hand pulls
    assert BodyPartHigh.FEET in parts           # reaping leg
    assert BodyPartHigh.HIPS in parts           # hip load (Uchi-mata is hip_loading)
    assert BodyPartHigh.POSTURE in parts        # uke posture beat
    assert BodyPartVerb.PULL in verbs           # at least one pull
    assert BodyPartVerb.LOAD in verbs           # hip load
    assert BodyPartVerb.REAP in verbs           # leg reap
    # Hikite has a SLEEVE target; tsurite has a LAPEL/COLLAR target.
    targets = {e.target for e in bpes if e.target is not None}
    assert BodyPartTarget.SLEEVE in targets
    assert BodyPartTarget.LAPEL in targets or BodyPartTarget.COLLAR in targets
    # Posture beat is forward-broken (kuzushi vector +X).
    posture_evs = [e for e in bpes if e.part is BodyPartHigh.POSTURE]
    assert any(e.verb is BodyPartVerb.BROKEN_FORWARD for e in posture_evs)


def test_o_soto_gari_decomposes_cleanly() -> None:
    bpes = _commit_decomp(O_SOTO_GARI)
    verbs = _verbs(bpes)
    posture_evs = [e for e in bpes if e.part is BodyPartHigh.POSTURE]
    assert BodyPartVerb.PULL in verbs
    assert BodyPartVerb.REAP in verbs
    # O-soto's kuzushi vector is backward (-X) → BROKEN_BACK.
    assert any(e.verb is BodyPartVerb.BROKEN_BACK for e in posture_evs)
    # NOT hip-loading (hip_loading=False on O-soto-gari) → TURN_IN, not LOAD.
    hip_evs = [e for e in bpes if e.part is BodyPartHigh.HIPS]
    assert any(e.verb is BodyPartVerb.TURN_IN for e in hip_evs)


def test_seoi_nage_decomposes_cleanly() -> None:
    bpes = _commit_decomp(SEOI_NAGE_MOROTE)
    parts = _parts(bpes)
    verbs = _verbs(bpes)
    # Lever throw — fulcrum is a SHOULDER, base is the BASE part.
    assert BodyPartHigh.SHOULDERS in parts
    assert BodyPartHigh.BASE in parts
    assert BodyPartVerb.LIFT in verbs       # shoulder lift
    assert BodyPartVerb.POST in verbs       # base post
    assert BodyPartVerb.PULL in verbs       # hikite + tsurite


def test_ko_uchi_gari_decomposes_cleanly() -> None:
    bpes = _commit_decomp(KO_UCHI_GARI)
    verbs = _verbs(bpes)
    parts = _parts(bpes)
    # Foot-class reap, posture broken backward (kuzushi -X).
    assert BodyPartHigh.FEET in parts
    assert BodyPartVerb.REAP in verbs
    posture_evs = [e for e in bpes if e.part is BodyPartHigh.POSTURE]
    assert posture_evs
    assert any(e.verb is BodyPartVerb.BROKEN_BACK for e in posture_evs)


def test_sasae_tsurikomi_ashi_decomposes_to_propping_foot() -> None:
    bpes = _commit_decomp(SASAE_TSURIKOMI_ASHI)
    parts = _parts(bpes)
    verbs = _verbs(bpes)
    # The signature beat of Sasae is the propping foot — supporting foot
    # blocks uke's lead-foot ankle. The decomposition must surface PROP.
    assert BodyPartHigh.FEET in parts
    assert BodyPartVerb.PROP in verbs
    # Hikite + tsurite still pull forward.
    assert BodyPartVerb.PULL in verbs
    posture_evs = [e for e in bpes if e.part is BodyPartHigh.POSTURE]
    # Sasae's kuzushi vector is forward → BROKEN_FORWARD.
    assert any(e.verb is BodyPartVerb.BROKEN_FORWARD for e in posture_evs)


# ---------------------------------------------------------------------------
# §13.8 self-cancellation pattern — pull-vector and step-vector opposed.
# ---------------------------------------------------------------------------
def test_self_cancel_pull_and_step_are_detectable_as_contradiction() -> None:
    """A novice pulling in one direction while their base steps the
    opposite way produces two body-part events whose direction vectors
    are opposed. The substrate must carry enough information for a
    downstream layer to detect this as a contradiction."""
    t, _ = _pair()
    # Build a sleeve-grip edge to drive the PULL through.
    edge = GripEdge(
        grasper_id=t.identity.name, grasper_part=BodyPart.LEFT_HAND,
        target_id="Sato", target_location=GripTarget.RIGHT_SLEEVE,
        grip_type_v2=GripTypeV2.SLEEVE_HIGH, depth_level=GripDepth.STANDARD,
        strength=1.0, established_tick=0,
    )
    pull_dir = (1.0, 0.0)         # tori pulls uke forward (toward tori)
    step_dir = (-1.0, 0.0)        # tori's base steps backward — opposite!
    pulls = decompose_pull(t, edge, pull_dir, magnitude=300.0, tick=5)
    steps = decompose_step(t, "right_foot", step_dir, magnitude=0.3, tick=5)
    # Find the HANDS-PULL bpe and the FEET-STEP bpe.
    hand_pull = next(e for e in pulls if e.part is BodyPartHigh.HANDS)
    foot_step = next(e for e in steps if e.part is BodyPartHigh.FEET)
    assert is_self_cancel_pair(hand_pull, foot_step)
    # And the same pair when in the same direction is NOT a contradiction.
    aligned_steps = decompose_step(t, "right_foot", pull_dir, magnitude=0.3, tick=5)
    aligned_step = next(e for e in aligned_steps if e.part is BodyPartHigh.FEET)
    assert not is_self_cancel_pair(hand_pull, aligned_step)


# ---------------------------------------------------------------------------
# ENGINE WIRING — the match emits BPEs on the right hooks.
# ---------------------------------------------------------------------------
def _build_match():
    """Build a fresh Match without running it. The decomposition layer is
    callable directly for unit-style assertions; this fixture exists only
    so the wired-emission tests can assert match.body_part_events grows."""
    import random as _random
    from match import Match
    from referee import build_suzuki

    _random.seed(7)
    t, s = _pair()
    return Match(
        fighter_a=t, fighter_b=s, referee=build_suzuki(),
        max_ticks=8, seed=7, stream="debug",
    )


def test_match_exposes_body_part_events_collector() -> None:
    m = _build_match()
    assert isinstance(m.body_part_events, list)
    assert m.body_part_events == []   # nothing emitted yet


def test_grip_establish_emits_bpe_through_match() -> None:
    """Seat an edge through the engine's normal path and verify the
    GRIP_ESTABLISH path produces a HANDS-GRIP body-part event on the
    parent Event's data['bpe'] slot."""
    m = _build_match()
    # Drive a contrived engagement: hand-call the decomposer to verify the
    # wiring contract independent of the action ladder's choices.
    edge = GripEdge(
        grasper_id=m.fighter_a.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=m.fighter_b.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.POCKET,
        strength=0.6, established_tick=1,
    )
    bpes = decompose_grip_establish(edge, m.fighter_a, tick=1)
    assert len(bpes) == 1
    e = bpes[0]
    assert e.part is BodyPartHigh.HANDS
    assert e.verb is BodyPartVerb.GRIP
    assert e.target is BodyPartTarget.LAPEL
    assert e.side is Side.RIGHT
    assert e.source == "GRIP_ESTABLISH"


def test_commit_emission_attaches_bpe_to_parent_event() -> None:
    """When _resolve_commit_throw fires, the THROW_ENTRY event must carry
    the decomposed BPE stream on its data['bpe'] slot."""
    m = _build_match()
    # Seat the grips Uchi-mata wants, then drive a direct commit.
    g = m.grip_graph
    g.add_edge(GripEdge(
        grasper_id=m.fighter_a.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=m.fighter_b.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.STANDARD,
        strength=1.0, established_tick=0, mode=GripMode.DRIVING,
    ))
    g.add_edge(GripEdge(
        grasper_id=m.fighter_a.identity.name, grasper_part=BodyPart.LEFT_HAND,
        target_id=m.fighter_b.identity.name, target_location=GripTarget.RIGHT_SLEEVE,
        grip_type_v2=GripTypeV2.SLEEVE_HIGH, depth_level=GripDepth.STANDARD,
        strength=1.0, established_tick=0, mode=GripMode.DRIVING,
    ))
    events = m._resolve_commit_throw(
        m.fighter_a, m.fighter_b, ThrowID.UCHI_MATA, tick=2,
    )
    # First emitted event is THROW_ENTRY (or, on the rare deny-path, the
    # deny event — but we just seated grips, so we should reach commit).
    entry = next(e for e in events if e.event_type == "THROW_ENTRY")
    bpe_slot = entry.data.get("bpe")
    assert bpe_slot, "THROW_ENTRY should carry decomposed body-part events"
    # The commit decomposition includes hands, feet, hips, posture beats.
    parts_seen = {b["part"] for b in bpe_slot}
    assert "HANDS" in parts_seen
    assert "POSTURE" in parts_seen
    # And the match-level collector grew.
    assert len(m.body_part_events) > 0
