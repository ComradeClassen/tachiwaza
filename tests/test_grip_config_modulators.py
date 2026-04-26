# tests/test_grip_config_modulators.py
# Verifies physics-substrate Parts 4.3 / 4.4 force-application modulators:
#
#   - Lever throw with `requires_dominant_hand_grip=True` and tori's
#     dominant hand in FREE ContactState produces lower execution_quality
#     than the same throw with the dominant hand in GRIPPING_UKE on a
#     required grip type.
#   - Couple throw against an uke with zero grips in GRIPPING_UKE state
#     (zero edges owned by uke) produces higher execution_quality than the
#     same throw against a gripped uke.
#   - Both modulators are flagged as calibration targets — the asserts here
#     test monotonicity and non-zero magnitude, not exact numerics.

from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from body_state import ContactState, place_judoka
from enums import (
    BodyPart, GripTypeV2, GripDepth, GripMode, GripTarget, DominantSide,
)
from execution_quality import compute_execution_quality
from grip_graph import GripGraph, GripEdge
from throw_signature import (
    match_force_application, signature_match,
    DOMINANT_HAND_FREE_LEVER_PENALTY, UKE_UNGRIPPED_COUPLE_BONUS,
)
from worked_throws import SEOI_NAGE_MOROTE, O_SOTO_GARI
import main as main_module


# ---------------------------------------------------------------------------
# FIXTURES
# ---------------------------------------------------------------------------
def _pair():
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.25, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.25, 0.0), facing=(-1.0, 0.0))
    return t, s


def _seat_tori_deep_grips(graph: GripGraph, tori, uke) -> None:
    """Seat tsurite (right-hand → uke's left lapel) + hikite (left-hand →
    uke's right sleeve). Both DEEP + DRIVING. Also updates tori's
    body-part ContactState to GRIPPING_UKE on both hands."""
    graph.add_edge(GripEdge(
        grasper_id=tori.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=uke.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.DEEP,
        strength=1.0, established_tick=0, mode=GripMode.DRIVING,
    ))
    graph.add_edge(GripEdge(
        grasper_id=tori.identity.name, grasper_part=BodyPart.LEFT_HAND,
        target_id=uke.identity.name, target_location=GripTarget.RIGHT_SLEEVE,
        grip_type_v2=GripTypeV2.SLEEVE_HIGH, depth_level=GripDepth.DEEP,
        strength=1.0, established_tick=0, mode=GripMode.DRIVING,
    ))
    tori.state.body["right_hand"].contact_state = ContactState.GRIPPING_UKE
    tori.state.body["left_hand"].contact_state  = ContactState.GRIPPING_UKE


def _seat_tori_standard_grips_fatigued(
    graph: GripGraph, tori, uke,
) -> None:
    """Seat STANDARD-depth tsurite + hikite with moderate hand fatigue so
    the base force-application score sits well below 1.0 — this keeps the
    Couple "uke-ungripped" +0.3 bonus visible instead of being erased by
    the upper clamp.
    """
    graph.add_edge(GripEdge(
        grasper_id=tori.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=uke.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.STANDARD,
        strength=0.9, established_tick=0, mode=GripMode.DRIVING,
    ))
    graph.add_edge(GripEdge(
        grasper_id=tori.identity.name, grasper_part=BodyPart.LEFT_HAND,
        target_id=uke.identity.name, target_location=GripTarget.RIGHT_SLEEVE,
        grip_type_v2=GripTypeV2.SLEEVE_HIGH, depth_level=GripDepth.STANDARD,
        strength=0.9, established_tick=0, mode=GripMode.DRIVING,
    ))
    tori.state.body["right_hand"].contact_state = ContactState.GRIPPING_UKE
    tori.state.body["left_hand"].contact_state  = ContactState.GRIPPING_UKE
    tori.state.body["right_hand"].fatigue = 0.5
    tori.state.body["left_hand"].fatigue = 0.5


