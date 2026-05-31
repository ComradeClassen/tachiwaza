# tests/test_self_inflicted_kuzushi.py
# Failed-throw compromised state folded into the kuzushi buffer.
#
# A failed throw leaves tori off-balance with no opponent pull behind it.
# Pre-fix this lived only as a body_state mutation + the _compromised_states
# tag, invisible to the decaying kuzushi buffer the signature-match layer
# reads. Post-fix, apply_failure_resolution also records a SELF_INFLICTED
# KuzushiEvent into tori's OWN buffer for compromised outcomes that carry
# kuzushi severity; clean resets / clean counters / tactical drops record
# nothing.
#
# Scope guard (next ticket): is_kuzushi and the off-balance event wiring are
# deliberately untouched here — this only adds the buffer contribution.

from __future__ import annotations
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from body_state import place_judoka
from kuzushi import KuzushiSource
from compromised_state import (
    self_inflicted_kuzushi_event, _rotate_rel_to_mat,
    BASE_SELF_INFLICTED_KUZUSHI_FORCE, COMPROMISED_STATE_CONFIGS,
)
from failure_resolution import FailureResolution, apply_failure_resolution
from throw_templates import FailureOutcome
import main as main_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _tori(facing=(1.0, 0.0)):
    t = main_module.build_tanaka()
    place_judoka(t, com_position=(0.0, 0.0), facing=facing)
    return t


def _resolution(outcome, recovery=2):
    return FailureResolution(
        outcome=outcome, recovery_ticks=recovery,
        failed_dimension="kuzushi", dimension_score=0.0,
    )


# ---------------------------------------------------------------------------
# 1. Enum
# ---------------------------------------------------------------------------
def test_self_inflicted_source_registered() -> None:
    assert hasattr(KuzushiSource, "SELF_INFLICTED")
    assert hasattr(KuzushiSource, "THROW_RESOLUTION")


# ---------------------------------------------------------------------------
# 2. Builder — which outcomes emit
# ---------------------------------------------------------------------------
def test_compromised_outcome_emits_self_inflicted_event() -> None:
    t = _tori()
    ev = self_inflicted_kuzushi_event(
        t, FailureOutcome.TORI_COMPROMISED_FORWARD_LEAN, current_tick=7,
    )
    assert ev is not None
    assert ev.source_kind == KuzushiSource.SELF_INFLICTED
    assert ev.tick_emitted == 7
    assert ev.magnitude > 0.0


def test_clean_reset_emits_nothing() -> None:
    t = _tori()
    assert self_inflicted_kuzushi_event(
        t, FailureOutcome.STANCE_RESET, current_tick=0,
    ) is None


def test_tactical_drop_emits_nothing() -> None:
    """HAJ-50 intent preserved: a tactical drop carries no self-inflicted
    kuzushi (severity 0) — nothing to fold into the buffer."""
    t = _tori()
    assert self_inflicted_kuzushi_event(
        t, FailureOutcome.TACTICAL_DROP_RESET, current_tick=0,
    ) is None


def test_blocked_by_hip_emits_nothing() -> None:
    t = _tori()
    assert self_inflicted_kuzushi_event(
        t, FailureOutcome.BLOCKED_BY_HIP, current_tick=0,
    ) is None


# ---------------------------------------------------------------------------
# 3. Magnitude — severity ordering
# ---------------------------------------------------------------------------
def test_magnitude_tracks_severity() -> None:
    """Maximum-vulnerability (both knees) outranks the lightest (sweep
    rebound) state, matching the per-config severity weights."""
    t = _tori()
    both_knees = self_inflicted_kuzushi_event(
        t, FailureOutcome.TORI_ON_BOTH_KNEES_UKE_STANDING, current_tick=0,
    )
    sweep = self_inflicted_kuzushi_event(
        t, FailureOutcome.TORI_SWEEP_BOUNCES_OFF, current_tick=0,
    )
    assert both_knees.magnitude > sweep.magnitude


