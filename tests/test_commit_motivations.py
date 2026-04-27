# tests/test_commit_motivations.py
# HAJ-67 — four non-scoring commit motivations, each firing in isolation.
#
# Builds on HAJ-49 / HAJ-50 (test_false_attack.py). CLOCK_RESET coverage
# lives there; this file covers the three new motivations:
#
#   - GRIP_ESCAPE         — opponent dominant grips + own grips compromised + low composure
#   - SHIDO_FARMING       — opp passive clock high + no scoring opp + style tolerance
#   - STAMINA_DESPERATION — cardio low + shido taken + cannot drive force
#
# Plus meta-coverage:
#   - CommitMotivation enum has exactly four values
#   - Each motivation renders its own compact narration on failure
#   - The dispatcher respects priority order (CLOCK_RESET first)
#   - THROW_ENTRY.data carries the motivation enum name

from __future__ import annotations
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from action_selection import (
    _should_fire_clock_reset, _should_fire_grip_escape,
    _should_fire_shido_farming, _should_fire_stamina_desperation,
    _select_non_scoring_motivation, select_actions,
    FALSE_ATTACK_TENDENCY_KEY, SHIDO_FARMING_TENDENCY_KEY,
    GRIP_ESCAPE_DELTA_THRESHOLD, GRIP_ESCAPE_COMPOSURE_FRAC,
    SHIDO_FARMING_OPP_CLOCK,
    STAMINA_DESPERATION_CARDIO_MAX, STAMINA_DESPERATION_HAND_FAT_MIN,
    REASON_INTENTIONAL_FALSE_ATTACK,
)
from actions import ActionKind, commit_throw
from body_state import place_judoka
from commit_motivation import (
    CommitMotivation, DEBUG_TAGS, COMPACT_NARRATION, narration_for,
)
from enums import (
    BodyArchetype, BeltRank, BodyPart, DominantSide,
    GripDepth, GripMode, GripTarget, GripTypeV2,
)
from grip_graph import GripGraph, GripEdge
from judoka import Capability, Identity, Judoka, State
from throw_templates import FailureOutcome
from throws import ThrowID


# ---------------------------------------------------------------------------
# FIXTURES — tunable judoka that isolates one motivation at a time.
# ---------------------------------------------------------------------------
def _judoka(
    *, name: str = "Gaba", fight_iq: int = 7,
    cardio_current: float = 1.0, shidos: int = 0,
    composure_current: float | None = None,
    hand_fatigue: float = 0.0,
    style_dna: dict[str, float] | None = None,
    vocab: list[ThrowID] | None = None,
) -> Judoka:
    if vocab is None:
        vocab = [ThrowID.TAI_OTOSHI, ThrowID.KO_UCHI_GARI]
    ident = Identity(
        name=name, age=25, weight_class="-81kg", height_cm=178,
        body_archetype=BodyArchetype.GRIP_FIGHTER,
        belt_rank=BeltRank.BLACK_1, dominant_side=DominantSide.RIGHT,
        personality_facets={"aggressive": 5, "technical": 6,
                            "confident": 6, "loyal_to_plan": 5},
        arm_reach_cm=185, hip_height_cm=98, nationality="French",
        style_dna=style_dna or {},
    )
    cap = Capability(
        right_hand=8, left_hand=7, right_forearm=8, left_forearm=7,
        right_bicep=7, left_bicep=7, right_shoulder=7, left_shoulder=7,
        right_leg=8, left_leg=8, right_foot=7, left_foot=7,
        core=8, lower_back=7, neck=7,
        cardio_capacity=7, cardio_efficiency=7, composure_ceiling=8,
        fight_iq=fight_iq, ne_waza_skill=5,
        right_hip=7, left_hip=7, right_thigh=7, left_thigh=7,
        right_knee=6, left_knee=6, right_wrist=7, left_wrist=7, head=5,
        throw_vocabulary=list(vocab),
        throw_profiles={},
        signature_throws=[vocab[0]],
        signature_combos=[],
    )
    st = State.fresh(cap, ident)
    st.cardio_current = cardio_current
    st.shidos = shidos
    if composure_current is not None:
        st.composure_current = composure_current
    # Apply hand fatigue to both hands (drives _avg_hand_fatigue).
    st.body["right_hand"].fatigue = hand_fatigue
    st.body["left_hand"].fatigue = hand_fatigue
    return Judoka(identity=ident, capability=cap, state=st)


