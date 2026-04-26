# tests/test_false_attack.py
# HAJ-49 — intentional false attack as a distinct commit motivation.
#
# The false-attack pathway fires when:
#   - The normal-signature pathway has nothing to commit to
#   - Offensive desperation is not firing
#   - The kumi-kata clock is in the [18, 29) pre-shido zone
#   - The judoka's fight_iq is ≥ FALSE_ATTACK_MIN_FIGHT_IQ (whites panic)
#   - style_dna["false_attack_tendency"] ≥ FALSE_ATTACK_TENDENCY_THRESHOLD
#
# These tests cover:
#   - The Action.intentional_false_attack flag + commit_throw constructor
#   - _should_fire_false_attack predicate — each gate, independently
#   - _select_false_attack_throw prefers drop variants in priority order
#   - action_selection returns a flagged commit when the gate passes
#   - The commit log line shows "intentional false attack; clock reset"
#   - A failed intentional false attack routes to TACTICAL_DROP_RESET
#     (2-tick recovery; NOT TORI_ON_BOTH_KNEES_UKE_STANDING)
#   - A STUFFED result on a false attack is re-routed through the failure
#     path (no ne-waza window, no -0.30 composure hit)

from __future__ import annotations
import io
import os
import random
import re
import sys
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from action_selection import (
    _should_fire_clock_reset, _select_false_attack_throw,
    select_actions,
    FALSE_ATTACK_CLOCK_MIN, FALSE_ATTACK_CLOCK_MAX,
    FALSE_ATTACK_MIN_FIGHT_IQ, FALSE_ATTACK_TENDENCY_KEY,
    FALSE_ATTACK_TENDENCY_THRESHOLD, FALSE_ATTACK_PREFERENCES,
    REASON_INTENTIONAL_FALSE_ATTACK, COMMIT_THRESHOLD,
)
# HAJ-49 tests renamed _should_fire_false_attack → _should_fire_clock_reset
# under HAJ-67's motivation refactor. The predicate is the same: CLOCK_RESET
# is the original HAJ-49 motivation. Alias so existing test bodies keep
# reading cleanly without rewrites.
_should_fire_false_attack = _should_fire_clock_reset
from actions import Action, ActionKind, commit_throw
from commit_motivation import CommitMotivation
from body_state import place_judoka
from enums import (
    BodyArchetype, BeltRank, BodyPart, DominantSide,
    GripDepth, GripMode, GripTarget, GripTypeV2,
)
from failure_resolution import RECOVERY_TICKS_BY_OUTCOME
from grip_graph import GripGraph, GripEdge
from judoka import Capability, Identity, Judoka, State
from throw_templates import FailureOutcome
from throws import ThrowID
import main as main_module


