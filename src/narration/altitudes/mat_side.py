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

import random
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
import grip_narration

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


# ---------------------------------------------------------------------------
# HAJ-167 — windowed-pull narration substrate.
#
# The narrator keeps a fixed-size ring of recent TickFrames so promotion
# rules can read across ticks (delta detection without per-detector state
# fields, gap surfacing without firing blind on the trigger tick).
# Snapshots are immutable per-tick — we don't deep-copy the live Match.
# Design notes: design-notes/narration-decouple-v1.md.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MatchSnapshot:
    """Minimum match-level state a rule might need to read against the
    past. Built once per tick from the live Match; immutable from then
    on. Optional fields default to None so legacy stub-match call sites
    (e.g. desperation-prose unit-test stubs) work without a full match
    instance."""
    tick:                  int
    position:              object  # Position enum
    sub_loop_state:        object  # SubLoopState enum
    a_name:                Optional[str] = None
    b_name:                Optional[str] = None
    a_region:              Optional[object] = None
    b_region:              Optional[object] = None
    a_posture:             Optional[object] = None
    b_posture:             Optional[object] = None
    a_com:                 Optional[tuple] = None
    b_com:                 Optional[tuple] = None
    grip_count_a:          int = 0
    grip_count_b:          int = 0
    in_progress_attackers: frozenset[str] = frozenset()


@dataclass(frozen=True)
class TickFrame:
    """One tick's worth of engine state the narrator can read against.
    `events` and `bpes` are stored as tuples (immutable) so a rule
    iterating the window can't mutate a prior frame."""
    tick:     int
    events:   tuple
    bpes:     tuple
    snapshot: MatchSnapshot


def _build_match_snapshot(tick: int, match: "Match") -> MatchSnapshot:
    """Build a MatchSnapshot from a live Match. Defensive against
    stub-match callers that don't carry the full attribute surface."""
    fighter_a = getattr(match, "fighter_a", None)
    fighter_b = getattr(match, "fighter_b", None)
    if fighter_a is None or fighter_b is None:
        return MatchSnapshot(
            tick=tick,
            position=getattr(match, "position", None),
            sub_loop_state=getattr(match, "sub_loop_state", None),
        )
    try:
        from match import region_of
    except ImportError:
        region_of = None
    try:
        from body_state import derive_posture
    except ImportError:
        derive_posture = None
    a_bs = fighter_a.state.body_state
    b_bs = fighter_b.state.body_state
    a_region = region_of(fighter_a) if region_of is not None else None
    b_region = region_of(fighter_b) if region_of is not None else None
    a_posture = (
        derive_posture(a_bs.trunk_sagittal, a_bs.trunk_frontal)
        if derive_posture is not None else None
    )
    b_posture = (
        derive_posture(b_bs.trunk_sagittal, b_bs.trunk_frontal)
        if derive_posture is not None else None
    )
    grip_graph = getattr(match, "grip_graph", None)
    if grip_graph is not None:
        a_owned = len(grip_graph.edges_owned_by(fighter_a.identity.name))
        b_owned = len(grip_graph.edges_owned_by(fighter_b.identity.name))
    else:
        a_owned = b_owned = 0
    in_progress = frozenset(
        getattr(match, "_throws_in_progress", {}).keys()
    )
    return MatchSnapshot(
        tick=tick,
        position=getattr(match, "position", None),
        sub_loop_state=getattr(match, "sub_loop_state", None),
        a_name=fighter_a.identity.name,
        b_name=fighter_b.identity.name,
        a_region=a_region,
        b_region=b_region,
        a_posture=a_posture,
        b_posture=b_posture,
        a_com=tuple(a_bs.com_position),
        b_com=tuple(b_bs.com_position),
        grip_count_a=a_owned,
        grip_count_b=b_owned,
        in_progress_attackers=in_progress,
    )


# Width of the trailing tick window. 8 ticks covers throw resolution
# chains (4-tick spread) plus the 3-tick deferred pull-without-commit
# rule with a one-tick margin.
_NARRATION_WINDOW_SIZE: int = 8

# How long the deferred pull-without-commit rule waits before firing.
# 3 ticks is long enough that a real pull-then-commit chain resolves
# inside the gap; short enough that the prose lands while the moment
# is still fresh.
_DEFERRED_PULL_K_TICKS: int = 3

# HAJ-229 — engine events that invalidate a deferred pull-without-commit
# line if they land anywhere in the deferral window. A pre-throw PULL must
# not surface "tugs at the sleeve — rides it out" K ticks later when, in the
# gap, a throw resolved, someone scored, or the dyad reset / dropped to
# ne-waza — by then the puller may be the just-thrown fighter. The COMMIT-BPE
# check upstream only catches the *puller's own* throw; these dyad-global
# state changes (opponent scoring, matte, ne-waza) need their own gate.
_DEFERRED_PULL_INVALIDATING_EVENTS: frozenset[str] = frozenset({
    "THROW_LANDING", "SCORE_AWARDED", "IPPON_AWARDED",
    "NEWAZA_TRANSITION", "MATTE",
})


# Always-promote engine events — their bare description is already
# coach-voice prose, so the clock log echoes them rather than re-authoring.
# HAJ-225 — GRIP_STRIPPED is NO LONGER always-promoted: its bare description
# is the raw debug form ("X loses left_lapel grip on Y — stripped"). It is now
# authored as plain-language prose by `_detect_grip_strip_outcome` off the
# data-driven grip_narration layer.
_ALWAYS_PROMOTE_EVENT_TYPES: frozenset[str] = frozenset({
    "SCORE_AWARDED", "IPPON_AWARDED", "THROW_LANDING",
    "THROW_ENTRY", "COUNTER_COMMIT", "STUFFED",
    "SUBMISSION_VICTORY", "ESCAPE_SUCCESS", "MATTE",
    "NEWAZA_TRANSITION", "GRIP_BREAK",
})

