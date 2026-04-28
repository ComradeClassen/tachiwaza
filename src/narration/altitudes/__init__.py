# narration/altitudes/__init__.py
# HAJ-144 acceptance #3 — four altitude readers as separate modules.
#
# Mat-side is the v0.1 working altitude rendered into the visible match
# log. The other three (stands, review, broadcast) are scaffolded with
# passing tests but not wired into a player-facing surface — Ring 2 wires
# them. Each module owns its own (threshold, voice) defaults and any
# altitude-specific composition logic; shared vocabulary lives in
# narration/word_verbs.py.

from narration.altitudes.mat_side  import MatSideNarrator, build_mat_side_reader
from narration.altitudes.stands    import build_stands_reader
from narration.altitudes.review    import build_review_reader
from narration.altitudes.broadcast import build_broadcast_reader

__all__ = [
    "MatSideNarrator",
    "build_mat_side_reader",
    "build_stands_reader",
    "build_review_reader",
    "build_broadcast_reader",
]
