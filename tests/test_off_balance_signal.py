# tests/test_off_balance_signal.py
# B-3 — the off-balance signal (KUZUSHI_INDUCED + defensive-pressure feed)
# reads the decaying kuzushi buffer instead of the CoM-envelope predicate.
#
# The match layer's Step-9 check now calls Match._check_off_balance, which
# fires when compromised_state(buffer).magnitude crosses
# OFF_BALANCE_MAGNITUDE_THRESHOLD (edge-triggered per fighter) and exposes the
# dominant source + resultant direction on the event so narration can name a
# cause. is_kuzushi is kept (B-4 retires it) but no longer drives this signal.

from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from body_state import place_judoka
from kuzushi import (
    KuzushiEvent, KuzushiSource, record_kuzushi_event,
    compromised_state, dominant_kuzushi_source,
    OFF_BALANCE_MAGNITUDE_THRESHOLD,
)
from match import Match, _off_balance_cause_suffix
from referee import build_suzuki
import main as main_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _pair_match():
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    m = Match(fighter_a=t, fighter_b=s, referee=build_suzuki())
    return t, s, m


def _seed(fighter, magnitude, tick, source=KuzushiSource.PULL, vector=(1.0, 0.0)):
    record_kuzushi_event(fighter, KuzushiEvent(
        tick_emitted=tick, vector=vector, magnitude=magnitude, source_kind=source,
    ))


_ABOVE = OFF_BALANCE_MAGNITUDE_THRESHOLD + 20.0
_BELOW = OFF_BALANCE_MAGNITUDE_THRESHOLD - 20.0


# ---------------------------------------------------------------------------
# 1. Threshold constant
# ---------------------------------------------------------------------------
def test_threshold_is_positive() -> None:
    assert OFF_BALANCE_MAGNITUDE_THRESHOLD > 0.0


# ---------------------------------------------------------------------------
# 2. Fires above threshold, silent below
# ---------------------------------------------------------------------------
def test_fires_when_buffer_above_threshold() -> None:
    t, s, m = _pair_match()
    _seed(t, _ABOVE, tick=0)
    events: list = []
    m._check_off_balance(tick=0, events=events)
    kz = [e for e in events if e.event_type == "KUZUSHI_INDUCED"]
    assert len(kz) == 1
    assert kz[0].data["fighter"] == t.identity.name
    assert m._a_was_kuzushi_last_tick is True


def test_silent_when_buffer_below_threshold() -> None:
    t, s, m = _pair_match()
    _seed(t, _BELOW, tick=0)
    events: list = []
    m._check_off_balance(tick=0, events=events)
    assert not [e for e in events if e.event_type == "KUZUSHI_INDUCED"]
    assert m._a_was_kuzushi_last_tick is False


# ---------------------------------------------------------------------------
# 3. Edge-trigger semantics
# ---------------------------------------------------------------------------
def test_edge_triggered_fires_once_while_sustained() -> None:
    """Stays above threshold across two ticks → fires only on the crossing
    tick, not the second."""
    t, s, m = _pair_match()
    # A big event at tick 0; still above threshold a tick later after decay.
    _seed(t, 200.0, tick=0)
    ev1: list = []
    m._check_off_balance(tick=0, events=ev1)
    ev2: list = []
    m._check_off_balance(tick=1, events=ev2)
    assert len([e for e in ev1 if e.event_type == "KUZUSHI_INDUCED"]) == 1
    assert len([e for e in ev2 if e.event_type == "KUZUSHI_INDUCED"]) == 0


def test_rearms_after_dropping_below() -> None:
    """Fires, decays below threshold, then a fresh spike re-fires."""
    t, s, m = _pair_match()
    _seed(t, _ABOVE, tick=0)
    ev1: list = []
    m._check_off_balance(tick=0, events=ev1)
    # Far in the future the tick-0 event has fully decayed → below threshold.
    ev_decayed: list = []
    m._check_off_balance(tick=40, events=ev_decayed)
    assert m._a_was_kuzushi_last_tick is False
    # New spike re-arms and fires again.
    _seed(t, _ABOVE, tick=41)
    ev2: list = []
    m._check_off_balance(tick=41, events=ev2)
    assert len([e for e in ev2 if e.event_type == "KUZUSHI_INDUCED"]) == 1


# ---------------------------------------------------------------------------
# 4. Event payload + cause naming
# ---------------------------------------------------------------------------
def test_event_exposes_magnitude_vector_source() -> None:
    t, s, m = _pair_match()
    _seed(t, _ABOVE, tick=0, source=KuzushiSource.PULL, vector=(1.0, 0.0))
    events: list = []
    m._check_off_balance(tick=0, events=events)
    data = events[0].data
    assert data["magnitude"] >= OFF_BALANCE_MAGNITUDE_THRESHOLD
    assert data["source"] == "PULL"
    assert isinstance(data["vector"], tuple) and len(data["vector"]) == 2


def test_description_names_cause() -> None:
    t, s, m = _pair_match()
    _seed(t, _ABOVE, tick=0, source=KuzushiSource.FOOT_ATTACK)
    events: list = []
    m._check_off_balance(tick=0, events=events)
    assert "swept off balance" in events[0].description


# ---------------------------------------------------------------------------
# 5. Defensive-pressure feed
# ---------------------------------------------------------------------------
def test_feeds_defensive_pressure() -> None:
    t, s, m = _pair_match()
    pre = len(m._defensive_pressure[t.identity.name].kuzushi_ticks)
    _seed(t, _ABOVE, tick=3)
    m._check_off_balance(tick=3, events=[])
    post = len(m._defensive_pressure[t.identity.name].kuzushi_ticks)
    assert post == pre + 1
    assert 3 in m._defensive_pressure[t.identity.name].kuzushi_ticks


# ---------------------------------------------------------------------------
# 6. dominant_kuzushi_source
# ---------------------------------------------------------------------------
def test_dominant_source_empty_is_none() -> None:
    assert dominant_kuzushi_source([], current_tick=0) is None


def test_dominant_source_picks_largest_decayed() -> None:
    evs = [
        KuzushiEvent(0, (1.0, 0.0), 30.0, KuzushiSource.PULL),
        KuzushiEvent(0, (0.0, 1.0), 80.0, KuzushiSource.FOOT_ATTACK),
    ]
    assert dominant_kuzushi_source(evs, current_tick=0) is KuzushiSource.FOOT_ATTACK


def test_dominant_source_respects_decay() -> None:
    """A small fresh event can outweigh a large stale one."""
    evs = [
        KuzushiEvent(0,  (1.0, 0.0), 100.0, KuzushiSource.PULL),         # very stale
        KuzushiEvent(30, (0.0, 1.0), 40.0,  KuzushiSource.SELF_INFLICTED),  # fresh
    ]
    assert dominant_kuzushi_source(evs, current_tick=30) is KuzushiSource.SELF_INFLICTED


# ---------------------------------------------------------------------------
# 7. cause-suffix mapping
# ---------------------------------------------------------------------------
def test_cause_suffix_mapping() -> None:
    assert "pulled" in _off_balance_cause_suffix(KuzushiSource.PULL)
    assert "swept" in _off_balance_cause_suffix(KuzushiSource.FOOT_ATTACK)
    assert "over-committed" in _off_balance_cause_suffix(KuzushiSource.SELF_INFLICTED)
    assert "driven" in _off_balance_cause_suffix(KuzushiSource.THROW_RESOLUTION)
    assert _off_balance_cause_suffix(None) == ""


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