# Sample one prose line every N ticks during stable grip-war phases.
_STABLE_SAMPLE_INTERVAL: int = 7


# HAJ-166 — head-as-output substrate (HAJ-146 + HAJ-161) emits one
# HEAD_AS_OUTPUT BPE per fighter under steer. The mat-side prose layer
# renders an outcome-bound line citing the specific collar sub-type and
# the resulting head movement. Below the threshold the steerer's grip
# is poorly seated (force absorbed, posture stiff) — a substitute line
# fires instead. Lapel grips are filtered out at the substrate (HAJ-161
# is_collar() gate), so this template never reaches a non-collar grip.
_HEAD_STEER_GRIP_STRENGTH_THRESHOLD: float = 0.5


# HAJ-162 — the (closing, grip_war) entry is dynamic (resolved by
# `_grip_seating_prose` against engine state) so the line is honest
# about whether one or both fighters actually seated grips on the
# transition tick. The static fallback below is used only when no
# match object is available (e.g., legacy unit-test paths that exercise
# the transition table directly).
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
# HAJ-162 — outcome-bound prose for grip seating
# ---------------------------------------------------------------------------
def _grip_seating_prose(match: "Match", tick: int) -> str:
    """Resolve the (closing → grip_war) phase-transition line against
    engine state at the transition tick.

    Pre-HAJ-162: the static "Both fighters lock onto their grips" fired
    every time the position transitioned to GRIPPING. After HAJ-151
    grip-initiative variance and HAJ-162 triage stretched the
    leader→follower lag to GRIP_CASCADE_LAG_TICKS=2, only the leader's
    grips have seated on the transition tick — claiming "both" was
    false by one fighter.

    Post-fix: read each fighter's own-grip-edge count and compose:
      - Both gripped → "Both fighters lock onto their grips." (canonical)
      - One gripped  → first-grip line, contested or uncontested.
      - Neither      → fallback to the canonical line (defensive; should
                        not happen because the engine sets GRIPPING
                        position only after at least one grip seats).

    HAJ-225 — the strings now come from the data-driven grip_narration layer,
    and the one-gripped case can read as contested. With HAJ-224's single-hand
    first grip the leader seats one grip and the follower responds a beat
    later, so the initiation tick is a genuine contest rather than always a
    clean shut-out (`finds nothing`).
    """
    a_name = match.fighter_a.identity.name
    b_name = match.fighter_b.identity.name
    a_has = bool(match.grip_graph.edges_owned_by(a_name))
    b_has = bool(match.grip_graph.edges_owned_by(b_name))
    if a_has == b_has:
        # Both gripped, or (defensively) neither.
        return grip_narration.select_line(grip_narration.BOTH_GRIPS, seed=tick)
    leader, follower = (a_name, b_name) if a_has else (b_name, a_name)
    key = (
        grip_narration.FIRST_GRIP_CONTESTED
        if _first_grip_contested(match, tick)
        else grip_narration.FIRST_GRIP_UNCONTESTED
    )
    return grip_narration.select_line(
        key, seed=tick, leader=leader, follower=follower,
    )


def _first_grip_contested(match: "Match", tick: int) -> bool:
    """HAJ-225 — does the first-grip tick read as contested?

    The follower contests when a cascade response is staged (HAJ-151/224: the
    leader seats the lead grip and the follower answers a beat later, so a
    response is pending on the transition tick). We keep some clean-shut-out
    variety so it isn't *always* contested — deterministic in `tick` for
    replay stability."""
    cascade_pending = getattr(match, "_grip_cascade", None) is not None
    if not cascade_pending:
        return False
    return random.Random(f"haj225:firstgrip:{tick}").random() < 0.65


# ---------------------------------------------------------------------------
# HAJ-166 — outcome-bound prose for collar-grip head-steering
# ---------------------------------------------------------------------------
def _head_steer_prose(match: "Match", victim_name: str) -> Optional[str]:
    """Resolve the head-steer line for `victim_name` against the live
    grip graph. Returns the prose string, or None when no collar grip
    with STEER intent is on the victim (the BPE substrate would have
    suppressed the HEAD_AS_OUTPUT event in that case too — defensive).

    Discrimination:
      - COLLAR_BACK → oku-eri / nape grip; head moves down-and-forward.
      - COLLAR_SIDE → kata-eri / trapezius grip; head turns / chin off.
      - Below the strength threshold → the force is absorbed; substitute
        with a "stays planted" line instead of an effective steer.

    Lapel grips never reach this path because HAJ-161's is_collar()
    filter on `compute_head_state` suppresses the BPE; the narrator's
    detector keys off the HEAD_AS_OUTPUT BPE, so a lapel-only steer
    produces no input here.
    """
    from enums import GripTypeV2
    primary = None
    for edge in match.grip_graph.edges:
        if edge.target_id != victim_name:
            continue
        if edge.current_intent != "STEER":
            continue
        if not edge.grip_type_v2.is_collar():
            continue
        primary = edge
        break
    if primary is None:
        return None
    grasper_name = primary.grasper_id
    effective = primary.strength >= _HEAD_STEER_GRIP_STRENGTH_THRESHOLD
    if not effective:
        # Blocked — force absorbed, posture stiff. Same template across
        # both collar sub-types; the failure mode is the same beat
        # (no head movement).
        side_word = (
            "back collar" if primary.grip_type_v2 is GripTypeV2.COLLAR_BACK
            else "side collar"
        )
        return (
            f"{grasper_name} cranks at the {side_word} — "
            f"{victim_name}'s neck stays planted."
        )
    if primary.grip_type_v2 is GripTypeV2.COLLAR_BACK:
        return (
            f"{grasper_name} pulls {victim_name}'s head down with the "
            f"back collar."
        )
    if primary.grip_type_v2 is GripTypeV2.COLLAR_SIDE:
        return (
            f"{grasper_name} cranks the side collar, turning "
            f"{victim_name}'s chin off-center."
        )
    return None


