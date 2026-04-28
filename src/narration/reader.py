# narration/reader.py
# HAJ-144 acceptance #4 — independent (threshold, voice) configurability.
#
# Each altitude reader is a `Reader` constructed from two knobs:
#
#   - `threshold`: the significance value at-or-above which an Event
#     is rendered. mat-side defaults to 1, stands to 4, review to 7,
#     broadcast to 9.
#   - `voice`: a callable that turns one (Event, BodyPartEvent slice,
#     match) tuple into a prose string — or returns None to suppress.
#
# Future career-progression unlocks (a radio at mid-career, a streaming
# feed at late-career — HAJ-144 part A) compose as new (threshold, voice)
# pairings without forcing a new altitude class.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from grip_graph import Event
    from body_part_events import BodyPartEvent
    from match import Match


# A voice callable: given an event with attached BPEs and the match,
# return a prose line — or None to suppress.
Voice = Callable[
    ["Event", list["BodyPartEvent"], "Match"], Optional[str],
]


@dataclass
class Reader:
    """A `(threshold, voice)` pair. The match runs each registered
    Reader once per tick; entries below threshold are filtered before
    the voice fires. Tests construct non-default pairings (e.g. stands-
    voice + mat-side-threshold) to verify the two are decoupled."""

    threshold: int
    voice: Voice
    name: str = "anonymous"
    # Prose entries the reader produced; the match polls this list to
    # render to whatever surface that altitude lives on (mat-side log,
    # stands ticker, review write-up, broadcast desk overview).
    log: list[str] = field(default_factory=list)

    def consume(
        self, event: "Event", bpes: list["BodyPartEvent"], match: "Match",
    ) -> Optional[str]:
        """Filter by threshold; if the event qualifies, fire the voice
        and append the result to the reader's own log."""
        if event.significance < self.threshold:
            return None
        line = self.voice(event, bpes, match)
        if line:
            self.log.append(line)
        return line
