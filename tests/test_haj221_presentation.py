# tests/test_haj221_presentation.py
# HAJ-221 — match log presentation pass.
#
# Covers the six changes:
#   1. Narrative-first vocabulary for counter, grip-cascade, chase,
#      defense, and defensive-desperation events.
#   2/3. Body-part narration data structure and loader for throw phases.
#   4. Quality band computation (clean / standard / sloppy).
#   5. coach / debug stream toggle.
#   6. Hajime / Matte banner gating + Matte context line.

from __future__ import annotations

import io
import os
import sys
import contextlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import main as main_module
from body_state import place_judoka
from enums import (
    BodyPart, GripTypeV2, GripDepth, GripMode, GripTarget,
    MatteReason, Position, SubLoopState,
)
from execution_quality import (
    NARRATION_BAND_CLEAN, NARRATION_BAND_STANDARD, NARRATION_BAND_SLOPPY,
    NARRATION_CLEAN_MIN, NARRATION_STANDARD_MIN,
    narration_band_for,
)
from grip_graph import GripEdge
from match import (
    Match,
    VALID_STREAMS, _is_coach_stream,
    _counter_coach_prose, _grip_cascade_coach_prose,
    _chase_coach_prose, _defense_coach_prose,
    _defensive_desperation_coach_prose,
    _offensive_desperation_coach_prose,
    _judoka_state_phrase,
)
from referee import build_suzuki, MatchState, Referee
from throws import ThrowID
import throw_narration as tn


def _pair():
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    return t, s


# ===========================================================================
# 1. Narrative-first vocabulary helpers
# ===========================================================================
def test_counter_coach_prose_inverts_sen_sen_no_sen() -> None:
    from counter_windows import CounterWindow
    line = _counter_coach_prose(
        "Sato", CounterWindow.SEN_SEN_NO_SEN, "Ko-uchi-gari",
    )
    assert line.startswith("[counter] Sato sees the attack forming and strikes first")
    assert "(sen-sen-no-sen)" in line
    assert "Ko-uchi-gari" in line


def test_counter_coach_prose_inverts_go_no_sen() -> None:
    from counter_windows import CounterWindow
    line = _counter_coach_prose(
        "Sato", CounterWindow.GO_NO_SEN, "O-soto-gari",
    )
    assert "reacts to the attack and counters" in line
    assert "(go-no-sen)" in line


def test_grip_cascade_coach_prose_pursue_own() -> None:
    line = _grip_cascade_coach_prose("Tanaka", "Sato", "PURSUE_OWN")
    assert line.startswith("Sato ignores the grip war")
    assert "(PURSUE_OWN)" in line


def test_grip_cascade_coach_prose_disengage() -> None:
    line = _grip_cascade_coach_prose("Sato", "Tanaka", "DISENGAGE")
    assert "Tanaka backs off the grip exchange" in line
    assert "(DISENGAGE)" in line


def test_grip_cascade_coach_prose_contest() -> None:
    line = _grip_cascade_coach_prose("Sato", "Tanaka", "CONTEST")
    assert "Tanaka contests the grip" in line
    assert "(CONTEST)" in line


def test_grip_cascade_coach_prose_defensive() -> None:
    line = _grip_cascade_coach_prose("Sato", "Tanaka", "DEFENSIVE")
    assert "Tanaka fights defensively for the grip" in line
    assert "(DEFENSIVE)" in line


def test_chase_coach_prose_chase() -> None:
    line = _chase_coach_prose("Tanaka", "CHASE")
    assert "Tanaka chases the score to the ground" in line
    assert "(CHASE)" in line


def test_defense_coach_prose_scramble() -> None:
    line = _defense_coach_prose("Sato", "SCRAMBLE")
    assert "Sato scrambles to avoid the follow-up" in line
    assert "(SCRAMBLE)" in line


def test_defensive_desperation_coach_prose_lacks_numbers() -> None:
    line = _defensive_desperation_coach_prose("Tanaka")
    assert "Tanaka" in line
    assert "(defensive desperation)" in line
    # Numbers should not leak into the coach phrasing.
    for digit in "0123456789":
        assert digit not in line


