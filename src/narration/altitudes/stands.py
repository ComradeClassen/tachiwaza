# narration/altitudes/stands.py
# HAJ-144 acceptance #3 — stands altitude (announcer voice).
#
# Voice: announcer voice — narrative-arc framing, recognition-driven
# calls, quieter between events than mat-side. Threshold: 4 (only
# higher-significance events render; routine grip war stays silent).
#
# v0.1 SCAFFOLD ONLY. Ring 2 wires this into a player-facing surface
# when the calendar-conflict mechanic forces altitude selection. Tests
# assert the (threshold, voice) pair filters the same event stream
# differently than mat-side.

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from body_part_events import BodyPartEvent
from narration.reader import Reader
from significance import THRESHOLD_STANDS

if TYPE_CHECKING:
    from match import Match
    from grip_graph import Event


_STANDS_PROMOTABLE_TYPES: frozenset[str] = frozenset({
    "SCORE_AWARDED", "IPPON_AWARDED", "THROW_LANDING",
    "COUNTER_COMMIT", "SUBMISSION_VICTORY", "MATTE",
    "OFFENSIVE_DESPERATION_ENTER", "DEFENSIVE_DESPERATION_ENTER",
})


def _stands_voice(
    event: "Event", bpes: list[BodyPartEvent], match: "Match",
) -> Optional[str]:
    """Announcer-voice render. v0.1 collapses to a narrative-framing
    rewrite of the mat-side description for high-significance beats —
    most of the announcer's distinct register (signature anticipation,
    arc framing) needs the recognition mechanic and is HAJ-148+ work."""
    if event.event_type not in _STANDS_PROMOTABLE_TYPES:
        return None
    desc = event.description
    if event.event_type in ("IPPON_AWARDED", "SUBMISSION_VICTORY"):
        return f"And there it is — {desc}"
    if event.event_type == "COUNTER_COMMIT":
        return f"Counter on! {desc}"
    return desc


def build_stands_reader(threshold: int = THRESHOLD_STANDS) -> Reader:
    return Reader(
        threshold=threshold,
        voice=_stands_voice,
        name="stands",
    )
