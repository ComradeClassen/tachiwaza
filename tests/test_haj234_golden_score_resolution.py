# tests/test_haj234_golden_score_resolution.py
# HAJ-234 — Golden score: sudden-death RESOLUTION (replaces the "Phase 3"
# draw stub). HAJ-93 wired GS entry + first-score/third-shido endings; this
# file covers the gap: the match must actually run the sudden-death clock to
# a decision instead of returning "Match drawn 0-0. Golden score pending
# (Phase 3)." the instant regulation expires level.
#
# Acceptance criteria covered:
#   1. A level-score regulation end continues into a real GS period (the loop
#      no longer terminates at max_ticks while GS is live).
#   3. GS termination policy: capped window with a shido-tiebreak decision /
#      draw fallback (see GOLDEN_SCORE_MAX_TICKS).
#   4. The "Golden score pending (Phase 3)." string is gone from the live path.
#   5. A seeded match that ends regulation 0-0 plays out to a GS decision.

from __future__ import annotations
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from body_state import place_judoka
from match import Match, GOLDEN_SCORE_MAX_TICKS
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


def _match(regulation_ticks: int = 240, max_ticks: int | None = None,
           golden_score_ticks: int | None = None, seed: int = 1) -> tuple:
    random.seed(seed)
    t, s = _pair()
    if max_ticks is None:
        max_ticks = regulation_ticks
    m = Match(
        fighter_a=t, fighter_b=s, referee=build_suzuki(),
        regulation_ticks=regulation_ticks, max_ticks=max_ticks,
        golden_score_ticks=golden_score_ticks, seed=seed,
    )
    return t, s, m


def _silence(m: Match) -> None:
    m._print_events = lambda evs: None
    m._print_header = lambda: None


# ===========================================================================
# AC#1 — the loop keeps running past max_ticks once GS is live
# ===========================================================================
def test_is_done_false_immediately_after_golden_score_starts() -> None:
    """Default config (regulation == max_ticks): GS flips on the final
    regulation tick, but is_done must NOT terminate the match — the GS window
    has not opened yet. This is the exact bug the Phase-3 stub masked."""
    t, s, m = _match(regulation_ticks=240, max_ticks=240)
    m.golden_score = True
    m.golden_score_start_tick = 240
    m.ticks_run = 240  # at/over max_ticks, but GS just began
    assert m.is_done() is False


def test_is_done_true_when_golden_score_cap_reached() -> None:
    t, s, m = _match(regulation_ticks=240, max_ticks=240,
                     golden_score_ticks=100)
    m.golden_score = True
    m.golden_score_start_tick = 240
    m.ticks_run = 240 + 100
    assert m.is_done() is True


def test_default_golden_score_window_is_the_documented_cap() -> None:
    _, _, m = _match(regulation_ticks=240, max_ticks=240)
    assert m.golden_score_ticks == GOLDEN_SCORE_MAX_TICKS


# ===========================================================================
# AC#3 — capped-window termination policy: shido tiebreak / draw
# ===========================================================================
def test_cap_decides_on_fewer_shidos() -> None:
    t, s, m = _match(regulation_ticks=240, max_ticks=240,
                     golden_score_ticks=100)
    m.golden_score = True
    m.golden_score_start_tick = 240
    t.state.shidos = 1
    s.state.shidos = 2  # Sato carries more shidos -> loses the decision
    events: list = []
    m._resolve_golden_score_cap(tick=340, events=events)

    assert m.match_over is True
    assert m.winner is t
    assert m.win_method == "decision (golden score)"

    decided = [e for e in events if e.event_type == "GOLDEN_SCORE_DECISION"]
    assert len(decided) == 1
    assert decided[0].data["winner"] == t.identity.name
    ended = [e for e in events if e.event_type == "MATCH_ENDED"]
    assert len(ended) == 1
    assert ended[0].data["method"] == "decision (golden score)"
    assert ended[0].data["golden_score"] is True


def test_cap_with_level_shidos_is_a_draw() -> None:
    t, s, m = _match(regulation_ticks=240, max_ticks=240,
                     golden_score_ticks=100)
    m.golden_score = True
    m.golden_score_start_tick = 240
    t.state.shidos = 1
    s.state.shidos = 1
    events: list = []
    m._resolve_golden_score_cap(tick=340, events=events)

    assert m.match_over is True
    assert m.winner is None
    assert m.win_method == "draw"
    draws = [e for e in events if e.event_type == "GOLDEN_SCORE_DRAW"]
    assert len(draws) == 1
    ended = [e for e in events if e.event_type == "MATCH_ENDED"]
    assert len(ended) == 1
    assert ended[0].data["winner"] is None
    assert ended[0].data["method"] == "draw"


# ===========================================================================
# AC#4 — the "Phase 3" string is gone from the live draw path
# ===========================================================================
def test_phase_3_string_removed_from_draw_summary() -> None:
    t, s, m = _match(regulation_ticks=240, max_ticks=240)
    m.golden_score = True
    m.win_method = "draw"
    summary = m._compose_match_summary()
    joined = " ".join(summary)
    assert "Phase 3" not in joined
    assert "golden score" in joined.lower()


def test_phase_3_stub_string_absent_from_source() -> None:
    """Belt-and-suspenders: the literal "Golden score pending (Phase 3)."
    stub must not survive anywhere in the engine module."""
    src = os.path.join(os.path.dirname(__file__), "..", "src", "match.py")
    with open(src, "r", encoding="utf-8") as f:
        text = f.read()
    assert "Golden score pending" not in text


# ===========================================================================
# AC#5 — seeded full match: regulation ends 0-0, GS runs to a decision
# ===========================================================================
def test_seeded_regulation_0_0_plays_out_to_golden_score_decision() -> None:
    """Short regulation guarantees a 0-0 expiry; the match must then enter
    golden score and terminate with a real decision (a score, a third shido,
    or the shido-tiebreak / draw cap) — never hang and never return the
    Phase-3 stub."""
    t, s, m = _match(regulation_ticks=8, max_ticks=8,
                     golden_score_ticks=80, seed=20260608)
    _silence(m)

    m.begin()
    entered_gs = False
    while not m.is_done():
        m.step()
        if m.golden_score:
            entered_gs = True
    m.end()

    # Regulation expired level, so golden score was entered...
    assert entered_gs is True
    assert t.state.score["waza_ari"] == s.state.score["waza_ari"] == 0 \
        or m.golden_score  # (level at the boundary is what triggers GS)
    # ...and the match reached a real terminal state.
    assert m.match_over is True
    assert m.win_method in {
        "waza-ari (golden score)", "ippon (golden score)",
        "ippon (pin, golden score)", "ippon (submission, golden score)",
        "hansoku-make", "decision (golden score)", "draw",
    }
    summary = " ".join(m._compose_match_summary())
    assert "Phase 3" not in summary
