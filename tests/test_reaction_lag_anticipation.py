# tests/test_reaction_lag_anticipation.py
# HAJ-149 — reaction lag + fight_iq-gated anticipation regression tests.
#
# Five canonical scenarios from the issue spec:
#   1. Elite mirror match — both fighters sample low / negative lag,
#      both produce BRACE responses to the opponent's commits.
#   2. Novice mirror match — both fighters sample positive lag, NONE
#      responses dominate.
#   3. Asymmetric match — high-fight_iq dominates rhythm via more
#      BRACE responses than the low-fight_iq side.
#   4. High-disguise tori vs. elite uke — disguise degrades anticipation:
#      uke's lag distribution shifts later than baseline elite-vs-elite.
#   5. HAJ-144 t003 reproduction — fighters with different fight_iq do
#      not co-fire identical commit-tick perception (no perfect mirror).
#
# Plus property-level tests on the reaction_lag math: signed-and-
# distributed (AC#1), fatigue / disguise / familiarity / composure
# modulators (AC#5-7), stamina cost (AC#8), no recursion cap (AC#9).

from __future__ import annotations
import contextlib
import io
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from enums import (
    BeltRank, BodyPart, GripTypeV2, GripDepth, GripMode, GripTarget,
    Position,
)
from body_state import place_judoka
from grip_graph import GripGraph, GripEdge
from throws import ThrowID
from match import Match, ANTICIPATION_CARDIO_COST
from referee import build_suzuki
from reaction_lag import (
    expected_lag, sample_lag, choose_response, disguise_for,
    LAG_CLAMP_MIN, LAG_CLAMP_MAX,
    BASE_LAG_INTERCEPT_IQ0, BASE_LAG_SLOPE_PER_IQ,
)
from skill_vector import SkillVector, set_uniform
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


def _set_fight_iq(judoka, iq: int) -> None:
    judoka.capability.fight_iq = iq


# ===========================================================================
# AC#1 — reaction_lag is signed, distributed, modulated
# ===========================================================================
def test_expected_lag_scales_with_fight_iq() -> None:
    """HAJ-222 — elite reads faster than novice, both still take at
    least one tick at our tick resolution (post-clamp). The signed-lag
    negative-anticipation semantics from the pre-HAJ-222 calibration
    are gone: the issue surfaced that the previous bias collapsed
    perception onto the commit tick. At neutral disguise, the base
    sits at 1.0 for elite and 4.0 for novice."""
    t, s = _pair()
    # Neutral disguise on both — isolates the fight_iq axis.
    set_uniform(t, 0.5)
    set_uniform(s, 0.5)
    _set_fight_iq(t, 10)
    _set_fight_iq(s, 0)
    elite_lag = expected_lag(t, s)
    novice_lag = expected_lag(s, t)
    assert elite_lag < novice_lag, (
        f"elite should read faster than novice: elite={elite_lag}, novice={novice_lag}"
    )
    # Elite base hugs 1 tick of physical reaction; novice sits in the
    # 3–5 tick range per HAJ-222 spec.
    assert elite_lag >= 0.5, f"elite base should be >= ~1, got {elite_lag}"
    assert novice_lag >= 3.0, f"novice base should be >= 3, got {novice_lag}"


def test_sample_lag_is_clamped() -> None:
    """Even with extreme inputs, sampled lag stays inside the v0.1 window."""
    rng = random.Random(0)
    t, s = _pair()
    set_uniform(t, 0.0)
    set_uniform(s, 0.0)
    _set_fight_iq(t, 10)
    _set_fight_iq(s, 0)
    for _ in range(200):
        lag = sample_lag(t, s, rng=rng)
        assert LAG_CLAMP_MIN <= lag <= LAG_CLAMP_MAX