def _seat_uke_counter_grips(graph: GripGraph, tori, uke) -> None:
    """Seat uke-owned mirror grips so the ungripped-uke predicate is false."""
    graph.add_edge(GripEdge(
        grasper_id=uke.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=tori.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.STANDARD,
        strength=0.9, established_tick=0, mode=GripMode.DRIVING,
    ))
    graph.add_edge(GripEdge(
        grasper_id=uke.identity.name, grasper_part=BodyPart.LEFT_HAND,
        target_id=tori.identity.name, target_location=GripTarget.RIGHT_SLEEVE,
        grip_type_v2=GripTypeV2.SLEEVE_HIGH, depth_level=GripDepth.STANDARD,
        strength=0.9, established_tick=0, mode=GripMode.DRIVING,
    ))
    uke.state.body["right_hand"].contact_state = ContactState.GRIPPING_UKE
    uke.state.body["left_hand"].contact_state  = ContactState.GRIPPING_UKE


def _set_seoi_scene(graph: GripGraph, tori, uke) -> None:
    """Drop tori's CoM below uke's to satisfy the Seoi fulcrum offset, and
    set uke CoM displacement + velocity so kuzushi/posture dims score.
    """
    tori.state.body_state.com_height = uke.state.body_state.com_height - 0.20
    # Uke past the recoverable envelope forward (mat-frame +X). Uke's facing
    # is (-1, 0), so mat-frame forward motion (+X) maps to -X in uke's body
    # frame, i.e. backward — not what we want. Flip sign: uke velocity in
    # mat-frame -X direction = +X in uke frame = forward kuzushi.
    uke.state.body_state.com_position = (0.50, 0.0)
    uke.state.body_state.com_velocity = (-0.6, 0.0)


# ---------------------------------------------------------------------------
# LEVER — dominant-hand FREE vs GRIPPING_UKE
# ---------------------------------------------------------------------------
def test_seoi_marks_requires_dominant_hand_grip() -> None:
    """Sanity: the worked Seoi-nage template carries the flag."""
    assert SEOI_NAGE_MOROTE.requires_dominant_hand_grip is True


def test_lever_dominant_hand_free_reduces_force_score() -> None:
    """Same Seoi setup, same grip edges — but in one case tori's right hand
    (dominant) is not GRIPPING_UKE. The force-dim score should drop by the
    calibration penalty, clamped to [0, 1]."""
    t, s = _pair()
    g_engaged = GripGraph()
    _seat_tori_deep_grips(g_engaged, t, s)
    f_engaged = match_force_application(SEOI_NAGE_MOROTE, t, s, g_engaged)

    # Now build the FREE-dominant scenario: same DEEP+DRIVING edges exist
    # (so base grip + force components are unchanged) BUT tori's dominant
    # right hand reports FREE in ContactState — e.g. the hand slipped off
    # this tick but the edge has not yet been torn down. This triggers
    # the modulator in isolation.
    t2, s2 = _pair()
    g_free = GripGraph()
    _seat_tori_deep_grips(g_free, t2, s2)
    t2.state.body["right_hand"].contact_state = ContactState.FREE
    f_free = match_force_application(SEOI_NAGE_MOROTE, t2, s2, g_free)

    assert f_free < f_engaged
    # Penalty magnitude should be roughly the configured constant
    # (bounded by the [0, 1] clamp on the engaged side).
    drop = f_engaged - f_free
    assert drop >= DOMINANT_HAND_FREE_LEVER_PENALTY - 1e-6


def test_lever_dominant_hand_free_reduces_execution_quality() -> None:
    """End-to-end: the FREE-dominant-hand scenario produces lower signature
    match and therefore lower execution_quality than the engaged scenario,
    with every other input held identical.
    """
    # Engaged case.
    t1, s1 = _pair()
    g1 = GripGraph()
    _seat_tori_deep_grips(g1, t1, s1)
    _set_seoi_scene(g1, t1, s1)
    sig_engaged = signature_match(SEOI_NAGE_MOROTE, t1, s1, g1)
    eq_engaged = compute_execution_quality(
        sig_engaged, SEOI_NAGE_MOROTE.commit_threshold,
    )

    # FREE-dominant case — everything else identical.
    t2, s2 = _pair()
    g2 = GripGraph()
    _seat_tori_deep_grips(g2, t2, s2)
    _set_seoi_scene(g2, t2, s2)
    t2.state.body["right_hand"].contact_state = ContactState.FREE
    sig_free = signature_match(SEOI_NAGE_MOROTE, t2, s2, g2)
    eq_free = compute_execution_quality(
        sig_free, SEOI_NAGE_MOROTE.commit_threshold,
    )

    assert sig_free < sig_engaged
    assert eq_free < eq_engaged


