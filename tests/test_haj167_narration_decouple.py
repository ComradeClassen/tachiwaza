# tests/test_haj167_narration_decouple.py
# HAJ-167 — narration decouple v1: windowed-pull architecture.
#
# Pre-decouple the mat-side narrator was a per-tick pull but each
# detector only read the current tick's slice and any cross-tick
# state was bookkept on the narrator instance (`_last_posture`,
# `_last_region`). Post-decouple the narrator owns a fixed-size
# tick window of (events, BPEs, snapshot) tuples; rules read across
# frames; gap-surfacing rules can defer firing until the gap is real.
#
# AC coverage:
#
#   AC#1 — Narration module operates on windowed reads. The window
#          appends per tick and slides; rules read window[-1] and / or
#          earlier frames. Verified by inspecting `_window` after
#          consume_tick calls.
#   AC#2 — Existing prose families migrated. Posture / region /
#          phase-transition / pull-without-commit rules all run from
#          the new pipeline; legacy detector method bodies retired
#          for those families. Existing tests are the regression net
#          (all green).
#   AC#3 — Promotion rules first-class. `consume_tick` invokes named
#          `_rule_*` methods in priority order; suppression flag is
#          explicit.
#   AC#4 — Tick log untouched. The narrator never mutates the
#          engine's events / BPEs (it stores tuples).
#   AC#5 — Match clock log behavior equivalent or better — verified
#          by full-suite green plus the HAJ-162 anchor tests.
#   AC#6 — Intent-vs-outcome gap surfacing. Pull-without-commit fires
#          K ticks after a PULL only if no commit followed. New tests
#          here pin both branches (gap real → fires; gap closed by
#          commit → silent). The opposite-blind v0.1 behavior is no
#          longer possible.
#   AC#7 — Architecture documented in design-notes/narration-
#          decouple-v1.md.

from __future__ import annotations
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from body_part_decompose import decompose_pull
from body_state import (
    SLIGHTLY_BENT_LIMIT_RAD, UPRIGHT_LIMIT_RAD, place_judoka,
)
from enums import (
    BodyPart, GripDepth, GripMode, GripTarget, GripTypeV2, MatRegion,
    Position, Posture, SubLoopState,
)
from grip_graph import Event, GripEdge
from match import MAT_HALF_WIDTH, Match
from narration.altitudes.mat_side import (
    MatSideNarrator, MatchSnapshot, TickFrame,
    _build_match_snapshot, _DEFERRED_PULL_K_TICKS, _NARRATION_WINDOW_SIZE,
)
from referee import build_suzuki
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


def _new_match(seed: int = 1):
    random.seed(seed)
    t, s = _pair()
    m = Match(
        fighter_a=t, fighter_b=s, referee=build_suzuki(),
        max_ticks=40, seed=seed, stream="prose",
    )
    m._print_header = lambda: None
    m.position = Position.GRIPPING
    return t, s, m


def _seat_lapel(graph, grasper, victim) -> GripEdge:
    edge = GripEdge(
        grasper_id=grasper.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=victim.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.STANDARD,
        strength=1.0, established_tick=0, mode=GripMode.DRIVING,
    )
    graph.add_edge(edge)
    return edge


def _prime(narrator, m, tick: int = 0) -> None:
    """Establish baseline frames so window[-2] is populated for delta
    rules. Two priming ticks produce window of length 2 (or larger
    after subsequent calls)."""
    narrator._last_phase = "grip_war"
    narrator.consume_tick(tick, [], [], m)


# ===========================================================================
# AC#1 — windowed reads (the substrate)
# ===========================================================================
def test_window_buffer_appends_and_slides() -> None:
    """The narrator's window grows by one TickFrame per consume_tick
    call and caps at _NARRATION_WINDOW_SIZE. The oldest frame drops
    when capacity is exceeded."""
    t, s, m = _new_match()
    narrator = MatSideNarrator()
    for n in range(_NARRATION_WINDOW_SIZE + 5):
        narrator.consume_tick(n, [], [], m)
    assert len(narrator._window) == _NARRATION_WINDOW_SIZE
    # Newest frame is the most recent tick.
    assert narrator._window[-1].tick == _NARRATION_WINDOW_SIZE + 4
    # Oldest frame is the first one within the window cap.
    assert narrator._window[0].tick == 5  # (5..12) inclusive — 8 frames


