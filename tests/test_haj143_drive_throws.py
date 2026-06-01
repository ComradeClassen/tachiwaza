# tests/test_haj143_drive_throws.py
# HAJ-143 — execution_ticks and drive_distance per throw template.
#
# Acceptance criteria (per the ticket):
#   AC#1 — Substrate updated: physics-substrate Part 5 §5.0 carries the
#          execution_ticks / drive_distance attribute table; worked-throw
#          templates carry the seed values.
#   AC#2 — Engine state extended: _ThrowInProgress carries
#          execution_ticks and drive_vector. (HAJ-127 OOB grace continues
#          to read any_throw_in_flight off the dict.)
#   AC#3 — Multi-tick resolution path: a drive throw with execution_ticks
#          > 1 consumes the specified ticks between commit and resolution,
#          per-tick COM displacement applied to uke.
#   AC#4 — Snap throws unchanged: throws with execution_ticks=1 resolve
#          identically to current behaviour.
#   AC#5 — Boundary interaction: multi-tick drive throws do not fire OOB
#          Matte mid-execution; if the drive ended OOB the score resolves
#          first and OOB fires post-resolution.
#   AC#6 — Three regression tests minimum (this file).
#   AC#7 — In-progress prose hook renders exactly once per multi-tick
#          throw between commit and resolution.

from __future__ import annotations
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from enums import (
    BeltRank, BodyPart, GripTypeV2, GripDepth, GripMode, GripTarget,
    Position, MatteReason,
)
from body_state import place_judoka
from grip_graph import GripGraph, GripEdge
from match import Match, MAT_HALF_WIDTH, is_out_of_bounds
from referee import build_suzuki
from throws import ThrowID
from throw_templates import CoupleThrow, LeverThrow
from worked_throws import (
    WORKED_THROWS,
    UCHI_MATA, O_SOTO_GARI, SEOI_NAGE_MOROTE,
    KO_UCHI_GARI, O_UCHI_GARI, TOMOE_NAGE,
    execution_ticks_for, drive_distance_for,
)
import main as main_module
import match as match_module


# ---------------------------------------------------------------------------
# FIXTURES
# ---------------------------------------------------------------------------
def _pair():
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    return t, s


def _seat_deep_grips(graph: GripGraph, attacker, defender) -> None:
    graph.add_edge(GripEdge(
        grasper_id=attacker.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=defender.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.DEEP,
        strength=1.0, established_tick=0, mode=GripMode.DRIVING,
    ))
    graph.add_edge(GripEdge(
        grasper_id=attacker.identity.name, grasper_part=BodyPart.LEFT_HAND,
        target_id=defender.identity.name, target_location=GripTarget.RIGHT_SLEEVE,
        grip_type_v2=GripTypeV2.SLEEVE_HIGH, depth_level=GripDepth.DEEP,
        strength=1.0, established_tick=0, mode=GripMode.DRIVING,
    ))


def _elite_match(seed: int = 0):
    """Both fighters elite (N=1) with grips already seated, ready for
    direct commit-resolution. Bypasses the engagement-distance gate
    because we drive _resolve_commit_throw directly."""
    random.seed(seed)
    t, s = _pair()
    t.identity.belt_rank = BeltRank.BLACK_5
    s.identity.belt_rank = BeltRank.BLACK_5
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki(), seed=seed)
    m.position = Position.GRIPPING
    _seat_deep_grips(m.grip_graph, t, s)
    _seat_deep_grips(m.grip_graph, s, t)
    return t, s, m


# ===========================================================================
# AC#1 — substrate seed values land on the worked-throw templates
# ===========================================================================
def test_snap_throws_default_to_execution_ticks_one() -> None:
    """Snap-class throws (HAJ-143 §5.0) default to execution_ticks=1 and
    drive_distance=0.0 — no behavioural drift for the canonical four
    worked throws."""
    for throw in (UCHI_MATA, O_SOTO_GARI, SEOI_NAGE_MOROTE):
        assert throw.execution_ticks == 1, (
            f"{throw.name} should be snap (execution_ticks=1)"
        )
        assert throw.drive_distance == 0.0, (
            f"{throw.name} should be snap (drive_distance=0.0)"
        )


