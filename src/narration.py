# narration.py
# HAJ-147 — mat-side reader v0.1 + match clock log.
#
# The editorial layer that reads the BodyPartEvent stream (HAJ-145), grip
# intent + head-as-output state (HAJ-146), and SkillVector and produces
# coach's-eye prose at match-clock granularity.
#
# Architecture: two logs, one substrate.
#   - Tick log (existing Match events): full fidelity, every event, debug.
#   - Match clock log (this module's output): sampled prose, what the
#     reader sees in the viewer.
#
# This layer is a *filter*, not a generator. The engine emits at full
# fidelity (HAJ-145 + HAJ-146); the narrator decides what gets promoted
# from tick to clock log and how it reads.
#
# v0.1 promotion rules (per ticket):
#   1. Always promote: scoring actions, completed throws, submissions,
#      posture breaks, grip kills, counter fires, phase transitions.
#   2. Promote when modifier is non-default (crisp / flaring / late /
#      tentative / explosive — anything that reveals skill).
#   3. Promote on contradiction (pull-vs-step opposed; intent-outcome
#      mismatch).
#   4. Sample during stable phases (≈ one line per 5–10 ticks unless
#      something changes).
#   5. Always promote on phase transition.
#
# Out of scope (per ticket): stands / review / broadcast altitudes;
# significance scoring as a first-class field; recognition mechanic;
# persistence rule; bench-voice scaffold; grip-strength / breath /
# fatigue prose. Audio is out of scope ever.

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

from body_part_events import (
    BodyPartEvent, BodyPartHigh, Side, BodyPartVerb, BodyPartTarget,
    Crispness, Tightness, Speed, Connection, Timing, Commitment,
    GripIntent, SteerDirection, is_self_cancel_pair,
)

if TYPE_CHECKING:
    from match import Match
    from grip_graph import Event


# ---------------------------------------------------------------------------
# REGISTER
# Three skill registers per the HAJ-144 part C spec: novice / neutral /
# high-skill. Selection driven by the actor's modifier bundle on the
# event — CRISP/EXPLOSIVE/TIGHT collapse to "high"; SLOPPY/FLARING/SLOW
# collapse to "low"; everything else (and missing modifiers) to "mid".
# ---------------------------------------------------------------------------
def register_for(event: BodyPartEvent) -> str:
    """Pick novice / neutral / high register for prose word-verb lookup."""
    m = event.modifiers
    if m.crispness is Crispness.CRISP or m.speed is Speed.EXPLOSIVE:
        return "high"
    if (m.crispness is Crispness.SLOPPY or m.speed is Speed.SLOW
            or m.tightness is Tightness.FLARING):
        return "low"
    return "mid"


