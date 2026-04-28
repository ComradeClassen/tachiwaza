# narration/__init__.py
# HAJ-144 — narration package, re-exports the public API.

from narration.altitudes.mat_side  import MatSideNarrator, MatchClockEntry, build_mat_side_reader
from narration.altitudes.stands    import build_stands_reader
from narration.altitudes.review    import build_review_reader
from narration.altitudes.broadcast import build_broadcast_reader
from narration.reader              import Reader, Voice
from narration.word_verbs          import WORD_VERBS, register_for, prose_for_event
from narration.bench_voice         import BenchProfile, VocabularyDepth

__all__ = [
    # Mat-side narrator (the v0.1 working altitude rendered into the visible log).
    "MatSideNarrator", "MatchClockEntry",
    # Reader abstraction + altitude builders.
    "Reader", "Voice",
    "build_mat_side_reader", "build_stands_reader",
    "build_review_reader", "build_broadcast_reader",
    # Vocabulary helpers (used by altitude voices and tests).
    "WORD_VERBS", "register_for", "prose_for_event",
    # Bench-voice scaffold.
    "BenchProfile", "VocabularyDepth",
]