def test_drive_class_throws_carry_seed_values() -> None:
    """Drive-class throws (o-uchi, ko-uchi, tomoe) carry the §5.0 seed
    values: execution_ticks 2..3, drive_distance 1.0..2.5 m."""
    assert O_UCHI_GARI.execution_ticks == 3
    assert O_UCHI_GARI.drive_distance == 2.0
    assert KO_UCHI_GARI.execution_ticks == 2
    assert KO_UCHI_GARI.drive_distance == 1.0
    # Tomoe-nage rides on its sacrifice fulcrum; modeled as exec_ticks=2
    # with a rotational carry.
    assert TOMOE_NAGE.execution_ticks == 2
    assert TOMOE_NAGE.drive_distance > 0.0


def test_lookup_helpers_round_trip_worked_templates() -> None:
    """The duration/drive lookups round-trip each worked template's values.
    B-3a — SUMI_GAESHI migrated to a worked template (execution_ticks 1→2,
    drive_distance 0.0→1.1), so it now reports its template values rather than
    the legacy snap defaults. With every v0.1 throw templated, the 1-tick /
    0.0 default path is dormant (no live ThrowID is template-less)."""
    assert execution_ticks_for(ThrowID.SUMI_GAESHI) == 2
    assert drive_distance_for(ThrowID.SUMI_GAESHI) == 1.1
    # Worked-throw lookups round-trip the template values.
    assert execution_ticks_for(ThrowID.O_UCHI_GARI) == 3
    assert drive_distance_for(ThrowID.O_UCHI_GARI) == 2.0


# ===========================================================================
# AC#4 — snap throws unchanged
# AC#6 — regression test #1: snap-throw 1-tick resolution
# ===========================================================================
def test_snap_throw_resolves_on_baseline_tick_with_no_drive_displacement() -> None:
    """Snap throw (uchi-mata, exec_ticks=1) — the resolution timing and
    uke COM stay on the pre-HAJ-143 path. The drive vector is (0, 0);
    no THROW_DRIVE event fires; the RESOLVE_KAKE_N1 consequence is
    queued for the unchanged T+3 tick (per HAJ-157 V1/V5 spread)."""
    t, s, m = _elite_match(seed=1)
    real = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: ("WAZA_ARI", 4.0)
    real_sig = match_module.actual_signature_match
    match_module.actual_signature_match = lambda *a, **kw: 1.0
    pre_uke_com = s.state.body_state.com_position
    collected: list = []
    try:
        T = 5
        collected.extend(m._resolve_commit_throw(t, s, ThrowID.UCHI_MATA, tick=T))
        # Tip carries no drive state.
        tip = m._throws_in_progress[t.identity.name]
        assert tip.execution_ticks == 1
        assert tip.drive_vector == (0.0, 0.0)
        # Walk the schedule and resolve at the baseline T+3 tick.
        collected.extend(m._advance_throws_in_progress(tick=T + 1))
        collected.extend(m._advance_throws_in_progress(tick=T + 2))
        m._resolve_consequences(tick=T + 3, events=collected)
    finally:
        match_module.resolve_throw = real
        match_module.actual_signature_match = real_sig

    # No drive prose for snap throws.
    drives = [e for e in collected if e.event_type == "THROW_DRIVE"]
    assert len(drives) == 0, "snap throws must not emit THROW_DRIVE"
    # Uke's CoM is unmoved by the drive system itself (other engine
    # systems may move it via force application; the drive system
    # contributes zero for snap).
    assert s.state.body_state.com_position == pre_uke_com
    # Score lands on T+3 — pre-HAJ-143 baseline.
    score = next(
        e for e in collected
        if e.event_type in ("WAZA_ARI_AWARDED", "IPPON_AWARDED")
    )
    assert score.tick == T + 3