def test_sample_lag_distribution_matches_fight_iq() -> None:
    """HAJ-222 — across many samples, an elite perceiver's lag
    distribution sits lower than a novice's. Both are positive
    (no anticipation at tick resolution); the gap is what matters."""
    rng = random.Random(7)
    t, s = _pair()
    set_uniform(t, 0.5)
    set_uniform(s, 0.5)
    _set_fight_iq(t, 10)
    _set_fight_iq(s, 0)
    elite_samples = [sample_lag(t, s, rng=rng) for _ in range(200)]
    novice_samples = [sample_lag(s, t, rng=rng) for _ in range(200)]
    assert statistics.mean(elite_samples) < statistics.mean(novice_samples)
    # Distribution width on the novice side — elite sits at the clamp
    # floor with little observable variance, but novice base 4.0
    # leaves room for the Gaussian to actually spread.
    assert statistics.pstdev(novice_samples) > 0.1
    # HAJ-222 — every sample is at least the LAG_CLAMP_MIN floor (1).
    assert min(elite_samples) >= LAG_CLAMP_MIN
    assert min(novice_samples) >= LAG_CLAMP_MIN


# ===========================================================================
# AC#5 — disguise modulates lag
# ===========================================================================
def test_high_disguise_pushes_perceiver_lag_later() -> None:
    """An elite uke vs. a high-disguise tori reads worse than the same
    uke vs. a low-disguise tori. (AC#5: disguise modulates signal.)"""
    t, s = _pair()
    _set_fight_iq(t, 10)
    # Low-disguise tori: uniform 0.0 across all skill axes including
    # sequencing / pull_execution.
    set_uniform(s, 0.0)
    low_disguise_lag = expected_lag(t, s)
    # High-disguise tori: uniform 1.0.
    set_uniform(s, 1.0)
    high_disguise_lag = expected_lag(t, s)
    assert high_disguise_lag > low_disguise_lag, (
        f"high disguise should push lag later: "
        f"low={low_disguise_lag}, high={high_disguise_lag}"
    )


# ===========================================================================
# AC#6 — fatigue degrades perception
# ===========================================================================
def test_fatigue_degrades_perception() -> None:
    """Same fighter, different fatigue states; lag distribution shifts
    later under fatigue. (AC#6 verbatim.)"""
    t, s = _pair()
    set_uniform(s, 0.0)
    _set_fight_iq(t, 10)
    fresh_lag = expected_lag(t, s, fatigue_frac=0.0)
    cooked_lag = expected_lag(t, s, fatigue_frac=1.0)
    assert cooked_lag > fresh_lag, (
        f"cooked perceiver should read worse: "
        f"fresh={fresh_lag}, cooked={cooked_lag}"
    )


# ===========================================================================
# AC#7 — composure modulates desperation's effect
# ===========================================================================
def test_high_composure_under_desperation_does_not_perceive_worse() -> None:
    """A high-composure fighter under desperation does not perceive worse
    than the same fighter without desperation. (AC#7 verbatim — high
    composure under desperation focuses, low composure panics.)"""
    t, s = _pair()
    set_uniform(s, 0.0)
    _set_fight_iq(t, 10)
    # Baseline (no desperation).
    baseline = expected_lag(t, s, in_desperation=False)
    # High composure (focus): lag should not be worse than baseline.
    focused = expected_lag(
        t, s, in_desperation=True, composure_frac=0.9,
    )
    panicked = expected_lag(
        t, s, in_desperation=True, composure_frac=0.1,
    )
    assert focused <= baseline + 1e-9, (
        f"high-composure desperation should sharpen, not dull: "
        f"baseline={baseline}, focused={focused}"
    )
    assert panicked > focused, (
        f"low-composure desperation should perceive worse than "
        f"high-composure desperation: panicked={panicked}, focused={focused}"
    )


# ===========================================================================
# Familiarity bonus
# ===========================================================================
def test_familiarity_shaves_lag() -> None:
    """Seeing the same throw class repeatedly in-match shaves lag —
    the perceiver pattern-matches the setup."""
    t, s = _pair()
    set_uniform(s, 0.0)
    _set_fight_iq(t, 10)
    cold = expected_lag(t, s, familiarity_count=0)
    seasoned = expected_lag(t, s, familiarity_count=3)
    assert seasoned < cold


# ===========================================================================
# Response selection — BRACE / NONE under HAJ-148's deferral
# ===========================================================================
def test_choose_response_brace_for_low_lag() -> None:
    """An elite perceiver (lag == 1) braces in time — the brace lands
    on the resolution tick. HAJ-222: the post-clamp minimum is 1, so
    this is the canonical "fast elite read" case."""
    t, s = _pair()
    _set_fight_iq(t, 10)
    resp = choose_response(t, s, sampled_lag=1, commit_tick=10)
    assert resp.kind == "BRACE"
    assert resp.target_tick == 11


