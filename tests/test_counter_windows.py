# tests/test_counter_windows.py
# Verifies Part 6.2 of design-notes/physics-substrate.md:
#   - actual_counter_window classifies the dyad into one of four regions
#     using in-progress state + grip mode + approach velocity
#   - perceived_counter_window narrows to actual for elite, noisy for novice
#   - has_counter_resources gates on composure + fatigue
#   - select_counter_throw prefers symmetric (sen-no-sen), else window
#     options, else signature, only from vocabulary
#   - Match._check_counter_opportunities aborts a mid-attempt attack and
#     fires the counter through _resolve_commit_throw when conditions hold

from __future__ import annotations
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from enums import (
    BeltRank, BodyPart, GripTypeV2, GripDepth, GripMode, GripTarget,
)
from body_state import place_judoka
from grip_graph import GripGraph, GripEdge
from throws import ThrowID
from skill_compression import SubEvent
from counter_windows import (
    CounterWindow,
    actual_counter_window, perceived_counter_window,
    has_counter_resources, select_counter_throw,
    counter_fire_probability, attacker_vulnerability_for,
    SEN_SEN_APPROACH_SPEED, COUNTER_COMPOSURE_GATE, COUNTER_FATIGUE_GATE,
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


class _FakeTip:
    """Stand-in for _ThrowInProgress; actual_counter_window only reads a
    couple of fields so we avoid importing the private dataclass here."""
    def __init__(self, throw_id: ThrowID):
        self.throw_id = throw_id
        self.last_sub_event = None


# ---------------------------------------------------------------------------
# Region classification
# ---------------------------------------------------------------------------
def test_region_is_none_without_any_attack_indicator() -> None:
    t, s = _pair()
    g = GripGraph()
    # No grips, no in-progress, no approach velocity → NONE.
    assert actual_counter_window(t, s, g, None, None) == CounterWindow.NONE


def test_sen_sen_no_sen_fires_when_driving_grip_plus_approach_speed() -> None:
    t, s = _pair()
    g = GripGraph()
    _seat_deep_grips(g, t, s)
    # Tanaka faces +X. Moving toward Sato (at +0.5) means +X velocity.
    t.state.body_state.com_velocity = (SEN_SEN_APPROACH_SPEED + 0.1, 0.0)
    assert actual_counter_window(t, s, g, None, None) == CounterWindow.SEN_SEN_NO_SEN


def test_sen_sen_requires_driving_mode() -> None:
    t, s = _pair()
    g = GripGraph()
    _seat_deep_grips(g, t, s)
    for e in g.edges:
        e.mode = GripMode.CONNECTIVE
    t.state.body_state.com_velocity = (1.0, 0.0)
    # Connective mode disqualifies — not actually attacking yet.
    assert actual_counter_window(t, s, g, None, None) == CounterWindow.NONE


def test_sen_no_sen_fires_at_reach_kuzushi_sub_event() -> None:
    t, s = _pair()
    g = GripGraph()
    tip = _FakeTip(ThrowID.UCHI_MATA)
    tip.last_sub_event = SubEvent.REACH_KUZUSHI
    assert actual_counter_window(t, s, g, tip, SubEvent.REACH_KUZUSHI) == CounterWindow.SEN_NO_SEN


def test_sen_no_sen_fires_at_kuzushi_achieved_sub_event() -> None:
    t, s = _pair()
    g = GripGraph()
    tip = _FakeTip(ThrowID.UCHI_MATA)
    assert actual_counter_window(
        t, s, g, tip, SubEvent.KUZUSHI_ACHIEVED,
    ) == CounterWindow.SEN_NO_SEN


def test_go_no_sen_fires_at_tsukuri_and_kake() -> None:
    t, s = _pair()
    g = GripGraph()
    tip = _FakeTip(ThrowID.SEOI_NAGE)
    for sub in (SubEvent.TSUKURI, SubEvent.KAKE_COMMIT):
        assert actual_counter_window(t, s, g, tip, sub) == CounterWindow.GO_NO_SEN


# ---------------------------------------------------------------------------
# Perceived region (perception noise)
# ---------------------------------------------------------------------------
def test_elite_perception_almost_always_matches_actual() -> None:
    _, s = _pair()
    s.capability.fight_iq = 10
    matches = 0
    for seed in range(200):
        p = perceived_counter_window(
            CounterWindow.GO_NO_SEN, s, rng=random.Random(seed),
        )
        if p == CounterWindow.GO_NO_SEN:
            matches += 1
    # With iq=10, flip_p floors at 0.02, so >90% should match.
    assert matches > 180


def test_novice_perception_misreads_often() -> None:
    _, s = _pair()
    s.capability.fight_iq = 0
    mismatches = 0
    for seed in range(200):
        p = perceived_counter_window(
            CounterWindow.SEN_NO_SEN, s, rng=random.Random(seed),
        )
        if p != CounterWindow.SEN_NO_SEN:
            mismatches += 1
    # With iq=0, flip probability is the full 0.25 — so ~50 mismatches expected.
    assert mismatches >= 30


# ---------------------------------------------------------------------------
# Resource gate
# ---------------------------------------------------------------------------
def test_panicked_defender_cannot_counter() -> None:
    _, s = _pair()
    # Force composure below the gate.
    s.state.composure_current = 0.1   # very low
    assert has_counter_resources(s) is False


def test_fatigued_defender_cannot_counter() -> None:
    _, s = _pair()
    for key in ("right_leg", "left_leg", "right_hand", "left_hand"):
        s.state.body[key].fatigue = COUNTER_FATIGUE_GATE + 0.1
    assert has_counter_resources(s) is False


def test_fresh_composed_defender_has_resources() -> None:
    _, s = _pair()
    assert has_counter_resources(s) is True


# ---------------------------------------------------------------------------
# Counter selection
# ---------------------------------------------------------------------------
def test_select_counter_prefers_symmetric_for_sen_no_sen() -> None:
    _, s = _pair()
    # Sato's vocab includes UCHI_MATA. Attacker's throw is UCHI_MATA →
    # symmetric (Uchi-mata back at them) should be selected.
    assert ThrowID.UCHI_MATA in s.capability.throw_vocabulary
    pick = select_counter_throw(s, CounterWindow.SEN_NO_SEN, ThrowID.UCHI_MATA)
    assert pick == ThrowID.UCHI_MATA


def test_select_counter_falls_through_to_window_options() -> None:
    _, s = _pair()
    # Strip Sato's vocab down so symmetric isn't available.
    s.capability.throw_vocabulary = [ThrowID.SUMI_GAESHI, ThrowID.O_SOTO_GARI]
    pick = select_counter_throw(s, CounterWindow.GO_NO_SEN, ThrowID.SEOI_NAGE)
    assert pick == ThrowID.O_SOTO_GARI


def test_select_counter_returns_none_when_nothing_available() -> None:
    _, s = _pair()
    s.capability.throw_vocabulary = []
    s.capability.signature_throws = []
    assert select_counter_throw(
        s, CounterWindow.GO_NO_SEN, ThrowID.SEOI_NAGE,
    ) is None


def test_select_counter_none_window_returns_none() -> None:
    _, s = _pair()
    assert select_counter_throw(
        s, CounterWindow.NONE, ThrowID.UCHI_MATA,
    ) is None


# ---------------------------------------------------------------------------
# Fire probability
# ---------------------------------------------------------------------------
def test_fire_probability_zero_for_none_window() -> None:
    _, s = _pair()
    assert counter_fire_probability(s, CounterWindow.NONE, 1.0) == 0.0


def test_fire_probability_scales_with_iq_and_vulnerability() -> None:
    _, s = _pair()
    s.capability.fight_iq = 10
    high_vuln = counter_fire_probability(s, CounterWindow.SEN_NO_SEN, 1.0)
    low_vuln  = counter_fire_probability(s, CounterWindow.SEN_NO_SEN, 0.1)
    assert high_vuln > low_vuln

    s.capability.fight_iq = 2
    low_iq_prob = counter_fire_probability(s, CounterWindow.SEN_NO_SEN, 1.0)
    assert high_vuln > low_iq_prob


# ---------------------------------------------------------------------------
# Attacker vulnerability lookup
# ---------------------------------------------------------------------------
def test_vulnerability_pulls_from_worked_template() -> None:
    # Uchi-mata sukashi vulnerability (Part 5) is 0.75.
    assert abs(attacker_vulnerability_for(ThrowID.UCHI_MATA) - 0.75) < 1e-9
    # Seoi-nage has counter_vulnerability 0.55 (Lever).
    assert abs(attacker_vulnerability_for(ThrowID.SEOI_NAGE) - 0.55) < 1e-9


def test_vulnerability_default_for_legacy_throws() -> None:
    # SUMI_GAESHI is the only v0.1 throw without a Part-5 template after
    # HAJ-29 backfill — default 0.30 applies.
    from worked_throws import WORKED_THROWS
    assert ThrowID.SUMI_GAESHI not in WORKED_THROWS
    assert attacker_vulnerability_for(ThrowID.SUMI_GAESHI) == 0.30


# ---------------------------------------------------------------------------
# Match integration — counter preempts in-progress attempt
# ---------------------------------------------------------------------------
def test_counter_fires_mid_attempt_and_aborts_original() -> None:
    """Stage a high-vulnerability Uchi-mata mid-attempt; force the counter
    RNG to fire; verify the original attempt aborts and a COUNTER_COMMIT
    event is emitted followed by the defender's commit.
    """
    from match import Match
    from referee import build_suzuki

    t, s = _pair()
    # Make Sato a sharp, composed reader so resources + probability pass.
    s.capability.fight_iq = 10
    s.state.composure_current = float(s.capability.composure_ceiling)
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())
    _seat_deep_grips(m.grip_graph, t, s)
    # HAJ-141 — Sato is the counter-attacker but has no own edges in this
    # setup; the engagement-distance gate would deny her commit. Production
    # flow always has the dyad in GRIPPING/ENGAGED before counters fire.
    from enums import Position
    m.position = Position.GRIPPING

    # Tanaka starts a 2-tick Uchi-mata attempt (sukashi_vulnerability=0.75).
    m._resolve_commit_throw(t, s, ThrowID.UCHI_MATA, tick=1)
    assert t.identity.name in m._throws_in_progress

    # RNG seeded so the fire-probability roll succeeds; with vuln 0.75,
    # iq 1.0, composure 1.0 and SEN_NO_SEN mod 1.0 → ~0.225. Seed 0 gives a
    # first random() < 0.225 with high probability.
    class _RigRng:
        """Fake rng that always passes perception-noise and counter-fire rolls."""
        def random(self):
            return 0.0
        def choice(self, seq):
            return seq[0]

    events = m._check_counter_opportunities(tick=2, rng=_RigRng())
    kinds = [e.event_type for e in events]
    assert "COUNTER_COMMIT" in kinds
    assert "THROW_ABORTED" in kinds
    # Tanaka's attempt cleared, Sato's counter registered.
    assert t.identity.name not in m._throws_in_progress
    # Sato's counter either resolved immediately (N=1) or stashed (N>1).
    # Either way a THROW_ENTRY for Sato is present.
    entries = [e for e in events if e.event_type == "THROW_ENTRY"]
    assert any(
        isinstance(e.description, str) and "Sato" in e.description
        for e in entries
    )


def test_no_counter_when_defender_lacks_resources() -> None:
    """A panicked/fatigued defender sees the window but can't commit."""
    from match import Match
    from referee import build_suzuki

    t, s = _pair()
    # Cook Sato so resource gate fails.
    for key in ("right_leg", "left_leg", "right_hand", "left_hand"):
        s.state.body[key].fatigue = 0.95
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())
    _seat_deep_grips(m.grip_graph, t, s)
    m._resolve_commit_throw(t, s, ThrowID.UCHI_MATA, tick=1)
    assert t.identity.name in m._throws_in_progress

    events = m._check_counter_opportunities(
        tick=2, rng=random.Random(0),
    )
    assert all(e.event_type != "COUNTER_COMMIT" for e in events)
    # Tanaka's attempt still live.
    assert t.identity.name in m._throws_in_progress


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
