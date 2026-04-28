# tests/test_narration.py
# HAJ-147 — mat-side narration layer + match clock log.
#
# Verifies:
#   - WORD_VERBS table maps engine verbs to register-aware prose words.
#   - Same engine event with different modifiers reads at different
#     registers (skill-revealing prose).
#   - Self-cancel structural detection (opposed pull/step + DISCONNECTED
#     base) produces a coach's-eye gap-prose line.
#   - Intent-outcome mismatch (intent=BREAK + verb=SNAP) promotes as
#     gap-prose.
#   - Phase transitions always promote.
#   - The five canonical throws fire promotion when committed in a
#     real match.
#   - Match.match_clock_log accumulates entries.

from __future__ import annotations

import io
import os
import contextlib
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from body_part_events import (
    BodyPartEvent, BodyPartHigh, Side, BodyPartVerb, BodyPartTarget,
    Modifiers, Crispness, Tightness, Speed, Connection, Timing, Commitment,
    GripIntent, SteerDirection,
)
from narration import (
    MatSideNarrator, MatchClockEntry,
    WORD_VERBS, prose_for_event, register_for,
)
from body_state import place_judoka
import main as main_module


def _pair():
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    return t, s


# ---------------------------------------------------------------------------
# WORD-VERB MAPPING
# ---------------------------------------------------------------------------
def test_word_verbs_cover_canonical_engine_verbs() -> None:
    """Every engine verb in HAJ-145's vocabulary maps to at least one
    prose word in the table (some collapse on register, but the entry
    must exist or prose_for_event falls back to the enum name)."""
    canonical = {
        BodyPartVerb.REACH, BodyPartVerb.GRIP, BodyPartVerb.PULL,
        BodyPartVerb.PUSH, BodyPartVerb.SNAP, BodyPartVerb.BREAK,
        BodyPartVerb.RELEASE, BodyPartVerb.POST, BodyPartVerb.LIFT,
        BodyPartVerb.HOOK, BodyPartVerb.REAP, BodyPartVerb.STEP,
        BodyPartVerb.PROP, BodyPartVerb.LOAD, BodyPartVerb.PIVOT,
        BodyPartVerb.BEND, BodyPartVerb.BLOCK,
    }
    for v in canonical:
        assert v in WORD_VERBS, f"missing word-verb mapping for {v.name}"
        for register in ("low", "mid", "high"):
            assert register in WORD_VERBS[v]


def test_register_picks_high_for_crisp_explosive_event() -> None:
    e = BodyPartEvent(
        tick=0, actor="A", part=BodyPartHigh.HANDS, side=Side.RIGHT,
        verb=BodyPartVerb.PULL, target=BodyPartTarget.LAPEL,
        modifiers=Modifiers(crispness=Crispness.CRISP, speed=Speed.EXPLOSIVE),
    )
    assert register_for(e) == "high"


def test_register_picks_low_for_sloppy_flaring_event() -> None:
    e = BodyPartEvent(
        tick=0, actor="A", part=BodyPartHigh.HANDS, side=Side.LEFT,
        verb=BodyPartVerb.PULL, target=BodyPartTarget.SLEEVE,
        modifiers=Modifiers(crispness=Crispness.SLOPPY, tightness=Tightness.FLARING),
    )
    assert register_for(e) == "low"


def test_same_event_different_modifiers_reads_differently() -> None:
    """Same engine event (PULL on lapel) reads as 'tugs' / 'pulls' /
    'drives' depending on the actor's skill register."""
    base = dict(
        tick=0, actor="A", part=BodyPartHigh.HANDS, side=Side.RIGHT,
        verb=BodyPartVerb.PULL, target=BodyPartTarget.LAPEL,
    )
    novice = BodyPartEvent(**base, modifiers=Modifiers(crispness=Crispness.SLOPPY))
    elite = BodyPartEvent(**base, modifiers=Modifiers(crispness=Crispness.CRISP))
    assert "tugs" in prose_for_event(novice)
    assert "drives" in prose_for_event(elite)


# ---------------------------------------------------------------------------
# RULE 3a — SELF-CANCEL STRUCTURAL DETECTION
# ---------------------------------------------------------------------------
def test_self_cancel_promotes_gap_prose_with_disconnected_base() -> None:
    """Pull-vector + step-vector opposed AND actor's connection
    modifier == DISCONNECTED → emit a self-cancel coach-prose line."""
    n = MatSideNarrator()
    pull = BodyPartEvent(
        tick=5, actor="Tanaka",
        part=BodyPartHigh.HANDS, side=Side.LEFT,
        verb=BodyPartVerb.PULL, target=BodyPartTarget.SLEEVE,
        direction=(1.0, 0.0),
        modifiers=Modifiers(connection=Connection.DISCONNECTED),
    )
    step = BodyPartEvent(
        tick=5, actor="Tanaka",
        part=BodyPartHigh.FEET, side=Side.RIGHT,
        verb=BodyPartVerb.STEP, direction=(-1.0, 0.0),
        modifiers=Modifiers(connection=Connection.DISCONNECTED),
    )
    entries = n._detect_self_cancel(tick=5, bpes=[pull, step])
    assert len(entries) == 1
    assert entries[0].source == "self_cancel"
    assert "Tanaka" in entries[0].prose
    assert "feet" in entries[0].prose