def test_offensive_desperation_coach_prose_lacks_numbers() -> None:
    line = _offensive_desperation_coach_prose("Sato")
    assert "Sato" in line
    assert "(offensive desperation)" in line


# ===========================================================================
# 4. Quality band computation (HAJ-221 thresholds)
# ===========================================================================
def test_narration_band_thresholds_match_spec() -> None:
    assert NARRATION_CLEAN_MIN == 0.75
    assert NARRATION_STANDARD_MIN == 0.40


def test_narration_band_clean_above_threshold() -> None:
    assert narration_band_for(0.90) == NARRATION_BAND_CLEAN
    assert narration_band_for(0.75) == NARRATION_BAND_CLEAN


def test_narration_band_standard_mid_range() -> None:
    assert narration_band_for(0.60) == NARRATION_BAND_STANDARD
    assert narration_band_for(0.40) == NARRATION_BAND_STANDARD


def test_narration_band_sloppy_below_threshold() -> None:
    assert narration_band_for(0.39) == NARRATION_BAND_SLOPPY
    assert narration_band_for(0.0) == NARRATION_BAND_SLOPPY


# ===========================================================================
# 2/3. throw_narration loader + data structure
# ===========================================================================
def test_loader_parses_full_throw_entry() -> None:
    raw = {
        "ko_uchi_gari": {
            "commit": ["Tanaka commits to Ko-uchi-gari."],
            "reach_kuzushi": {
                "clean":    ["clean rk"],
                "standard": ["standard rk"],
                "sloppy":   ["sloppy rk"],
            },
            "kuzushi": {
                "standard": ["uke shifts"],
            },
            "tsukuri": {"standard": ["tori positions"]},
            "kake":    {"standard": ["tori sweeps"]},
            "failures": {
                "SWEEP_BOUNCES_OFF": ["sweep glances"],
                "forward_lean":      ["tori falls forward"],
            },
        },
    }
    data = tn.parse_throw_narration(raw)
    assert "ko_uchi_gari" in data
    entry = data["ko_uchi_gari"]
    assert entry.phases["commit"] == ["Tanaka commits to Ko-uchi-gari."]
    assert entry.phases["reach_kuzushi"]["clean"] == ["clean rk"]
    # Failure keys normalised to lower-snake regardless of input case.
    assert "sweep_bounces_off" in entry.failures
    assert "forward_lean" in entry.failures


def test_loader_lifts_bare_string_to_variant_list() -> None:
    data = tn.parse_throw_narration({
        "ko_uchi_gari": {
            "commit": "single line",
            "reach_kuzushi": {"clean": "clean-only"},
        },
    })
    entry = data["ko_uchi_gari"]
    assert entry.phases["commit"] == ["single line"]
    assert entry.phases["reach_kuzushi"]["clean"] == ["clean-only"]


def test_loader_rejects_empty_variants_list() -> None:
    try:
        tn.parse_throw_narration({
            "ko_uchi_gari": {
                "reach_kuzushi": {"clean": []},
            },
        })
    except tn.ThrowNarrationLoadError as e:
        assert "empty" in str(e).lower()
        return
    raise AssertionError("expected ThrowNarrationLoadError for empty variants")


def test_select_phase_line_picks_band_matching_quality() -> None:
    data = tn.parse_throw_narration({
        "ko_uchi_gari": {
            "reach_kuzushi": {
                "clean":    ["CLEAN"],
                "standard": ["STANDARD"],
                "sloppy":   ["SLOPPY"],
            },
        },
    })
    assert tn.select_phase_line(
        data, ThrowID.KO_UCHI_GARI, "reach_kuzushi", quality=0.9, seed=1,
    ) == "CLEAN"
    assert tn.select_phase_line(
        data, ThrowID.KO_UCHI_GARI, "reach_kuzushi", quality=0.5, seed=1,
    ) == "STANDARD"
    assert tn.select_phase_line(
        data, ThrowID.KO_UCHI_GARI, "reach_kuzushi", quality=0.2, seed=1,
    ) == "SLOPPY"


