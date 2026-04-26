# test_kuzushi_signature_read.py — HAJ-132 acceptance tests.
#
# The polarity reversal: throws fire because pull events composed in
# uke's buffer, NOT because uke happens to be moving this tick.
#
# Covers:
#   - Throw fires when buffer events compose to match the throw's signature,
#     even if uke's CoM velocity is zero (the keystone test).
#   - Throw does NOT fire on a CoM-velocity spike that has no corresponding
#     pull-event history (the inverse keystone test).
#   - Decay matters: a stale pull event scores lower than a fresh one.
#   - Direction matters: misaligned events get a low direction score.
#   - current_tick threading: signature_match queries the buffer at the
#     tick passed in, so the same buffer scores differently as time advances.

import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from body_state import place_judoka
from enums import (
    BodyPart, GripDepth, GripMode, GripTarget, GripTypeV2,
)
from grip_graph import GripEdge, GripGraph
from kuzushi import (
    KuzushiEvent, KuzushiSource,
    KUZUSHI_PER_MPS, record_kuzushi_event, seed_kuzushi_from_velocity,
)
from throw_signature import match_kuzushi_vector, signature_match
from worked_throws import UCHI_MATA, O_SOTO_GARI, SEOI_NAGE_MOROTE
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


def _seat_uchi_mata_grips(graph, attacker, defender):
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


# ---------------------------------------------------------------------------
# POLARITY REVERSAL — KEYSTONE TESTS
# ---------------------------------------------------------------------------
class TestKeystone:
    def test_throw_fires_on_composed_buffer_with_zero_com_velocity(self):
        """The headline HAJ-132 behavior: pull events compose in uke's buffer
        and the throw's kuzushi-vector dim scores high, even though uke's
        instantaneous CoM velocity is exactly zero.

        Pre-HAJ-132 this was impossible: kuzushi-vector read only com_velocity.
        """
        t, s = _pair()
        g = GripGraph()
        _seat_uchi_mata_grips(g, t, s)

        # Compose three forward-kuzushi pull events into Sato's buffer.
        # Sato faces (-1, 0) so a mat-frame -X kuzushi is +X in body frame.
        for i in range(3):
            record_kuzushi_event(s, KuzushiEvent(
                tick_emitted=10 + i, vector=(-1.0, 0.0),
                magnitude=30.0, source_kind=KuzushiSource.PULL,
            ))

        # Critical: Sato's CoM velocity is exactly zero.
        s.state.body_state.com_velocity = (0.0, 0.0)

        score = signature_match(UCHI_MATA, t, s, g, current_tick=12)
        assert score >= UCHI_MATA.commit_threshold, (
            f"Polarity reversal broken: signature {score} below threshold "
            f"{UCHI_MATA.commit_threshold} despite composed buffer"
        )

    def test_kuzushi_dim_zero_on_com_velocity_spike_without_buffer(self):
        """The inverse keystone: a momentary CoM-velocity spike with NO
        corresponding pull events in the buffer must produce zero kuzushi-
        vector score. Pre-HAJ-132 the same setup produced a near-1.0 score.

        We assert on the dimension directly rather than the composed
        signature — composed signature can clear threshold from other
        dimensions alone (force/body/posture); the polarity reversal
        claim is specifically about what the kuzushi dimension reads.
        """
        t, s = _pair()
        # Buffer is empty; CoM velocity is large and well-aligned.
        assert len(s.kuzushi_events) == 0
        s.state.body_state.com_velocity = (-1.0, 0.0)  # huge forward velocity

        # Kuzushi-vector dim now reads the buffer, not com_velocity.
        k = match_kuzushi_vector(UCHI_MATA, t, s, current_tick=0)
        assert k == 0.0, (
            f"Kuzushi dim must be zero with empty buffer regardless of "
            f"CoM velocity (got {k}). Polarity reversal not in effect."
        )

    def test_kuzushi_dim_high_when_buffer_composes_with_zero_velocity(self):
        """Companion to the above: with com_velocity at zero and a strong
        composed buffer, the kuzushi-vector dim scores high. The two tests
        together prove the read source switched from com_velocity to buffer.
        """
        t, s = _pair()
        s.state.body_state.com_velocity = (0.0, 0.0)
        for i in range(3):
            record_kuzushi_event(s, KuzushiEvent(
                tick_emitted=10 + i, vector=(-1.0, 0.0),
                magnitude=30.0, source_kind=KuzushiSource.PULL,
            ))
        k = match_kuzushi_vector(UCHI_MATA, t, s, current_tick=12)
        assert k >= 0.9