# ---------------------------------------------------------------------------
# HAJ-165 — movement prose (circling / posture / pull-without-commit)
#
# Three connective-beat families that fill the dead air between grip events
# and throw commits. Each follows the HAJ-162 dynamic-resolver pattern:
# read engine state at emission time, render only what's actually true.
# ---------------------------------------------------------------------------

# Suppress movement prose on ticks that already carry a state-change event
# — those have their own prose lines (always-promote / phase / contradiction)
# and movement beats would just duplicate the slot. THROW_ENTRY is included
# because a commit-tick is precisely when movement prose should defer.
_MOVEMENT_SUPPRESS_EVENT_TYPES: frozenset[str] = frozenset({
    "THROW_ENTRY", "THROW_LANDING", "STUFFED", "FAILED",
    "SCORE_AWARDED", "IPPON_AWARDED", "COUNTER_COMMIT",
    "MATTE", "NEWAZA_TRANSITION",
    "KUZUSHI_INDUCED",
    "GRIP_ESTABLISH",
})


# Per-tactical-intent prose. Keys are the tactical_intent string carried
# on the MOVE event; the resolver picks the line for the actor / opponent
# pair. Intents not listed return None (no movement prose for that step).
def _circling_prose(
    tactical_intent: Optional[str], actor: str, opponent: str,
) -> Optional[str]:
    if tactical_intent is None:
        return None
    if tactical_intent in ("circle", "circle_closing"):
        return f"{actor} circles, looking for an angle on {opponent}."
    if tactical_intent == "lateral_approach":
        return f"{actor} steps wide, working {opponent} into space."
    if tactical_intent == "bait_retreat":
        return f"{actor} steps back, baiting {opponent} forward."
    if tactical_intent in ("closing", "step_in"):
        return f"{actor} closes ground on {opponent}."
    if tactical_intent == "pressure":
        return f"{actor} drives forward, pressing {opponent}."
    if tactical_intent == "give_ground":
        return f"{actor} gives ground, ceding the center."
    if tactical_intent == "gain_angle":
        return f"{actor} works for an angle on {opponent}."
    return None


def _posture_change_prose(
    name: str, old_posture, new_posture,
) -> Optional[str]:
    """Render a one-line beat for a posture transition that didn't go
    through kuzushi. Transitions INTO BROKEN are kuzushi events and own
    their own prose; transitions OUT of BROKEN are recoveries; the
    UPRIGHT ↔ SLIGHTLY_BENT pair is the "settling in / straightening
    up" beat the ticket calls for."""
    from enums import Posture
    if old_posture is new_posture:
        return None
    # BROKEN entry is a kuzushi event — engine emits KUZUSHI_INDUCED on
    # the same tick and that's the prose line. Don't double-author.
    if new_posture is Posture.BROKEN:
        return None
    if old_posture is Posture.BROKEN:
        return f"{name} recovers posture, base re-set."
    if (old_posture is Posture.UPRIGHT
            and new_posture is Posture.SLIGHTLY_BENT):
        return f"{name} bends in, weight rolling onto the front foot."
    if (old_posture is Posture.SLIGHTLY_BENT
            and new_posture is Posture.UPRIGHT):
        return f"{name} straightens up, posture restored."
    return None


def _region_transition_prose(
    name: str, old_region, new_region,
) -> Optional[str]:
    """HAJ-142 — short connective beat for a fighter's region change.
    Returns None when the change isn't worth surfacing (entry to the
    same band twice, OOB transitions which the engine's HAJ-127 prose
    already covers, or any baseline establish where the prior region
    is unknown). Lean toward narrating arrivals at the WARNING and
    CENTER bands — they're the bands a viewer cares about; WORKING is
    the default and largely silent."""
    from enums import MatRegion
    if old_region is None or old_region == new_region:
        return None
    # OOB is owned by the existing OOB / Matte prose path.
    if new_region is MatRegion.OUT_OF_BOUNDS:
        return None
    # Returning to CENTER from outer bands: a recovered-position beat.
    if new_region is MatRegion.CENTER:
        return f"{name} works back to the center of the mat."
    if new_region is MatRegion.WARNING:
        return f"{name} drifts into the warning area near the edge."
    # WORKING entries from CENTER are bland; WORKING from WARNING is
    # a recovery beat.
    if (new_region is MatRegion.WORKING
            and old_region is MatRegion.WARNING):
        return f"{name} steps off the line, back into open mat."
    return None