# ===========================================================================
# AC#3 + AC#7 — drive-throw multi-tick resolution + once-per-throw prose
# AC#6 — regression test #2: drive throw observable across N ticks
# ===========================================================================
def test_drive_throw_extends_resolution_and_walks_uke_com() -> None:
    """O-uchi-gari (exec_ticks=3, drive_distance=2.0 m). Resolution is
    pushed out from the snap-throw T+3 baseline to T+5; per-tick COM
    displacement is applied to uke; THROW_DRIVE prose fires exactly once."""
    t, s, m = _elite_match(seed=2)
    real = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: ("WAZA_ARI", 4.0)
    real_sig = match_module.actual_signature_match
    match_module.actual_signature_match = lambda *a, **kw: 1.0
    pre_uke = s.state.body_state.com_position
    collected: list = []
    try:
        T = 5
        collected.extend(m._resolve_commit_throw(t, s, ThrowID.O_UCHI_GARI, tick=T))
        tip = m._throws_in_progress[t.identity.name]
        # AC#2 — engine state extended: tip carries execution_ticks +
        # drive_vector. The drive vector points attacker→defender (T at
        # x=-0.5, S at x=+0.5 → +x direction) and has magnitude
        # drive_distance.
        assert tip.execution_ticks == 3
        dvx, dvy = tip.drive_vector
        assert abs((dvx ** 2 + dvy ** 2) ** 0.5 - 2.0) < 1e-6
        assert dvx > 0  # Sato lies on the +x side of Tanaka.
        # Walk the schedule.
        # T+1: TS sub-event.
        collected.extend(m._advance_throws_in_progress(tick=T + 1))
        # T+2: KC fires; first drive step applies (drive_ticks_consumed=1).
        collected.extend(m._advance_throws_in_progress(tick=T + 2))
        # T+3: drive step #2 (consumed=2). Pre-HAJ-143 baseline resolution
        # tick — under HAJ-143 the consequence is now queued for T+5.
        collected.extend(m._advance_throws_in_progress(tick=T + 3))
        # T+4: drive step #3 — would-be no-op (consumed=3, capped at
        # exec_ticks). _advance_throws_in_progress handles the cap.
        collected.extend(m._advance_throws_in_progress(tick=T + 4))
        # T+5: RESOLVE_KAKE_N1 consequence fires; tip is popped.
        m._resolve_consequences(tick=T + 5, events=collected)
    finally:
        match_module.resolve_throw = real
        match_module.actual_signature_match = real_sig

    # AC#7 — exactly one drive prose event between commit and resolution.
    drives = [e for e in collected if e.event_type == "THROW_DRIVE"]
    assert len(drives) == 1, (
        f"expected exactly 1 THROW_DRIVE event; got {len(drives)}"
    )
    assert drives[0].data["execution_ticks"] == 3

    # AC#3 — score lands on T+5 (drive resolution), not T+3 (snap baseline).
    score = next(
        e for e in collected
        if e.event_type in ("WAZA_ARI_AWARDED", "IPPON_AWARDED")
    )
    assert score.tick == T + 5

    # AC#3 — uke's CoM walked along the drive vector during the window.
    # Other engine systems also nudge CoM during force application; the
    # drive contribution alone is drive_distance ≈ 2 m. We assert at least
    # the drive component lands by checking the +x walk past the original
    # (Sato started at x=+0.5).
    final_x, _ = s.state.body_state.com_position
    assert final_x > pre_uke[0] + 1.5, (
        f"expected uke to walk forward at least 1.5 m by the drive; "
        f"started x={pre_uke[0]:.2f}, ended x={final_x:.2f}"
    )