def _placed_pair(tori: Judoka, uke: Judoka) -> None:
    place_judoka(tori, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(uke,  com_position=(+0.5, 0.0), facing=(-1.0, 0.0))


def _tori_pocket_grips(graph: GripGraph, tori: Judoka, uke: Judoka) -> None:
    """Tori has POCKET-depth grips only — grip integrity is compromised
    but the engagement precondition (some owned edge) is satisfied."""
    graph.add_edge(GripEdge(
        grasper_id=tori.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=uke.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.POCKET,
        strength=0.4, established_tick=0, mode=GripMode.CONNECTIVE,
    ))


def _uke_deep_grips(graph: GripGraph, tori: Judoka, uke: Judoka) -> None:
    """Uke has DEEP grips on tori — grip delta favors uke."""
    graph.add_edge(GripEdge(
        grasper_id=uke.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=tori.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.DEEP,
        strength=1.0, established_tick=0, mode=GripMode.DRIVING,
    ))
    graph.add_edge(GripEdge(
        grasper_id=uke.identity.name, grasper_part=BodyPart.LEFT_HAND,
        target_id=tori.identity.name, target_location=GripTarget.RIGHT_SLEEVE,
        grip_type_v2=GripTypeV2.SLEEVE_HIGH, depth_level=GripDepth.DEEP,
        strength=1.0, established_tick=0, mode=GripMode.DRIVING,
    ))


def _standard_grips(graph: GripGraph, tori: Judoka, uke: Judoka) -> None:
    """Tori has a clean set of STANDARD grips — the engagement
    precondition is satisfied without the GRIP_ESCAPE gate firing."""
    graph.add_edge(GripEdge(
        grasper_id=tori.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=uke.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.STANDARD,
        strength=0.8, established_tick=0, mode=GripMode.CONNECTIVE,
    ))
    graph.add_edge(GripEdge(
        grasper_id=tori.identity.name, grasper_part=BodyPart.LEFT_HAND,
        target_id=uke.identity.name, target_location=GripTarget.RIGHT_SLEEVE,
        grip_type_v2=GripTypeV2.SLEEVE_HIGH, depth_level=GripDepth.STANDARD,
        strength=0.8, established_tick=0, mode=GripMode.CONNECTIVE,
    ))


# ===========================================================================
# Enum + prose metadata
# ===========================================================================
def test_commit_motivation_has_four_members() -> None:
    """The enum carries exactly the four motivations the ticket lists."""
    names = {m.name for m in CommitMotivation}
    assert names == {
        "CLOCK_RESET", "GRIP_ESCAPE",
        "SHIDO_FARMING", "STAMINA_DESPERATION",
    }


def test_every_motivation_has_debug_tag_and_narration() -> None:
    """No silent fall-throughs — each motivation must supply its own
    debug tag string and compact narration template."""
    for m in CommitMotivation:
        assert m in DEBUG_TAGS
        assert m in COMPACT_NARRATION
        # Narration template must carry both placeholders.
        template = COMPACT_NARRATION[m]
        assert "{tori}" in template
        assert "{throw}" in template


def test_narration_for_renders_placeholders() -> None:
    """narration_for substitutes tori + throw names."""
    line = narration_for(CommitMotivation.CLOCK_RESET, "Gaba", "Tai-otoshi")
    assert "Gaba" in line
    assert "Tai-otoshi" in line


# ===========================================================================
# GRIP_ESCAPE — in isolation
# ===========================================================================
def test_grip_escape_happy_path_without_probability_roll() -> None:
    """Opp grip-delta above threshold + own grips pocket-only + composure
    below the escape threshold → the gate passes. `rng=None` skips the
    probability roll so we're testing the hard conjuncts."""
    tori = _judoka(composure_current=4.0)   # 4/8 = 0.50 — just below
    uke  = _judoka(name="Kyo")
    _placed_pair(tori, uke)
    g = GripGraph()
    _tori_pocket_grips(g, tori, uke)
    _uke_deep_grips(g, tori, uke)
    # Composure just below the 0.55 threshold.
    tori.state.composure_current = 4.2   # 4.2/8 = 0.525
    assert _should_fire_grip_escape(tori, uke, g, rng=None) is True


def test_grip_escape_rejects_when_own_grips_standard() -> None:
    """Tori's grips are STANDARD — integrity is NOT compromised, so
    there's nothing to escape from. Even with opponent dominance +
    low composure the gate must refuse."""
    tori = _judoka(composure_current=4.0)
    uke  = _judoka(name="Kyo")
    _placed_pair(tori, uke)
    g = GripGraph()
    _standard_grips(g, tori, uke)
    _uke_deep_grips(g, tori, uke)
    assert _should_fire_grip_escape(tori, uke, g, rng=None) is False


def test_grip_escape_rejects_when_composure_high() -> None:
    """A composed fighter doesn't panic-break contact. Even with opponent
    dominance + pocket grips, high composure blocks the gate."""
    tori = _judoka(composure_current=8.0)   # 8/8 = 1.0
    uke  = _judoka(name="Kyo")
    _placed_pair(tori, uke)
    g = GripGraph()
    _tori_pocket_grips(g, tori, uke)
    _uke_deep_grips(g, tori, uke)
    assert _should_fire_grip_escape(tori, uke, g, rng=None) is False


def test_grip_escape_rejects_when_opp_not_dominant() -> None:
    """Opponent has no grips — no grip war to lose, no reason to escape."""
    tori = _judoka(composure_current=3.0)
    uke  = _judoka(name="Kyo")
    _placed_pair(tori, uke)
    g = GripGraph()
    _tori_pocket_grips(g, tori, uke)   # only tori's grips exist
    assert _should_fire_grip_escape(tori, uke, g, rng=None) is False


# ===========================================================================
# SHIDO_FARMING — in isolation
# ===========================================================================
def test_shido_farming_happy_path_without_probability_roll() -> None:
    """Opp passive clock above threshold + no strong scoring opp + style
    tolerance → gate passes."""
    tori = _judoka(style_dna={SHIDO_FARMING_TENDENCY_KEY: 0.70})
    assert _should_fire_shido_farming(
        tori, opponent_kumi_kata_clock=20,
        perceived_by_throw={ThrowID.TAI_OTOSHI: 0.20},
        rng=None,
    ) is True


def test_shido_farming_rejects_when_opp_not_passive() -> None:
    tori = _judoka(style_dna={SHIDO_FARMING_TENDENCY_KEY: 0.70})
    # Opp kumi-kata clock below the threshold — uke hasn't been passive.
    assert _should_fire_shido_farming(
        tori, opponent_kumi_kata_clock=SHIDO_FARMING_OPP_CLOCK - 1,
        perceived_by_throw={ThrowID.TAI_OTOSHI: 0.20},
        rng=None,
    ) is False


def test_shido_farming_rejects_when_scoring_opportunity_exists() -> None:
    """If tori has a throw nearly clearing the commit threshold, they
    commit normally — farming a shido is the tactic of last resort when
    no real opportunity exists."""
    tori = _judoka(style_dna={SHIDO_FARMING_TENDENCY_KEY: 0.70})
    assert _should_fire_shido_farming(
        tori, opponent_kumi_kata_clock=20,
        perceived_by_throw={ThrowID.TAI_OTOSHI: 0.60},   # strong signature
        rng=None,
    ) is False


def test_shido_farming_rejects_low_style_tendency() -> None:
    """Classical-Kodokan judoka with no appetite for grinding the
    referee: gate stays shut."""
    tori = _judoka(style_dna={SHIDO_FARMING_TENDENCY_KEY: 0.20})
    assert _should_fire_shido_farming(
        tori, opponent_kumi_kata_clock=20,
        perceived_by_throw={ThrowID.TAI_OTOSHI: 0.20},
        rng=None,
    ) is False


# ===========================================================================
# STAMINA_DESPERATION — in isolation
# ===========================================================================
def test_stamina_desperation_happy_path_without_probability_roll() -> None:
    """Cardio low + shido taken + high hand fatigue → gate passes."""
    tori = _judoka(
        cardio_current=0.20, shidos=1, hand_fatigue=0.75,
    )
    assert _should_fire_stamina_desperation(tori, rng=None) is True


def test_stamina_desperation_rejects_when_cardio_high() -> None:
    tori = _judoka(
        cardio_current=STAMINA_DESPERATION_CARDIO_MAX + 0.10,
        shidos=1, hand_fatigue=0.75,
    )
    assert _should_fire_stamina_desperation(tori, rng=None) is False


def test_stamina_desperation_rejects_without_shido() -> None:
    """No prior penalty — tori doesn't need this tactic yet."""
    tori = _judoka(cardio_current=0.20, shidos=0, hand_fatigue=0.75)
    assert _should_fire_stamina_desperation(tori, rng=None) is False


def test_stamina_desperation_rejects_when_can_drive_force() -> None:
    """Hand fatigue below threshold — tori can still generate force, so
    the 'can't make kuzushi' precondition is not met."""
    tori = _judoka(
        cardio_current=0.20, shidos=1,
        hand_fatigue=STAMINA_DESPERATION_HAND_FAT_MIN - 0.10,
    )
    assert _should_fire_stamina_desperation(tori, rng=None) is False


# ===========================================================================
# Dispatcher priority — CLOCK_RESET wins when multiple gates would fire
# ===========================================================================
def test_dispatcher_priority_clock_reset_wins_over_others() -> None:
    """Construct a fighter for whom multiple motivations would independently
    fire. The dispatcher must pick CLOCK_RESET first (highest priority)."""
    # Clock in the CLOCK_RESET window + high tendency for BOTH motivations +
    # passive opponent + composure high so GRIP_ESCAPE is blocked by
    # composure, leaving CLOCK_RESET and SHIDO_FARMING both eligible.
    tori = _judoka(
        composure_current=8.0,
        style_dna={
            FALSE_ATTACK_TENDENCY_KEY: 0.80,
            SHIDO_FARMING_TENDENCY_KEY: 0.80,
        },
    )
    uke = _judoka(name="Kyo")
    _placed_pair(tori, uke)
    g = GripGraph()
    _standard_grips(g, tori, uke)
    # rng seed known to pass the CLOCK_RESET probability roll first.
    result = _select_non_scoring_motivation(
        tori, uke, g, random.Random(31),
        kumi_kata_clock=20, opponent_kumi_kata_clock=20,
        perceived_by_throw={ThrowID.TAI_OTOSHI: 0.10},
    )
    assert result == CommitMotivation.CLOCK_RESET


# ===========================================================================
# End-to-end — motivation surfaces on the failure line via the compact prose
# ===========================================================================
def _build_match(tori, uke):
    from match import Match
    from referee import build_suzuki
    from enums import Position
    m = Match(
        fighter_a=tori, fighter_b=uke, referee=build_suzuki(),
        stream="debug", seed=1,
    )
    # HAJ-141 — these tests poke _resolve_commit_throw and _resolve_failed_commit
    # directly to verify motivation tagging; bypass the engagement-distance gate
    # by flipping out of STANDING_DISTANT (production flow does the same the
    # tick first edges seat).
    m.position = Position.GRIPPING
    return m


def test_grip_escape_renders_grip_escape_prose() -> None:
    tori = _judoka(name="Gaba")
    uke  = _judoka(name="Kyo")
    _placed_pair(tori, uke)
    m = _build_match(tori, uke)
    m._commit_motivation[tori.identity.name] = CommitMotivation.GRIP_ESCAPE
    events = m._resolve_failed_commit(
        tori, uke, ThrowID.TAI_OTOSHI, "Tai-otoshi", net=-1.0, tick=20,
    )
    failed = next(e for e in events if e.event_type == "FAILED")
    assert "breaks contact" in failed.description
    assert failed.data["outcome"] == FailureOutcome.TACTICAL_DROP_RESET.name
    assert failed.data["commit_motivation"] == CommitMotivation.GRIP_ESCAPE.name


def test_shido_farming_renders_shido_farming_prose() -> None:
    tori = _judoka(name="Gaba")
    uke  = _judoka(name="Kyo")
    _placed_pair(tori, uke)
    m = _build_match(tori, uke)
    m._commit_motivation[tori.identity.name] = CommitMotivation.SHIDO_FARMING
    events = m._resolve_failed_commit(
        tori, uke, ThrowID.TAI_OTOSHI, "Tai-otoshi", net=-1.0, tick=20,
    )
    failed = next(e for e in events if e.event_type == "FAILED")
    assert "poses an attack" in failed.description
    assert failed.data["commit_motivation"] == CommitMotivation.SHIDO_FARMING.name


def test_stamina_desperation_renders_stamina_prose() -> None:
    tori = _judoka(name="Gaba")
    uke  = _judoka(name="Kyo")
    _placed_pair(tori, uke)
    m = _build_match(tori, uke)
    m._commit_motivation[tori.identity.name] = CommitMotivation.STAMINA_DESPERATION
    events = m._resolve_failed_commit(
        tori, uke, ThrowID.TAI_OTOSHI, "Tai-otoshi", net=-1.0, tick=20,
    )
    failed = next(e for e in events if e.event_type == "FAILED")
    assert "Out of gas" in failed.description
    assert failed.data["commit_motivation"] == CommitMotivation.STAMINA_DESPERATION.name


def test_clock_reset_still_renders_legacy_haj49_prose() -> None:
    """HAJ-49's CLOCK_RESET narration should continue to produce the
    same compact register that HAJ-50 introduced."""
    tori = _judoka(name="Gaba")
    uke  = _judoka(name="Kyo")
    _placed_pair(tori, uke)
    m = _build_match(tori, uke)
    m._commit_motivation[tori.identity.name] = CommitMotivation.CLOCK_RESET
    events = m._resolve_failed_commit(
        tori, uke, ThrowID.TAI_OTOSHI, "Tai-otoshi", net=-1.0, tick=20,
    )
    failed = next(e for e in events if e.event_type == "FAILED")
    assert "Nothing there" in failed.description
    assert "Back up" in failed.description


# ===========================================================================
# THROW_ENTRY carries the motivation on the data dict
# ===========================================================================
def test_throw_entry_data_carries_motivation_enum_name() -> None:
    tori = _judoka(name="Gaba")
    uke  = _judoka(name="Kyo")
    _placed_pair(tori, uke)
    m = _build_match(tori, uke)
    for motivation in CommitMotivation:
        evts = m._resolve_commit_throw(
            tori, uke, ThrowID.TAI_OTOSHI, tick=10,
            commit_motivation=motivation,
            gate_bypass_reason=REASON_INTENTIONAL_FALSE_ATTACK,
            gate_bypass_kind="false_attack",
        )
        entry = next(e for e in evts if e.event_type == "THROW_ENTRY")
        assert entry.data["commit_motivation"] == motivation.name
        # And the tag appears in the description for readers.
        assert DEBUG_TAGS[motivation] in entry.description
        # Reset the motivation snapshot for the next iteration since
        # _resolve_commit_throw sets it each time.
        m._commit_motivation.pop(tori.identity.name, None)


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
                print(f"PASS  {name}")
                passed += 1
            except Exception:
                print(f"FAIL  {name}")
                traceback.print_exc()
                failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