def test_tick_frame_carries_events_bpes_and_snapshot() -> None:
    t, s, m = _new_match()
    narrator = MatSideNarrator()
    fake_event = Event(tick=10, event_type="MOVE",
                       description="[move]", data={"prose_silent": True})
    narrator.consume_tick(10, [fake_event], [], m)
    frame = narrator._window[-1]
    assert isinstance(frame, TickFrame)
    assert frame.tick == 10
    # Events stored as a tuple — immutable.
    assert isinstance(frame.events, tuple)
    assert frame.events[0].event_type == "MOVE"
    assert isinstance(frame.snapshot, MatchSnapshot)


def test_match_snapshot_captures_per_fighter_state() -> None:
    """The snapshot exposes region, posture, CoM, and grip counts so
    rules can read them without dipping into the live Match."""
    t, s, m = _new_match()
    # Drift Sato into WARNING and bend his trunk into SLIGHTLY_BENT.
    s.state.body_state.com_position = (MAT_HALF_WIDTH * 0.85, 0.0)
    s.state.body_state.trunk_sagittal = (
        UPRIGHT_LIMIT_RAD + (SLIGHTLY_BENT_LIMIT_RAD - UPRIGHT_LIMIT_RAD) / 2
    )
    snapshot = _build_match_snapshot(tick=10, match=m)
    assert snapshot.tick == 10
    assert snapshot.a_name == t.identity.name
    assert snapshot.b_name == s.identity.name
    assert snapshot.b_region is MatRegion.WARNING
    assert snapshot.a_region is MatRegion.CENTER
    assert snapshot.b_posture is Posture.SLIGHTLY_BENT
    assert snapshot.a_posture is Posture.UPRIGHT


def test_snapshot_handles_stub_match_without_fighter_attrs() -> None:
    """Defensive — legacy unit tests pass a stub match with only
    `position` / `sub_loop_state`. The snapshot builder must not
    crash; it returns minimum-fidelity fields."""
    class _StubMatch:
        position = Position.GRIPPING
        sub_loop_state = SubLoopState.STANDING
    snapshot = _build_match_snapshot(tick=5, match=_StubMatch())
    assert snapshot.tick == 5
    assert snapshot.a_name is None and snapshot.b_name is None


# ===========================================================================
# AC#3 — promotion rules first-class
# ===========================================================================
def test_pipeline_runs_phase_transition_before_movement() -> None:
    """Phase-transition prose must precede any same-tick movement
    beat. Verifies the pipeline order: phase rule → movement rules."""
    t, s, m = _new_match()
    narrator = MatSideNarrator()
    # Establish a non-grip_war phase first.
    narrator._last_phase = "closing"
    m.position = Position.STANDING_DISTANT
    narrator.consume_tick(0, [], [], m)
    # Now flip to grip_war so the closing→grip_war transition fires.
    m.position = Position.GRIPPING
    move = Event(
        tick=1, event_type="MOVE",
        description="[move]",
        data={"fighter": t.identity.name,
              "tactical_intent": "circle_closing",
              "prose_silent": True},
    )
    entries = narrator.consume_tick(1, [move], [], m)
    # Phase entry must come before any movement entry.
    sources = [e.source for e in entries]
    if "phase" in sources and "circling" in sources:
        assert sources.index("phase") < sources.index("circling")


def test_movement_rules_suppressed_on_state_change_tick() -> None:
    """Pipeline suppression flag gates rules 7-8 when a state-change
    event is in the tick. Rule 9 (deferred pull) and rule 10 (sample)
    apply their own logic."""
    t, s, m = _new_match()
    narrator = MatSideNarrator()
    _prime(narrator, m)
    move = Event(
        tick=1, event_type="MOVE",
        description="[move]",
        data={"fighter": t.identity.name,
              "tactical_intent": "circle_closing",
              "prose_silent": True},
    )
    matte = Event(
        tick=1, event_type="MATTE",
        description="[matte]", data={},
    )
    entries = narrator.consume_tick(1, [move, matte], [], m)
    # Circling rule suppressed; MATTE always-promote still fires.
    assert not [e for e in entries if e.source == "circling"]
    assert any(e.source == "matte" for e in entries)