# ---------------------------------------------------------------------------
# FIXTURES
# ---------------------------------------------------------------------------
def _composed_judoka(
    *, fight_iq: int = 7, tendency: float = 0.70,
    vocab: list[ThrowID] | None = None, name: str = "Gaba",
) -> Judoka:
    """Shodan-ish athlete with a drop vocabulary and tunable style_dna."""
    if vocab is None:
        vocab = [ThrowID.TAI_OTOSHI, ThrowID.KO_UCHI_GARI,
                 ThrowID.SEOI_NAGE, ThrowID.O_UCHI_GARI]
    ident = Identity(
        name=name, age=25, weight_class="-81kg", height_cm=178,
        body_archetype=BodyArchetype.GRIP_FIGHTER,
        belt_rank=BeltRank.BLACK_1, dominant_side=DominantSide.RIGHT,
        personality_facets={"aggressive": 5, "technical": 6,
                            "confident": 6, "loyal_to_plan": 5},
        arm_reach_cm=185, hip_height_cm=98, nationality="French",
        style_dna={FALSE_ATTACK_TENDENCY_KEY: tendency},
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
    return Judoka(identity=ident, capability=cap,
                  state=State.fresh(cap, ident))


def _gripped_graph(tori: Judoka, uke: Judoka) -> GripGraph:
    """Baseline grip configuration: both hands engaged, STANDARD depth,
    so _try_commit's engagement precondition is satisfied."""
    g = GripGraph()
    g.add_edge(GripEdge(
        grasper_id=tori.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=uke.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.STANDARD,
        strength=0.8, established_tick=0, mode=GripMode.CONNECTIVE,
    ))
    g.add_edge(GripEdge(
        grasper_id=tori.identity.name, grasper_part=BodyPart.LEFT_HAND,
        target_id=uke.identity.name, target_location=GripTarget.RIGHT_SLEEVE,
        grip_type_v2=GripTypeV2.SLEEVE_HIGH, depth_level=GripDepth.STANDARD,
        strength=0.8, established_tick=0, mode=GripMode.CONNECTIVE,
    ))
    return g


# ---------------------------------------------------------------------------
# Action flag plumbing
# ---------------------------------------------------------------------------
def test_action_intentional_false_attack_defaults_false() -> None:
    a = commit_throw(ThrowID.TAI_OTOSHI)
    assert a.intentional_false_attack is False


def test_action_intentional_false_attack_carries_through_commit_throw() -> None:
    # HAJ-67 — the bool flag became a CommitMotivation enum; the shim
    # property `intentional_false_attack` returns True iff motivation is
    # non-None. Verify both the enum and the shim.
    a = commit_throw(
        ThrowID.TAI_OTOSHI,
        commit_motivation=CommitMotivation.CLOCK_RESET,
        gate_bypass_reason=REASON_INTENTIONAL_FALSE_ATTACK,
        gate_bypass_kind="false_attack",
    )
    assert a.kind == ActionKind.COMMIT_THROW
    assert a.commit_motivation == CommitMotivation.CLOCK_RESET
    assert a.intentional_false_attack is True
    assert a.gate_bypass_reason == REASON_INTENTIONAL_FALSE_ATTACK


# ---------------------------------------------------------------------------
# _should_fire_false_attack — each gate in isolation
# ---------------------------------------------------------------------------
def test_should_fire_false_attack_happy_path() -> None:
    j = _composed_judoka()
    assert _should_fire_false_attack(j, kumi_kata_clock=20) is True


def test_should_fire_false_attack_rejects_clock_below_min() -> None:
    j = _composed_judoka()
    assert _should_fire_false_attack(j, FALSE_ATTACK_CLOCK_MIN - 1) is False
    assert _should_fire_false_attack(j, 0) is False


def test_should_fire_false_attack_rejects_clock_at_or_above_max() -> None:
    """At FALSE_ATTACK_CLOCK_MAX, imminent-shido desperation takes over."""
    j = _composed_judoka()
    assert _should_fire_false_attack(j, FALSE_ATTACK_CLOCK_MAX) is False
    assert _should_fire_false_attack(j, FALSE_ATTACK_CLOCK_MAX + 1) is False


def test_should_fire_false_attack_rejects_low_fight_iq() -> None:
    j = _composed_judoka(fight_iq=FALSE_ATTACK_MIN_FIGHT_IQ - 1)
    assert _should_fire_false_attack(j, kumi_kata_clock=20) is False


def test_should_fire_false_attack_rejects_low_tendency() -> None:
    """Classical Kodokan-style judoka with a low style_dna tendency —
    the tactical fake isn't part of their kata. They wait for real kuzushi
    or eat the shido."""
    j = _composed_judoka(tendency=FALSE_ATTACK_TENDENCY_THRESHOLD - 0.05)
    assert _should_fire_false_attack(j, kumi_kata_clock=20) is False


def test_should_fire_false_attack_default_tendency_fires_at_neutral() -> None:
    """Missing style_dna key should default to neutral — which is above the
    threshold, so a generic judoka still fires in the pre-shido zone."""
    j = _composed_judoka(tendency=0.60)
    # Wipe the key and confirm the defaulting path still passes.
    j.identity.style_dna.clear()
    assert _should_fire_false_attack(j, kumi_kata_clock=20) is True


def test_no_drop_vocabulary_blocks_motivation_dispatch() -> None:
    """A fighter whose vocabulary contains none of the drop-variant
    preferences can't fake — the upstream dispatcher
    `_select_non_scoring_motivation` short-circuits on the vocab check
    before any predicate runs. Use the dispatcher directly (the
    CLOCK_RESET predicate itself no longer checks vocab under HAJ-67 —
    it moved up to the dispatcher level since all four motivations
    share the same vocab requirement)."""
    from action_selection import _select_non_scoring_motivation
    tori = _composed_judoka(vocab=[ThrowID.UCHI_MATA, ThrowID.HARAI_GOSHI])
    uke  = _composed_judoka(name="uke")
    place_judoka(tori, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(uke,  com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    g = _gripped_graph(tori, uke)
    result = _select_non_scoring_motivation(
        tori, uke, g, random.Random(1),
        kumi_kata_clock=20, opponent_kumi_kata_clock=0,
        perceived_by_throw={},
    )
    assert result is None


# ---------------------------------------------------------------------------
# _select_false_attack_throw — priority order
# ---------------------------------------------------------------------------
def test_select_false_attack_respects_preference_priority() -> None:
    """With all preferred drop variants in vocabulary, the helper picks
    TAI_OTOSHI first — the most-preferred shin-block entry."""
    tori = _composed_judoka()
    uke  = _composed_judoka(name="uke")
    g = _gripped_graph(tori, uke)
    pick = _select_false_attack_throw(tori, g)
    assert pick == FALSE_ATTACK_PREFERENCES[0]
    assert pick == ThrowID.TAI_OTOSHI


def test_select_false_attack_falls_through_to_next_preference() -> None:
    """Without TAI_OTOSHI in vocabulary, the next-preferred (KO_UCHI_GARI)
    is chosen."""
    tori = _composed_judoka(vocab=[ThrowID.KO_UCHI_GARI, ThrowID.SEOI_NAGE])
    uke  = _composed_judoka(name="uke")
    g = _gripped_graph(tori, uke)
    assert _select_false_attack_throw(tori, g) == ThrowID.KO_UCHI_GARI


def test_select_false_attack_returns_none_without_edges() -> None:
    """The engagement precondition upstream stops this code path, but the
    helper itself is defensive — no edges means no commit."""
    tori = _composed_judoka()
    g = GripGraph()   # empty
    assert _select_false_attack_throw(tori, g) is None


# ---------------------------------------------------------------------------
# select_actions — end-to-end commit flow
# ---------------------------------------------------------------------------
def test_select_actions_emits_false_attack_commit_in_window() -> None:
    """When the normal pathway finds nothing and the fighter is in the
    pre-shido zone with style_dna backing, select_actions returns a single
    COMMIT_THROW flagged as an intentional false attack. The per-tick
    probability gate is deliberately low (tendency × scale ≈ 0.07); this
    test uses a seeded rng known to produce a roll under that threshold
    on the first call so the firing is deterministic."""
    tori = _composed_judoka(tendency=0.70)
    uke  = _composed_judoka(name="uke")
    place_judoka(tori, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(uke,  com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    g = _gripped_graph(tori, uke)
    # Seed chosen so the first random() < 0.07 (see probability gate).
    rng = random.Random(31)

    actions = select_actions(tori, uke, g, kumi_kata_clock=20, rng=rng)
    assert len(actions) == 1
    act = actions[0]
    assert act.kind == ActionKind.COMMIT_THROW
    assert act.intentional_false_attack is True
    assert act.offensive_desperation is False
    assert act.gate_bypass_reason == REASON_INTENTIONAL_FALSE_ATTACK
    assert act.throw_id in FALSE_ATTACK_PREFERENCES


def test_select_actions_does_not_false_attack_outside_window() -> None:
    """Clock below min — fall through to deepen/drive rung, not commit."""
    tori = _composed_judoka()
    uke  = _composed_judoka(name="uke")
    place_judoka(tori, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(uke,  com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    g = _gripped_graph(tori, uke)
    rng = random.Random(42)

    actions = select_actions(tori, uke, g, kumi_kata_clock=5, rng=rng)
    for a in actions:
        assert a.kind != ActionKind.COMMIT_THROW


# ---------------------------------------------------------------------------
# Log line — motivation surfaces on the [throw] commit event
# ---------------------------------------------------------------------------
def test_commit_log_line_tags_commit_motivation() -> None:
    """HAJ-67 — the THROW_ENTRY commit line must tag the specific
    motivation ("commit motivation: clock_reset") so readers and log
    parsers can distinguish among the four non-scoring motivations and
    from both normal commits and offensive-desperation commits."""
    from match import Match
    from referee import build_suzuki
    tori = _composed_judoka(name="Gaba")
    uke  = _composed_judoka(name="Kyo")
    place_judoka(tori, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(uke,  com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    m = Match(
        fighter_a=tori, fighter_b=uke, referee=build_suzuki(),
        stream="debug", seed=1,
    )
    # Directly resolve a non-scoring-motivation commit via the match API.
    evts = m._resolve_commit_throw(
        tori, uke, ThrowID.TAI_OTOSHI, tick=20,
        commit_motivation=CommitMotivation.CLOCK_RESET,
        gate_bypass_reason=REASON_INTENTIONAL_FALSE_ATTACK,
        gate_bypass_kind="false_attack",
    )
    entry = next((e for e in evts if e.event_type == "THROW_ENTRY"), None)
    assert entry is not None
    assert "commit motivation: clock_reset" in entry.description
    # The event data also carries the motivation enum name so downstream
    # consumers can classify without re-parsing the description.
    assert entry.data["commit_motivation"] == CommitMotivation.CLOCK_RESET.name


# ---------------------------------------------------------------------------
# Failure outcome — TACTICAL_DROP_RESET override
# ---------------------------------------------------------------------------
def test_tactical_drop_reset_has_fast_recovery() -> None:
    """The whole point of the state: cheap, fast recovery to stance.
    HAJ-50 reduces this to the minimum — 1 tick — because tori's CoM was
    never committed and there is nothing to recover from, only a tempo
    cost to absorb."""
    assert RECOVERY_TICKS_BY_OUTCOME[FailureOutcome.TACTICAL_DROP_RESET] == 1


def test_failed_false_attack_routes_to_tactical_drop_reset() -> None:
    """When a commit that was flagged intentional_false_attack fails, the
    resolved outcome must be TACTICAL_DROP_RESET regardless of which
    FailureSpec branch the template's dimensions would otherwise select."""
    from match import Match
    from referee import build_suzuki
    tori = _composed_judoka(name="Gaba")
    uke  = _composed_judoka(name="Kyo")
    place_judoka(tori, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(uke,  com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    m = Match(
        fighter_a=tori, fighter_b=uke, referee=build_suzuki(),
        stream="debug", seed=1,
    )
    # Set the motivation snapshot directly — _resolve_commit_throw would
    # also set it, but calling the full commit path here would consume
    # the flag before our assertion could fire (N=1 throws resolve in the
    # same tick). Test the failure path in isolation.
    m._commit_motivation[tori.identity.name] = CommitMotivation.CLOCK_RESET
    events = m._resolve_failed_commit(
        tori, uke, ThrowID.TAI_OTOSHI, "Tai-otoshi", net=-1.0, tick=20,
    )
    failed = next((e for e in events if e.event_type == "FAILED"), None)
    assert failed is not None
    assert failed.data["outcome"] == FailureOutcome.TACTICAL_DROP_RESET.name
    assert failed.data["recovery_ticks"] == 1
    # And the compromised state is tagged on the fighter so counter-window
    # lookups see the lighter vulnerability.
    assert m._compromised_states[tori.identity.name] == FailureOutcome.TACTICAL_DROP_RESET


def test_failed_false_attack_negligible_composure_drop() -> None:
    """A tactical drop is a planned tempo cost, not a failure. HAJ-50
    reduces the composure hit to near-zero (~0.005) — the fighter is
    meant to emerge from a false attack mentally unaffected."""
    from match import Match
    from referee import build_suzuki
    tori = _composed_judoka(name="Gaba")
    uke  = _composed_judoka(name="Kyo")
    place_judoka(tori, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(uke,  com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    m = Match(
        fighter_a=tori, fighter_b=uke, referee=build_suzuki(),
        stream="debug", seed=1,
    )
    m._commit_motivation[tori.identity.name] = CommitMotivation.CLOCK_RESET
    pre = tori.state.composure_current
    m._resolve_failed_commit(
        tori, uke, ThrowID.TAI_OTOSHI, "Tai-otoshi", net=-1.0, tick=20,
    )
    post = tori.state.composure_current
    drop = pre - post
    # Allow a small float-fuzz range around the 0.005 constant.
    assert 0.0 <= drop <= 0.01, (
        f"expected near-zero composure drop (~0.005), got {drop}"
    )


# ---------------------------------------------------------------------------
# HAJ-50 — signature-based discriminator + tuning + prose
# ---------------------------------------------------------------------------
def test_low_signature_drop_routes_to_tactical_drop_reset_without_flag() -> None:
    """HAJ-50 discriminator: even WITHOUT the intentional_false_attack
    flag, a drop-variant commit whose kuzushi + force signature is below
    the floor routes to TACTICAL_DROP_RESET. Physics doesn't care about
    motivation labels — a drop with no kuzushi is mechanically the same
    thing whether tori planned the fake or stumbled into it."""
    from failure_resolution import select_failure_outcome
    from grip_graph import GripGraph
    from worked_throws import TAI_OTOSHI
    tori = _composed_judoka(name="Gaba")
    uke  = _composed_judoka(name="Kyo")
    place_judoka(tori, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(uke,  com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    # Empty grip graph + stationary uke → kuzushi=0, force=0.
    g = GripGraph()
    resolution = select_failure_outcome(
        TAI_OTOSHI, tori, uke, g, throw_id=ThrowID.TAI_OTOSHI,
    )
    assert resolution.outcome == FailureOutcome.TACTICAL_DROP_RESET
    assert resolution.recovery_ticks == 1


def test_real_commit_drop_does_not_route_to_tactical_drop_reset() -> None:
    """A genuine drop-variant commit with real kuzushi + force grips
    routes through the FailureSpec as before — it was a real attempt
    that simply failed, not a feint."""
    from failure_resolution import select_failure_outcome
    from worked_throws import TAI_OTOSHI
    tori = _composed_judoka(name="Gaba")
    uke  = _composed_judoka(name="Kyo")
    place_judoka(tori, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(uke,  com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    g = _gripped_graph(tori, uke)
    # Flip grips into DRIVING mode so force-application dim is non-zero
    # and give uke a real velocity → kuzushi dim above floor.
    for e in g.edges:
        e.mode = GripMode.DRIVING
        e.depth_level = GripDepth.DEEP
    uke.state.body_state.com_velocity = (-0.8, 0.0)
    resolution = select_failure_outcome(
        TAI_OTOSHI, tori, uke, g, throw_id=ThrowID.TAI_OTOSHI,
        rng=random.Random(1),
    )
    assert resolution.outcome != FailureOutcome.TACTICAL_DROP_RESET


def test_non_drop_throw_never_routes_to_tactical_drop_reset() -> None:
    """Only drop-variant throws can land in TACTICAL_DROP_RESET via the
    discriminator. An Uchi-mata with no signature would fall through the
    normal FailureSpec path — it's not a drop at all."""
    from failure_resolution import select_failure_outcome
    from grip_graph import GripGraph
    from worked_throws import UCHI_MATA
    tori = _composed_judoka(name="Gaba")
    uke  = _composed_judoka(name="Kyo")
    place_judoka(tori, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(uke,  com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    g = GripGraph()
    resolution = select_failure_outcome(
        UCHI_MATA, tori, uke, g, throw_id=ThrowID.UCHI_MATA,
        rng=random.Random(1),
    )
    assert resolution.outcome != FailureOutcome.TACTICAL_DROP_RESET


def test_tactical_drop_reset_config_has_no_counter_bonuses() -> None:
    """HAJ-50 clears the counter_bonuses dict on TACTICAL_DROP_RESET. Uke
    cannot score osaekomi transitions against a tori who is already
    rising; there is no scoop-under for Ura-nage against an uncommitted
    body. The state carries no exploitable bonus."""
    from compromised_state import COMPROMISED_STATE_CONFIGS
    cfg = COMPROMISED_STATE_CONFIGS[FailureOutcome.TACTICAL_DROP_RESET]
    assert cfg.counter_bonuses == {}


def test_tactical_drop_reset_produces_compact_prose() -> None:
    """HAJ-50 — the log line for a tactical drop must be the compact
    two-beat register, not the drawn-out '(tag; recovery N tick(s))'
    narration the generic failure path produces."""
    from match import Match
    from referee import build_suzuki
    tori = _composed_judoka(name="Gaba")
    uke  = _composed_judoka(name="Kyo")
    place_judoka(tori, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(uke,  com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    m = Match(
        fighter_a=tori, fighter_b=uke, referee=build_suzuki(),
        stream="debug", seed=1,
    )
    m._commit_motivation[tori.identity.name] = CommitMotivation.CLOCK_RESET
    events = m._resolve_failed_commit(
        tori, uke, ThrowID.TAI_OTOSHI, "Tai-otoshi", net=-1.0, tick=20,
    )
    failed = next((e for e in events if e.event_type == "FAILED"), None)
    assert failed is not None
    desc = failed.description
    assert "Nothing there" in desc, (
        f"expected compact 'Nothing there' register, got: {desc!r}"
    )
    assert "Back up" in desc
    # The verbose recovery-tick parenthetical should NOT appear.
    assert "recovery" not in desc
    assert "tick" not in desc


# ---------------------------------------------------------------------------
# Exclusivity — desperation takes precedence
# ---------------------------------------------------------------------------
def test_false_attack_does_not_fire_when_desperate() -> None:
    """When offensive desperation is already firing (imminent shido),
    the ladder takes the desperation path, not false-attack."""
    tori = _composed_judoka()
    uke  = _composed_judoka(name="uke")
    place_judoka(tori, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(uke,  com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    g = _gripped_graph(tori, uke)
    rng = random.Random(42)
    # Clock at the imminent-shido trigger (29) — desperation fires.
    actions = select_actions(tori, uke, g, kumi_kata_clock=29, rng=rng)
    commit = [a for a in actions if a.kind == ActionKind.COMMIT_THROW]
    if commit:
        # If a commit occurred, it's the desperation path, not false-attack.
        assert commit[0].intentional_false_attack is False
        assert commit[0].offensive_desperation is True


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
                print(f"PASS  {name}")
                passed += 1
            except Exception:
                print(f"FAIL  {name}")
                traceback.print_exc()
                failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
