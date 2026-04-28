# tests/test_execution_quality.py
# Verifies Part 4.2.1 of design-notes/physics-substrate.md (HAJ-62):
#   - execution_quality = (actual - threshold) / (1 - threshold), clamped
#   - band_for thresholds at 0.40 / 0.70
#   - force_transfer_multiplier is monotonic and bounded by [FLOOR, 1]
#   - counter_vulnerability_multiplier is monotonic; 1.0 at eq=1
#   - commit_threshold_for reads the worked template, default for legacy
#   - resolve_throw scales attack_strength by the eq multiplier
#   - Referee.score_throw gates IPPON / WAZA_ARI / NO_SCORE on eq
#   - counter_fire_probability consumes tori_execution_quality in go-no-sen
#   - Match._resolve_commit_throw surfaces eq on the THROW_ENTRY line/data

from __future__ import annotations
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from enums import BodyPart, GripTarget, LandingProfile
from body_state import place_judoka
from grip_graph import GripGraph, GripEdge
from throws import ThrowID
from worked_throws import SEOI_NAGE_MOROTE, UCHI_MATA
from execution_quality import (
    compute_execution_quality, commit_threshold_for, band_for,
    force_transfer_multiplier, counter_vulnerability_multiplier,
    narration_for,
    QualityBand,
    FORCE_TRANSFER_FLOOR, IPPON_MIN_EQ, WAZA_ARI_MIN_EQ,
    DEFAULT_COMMIT_THRESHOLD,
)
from counter_windows import (
    CounterWindow, counter_fire_probability,
)
from referee import ScoreResult, ThrowLanding, build_suzuki
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


def _seat_deep_grips(graph: GripGraph, attacker, defender) -> None:
    from enums import GripTypeV2, GripDepth, GripMode
    graph.add_edge(GripEdge(
        grasper_id=attacker.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=defender.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.STANDARD,
        strength=0.8, established_tick=0, mode=GripMode.DRIVING,
    ))
    graph.add_edge(GripEdge(
        grasper_id=attacker.identity.name, grasper_part=BodyPart.LEFT_HAND,
        target_id=defender.identity.name, target_location=GripTarget.RIGHT_SLEEVE,
        grip_type_v2=GripTypeV2.SLEEVE_HIGH, depth_level=GripDepth.STANDARD,
        strength=0.8, established_tick=0, mode=GripMode.DRIVING,
    ))


# ---------------------------------------------------------------------------
# compute_execution_quality
# ---------------------------------------------------------------------------
def test_eq_zero_at_commit_threshold() -> None:
    assert compute_execution_quality(0.55, 0.55) == 0.0


def test_eq_one_at_perfect_match() -> None:
    assert compute_execution_quality(1.0, 0.55) == 1.0


def test_eq_clamps_below_threshold_to_zero() -> None:
    assert compute_execution_quality(0.20, 0.55) == 0.0


def test_eq_halfway_gives_half() -> None:
    # threshold 0.50 → (0.75 - 0.50) / 0.50 = 0.5
    assert abs(compute_execution_quality(0.75, 0.50) - 0.5) < 1e-9


def test_eq_degenerate_threshold_returns_zero() -> None:
    # A threshold of 1.0 would divide by zero; should fall back to 0.
    assert compute_execution_quality(1.0, 1.0) == 0.0


# ---------------------------------------------------------------------------
# band_for
# ---------------------------------------------------------------------------
def test_band_low_below_waza_ari_min() -> None:
    assert band_for(0.0) == QualityBand.LOW
    assert band_for(WAZA_ARI_MIN_EQ - 0.01) == QualityBand.LOW


def test_band_med_in_range() -> None:
    assert band_for(WAZA_ARI_MIN_EQ) == QualityBand.MED
    assert band_for(IPPON_MIN_EQ - 0.01) == QualityBand.MED


def test_band_high_at_or_above_ippon_min() -> None:
    assert band_for(IPPON_MIN_EQ) == QualityBand.HIGH
    assert band_for(1.0) == QualityBand.HIGH