def test_tomoe_nage_without_flag_unaffected_by_free_dominant_hand() -> None:
    """Sacrifice Lever (Tomoe-nage) defaults to
    `requires_dominant_hand_grip=False` — the modulator must not fire,
    so FREE vs GRIPPING_UKE produces identical force-dim scores.
    """
    from worked_throws import TOMOE_NAGE
    assert TOMOE_NAGE.requires_dominant_hand_grip is False

    t1, s1 = _pair()
    g1 = GripGraph()
    _seat_tori_deep_grips(g1, t1, s1)
    f_engaged = match_force_application(TOMOE_NAGE, t1, s1, g1)

    t2, s2 = _pair()
    g2 = GripGraph()
    _seat_tori_deep_grips(g2, t2, s2)
    t2.state.body["right_hand"].contact_state = ContactState.FREE
    f_free = match_force_application(TOMOE_NAGE, t2, s2, g2)

    assert f_engaged == f_free


# ---------------------------------------------------------------------------
# COUPLE — uke gripped vs ungripped
# ---------------------------------------------------------------------------
def test_couple_uke_ungripped_raises_force_score() -> None:
    """O-soto-gari against an uke with zero grips gets a +bonus on the
    force-application dimension vs the same throw against a gripped uke.
    Uses STANDARD-depth grips with moderate hand fatigue so the base
    score sits under the upper clamp — otherwise the +0.3 bonus would
    be erased by the [0, 1] clamp at the top end.
    """
    t1, s1 = _pair()
    g_uke_gripped = GripGraph()
    _seat_tori_standard_grips_fatigued(g_uke_gripped, t1, s1)
    _seat_uke_counter_grips(g_uke_gripped, t1, s1)
    f_gripped = match_force_application(O_SOTO_GARI, t1, s1, g_uke_gripped)

    t2, s2 = _pair()
    g_uke_free = GripGraph()
    _seat_tori_standard_grips_fatigued(g_uke_free, t2, s2)
    # uke owns zero edges → ungripped-uke bonus triggers
    f_free = match_force_application(O_SOTO_GARI, t2, s2, g_uke_free)

    assert f_free > f_gripped
    rise = f_free - f_gripped
    # Bonus applies as an additive unless clamping kicks in; asserting the
    # delta is at least some meaningful fraction of the constant.
    assert rise >= min(UKE_UNGRIPPED_COUPLE_BONUS, 1.0 - f_gripped) - 1e-6


def test_couple_uke_ungripped_raises_execution_quality() -> None:
    """End-to-end: O-soto-gari at the same distance and posture but against
    an uke with no grips produces a higher signature (and therefore
    execution_quality) than the gripped-uke baseline.
    """
    # Gripped uke.
    t1, s1 = _pair()
    g1 = GripGraph()
    _seat_tori_standard_grips_fatigued(g1, t1, s1)
    _seat_uke_counter_grips(g1, t1, s1)
    s1.state.body_state.com_velocity = (0.4, 0.0)  # backward in uke frame
    sig_gripped = signature_match(O_SOTO_GARI, t1, s1, g1)
    eq_gripped = compute_execution_quality(
        sig_gripped, O_SOTO_GARI.commit_threshold,
    )

    # Ungripped uke.
    t2, s2 = _pair()
    g2 = GripGraph()
    _seat_tori_standard_grips_fatigued(g2, t2, s2)
    s2.state.body_state.com_velocity = (0.4, 0.0)
    sig_free = signature_match(O_SOTO_GARI, t2, s2, g2)
    eq_free = compute_execution_quality(
        sig_free, O_SOTO_GARI.commit_threshold,
    )

    assert sig_free > sig_gripped
    assert eq_free > eq_gripped


# ---------------------------------------------------------------------------
# Identity layer — dominant_side + tokui_waza
# ---------------------------------------------------------------------------
def test_identity_carries_dominant_side_and_tokui_waza() -> None:
    """Identity exposes dominant_side (pre-existing) and tokui_waza (added
    alongside it). Default tokui_waza is an empty list.
    """
    t = main_module.build_tanaka()
    assert t.identity.dominant_side in (DominantSide.LEFT, DominantSide.RIGHT)
    assert isinstance(t.identity.tokui_waza, list)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import traceback
    passed = 0
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                passed += 1
                print(f"PASS  {name}")
            except Exception:
                failed += 1
                print(f"FAIL  {name}")
                traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
