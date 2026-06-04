# tests/test_haj162_outcome_bound_prose.py
# HAJ-162 — outcome-bound prose: fire prose templates only when their
# event actually occurred.
#
# Two anchor examples from the Sato vs Renard playthrough:
#
#   AC#1 — t003 anchor: "Both fighters lock onto their grips" fired even
#          though grip-initiative variance (HAJ-151) put Sato +4.17 vs
#          Renard +1.41. Only Sato seated grips on the transition tick;
#          the "both" claim was false-by-one-fighter.
#   AC#2 — t011 anchor: throw landing prose surfaced phase tokens
#          ("reach-kuzushi / kuzushi / tsukuri / kake") as separate
#          user-facing lines. They should stay in the debug stream;
#          the coach stream renders one outcome-bound line per resolved
#          throw.
#   AC#3 — Test coverage for both anchor examples (this file).
#   AC#4 — No regressions on existing prose families (covered by the
#          existing prose / narrator suite, run alongside this file).
#   AC#5 — Debug stream preserved: phase-token sub-events still emit
#          on the engineer side.

from __future__ import annotations
import contextlib
import io
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from enums import (
    BeltRank, BodyPart, GripDepth, GripMode, GripTarget, GripTypeV2,
    Position,
)
from grip_graph import GripEdge
from match import Match
from referee import build_suzuki
from throws import ThrowID
import main as main_module
from body_state import place_judoka


# ---------------------------------------------------------------------------
# FIXTURES
# ---------------------------------------------------------------------------
def _pair():
    t = main_module.build_tanaka()
    s = main_module.build_sato()
    place_judoka(t, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(s, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))
    return t, s


def _new_match(seed: int = 1, max_ticks: int = 80, stream: str = "prose"):
    random.seed(seed)
    t, s = _pair()
    m = Match(
        fighter_a=t, fighter_b=s, referee=build_suzuki(),
        max_ticks=max_ticks, seed=seed, stream=stream,
    )
    m._print_header = lambda: None
    return t, s, m


def _seat_one_grip(graph, grasper, target):
    """Hand-seat a single grip from `grasper` onto `target` so the
    transition-tick state reflects an asymmetric cascade where only
    one fighter has gripped."""
    graph.add_edge(GripEdge(
        grasper_id=grasper.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=target.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.STANDARD,
        strength=1.0, established_tick=0, mode=GripMode.DRIVING,
    ))


def _seat_both_grips(graph, a, b):
    """Symmetric seat — both fighters have own-grip edges. The transition
    line should render the canonical 'Both fighters lock' prose."""
    graph.add_edge(GripEdge(
        grasper_id=a.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=b.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.STANDARD,
        strength=1.0, established_tick=0, mode=GripMode.DRIVING,
    ))
    graph.add_edge(GripEdge(
        grasper_id=b.identity.name, grasper_part=BodyPart.RIGHT_HAND,
        target_id=a.identity.name, target_location=GripTarget.LEFT_LAPEL,
        grip_type_v2=GripTypeV2.LAPEL_HIGH, depth_level=GripDepth.STANDARD,
        strength=1.0, established_tick=0, mode=GripMode.DRIVING,
    ))


# ===========================================================================
# AC#1 — initiative-aware grip-seating prose
# ===========================================================================
# HAJ-225 — the first-grip line is now data-driven (grip_narration.yaml) and
# the one-sided case can read as contested. These markers cover every leader-
# first variant (uncontested + contested) so the tests assert the *shape*
# (asymmetric, leader-first) without pinning a single string.
_ASYMMETRIC_FIRST_GRIP_MARKERS = (
    "secures the first grip",   # uncontested
    "wins the lead grip",       # uncontested / contested
    "gets the first grip",      # contested
    "lands the lead grip",      # contested
    "takes the lead hand",      # contested
)


def test_grip_seating_prose_renders_asymmetric_when_only_leader_has_grips() -> None:
    """The t003 anchor: at the cascade-staging tick only the leader has
    seated grips. The transition prose reads as the leader securing the
    first grip — not 'Both fighters lock,' which would be dishonest by
    one fighter. HAJ-225 — string is data-driven; assert the asymmetric
    leader-first shape rather than one exact variant."""
    from narration.altitudes.mat_side import _grip_seating_prose
    t, s, m = _new_match()
    m.begin()
    _seat_one_grip(m.grip_graph, t, s)  # only Tanaka has a grip
    line = _grip_seating_prose(m, tick=3)
    assert line != "Both fighters lock onto their grips."
    assert any(mark in line for mark in _ASYMMETRIC_FIRST_GRIP_MARKERS), (
        f"expected an asymmetric first-grip line; got: {line!r}"
    )
    assert t.identity.name in line
    assert s.identity.name in line
    assert line.startswith(t.identity.name), (
        f"leader's name should lead the line: {line!r}"
    )


