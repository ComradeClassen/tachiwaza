# test_kuzushi_debug_hygiene.py — HAJ-227 acceptance tests.
#
# The off-balance *mechanic* is correct; this ticket is presentation +
# buffer-lifecycle hygiene for the raw `[kuzushi] buf …` debug readout.
#
# Covers:
#   - Buffer is cleared on every hard boundary:
#       * _reset_dyad_to_distant (matte / post-score / reset-to-standing)
#       * _end_match (match end)
#   - _print_kuzushi_buffer_debug is gated:
#       * off the default stream entirely (requires --stream debug AND
#         the dedicated --debug-kuzushi flag)
#       * silent after match end
#       * silent in ne-waza (off the feet)
#       * silent with zero grips established
#       * emits only on standing play with live grips and the flag set

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from enums import (
    BeltRank, BodyArchetype, DominantSide, GripDepth, GripMode, GripTypeV2,
    SubLoopState,
)
from kuzushi import KuzushiEvent, KuzushiSource


# ---------------------------------------------------------------------------
# FIXTURES
# ---------------------------------------------------------------------------
def _build_judoka(name="Test", belt=BeltRank.BLACK_1):
    from judoka import BODY_PARTS, Capability, Identity, Judoka, State
    identity = Identity(
        name=name, age=25, weight_class="-73kg", height_cm=175,
        body_archetype=BodyArchetype.GRIP_FIGHTER, belt_rank=belt,
        dominant_side=DominantSide.RIGHT,
    )
    cap_kwargs = {part: 7 for part in BODY_PARTS}
    cap = Capability(
        **cap_kwargs, cardio_capacity=7, cardio_efficiency=7,
        composure_ceiling=7, fight_iq=7, ne_waza_skill=7,
    )
    state = State.fresh(cap, identity)
    return Judoka(identity=identity, capability=cap, state=state)


def _make_referee():
    from referee import Referee
    return Referee(name="Suzuki-sensei", nationality="JPN")


def _make_match(stream="both", debug_kuzushi=False):
    from match import Match
    a = _build_judoka("Aoi")
    b = _build_judoka("Beni")
    match = Match(
        fighter_a=a, fighter_b=b, referee=_make_referee(),
        stream=stream, debug_kuzushi=debug_kuzushi,
    )
    return match


def _seed_event(fighter, tick=0, mag=120.0):
    """Drop one live impulse into a fighter's buffer."""
    fighter.kuzushi_events.append(KuzushiEvent(
        tick_emitted=tick, vector=(1.0, 0.0), magnitude=mag,
        source_kind=KuzushiSource.PULL,
    ))


def _seat_a_grip(match):
    """Establish one live grip edge so the grip-presence gate passes."""
    from grip_graph import GripEdge
    from enums import BodyPart, GripTarget
    match.grip_graph.add_edge(GripEdge(
        grasper_id="Aoi", grasper_part=BodyPart.RIGHT_HAND,
        target_id="Beni", target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_LOW, depth_level=GripDepth.STANDARD,
        strength=1.0, established_tick=0, mode=GripMode.CONNECTIVE,
    ))


# ---------------------------------------------------------------------------
# BUFFER CLEAR AT BOUNDARIES
# ---------------------------------------------------------------------------
class TestBufferClearedAtBoundaries:
    def test_reset_to_distant_clears_buffer(self):
        # _reset_dyad_to_distant is the shared matte / post-score /
        # reset-to-standing path — clearing here covers all three.
        match = _make_match()
        _seed_event(match.fighter_a)
        _seed_event(match.fighter_b)
        assert match.fighter_a.kuzushi_events
        assert match.fighter_b.kuzushi_events

        match._reset_dyad_to_distant(tick=10)

        assert len(match.fighter_a.kuzushi_events) == 0
        assert len(match.fighter_b.kuzushi_events) == 0

    def test_handle_matte_clears_buffer(self):
        match = _make_match()
        _seed_event(match.fighter_a, tick=12)
        _seed_event(match.fighter_b, tick=12)

        match._handle_matte(tick=13)

        assert len(match.fighter_a.kuzushi_events) == 0
        assert len(match.fighter_b.kuzushi_events) == 0

    def test_end_match_clears_buffer(self):
        match = _make_match()
        _seed_event(match.fighter_a, tick=45)
        _seed_event(match.fighter_b, tick=45)

        match._end_match(
            winner=match.fighter_a, method="ippon", tick=47, events=[],
        )

        assert match.match_over is True
        assert len(match.fighter_a.kuzushi_events) == 0
        assert len(match.fighter_b.kuzushi_events) == 0


# ---------------------------------------------------------------------------
# PRINT GATING
# ---------------------------------------------------------------------------
class TestDebugPrintGating:
    def test_off_default_stream(self, capsys):
        # Default stream ("both") + no flag → nothing, even with a live
        # buffer and grips.
        match = _make_match(stream="both", debug_kuzushi=False)
        _seat_a_grip(match)
        _seed_event(match.fighter_a, tick=5)

        match._print_kuzushi_buffer_debug(tick=5)

        assert capsys.readouterr().out == ""

    def test_debug_stream_without_flag_is_silent(self, capsys):
        # Engineer stream alone is not enough — the dedicated verbosity
        # flag is required.
        match = _make_match(stream="debug", debug_kuzushi=False)
        _seat_a_grip(match)
        _seed_event(match.fighter_a, tick=5)

        match._print_kuzushi_buffer_debug(tick=5)

        assert capsys.readouterr().out == ""

    def test_emits_on_standing_with_grips_and_flag(self, capsys):
        match = _make_match(stream="debug", debug_kuzushi=True)
        match.sub_loop_state = SubLoopState.STANDING
        _seat_a_grip(match)
        _seed_event(match.fighter_a, tick=5)

        match._print_kuzushi_buffer_debug(tick=5)

        out = capsys.readouterr().out
        assert "[kuzushi]" in out
        assert "buf" in out

    def test_silent_after_match_over(self, capsys):
        match = _make_match(stream="debug", debug_kuzushi=True)
        match.sub_loop_state = SubLoopState.STANDING
        _seat_a_grip(match)
        _seed_event(match.fighter_a, tick=5)
        match.match_over = True

        match._print_kuzushi_buffer_debug(tick=5)

        assert capsys.readouterr().out == ""

    def test_silent_in_newaza(self, capsys):
        match = _make_match(stream="debug", debug_kuzushi=True)
        match.sub_loop_state = SubLoopState.NE_WAZA
        _seat_a_grip(match)
        _seed_event(match.fighter_a, tick=5)

        match._print_kuzushi_buffer_debug(tick=5)

        assert capsys.readouterr().out == ""

    def test_silent_with_zero_grips(self, capsys):
        # Decayed impulses from a prior exchange with no live grip are a
        # ghost, not a live signal.
        match = _make_match(stream="debug", debug_kuzushi=True)
        match.sub_loop_state = SubLoopState.STANDING
        _seed_event(match.fighter_a, tick=5)
        assert match.grip_graph.edge_count() == 0

        match._print_kuzushi_buffer_debug(tick=5)

        assert capsys.readouterr().out == ""
