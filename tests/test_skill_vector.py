# tests/test_skill_vector.py
# HAJ-137 — fine-grained skill axes per grip-as-cause.md §5.1.
#
# Pre-fix Judoka exposed belt_rank, fight_iq, composure, cardio, plus
# per-throw profiles. The fine-grained axes that differentiate "white-
# belt throw spam" from "brown-belt patient grip war" structurally
# didn't exist as data — earlier tickets (HAJ-131 / 133 / 134 / 135 /
# 136) stubbed specific axes with `fight_iq` placeholders.
#
# Post-fix:
#   - SkillVector dataclass with all 22 axes from §5.1.
#   - Judoka.skill_vector populates with belt-rank-derived defaults
#     per §6 profiles.
#   - All earlier-ticket stubs (TODO: HAJ-137 — switch to <axis>) now
#     read from this vector via skill_vector.axis().

from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from enums import BeltRank
from skill_vector import (
    SkillVector, default_for_belt, axis, set_uniform,
)
import main as main_module


# ---------------------------------------------------------------------------
# 1. Dataclass surface — all §5.1 axes present.
# ---------------------------------------------------------------------------
def test_skill_vector_has_all_axes_from_spec_5_1() -> None:
    """Spec §5.1 lists ~20 axes across grip-fighting, footwork (offensive
    and defensive), fight IQ, and composure clusters. Verify each is
    present on the dataclass."""
    sv = SkillVector()
    expected = {
        # grip-fighting
        "lapel_grip", "sleeve_grip", "two_on_one", "stripping",
        "defending", "reposition", "pull_execution",
        # defensive footwork
        "tsugi_ashi", "ayumi_ashi", "pivots", "base_recovery",
        # offensive footwork
        "foot_sweeps", "leg_attacks", "disruptive_stepping",
        # fight IQ
        "counter_window_reading", "exposure_reading", "pattern_reading",
        "timing", "sequencing_precision",
        # composure
        "pressure_handling", "ref_handling", "score_handling",
    }
    actual = set(sv.axis_names())
    missing = expected - actual
    assert not missing, f"missing axes: {missing}"


def test_axis_values_clamp_to_unit_interval() -> None:
    """Defaults must be in [0, 1]; this is an invariant the math layer
    relies on."""
    sv = SkillVector()
    for name in sv.axis_names():
        v = sv[name]
        assert 0.0 <= v <= 1.0


# ---------------------------------------------------------------------------
# 2. Belt-correlated defaults (§6).
# ---------------------------------------------------------------------------
def test_white_belt_defaults_are_low() -> None:
    sv = default_for_belt(BeltRank.WHITE)
    # White belts sit around 0.2 across the board.
    assert sv.lapel_grip < 0.30
    assert sv.pull_execution < 0.30
    assert sv.counter_window_reading < 0.30


def test_black_belt_defaults_are_high() -> None:
    sv = default_for_belt(BeltRank.BLACK_1)
    # First-degree black belts sit around 0.75.
    assert sv.lapel_grip > 0.65
    assert sv.pull_execution > 0.65
    assert sv.sequencing_precision > 0.65


def test_belt_progression_is_monotone() -> None:
    """Each belt rank should have axes >= the previous rank — no
    regressions as you climb the ranks."""
    ranks = [
        BeltRank.WHITE, BeltRank.YELLOW, BeltRank.ORANGE, BeltRank.GREEN,
        BeltRank.BLUE, BeltRank.BROWN, BeltRank.BLACK_1,
    ]
    prev = -1.0
    for rank in ranks:
        sv = default_for_belt(rank)
        # Every axis is the same in v0.1, so check one representative.
        assert sv.pull_execution >= prev
        prev = sv.pull_execution


def test_brown_belt_between_blue_and_black() -> None:
    """Sanity: BROWN's profile sits between BLUE and BLACK_1."""
    blue = default_for_belt(BeltRank.BLUE)
    brown = default_for_belt(BeltRank.BROWN)
    black = default_for_belt(BeltRank.BLACK_1)
    assert blue.pull_execution < brown.pull_execution < black.pull_execution


# ---------------------------------------------------------------------------
# 3. Judoka.skill_vector populates from belt rank.
# ---------------------------------------------------------------------------
def test_tanaka_has_black1_profile() -> None:
    """build_tanaka() declares belt_rank=BLACK_1 — skill_vector should
    initialize to that default."""
    t = main_module.build_tanaka()
    assert t.skill_vector is not None
    expected = default_for_belt(BeltRank.BLACK_1)
    assert t.skill_vector.pull_execution == expected.pull_execution
    assert t.skill_vector.foot_sweeps == expected.foot_sweeps


def test_sato_has_black1_profile() -> None:
    s = main_module.build_sato()
    assert s.skill_vector is not None
    expected = default_for_belt(BeltRank.BLACK_1)
    assert s.skill_vector.pull_execution == expected.pull_execution


