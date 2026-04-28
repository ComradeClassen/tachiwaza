# tests/test_newaza_escape_rate.py
# HAJ-129 — ne-waza escape to stand up should be rare; matte fires more
# often when the position stalls.
#
# Pre-fix, BASE_ESCAPE_PROB=0.08 + skill bonus produced an escape
# probability of ~0.30-0.40 per tick for an elite from open guard, so a
# typical bottom fighter was back to standing within 2-4 ticks. Real judo:
# escapes from dominant positions are rare; most ne-waza resolves to
# pin/sub or to ref-called matte after a stalemate window.
#
# Post-fix:
#   - Escape probability cut roughly 4x (0.025 base + 0.008 per skill).
#   - stalemate_ticks now increments inside _tick_newaza so the referee's
#     NEWAZA_MATTE_TICKS window can trigger matte.
#   - Escape dispatches through the post-score reset path (recovery
#     bonus + throws_in_progress clear) so no stale aborts fire on the
#     first standing tick after the escape.

from __future__ import annotations
import os
import random as _r
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from body_state import place_judoka
from enums import (
    BodyPart, GripTarget, GripTypeV2, GripDepth, MatteReason, Position,
    SubLoopState,
)
from grip_graph import GripEdge
from match import (
    Match, ENGAGEMENT_TICKS_FLOOR, POST_SCORE_RECOVERY_TICKS,
)
from ne_waza import NewazaResolver
from referee import build_suzuki
from skill_compression import SubEvent
from throws import ThrowID
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


def _enter_ne_waza(m, top, bottom, position=Position.SIDE_CONTROL):
    m.sub_loop_state = SubLoopState.NE_WAZA
    m.position = position
    m.ne_waza_top_id = top.identity.name
    m.ne_waza_resolver.set_top_fighter(
        top.identity.name, (m.fighter_a, m.fighter_b),
    )


# ---------------------------------------------------------------------------
# 1. Escape rates dropped meaningfully.
# ---------------------------------------------------------------------------
def test_escape_rate_well_below_pre_fix() -> None:
    """For a median-skill bottom fighter in SIDE_CONTROL, the per-tick
    escape probability should sit well below the pre-fix ~0.16, around
    or under 0.08. We check by sampling many rolls."""
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    # Median ne_waza_skill (Tanaka and Sato both default to ~5).
    resolver = NewazaResolver()
    _r.seed(0)
    fires = 0
    for _ in range(2000):
        if resolver._roll_escape(s, t, Position.SIDE_CONTROL):
            fires += 1
    rate = fires / 2000
    assert rate < 0.10, f"escape rate {rate:.3f} >= 0.10 (post-fix target)"


def test_elite_escape_rate_still_meaningful() -> None:
    """An elite ne-waza specialist still has a meaningful escape rate
    (we don't want escapes to be impossible) — just much lower than
    pre-fix."""
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    s.capability.ne_waza_skill = 10
    resolver = NewazaResolver()
    _r.seed(0)
    fires = 0
    for _ in range(2000):
        if resolver._roll_escape(s, t, Position.SIDE_CONTROL):
            fires += 1
    rate = fires / 2000
    # Elite SIDE_CONTROL escape rate post-fix sits around 0.04-0.10.
    assert 0.02 < rate < 0.20, f"elite escape rate {rate:.3f} out of range"


# ---------------------------------------------------------------------------
# 2. Stalemate tracking during ne-waza.
# ---------------------------------------------------------------------------
def test_stalemate_increments_during_inactive_ne_waza_tick() -> None:
    """When neither fighter has a pin or active technique and no notable
    event fires, stalemate_ticks must advance during ne-waza so the
    referee's NEWAZA_MATTE_TICKS window can trigger matte. Use GUARD_TOP
    so the resolver's auto-pin-start branch (only fires from
    SIDE_CONTROL/MOUNT/BACK_CONTROL) doesn't seat a pin and trip the
    progress flag."""
    t, s, m = _pair_match()
    _enter_ne_waza(m, top=t, bottom=s, position=Position.GUARD_TOP)
    m.stalemate_ticks = 0
    # Force the resolver to do nothing notable — no active technique,
    # no escape. We monkey-patch the non-deterministic rolls so the tick
    # is genuinely empty.
    m.ne_waza_resolver._roll_escape = lambda *a, **kw: False
    m.ne_waza_resolver._resolve_counter = lambda *a, **kw: False
    import random
    real_random = random.random
    random.random = lambda: 0.99   # suppress technique-attempt roll
    try:
        m._tick_newaza(tick=10, events=[])
        m._tick_newaza(tick=11, events=[])
        m._tick_newaza(tick=12, events=[])
    finally:
        random.random = real_random
    assert m.stalemate_ticks >= 3


def test_stalemate_resets_when_pin_active() -> None:
    """An active pin is progress — stalemate_ticks must not advance."""
    t, s, m = _pair_match()
    _enter_ne_waza(m, top=t, bottom=s)
    m.osaekomi.start(t.identity.name, Position.SIDE_CONTROL)
    m.stalemate_ticks = 5
    # Run one ne-waza tick; pin is active so progress flag fires.
    import random
    real_random = random.random
    random.random = lambda: 0.99   # suppress technique attempts
    try:
        m._tick_newaza(tick=10, events=[])
    finally:
        random.random = real_random
    assert m.stalemate_ticks == 0


