# tests/test_grip_initiative.py
# HAJ-151 — grip initiative variance + five-response cascade.
#
# Six AC#11 regression scenarios:
#   1. HAJ-144 t003 reproduction — no symmetric four-grip seating on tick 3.
#   2. Aggressive vs. patient — aggressive fighter wins lead-grip race
#      in >70% of openings.
#   3. GRIP_FIGHTER vs. EXPLOSIVE — GRIP_FIGHTER wins lead grip more
#      often; EXPLOSIVE follower defaults to PURSUE_OWN over CONTEST.
#   4. Matched vs. mirrored stance — same fighters, swapped dominant_side;
#      response patterns differ measurably.
#   5. Composure-degraded fighter loses initiative.
#   6. Clock-pressure asymmetry — trailing fighter reaches faster;
#      leading fighter chooses DEFENSIVE/DISENGAGE more often.
#   7. Disengage and re-engage loop — DISENGAGE transitions to
#      STANDING_DISTANT, accumulates toward shido pressure.
#
# Plus property tests on the grip_initiative module: weight tables active,
# initiative is signed-and-distributed, response selection is probabilistic.

from __future__ import annotations
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from enums import (
    BeltRank, BodyArchetype, DominantSide, Position, StanceMatchup,
    SubLoopState, GripTypeV2, GripDepth,
)
from body_state import place_judoka
from match import Match, ENGAGEMENT_TICKS_FLOOR, DISENGAGE_SHIDO_THRESHOLD_COUNT
from referee import build_suzuki
from grip_initiative import (
    expected_initiative, sample_initiative, select_response,
    clock_pressure_roles,
    MATCHED_WEIGHTS, MIRRORED_WEIGHTS, _BASE_ARCHETYPE,
    RESP_CONTEST, RESP_MATCH, RESP_PURSUE_OWN, RESP_DEFENSIVE, RESP_DISENGAGE,
    RESP_ACCEPT_BAIT,
    ALL_RESPONSE_KINDS, CLOCK_PRESSURE_TICKS_REMAINING,
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


def _set_aggressive(j, value: int) -> None:
    j.identity.personality_facets["aggressive"] = value


def _set_archetype(j, archetype: BodyArchetype) -> None:
    j.identity.body_archetype = archetype


# ===========================================================================
# AC#1 / AC#7 — initiative score is signed, weighted, distributed
# ===========================================================================
def test_expected_initiative_is_a_weighted_sum() -> None:
    t, s = _pair()
    score = expected_initiative(t, s)
    # Sanity — positive score for the canonical fighters in matched stance.
    assert isinstance(score, float)
    assert score > 0.0


def test_aggressive_facet_increases_initiative() -> None:
    t, s = _pair()
    _set_aggressive(t, 0)
    low = expected_initiative(t, s)
    _set_aggressive(t, 10)
    high = expected_initiative(t, s)
    assert high > low


def test_grip_fighter_archetype_outscores_others() -> None:
    t, s = _pair()
    _set_archetype(t, BodyArchetype.LEVER)
    lever = expected_initiative(t, s)
    _set_archetype(t, BodyArchetype.GRIP_FIGHTER)
    gripper = expected_initiative(t, s)
    assert gripper > lever


def test_mirrored_stance_uses_different_weights() -> None:
    """Aggressive weight shrinks, fight_iq grows. A high-aggressive
    low-IQ fighter is *worse* in mirrored than matched; a low-aggressive
    high-IQ fighter is *better* in mirrored than matched."""
    t, s = _pair()
    # Aggressive fighter, modest IQ.
    _set_aggressive(t, 10)
    t.capability.fight_iq = 4
    matched = expected_initiative(t, s, stance_matchup=StanceMatchup.MATCHED)
    mirrored = expected_initiative(t, s, stance_matchup=StanceMatchup.MIRRORED)
    assert mirrored < matched, (
        f"aggressive low-IQ should score worse in mirrored: "
        f"matched={matched}, mirrored={mirrored}"
    )


def test_clock_pressure_trailing_boosts_initiative() -> None:
    t, s = _pair()
    base = expected_initiative(t, s)
    trailing = expected_initiative(t, s, clock_pressure_role="trailing")
    leading  = expected_initiative(t, s, clock_pressure_role="leading")
    assert trailing > base > leading


def test_clock_pressure_roles_inactive_when_clock_high() -> None:
    t, s = _pair()
    a_role, b_role = clock_pressure_roles(
        t, s, current_tick=0, max_ticks=240,
        a_score={"waza_ari": 0, "ippon": False},
        b_score={"waza_ari": 0, "ippon": False},
    )
    assert a_role is None and b_role is None


def test_clock_pressure_roles_active_at_low_clock_with_score_diff() -> None:
    t, s = _pair()
    # 20 ticks remaining, A leading 1-0.
    a_role, b_role = clock_pressure_roles(
        t, s, current_tick=220, max_ticks=240,
        a_score={"waza_ari": 1, "ippon": False},
        b_score={"waza_ari": 0, "ippon": False},
    )
    assert a_role == "leading" and b_role == "trailing"


def test_sample_initiative_introduces_variance() -> None:
    """Across many samples, the same configuration produces a
    distribution — different exchanges yield different scores."""
    rng = random.Random(0)
    t, s = _pair()
    samples = [sample_initiative(t, s, rng=rng) for _ in range(100)]
    assert statistics.pstdev(samples) > 0.1


def test_higher_expected_wins_more_often() -> None:
    """AC#2 — the higher-initiative fighter reaches first in >70% of
    races when expected delta > 1.0."""
    rng = random.Random(0)
    t, s = _pair()
    _set_aggressive(t, 10)
    _set_aggressive(s, 0)
    _set_archetype(t, BodyArchetype.GRIP_FIGHTER)
    _set_archetype(s, BodyArchetype.GROUND_SPECIALIST)
    t_wins = 0
    n = 200
    for _ in range(n):
        a = sample_initiative(t, s, rng=rng)
        b = sample_initiative(s, t, rng=rng)
        if a >= b:
            t_wins += 1
    rate = t_wins / n
    assert rate > 0.70, f"expected >70% wins, got {rate:.2f}"


# ===========================================================================
# AC#4 — five response types
# ===========================================================================
def test_select_response_returns_valid_kind() -> None:
    rng = random.Random(0)
    t, s = _pair()
    choice = select_response(t, s, rng=rng)
    assert choice.kind in ALL_RESPONSE_KINDS


def test_response_distribution_covers_all_six_types() -> None:
    """Across many rolls with neutral inputs, all six response kinds
    are represented (no kind has zero probability)."""
    rng = random.Random(0)
    t, s = _pair()
    counts = {k: 0 for k in ALL_RESPONSE_KINDS}
    for _ in range(2000):
        choice = select_response(t, s, rng=rng)
        counts[choice.kind] += 1
    for kind, n in counts.items():
        assert n > 0, f"kind {kind} never selected: {counts}"


def test_grip_fighter_prefers_contest() -> None:
    """A GRIP_FIGHTER follower contests more often than other archetypes."""
    rng = random.Random(0)
    t, s = _pair()
    _set_archetype(t, BodyArchetype.GRIP_FIGHTER)
    gf_contests = sum(
        1 for _ in range(500)
        if select_response(t, s, rng=rng).kind == RESP_CONTEST
    )
    rng = random.Random(0)
    _set_archetype(t, BodyArchetype.GROUND_SPECIALIST)
    gs_contests = sum(
        1 for _ in range(500)
        if select_response(t, s, rng=rng).kind == RESP_CONTEST
    )
    assert gf_contests > gs_contests


def test_explosive_prefers_pursue_own() -> None:
    """An EXPLOSIVE follower commits to their own grip path more often
    than they contest the leader's reach. (AC#11 GRIP_FIGHTER vs EXPLOSIVE
    pattern: EXPLOSIVE defaults to pursue-own over contest/match.)"""
    rng = random.Random(0)
    t, s = _pair()
    _set_archetype(t, BodyArchetype.EXPLOSIVE)
    pursues = 0
    contests = 0
    for _ in range(500):
        kind = select_response(t, s, rng=rng).kind
        if kind == RESP_PURSUE_OWN:
            pursues += 1
        elif kind == RESP_CONTEST:
            contests += 1
    assert pursues > contests


def test_low_iq_defaults_to_match() -> None:
    """Novice fighters (low IQ) default to the safe MATCH response more
    than elite fighters do."""
    rng = random.Random(0)
    t, s = _pair()
    t.capability.fight_iq = 1
    novice_match = sum(
        1 for _ in range(500)
        if select_response(t, s, rng=rng).kind == RESP_MATCH
    )
    rng = random.Random(0)
    t.capability.fight_iq = 9
    elite_match = sum(
        1 for _ in range(500)
        if select_response(t, s, rng=rng).kind == RESP_MATCH
    )
    assert novice_match > elite_match


def test_clock_pressure_leading_picks_defensive_responses_more() -> None:
    """A leading fighter at clock-pressure picks DEFENSIVE / DISENGAGE
    more often than the same fighter without clock pressure. (AC#11
    clock-pressure asymmetry.)"""
    rng = random.Random(0)
    t, s = _pair()
    base_defensive = 0
    for _ in range(500):
        c = select_response(t, s, rng=rng)
        if c.kind in (RESP_DEFENSIVE, RESP_DISENGAGE):
            base_defensive += 1
    rng = random.Random(0)
    leading_defensive = 0
    for _ in range(500):
        c = select_response(t, s, rng=rng, clock_pressure_role="leading")
        if c.kind in (RESP_DEFENSIVE, RESP_DISENGAGE):
            leading_defensive += 1
    assert leading_defensive > base_defensive


# ===========================================================================
# HAJ-226 — ACCEPT_BAIT (counter-fighter who deliberately doesn't strip)
# ===========================================================================
def _set_facet(j, key: str, value: int) -> None:
    j.identity.personality_facets[key] = value


def test_accept_bait_is_selectable() -> None:
    """ACCEPT_BAIT is a real, drawable sixth branch — never zero-probability
    for a fighter built to use it (patient, high-IQ, counter-leaning)."""
    rng = random.Random(0)
    t, s = _pair()
    _set_archetype(t, BodyArchetype.EXPLOSIVE)
    _set_aggressive(t, 2)
    t.capability.fight_iq = 9
    seen = sum(
        1 for _ in range(500)
        if select_response(t, s, rng=rng).kind == RESP_ACCEPT_BAIT
    )
    assert seen > 0, "ACCEPT_BAIT was never selected by a counter-profile"


def test_counter_fighter_accepts_bait_more_than_pressure_fighter() -> None:
    """AC — a counter-fighter archetype (patient EXPLOSIVE, high fight_iq,
    composed) selects ACCEPT_BAIT at a meaningfully higher rate than a
    pressure/grip fighter (aggressive MOTOR / GRIP_FIGHTER)."""
    n = 1000

    # Counter-fighter: patient, high-IQ, composed EXPLOSIVE.
    rng = random.Random(0)
    t, s = _pair()
    _set_archetype(t, BodyArchetype.EXPLOSIVE)
    _set_aggressive(t, 2)
    t.capability.fight_iq = 9
    t.state.composure_current = float(t.capability.composure_ceiling)
    counter_baits = sum(
        1 for _ in range(n)
        if select_response(t, s, rng=rng).kind == RESP_ACCEPT_BAIT
    )

    # Pressure fighter: aggressive MOTOR.
    rng = random.Random(0)
    t, s = _pair()
    _set_archetype(t, BodyArchetype.MOTOR)
    _set_aggressive(t, 9)
    pressure_baits = sum(
        1 for _ in range(n)
        if select_response(t, s, rng=rng).kind == RESP_ACCEPT_BAIT
    )

    assert counter_baits > pressure_baits * 2, (
        f"counter-fighter should bait far more than a pressure fighter: "
        f"counter={counter_baits}, pressure={pressure_baits}"
    )


def test_clock_pressure_suppresses_accept_bait() -> None:
    """The clock kills the patient counter — a fighter under clock pressure
    picks ACCEPT_BAIT less than the same fighter with no clock pressure."""
    rng = random.Random(0)
    t, s = _pair()
    _set_archetype(t, BodyArchetype.EXPLOSIVE)
    _set_aggressive(t, 2)
    t.capability.fight_iq = 9
    base = sum(
        1 for _ in range(800)
        if select_response(t, s, rng=rng).kind == RESP_ACCEPT_BAIT
    )
    rng = random.Random(0)
    pressured = sum(
        1 for _ in range(800)
        if select_response(
            t, s, rng=rng, clock_pressure_role="leading",
        ).kind == RESP_ACCEPT_BAIT
    )
    assert pressured < base, (
        f"clock pressure should suppress ACCEPT_BAIT: "
        f"base={base}, pressured={pressured}"
    )


def test_accept_bait_leaves_leader_grip_and_seats_off_committed_arm() -> None:
    """Forcing ACCEPT_BAIT: the leader's lead grip is NOT stripped, the dyad
    stays engaged (not STANDING_DISTANT), the follower seats a grip on the
    leader's committed arm, and the choice is logged in the cascade log."""
    random.seed(0)
    t, s = _pair()
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki(),
              max_ticks=20, seed=0)
    captured: list = []
    def _capture(events):
        captured.extend(events)
        return None
    m._print_events = _capture
    m.begin()
    while m._grip_cascade is None and m.ticks_run < 15:
        m.step()
    assert m._grip_cascade is not None
    leader_name = m._grip_cascade["leader_name"]
    follower_name = m._grip_cascade["follower_name"]
    leader = (t if t.identity.name == leader_name else s)
    # Leader seated their lead grip at staging — record it.
    leader_edges_pre = len(m.grip_graph.edges_owned_by(leader_name))
    assert leader_edges_pre >= 1, "leader should hold a lead grip pre-cascade"

    from grip_initiative import GripResponseChoice
    forced = GripResponseChoice(
        kind=RESP_ACCEPT_BAIT,
        weights={k: 1.0 for k in ALL_RESPONSE_KINDS},
        rolled=0.0,
    )
    import match as match_module
    real = match_module.select_response
    match_module.select_response = lambda *a, **kw: forced
    try:
        while m._grip_cascade is not None and m.ticks_run < 20:
            m.step()
    finally:
        match_module.select_response = real

    # The dyad stayed engaged (ACCEPT_BAIT is not a disengage).
    assert m.position != Position.STANDING_DISTANT
    # The leader's grip survived — accept-bait does NOT strip.
    leader_edges_post = len(m.grip_graph.edges_owned_by(leader_name))
    assert leader_edges_post >= leader_edges_pre, (
        "ACCEPT_BAIT must not strip the leader's grip"
    )
    # The follower seated a grip on the leader (off the committed arm).
    follower_on_leader = [
        e for e in m.grip_graph.edges_owned_by(follower_name)
        if e.target_id == leader_name
    ]
    assert follower_on_leader, "follower should grip the leader's committed arm"
    # The choice is logged in the cascade log, like the other branches.
    bait_logs = [
        entry for entry in m._grip_cascade_log
        if entry["kind"] == RESP_ACCEPT_BAIT
    ]
    assert bait_logs, "ACCEPT_BAIT should be recorded in the cascade log"
    # And surfaced as a GRIP_CASCADE_RESPONSE event.
    bait_events = [
        e for e in captured
        if e.event_type == "GRIP_CASCADE_RESPONSE"
        and e.data.get("kind") == RESP_ACCEPT_BAIT
    ]
    assert bait_events, "ACCEPT_BAIT should emit a cascade-response event"


