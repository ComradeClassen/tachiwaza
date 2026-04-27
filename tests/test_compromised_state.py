# tests/test_compromised_state.py
# Verifies Part 6.3 of design-notes/physics-substrate.md:
#   - Every tori-compromised FailureOutcome has a config
#   - apply_compromised_body_state mutates trunk / feet / CoM as configured
#   - counter_bonus_for returns per-state additive probability bonuses
#   - Desperation overlay extends recovery + stacks composure drop
#   - Match tracker sets the compromised-state tag on failure, clears at
#     recovery end, and bumps counter-fire probability during the window

from __future__ import annotations
import math
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from enums import (
    BeltRank, BodyPart, GripTypeV2, GripDepth, GripMode, GripTarget,
)
from body_state import place_judoka, FootContactState
from grip_graph import GripGraph, GripEdge
from throws import ThrowID
from throw_templates import FailureOutcome
from failure_resolution import FailureResolution, apply_failure_resolution
from compromised_state import (
    CompromisedStateConfig, COMPROMISED_STATE_CONFIGS,
    apply_compromised_body_state, counter_bonus_for,
    is_desperation_state, apply_desperation_overlay,
    DESPERATION_COMPOSURE_FRAC, DESPERATION_CLOCK_TICKS,
    DESPERATION_RECOVERY_BONUS,
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


# ---------------------------------------------------------------------------
# Config table coverage
# ---------------------------------------------------------------------------
def test_all_failure_outcomes_have_a_config() -> None:
    for outcome in FailureOutcome:
        assert outcome in COMPROMISED_STATE_CONFIGS, f"missing config for {outcome.name}"


def test_named_tori_states_have_counter_bonuses() -> None:
    """Every compromised-state-producing outcome names at least one exploiting
    counter throw. Non-compromised outcomes (STANCE_RESET, PARTIAL_THROW) are
    allowed to be empty.
    """
    compromised = (
        FailureOutcome.TORI_COMPROMISED_FORWARD_LEAN,
        FailureOutcome.TORI_COMPROMISED_SINGLE_SUPPORT,
        FailureOutcome.TORI_STUCK_WITH_UKE_ON_BACK,
        FailureOutcome.TORI_BENT_FORWARD_LOADED,
        FailureOutcome.TORI_ON_KNEE_UKE_STANDING,
        FailureOutcome.TORI_ON_BOTH_KNEES_UKE_STANDING,
        FailureOutcome.TORI_SWEEP_BOUNCES_OFF,
    )
    for outcome in compromised:
        bonuses = COMPROMISED_STATE_CONFIGS[outcome].counter_bonuses
        assert bonuses, f"{outcome.name} needs at least one counter bonus"
        for bonus in bonuses.values():
            assert 0.0 <= bonus <= 1.0


# ---------------------------------------------------------------------------
# Body-state mutations
# ---------------------------------------------------------------------------
def test_forward_lean_pitches_trunk_sagittal_forward() -> None:
    t, _ = _pair()
    before = t.state.body_state.trunk_sagittal
    apply_compromised_body_state(
        t, FailureOutcome.TORI_COMPROMISED_FORWARD_LEAN,
    )
    assert t.state.body_state.trunk_sagittal > before + math.radians(25)


def test_single_support_airborne_right_foot_and_shifts_weight() -> None:
    t, _ = _pair()
    apply_compromised_body_state(
        t, FailureOutcome.TORI_COMPROMISED_SINGLE_SUPPORT,
    )
    bs = t.state.body_state
    assert bs.foot_state_right.contact_state == FootContactState.AIRBORNE
    assert bs.foot_state_right.weight_fraction == 0.0
    assert bs.foot_state_left.weight_fraction == 1.0


def test_on_both_knees_drops_com_height() -> None:
    t, _ = _pair()
    before = t.state.body_state.com_height
    apply_compromised_body_state(
        t, FailureOutcome.TORI_ON_BOTH_KNEES_UKE_STANDING,
    )
    assert t.state.body_state.com_height < before - 0.30


def test_stuck_with_uke_on_back_bends_spine_sharply() -> None:
    t, _ = _pair()
    before = t.state.body_state.trunk_sagittal
    apply_compromised_body_state(
        t, FailureOutcome.TORI_STUCK_WITH_UKE_ON_BACK,
    )
    assert t.state.body_state.trunk_sagittal > before + math.radians(40)


def test_empty_config_does_not_mutate_body() -> None:
    t, _ = _pair()
    before_trunk  = t.state.body_state.trunk_sagittal
    before_height = t.state.body_state.com_height
    apply_compromised_body_state(t, FailureOutcome.STANCE_RESET)
    assert t.state.body_state.trunk_sagittal == before_trunk
    assert t.state.body_state.com_height    == before_height


# ---------------------------------------------------------------------------
# Counter-bonus lookup
# ---------------------------------------------------------------------------
def test_counter_bonus_returns_matching_outcome_entry() -> None:
    # Forward lean → O-soto-gari bonus per config.
    assert counter_bonus_for(
        FailureOutcome.TORI_COMPROMISED_FORWARD_LEAN, ThrowID.O_SOTO_GARI,
    ) > 0.0


def test_counter_bonus_returns_zero_for_none_outcome() -> None:
    assert counter_bonus_for(None, ThrowID.O_SOTO_GARI) == 0.0


def test_counter_bonus_returns_zero_for_mismatched_throw() -> None:
    # Sweep-bounces-off has no bonus for Seoi-nage.
    assert counter_bonus_for(
        FailureOutcome.TORI_SWEEP_BOUNCES_OFF, ThrowID.SEOI_NAGE,
    ) == 0.0


# ---------------------------------------------------------------------------
# Desperation overlay
# ---------------------------------------------------------------------------
def test_desperation_fires_when_panicked_and_clock_near_shido() -> None:
    t, _ = _pair()
    t.state.composure_current = 0.1   # very low vs ceiling
    assert is_desperation_state(t, DESPERATION_CLOCK_TICKS + 1) is True


def test_desperation_does_not_fire_when_composed() -> None:
    t, _ = _pair()
    t.state.composure_current = float(t.capability.composure_ceiling)
    assert is_desperation_state(t, DESPERATION_CLOCK_TICKS + 5) is False


def test_desperation_does_not_fire_when_clock_low() -> None:
    t, _ = _pair()
    t.state.composure_current = 0.1
    assert is_desperation_state(t, 0) is False


def test_apply_desperation_overlay_extends_recovery() -> None:
    base = FailureResolution(
        outcome=FailureOutcome.TORI_COMPROMISED_FORWARD_LEAN,
        recovery_ticks=3, failed_dimension="body", dimension_score=0.2,
    )
    overlaid = apply_desperation_overlay(base)
    assert overlaid.recovery_ticks == base.recovery_ticks + DESPERATION_RECOVERY_BONUS
    assert overlaid.outcome == base.outcome


# ---------------------------------------------------------------------------
# apply_failure_resolution integration
# ---------------------------------------------------------------------------
def test_apply_failure_resolution_now_mutates_body_state() -> None:
    t, _ = _pair()
    before = t.state.body_state.trunk_sagittal
    res = FailureResolution(
        outcome=FailureOutcome.TORI_COMPROMISED_FORWARD_LEAN,
        recovery_ticks=3, failed_dimension="body", dimension_score=0.2,
    )
    apply_failure_resolution(res, t)
    assert t.state.body_state.trunk_sagittal > before + math.radians(25)
    assert t.state.stun_ticks >= 3


# ---------------------------------------------------------------------------
# Match integration
# ---------------------------------------------------------------------------
def test_match_tracks_compromised_state_on_failure() -> None:
    """A failed worked-template throw sets _compromised_states[attacker]."""
    from match import Match
    from referee import build_suzuki
    from enums import Position
    random.seed(0)
    t, s = _pair()
    t.identity.belt_rank = BeltRank.BLACK_5   # N=1 for single-tick resolve
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())
    # HAJ-141 — bypass the engagement-distance gate for this commit-resolution
    # unit test. Production flow would set this when first edges seat.
    m.position = Position.GRIPPING
    import match as match_module
    real_resolve = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: ("FAILED", -5.0)
    try:
        m._resolve_commit_throw(t, s, ThrowID.UCHI_MATA, tick=1)
    finally:
        match_module.resolve_throw = real_resolve
    assert t.identity.name in m._compromised_states
    assert isinstance(m._compromised_states[t.identity.name], FailureOutcome)