# ---------------------------------------------------------------------------
# Multipliers
# ---------------------------------------------------------------------------
def test_force_multiplier_bounded_and_monotonic() -> None:
    assert force_transfer_multiplier(0.0) == FORCE_TRANSFER_FLOOR
    assert force_transfer_multiplier(1.0) == 1.0
    assert (force_transfer_multiplier(0.3)
            < force_transfer_multiplier(0.7)
            < force_transfer_multiplier(1.0))


def test_counter_vulnerability_multiplier_monotonic_inverse() -> None:
    assert counter_vulnerability_multiplier(1.0) == 1.0
    # Low eq → larger multiplier (more vulnerable).
    assert counter_vulnerability_multiplier(0.0) > 1.0
    assert (counter_vulnerability_multiplier(0.0)
            > counter_vulnerability_multiplier(0.5)
            > counter_vulnerability_multiplier(1.0))


# ---------------------------------------------------------------------------
# commit_threshold_for
# ---------------------------------------------------------------------------
def test_commit_threshold_for_reads_worked_template() -> None:
    # Seoi-nage worked template sets 0.70.
    assert commit_threshold_for(ThrowID.SEOI_NAGE) == 0.70
    assert commit_threshold_for(ThrowID.UCHI_MATA) == UCHI_MATA.commit_threshold


def test_commit_threshold_for_default_on_legacy() -> None:
    # Sumi-gaeshi has no worked template; default applies.
    assert commit_threshold_for(ThrowID.SUMI_GAESHI) == DEFAULT_COMMIT_THRESHOLD


# ---------------------------------------------------------------------------
# Narration table
# ---------------------------------------------------------------------------
def test_narration_has_three_bands_for_worked_throws() -> None:
    for throw_id in (
        ThrowID.UCHI_MATA, ThrowID.O_SOTO_GARI, ThrowID.SEOI_NAGE,
        ThrowID.DE_ASHI_HARAI, ThrowID.TAI_OTOSHI,
    ):
        for band in QualityBand:
            text = narration_for(throw_id, band)
            assert isinstance(text, str) and text
            # The three bands should differ for each worked throw.
        bands = {narration_for(throw_id, b) for b in QualityBand}
        assert len(bands) == 3, f"{throw_id} has duplicate narration bands"


def test_narration_falls_back_to_generic_for_unknown_throw() -> None:
    # SUMI_GAESHI isn't in the quality-narration table — should still return
    # a non-empty string via the generic fallback.
    for band in QualityBand:
        assert narration_for(ThrowID.SUMI_GAESHI, band)


# ---------------------------------------------------------------------------
# resolve_throw — eq scales attack_strength
# ---------------------------------------------------------------------------
def test_resolve_throw_eq_scales_net_score() -> None:
    """Same attacker/defender state, different eq → lower eq yields a lower
    net_score because attack_strength is multiplied by force_transfer_multiplier.
    """
    from match import resolve_throw
    from enums import StanceMatchup
    t, s = _pair()
    random.seed(42)
    _, net_high = resolve_throw(
        t, s, ThrowID.SEOI_NAGE, StanceMatchup.MATCHED,
        window_quality=1.0, execution_quality=1.0,
    )
    random.seed(42)
    _, net_low = resolve_throw(
        t, s, ThrowID.SEOI_NAGE, StanceMatchup.MATCHED,
        window_quality=1.0, execution_quality=0.0,
    )
    # Same RNG seed, same wq → net differs only via force multiplier.
    # Low eq goes through FORCE_TRANSFER_FLOOR, so net should be noticeably lower.
    assert net_low < net_high


# ---------------------------------------------------------------------------
# Referee gates IPPON / WAZA_ARI / NO_SCORE on eq
# ---------------------------------------------------------------------------
def _landing(eq: float, net: float = 5.0) -> ThrowLanding:
    return ThrowLanding(
        landing_profile=LandingProfile.FORWARD_ROTATIONAL,
        net_score=net,
        window_quality=1.0,
        control_maintained=True,
        execution_quality=eq,
    )


def test_score_throw_no_score_when_eq_below_waza_ari_min() -> None:
    ref = build_suzuki()
    random.seed(0)
    result = ref.score_throw(_landing(eq=WAZA_ARI_MIN_EQ - 0.05), tick=1)
    assert result.award == "NO_SCORE"