def test_choose_response_none_for_late_lag() -> None:
    """A novice (lag >= 2) reacts after the resolution — too late."""
    t, s = _pair()
    _set_fight_iq(s, 0)
    resp = choose_response(s, t, sampled_lag=2, commit_tick=10)
    assert resp.kind == "NONE"


# ===========================================================================
# Match-level integration tests
# ===========================================================================
def _elite_match(seed: int = 0):
    """Both fighters elite (BLACK_5, fight_iq=10), grips seated, ready
    to drive commits directly."""
    random.seed(seed)
    t, s = _pair()
    t.identity.belt_rank = BeltRank.BLACK_5
    s.identity.belt_rank = BeltRank.BLACK_5
    _set_fight_iq(t, 10)
    _set_fight_iq(s, 10)
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki(), seed=seed)
    m.position = Position.GRIPPING
    _seat_deep_grips(m.grip_graph, t, s)
    _seat_deep_grips(m.grip_graph, s, t)
    return t, s, m


def _novice_match(seed: int = 0):
    """Both fighters novice (WHITE, fight_iq=0)."""
    random.seed(seed)
    t, s = _pair()
    t.identity.belt_rank = BeltRank.WHITE
    s.identity.belt_rank = BeltRank.WHITE
    _set_fight_iq(t, 0)
    _set_fight_iq(s, 0)
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki(), seed=seed)
    m.position = Position.GRIPPING
    _seat_deep_grips(m.grip_graph, t, s)
    _seat_deep_grips(m.grip_graph, s, t)
    return t, s, m


def test_intent_signal_emits_on_commit() -> None:
    """Every staged COMMIT_THROW emits at least one IntentSignal
    observable by the opposing fighter's perception system. HAJ-154
    moves the intent emission to the staging layer (one tick before
    the actual commit fires)."""
    from actions import Action, ActionKind
    t, s, m = _elite_match(seed=1)
    n_before = len(m._intent_signals)
    act = Action(kind=ActionKind.COMMIT_THROW, throw_id=ThrowID.UCHI_MATA)
    m._stage_commit_intent(t, s, act, tick=5)
    assert len(m._intent_signals) == n_before + 1
    sig = m._intent_signals[-1]
    assert sig.fighter == t.identity.name
    assert sig.throw_id == ThrowID.UCHI_MATA
    assert sig.setup_class == "throw_commit"
    assert 0.0 <= sig.specificity <= 1.0
    # And the actual commit firing is queued for tick+1.
    assert any(
        c.kind == "FIRE_COMMIT_FROM_INTENT" and c.due_tick == 6
        for c in m._consequence_queue
    )


# ===========================================================================
# AC#10 — five regression scenarios
# ===========================================================================
def _drive_commit_and_perception(m: Match, tori, uke, throw_id, tick: int):
    """Helper — stage a commit from `tori` against `uke` (HAJ-154
    intent-first pipeline), run the perception phase, and drain the
    consequence queue so the actual commit + landing fire on subsequent
    ticks. Returns the events captured across all those ticks."""
    from actions import Action, ActionKind
    act = Action(kind=ActionKind.COMMIT_THROW, throw_id=throw_id)
    events: list = list(m._stage_commit_intent(tori, uke, act, tick))
    m._perception_phase(tick, events)
    for follow_tick in (tick + 1, tick + 2, tick + 3):
        followup: list = []
        m._resolve_consequences(follow_tick, followup)
        events.extend(followup)
    return events