def test_drive_does_not_apply_per_tick_during_window() -> None:
    """Post P1 regression fix: COM displacement no longer applies per-tick
    during the in-flight drive window. _apply_drive_step ticks the
    consumed counter and emits prose, but uke's CoM stays put until the
    resolution tick (where _resolve_kake applies the full drive_vector
    *only* on a successful outcome). Pre-fix this teleported uke 0.5+ m
    per tick and walked failed throws across the contest area."""
    t, s, m = _elite_match(seed=3)
    real_sig = match_module.actual_signature_match
    match_module.actual_signature_match = lambda *a, **kw: 1.0
    try:
        T = 5
        m._resolve_commit_throw(t, s, ThrowID.KO_UCHI_GARI, tick=T)
        tip = m._throws_in_progress[t.identity.name]
        assert tip.execution_ticks == 2
        m._advance_throws_in_progress(tick=T + 1)
        # Snapshot uke x just before KC.
        pre_kc_x = s.state.body_state.com_position[0]
        m._advance_throws_in_progress(tick=T + 2)
        post_kc_x = s.state.body_state.com_position[0]
        # The drive system contributes zero on the KC tick — it's all
        # deferred to resolution. Other engine systems may still nudge
        # CoM, but the drive component itself doesn't apply yet.
        # Confirm the in-progress accounting still ticks the counter and
        # the prose has fired.
        assert tip.drive_ticks_consumed >= 1
        assert tip.drive_prose_emitted is True
        # The displacement budget for the drive (1.0 m on ko-uchi) has
        # not landed on uke during the in-flight window.
        assert post_kc_x - pre_kc_x < 1.0
    finally:
        match_module.actual_signature_match = real_sig


def test_drive_displacement_lands_only_on_successful_outcome() -> None:
    """The Priority-1 regression fix: a *failed* drive throw applies zero
    drive displacement. Pre-fix a failed o-uchi-gari teleported uke 2 m
    forward — visible in the playthrough as GRIPPING-state fighters
    drifting 3 m apart."""
    t, s, m = _elite_match(seed=4)
    real = match_module.resolve_throw
    real_sig = match_module.actual_signature_match
    # Force the throw to fail outright. Uke must NOT be displaced.
    match_module.resolve_throw = lambda *a, **kw: ("FAILED", -3.0)
    match_module.actual_signature_match = lambda *a, **kw: 1.0
    pre_uke = s.state.body_state.com_position
    try:
        T = 5
        m._resolve_commit_throw(t, s, ThrowID.O_UCHI_GARI, tick=T)
        for offset in range(1, 5):
            m._advance_throws_in_progress(tick=T + offset)
        m._resolve_consequences(tick=T + 5, events=[])
    finally:
        match_module.resolve_throw = real
        match_module.actual_signature_match = real_sig
    # Drive contribution is zero on FAILED. Other engine systems may
    # nudge uke a small amount during the window; the assertion is that
    # the o-uchi 2 m drive vector did NOT land.
    final_x, final_y = s.state.body_state.com_position
    drift = ((final_x - pre_uke[0]) ** 2 + (final_y - pre_uke[1]) ** 2) ** 0.5
    assert drift < 1.0, (
        f"failed drive throw displaced uke by {drift:.2f} m — drive must "
        f"only apply on landed outcomes"
    )


# ===========================================================================
# AC#5 — boundary interaction
# AC#6 — regression test #3: drive carries uke OOB; score before Matte
# ===========================================================================
def test_drive_into_oob_resolves_score_before_oob_matte() -> None:
    """Throw initiated inside, drive carries uke past the boundary.
    HAJ-127 in-flight grace must hold: no OOB Matte while the drive is
    in progress. The score resolves on the drive's final tick; OOB
    Matte is then eligible to fire on a subsequent tick once the tip
    is cleared from _throws_in_progress."""
    t, s, m = _elite_match(seed=4)
    real = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: ("WAZA_ARI", 4.0)
    real_sig = match_module.actual_signature_match
    match_module.actual_signature_match = lambda *a, **kw: 1.0
    # Position uke close to the +x boundary so the +x drive (attacker
    # at x=-0.5, defender at x≈MAT_HALF_WIDTH-0.3) walks them outside.
    place_judoka(s, com_position=(MAT_HALF_WIDTH - 0.3, 0.0),
                  facing=(-1.0, 0.0))
    collected: list = []
    try:
        T = 5
        collected.extend(m._resolve_commit_throw(t, s, ThrowID.O_UCHI_GARI, tick=T))
        # Walk the full window. Post P1-fix the drive doesn't displace
        # uke per-tick — the full drive_vector lands at resolution. The
        # in-flight grace must still hold across the wait so OOB Matte
        # can't fire even if other engine systems edge uke close to the
        # line.
        for offset in range(1, 5):
            collected.extend(m._advance_throws_in_progress(tick=T + offset))
            state = m._build_match_state(tick=T + offset)
            assert state.any_throw_in_flight is True, (
                f"in-flight grace lost on tick T+{offset}"
            )
            reason = m.referee.should_call_matte(state, current_tick=T + offset)
            assert reason != MatteReason.OUT_OF_BOUNDS, (
                f"OOB Matte fired at T+{offset} despite throw in flight"
            )
        # Resolution on T+5: the WAZA_ARI lands AND the 2-m drive is
        # applied to uke as a one-shot displacement, walking uke past
        # the +x boundary. The score event lives on T+5 alongside the
        # drive landing.
        m._resolve_consequences(tick=T + 5, events=collected)
        score = next(
            e for e in collected
            if e.event_type in ("WAZA_ARI_AWARDED", "IPPON_AWARDED")
        )
        assert score.tick == T + 5
        # The drive really did carry uke across the line — applied on
        # the resolution tick *after* the score was awarded.
        assert is_out_of_bounds(s), (
            f"expected uke OOB after resolution-tick drive landing; "
            f"com={s.state.body_state.com_position}"
        )
        # Tip is cleared post-resolution; OOB Matte is now eligible.
        assert t.identity.name not in m._throws_in_progress
        post_state = m._build_match_state(tick=T + 6)
        assert post_state.any_throw_in_flight is False
        assert m.referee.should_call_matte(post_state, current_tick=T + 6) == (
            MatteReason.OUT_OF_BOUNDS
        )
    finally:
        match_module.resolve_throw = real
        match_module.actual_signature_match = real_sig


