# tests/test_failure_resolution.py
# Verifies Part 4.5 / Part 6.3 failure-outcome routing:
#   - select_failure_outcome picks primary by default
#   - Tertiary fires when uke is fatigued or panicked
#   - Secondary (clean counter) fires when uke is sharp + throw is vulnerable
#   - apply_failure_resolution applies stun_ticks + composure delta
#   - Recovery ticks mirror Part 6.3's published durations
#   - match._apply_throw_result FAILED branch emits a typed FailureOutcome event

from __future__ import annotations
import math
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from body_state import place_judoka
from grip_graph import GripGraph
from throws import ThrowID
from throw_templates import FailureOutcome, FailureSpec
from worked_throws import (
    UCHI_MATA, O_SOTO_GARI, SEOI_NAGE_MOROTE, DE_ASHI_HARAI,
)
from failure_resolution import (
    select_failure_outcome, apply_failure_resolution,
    RECOVERY_TICKS_BY_OUTCOME, FailureResolution,
    COUNTER_READINESS_GATE, FATIGUED_UKE_THRESHOLD, PANICKED_UKE_THRESHOLD,
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
# Recovery table sanity
# ---------------------------------------------------------------------------
def test_recovery_durations_match_spec_6_3() -> None:
    # Spec 6.3 published durations.
    assert RECOVERY_TICKS_BY_OUTCOME[FailureOutcome.TORI_SWEEP_BOUNCES_OFF]          == 1
    assert RECOVERY_TICKS_BY_OUTCOME[FailureOutcome.TORI_COMPROMISED_SINGLE_SUPPORT] in (1, 2)
    assert RECOVERY_TICKS_BY_OUTCOME[FailureOutcome.TORI_STUCK_WITH_UKE_ON_BACK]     in (3, 4)
    assert RECOVERY_TICKS_BY_OUTCOME[FailureOutcome.TORI_ON_BOTH_KNEES_UKE_STANDING] in (3, 4, 5)
    # Non-compromised outcomes have zero recovery.
    assert RECOVERY_TICKS_BY_OUTCOME[FailureOutcome.STANCE_RESET] == 0
    assert RECOVERY_TICKS_BY_OUTCOME[FailureOutcome.PARTIAL_THROW] == 0


# ---------------------------------------------------------------------------
# Routing: primary / secondary / tertiary branches
# ---------------------------------------------------------------------------
def test_primary_outcome_picked_when_uke_is_average() -> None:
    t, s = _pair()
    g = GripGraph()
    # Sato is fresh + composed; fight_iq mid; throw vulnerability moderate.
    # Random seeded so the secondary-branch roll fails deterministically.
    rng = random.Random(0)
    # Drop Sato's IQ so counter_ready is below the gate.
    s.capability.fight_iq = 3
    res = select_failure_outcome(UCHI_MATA, t, s, g, rng=rng)
    assert res.outcome == UCHI_MATA.failure_outcome.primary


def test_tertiary_outcome_fires_when_uke_is_fatigued() -> None:
    t, s = _pair()
    g = GripGraph()
    # Cook Sato's legs past the fatigue threshold.
    s.state.body["right_leg"].fatigue = 0.9
    s.state.body["left_leg"].fatigue  = 0.9
    res = select_failure_outcome(UCHI_MATA, t, s, g, rng=random.Random(0))
    assert res.outcome == UCHI_MATA.failure_outcome.tertiary


def test_tertiary_outcome_fires_when_uke_is_panicked() -> None:
    t, s = _pair()
    g = GripGraph()
    # Drop Sato's composure below the panic threshold.
    s.state.composure_current = 0.5   # ceiling is 7+ for built Sato; fraction < 0.3
    res = select_failure_outcome(UCHI_MATA, t, s, g, rng=random.Random(0))
    assert res.outcome == UCHI_MATA.failure_outcome.tertiary


def test_secondary_outcome_can_fire_for_high_vulnerability_throw() -> None:
    """Uchi-mata has sukashi_vulnerability=0.75 — a sharp uke has a real shot."""
    t, s = _pair()
    g = GripGraph()
    # Max Sato out on IQ + composure to satisfy counter_ready gate.
    s.capability.fight_iq = 10
    s.capability.composure_ceiling = 10
    s.state.composure_current = 10
    # Drain a bunch of seeds until we hit the probabilistic secondary branch;
    # with readiness ~1.0 and vuln 0.75, ~75% of rolls should fire secondary.
    hits = 0
    for seed in range(20):
        res = select_failure_outcome(UCHI_MATA, t, s, g, rng=random.Random(seed))
        if res.outcome == UCHI_MATA.failure_outcome.secondary:
            hits += 1
    # At least a few must land given the probability.
    assert hits >= 5


# ---------------------------------------------------------------------------
# apply_failure_resolution
# ---------------------------------------------------------------------------
def test_apply_sets_stun_and_drops_composure() -> None:
    t, _ = _pair()
    before_stun = t.state.stun_ticks
    before_comp = t.state.composure_current
    res = FailureResolution(
        outcome=FailureOutcome.TORI_STUCK_WITH_UKE_ON_BACK,
        recovery_ticks=4, failed_dimension="body", dimension_score=0.2,
    )
    apply_failure_resolution(res, t, composure_drop=0.2)
    assert t.state.stun_ticks == before_stun + 4
    assert t.state.composure_current == max(0.0, before_comp - 0.2)


def test_recovery_extended_when_attacker_is_panicked() -> None:
    t, s = _pair()
    g = GripGraph()
    # Tori panicked below threshold; drops recovery +1 per Part 6.3 desperation.
    t.state.composure_current = 0.5   # < 0.3 × ceiling
    # And sato is average — primary branch fires.
    s.capability.fight_iq = 3
    base = RECOVERY_TICKS_BY_OUTCOME[UCHI_MATA.failure_outcome.primary]
    res = select_failure_outcome(UCHI_MATA, t, s, g, rng=random.Random(0))
    assert res.recovery_ticks == base + 1


# ---------------------------------------------------------------------------
# Failed-dimension reporting
# ---------------------------------------------------------------------------
def test_failed_dimension_identified_as_kuzushi_when_uke_is_stationary() -> None:
    t, s = _pair()
    g = GripGraph()
    # Stationary uke → kuzushi dimension is 0, should be identified as worst.
    res = select_failure_outcome(UCHI_MATA, t, s, g, rng=random.Random(0))
    # Force is also 0 (no grips), so worst is tied at 0 — but min() picks one.
    assert res.failed_dimension in ("kuzushi", "force")
    assert res.dimension_score == 0.0


# ---------------------------------------------------------------------------
# match.py FAILED-branch integration
# ---------------------------------------------------------------------------
def test_match_failed_branch_emits_typed_failure_event_for_worked_throws() -> None:
    """When resolve_throw returns FAILED for a worked-template throw, the
    emitted event carries the FailureOutcome name in its data dict.
    Elite tori (N=1) resolves in a single tick so we can observe the full
    event chain from one commit call.
    """
    from enums import BeltRank
    from match import Match
    from referee import build_suzuki
    random.seed(0)
    t, s = _pair()
    t.identity.belt_rank = BeltRank.BLACK_5   # Force N=1 for predictable single-tick resolve.
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())
    # HAJ-141 — direct-resolve unit test; bypass the engagement-distance gate.
    from enums import Position
    m.position = Position.GRIPPING
    import match as match_module
    real_resolve = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: ("FAILED", -5.0)
    try:
        events = m._resolve_commit_throw(t, s, ThrowID.UCHI_MATA, tick=9)
    finally:
        match_module.resolve_throw = real_resolve
    failed = [ev for ev in events if ev.event_type == "FAILED"]
    assert failed, "expected a FAILED event"
    ev = failed[0]
    assert "outcome" in ev.data
    assert ev.data["outcome"] in {o.name for o in FailureOutcome}
    assert ev.data["recovery_ticks"] >= 0