# ---------------------------------------------------------------------------
# 3. Matte fires when ne-waza stalls long enough.
# ---------------------------------------------------------------------------
def test_matte_fires_on_ne_waza_stalemate() -> None:
    """Drive enough no-progress ne-waza ticks that stalemate_ticks crosses
    the referee's NEWAZA_MATTE_TICKS threshold; verify the matte path
    triggers and the dyad ends up back in STANDING_DISTANT. Use GUARD_TOP
    so the resolver doesn't auto-seat a pin (which would count as
    progress and reset the stalemate counter)."""
    t, s, m = _pair_match()
    _enter_ne_waza(m, top=t, bottom=s, position=Position.GUARD_TOP)
    m.stalemate_ticks = 0
    m.ne_waza_resolver._roll_escape = lambda *a, **kw: False
    m.ne_waza_resolver._resolve_counter = lambda *a, **kw: False
    import random
    real_random = random.random
    random.random = lambda: 0.99
    try:
        for tick in range(1, 200):
            m._tick(tick)
            if m.match_over:
                break
            if m.position == Position.STANDING_DISTANT:
                break
        else:
            assert False, "matte never fired on stalled ne-waza"
    finally:
        random.random = real_random
    assert m.position == Position.STANDING_DISTANT
    assert m.sub_loop_state == SubLoopState.STANDING


# ---------------------------------------------------------------------------
# 4. Escape routes through the reset helper.
# ---------------------------------------------------------------------------
def test_escape_resets_to_distant_with_recovery_bonus() -> None:
    """When ESCAPE_SUCCESS fires, the dyad must reset to STANDING_DISTANT
    with the post-score recovery bonus and no stale throws_in_progress
    survive into the next standing tick."""
    t, s, m = _pair_match()
    _enter_ne_waza(m, top=t, bottom=s)
    # Park a stranded throw_in_progress that pre-dates ne-waza.
    from match import _ThrowInProgress
    m._throws_in_progress[t.identity.name] = _ThrowInProgress(
        attacker_name=t.identity.name, defender_name=s.identity.name,
        throw_id=ThrowID.O_UCHI_GARI, start_tick=0, compression_n=2,
        schedule={0: [SubEvent.REACH_KUZUSHI]},
        commit_actual=0.6, commit_execution_quality=0.6,
        last_sub_event=SubEvent.REACH_KUZUSHI,
    )
    # Force escape on the next ne-waza tick.
    m.ne_waza_resolver._roll_escape = lambda *a, **kw: True
    m._tick_newaza(tick=10, events=[])
    assert m.position == Position.STANDING_DISTANT
    assert m.sub_loop_state == SubLoopState.STANDING
    # Recovery bonus pre-decremented engagement_ticks.
    assert m.engagement_ticks == -POST_SCORE_RECOVERY_TICKS
    # Stale throw cleared so no spurious abort fires next tick.
    assert m._throws_in_progress == {}


def test_post_escape_no_stale_throw_aborts() -> None:
    """Driving forward a few ticks after escape must not produce
    THROW_ABORTED events for the stranded pre-ne-waza throw."""
    t, s, m = _pair_match()
    _enter_ne_waza(m, top=t, bottom=s)
    from match import _ThrowInProgress
    m._throws_in_progress[t.identity.name] = _ThrowInProgress(
        attacker_name=t.identity.name, defender_name=s.identity.name,
        throw_id=ThrowID.O_UCHI_GARI, start_tick=0, compression_n=2,
        schedule={0: [SubEvent.REACH_KUZUSHI]},
        commit_actual=0.6, commit_execution_quality=0.6,
        last_sub_event=SubEvent.REACH_KUZUSHI,
    )
    m.ne_waza_resolver._roll_escape = lambda *a, **kw: True
    aborts = []
    real_print = m._print_events
    def _capture(events):
        aborts.extend(
            ev for ev in events if ev.event_type == "THROW_ABORTED"
        )
    m._print_events = _capture
    try:
        m._tick_newaza(tick=10, events=[])
        # Now run a few standing ticks — none should produce a stale abort.
        for tick in range(11, 15):
            m._tick(tick)
    finally:
        m._print_events = real_print
    assert not aborts, f"stale throw aborts fired: {aborts}"


# ---------------------------------------------------------------------------
# 5. Stuffed-throw ne-waza entry clears OTHER fighters' throws.
# ---------------------------------------------------------------------------
def test_ne_waza_entry_drops_other_fighter_throws() -> None:
    """If both fighters have throws stashed and a stuffed-throw transition
    fires, only the attacker's entry survives (the caller still owns its
    deletion); the other fighter's throw is dropped so it can't surface
    as a stale abort post-escape."""
    t, s, m = _pair_match()
    from match import _ThrowInProgress
    # Both fighters have multi-tick throws stashed.
    m._throws_in_progress[t.identity.name] = _ThrowInProgress(
        attacker_name=t.identity.name, defender_name=s.identity.name,
        throw_id=ThrowID.UCHI_MATA, start_tick=0, compression_n=2,
        schedule={0: [SubEvent.REACH_KUZUSHI]},
        commit_actual=0.6, commit_execution_quality=0.6,
        last_sub_event=SubEvent.REACH_KUZUSHI,
    )
    m._throws_in_progress[s.identity.name] = _ThrowInProgress(
        attacker_name=s.identity.name, defender_name=t.identity.name,
        throw_id=ThrowID.O_SOTO_GARI, start_tick=0, compression_n=2,
        schedule={0: [SubEvent.REACH_KUZUSHI]},
        commit_actual=0.6, commit_execution_quality=0.6,
        last_sub_event=SubEvent.REACH_KUZUSHI,
    )
    # Force the ground commit to fire deterministically.
    m.ne_waza_resolver.attempt_ground_commit = lambda *a, **kw: True
    m._resolve_newaza_transition(aggressor=t, defender=s, tick=10)
    assert m.sub_loop_state == SubLoopState.NE_WAZA
    # Attacker's entry preserved for the caller to clean up; defender's gone.
    assert t.identity.name in m._throws_in_progress
    assert s.identity.name not in m._throws_in_progress


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
