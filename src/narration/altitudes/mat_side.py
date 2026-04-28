# narration/altitudes/mat_side.py
# HAJ-144 acceptance #3 — mat-side reader (working altitude).
# HAJ-147 — the editorial layer that produces the match-clock log.
#
# Voice: coach voice — third-person observer, body-part literate, calm,
# technical. Threshold: 1 (everything except true noise; HAJ-144 default).
#
# Implements the five promotion rules (always-promote, modifier extreme,
# contradiction, sample, phase) against the BodyPartEvent + Event streams.
# This is the v0.1 module imported directly by Match._post_tick; the other
# three altitudes (stands / review / broadcast) live alongside it as
# scaffolds for Ring 2 wiring.

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

from body_part_events import (
    BodyPartEvent, BodyPartHigh, BodyPartVerb,
    Crispness, Tightness, Speed, Connection, Timing, Commitment,
    GripIntent, is_self_cancel_pair,
)
from narration.word_verbs import (
    WORD_VERBS, register_for, prose_for_event,
    _target_phrase, _side_phrase,
)
from narration.reader import Reader
from significance import THRESHOLD_MAT_SIDE

if TYPE_CHECKING:
    from match import Match
    from grip_graph import Event


# ---------------------------------------------------------------------------
# MATCH CLOCK ENTRY — one prose line at a given tick.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MatchClockEntry:
    tick:   int
    prose:  str
    source: str
    actors: tuple[str, ...] = ()


# Always-promote engine events — their bare description is already
# coach-voice prose, so the clock log echoes them rather than re-authoring.
_ALWAYS_PROMOTE_EVENT_TYPES: frozenset[str] = frozenset({
    "SCORE_AWARDED", "IPPON_AWARDED", "THROW_LANDING",
    "THROW_ENTRY", "COUNTER_COMMIT", "STUFFED",
    "SUBMISSION_VICTORY", "ESCAPE_SUCCESS", "MATTE",
    "NEWAZA_TRANSITION", "GRIP_STRIPPED", "GRIP_BREAK",
})

# Sample one prose line every N ticks during stable grip-war phases.
_STABLE_SAMPLE_INTERVAL: int = 7


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


class MatSideNarrator:
    """Per-match instance held by Match. Filters BPE + Event streams each
    tick and emits MatchClockEntry records. Stateful — tracks last-promoted
    tick, last seen phase, last-sample tick — so promotion rule 4 (sampling)
    and rule 5 (phase transitions) work.
    """

    _RATE_LIMIT_TICKS: int = 6

    def __init__(self) -> None:
        self._last_phase: Optional[str] = None
        self._last_sample_tick: int = -1_000
        self._last_promoted_tick: int = -1
        self._last_actor_source_tick: dict[tuple[str, str], int] = {}

    def consume_tick(
        self, tick: int, events: list, bpes: list[BodyPartEvent],
        match: "Match",
    ) -> list[MatchClockEntry]:
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

        # Rule 1 — always-promote events.
        for ev in events:
            et = ev.event_type
            if et in _ALWAYS_PROMOTE_EVENT_TYPES:
                out.append(MatchClockEntry(
                    tick=tick, prose=ev.description,
                    source=self._source_for(et),
                ))
            # HAJ-144 acceptance #13 — desperation overlay + failed_dimension
            # surface as body-part prose, not enum names. The engine emits
            # OFFENSIVE_DESPERATION_ENTER / DEFENSIVE_DESPERATION_ENTER with
            # a numeric breakdown in description; we re-author them into
            # coach prose that names the body-part feel.
            elif et in (
                "OFFENSIVE_DESPERATION_ENTER",
                "DEFENSIVE_DESPERATION_ENTER",
            ):
                actor = ev.data.get("type", "")
                # The engine description carries the actor name first;
                # extract a coach-voice rewrite that drops the breakdown
                # numerics and keeps the structural cue.
                desc = ev.description
                # Heuristic: pull "{name} enters …" out of the legacy line.
                name = ""
                if "[state] " in desc:
                    rest = desc.split("[state] ", 1)[1]
                    name = rest.split(" enters ", 1)[0]
                if et == "OFFENSIVE_DESPERATION_ENTER":
                    prose = (
                        f"{name}'s posture stiffens — composure leaks "
                        f"as the kumi-kata clock runs hot."
                    )
                else:
                    prose = (
                        f"{name} backs onto the heels — eyes widening, "
                        f"reading the next attack before it lands."
                    )
                out.append(MatchClockEntry(
                    tick=tick, prose=prose,
                    source="desperation",
                    actors=(name,) if name else (),
                ))

        # Rule 3 — contradiction detection.
        out.extend(self._detect_self_cancel(tick, bpes))
        out.extend(self._detect_intent_outcome_mismatch(tick, bpes))

        # Rule 2 — non-default-modifier promotion.
        out.extend(self._promote_modifier_extremes(tick, bpes))

        # Rule 4 — sample.
        if not out and (tick - self._last_sample_tick) >= _STABLE_SAMPLE_INTERVAL:
            sample = self._sample_phase(tick, match, bpes)
            if sample is not None:
                out.append(sample)
                self._last_sample_tick = tick

        if out:
            self._last_promoted_tick = tick
        return out

    def _detect_self_cancel(
        self, tick: int, bpes: list[BodyPartEvent],
    ) -> list[MatchClockEntry]:
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
                    return out
        return out

    def _detect_intent_outcome_mismatch(
        self, tick: int, bpes: list[BodyPartEvent],
    ) -> list[MatchClockEntry]:
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
        key = (actor, source)
        last = self._last_actor_source_tick.get(key, -10_000)
        if tick - last < self._RATE_LIMIT_TICKS:
            return False
        self._last_actor_source_tick[key] = tick
        return True

    def _promote_modifier_extremes(
        self, tick: int, bpes: list[BodyPartEvent],
    ) -> list[MatchClockEntry]:
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

    def _sample_phase(
        self, tick: int, match: "Match", bpes: list[BodyPartEvent],
    ) -> Optional[MatchClockEntry]:
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

    def _phase_label(self, match: "Match") -> str:
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


# ---------------------------------------------------------------------------
# Reader factory — independent (threshold, voice) construction (acceptance #4).
# This wraps MatSideNarrator's per-event voice into the generic Reader
# interface so test_threshold_voice_independence can swap voices freely.
# ---------------------------------------------------------------------------
def _mat_side_voice(
    event: "Event", bpes: list[BodyPartEvent], match: "Match",
) -> Optional[str]:
    """Per-event mat-side voice (coach register). Stateless wrapper —
    most prose composition happens in MatSideNarrator's tick-level
    pipeline; this adapter renders one event at a time when callers
    want the Reader interface instead. Returns None for events the
    mat-side voice doesn't speak (debug-only and below threshold)."""
    if event.event_type in _ALWAYS_PROMOTE_EVENT_TYPES:
        return event.description
    return None


def build_mat_side_reader(threshold: int = THRESHOLD_MAT_SIDE) -> Reader:
    """v0.1 mat-side reader: coach voice + everything-above-noise threshold.
    Caller can override threshold for testing decoupling."""
    return Reader(
        threshold=threshold,
        voice=_mat_side_voice,
        name="mat_side",
    )
