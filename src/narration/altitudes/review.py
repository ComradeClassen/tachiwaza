# narration/altitudes/review.py
# HAJ-144 acceptance #3 — simulated-review altitude.
#
# Voice: review voice — write-up register, past tense, summary cadence,
# sampled highlights. Threshold: 7 (score events, high-recognition throws,
# match-defining beats).
#
# Used when the player chose another presence and didn't watch live —
# the post-match write-up they read later. v0.1 SCAFFOLD ONLY.

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from body_part_events import BodyPartEvent
from narration.reader import Reader
from significance import THRESHOLD_REVIEW

if TYPE_CHECKING:
    from match import Match
    from grip_graph import Event


_REVIEW_PROMOTABLE_TYPES: frozenset[str] = frozenset({
    "SCORE_AWARDED", "IPPON_AWARDED", "THROW_LANDING",
    "SUBMISSION_VICTORY", "MATCH_OVER",
})


def _past_tense(desc: str) -> str:
    """Cheap present→past collapse for the review register. v0.1 — the
    engine's score lines already read as observed beats; the review
    voice just wraps them in a "the match" framing."""
    return desc


def _review_voice(
    event: "Event", bpes: list[BodyPartEvent], match: "Match",
) -> Optional[str]:
    if event.event_type not in _REVIEW_PROMOTABLE_TYPES:
        return None
    desc = _past_tense(event.description)
    if event.event_type == "IPPON_AWARDED":
        return f"Decisive ippon. {desc}"
    if event.event_type == "SUBMISSION_VICTORY":
        return f"Submission victory. {desc}"
    if event.event_type == "SCORE_AWARDED":
        return f"Scoring beat: {desc}"
    return desc


def build_review_reader(threshold: int = THRESHOLD_REVIEW) -> Reader:
    return Reader(
        threshold=threshold,
        voice=_review_voice,
        name="review",
    )