def test_self_cancel_silent_without_disconnected_base() -> None:
    """A retreating tactical pull with a rooted base — opposed vectors
    but the structural signature isn't there. No promotion."""
    n = MatSideNarrator()
    pull = BodyPartEvent(
        tick=5, actor="A", part=BodyPartHigh.HANDS, side=Side.LEFT,
        verb=BodyPartVerb.PULL, direction=(1.0, 0.0),
        modifiers=Modifiers(connection=Connection.ROOTED),
    )
    step = BodyPartEvent(
        tick=5, actor="A", part=BodyPartHigh.FEET, side=Side.RIGHT,
        verb=BodyPartVerb.STEP, direction=(-1.0, 0.0),
        modifiers=Modifiers(connection=Connection.ROOTED),
    )
    assert n._detect_self_cancel(5, [pull, step]) == []


# ---------------------------------------------------------------------------
# RULE 3b — INTENT-OUTCOME MISMATCH
# ---------------------------------------------------------------------------
def test_intent_break_with_snap_outcome_promotes_as_gap_prose() -> None:
    """A grip event with intent=BREAK whose verb is SNAP (failed strip)
    promotes as gap prose."""
    n = MatSideNarrator()
    bpe = BodyPartEvent(
        tick=10, actor="Sato", part=BodyPartHigh.HANDS, side=Side.NONE,
        verb=BodyPartVerb.SNAP, target=BodyPartTarget.LAPEL,
        intent=GripIntent.BREAK, source="GRIP_STRIP",
    )
    entries = n._detect_intent_outcome_mismatch(tick=10, bpes=[bpe])
    assert len(entries) == 1
    assert entries[0].source == "intent_mismatch"
    assert "Sato" in entries[0].prose
    assert "rip" in entries[0].prose or "budge" in entries[0].prose


def test_intent_mismatch_rate_limited_per_actor() -> None:
    """Same actor's repeated intent-outcome gap doesn't fire every tick;
    rate-limit prevents drowning the clock log."""
    n = MatSideNarrator()
    bpe5 = BodyPartEvent(
        tick=5, actor="Sato", part=BodyPartHigh.HANDS, side=Side.NONE,
        verb=BodyPartVerb.SNAP, target=BodyPartTarget.LAPEL,
        intent=GripIntent.BREAK, source="GRIP_STRIP",
    )
    bpe6 = BodyPartEvent(**{**bpe5.__dict__, "tick": 6})
    e1 = n._detect_intent_outcome_mismatch(5, [bpe5])
    e2 = n._detect_intent_outcome_mismatch(6, [bpe6])
    assert len(e1) == 1
    assert len(e2) == 0


def test_intent_break_with_break_outcome_no_promotion() -> None:
    """A successful strip (intent=BREAK + verb=BREAK) is the *match* of
    intent and outcome — no gap, no gap-prose."""
    n = MatSideNarrator()
    bpe = BodyPartEvent(
        tick=10, actor="A", part=BodyPartHigh.HANDS, side=Side.NONE,
        verb=BodyPartVerb.BREAK, target=BodyPartTarget.LAPEL,
        intent=GripIntent.BREAK, source="GRIP_STRIP",
    )
    assert n._detect_intent_outcome_mismatch(10, [bpe]) == []


# ---------------------------------------------------------------------------
# RULE 5 — PHASE TRANSITIONS
# ---------------------------------------------------------------------------
def test_phase_transition_always_promotes() -> None:
    """The first tick where match.position changes → narrator emits a
    phase-source MatchClockEntry."""
    from match import Match
    from referee import build_suzuki
    from enums import Position
    random.seed(0)
    t, s = _pair()
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki(),
              max_ticks=5, seed=0)
    n = m._narrator
    n._last_phase = "closing"
    m.position = Position.GRIPPING
    entries = n.consume_tick(tick=4, events=[], bpes=[], match=m)
    phase_entries = [e for e in entries if e.source == "phase"]
    assert phase_entries
    assert "grips" in phase_entries[0].prose.lower()


# ---------------------------------------------------------------------------
# END-TO-END — narration accumulates on a real match
# ---------------------------------------------------------------------------
def _run_short_match(seed: int = 11, ticks: int = 60):
    from match import Match
    from referee import build_suzuki
    random.seed(seed)
    t, s = _pair()
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki(),
              max_ticks=ticks, seed=seed, stream="debug")
    with contextlib.redirect_stdout(io.StringIO()):
        m.run()
    return m


def test_match_clock_log_populates_during_run() -> None:
    m = _run_short_match()
    assert len(m.match_clock_log) > 0


def test_match_clock_log_includes_throw_promotions() -> None:
    """Rule 1 always-promote: every committed throw must surface in the
    clock log."""
    m = _run_short_match()
    throw_entries = [e for e in m.match_clock_log if e.source == "throw"]
    assert throw_entries, "expected at least one throw promotion"


def test_match_clock_log_includes_phase_transitions() -> None:
    """A 60-tick match starts in closing and at minimum transitions to
    grip_war / engaged — at least one phase entry must exist."""
    m = _run_short_match()
    phase_entries = [e for e in m.match_clock_log if e.source == "phase"]
    assert phase_entries


def test_match_clock_log_diverse_sources() -> None:
    """Healthy clock log spans at least three of the source categories
    over a 60-tick match (throw / phase / skill_reveal / sample / etc)."""
    m = _run_short_match()
    sources = {e.source for e in m.match_clock_log}
    assert len(sources) >= 3, (
        f"expected multi-source clock log, got: {sources}"
    )


def test_match_clock_entries_are_prose_strings() -> None:
    """No empty entries, no leading/trailing whitespace garbage."""
    m = _run_short_match()
    for entry in m.match_clock_log:
        assert isinstance(entry.prose, str)
        assert entry.prose.strip() == entry.prose
        assert entry.prose != ""
