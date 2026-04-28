# narration/word_verbs.py
# HAJ-144 part C / HAJ-147 — engine-event-verb → prose-word-verb mapping.
#
# Three skill registers per HAJ-144 part C: novice / neutral / high. The
# table is intentionally small in v0.1; it grows as prose density needs.
# Same engine event reads as different prose depending on the actor's
# skill modifiers.

from __future__ import annotations

from typing import Optional

from body_part_events import (
    BodyPartEvent, BodyPartHigh, Side, BodyPartVerb, BodyPartTarget,
    Crispness, Tightness, Speed,
)


def register_for(event: BodyPartEvent) -> str:
    """Pick novice / neutral / high register for prose word-verb lookup."""
    m = event.modifiers
    if m.crispness is Crispness.CRISP or m.speed is Speed.EXPLOSIVE:
        return "high"
    if (m.crispness is Crispness.SLOPPY or m.speed is Speed.SLOW
            or m.tightness is Tightness.FLARING):
        return "low"
    return "mid"


WORD_VERBS: dict[BodyPartVerb, dict[str, str]] = {
    BodyPartVerb.REACH:   {"low": "fishes for",     "mid": "reaches for",       "high": "reaches in for"},
    BodyPartVerb.GRIP:    {"low": "grabs",          "mid": "secures",           "high": "gets"},
    BodyPartVerb.PULL:    {"low": "tugs on",        "mid": "pulls",             "high": "drives"},
    BodyPartVerb.PUSH:    {"low": "shoves",         "mid": "pushes",            "high": "drives"},
    BodyPartVerb.SNAP:    {"low": "yanks at",       "mid": "snaps",             "high": "rips at"},
    BodyPartVerb.BREAK:   {"low": "breaks",         "mid": "breaks",            "high": "tears off"},
    BodyPartVerb.RELEASE: {"low": "lets go of",     "mid": "releases",          "high": "lets go"},
    BodyPartVerb.POST:    {"low": "posts on",       "mid": "posts on",          "high": "frames on"},
    BodyPartVerb.PIN:     {"low": "holds onto",     "mid": "pins",              "high": "controls"},
    BodyPartVerb.LIFT:    {"low": "lifts",          "mid": "lifts",             "high": "loads"},
    BodyPartVerb.HOOK:    {"low": "hooks",          "mid": "hooks",             "high": "hooks"},
    BodyPartVerb.REAP:    {"low": "kicks at",       "mid": "reaps",             "high": "sweeps"},
    BodyPartVerb.STEP:    {"low": "steps",          "mid": "steps",             "high": "steps in"},
    BodyPartVerb.PROP:    {"low": "plants on",      "mid": "props",             "high": "props"},
    BodyPartVerb.LOAD:    {"low": "loads",          "mid": "loads",             "high": "loads deep"},
    BodyPartVerb.TURN_IN: {"low": "turns",          "mid": "turns in",          "high": "turns in"},
    BodyPartVerb.PIVOT:   {"low": "pivots",         "mid": "pivots",            "high": "pivots through"},
    BodyPartVerb.BEND:    {"low": "bends",          "mid": "bends",             "high": "loads the leg"},
    BodyPartVerb.BLOCK:   {"low": "blocks",         "mid": "blocks",            "high": "checks"},
    BodyPartVerb.CUT_INSIDE: {"low": "cuts in",     "mid": "cuts inside",       "high": "cuts inside"},
    BodyPartVerb.STRAIGHTEN: {"low": "straightens", "mid": "straightens",       "high": "straightens"},
    BodyPartVerb.TIGHT:   {"low": "tucks",          "mid": "keeps the elbow tight", "high": "tucks tight"},
    BodyPartVerb.FLARE:   {"low": "flares",         "mid": "flares",            "high": "flares wide"},
    BodyPartVerb.SQUARE:  {"low": "squares up",     "mid": "squares up",        "high": "squares up"},
    BodyPartVerb.CHECK:   {"low": "checks",         "mid": "checks",            "high": "checks"},
    BodyPartVerb.COLLAPSE:{"low": "collapses",      "mid": "collapses",         "high": "gives out"},
    BodyPartVerb.DRIVING: {"low": "is driven",      "mid": "is driven",         "high": "is steered"},
    BodyPartVerb.DOWN:    {"low": "is bent down",   "mid": "drops",             "high": "drops"},
    BodyPartVerb.UP:      {"low": "rises",          "mid": "rises",             "high": "is lifted"},
    BodyPartVerb.TURNED:  {"low": "is turned",      "mid": "is turned",         "high": "is steered round"},
    BodyPartVerb.UPRIGHT: {"low": "stays upright",  "mid": "stays upright",     "high": "stays composed"},
    BodyPartVerb.BROKEN_FORWARD: {"low": "is bent forward", "mid": "is broken forward",   "high": "is broken forward"},
    BodyPartVerb.BROKEN_BACK:    {"low": "is bent back",    "mid": "is broken back",      "high": "is broken back"},
    BodyPartVerb.BROKEN_SIDE:    {"low": "tilts",           "mid": "is broken to the side","high": "is broken to the corner"},
    BodyPartVerb.BENT:    {"low": "is bent",        "mid": "is bent",           "high": "is bent low"},
    BodyPartVerb.SQUARED: {"low": "squares up",     "mid": "squares up",        "high": "squares up"},
}


def _target_phrase(target: Optional[BodyPartTarget]) -> str:
    if target is None:
        return ""
    return {
        BodyPartTarget.LAPEL:      " on the lapel",
        BodyPartTarget.SLEEVE:     " on the sleeve",
        BodyPartTarget.COLLAR:     " on the collar",
        BodyPartTarget.BELT:       " on the belt",
        BodyPartTarget.BACK_OF_GI: " on the back",
        BodyPartTarget.WRIST:      " on the wrist",
        BodyPartTarget.CROSS_GRIP: " across the body",
    }.get(target, "")


def _side_phrase(side: Side, part: BodyPartHigh) -> str:
    """Render a side-and-part fragment: 'right hand', 'left foot', etc."""
    part_word = {
        BodyPartHigh.HANDS:     "hand",
        BodyPartHigh.ELBOWS:    "elbow",
        BodyPartHigh.SHOULDERS: "shoulder",
        BodyPartHigh.HIPS:      "hips",
        BodyPartHigh.KNEES:     "knee",
        BodyPartHigh.FEET:      "foot",
        BodyPartHigh.HEAD:      "head",
        BodyPartHigh.POSTURE:   "posture",
        BodyPartHigh.BASE:      "base",
    }[part]
    if side is Side.RIGHT:
        return f"right {part_word}"
    if side is Side.LEFT:
        return f"left {part_word}"
    return part_word


def prose_for_event(event: BodyPartEvent) -> str:
    """Render one BodyPartEvent as a coach's-eye sentence fragment.

    Composition: '<actor>'s <side+part> <verb><target>'. The register-
    aware verb selection is what makes the same event read differently
    for different fighters.
    """
    register = register_for(event)
    word = WORD_VERBS.get(event.verb, {}).get(register, event.verb.name.lower())
    sub  = _side_phrase(event.side, event.part)
    tgt  = _target_phrase(event.target)
    actor_phrase = (
        f"{event.actor}'s {sub}"
        if event.part is not BodyPartHigh.POSTURE
        else f"{event.actor}'s posture"
    )
    return f"{actor_phrase} {word}{tgt}".strip()


# Public helpers used by reader composers.
__all__ = [
    "WORD_VERBS", "register_for", "prose_for_event",
    "_target_phrase", "_side_phrase",
]