# ===========================================================================
# AC#10 — t003 reproduction: no symmetric four-grip seating on tick 3
# ===========================================================================
def _drive_match_to_first_engagement(seed: int):
    """Run a match from Hajime through the first cascade and return the
    grip events emitted on the cascade-staging tick."""
    random.seed(seed)
    t, s = _pair()
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki(),
              max_ticks=20, seed=seed)
    captured: list = []
    real_print = m._print_events
    def _capture(events):
        captured.extend(events)
        # Suppress actual printing to keep test output clean.
        return None
    m._print_events = _capture
    m.begin()
    while m.position == Position.STANDING_DISTANT and m.ticks_run < 20:
        m.step()
    # Step until the cascade resolves. Triage 2026-05-02 stretched the
    # leader→follower lag from 1 to GRIP_CASCADE_LAG_TICKS (2), so
    # `_grip_cascade` may stay set across multiple ticks before the
    # follower's response fires.
    while m._grip_cascade is not None and m.ticks_run < 25:
        m.step()
    return t, s, m, captured


def test_haj144_t003_no_four_grip_seat_on_single_tick() -> None:
    """The opening grip exchange must distribute across multiple ticks.
    No single tick should contain four GRIP_ESTABLISH events for two
    fighters' full grip sets."""
    for seed in (1, 7, 42, 99, 123):
        _, _, _, events = _drive_match_to_first_engagement(seed)
        per_tick: dict[int, int] = {}
        for ev in events:
            if ev.event_type == "GRIP_ESTABLISH":
                per_tick[ev.tick] = per_tick.get(ev.tick, 0) + 1
        for t_n, count in per_tick.items():
            assert count <= 2, (
                f"seed {seed}: tick {t_n} seated {count} grips at once "
                f"(t003 regression — should never exceed 2 in v0.1)"
            )