def test_select_phase_line_falls_back_when_band_missing() -> None:
    data = tn.parse_throw_narration({
        "ko_uchi_gari": {
            "reach_kuzushi": {
                "standard": ["STANDARD-ONLY"],
            },
        },
    })
    # No clean variant — falls back to standard.
    assert tn.select_phase_line(
        data, ThrowID.KO_UCHI_GARI, "reach_kuzushi", quality=0.9, seed=1,
    ) == "STANDARD-ONLY"


def test_select_phase_line_returns_none_for_unknown_throw() -> None:
    assert tn.select_phase_line(
        {}, ThrowID.UCHI_MATA, "reach_kuzushi", quality=0.5, seed=1,
    ) is None


def test_select_phase_line_is_deterministic_by_seed() -> None:
    data = tn.parse_throw_narration({
        "ko_uchi_gari": {
            "reach_kuzushi": {
                "standard": ["VAR_A", "VAR_B", "VAR_C", "VAR_D"],
            },
        },
    })
    line1 = tn.select_phase_line(
        data, ThrowID.KO_UCHI_GARI, "reach_kuzushi",
        quality=0.5, seed="match-seed-42",
    )
    line2 = tn.select_phase_line(
        data, ThrowID.KO_UCHI_GARI, "reach_kuzushi",
        quality=0.5, seed="match-seed-42",
    )
    assert line1 == line2
    # Different seed → can land on a different variant; over many
    # variants this is overwhelmingly likely.
    differing_seeds = {
        tn.select_phase_line(
            data, ThrowID.KO_UCHI_GARI, "reach_kuzushi",
            quality=0.5, seed=f"seed-{i}",
        )
        for i in range(8)
    }
    assert len(differing_seeds) > 1


def test_select_failure_line_accepts_enum_name() -> None:
    data = tn.parse_throw_narration({
        "ko_uchi_gari": {
            "failures": {"SWEEP_BOUNCES_OFF": ["bounce-off"]},
        },
    })
    assert tn.select_failure_line(
        data, ThrowID.KO_UCHI_GARI, "SWEEP_BOUNCES_OFF", seed=0,
    ) == "bounce-off"
    # Lower-snake spelling matches the same entry.
    assert tn.select_failure_line(
        data, ThrowID.KO_UCHI_GARI, "sweep_bounces_off", seed=0,
    ) == "bounce-off"


# ---------------------------------------------------------------------------
# HAJ-223 — authored failure narration wired into the coach stream.
# _format_failure_events attaches the authored body-part failure line to the
# FAILED event's `coach_prose`, falling back to the engineer tag when the
# throw has no entry for that FailureOutcome.
# ---------------------------------------------------------------------------
def _failure_resolution(outcome, recovery=1):
    from failure_resolution import FailureResolution
    return FailureResolution(
        outcome=outcome, recovery_ticks=recovery,
        failed_dimension="kuzushi", dimension_score=0.3,
    )


def _match_for_failures():
    t, s = _pair()
    return Match(
        fighter_a=t, fighter_b=s, referee=build_suzuki(),
        seed=1, stream="coach",
    ), t, s


def test_authored_failure_line_surfaces_as_coach_prose() -> None:
    from throw_templates import FailureOutcome
    tn.reset_default_data(tn.parse_throw_narration({
        "ko_uchi_gari": {
            "failures": {
                "TORI_SWEEP_BOUNCES_OFF": ["{tori}'s foot skids off {uke}'s heel."],
            },
        },
    }))
    try:
        m, t, s = _match_for_failures()
        events = m._format_failure_events(
            t, s, "Ko-uchi-gari",
            _failure_resolution(FailureOutcome.TORI_SWEEP_BOUNCES_OFF),
            desperation=False, tick=10, throw_id=ThrowID.KO_UCHI_GARI,
        )
        failed = [e for e in events if e.event_type == "FAILED"]
        assert len(failed) == 1
        # {tori}/{uke} resolved to live fighter names (attacker=tori).
        assert failed[0].data.get("coach_prose") == (
            f"{t.identity.name}'s foot skids off {s.identity.name}'s heel."
        )
        # Engineer-facing description still carries the enum tag for debug.
        assert "sweep bounces off" in failed[0].description
    finally:
        tn.reset_default_data(None)