def _pull_without_commit_prose(
    actor: str, opponent: str, target: Optional[str],
) -> str:
    """Outcome-bound line for a PULL / REACH BPE that didn't reach the
    commit threshold. The grip referent (sleeve / lapel / collar)
    sharpens the prose; uke 'rides it out' reads the absence of a
    follow-up commit honestly."""
    if target == "SLEEVE":
        return f"{actor} tugs at the sleeve — {opponent} rides it out."
    if target == "LAPEL":
        return (
            f"{actor} hauls on the lapel, but {opponent} stays "
            f"square."
        )
    if target == "COLLAR":
        return (
            f"{actor} hooks the collar and tries to break "
            f"{opponent}'s posture — no give."
        )
    return f"{actor} pulls in but {opponent} absorbs the load."


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
        # HAJ-167 — windowed-pull narration. The narrator keeps a fixed-
        # size ring of recent TickFrames so rules can read across ticks
        # (posture/region delta detection, deferred pull-without-commit
        # gap surfacing). Pre-decouple the legacy per-detector state
        # fields lived on the instance directly; post-decouple they're
        # reads against `self._window[-2]` (the previous frame).
        self._window: list[TickFrame] = []
        # Pull BPEs the deferred pull-without-commit rule has already
        # rendered prose for. The rule defers firing by K ticks; this
        # tracker prevents the same pull from firing twice as the
        # window slides.
        self._fired_pull_bpe_keys: set[tuple[int, str]] = set()

    def consume_tick(
        self, tick: int, events: list, bpes: list[BodyPartEvent],
        match: "Match",
    ) -> list[MatchClockEntry]:
        """HAJ-167 — windowed-pull entry point. The narrator captures
        the current frame, slides the window, and runs the explicit
        rule pipeline over the window. Each rule reads from the window
        (current frame and/or prior frames); rules 1-4 emit a state-
        change suppress flag that downstream movement / sample rules
        respect so the slot isn't double-authored.

        Pre-decouple this function inlined the rule logic and kept
        per-detector state on the narrator (`_last_posture`,
        `_last_region`, etc.). Post-decouple delta detection reads
        `self._window[-2]` and gap surfacing reads the trailing slice;
        the per-detector state fields are gone.
        """
        # Capture this tick's frame. Snapshot is built before any rule
        # runs so all rules see the same view.
        snapshot = _build_match_snapshot(tick, match)
        frame = TickFrame(
            tick=tick,
            events=tuple(events),
            bpes=tuple(bpes),
            snapshot=snapshot,
        )
        self._window.append(frame)
        if len(self._window) > _NARRATION_WINDOW_SIZE:
            self._window = self._window[-_NARRATION_WINDOW_SIZE:]

        out: list[MatchClockEntry] = []

        # Pipeline rule 1 — phase transition (highest-priority slot
        # owner; runs first so the transition line precedes whatever
        # else this tick brought).
        out.extend(self._rule_phase_transition(tick, match))

        # Pipeline rule 2 — always-promote engine events (echoes the
        # event description verbatim).
        out.extend(self._rule_always_promote(tick, events))

        # Pipeline rule 3 — contradictions (self-cancel / intent
        # outcome mismatch).
        out.extend(self._detect_self_cancel(tick, bpes))
        out.extend(self._detect_intent_outcome_mismatch(tick, bpes))

        # Pipeline rule 3b (HAJ-225) — successful strip outcomes (partial /
        # full) authored off the GRIP_DEGRADE / GRIP_STRIPPED engine events.
        out.extend(self._detect_grip_strip_outcome(tick, events))

        # Pipeline rule 4 — non-default modifier promotion.
        out.extend(self._promote_modifier_extremes(tick, bpes))

        # Pipeline rule 5 — head-steer (collar grip). HEAD_AS_OUTPUT
        # BPE substrate; reads live grip graph for collar sub-type.
        out.extend(self._detect_head_steer(tick, bpes, match))

        # Pipeline rule 6 — posture-change beat. Reads window[-2] for
        # the previous frame's posture (no per-detector state needed
        # post-decouple).
        out.extend(self._rule_posture_change(tick, events))

        # Suppression flag — when this tick already carries a state-
        # change engine event (commit / land / score / matte / etc.),
        # the lower-priority movement / region / sample rules defer.
        # The window's trailing pull-without-commit rule is exempt
        # (it's a deferred rule and may legitimately fire on the
        # state-change tick reading older frames).
        suppress_movement = any(
            ev.event_type in _MOVEMENT_SUPPRESS_EVENT_TYPES
            for ev in events
        )

        if not suppress_movement:
            # Pipeline rule 7 — region transition.
            out.extend(self._rule_region_transition(tick))
            # Pipeline rule 8 — circling.
            out.extend(self._detect_circling(tick, events, match))

        # Pipeline rule 9 — deferred pull-without-commit (windowed).
        # The new HAJ-167 rule. Fires K ticks AFTER a PULL BPE if no
        # commit followed. Pre-decouple this fired blind on the PULL
        # tick and could mis-narrate when a commit was actually
        # inbound; post-decouple it reads the trailing window slice
        # and only fires when the gap is real. Allowed to run even on
        # state-change ticks because it references older frames whose
        # context is known stable.
        out.extend(self._rule_deferred_pull_without_commit(tick))

        # Pipeline rule 10 — sample fill. Last-resort prose when
        # nothing else fired; rate-limited per phase.
        if not out and (tick - self._last_sample_tick) >= _STABLE_SAMPLE_INTERVAL:
            sample = self._sample_phase(tick, match, bpes)
            if sample is not None:
                out.append(sample)
                self._last_sample_tick = tick

        if out:
            self._last_promoted_tick = tick
        return out

    # -----------------------------------------------------------------
    # HAJ-167 — promotion-rule pipeline (windowed pull).
    # Each `_rule_*` reads from the captured window via
    # `self._window[-1]` (current frame) and / or `self._window[-2]`
    # (previous frame for delta detection) instead of bookkeeping
    # state on the narrator instance.
    # -----------------------------------------------------------------
    def _rule_phase_transition(
        self, tick: int, match: "Match",
    ) -> list[MatchClockEntry]:
        out: list[MatchClockEntry] = []
        phase = self._phase_label(match)
        if self._last_phase is not None and phase != self._last_phase:
            transition = (self._last_phase, phase)
            if transition == ("closing", "grip_war"):
                prose = _grip_seating_prose(match, tick)
            else:
                prose = _PHASE_TRANSITION_PROSE.get(
                    transition,
                    f"phase shifts: {self._last_phase} → {phase}.",
                )
            out.append(MatchClockEntry(
                tick=tick, prose=prose, source="phase",
            ))
        self._last_phase = phase
        return out

    def _rule_always_promote(
        self, tick: int, events: list,
    ) -> list[MatchClockEntry]:
        out: list[MatchClockEntry] = []
        for ev in events:
            et = ev.event_type
            if et in _ALWAYS_PROMOTE_EVENT_TYPES:
                out.append(MatchClockEntry(
                    tick=tick, prose=ev.description,
                    source=self._source_for(et),
                ))
            elif et in (
                "OFFENSIVE_DESPERATION_ENTER",
                "DEFENSIVE_DESPERATION_ENTER",
            ):
                desc = ev.description
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
        return out

    def _rule_posture_change(
        self, tick: int, events: list,
    ) -> list[MatchClockEntry]:
        """HAJ-167 — windowed posture-change rule. Reads window[-2] for
        the previous frame's per-fighter posture; no per-detector
        state field on the narrator. Suppresses on KUZUSHI_INDUCED
        ticks (engine prose owns that line)."""
        if any(ev.event_type == "KUZUSHI_INDUCED" for ev in events):
            return []
        if len(self._window) < 2:
            return []
        prev = self._window[-2].snapshot
        cur = self._window[-1].snapshot
        if cur.a_name is None or prev.a_name is None:
            return []
        out: list[MatchClockEntry] = []
        for name, prev_p, cur_p in (
            (cur.a_name, prev.a_posture, cur.a_posture),
            (cur.b_name, prev.b_posture, cur.b_posture),
        ):
            if prev_p is None or cur_p is None:
                continue
            prose = _posture_change_prose(name, prev_p, cur_p)
            if prose is None:
                continue
            out.append(MatchClockEntry(
                tick=tick, prose=prose,
                source="posture", actors=(name,),
            ))
        return out

    def _rule_region_transition(
        self, tick: int,
    ) -> list[MatchClockEntry]:
        """HAJ-167 — windowed region-transition rule. Reads window[-2]
        for the previous frame's per-fighter region; no per-detector
        state field on the narrator."""
        if len(self._window) < 2:
            return []
        prev = self._window[-2].snapshot
        cur = self._window[-1].snapshot
        if cur.a_name is None or prev.a_name is None:
            return []
        out: list[MatchClockEntry] = []
        for name, prev_r, cur_r in (
            (cur.a_name, prev.a_region, cur.a_region),
            (cur.b_name, prev.b_region, cur.b_region),
        ):
            if prev_r is None or cur_r is None:
                continue
            prose = _region_transition_prose(name, prev_r, cur_r)
            if prose is None:
                continue
            out.append(MatchClockEntry(
                tick=tick, prose=prose,
                source="region", actors=(name,),
            ))
        return out

    def _rule_deferred_pull_without_commit(
        self, tick: int,
    ) -> list[MatchClockEntry]:
        """HAJ-167 — the architectural improvement.

        Pre-decouple, pull-without-commit fired on the PULL tick — but
        the narrator didn't know whether a commit was about to follow.
        On real pull-then-commit chains the prose still fired, claiming
        the opponent 'rides it out' even when a throw landed two ticks
        later. The line was honest most of the time but blind.

        Post-decouple: a PULL BPE in window[t - K] fires prose at tick t
        only if no THROW_ENTRY for the same actor landed in
        window[t - K + 1 .. t]. The K-tick wait is the gap: if a commit
        actually followed, this rule sees it and stays silent. If no
        commit followed, the gap is real and the prose lands honestly,
        K ticks late.
        """
        if len(self._window) < _DEFERRED_PULL_K_TICKS + 1:
            return []
        # Locate the trigger frame (window slice ends at the current
        # frame; the trigger is K ticks back).
        trigger_idx = -1 - _DEFERRED_PULL_K_TICKS
        if abs(trigger_idx) > len(self._window):
            return []
        trigger = self._window[trigger_idx]
        # Followup window: ticks AFTER the trigger up to and including
        # the current tick.
        followup_frames = self._window[trigger_idx + 1:]
        # HAJ-229 — gate the whole rule when the deferral window straddles
        # a throw resolution, score, matte, or ne-waza drop. The PULL was
        # pre-throw; surfacing "tugs at the sleeve" now would attribute it
        # to the just-thrown fighter (triage cluster 3.2, t011). These are
        # dyad-global state changes, so one such event anywhere in the
        # window (trigger tick through current) suppresses the line for
        # every actor — the pre-throw grip context is stale.
        for wf in self._window[trigger_idx:]:
            if any(
                ev.event_type in _DEFERRED_PULL_INVALIDATING_EVENTS
                for ev in wf.events
            ):
                return []
        # Backstop for transitions whose bridging event wasn't promoted
        # into a frame: the dyad slid into ne-waza, or reset to standing-
        # distant, between the trigger tick and now.
        from enums import Position, SubLoopState
        cur_snap = self._window[-1].snapshot
        if (
            cur_snap.sub_loop_state == SubLoopState.NE_WAZA
            and trigger.snapshot.sub_loop_state != SubLoopState.NE_WAZA
        ):
            return []
        if (
            cur_snap.position == Position.STANDING_DISTANT
            and trigger.snapshot.position != Position.STANDING_DISTANT
        ):
            return []
        in_progress = trigger.snapshot.in_progress_attackers
        out: list[MatchClockEntry] = []
        seen_actors: set[str] = set()
        for b in trigger.bpes:
            if b.source != "PULL":
                continue
            actor = b.actor
            if actor in seen_actors:
                continue
            # Skip if actor was mid-commit at the trigger tick.
            if actor in in_progress:
                continue
            # Did a commit fire for this actor in the K-tick follow-up
            # window? COMMIT-source BPEs accompany THROW_ENTRY events
            # one-to-one and carry the attacker name on .actor; any
            # such BPE in the followup means the pull was a setup, so
            # the gap-prose stays silent.
            committed = False
            for ff in followup_frames:
                for fb in ff.bpes:
                    if fb.source == "COMMIT" and fb.actor == actor:
                        committed = True
                        break
                if committed:
                    break
            if committed:
                continue
            # Dedupe — don't fire twice for the same trigger BPE as
            # the window slides.
            key = (trigger.tick, actor)
            if key in self._fired_pull_bpe_keys:
                continue
            # Rate-limit per actor (per the legacy 6-tick window).
            if not self._rate_check(actor, "pull_no_commit", tick):
                continue
            opponent = self._opponent_of(actor, None)
            if opponent is None:
                opponent = self._opponent_from_snapshot(actor, trigger.snapshot)
            if opponent is None:
                continue
            target = b.target.name if b.target is not None else None
            seen_actors.add(actor)
            self._fired_pull_bpe_keys.add(key)
            out.append(MatchClockEntry(
                tick=tick,
                prose=_pull_without_commit_prose(actor, opponent, target),
                source="pull_no_commit",
                actors=(actor,),
            ))
        # Cap memory growth — drop fired keys older than the window.
        oldest_tick = self._window[0].tick
        self._fired_pull_bpe_keys = {
            k for k in self._fired_pull_bpe_keys if k[0] >= oldest_tick
        }
        return out

    def _opponent_from_snapshot(
        self, actor: str, snap: MatchSnapshot,
    ) -> Optional[str]:
        if actor == snap.a_name:
            return snap.b_name
        if actor == snap.b_name:
            return snap.a_name
        return None

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
        """Failed strip — a strip BPE that snapped at the grip with no
        mechanical effect (intent=BREAK, verb=SNAP). HAJ-225: a partial
        degrade now carries verb=BREAK and is narrated as a successful
        partial strip by `_detect_grip_strip_outcome`, so SNAP here is the
        genuine 'held it' case. String comes from the data-driven layer."""
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
                prose = grip_narration.select_line(
                    grip_narration.STRIP_FAILED,
                    seed=tick, actor=b.actor, target_phrase=tgt,
                )
                out.append(MatchClockEntry(
                    tick=tick, prose=prose,
                    source="intent_mismatch",
                    actors=(b.actor,),
                ))
        return out

    # HAJ-225 — depth label for partial-strip prose. The engine event carries
    # the post-degrade depth name; render it as a short phrase.
    _STRIP_DEPTH_PHRASE: dict[str, str] = {
        "STANDARD": "shallower hold",
        "POCKET":   "pocket",
        "SLIPPING": "slipping fingertip hold",
    }

    def _detect_grip_strip_outcome(
        self, tick: int, events: list,
    ) -> list[MatchClockEntry]:
        """HAJ-225 — author plain-language mat-side prose for successful
        strips, off the GRIP_DEGRADE (partial) and GRIP_STRIPPED (full)
        engine events. Distinct from the failed-strip 'can't budge it' line.
        Rate-limited per stripper so a multi-tick strip run doesn't flood
        the clock log."""
        out: list[MatchClockEntry] = []
        for ev in events:
            et = ev.event_type
            if et not in ("GRIP_DEGRADE", "GRIP_STRIPPED"):
                continue
            data = getattr(ev, "data", {}) or {}
            stripper = data.get("stripper")
            owner = data.get("owner")
            grip = data.get("grip_label")
            if not (stripper and owner and grip):
                # Event wasn't enriched (e.g. a fatigue/voluntary degrade with
                # no stripper) — skip rather than mis-author a strip line.
                continue
            if not self._rate_check(stripper, "grip_strip_outcome", tick):
                continue
            if et == "GRIP_STRIPPED":
                prose = grip_narration.select_line(
                    grip_narration.STRIP_FULL,
                    seed=tick, stripper=stripper, target=owner, grip=grip,
                )
            else:
                depth = self._STRIP_DEPTH_PHRASE.get(
                    data.get("new_depth", ""), "shallower hold",
                )
                prose = grip_narration.select_line(
                    grip_narration.STRIP_PARTIAL,
                    seed=tick, stripper=stripper, target=owner,
                    grip=grip, depth=depth,
                )
            out.append(MatchClockEntry(
                tick=tick, prose=prose,
                source="grip_strip_outcome",
                actors=(stripper,),
            ))
        return out

    def _detect_head_steer(
        self, tick: int, bpes: list[BodyPartEvent], match: "Match",
    ) -> list[MatchClockEntry]:
        """HAJ-166 — render a single outcome-bound head-steer line per
        victim per tick (rate-limited). Fires off HEAD_AS_OUTPUT BPEs
        so the narration follows the substrate; the live grip graph
        supplies the collar sub-type and effectiveness."""
        out: list[MatchClockEntry] = []
        seen_victims: set[str] = set()
        for b in bpes:
            if b.tick != tick:
                continue
            if b.source != "HEAD_AS_OUTPUT":
                continue
            if b.actor in seen_victims:
                continue
            if not self._rate_check(b.actor, "head_steer", tick):
                continue
            prose = _head_steer_prose(match, b.actor)
            if prose is None:
                continue
            seen_victims.add(b.actor)
            out.append(MatchClockEntry(
                tick=tick, prose=prose,
                source="head_steer",
                actors=(b.actor,),
            ))
        return out

    def _detect_circling(
        self, tick: int, events: list, match: "Match",
    ) -> list[MatchClockEntry]:
        """HAJ-165 — read MOVE engine events with a tactical_intent
        label and render at most one circling beat per actor per tick,
        rate-limited through _rate_check (default 6-tick window). The
        prose cites the actual locomotion intent so the line matches
        the geometry. Only fires while the dyad is mid-fight (gripping
        / engaged / standing-distant) — ne-waza has its own substrate."""
        from enums import SubLoopState, Position
        if match.sub_loop_state == SubLoopState.NE_WAZA:
            return []
        if match.position not in (
            Position.GRIPPING, Position.ENGAGED, Position.STANDING_DISTANT,
        ):
            return []
        out: list[MatchClockEntry] = []
        seen_actors: set[str] = set()
        for ev in events:
            if ev.event_type != "MOVE":
                continue
            actor = ev.data.get("fighter")
            if not actor or actor in seen_actors:
                continue
            opponent = self._opponent_of(actor, match)
            if opponent is None:
                continue
            tactical = ev.data.get("tactical_intent")
            prose = _circling_prose(tactical, actor, opponent)
            if prose is None:
                continue
            if not self._rate_check(actor, "circling", tick):
                continue
            seen_actors.add(actor)
            out.append(MatchClockEntry(
                tick=tick, prose=prose,
                source="circling",
                actors=(actor,),
            ))
        return out

    def _detect_posture_change(
        self, tick: int, events: list, match: "Match",
    ) -> list[MatchClockEntry]:
        """HAJ-165 — fire a single line per fighter whose discrete
        posture (UPRIGHT / SLIGHTLY_BENT / BROKEN) changed since the
        last tick. Transitions INTO BROKEN are owned by KUZUSHI_INDUCED
        prose; transitions OUT of BROKEN are recoveries. Always
        promotes on state change (no rate limit) per AC#4."""
        from body_state import derive_posture
        # Defensive — legacy unit-test stubs don't always carry fighter
        # references. Skip silently in that case so the existing test
        # surface (e.g. desperation-prose stub matches) isn't broken.
        fighter_a = getattr(match, "fighter_a", None)
        fighter_b = getattr(match, "fighter_b", None)
        if fighter_a is None or fighter_b is None:
            return []
        # KUZUSHI_INDUCED ticks belong to the engine's kuzushi prose; a
        # posture beat would just paraphrase the same beat.
        if any(ev.event_type == "KUZUSHI_INDUCED" for ev in events):
            for fighter in (fighter_a, fighter_b):
                bs = fighter.state.body_state
                self._last_posture[fighter.identity.name] = derive_posture(
                    bs.trunk_sagittal, bs.trunk_frontal,
                )
            return []
        out: list[MatchClockEntry] = []
        for fighter in (fighter_a, fighter_b):
            name = fighter.identity.name
            bs = fighter.state.body_state
            current = derive_posture(bs.trunk_sagittal, bs.trunk_frontal)
            previous = self._last_posture.get(name)
            self._last_posture[name] = current
            if previous is None:
                continue  # baseline tick; no prose
            prose = _posture_change_prose(name, previous, current)
            if prose is None:
                continue
            out.append(MatchClockEntry(
                tick=tick, prose=prose,
                source="posture",
                actors=(name,),
            ))
        return out

    def _detect_pull_without_commit(
        self, tick: int, bpes: list[BodyPartEvent], match: "Match",
    ) -> list[MatchClockEntry]:
        """HAJ-165 — render a connective beat when a PULL BPE fires
        this tick without the actor being mid-commit. The suppression
        gate at the call site already handles THROW_ENTRY ticks; this
        detector additionally checks _throws_in_progress so a multi-
        tick attempt that started earlier doesn't get described as
        'no commit' just because THROW_ENTRY isn't on this tick.
        Rate-limited through _rate_check.
        REACH BPEs are excluded — REACH is "extending the hand toward
        a grip target," fired before any edge exists. The "hauls on
        the lapel" / "tugs at the sleeve" prose family describes
        force through a live grip, so emitting it for REACH produces
        false copy ('Renard hauls on the lapel' before contact, with
        no lapel grip seated). Only PULL (which requires an existing
        edge) drives this template.
        """
        out: list[MatchClockEntry] = []
        seen_actors: set[str] = set()
        in_progress = set(getattr(match, "_throws_in_progress", {}).keys())
        for b in bpes:
            if b.tick != tick:
                continue
            if b.source != "PULL":
                continue
            actor = b.actor
            if actor in seen_actors or actor in in_progress:
                continue
            opponent = self._opponent_of(actor, match)
            if opponent is None:
                continue
            if not self._rate_check(actor, "pull_no_commit", tick):
                continue
            target = b.target.name if b.target is not None else None
            seen_actors.add(actor)
            out.append(MatchClockEntry(
                tick=tick,
                prose=_pull_without_commit_prose(actor, opponent, target),
                source="pull_no_commit",
                actors=(actor,),
            ))
        return out

    def _detect_region_transition(
        self, tick: int, match: "Match",
    ) -> list[MatchClockEntry]:
        """HAJ-142 — render a single line per fighter whose mat region
        changed since the last tick. State-change beat (always promote
        when the line resolves to non-None); the resolver suppresses
        bland transitions like CENTER→WORKING by default."""
        out: list[MatchClockEntry] = []
        fighter_a = getattr(match, "fighter_a", None)
        fighter_b = getattr(match, "fighter_b", None)
        if fighter_a is None or fighter_b is None:
            return out
        try:
            from match import region_of
        except ImportError:
            return out
        for fighter in (fighter_a, fighter_b):
            name = fighter.identity.name
            current = region_of(fighter)
            previous = self._last_region.get(name)
            self._last_region[name] = current
            if previous is None:
                continue
            prose = _region_transition_prose(name, previous, current)
            if prose is None:
                continue
            out.append(MatchClockEntry(
                tick=tick, prose=prose,
                source="region",
                actors=(name,),
            ))
        return out

    def _refresh_region_baseline(self, match: "Match") -> None:
        fighter_a = getattr(match, "fighter_a", None)
        fighter_b = getattr(match, "fighter_b", None)
        if fighter_a is None or fighter_b is None:
            return
        try:
            from match import region_of
        except ImportError:
            return
        for fighter in (fighter_a, fighter_b):
            self._last_region[fighter.identity.name] = region_of(fighter)

    def _opponent_of(self, actor: str, match: "Match") -> Optional[str]:
        fighter_a = getattr(match, "fighter_a", None)
        fighter_b = getattr(match, "fighter_b", None)
        if fighter_a is None or fighter_b is None:
            return None
        a = fighter_a.identity.name
        b = fighter_b.identity.name
        if actor == a:
            return b
        if actor == b:
            return a
        return None

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
            # HAJ-154 — commit-source BPEs no longer drive modifier-reveal
            # prose. The modifier-reveal text reads as an outcome claim
            # ("X's commit lands crisp and explosive"), but on the commit
            # tick the throw hasn't resolved yet — five out of six
            # instances in the audit log made factually wrong claims
            # (the throw failed). HAJ-148 AC3 requires no prose to
            # co-occur with a commit event tag; this is the prose source
            # that violated it. COUNTER_COMMIT BPEs still surface — a
            # counter is itself a resolution event.
            if b.source != "COUNTER_COMMIT":
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
        # HAJ-233 — these reads are the player's only window into commit
        # quality, so each names the body action *and* its consequence on
        # uke rather than a bare adjective ("crisp and explosive" told the
        # player nothing). Register target: the aborted-line voice — what
        # the commit did, and what it costs. Each branch carries a small
        # variant pool so a commit repeated across one match doesn't read
        # identically (the t015/t328 bloat note); the pick is seeded on
        # (actor, tick) so replays stay deterministic.
        variants: list[str]
        if m.crispness is Crispness.CRISP and m.speed is Speed.EXPLOSIVE:
            variants = [
                f"{b.actor}'s commit fires off the line before uke can read it.",
                f"{b.actor} explodes into the entry — uke gets no warning beat.",
                f"{b.actor}'s commit snaps in fast and clean, inside uke's reaction.",
            ]
        elif m.crispness is Crispness.CRISP:
            variants = [
                f"{b.actor}'s commit snaps in on time — the entry is set before uke can square up.",
                f"{b.actor} times the commit clean, slotting in before uke resets.",
            ]
        elif m.crispness is Crispness.SLOPPY:
            variants = [
                f"{b.actor}'s commit drags in loose — uke feels it coming and braces.",
                f"{b.actor}'s entry arrives ragged, telegraphed enough for uke to set against it.",
            ]
        elif m.tightness is Tightness.FLARING:
            variants = [
                f"{b.actor}'s elbow flares — the power leaks out the side instead of into uke.",
                f"{b.actor}'s arm springs wide, the drive bleeding off before it reaches uke.",
            ]
        elif m.timing is Timing.LATE:
            variants = [
                f"{b.actor} commits late — uke has already moved off the line.",
                f"{b.actor}'s entry lands a beat behind, uke's weight already gone.",
            ]
        elif m.timing is Timing.EARLY:
            variants = [
                f"{b.actor} commits early — the kuzushi hasn't stacked under uke yet.",
                f"{b.actor} fires before uke's balance breaks — nothing to throw against.",
            ]
        elif m.commitment is Commitment.OVERCOMMITTED:
            variants = [
                f"{b.actor} throws himself at it — nothing left to recover if uke isn't there.",
                f"{b.actor} pours everything into the entry, no base kept back if it misses.",
            ]
        elif m.speed is Speed.SLOW:
            variants = [
                f"{b.actor}'s commit is slow off the mark — uke has the beat to answer it.",
                f"{b.actor} loads the entry heavy and late, uke reading it the whole way.",
            ]
        else:
            return prose_for_event(b)
        rng = random.Random(f"haj233:modreveal:{b.actor}:{b.tick}")
        return rng.choice(variants)

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