# ===========================================================================
# Defensive guards
# ===========================================================================
def test_drive_vector_zero_for_colocated_fighters_falls_back_to_facing() -> None:
    """Degenerate test setup where attacker and defender share a CoM:
    the drive system must still produce a usable direction (attacker's
    facing) so the throw doesn't NaN out."""
    t, s, m = _elite_match(seed=5)
    place_judoka(t, com_position=(0.0, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(0.0, 0.0), facing=(-1.0, 0.0))
    real_sig = match_module.actual_signature_match
    match_module.actual_signature_match = lambda *a, **kw: 1.0
    try:
        m._resolve_commit_throw(t, s, ThrowID.O_UCHI_GARI, tick=5)
        tip = m._throws_in_progress[t.identity.name]
        dvx, dvy = tip.drive_vector
        # Magnitude should equal drive_distance; direction = attacker
        # facing (+x).
        assert abs((dvx ** 2 + dvy ** 2) ** 0.5 - 2.0) < 1e-6
        assert dvx > 0
    finally:
        match_module.actual_signature_match = real_sig


def test_drive_step_consumed_counter_capped_at_execution_ticks() -> None:
    """_apply_drive_step is idempotent past execution_ticks — repeated
    calls don't bump the consumed counter beyond exec_ticks. Post P1
    fix this is a pure bookkeeping check (no per-tick displacement);
    ensures the prose-emitted guard and counter-cap logic stay in sync.
    """
    t, s, m = _elite_match(seed=6)
    real_sig = match_module.actual_signature_match
    match_module.actual_signature_match = lambda *a, **kw: 1.0
    try:
        m._resolve_commit_throw(t, s, ThrowID.KO_UCHI_GARI, tick=5)
        tip = m._throws_in_progress[t.identity.name]
        # KO_UCHI_GARI: exec_ticks=2.
        snapshot = s.state.body_state.com_position
        m._apply_drive_step(tip, s, "Ko-uchi-gari", tick=10)
        m._apply_drive_step(tip, s, "Ko-uchi-gari", tick=10)
        assert tip.drive_ticks_consumed == 2
        # A third call doesn't bump the counter past exec_ticks.
        m._apply_drive_step(tip, s, "Ko-uchi-gari", tick=10)
        assert tip.drive_ticks_consumed == 2
        # Drive-step itself never moves uke now — that's deferred to
        # _resolve_kake on a successful resolution.
        assert s.state.body_state.com_position == snapshot
    finally:
        match_module.actual_signature_match = real_sig


# ===========================================================================
# Entry point
# ===========================================================================
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
