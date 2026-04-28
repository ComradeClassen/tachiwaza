# narration/bench_voice.py
# HAJ-144 acceptance #12 — bench voice as a sub-stream of mat-side.
#
# When the player is in dojo-view watching their students randori, they
# sit at mat-side altitude over the dojo, and bench voice is the
# students' commentary mixed into the coach stream. The miscall *is*
# the simulation: a white-belt or yellow-belt student calls everything
# in the family "Ko-soto" without distinguishing variants; a brown-belt
# sempai correctly names reversals and signature variants.
#
# v0.1 SCAFFOLD ONLY — not yet rendered into a player-facing surface.
# Ring 2 dojo view wires it in. The scaffold is testable in isolation.

from __future__ import annotations

from dataclasses import dataclass

from enums import BeltRank


# ---------------------------------------------------------------------------
# BELT-KEYED ACCURACY CURVE
# Per HAJ-144 acceptance #12: white/yellow belts produce generic
# family-level miscalls (everything in the family "Ko-soto" without
# distinguishing Ko-soto-gari from Ko-soto-gake); brown+ belts call
# variants and reversals correctly.
#
# Two parameters drive the bench voice's recognition:
#
#   - `recognition_accuracy` ∈ [0, 1]: probability that the called name
#     matches the actual technique. v0.1 calibration target.
#
#   - `vocabulary_depth`: how specific the call lands. FAMILY collapses
#     all variants in a throw family to the family name; SPECIFIC names
#     the canonical throw (Ko-soto-gari vs Ko-soto-gake); SIGNATURE
#     names rare/expert variants and reversals.
# ---------------------------------------------------------------------------
class VocabularyDepth:
    FAMILY    = "family"      # "ko-soto"
    SPECIFIC  = "specific"    # "ko-soto-gari"
    SIGNATURE = "signature"   # "ko-soto-gari counter to harai-goshi"


_BELT_PROFILE: dict[BeltRank, tuple[float, str]] = {
    BeltRank.WHITE:   (0.40, VocabularyDepth.FAMILY),
    BeltRank.YELLOW:  (0.50, VocabularyDepth.FAMILY),
    BeltRank.ORANGE:  (0.60, VocabularyDepth.FAMILY),
    BeltRank.GREEN:   (0.70, VocabularyDepth.SPECIFIC),
    BeltRank.BLUE:    (0.78, VocabularyDepth.SPECIFIC),
    BeltRank.BROWN:   (0.85, VocabularyDepth.SPECIFIC),
    BeltRank.BLACK_1: (0.92, VocabularyDepth.SIGNATURE),
    BeltRank.BLACK_2: (0.94, VocabularyDepth.SIGNATURE),
    BeltRank.BLACK_3: (0.96, VocabularyDepth.SIGNATURE),
    BeltRank.BLACK_4: (0.98, VocabularyDepth.SIGNATURE),
    BeltRank.BLACK_5: (0.99, VocabularyDepth.SIGNATURE),
}


@dataclass(frozen=True)
class BenchProfile:
    """The recognition profile for one student calling from the bench."""
    belt:                 BeltRank
    recognition_accuracy: float
    vocabulary_depth:     str

    @classmethod
    def for_belt(cls, belt: BeltRank) -> "BenchProfile":
        acc, depth = _BELT_PROFILE.get(
            belt, (0.50, VocabularyDepth.FAMILY)
        )
        return cls(belt=belt, recognition_accuracy=acc, vocabulary_depth=depth)

    def likely_call(self, actual_throw_name: str) -> str:
        """Render the throw name at the bench-caller's vocabulary depth.
        v0.1 collapses Ko-soto-gari / Ko-soto-gake / Ko-uchi-gari etc. to
        their family stem when the caller is at FAMILY depth — the
        miscall mechanic. Tests assert family-level callers don't surface
        the variant suffix."""
        if self.vocabulary_depth == VocabularyDepth.FAMILY:
            return _family_name(actual_throw_name)
        return actual_throw_name


def _family_name(throw_name: str) -> str:
    """Collapse a canonical throw name onto its family stem.
    Ko-soto-gari → Ko-soto; Uchi-mata → Uchi-mata (single-word family).
    Heuristic: if the throw has a hyphenated suffix matching one of the
    common technique-modifier suffixes, drop it."""
    suffixes = ("-gari", "-gake", "-otoshi", "-harai", "-nage")
    lower = throw_name.lower()
    for suf in suffixes:
        if lower.endswith(suf):
            return throw_name[: -len(suf)]
    return throw_name