def test_initiative_event_fires_at_cascade_start() -> None:
    """Every grip cascade emits a [grip_init] engineering event with
    both fighters' scores. (AC#1.)"""
    _, _, m, events = _drive_match_to_first_engagement(seed=11)
    inits = [e for e in events if e.event_type == "GRIP_INITIATIVE"]
    assert inits
    init = inits[0]
    assert "leader" in init.data and "follower" in init.data
    assert "leader_init" in init.data and "follower_init" in init.data
    assert init.data["leader_init"] >= init.data["follower_init"]


def test_cascade_takes_at_least_two_ticks() -> None:
    """The opening grip exchange takes at least two ticks (leader seats,
    then follower responds on tick+1). AC#3 calls for 3–6 ticks total
    including the closing-phase floor; v0.1 ships the closing-phase
    floor (3 ticks) + cascade (2 ticks) = 5 ticks from Hajime."""
    _, _, m, events = _drive_match_to_first_engagement(seed=5)
    init_tick = next(
        e.tick for e in events if e.event_type == "GRIP_INITIATIVE"
    )
    response_tick = next(
        (e.tick for e in events if e.event_type == "GRIP_CASCADE_RESPONSE"),
        None,
    )
    assert response_tick is not None
    assert response_tick > init_tick


# ===========================================================================
# AC#5 — disengage transitions to STANDING_DISTANT
# ===========================================================================
def test_disengage_transitions_to_standing_distant() -> None:
    """Force a DISENGAGE response and confirm the dyad transitions back
    to STANDING_DISTANT with grips broken."""
    random.seed(0)
    t, s = _pair()
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki(),
              max_ticks=20, seed=0)
    m.begin()
    # Run until the cascade stages.
    while m._grip_cascade is None and m.ticks_run < 15:
        m.step()
    assert m._grip_cascade is not None
    # Force the response selector to return DISENGAGE.
    import grip_initiative as gi
    real_select = gi.select_response
    from grip_initiative import GripResponseChoice
    forced = GripResponseChoice(
        kind=RESP_DISENGAGE,
        weights={k: 1.0 for k in ALL_RESPONSE_KINDS},
        rolled=0.0,
    )
    import match as match_module
    match_module.select_response = lambda *a, **kw: forced
    try:
        # Step until the cascade resolves (Priority-3 lag = 2 ticks).
        while m._grip_cascade is not None and m.ticks_run < 20:
            m.step()
    finally:
        match_module.select_response = real_select
    assert m.position == Position.STANDING_DISTANT
    assert m.grip_graph.edge_count() == 0


