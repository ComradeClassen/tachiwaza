# narration/altitudes/broadcast.py
# HAJ-144 acceptance #3 — broadcast-desk altitude.
#
# Voice: broadcast voice — between-matches, multi-match aggregates,
# "Tanaka's looking sharp today". Threshold: 9 (match outcomes, narrative
# trends, signature performances across the day).
#
# Used when the player skims a tournament rather than tracking it. v0.1
# SCAFFOLD ONLY: single-match outcomes only. Multi-match aggregation
# requires tournament-level state and lands when tournaments do
# (Ring 2). The (threshold, voice) pairing is the v0.1 contract.

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from body_part_events import BodyPartEvent
from narration.reader import Reader
from significance import THRESHOLD_BROADCAST

if TYPE_CHECKING:
    from match import Match
    from grip_graph import Event


_BROADCAST_PROMOTABLE_TYPES: frozenset[str] = frozenset({
    "IPPON_AWARDED", "SUBMISSION_VICTORY", "MATCH_OVER",
    "TIME_EXPIRED", "SCORE_AWARDED",
})


def _broadcast_voice(
    event: "Event", bpes: list[BodyPartEvent], match: "Match",
) -> Optional[str]:
    if event.event_type not in _BROADCAST_PROMOTABLE_TYPES:
        return None
    if event.event_type == "IPPON_AWARDED":
        return f"Match decided: {event.description}"
    if event.event_type == "SUBMISSION_VICTORY":
        return f"Submission ends it: {event.description}"
    if event.event_type == "MATCH_OVER":
        return event.description
    return event.description


def build_broadcast_reader(threshold: int = THRESHOLD_BROADCAST) -> Reader:
    return Reader(
        threshold=threshold,
        voice=_broadcast_voice,
        name="broadcast",
    )