def test_elite_mirror_match_produces_brace_responses() -> None:
    """AC#10 elite mirror — both elite fighters perceive opponent
    commits in time and brace for resolution.

    HAJ-222 calibration: elite base lag is 1 tick, which lands the
    awareness on the resolution tick → BRACE. Gaussian variance still
    samples some 2s (NONE), so a strict "all BRACE" assertion is the
    wrong shape; we require majority BRACE instead. Commit spacing
    widened to 5 ticks so each attempt resolves before the next
    stages (a stale in-progress entry would suppress perception)."""
    t, s, m = _elite_match(seed=2)
    # Drive a sequence of commits; collect perception responses.
    for tick in range(5, 30, 5):
        # Patch resolve_throw so the deferred consequence is harmless.
        real = match_module.resolve_throw
        match_module.resolve_throw = lambda *a, **kw: ("FAILED", -2.0)
        try:
            _drive_commit_and_perception(m, t, s, ThrowID.UCHI_MATA, tick)
            m._resolve_consequences(tick + 1, [])  # drain consequence
        finally:
            match_module.resolve_throw = real
    # Across all those commits, the perception log should contain
    # mostly BRACE responses (elite uke reads them in time).
    kinds = [r.kind for r in m._perception_log]
    brace_count = sum(1 for k in kinds if k == "BRACE")
    assert kinds, "expected at least one perception response"
    assert brace_count >= len(kinds) // 2, (
        f"elite mirror should brace majority of commits, got {kinds}"
    )


def test_novice_mirror_match_brace_rate_is_lower() -> None:
    """AC#10 novice mirror — novices react late; BRACE rate is lower
    than the elite-mirror baseline."""
    t_e, s_e, m_e = _elite_match(seed=42)
    t_n, s_n, m_n = _novice_match(seed=42)
    real = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: ("FAILED", -2.0)
    try:
        for tick in range(5, 25, 2):
            _drive_commit_and_perception(m_e, t_e, s_e, ThrowID.UCHI_MATA, tick)
            m_e._resolve_consequences(tick + 1, [])
            _drive_commit_and_perception(m_n, t_n, s_n, ThrowID.UCHI_MATA, tick)
            m_n._resolve_consequences(tick + 1, [])
    finally:
        match_module.resolve_throw = real
    elite_brace = sum(1 for r in m_e._perception_log if r.kind == "BRACE")
    novice_brace = sum(1 for r in m_n._perception_log if r.kind == "BRACE")
    # AC#10: novice rate is *not higher* than elite rate. They can be
    # equal in degenerate seeds, but elite should generally meet or beat.
    assert elite_brace >= novice_brace, (
        f"elite brace rate ({elite_brace}) should meet or beat novice "
        f"({novice_brace})"
    )


def test_asymmetric_match_high_iq_dominates_rhythm() -> None:
    """AC#10 asymmetric — high-fight_iq side perceives commits in time
    more often than the low-fight_iq side."""
    random.seed(11)
    t, s = _pair()
    t.identity.belt_rank = BeltRank.BLACK_5
    s.identity.belt_rank = BeltRank.WHITE
    _set_fight_iq(t, 10)
    _set_fight_iq(s, 0)
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki(), seed=11)
    m.position = Position.GRIPPING
    _seat_deep_grips(m.grip_graph, t, s)
    _seat_deep_grips(m.grip_graph, s, t)
    real = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: ("FAILED", -2.0)
    try:
        for tick in range(5, 25, 2):
            # Tori commits → uke perceives.
            _drive_commit_and_perception(m, t, s, ThrowID.UCHI_MATA, tick)
            m._resolve_consequences(tick + 1, [])
            # Uke commits → tori perceives. Use a different tick to
            # avoid clobbering the throws-in-progress entry.
            _drive_commit_and_perception(m, s, t, ThrowID.O_SOTO_GARI, tick + 1)
            m._resolve_consequences(tick + 2, [])
    finally:
        match_module.resolve_throw = real
    # Tori (elite) braced uke's commits more often than uke (novice)
    # braced tori's commits.
    tori_braces = sum(
        1 for r in m._perception_log
        if r.kind == "BRACE" and r.perceiver == t.identity.name
    )
    uke_braces = sum(
        1 for r in m._perception_log
        if r.kind == "BRACE" and r.perceiver == s.identity.name
    )
    assert tori_braces >= uke_braces, (
        f"elite tori should brace more often than novice uke: "
        f"tori={tori_braces}, uke={uke_braces}"
    )