def test_compromised_state_clears_after_recovery_window() -> None:
    """When stun_ticks decays to zero, the compromised-state tag clears."""
    from match import Match
    from referee import build_suzuki
    t, s = _pair()
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())
    m._compromised_states[t.identity.name] = (
        FailureOutcome.TORI_COMPROMISED_FORWARD_LEAN
    )
    t.state.stun_ticks = 1
    m._decay_stun(t)
    # After decay, stun=0 and the tag is gone.
    assert t.state.stun_ticks == 0
    assert t.identity.name not in m._compromised_states


def test_match_desperation_overlay_in_failed_event() -> None:
    """When commit conditions match desperation, FAILED event data reflects
    the overlay (longer recovery + desperation=True).
    """
    from match import Match
    from referee import build_suzuki
    from enums import Position
    random.seed(0)
    t, s = _pair()
    t.identity.belt_rank = BeltRank.BLACK_5     # N=1
    # Panic tori's composure.
    t.state.composure_current = 0.1
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())
    # HAJ-141 — bypass the engagement-distance gate for the direct-resolve call.
    m.position = Position.GRIPPING
    # Load the kumi-kata clock near shido.
    m.kumi_kata_clock[t.identity.name] = DESPERATION_CLOCK_TICKS + 5
    import match as match_module
    real_resolve = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: ("FAILED", -5.0)
    try:
        events = m._resolve_commit_throw(t, s, ThrowID.UCHI_MATA, tick=9)
    finally:
        match_module.resolve_throw = real_resolve
    failed = [e for e in events if e.event_type == "FAILED"]
    assert failed
    ev = failed[0]
    assert ev.data.get("desperation") is True
    # Recovery was bumped.
    assert ev.data["recovery_ticks"] >= DESPERATION_RECOVERY_BONUS