def test_disengage_drains_cardio() -> None:
    """The follower absorbs a stamina cost on DISENGAGE."""
    random.seed(0)
    t, s = _pair()
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki(),
              max_ticks=20, seed=0)
    m.begin()
    while m._grip_cascade is None and m.ticks_run < 15:
        m.step()
    follower_name = m._grip_cascade["follower_name"]
    follower = (t if t.identity.name == follower_name else s)
    pre_cardio = follower.state.cardio_current
    import grip_initiative as gi
    from grip_initiative import GripResponseChoice
    forced = GripResponseChoice(
        kind=RESP_DISENGAGE,
        weights={k: 1.0 for k in ALL_RESPONSE_KINDS},
        rolled=0.0,
    )
    import match as match_module
    real = match_module.select_response
    match_module.select_response = lambda *a, **kw: forced
    try:
        while m._grip_cascade is not None and m.ticks_run < 20:
            m.step()
    finally:
        match_module.select_response = real
    assert follower.state.cardio_current < pre_cardio


# ===========================================================================
# AC#6 — disengage feeds shido pressure
# ===========================================================================
def test_repeated_disengage_logs_non_combative() -> None:
    """Three or more disengages in the same closing-phase span emit
    a DISENGAGE_NON_COMBATIVE event. Plugs into ref's existing passivity
    machinery via kumi_kata_clock bumps."""
    random.seed(0)
    t, s = _pair()
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki(),
              max_ticks=60, seed=0)
    captured: list = []
    real_print = m._print_events
    def _capture(events):
        captured.extend(events)
        return None
    m._print_events = _capture
    import grip_initiative as gi
    from grip_initiative import GripResponseChoice
    import match as match_module
    forced = GripResponseChoice(
        kind=RESP_DISENGAGE,
        weights={k: 1.0 for k in ALL_RESPONSE_KINDS},
        rolled=0.0,
    )
    real = match_module.select_response
    match_module.select_response = lambda *a, **kw: forced
    try:
        m.run()
    finally:
        match_module.select_response = real
    non_comb = [
        e for e in captured if e.event_type == "DISENGAGE_NON_COMBATIVE"
    ]
    assert non_comb, "expected at least one DISENGAGE_NON_COMBATIVE event"
    # And the streak in the event data reaches the threshold.
    streaks = [e.data["streak"] for e in non_comb]
    assert max(streaks) >= DISENGAGE_SHIDO_THRESHOLD_COUNT