# ---------------------------------------------------------------------------
# DECAY — fresh vs stale events
# ---------------------------------------------------------------------------
class TestDecayInfluence:
    def test_stale_event_scores_lower_than_fresh_event(self):
        t, s = _pair()
        # Same single-event buffer, queried at two different ticks.
        record_kuzushi_event(s, KuzushiEvent(
            tick_emitted=0, vector=(-1.0, 0.0),
            magnitude=80.0, source_kind=KuzushiSource.PULL,
        ))
        fresh = match_kuzushi_vector(UCHI_MATA, t, s, current_tick=0)
        stale = match_kuzushi_vector(UCHI_MATA, t, s, current_tick=20)
        assert stale < fresh

    def test_old_buffer_below_throw_threshold_after_long_gap(self):
        t, s = _pair()
        record_kuzushi_event(s, KuzushiEvent(
            tick_emitted=0, vector=(-1.0, 0.0),
            magnitude=40.0, source_kind=KuzushiSource.PULL,
        ))
        # 20 ticks later: 0.5 ** (20/5) = 0.0625 → ~2.5 effective magnitude.
        # Conversion via KUZUSHI_PER_MPS: 2.5 / 100 = 0.025 m/s equivalent,
        # well below Uchi-mata's 0.4 m/s threshold → low magnitude score.
        cv_mag_thresh = UCHI_MATA.kuzushi_requirement.min_velocity_magnitude
        assert cv_mag_thresh > 0
        late = match_kuzushi_vector(UCHI_MATA, t, s, current_tick=20)
        # Direction may still align; magnitude term will be small.
        # Score is 0.5 * dir + 0.5 * mag, so mag ≈ 0.06 caps score at ~0.53.
        assert late < 0.6


# ---------------------------------------------------------------------------
# DIRECTION — misalignment penalty
# ---------------------------------------------------------------------------
class TestDirection:
    def test_misaligned_buffer_scores_lower_than_aligned(self):
        t, s = _pair()
        # Sato faces (-1, 0). +X body = forward = mat -X. UCHI_MATA wants
        # forward kuzushi.
        s_aligned = main_module.build_sato()
        place_judoka(s_aligned, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
        seed_kuzushi_from_velocity(s_aligned, (-0.6, 0.0))  # forward in body frame

        s_misaligned = main_module.build_sato()
        place_judoka(s_misaligned, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
        seed_kuzushi_from_velocity(s_misaligned, (0.6, 0.0))  # backward in body frame

        aligned   = match_kuzushi_vector(UCHI_MATA, t, s_aligned, current_tick=0)
        misaligned = match_kuzushi_vector(UCHI_MATA, t, s_misaligned, current_tick=0)
        assert misaligned < aligned


# ---------------------------------------------------------------------------
# COMPOSITION — multiple events stack
# ---------------------------------------------------------------------------
class TestComposition:
    def test_multiple_aligned_events_score_higher_than_one(self):
        t, s_one  = _pair()
        _, s_many = _pair()
        # Single event vs three events of same direction.
        record_kuzushi_event(s_one, KuzushiEvent(
            tick_emitted=0, vector=(-1.0, 0.0),
            magnitude=30.0, source_kind=KuzushiSource.PULL,
        ))
        for i in range(3):
            record_kuzushi_event(s_many, KuzushiEvent(
                tick_emitted=i, vector=(-1.0, 0.0),
                magnitude=30.0, source_kind=KuzushiSource.PULL,
            ))
        one  = match_kuzushi_vector(UCHI_MATA, t, s_one,  current_tick=2)
        many = match_kuzushi_vector(UCHI_MATA, t, s_many, current_tick=2)
        assert many >= one

    def test_opposing_events_partially_cancel(self):
        t, s = _pair()
        # Equal-and-opposite events at the same tick → resultant zero.
        record_kuzushi_event(s, KuzushiEvent(
            tick_emitted=0, vector=(-1.0, 0.0),
            magnitude=50.0, source_kind=KuzushiSource.PULL,
        ))
        record_kuzushi_event(s, KuzushiEvent(
            tick_emitted=0, vector=(1.0, 0.0),
            magnitude=50.0, source_kind=KuzushiSource.PULL,
        ))
        score = match_kuzushi_vector(UCHI_MATA, t, s, current_tick=0)
        # Direction score collapses to 0 (zero resultant); Couple magnitude
        # check uses cs.magnitude (the resultant's length, also 0). Both
        # halves of the formula go to 0.
        assert score == 0.0


# ---------------------------------------------------------------------------
# LEVER PATH — buffer drives the displacement substitute
# ---------------------------------------------------------------------------
class TestLeverPath:
    def test_lever_throw_fires_on_buffered_kuzushi(self):
        """Lever throws now use the same buffer-magnitude path (with
        KUZUSHI_PER_M conversion) instead of CoM-displacement-past-envelope.
        Seeding a strong forward event should let SEOI_NAGE_MOROTE clear
        its kuzushi-vector dimension."""
        t, s = _pair()
        # Drop tori below uke for fulcrum geometry.
        t.state.body_state.com_height = s.state.body_state.com_height - 0.20
        # Strong forward kuzushi event.
        seed_kuzushi_from_velocity(s, (-0.6, 0.0))
        k = match_kuzushi_vector(SEOI_NAGE_MOROTE, t, s, current_tick=0)
        assert k > 0.5