def test_score_throw_waza_ari_in_med_band() -> None:
    ref = build_suzuki()
    random.seed(0)
    # Well inside the MED band, high raw net so IPPON threshold passes but
    # eq < IPPON_MIN_EQ forces WAZA_ARI.
    result = ref.score_throw(_landing(eq=0.5, net=6.0), tick=1)
    assert result.award == "WAZA_ARI"


def test_score_throw_ippon_eligible_high_band() -> None:
    ref = build_suzuki()
    # Run several trials because of the referee's gauss noise; at eq=0.95,
    # net=8, clean profile, IPPON should land on average.
    random.seed(123)
    awards = [
        ref.score_throw(_landing(eq=0.95, net=8.0), tick=1).award
        for _ in range(30)
    ]
    assert awards.count("IPPON") >= 15  # strong majority


# ---------------------------------------------------------------------------
# counter_fire_probability — tori eq amplifies vulnerability
# ---------------------------------------------------------------------------
def test_counter_fire_prob_increases_when_tori_eq_low() -> None:
    _, s = _pair()
    s.capability.fight_iq = 10
    # Seoi-nage counter_vulnerability=0.55. Go-no-sen window.
    high_eq = counter_fire_probability(
        s, CounterWindow.GO_NO_SEN, 0.55,
        tori_execution_quality=1.0,
    )
    low_eq = counter_fire_probability(
        s, CounterWindow.GO_NO_SEN, 0.55,
        tori_execution_quality=0.0,
    )
    assert low_eq > high_eq


def test_counter_fire_prob_unchanged_when_tori_eq_none() -> None:
    _, s = _pair()
    s.capability.fight_iq = 10
    base = counter_fire_probability(s, CounterWindow.GO_NO_SEN, 0.55)
    keyword_none = counter_fire_probability(
        s, CounterWindow.GO_NO_SEN, 0.55, tori_execution_quality=None,
    )
    assert base == keyword_none


def test_counter_fire_prob_ignores_eq_in_sen_sen_window() -> None:
    """Sen-sen-no-sen fires before tori commits; tori's eq is meaningless
    because no throw has fired yet. Passing eq should be ignored.
    """
    _, s = _pair()
    s.capability.fight_iq = 10
    with_eq = counter_fire_probability(
        s, CounterWindow.SEN_SEN_NO_SEN, 0.55,
        tori_execution_quality=0.0,
    )
    without = counter_fire_probability(
        s, CounterWindow.SEN_SEN_NO_SEN, 0.55,
    )
    assert with_eq == without


# ---------------------------------------------------------------------------
# Match integration — THROW_ENTRY carries eq
# ---------------------------------------------------------------------------
def test_throw_entry_event_carries_execution_quality() -> None:
    from match import Match
    t, s = _pair()
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())
    _seat_deep_grips(m.grip_graph, t, s)

    events = m._resolve_commit_throw(t, s, ThrowID.SEOI_NAGE, tick=1)
    entries = [e for e in events if e.event_type == "THROW_ENTRY"]
    assert entries, "expected a THROW_ENTRY event"
    e = entries[0]
    assert "execution_quality" in e.data
    assert "commit_threshold" in e.data
    assert 0.0 <= e.data["execution_quality"] <= 1.0
    # HAJ-144 acceptance #10 — eq= no longer surfaces in the visible
    # THROW_ENTRY description; the numeric value lives only in
    # Event.data for the debug stream / inspector.
    assert "eq=" not in e.description


def test_in_progress_throw_records_commit_execution_quality() -> None:
    from match import Match
    t, s = _pair()
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())
    _seat_deep_grips(m.grip_graph, t, s)

    m._resolve_commit_throw(t, s, ThrowID.SEOI_NAGE, tick=1)
    # If compression_n > 1, attempt is stashed with the eq captured at commit.
    tip = m._throws_in_progress.get(t.identity.name)
    if tip is not None:
        assert 0.0 <= tip.commit_execution_quality <= 1.0


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