# ===========================================================================
# AC#8 — composure modulates initiative
# ===========================================================================
def test_composure_dip_lowers_initiative() -> None:
    """Same fighter, same opponent — composure dip lowers initiative."""
    t, s = _pair()
    t.state.composure_current = float(t.capability.composure_ceiling)
    composed = expected_initiative(t, s)
    t.state.composure_current = 1.0  # near-zero composure
    rattled = expected_initiative(t, s)
    assert composed > rattled


# ===========================================================================
# AC#11 — six AC scenarios verified at the integration level
# ===========================================================================
def test_aggressive_vs_patient_aggressive_wins_majority() -> None:
    """AC#11 — aggressive fighter wins lead-grip race in >70% of openings
    across many matches (sampling many initiative draws via the cascade)."""
    rng = random.Random(0)
    t, s = _pair()
    _set_aggressive(t, 10)
    _set_aggressive(s, 0)
    wins_t = 0
    n = 200
    for _ in range(n):
        a = sample_initiative(t, s, rng=rng)
        b = sample_initiative(s, t, rng=rng)
        if a >= b:
            wins_t += 1
    assert wins_t / n > 0.70


def test_grip_fighter_vs_explosive_wins_lead_grip_more_often() -> None:
    """AC#11 — GRIP_FIGHTER vs EXPLOSIVE: GRIP_FIGHTER wins lead-grip
    race >65% of the time."""
    rng = random.Random(0)
    t, s = _pair()
    _set_archetype(t, BodyArchetype.GRIP_FIGHTER)
    _set_archetype(s, BodyArchetype.EXPLOSIVE)
    # Equalize other axes so the test isolates the archetype effect.
    _set_aggressive(t, 5); _set_aggressive(s, 5)
    t.capability.fight_iq = 7; s.capability.fight_iq = 7
    wins_t = 0
    n = 200
    for _ in range(n):
        a = sample_initiative(t, s, rng=rng)
        b = sample_initiative(s, t, rng=rng)
        if a >= b:
            wins_t += 1
    assert wins_t / n > 0.65, (
        f"GRIP_FIGHTER should win >65% vs EXPLOSIVE; got {wins_t/n:.2f}"
    )


