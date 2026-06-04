# tests/test_haj225_grip_narration.py
# HAJ-225 — mat-side grip narration: strip success/partial sentences, the
# failed-strip sibling, and the contested first-grip variant, all sourced
# from the data-driven grip_narration layer.

from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import grip_narration
from grip_graph import Event
from body_part_events import (
    BodyPartEvent, BodyPartHigh, BodyPartVerb, BodyPartTarget, Side, GripIntent,
)
from narration.altitudes.mat_side import MatSideNarrator


# ---------------------------------------------------------------------------
# DATA LAYER — loader / selection / fallback
# ---------------------------------------------------------------------------
def test_default_yaml_loads_all_keys() -> None:
    data = grip_narration.load_grip_narration()
    for key in (
        grip_narration.STRIP_FULL, grip_narration.STRIP_PARTIAL,
        grip_narration.STRIP_FAILED, grip_narration.BOTH_GRIPS,
        grip_narration.FIRST_GRIP_UNCONTESTED,
        grip_narration.FIRST_GRIP_CONTESTED,
    ):
        assert data.get(key), f"missing key in YAML: {key}"


def test_select_line_is_deterministic_in_seed() -> None:
    a = grip_narration.select_line(
        grip_narration.STRIP_FULL, seed=42,
        stripper="Sato", target="Tanaka", grip="lapel",
    )
    b = grip_narration.select_line(
        grip_narration.STRIP_FULL, seed=42,
        stripper="Sato", target="Tanaka", grip="lapel",
    )
    assert a == b
    assert "Sato" in a and "Tanaka" in a and "lapel" in a


def test_select_line_falls_back_when_yaml_empty() -> None:
    grip_narration.reset_default_data(grip_narration.parse_grip_narration({}))
    try:
        line = grip_narration.select_line(
            grip_narration.STRIP_PARTIAL, seed=1,
            stripper="A", target="B", grip="sleeve", depth="pocket",
        )
        # Falls back to the baked-in constant, still rendered with fields.
        assert "A" in line and "B" in line and "sleeve" in line
        assert "pocket" in line
    finally:
        grip_narration.reset_default_data(None)


def test_select_line_tolerates_missing_field() -> None:
    # An authored variant referencing an unsupplied field degrades to the
    # fallback rather than raising mid-match.
    grip_narration.reset_default_data(grip_narration.parse_grip_narration({
        grip_narration.STRIP_FULL: ["{stripper} rips {target}'s {grip} — {bogus}"],
    }))
    try:
        line = grip_narration.select_line(
            grip_narration.STRIP_FULL, seed=0,
            stripper="A", target="B", grip="lapel",
        )
        assert "A" in line and "B" in line  # rendered via fallback
    finally:
        grip_narration.reset_default_data(None)


# ---------------------------------------------------------------------------
# STRIP OUTCOME DETECTOR — partial / full off engine events
# ---------------------------------------------------------------------------
def _degrade_event(tick, stripper, owner, grip, new_depth):
    return Event(
        tick=tick, event_type="GRIP_DEGRADE", description="(raw)",
        data={"stripper": stripper, "owner": owner,
              "grip_label": grip, "new_depth": new_depth},
    )


def _stripped_event(tick, stripper, owner, grip):
    return Event(
        tick=tick, event_type="GRIP_STRIPPED", description="(raw)",
        data={"stripper": stripper, "owner": owner, "grip_label": grip},
    )


def test_partial_strip_emits_distinct_success_line() -> None:
    n = MatSideNarrator()
    ev = _degrade_event(5, "Sato", "Tanaka", "lapel", "POCKET")
    entries = n._detect_grip_strip_outcome(5, [ev])
    assert len(entries) == 1
    prose = entries[0].prose
    assert "Sato" in prose and "Tanaka" in prose and "lapel" in prose
    assert "pocket" in prose
    # Distinct from the failed-strip "can't budge it" line.
    assert "can't budge" not in prose


def test_full_strip_emits_loose_line() -> None:
    n = MatSideNarrator()
    ev = _stripped_event(7, "Tanaka", "Sato", "sleeve")
    entries = n._detect_grip_strip_outcome(7, [ev])
    assert len(entries) == 1
    prose = entries[0].prose
    assert "Tanaka" in prose and "Sato" in prose and "sleeve" in prose
    assert "can't budge" not in prose


def test_unenriched_degrade_event_is_skipped() -> None:
    # A degrade with no stripper (e.g. fatigue/voluntary) must not be
    # mis-authored as a strip.
    n = MatSideNarrator()
    ev = Event(tick=3, event_type="GRIP_DEGRADE", description="(raw)", data={})
    assert n._detect_grip_strip_outcome(3, [ev]) == []


def test_failed_strip_still_reads_as_cant_budge() -> None:
    # A no-effect strip surfaces as a SNAP GRIP_STRIP BPE → failed-strip line.
    n = MatSideNarrator()
    bpe = BodyPartEvent(
        tick=4, actor="Sato", part=BodyPartHigh.HANDS, side=Side.NONE,
        verb=BodyPartVerb.SNAP, target=BodyPartTarget.LAPEL,
        intent=GripIntent.BREAK, source="GRIP_STRIP",
    )
    entries = n._detect_intent_outcome_mismatch(4, [bpe])
    assert len(entries) == 1
    assert "Sato" in entries[0].prose
    # The failed line is recognisable as a failed strip attempt.
    assert any(tok in entries[0].prose for tok in ("budge", "holds", "strip it free"))


def test_successful_break_bpe_does_not_fire_failed_line() -> None:
    # A BREAK (had-effect) strip BPE must NOT trigger the failed-strip line —
    # that's the partial/full success path's job.
    n = MatSideNarrator()
    bpe = BodyPartEvent(
        tick=4, actor="Sato", part=BodyPartHigh.HANDS, side=Side.NONE,
        verb=BodyPartVerb.BREAK, target=BodyPartTarget.LAPEL,
        intent=GripIntent.BREAK, source="GRIP_STRIP",
    )
    assert n._detect_intent_outcome_mismatch(4, [bpe]) == []