# ===========================================================================
# AC#6 — intent-vs-outcome gap surfacing (deferred pull-without-commit)
# ===========================================================================
def test_deferred_pull_fires_only_after_k_ticks() -> None:
    """The deferred rule waits K ticks before firing — earlier ticks
    in the gap window must not produce the line."""
    t, s, m = _new_match()
    edge = _seat_lapel(m.grip_graph, t, s)
    narrator = MatSideNarrator()
    _prime(narrator, m)
    pull_bpes = decompose_pull(
        t, edge, direction=(1.0, 0.0), magnitude=0.3, tick=10,
    )
    early = narrator.consume_tick(10, [], pull_bpes, m)
    assert not [e for e in early if e.source == "pull_no_commit"]
    # Each intervening tick: rule still defers.
    for n in range(11, 10 + _DEFERRED_PULL_K_TICKS):
        entries = narrator.consume_tick(n, [], [], m)
        assert not [e for e in entries if e.source == "pull_no_commit"], (
            f"rule fired prematurely on tick {n}"
        )
    # PULL tick + K — line lands.
    entries = narrator.consume_tick(10 + _DEFERRED_PULL_K_TICKS, [], [], m)
    assert any(e.source == "pull_no_commit" for e in entries)


def test_deferred_pull_silent_when_commit_lands_in_followup_window() -> None:
    """If a commit (COMMIT-source BPE) lands in the K-tick followup
    window, the rule sees the commit and stays silent. Pre-decouple
    the line fired on the PULL tick blind to this."""
    t, s, m = _new_match()
    edge = _seat_lapel(m.grip_graph, t, s)
    narrator = MatSideNarrator()
    _prime(narrator, m)
    pull_bpes = decompose_pull(
        t, edge, direction=(1.0, 0.0), magnitude=0.3, tick=10,
    )
    narrator.consume_tick(10, [], pull_bpes, m)
    # Tick 11: a synthetic COMMIT BPE for the same actor.
    from body_part_events import (
        BodyPartEvent, BodyPartHigh, BodyPartVerb, Side,
    )
    commit_bpe = BodyPartEvent(
        tick=11, actor=t.identity.name,
        part=BodyPartHigh.HANDS, side=Side.RIGHT,
        verb=BodyPartVerb.PULL, source="COMMIT",
    )
    narrator.consume_tick(11, [], [commit_bpe], m)
    # Walk through the rest of the K window — no firing.
    for n in range(12, 16):
        entries = narrator.consume_tick(n, [], [], m)
        assert not [e for e in entries if e.source == "pull_no_commit"], (
            f"rule fired despite commit in followup; tick={n}"
        )


def test_deferred_pull_dedupe_does_not_fire_twice_for_same_pull() -> None:
    """The same trigger PULL BPE must not fire prose on two different
    ticks as the window slides. Dedupe key = (trigger_tick, actor)."""
    t, s, m = _new_match()
    edge = _seat_lapel(m.grip_graph, t, s)
    narrator = MatSideNarrator()
    _prime(narrator, m)
    pull_bpes = decompose_pull(
        t, edge, direction=(1.0, 0.0), magnitude=0.3, tick=10,
    )
    narrator.consume_tick(10, [], pull_bpes, m)
    # First firing window — should fire once.
    entries_first = []
    for n in range(11, 10 + _DEFERRED_PULL_K_TICKS + 1):
        entries_first.extend(narrator.consume_tick(n, [], [], m))
    fired_once = sum(
        1 for e in entries_first if e.source == "pull_no_commit"
    )
    assert fired_once == 1
    # Continue advancing the window — no further firings for this PULL.
    entries_after = []
    for n in range(10 + _DEFERRED_PULL_K_TICKS + 1, 20):
        entries_after.extend(narrator.consume_tick(n, [], [], m))
    fired_after = sum(
        1 for e in entries_after if e.source == "pull_no_commit"
    )
    assert fired_after == 0