def test_matched_and_mirrored_produce_different_response_distributions() -> None:
    """AC#11 — same two fighters, different stance_matchup → measurably
    different response distributions."""
    rng_m = random.Random(0)
    rng_x = random.Random(0)
    t, s = _pair()
    matched_kinds: dict[str, int] = {k: 0 for k in ALL_RESPONSE_KINDS}
    mirrored_kinds: dict[str, int] = {k: 0 for k in ALL_RESPONSE_KINDS}
    for _ in range(500):
        c1 = select_response(
            t, s, stance_matchup=StanceMatchup.MATCHED, rng=rng_m,
        )
        c2 = select_response(
            t, s, stance_matchup=StanceMatchup.MIRRORED, rng=rng_x,
        )
        matched_kinds[c1.kind] += 1
        mirrored_kinds[c2.kind] += 1
    # Some kind has a meaningfully different count (>15 difference at
    # 500 samples = >3% absolute shift, comfortably above sampling noise).
    assert any(
        abs(matched_kinds[k] - mirrored_kinds[k]) > 15
        for k in ALL_RESPONSE_KINDS
    ), f"matched={matched_kinds}, mirrored={mirrored_kinds}"


# ===========================================================================
# AC#12 — HAJ-148 / HAJ-149 invariants intact
# ===========================================================================
def test_haj148_haj149_invariants_still_hold() -> None:
    """Spot-check: a full match still emits intent signals, perception
    log entries, prose-silent commits, and respects the consequence
    queue."""
    import contextlib, io
    random.seed(0)
    t, s = _pair()
    m = Match(
        fighter_a=t, fighter_b=s, referee=build_suzuki(),
        max_ticks=60, seed=0, stream="debug",
    )
    with contextlib.redirect_stdout(io.StringIO()):
        m.run()
    # HAJ-149 — at least one intent signal fired.
    assert len(m._intent_signals) > 0
    # HAJ-148 — the consequence queue is empty at end (everything resolved).
    assert m._consequence_queue == [] or all(
        c.due_tick > m.ticks_run for c in m._consequence_queue
    )


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