def test_high_disguise_tori_degrades_elite_uke_anticipation() -> None:
    """AC#10 high-disguise tori vs. elite uke — anticipation degrades
    measurably vs. the low-disguise baseline."""
    # Build two matches differing only in tori's disguise.
    def _run_with_disguise(disg: float, seed: int) -> int:
        random.seed(seed)
        t, s = _pair()
        t.identity.belt_rank = BeltRank.BLACK_5
        s.identity.belt_rank = BeltRank.BLACK_5
        _set_fight_iq(t, 10)
        _set_fight_iq(s, 10)
        # Tori's disguise — set sequencing + pull_execution to disg.
        set_uniform(t, disg)
        m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki(), seed=seed)
        m.position = Position.GRIPPING
        _seat_deep_grips(m.grip_graph, t, s)
        _seat_deep_grips(m.grip_graph, s, t)
        real = match_module.resolve_throw
        match_module.resolve_throw = lambda *a, **kw: ("FAILED", -2.0)
        try:
            for tick in range(5, 35, 2):
                _drive_commit_and_perception(
                    m, t, s, ThrowID.UCHI_MATA, tick,
                )
                m._resolve_consequences(tick + 1, [])
        finally:
            match_module.resolve_throw = real
        # Average sampled lag across uke's perception responses.
        return sum(r.sampled_lag for r in m._perception_log
                   if r.perceiver == s.identity.name)
    low_lag_sum  = _run_with_disguise(disg=0.0, seed=21)
    high_lag_sum = _run_with_disguise(disg=1.0, seed=21)
    # High disguise pushes uke's lag distribution *later* (higher sum).
    assert high_lag_sum > low_lag_sum, (
        f"high-disguise tori should worsen elite uke's sampled lag: "
        f"low_disguise_total={low_lag_sum}, high_disguise_total={high_lag_sum}"
    )


def test_haj144_t003_no_perfect_perception_mirror() -> None:
    """AC#10 t003 — fighters with different fight_iq do not co-fire
    perfectly mirrored perception responses on the commit tick."""
    random.seed(3)
    t, s = _pair()
    t.identity.belt_rank = BeltRank.BLACK_5
    s.identity.belt_rank = BeltRank.WHITE
    _set_fight_iq(t, 10)
    _set_fight_iq(s, 0)
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki(), seed=3)
    m.position = Position.GRIPPING
    _seat_deep_grips(m.grip_graph, t, s)
    _seat_deep_grips(m.grip_graph, s, t)
    real = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: ("FAILED", -2.0)
    try:
        # HAJ-154 — both fighters' COMMIT_THROW intents staged on tick 3.
        # Each emits an IntentSignal for the perception phase to read.
        from actions import Action, ActionKind
        m._stage_commit_intent(
            t, s,
            Action(kind=ActionKind.COMMIT_THROW, throw_id=ThrowID.UCHI_MATA),
            tick=3,
        )
        m._stage_commit_intent(
            s, t,
            Action(kind=ActionKind.COMMIT_THROW,
                   throw_id=ThrowID.O_SOTO_GARI),
            tick=3,
        )
        m._perception_phase(3, [])
    finally:
        match_module.resolve_throw = real
    # At least one of: different lag samples, different response kinds.
    by_perceiver = {r.perceiver: r for r in m._perception_log}
    assert len(by_perceiver) == 2, (
        f"expected one perception per fighter, got {by_perceiver}"
    )
    a_resp = by_perceiver[t.identity.name]
    b_resp = by_perceiver[s.identity.name]
    differs = (a_resp.sampled_lag != b_resp.sampled_lag
               or a_resp.kind != b_resp.kind)
    assert differs, (
        f"asymmetric fighters should not produce identical perception "
        f"responses: a={a_resp}, b={b_resp}"
    )