def test_grip_seating_prose_renders_canonical_when_both_have_grips() -> None:
    """The both-have-grips path keeps the canonical 'Both fighters lock'
    prose — the asymmetric branch only fires when the cascade is mid-
    flight."""
    from narration.altitudes.mat_side import _grip_seating_prose
    t, s, m = _new_match()
    m.begin()
    _seat_both_grips(m.grip_graph, t, s)
    line = _grip_seating_prose(m, tick=3)
    assert line == "Both fighters lock onto their grips."


def test_grip_seating_prose_handles_either_fighter_as_leader() -> None:
    """Symmetry — the asymmetric line works when either side leads.
    The leader's name appears first; the follower's name appears after."""
    from narration.altitudes.mat_side import _grip_seating_prose
    # Sato leads.
    t, s, m = _new_match(seed=2)
    m.begin()
    _seat_one_grip(m.grip_graph, s, t)
    line = _grip_seating_prose(m, tick=5)
    # Sato leads, Tanaka follows.
    assert line.startswith(s.identity.name)
    assert any(mark in line for mark in _ASYMMETRIC_FIRST_GRIP_MARKERS)
    assert line.index(t.identity.name) > line.index(s.identity.name), (
        f"follower's name should appear after leader's in the line: {line!r}"
    )


# ===========================================================================
# Full-match integration — the live-fire path renders the asymmetric line
# when the cascade lag exposes one-sided seating
# ===========================================================================
def test_full_match_emits_asymmetric_grip_prose_on_first_engagement() -> None:
    """End-to-end: run a real match through the closing phase and
    verify the first grip-seating prose line is the asymmetric variant
    (because Priority-3 grip-cascade lag puts only the leader's grips
    in the graph at the transition tick)."""
    t, s, m = _new_match(seed=11, max_ticks=20, stream="prose")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m.run()
    out = buf.getvalue()
    # The first grip-seating beat should be an asymmetric line, not the
    # canonical "Both fighters lock" claim. HAJ-225 — accept any asymmetric
    # variant (contested or uncontested).
    seating_index = min(
        (out.find(mark) for mark in _ASYMMETRIC_FIRST_GRIP_MARKERS
         if out.find(mark) >= 0),
        default=-1,
    )
    assert seating_index >= 0, (
        f"expected asymmetric grip-seating prose somewhere in:\n{out}"
    )
    # And specifically — the canonical line should NOT precede the
    # asymmetric one for this seed (the cascade has its 2-tick lag).
    canonical_first = out.find("Both fighters lock onto their grips.")
    assert (
        canonical_first < 0 or canonical_first > seating_index
    ), (
        f"canonical line surfaced before the asymmetric line — the "
        f"cascade-lag dishonesty is back. Output:\n{out}"
    )


# ===========================================================================
# AC#2 — phase tokens stay out of the coach (prose) stream
# ===========================================================================
def test_phase_tokens_do_not_surface_in_prose_stream() -> None:
    """The t011 anchor: reach-kuzushi / kuzushi / tsukuri / kake phase
    tokens fire as engineering events on the debug stream. They must
    not surface as user-facing prose lines (AC#2 + AC#5)."""
    t, s, m = _new_match(seed=11, max_ticks=80, stream="prose")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m.run()
    out = buf.getvalue()
    forbidden = ("reach-kuzushi", "— kuzushi", "— tsukuri", "— kake")
    for token in forbidden:
        assert token not in out, (
            f"phase token {token!r} surfaced in the prose stream:\n{out}"
        )


def test_phase_tokens_remain_visible_in_debug_stream() -> None:
    """AC#5 — debug stream preserved. The same match emitted on the
    debug stream still surfaces SUB_REACH_KUZUSHI / SUB_TSUKURI /
    SUB_KAKE_COMMIT lines so engineers can trace the schedule."""
    t, s, m = _new_match(seed=11, max_ticks=80, stream="debug")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m.run()
    out = buf.getvalue()
    # At least one of the phase tokens must appear on the engineer side
    # (commits in any 80-tick match against the canonical pair).
    assert any(
        tok in out
        for tok in ("reach-kuzushi", "kuzushi", "tsukuri", "kake")
    ), (
        f"phase tokens disappeared from the debug stream — AC#5 violation:\n{out}"
    )


def test_throw_commit_event_remains_prose_silent() -> None:
    """The THROW_ENTRY engineering event itself stays prose-silent; the
    visible beat for a commit is the resolution line (THROW_LANDING /
    STUFFED / FAILED) on a later tick. Pre-HAJ-148 fix the commit and
    its resolution co-fired prose lines on the same tick."""
    t, s, m = _new_match(seed=1, max_ticks=80, stream="prose")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m.run()
    out = buf.getvalue()
    # No bare "commits — Throw-name" line surfaces in prose stream.
    # Resolution lines like "stuffed on Uchi-mata" still surface.
    for line in out.splitlines():
        if " commits — " in line and "stuffed" not in line.lower():
            # Drop legitimate resolution lines that happen to include
            # the word "commits" in some other context.
            assert " commits — " not in line, (
                f"raw THROW_ENTRY commit prose surfaced: {line!r}"
            )


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