# ===========================================================================
# HAJ-229 — suppress the deferred line when a throw resolves / scores in the
# gap. A pre-throw PULL must not surface "tugs at the sleeve — rides it out"
# attributed to the just-thrown fighter (triage cluster 3.2, t011).
# ===========================================================================
def test_deferred_pull_suppressed_when_throw_scores_in_window() -> None:
    """A SCORE_AWARDED (or THROW_LANDING) in the deferral window gates
    the rule off entirely — even though the PULL had no COMMIT BPE of
    its own, the pre-throw grip context is stale once a throw resolves."""
    t, s, m = _new_match()
    edge = _seat_lapel(m.grip_graph, t, s)
    narrator = MatSideNarrator()
    _prime(narrator, m)
    pull_bpes = decompose_pull(
        t, edge, direction=(1.0, 0.0), magnitude=0.3, tick=10,
    )
    narrator.consume_tick(10, [], pull_bpes, m)
    # Tick 12: the opponent's throw lands and scores during the gap.
    score_ev = Event(
        tick=12, event_type="SCORE_AWARDED",
        description="[score] Sato scores waza-ari on Tanaka",
    )
    narrator.consume_tick(12, [score_ev], [], m)
    # Walk the rest of the window — the deferred line must never fire.
    entries = []
    for n in range(13, 18):
        entries.extend(narrator.consume_tick(n, [], [], m))
    assert not [e for e in entries if e.source == "pull_no_commit"], (
        "pre-throw pull surfaced 'tugs at the sleeve' after a throw scored"
    )


def test_deferred_pull_suppressed_when_dyad_drops_to_ne_waza() -> None:
    """The dyad sliding into ne-waza inside the gap gates the rule even
    when no invalidating event was promoted into a frame — the snapshot
    backstop reads the sub-loop-state transition."""
    t, s, m = _new_match()
    edge = _seat_lapel(m.grip_graph, t, s)
    narrator = MatSideNarrator()
    _prime(narrator, m)
    pull_bpes = decompose_pull(
        t, edge, direction=(1.0, 0.0), magnitude=0.3, tick=10,
    )
    narrator.consume_tick(10, [], pull_bpes, m)
    # The match drops to ne-waza partway through the gap (no event passed).
    m.sub_loop_state = SubLoopState.NE_WAZA
    entries = []
    for n in range(11, 16):
        entries.extend(narrator.consume_tick(n, [], [], m))
    assert not [e for e in entries if e.source == "pull_no_commit"], (
        "pre-throw pull surfaced after the dyad dropped to ne-waza"
    )


# ===========================================================================
# Migrated rules (posture / region) read window[-2], not narrator state
# ===========================================================================
def test_posture_rule_reads_previous_frame_snapshot() -> None:
    """Post-decouple the posture rule reads window[-2].snapshot for
    the previous posture instead of a `_last_posture` dict on the
    narrator."""
    t, s, m = _new_match()
    narrator = MatSideNarrator()
    # Tick 0: baseline posture UPRIGHT.
    _prime(narrator, m)
    # Tick 1: bend Sato; rule fires on the delta read against window[-2].
    s.state.body_state.trunk_sagittal = (
        UPRIGHT_LIMIT_RAD + (SLIGHTLY_BENT_LIMIT_RAD - UPRIGHT_LIMIT_RAD) / 2
    )
    entries = narrator.consume_tick(1, [], [], m)
    assert any(e.source == "posture" for e in entries)
    # The narrator does NOT carry a _last_posture field anymore — the
    # delta lives entirely in the window.
    assert not hasattr(narrator, "_last_posture") or (
        getattr(narrator, "_last_posture", None) in (None, {})
    )


def test_region_rule_reads_previous_frame_snapshot() -> None:
    t, s, m = _new_match()
    narrator = MatSideNarrator()
    _prime(narrator, m)
    # Drift tori into WARNING — region delta read against window[-2].
    t.state.body_state.com_position = (MAT_HALF_WIDTH * 0.85, 0.0)
    entries = narrator.consume_tick(1, [], [], m)
    assert any(e.source == "region" for e in entries)


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