def test_multi_tick_failure_resolves_at_kake_commit_tick() -> None:
    """A non-elite's multi-tick attempt that resolves to FAILED emits the
    typed FailureOutcome event on the KAKE tick (not the commit tick).
    """
    from match import Match
    from referee import build_suzuki
    random.seed(0)
    t, s = _pair()
    # Tanaka BLACK_1 + UCHI_MATA (non-signature) → N=2.
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())
    # HAJ-141 — direct-resolve unit test; bypass the engagement-distance gate.
    from enums import Position
    m.position = Position.GRIPPING
    import match as match_module
    real_resolve = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: ("FAILED", -5.0)
    try:
        start_events = m._resolve_commit_throw(t, s, ThrowID.UCHI_MATA, tick=9)
        assert not any(ev.event_type == "FAILED" for ev in start_events)
        # KAKE tick advances the attempt and resolves it.
        kake_events = m._advance_throws_in_progress(tick=10)
    finally:
        match_module.resolve_throw = real_resolve
    failed = [ev for ev in kake_events if ev.event_type == "FAILED"]
    assert failed
    assert "outcome" in failed[0].data


def test_match_failed_branch_for_legacy_throw_is_unchanged() -> None:
    """Non-worked throws (e.g. SUMI_GAESHI, the only remaining legacy-only
    throw after HAJ-29 backfill) still fall through to the generic
    'failed (no commitment, net X.XX)' event shape with no outcome data.
    Elite belt forces N=1 so the resolution lands in a single tick.
    """
    from enums import BeltRank
    from match import Match
    from referee import build_suzuki
    from worked_throws import WORKED_THROWS
    # Sanity — SUMI_GAESHI must remain legacy-only for this test to mean what
    # it claims. If someone adds it to WORKED_THROWS, swap to another throw.
    assert ThrowID.SUMI_GAESHI not in WORKED_THROWS
    random.seed(0)
    t, s = _pair()
    t.identity.belt_rank = BeltRank.BLACK_5
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())
    # HAJ-141 — direct-resolve unit test; bypass the engagement-distance gate.
    from enums import Position
    m.position = Position.GRIPPING
    import match as match_module
    real_resolve = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: ("FAILED", -5.0)
    try:
        events = m._resolve_commit_throw(t, s, ThrowID.SUMI_GAESHI, tick=9)
    finally:
        match_module.resolve_throw = real_resolve
    failed = [ev for ev in events if ev.event_type == "FAILED"]
    assert failed
    assert "outcome" not in failed[0].data


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