# ===========================================================================
# AC#8 — anticipation costs stamina
# ===========================================================================
def test_anticipation_drains_cardio_proportionally() -> None:
    """Same fighter, same number of substantive opponent actions, but
    different perception-event counts → different cardio drain."""
    random.seed(99)
    # Match A: elite uke (lots of BRACE responses).
    t_a, s_a, m_a = _elite_match(seed=99)
    # Match B: novice uke (mostly NONE responses; little anticipation drain).
    t_b, s_b, m_b = _novice_match(seed=99)
    real = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: ("FAILED", -2.0)
    try:
        for tick in range(5, 25, 2):
            _drive_commit_and_perception(m_a, t_a, s_a, ThrowID.UCHI_MATA, tick)
            m_a._resolve_consequences(tick + 1, [])
            _drive_commit_and_perception(m_b, t_b, s_b, ThrowID.UCHI_MATA, tick)
            m_b._resolve_consequences(tick + 1, [])
    finally:
        match_module.resolve_throw = real
    # Elite uke braced more times → more cardio drained.
    elite_brace_count = sum(1 for r in m_a._perception_log if r.kind == "BRACE")
    novice_brace_count = sum(1 for r in m_b._perception_log if r.kind == "BRACE")
    elite_drain = 1.0 - s_a.state.cardio_current
    novice_drain = 1.0 - s_b.state.cardio_current
    # Each BRACE costs ANTICIPATION_CARDIO_COST. Confirm the deltas
    # match the brace counts (single-source-of-truth check; isolating
    # the perception drain from any other noise in the system).
    expected_elite_drain = elite_brace_count * ANTICIPATION_CARDIO_COST
    expected_novice_drain = novice_brace_count * ANTICIPATION_CARDIO_COST
    assert abs(elite_drain - expected_elite_drain) < 1e-6, (
        f"elite drain ({elite_drain}) != braces * cost ({expected_elite_drain})"
    )
    assert abs(novice_drain - expected_novice_drain) < 1e-6
    # And the elite path drained at least as much as the novice path.
    assert elite_drain >= novice_drain


# ===========================================================================
# AC#9 — no recursion cap (mutual anticipation runs unbounded)
# ===========================================================================
def test_mutual_anticipation_has_no_recursion_cap() -> None:
    """Two elite fighters with no disguise advantage produce unbounded
    perception cycles — the simulation does not artificially terminate
    after N cycles. (Natural systems — fatigue, kumi-kata clock — break
    the stalemate; not an internal cap.)"""
    t, s, m = _elite_match(seed=88)
    real = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: ("FAILED", -2.0)
    try:
        for tick in range(5, 50, 2):
            _drive_commit_and_perception(m, t, s, ThrowID.UCHI_MATA, tick)
            m._resolve_consequences(tick + 1, [])
            _drive_commit_and_perception(m, s, t, ThrowID.O_SOTO_GARI, tick + 1)
            m._resolve_consequences(tick + 2, [])
    finally:
        match_module.resolve_throw = real
    # We drove ~24 commits; the perception log carries an entry per
    # signal and there's no internal limit (no "cap" exception).
    # Also verify cardio drained — the natural-systems brake is real.
    assert len(m._perception_log) >= 20
    assert (
        s.state.cardio_current < 1.0 or t.state.cardio_current < 1.0
    ), "expected at least some cardio drain across many perception events"


# ===========================================================================
# AC#12 — HAJ-148 ACs continue to hold
# ===========================================================================
def test_haj148_invariants_still_hold() -> None:
    """Spot-check that HAJ-148's commit-silent-in-prose and consequence
    queue invariants still hold post-149/154. Uses the staging
    pipeline (HAJ-154) so an IntentSignal fires on tick 5 before the
    actual commit fires on tick 6 from the consequence queue."""
    from actions import Action, ActionKind
    t, s, m = _elite_match(seed=4)
    real = match_module.resolve_throw
    match_module.resolve_throw = lambda *a, **kw: ("FAILED", -2.0)
    try:
        # Tick 5 — stage commit (intent fires now; commit queued for tick 6).
        m._stage_commit_intent(
            t, s,
            Action(kind=ActionKind.COMMIT_THROW, throw_id=ThrowID.UCHI_MATA),
            tick=5,
        )
        sig = m._intent_signals[-1]
        assert sig.tick == 5
        # Tick 6 — consequence fires the actual commit; THROW_ENTRY
        # surfaces here, prose-silent.
        evts: list = []
        m._resolve_consequences(tick=6, events=evts)
        commit = next(e for e in evts if e.event_type == "THROW_ENTRY")
        assert commit.tick == 6
        assert commit.data.get("prose_silent") is True
        # Tick 7 — the N=1 deferred kake landing.
        followup: list = []
        m._resolve_consequences(tick=7, events=followup)
        if followup:
            assert all(e.tick == 7 for e in followup)
    finally:
        match_module.resolve_throw = real


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