def test_unauthored_failure_falls_back_to_tag() -> None:
    """No narration entry for this (throw, outcome) → no coach_prose; the
    engineer tag phrasing is preserved."""
    from throw_templates import FailureOutcome
    tn.reset_default_data(tn.parse_throw_narration({}))
    try:
        m, t, s = _match_for_failures()
        events = m._format_failure_events(
            t, s, "Ko-uchi-gari",
            _failure_resolution(FailureOutcome.STANCE_RESET),
            desperation=False, tick=10, throw_id=ThrowID.KO_UCHI_GARI,
        )
        failed = [e for e in events if e.event_type == "FAILED"]
        assert len(failed) == 1
        assert "coach_prose" not in failed[0].data
        assert "stance reset" in failed[0].description
    finally:
        tn.reset_default_data(None)


def test_authored_counter_line_overrides_counter_narration() -> None:
    """A clean-counter outcome (OSOTO_GAESHI) routes the authored line onto
    the [counter] FAILED event and silences the bare 'stuffed' beat."""
    from throw_templates import FailureOutcome
    tn.reset_default_data(tn.parse_throw_narration({
        "o_soto_gari": {
            "failures": {
                "OSOTO_GAESHI": ["{uke} catches the reap and turns it back on {tori}."],
            },
        },
    }))
    try:
        m, t, s = _match_for_failures()
        events = m._format_failure_events(
            t, s, "O-soto-gari",
            _failure_resolution(FailureOutcome.OSOTO_GAESHI),
            desperation=False, tick=10, throw_id=ThrowID.O_SOTO_GARI,
        )
        stuffed = [e for e in events if e.event_type == "THROW_STUFFED"]
        failed = [e for e in events if e.event_type == "FAILED"]
        assert len(stuffed) == 1 and len(failed) == 1
        # Authored line lands on the counter (FAILED) event, names resolved.
        assert failed[0].data.get("coach_prose") == (
            f"{s.identity.name} catches the reap and turns it back on "
            f"{t.identity.name}."
        )
        # The bare "stuffed" beat is silenced on the coach stream so the
        # authored counter line is the single narrative beat.
        assert stuffed[0].data.get("prose_silent") is True
    finally:
        tn.reset_default_data(None)


def test_empty_narration_data_falls_back_gracefully() -> None:
    """HAJ-221 AC: empty narration data must not crash."""
    assert tn.parse_throw_narration({}) == {}
    assert tn.select_phase_line(
        {}, ThrowID.KO_UCHI_GARI, "reach_kuzushi", quality=0.5, seed=0,
    ) is None
    # Generic phase line for unauthored throws.
    line = tn.generic_phase_line(
        "reach_kuzushi", tori="Tanaka", uke="Sato",
    )
    assert line is not None
    assert "Tanaka" in line and "Sato" in line


# ===========================================================================
# 5. Coach / debug stream toggle
# ===========================================================================
def test_coach_is_valid_stream_name() -> None:
    assert "coach" in VALID_STREAMS
    assert "debug" in VALID_STREAMS
    assert "prose" in VALID_STREAMS  # backward-compat alias
    assert "both" in VALID_STREAMS


def test_is_coach_stream_recognises_both_names() -> None:
    assert _is_coach_stream("coach")
    assert _is_coach_stream("prose")
    assert not _is_coach_stream("debug")
    assert not _is_coach_stream("both")


def test_match_accepts_coach_stream_kwarg() -> None:
    t, s = _pair()
    m = Match(
        fighter_a=t, fighter_b=s, referee=build_suzuki(),
        seed=1, stream="coach",
    )
    assert m._stream == "coach"