def test_magnitude_scales_from_base_and_severity() -> None:
    t = _tori()
    cfg = COMPROMISED_STATE_CONFIGS[FailureOutcome.TORI_COMPROMISED_FORWARD_LEAN]
    ev = self_inflicted_kuzushi_event(
        t, FailureOutcome.TORI_COMPROMISED_FORWARD_LEAN, current_tick=0,
    )
    expected = BASE_SELF_INFLICTED_KUZUSHI_FORCE * cfg.kuzushi_severity
    assert math.isclose(ev.magnitude, expected, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# 4. Direction — facing-relative → mat frame
# ---------------------------------------------------------------------------
def test_forward_lean_breaks_along_facing() -> None:
    """A purely-forward (1,0)-relative break rotates to the mat-frame
    facing direction."""
    ev_x = self_inflicted_kuzushi_event(
        _tori(facing=(1.0, 0.0)),
        FailureOutcome.TORI_COMPROMISED_FORWARD_LEAN, current_tick=0,
    )
    assert math.isclose(ev_x.vector[0], 1.0, abs_tol=1e-9)
    assert math.isclose(ev_x.vector[1], 0.0, abs_tol=1e-9)

    ev_y = self_inflicted_kuzushi_event(
        _tori(facing=(0.0, 1.0)),
        FailureOutcome.TORI_COMPROMISED_FORWARD_LEAN, current_tick=0,
    )
    assert math.isclose(ev_y.vector[0], 0.0, abs_tol=1e-9)
    assert math.isclose(ev_y.vector[1], 1.0, abs_tol=1e-9)


def test_single_support_breaks_toward_airborne_side() -> None:
    """Right foot airborne → break has a component toward tori's right.
    With facing +x, tori's right is -y in the mat frame."""
    ev = self_inflicted_kuzushi_event(
        _tori(facing=(1.0, 0.0)),
        FailureOutcome.TORI_COMPROMISED_SINGLE_SUPPORT, current_tick=0,
    )
    assert ev.vector[1] < 0.0


def test_rotation_helper_is_unit() -> None:
    v = _rotate_rel_to_mat((0.3, -0.95), (1.0, 0.0))
    assert math.isclose(math.hypot(*v), 1.0, abs_tol=1e-9)


def test_rotation_helper_zero_facing_returns_zero() -> None:
    assert _rotate_rel_to_mat((1.0, 0.0), (0.0, 0.0)) == (0.0, 0.0)


# ---------------------------------------------------------------------------
# 5. Integration — apply_failure_resolution records into tori's buffer
# ---------------------------------------------------------------------------
def test_apply_failure_resolution_records_self_inflicted() -> None:
    t = _tori()
    pre = len(t.kuzushi_events)
    apply_failure_resolution(
        _resolution(FailureOutcome.TORI_COMPROMISED_FORWARD_LEAN),
        t, composure_drop=0.0, current_tick=12,
    )
    assert len(t.kuzushi_events) == pre + 1
    ev = t.kuzushi_events[-1]
    assert ev.source_kind == KuzushiSource.SELF_INFLICTED
    assert ev.tick_emitted == 12


def test_apply_failure_resolution_clean_reset_records_nothing() -> None:
    t = _tori()
    pre = len(t.kuzushi_events)
    apply_failure_resolution(
        _resolution(FailureOutcome.STANCE_RESET, recovery=0),
        t, composure_drop=0.0, current_tick=3,
    )
    assert len(t.kuzushi_events) == pre


def test_self_inflicted_decays_in_buffer() -> None:
    """The recorded event participates in the decaying compromised_state
    read like any other source."""
    from kuzushi import compromised_state
    t = _tori()
    apply_failure_resolution(
        _resolution(FailureOutcome.TORI_ON_BOTH_KNEES_UKE_STANDING),
        t, composure_drop=0.0, current_tick=0,
    )
    fresh = compromised_state(t.kuzushi_events, current_tick=0)
    faded = compromised_state(t.kuzushi_events, current_tick=10)
    assert fresh.total_decayed_magnitude > faded.total_decayed_magnitude > 0.0


if __name__ == "__main__":
    import traceback
    passed = failed = 0
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