# ---------------------------------------------------------------------------
# WORD-VERB TABLE
# Engine event verbs (HAJ-145) → prose word verbs by register. The HAJ-144
# spec calls out the canonical mapping for each: REACH→"reaches",
# GRIP→"secures"/"gets", PULL→"pulls"/"drives", etc. v0.1 is deliberately
# small; HAJ-148+ will grow the table as the prose density needs it.
# ---------------------------------------------------------------------------
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
    """Render a side-and-part fragment: 'right hand', 'left foot', etc.
    Sideless parts (POSTURE / BASE / HEAD) collapse to just the part."""
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

    Composition: '<actor>'s <side+part> <verb><target>'. Modifiers append
    a parenthetical when non-default — crisp / sloppy / late / etc. The
    register-aware verb selection is what makes the same event read
    differently for different fighters.
    """
    register = register_for(event)
    word = WORD_VERBS.get(event.verb, {}).get(register, event.verb.name.lower())
    sub  = _side_phrase(event.side, event.part)
    tgt  = _target_phrase(event.target)
    actor_phrase = f"{event.actor}'s {sub}" if event.part is not BodyPartHigh.POSTURE else f"{event.actor}'s posture"
    return f"{actor_phrase} {word}{tgt}".strip()


# ---------------------------------------------------------------------------
# MATCH CLOCK ENTRY
# One line of editorial prose at a given tick. Carries the source tag so
# downstream readers (replay, summary, future altitudes) can group / filter.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MatchClockEntry:
    tick:   int
    prose:  str
    source: str    # "score" | "throw" | "counter" | "phase" | "self_cancel"
                   # | "intent_mismatch" | "skill_reveal" | "sample" | "matte"
    actors: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# PROMOTION CATEGORIES
# Engine event_types whose mere presence triggers a promotion (rule 1).
# ---------------------------------------------------------------------------
# Always-promote engine events — their bare description is already
# coach-voice prose, so the clock log echoes them rather than re-authoring.
# Desperation ENTER lines are intentionally NOT here: those carry a debug
# breakdown the prose layer shouldn't surface verbatim, and the engine
# event already prints through the regular pipeline.
_ALWAYS_PROMOTE_EVENT_TYPES: frozenset[str] = frozenset({
    "SCORE_AWARDED", "IPPON_AWARDED", "THROW_LANDING",
    "THROW_ENTRY", "COUNTER_COMMIT", "STUFFED",
    "SUBMISSION_VICTORY", "ESCAPE_SUCCESS", "MATTE",
    "NEWAZA_TRANSITION", "GRIP_STRIPPED", "GRIP_BREAK",
})


# Sample one prose line every N ticks during stable grip-war phases.
_STABLE_SAMPLE_INTERVAL: int = 7


# Coach-voice prose for each phase transition pair. Falling back to a
# generic "phase shifts" line when an unhandled pair appears keeps the
# clock log readable without forcing every combination to be authored.
_PHASE_TRANSITION_PROSE: dict[tuple[str, str], str] = {
    ("closing", "grip_war"):  "Both fighters lock onto their grips.",
    ("grip_war", "engaged"):  "They close — chest to chest, hands fighting hot.",
    ("engaged", "grip_war"):  "The engagement breaks — back to grip-fighting.",
    ("grip_war", "scramble"): "It collapses into a scramble.",
    ("engaged", "scramble"):  "They tumble into a scramble.",
    ("scramble", "grip_war"): "They reset to their feet, gripping again.",
    ("scramble", "ne_waza"):  "It goes to the ground.",
    ("engaged", "ne_waza"):   "The throw lands — ne-waza opens up.",
    ("grip_war", "ne_waza"):  "It hits the mat — ne-waza is on.",
    ("ne_waza", "closing"):   "Matte — they're back on their feet.",
    ("ne_waza", "grip_war"):  "Matte — back to grips.",
    ("grip_war", "closing"):  "The grips reset — both fighters disengage.",
    ("engaged", "closing"):   "They break apart and reset.",
    ("scramble", "closing"):  "They reset, distance restored.",
    ("ne_waza", "match_over"): "The submission ends it.",
    ("grip_war", "match_over"): "And that's the match.",
    ("engaged", "match_over"):  "And that's the match.",
}


# ---------------------------------------------------------------------------
# MAT-SIDE NARRATOR
# Per-match instance held by Match. Filters BPE + Event streams each tick
# and emits MatchClockEntry records. Stateful — tracks last-promoted tick,
# last seen phase, last-sample tick — so promotion rule 4 (sampling) and
# rule 5 (phase transitions) work.
# ---------------------------------------------------------------------------
class MatSideNarrator:
    def __init__(self) -> None:
        self._last_phase: Optional[str] = None
        self._last_sample_tick: int = -1_000
        self._last_promoted_tick: int = -1
        # Per-actor tick-of-last-rule for rate limiting. The same novice
        # SNAP can fire every grip-war tick; promoting it every tick
        # bloats the clock log and drowns the meaningful beats. v0.1
        # rate-limit window: a given (actor, source) pair promotes at
        # most once per _RATE_LIMIT_TICKS.
        self._last_actor_source_tick: dict[tuple[str, str], int] = {}
        # Tracks the previous tick's grip-graph snapshot so intent-outcome
        # detection can compare "intent declared last tick" vs "outcome
        # observed this tick" — used for the gap-prose detection in rule 3.
        # v0.1 is single-tick only; multi-tick mismatch tracking is HAJ-148+.

    _RATE_LIMIT_TICKS: int = 6

    # ----- public entrypoint --------------------------------------------
    def consume_tick(
        self, tick: int, events: list, bpes: list[BodyPartEvent],
        match: "Match",
    ) -> list[MatchClockEntry]:
        """Run the five promotion rules over one tick. Returns the
        MatchClockEntry list for this tick (may be empty)."""
        out: list[MatchClockEntry] = []

        # Rule 5 — phase transition always promotes (run first so the
        # transition line precedes whatever else happened on this tick).
        phase = self._phase_label(match)
        if self._last_phase is not None and phase != self._last_phase:
            out.append(MatchClockEntry(
                tick=tick,
                prose=_PHASE_TRANSITION_PROSE.get(
                    (self._last_phase, phase),
                    f"phase shifts: {self._last_phase} → {phase}.",
                ),
                source="phase",
            ))
        self._last_phase = phase

        # Rule 1 — always-promote events. We render directly off the
        # engine Event description to preserve the existing wording for
        # scores / matte / counters (those are already coach-voice prose
        # in match.py); we don't re-author them here.
        always_seen_this_tick = False
        for ev in events:
            et = ev.event_type
            if et in _ALWAYS_PROMOTE_EVENT_TYPES:
                out.append(MatchClockEntry(
                    tick=tick, prose=ev.description,
                    source=self._source_for(et),
                ))
                always_seen_this_tick = True

        # Rule 3 — contradiction detection. Self-cancel walks same-tick,
        # same-actor BPEs for opposed PULL/STEP pairs and a DISCONNECTED
        # connection modifier on the actor; intent-outcome mismatch fires
        # when a SNAP (failed strip) emits.
        out.extend(self._detect_self_cancel(tick, bpes))
        out.extend(self._detect_intent_outcome_mismatch(tick, bpes))

        # Rule 2 — non-default-modifier promotion. Walk BPEs from this
        # tick that come from "interesting" sources and emit a coach's-
        # eye line when a modifier extreme reveals skill. We deliberately
        # skip GRIP_DEEPEN and REACH-style filler events so the tick log
        # remains the source of truth and the clock log stays curated.
        out.extend(self._promote_modifier_extremes(tick, bpes))

        # Rule 4 — sample. During stable phases (no always-promote
        # events fired this tick, no contradiction, no modifier extreme),
        # emit one line every _STABLE_SAMPLE_INTERVAL ticks summarising
        # the dyad state so the reader doesn't see dead air.
        if not out and (tick - self._last_sample_tick) >= _STABLE_SAMPLE_INTERVAL:
            sample = self._sample_phase(tick, match, bpes)
            if sample is not None:
                out.append(sample)
                self._last_sample_tick = tick

        if out:
            self._last_promoted_tick = tick
        return out

    # ----- rule 3a: self-cancel ----------------------------------------
    def _detect_self_cancel(
        self, tick: int, bpes: list[BodyPartEvent],
    ) -> list[MatchClockEntry]:
        """The novice pull that fires while stepping forward into uke.
        Decomposes (per HAJ-145/146) as: hands pull sleeve [tentative,
        late]; foot step forward [disconnected]; posture bent forward
        over own feet. The detection reads opposed pull-vector and
        step-vector AND a disconnected base on the actor."""
        out: list[MatchClockEntry] = []
        by_actor: dict[str, list[BodyPartEvent]] = {}
        for b in bpes:
            if b.tick != tick:
                continue
            by_actor.setdefault(b.actor, []).append(b)
        for actor, evs in by_actor.items():
            pulls = [e for e in evs
                     if e.verb in (BodyPartVerb.PULL, BodyPartVerb.PUSH)
                     and e.direction is not None]
            steps = [e for e in evs
                     if e.part is BodyPartHigh.FEET
                     and e.verb is BodyPartVerb.STEP
                     and e.direction is not None]
            disconnected = any(
                e.modifiers.connection is Connection.DISCONNECTED
                for e in evs
            )
            for pull in pulls:
                for step in steps:
                    if not is_self_cancel_pair(pull, step):
                        continue
                    # Disconnected base requirement — without it, an
                    # intentional retreating pull (a real tactical pattern)
                    # would mis-fire. Per HAJ-147 spec the structural
                    # signature is opposed vectors AND disconnected base.
                    if not disconnected:
                        continue
                    out.append(MatchClockEntry(
                        tick=tick,
                        prose=(
                            f"{actor}'s pull dies in the sleeve as he "
                            f"steps in over his own feet."
                        ),
                        source="self_cancel",
                        actors=(actor,),
                    ))
                    return out  # one per tick is plenty
        return out

    # ----- rule 3b: intent-outcome mismatch ----------------------------
    def _detect_intent_outcome_mismatch(
        self, tick: int, bpes: list[BodyPartEvent],
    ) -> list[MatchClockEntry]:
        """A grip event with intent=BREAK whose outcome is SNAP (the
        opposing edge is still alive) IS the gap. Decompose layer
        (HAJ-145) emits SNAP for failed strips and BREAK for successful
        ones, so we read the verb directly. Novice's pull intends to
        break and doesn't; brown belt's intends and does. Rate-limited
        per-actor so a stuck strip across many ticks doesn't drown the
        clock log."""
        out: list[MatchClockEntry] = []
        seen_actors: set[str] = set()
        for b in bpes:
            if b.tick != tick:
                continue
            if b.intent is GripIntent.BREAK and b.verb is BodyPartVerb.SNAP:
                if b.actor in seen_actors:
                    continue
                if not self._rate_check(b.actor, "intent_mismatch", tick):
                    continue
                seen_actors.add(b.actor)
                tgt = _target_phrase(b.target).lstrip()
                out.append(MatchClockEntry(
                    tick=tick,
                    prose=(
                        f"{b.actor} tries to rip {tgt} but can't budge it."
                    ),
                    source="intent_mismatch",
                    actors=(b.actor,),
                ))
        return out

    def _rate_check(self, actor: str, source: str, tick: int) -> bool:
        """True iff `actor`/`source` last fired more than _RATE_LIMIT_TICKS
        ticks ago. Mutates the tracking dict on success."""
        key = (actor, source)
        last = self._last_actor_source_tick.get(key, -10_000)
        if tick - last < self._RATE_LIMIT_TICKS:
            return False
        self._last_actor_source_tick[key] = tick
        return True

    # ----- rule 2: non-default modifier ---------------------------------
    def _promote_modifier_extremes(
        self, tick: int, bpes: list[BodyPartEvent],
    ) -> list[MatchClockEntry]:
        """Promote one prose line per actor when a non-default modifier
        reveals skill on a meaningful event. We read SCALAR extremes
        (CRISP / SLOPPY / EXPLOSIVE / SLOW / FLARING) on the COMMIT-source
        BPEs only — those are where the visible quality of execution
        lives. Routine grip events stay in the tick log."""
        out: list[MatchClockEntry] = []
        seen_actors: set[str] = set()
        for b in bpes:
            if b.tick != tick:
                continue
            if b.source not in ("COMMIT", "COUNTER_COMMIT"):
                continue
            if b.actor in seen_actors:
                continue
            m = b.modifiers
            extreme = (
                m.crispness is Crispness.CRISP
                or m.crispness is Crispness.SLOPPY
                or m.speed is Speed.EXPLOSIVE
                or m.tightness is Tightness.FLARING
                or m.timing is Timing.LATE
                or m.timing is Timing.EARLY
                or m.commitment is Commitment.OVERCOMMITTED
            )
            if not extreme:
                continue
            if not self._rate_check(b.actor, "skill_reveal", tick):
                continue
            seen_actors.add(b.actor)
            out.append(MatchClockEntry(
                tick=tick,
                prose=self._modifier_reveal_prose(b),
                source="skill_reveal",
                actors=(b.actor,),
            ))
        return out

    def _modifier_reveal_prose(self, b: BodyPartEvent) -> str:
        m = b.modifiers
        # Pick the most-visible modifier extreme as the prose hook.
        if m.crispness is Crispness.CRISP and m.speed is Speed.EXPLOSIVE:
            return f"{b.actor}'s commit lands crisp and explosive."
        if m.crispness is Crispness.CRISP:
            return f"{b.actor}'s commit reads clean and on-time."
        if m.crispness is Crispness.SLOPPY:
            return f"{b.actor}'s commit comes apart at the seams."
        if m.tightness is Tightness.FLARING:
            return f"{b.actor}'s elbow flares — power leaks out the side."
        if m.timing is Timing.LATE:
            return f"{b.actor} commits late — uke has already moved."
        if m.timing is Timing.EARLY:
            return f"{b.actor} commits early — the kuzushi hasn't stacked."
        if m.commitment is Commitment.OVERCOMMITTED:
            return f"{b.actor} throws himself at it — no recovery if it misses."
        if m.speed is Speed.SLOW:
            return f"{b.actor}'s commit is slow and telegraphed."
        return prose_for_event(b)

    # ----- rule 4: sample ------------------------------------------------
    def _sample_phase(
        self, tick: int, match: "Match", bpes: list[BodyPartEvent],
    ) -> Optional[MatchClockEntry]:
        """Emit one summary line during a stable phase. v0.1 surfaces a
        head-as-output BPE if any are present this tick (the most
        information-dense single-event summary of the dyad state)."""
        head_evs = [b for b in bpes
                    if b.tick == tick and b.part is BodyPartHigh.HEAD]
        if head_evs:
            h = head_evs[0]
            verb_word = WORD_VERBS.get(
                h.verb, {"mid": h.verb.name.lower()}
            ).get(register_for(h), h.verb.name.lower())
            return MatchClockEntry(
                tick=tick,
                prose=f"{h.actor}'s head {verb_word}.",
                source="sample",
                actors=(h.actor,),
            )
        return None

    # ----- helpers -------------------------------------------------------
    def _phase_label(self, match: "Match") -> str:
        """Coarse phase label for rule 5 (transitions)."""
        from enums import SubLoopState, Position
        if match.match_over:
            return "match_over"
        if match.sub_loop_state == SubLoopState.NE_WAZA:
            return "ne_waza"
        if match.position == Position.STANDING_DISTANT:
            return "closing"
        if match.position == Position.GRIPPING:
            return "grip_war"
        if match.position == Position.ENGAGED:
            return "engaged"
        if match.position == Position.SCRAMBLE:
            return "scramble"
        return "standing"

    def _source_for(self, event_type: str) -> str:
        if event_type in ("THROW_ENTRY", "THROW_LANDING", "STUFFED"):
            return "throw"
        if event_type == "COUNTER_COMMIT":
            return "counter"
        if event_type in ("SCORE_AWARDED", "IPPON_AWARDED"):
            return "score"
        if event_type == "MATTE":
            return "matte"
        if event_type in ("SUBMISSION_VICTORY", "ESCAPE_SUCCESS",
                          "NEWAZA_TRANSITION"):
            return "newaza"
        if event_type in ("GRIP_STRIPPED", "GRIP_BREAK"):
            return "grip_kill"
        return "phase"