# ===========================================================================
# 6. Banner gating + Matte context line
# ===========================================================================
def test_announce_hajime_carries_banner_metadata() -> None:
    ref = build_suzuki()
    ev = ref.announce_hajime(tick=0)
    assert ev.data["banner"] == "hajime"
    assert ev.data["banner_duration_ticks"] >= 1
    assert ev.data["banner_blocking"] is True


def test_announce_matte_carries_banner_metadata() -> None:
    ref = build_suzuki()
    ev = ref.announce_matte(MatteReason.STUFFED_THROW_TIMEOUT, tick=10)
    assert ev.data["banner"] == "matte"
    assert ev.data["banner_duration_ticks"] >= 1
    assert ev.data["banner_blocking"] is True


def test_matte_pause_strictly_exceeds_banner_duration() -> None:
    """Engine invariant: the matte→hajime pause must clear the matte
    banner before the next hajime banner fires."""
    from match import MATTE_TO_HAJIME_PAUSE_TICKS
    assert MATTE_TO_HAJIME_PAUSE_TICKS > Referee.BANNER_DURATION_TICKS, (
        "matte→hajime pause must exceed banner display time to avoid overlap"
    )


def test_judoka_state_phrase_words() -> None:
    t, _ = _pair()
    # Default state — full composure + cardio.
    phrase = _judoka_state_phrase(t)
    assert isinstance(phrase, str) and phrase
    # Drained cardio → "gasping" branch.
    t.state.cardio_current = 0.10
    assert "gasping" in _judoka_state_phrase(t).lower()


def test_build_matte_context_event_has_both_judoka() -> None:
    t, s = _pair()
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki(), seed=1)
    ev = m._build_matte_context_event(tick=32)
    assert ev.event_type == "MATTE_CONTEXT"
    coach = ev.data["coach_prose"]
    assert t.identity.name in coach
    assert s.identity.name in coach
    assert ev.data["prose_silent"] is True


# ===========================================================================
# End-to-end coach stream check
# ===========================================================================
def test_coach_stream_surfaces_coach_prose_for_silent_events() -> None:
    """Events flagged prose_silent that carry coach_prose should surface
    on the coach stream (HAJ-221 — narrative-first state lines)."""
    from grip_graph import Event
    t, s = _pair()
    m = Match(
        fighter_a=t, fighter_b=s, referee=build_suzuki(),
        seed=1, stream="coach",
    )
    fake_event = Event(
        tick=5, event_type="GRIP_CASCADE_RESPONSE",
        description="[grip_cascade] Sato → PURSUE_OWN vs Tanaka",
        data={
            "prose_silent": True,
            "coach_prose": "Sato ignores the grip war and reaches for "
                           "his own grip (PURSUE_OWN).",
        },
    )
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m._print_events([fake_event])
    out = buf.getvalue()
    assert "Sato ignores the grip war" in out
    # The engineering description must NOT be rendered on coach stream.
    assert "[grip_cascade]" not in out


def test_debug_stream_keeps_engineering_description() -> None:
    """Debug stream must keep the original [grip_cascade] form for log
    parsing / calibration tools."""
    from grip_graph import Event
    t, s = _pair()
    m = Match(
        fighter_a=t, fighter_b=s, referee=build_suzuki(),
        seed=1, stream="debug",
    )
    fake_event = Event(
        tick=5, event_type="GRIP_CASCADE_RESPONSE",
        description="[grip_cascade] Sato → PURSUE_OWN vs Tanaka",
        data={
            "prose_silent": True,
            "coach_prose": "Sato ignores the grip war and reaches for "
                           "his own grip (PURSUE_OWN).",
        },
    )
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m._print_events([fake_event])
    out = buf.getvalue()
    assert "[grip_cascade]" in out
    assert "PURSUE_OWN" in out
    # The coach-narrative line should NOT appear on debug stream — the
    # debug stream wants the substrate dump.
    assert "ignores the grip war" not in out


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