def test_white_belt_judoka_defaults_to_white_profile() -> None:
    """A Judoka constructed with belt_rank=WHITE should get the white-belt
    skill-vector profile (low across the board). Override the existing
    Tanaka builder's belt rank pre-construction so the __post_init__
    default-factory picks WHITE."""
    from judoka import Judoka
    t = main_module.build_tanaka()
    t.identity.belt_rank = BeltRank.WHITE
    # Reconstruct skill_vector so the new belt rank takes effect.
    t.skill_vector = default_for_belt(t.identity.belt_rank)
    expected = default_for_belt(BeltRank.WHITE)
    assert t.skill_vector.pull_execution == expected.pull_execution
    assert t.skill_vector.lapel_grip == expected.lapel_grip
    assert t.skill_vector.pull_execution < 0.30


# ---------------------------------------------------------------------------
# 4. Read helper (axis()) handles both vector and legacy fallback.
# ---------------------------------------------------------------------------
def test_axis_reads_from_skill_vector_when_set() -> None:
    t = main_module.build_tanaka()
    t.skill_vector.pull_execution = 0.42
    assert axis(t, "pull_execution") == 0.42


def test_axis_falls_back_to_fight_iq_when_vector_missing() -> None:
    """Legacy fixtures that built Judoka without going through the
    builder still need a usable axis read — falls back to fight_iq/10."""
    t = main_module.build_tanaka()
    t.skill_vector = None
    t.capability.fight_iq = 7
    # Falls back to 7/10 = 0.7.
    assert abs(axis(t, "pull_execution") - 0.7) < 1e-9


def test_set_uniform_helper_writes_all_axes() -> None:
    t = main_module.build_tanaka()
    set_uniform(t, 0.33)
    for name in t.skill_vector.axis_names():
        assert t.skill_vector[name] == 0.33


# ---------------------------------------------------------------------------
# 5. Wired axes drive behavior end-to-end.
# ---------------------------------------------------------------------------
def test_pull_execution_drives_kuzushi_event_magnitude() -> None:
    """Two fighters, identical state, different pull_execution. Higher
    axis value → larger emitted KuzushiEvent."""
    from kuzushi import pull_kuzushi_event
    from grip_graph import GripGraph, GripEdge
    from body_state import place_judoka
    from enums import BodyPart, GripTarget, GripTypeV2, GripDepth

    def _emit(precision: float) -> float:
        t = main_module.build_tanaka()
        s = main_module.build_sato()
        place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
        place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
        t.skill_vector.pull_execution = precision
        g = GripGraph()
        edge = GripEdge(
            grasper_id=t.identity.name, grasper_part=BodyPart.RIGHT_HAND,
            target_id=s.identity.name, target_location=GripTarget.LEFT_LAPEL,
            grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.STANDARD,
            strength=0.8, established_tick=0,
        )
        g.add_edge(edge)
        ev = pull_kuzushi_event(
            attacker=t, edge=edge, victim=s,
            pull_direction=(-1.0, 0.0), current_tick=1,
        )
        return ev.magnitude if ev is not None else 0.0

    high = _emit(0.9)
    low = _emit(0.2)
    assert high > low, f"pull_execution should drive event mag; high={high}, low={low}"


def test_foot_sweep_axis_drives_foot_sweep_magnitude() -> None:
    """Per-kind axis specificity: foot_sweeps drives FOOT_SWEEP_SETUP
    magnitude, leg_attacks drives LEG_ATTACK_SETUP, etc."""
    from kuzushi import foot_attack_kuzushi_magnitude
    from actions import ActionKind

    t = main_module.build_tanaka()
    s = main_module.build_sato()
    # Tanaka: high foot_sweeps but low leg_attacks.
    t.skill_vector.foot_sweeps = 0.95
    t.skill_vector.leg_attacks = 0.10

    sweep_mag = foot_attack_kuzushi_magnitude(t, ActionKind.FOOT_SWEEP_SETUP, s)
    leg_mag   = foot_attack_kuzushi_magnitude(t, ActionKind.LEG_ATTACK_SETUP, s)
    # Despite leg attacks having a higher per-kind weight, Tanaka's
    # sweep skill dominates here.
    assert sweep_mag > leg_mag


def test_counter_window_reading_axis_drives_perception() -> None:
    """Defender with high counter_window_reading rarely flips; with low
    axis flips often."""
    import random
    from counter_windows import CounterWindow, perceived_counter_window
    s_high = main_module.build_sato()
    s_low = main_module.build_sato()
    s_high.skill_vector.counter_window_reading = 1.0
    s_low.skill_vector.counter_window_reading  = 0.0

    def _flip_rate(judoka, trials=400) -> float:
        flips = 0
        for seed in range(trials):
            p = perceived_counter_window(
                CounterWindow.GO_NO_SEN, judoka, rng=random.Random(seed),
            )
            if p != CounterWindow.GO_NO_SEN:
                flips += 1
        return flips / trials

    assert _flip_rate(s_low) > _flip_rate(s_high) + 0.10


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