def test_counter_bonus_applied_against_compromised_tori() -> None:
    """_try_fire_counter bumps fire probability by the per-state bonus when
    tori is compromised.
    """
    from match import Match
    from referee import build_suzuki
    t, s = _pair()
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())
    # Seat the compromised-state tag directly (bypassing resolution).
    m._compromised_states[t.identity.name] = (
        FailureOutcome.TORI_COMPROMISED_FORWARD_LEAN
    )
    # Enable Sato's attack readiness.
    s.capability.fight_iq = 10
    s.state.composure_current = float(s.capability.composure_ceiling)
    # Build a fake in-progress attempt so sen-no-sen fires and O-soto-gari
    # becomes the symmetric counter.
    from skill_compression import SubEvent
    from match import _ThrowInProgress
    m._throws_in_progress[t.identity.name] = _ThrowInProgress(
        attacker_name=t.identity.name, defender_name=s.identity.name,
        throw_id=ThrowID.O_SOTO_GARI, start_tick=0, compression_n=3,
        schedule={0: [SubEvent.REACH_KUZUSHI]},
        commit_actual=0.6,
        last_sub_event=SubEvent.REACH_KUZUSHI,
    )

    # Stub RNG so the counter-fire roll always succeeds unless bonus is absent.
    class _AlwaysRoll:
        def __init__(self, roll):
            self.roll = roll
        def random(self):
            return self.roll
        def choice(self, seq):
            return seq[0]
    # Without bonus, the base probability for Sato (iq=10 × comp=1 × vuln 0.35
    # × SEN_NO_SEN mod 1.0) ≈ 0.30 × 0.35 ≈ 0.105. A roll of 0.20 would fail.
    # With the compromised-state O-soto bonus of +0.40, effective ≈ 0.505.
    # So a 0.20 roll should pass only when the bonus is in effect.
    events = m._check_counter_opportunities(tick=1, rng=_AlwaysRoll(0.20))
    assert any(e.event_type == "COUNTER_COMMIT" for e in events)


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
