# ne_waza_consumption.py
# HAJ-220 — minimum-viable consumption of the ne-waza substrate.
#
# Sibling to availability.py (HAJ-207) but for ground work. Where the
# tachiwaza path filters throws by canonical_grip_signatures against a
# GripGraph, this filters pins/strangles/joint-locks by required_connections
# against a GroundConnectionGraph.
#
# The full substrate machinery (hysteresis enter/stay thresholds, danger
# zone, induced transitions, sensei coaching, use-driven progression,
# referee no-progress timer, full Stage 2 effectiveness scoring,
# connection-quality tuning loop) is explicitly deferred per the ticket;
# everything here is the minimum needed for ground positions in actual
# play to render with their Kodokan-named techniques in the log stream.
#
# Spec: design-notes/triage/ne-waza-vocabulary-system.md §1 (Stage 1
# availability) and §6.5 addendum (consumption semantics).

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from enums import BeltRank, Position
from ne_waza_catalog import (
    ConnectionRequirement, ConnectionType,
    NeWazaPositionDefinition, NeWazaTechniqueDefinition,
    ScoreMechanism,
)

if TYPE_CHECKING:
    import random as _random_mod
    from judoka import Judoka


# ---------------------------------------------------------------------------
# THRESHOLDS — single source of truth so the deferred 40% stay-threshold
# work (addendum §6.5.1) lands as a one-line edit here.
# ---------------------------------------------------------------------------

# Fraction of an authored `minimum_quality` required for a technique to
# be Stage-1 available. v0.1 uses a single threshold — entering and
# staying both at 0.5. The follow-up ticket lowers the stay value to
# 0.4 to add hysteresis; do that by changing STAY_THRESHOLD alone.
ENTRY_THRESHOLD: float = 0.5
STAY_THRESHOLD:  float = 0.5

# Dominant positions enter on a fully-present configuration. Sankaku
# either is or is not formed; nothing in the substrate treats a partial
# triangle as a recognized dominant position.
DOMINANT_POSITION_RECOGNITION_THRESHOLD: float = 1.0

# Submission resolution — minimum-viable tap-check loop. After this many
# failed tori-effectiveness rolls in a row, tori releases and the referee
# calls Matte. Full tap-resistance-curve machinery is deferred.
SUBMISSION_RELEASE_FAILED_TICKS: int = 5


# ---------------------------------------------------------------------------
# CONNECTION EDGE + GRAPH
# Substrate Part 3: the runtime object representing each active connection
# between the two judoka in a ground position.
# ---------------------------------------------------------------------------
@dataclass
class ConnectionEdge:
    """One active connection in a ground position.

    `quality` is in [0.0, 1.0]. Baseline values are set on entry to a
    position; the per-tick tuning loop (substrate Part 2) is deferred,
    so qualities stay at baseline unless the engine explicitly mutates
    them.

    `tori_part` / `target` are substrate strings (e.g. `right_arm` /
    `uke_neck`). For v0.1 the Stage 1 filter matches on type + quality
    only — wiring these strings to the engine body-part model is the
    substrate-strings ticket downstream. They're stored here so the
    follow-up work can read them directly.
    """
    type: ConnectionType
    tori_part: str
    target: str
    quality: float
    setup_ticks_remaining: int = 0
    mechanical_attributes: dict = field(default_factory=dict)


class GroundConnectionGraph:
    """Tracks the set of ConnectionEdges active between tori and uke in a
    ground position. Sibling to the standing GripGraph — same engine role
    (named contacts that gate techniques), entirely different vocabulary.
    """

    def __init__(self) -> None:
        self.edges: list[ConnectionEdge] = []

    def add(self, edge: ConnectionEdge) -> None:
        self.edges.append(edge)

    def clear(self) -> None:
        self.edges.clear()

    def edges_of_type(self, ct: ConnectionType) -> list[ConnectionEdge]:
        return [e for e in self.edges if e.type == ct]

    def has_type_at_quality(self, ct: ConnectionType, quality: float) -> bool:
        return any(e.type == ct and e.quality >= quality for e in self.edges)


# ---------------------------------------------------------------------------
# BASELINE POSITION → CONNECTION CONFIG
# When the engine transitions into a ground position, seed the connection
# graph with a baseline that's strong enough to clear ENTRY_THRESHOLD for
# the canonical pins of that position. Authored from the catalog's most-
# common requirements so the standard pin in each position is selectable
# the tick the position is established.
#
# Values are intentionally a hair above the average authored
# minimum_quality so a default top-fighter holds a baseline that
# satisfies the 50% entry threshold by a clear margin — the
# connection-quality tuning loop (Part 2, deferred) will move them
# around per-tick once it lands.
# ---------------------------------------------------------------------------
def _edge(
    ct: ConnectionType, tori_part: str, target: str, quality: float,
) -> ConnectionEdge:
    return ConnectionEdge(type=ct, tori_part=tori_part, target=target, quality=quality)


_BASELINE_BY_POSITION: dict[Position, list[ConnectionEdge]] = {
    # SIDE_CONTROL covers both LEFT and RIGHT YAML variants. Authored to
    # satisfy hon_kesa_gatame's four required_connections at ENTRY_THRESHOLD.
    Position.SIDE_CONTROL: [
        _edge(ConnectionType.ANATOMICAL_WRAP, "right_arm",
              "uke_neck", 0.7),
        _edge(ConnectionType.ANATOMICAL_TRAP, "left_armpit",
              "uke_right_arm", 0.8),
        _edge(ConnectionType.BODY_PRESSURE, "right_hip_and_chest",
              "uke_right_armpit_and_chest", 0.6),
        _edge(ConnectionType.POSITIONAL_BASE, "left_leg",
              "mat_extended_rear", 0.5),
    ],
    Position.MOUNT: [
        _edge(ConnectionType.BODY_PRESSURE, "hips", "uke_chest", 0.8),
        _edge(ConnectionType.POSITIONAL_BASE, "knees",
              "mat_at_uke_sides", 0.7),
    ],
    Position.BACK_CONTROL: [
        _edge(ConnectionType.BODY_PRESSURE, "chest", "uke_back", 0.7),
        _edge(ConnectionType.ANATOMICAL_WRAP, "legs",
              "uke_inner_thighs", 0.6),
        _edge(ConnectionType.GARMENT_GRIP_NEWAZA, "hands",
              "uke_lapel_and_shoulder", 0.5),
    ],
    Position.GUARD_TOP: [
        _edge(ConnectionType.BODY_PRESSURE, "torso", "uke_torso", 0.5),
    ],
    Position.GUARD_BOTTOM: [
        _edge(ConnectionType.ANATOMICAL_WRAP, "legs", "uke_waist", 0.5),
    ],
    Position.TURTLE_TOP: [
        _edge(ConnectionType.BODY_PRESSURE, "chest", "uke_back", 0.5),
    ],
    Position.TURTLE_BOTTOM: [],
    Position.DOWN: [],
    Position.SCRAMBLE: [],
}


def baseline_graph_for(position: Position) -> GroundConnectionGraph:
    """Build a fresh GroundConnectionGraph seeded with the position's
    baseline ConnectionEdges. Unknown / standing positions get an empty
    graph."""
    graph = GroundConnectionGraph()
    for edge in _BASELINE_BY_POSITION.get(position, ()):
        graph.add(ConnectionEdge(
            type=edge.type,
            tori_part=edge.tori_part,
            target=edge.target,
            quality=edge.quality,
            setup_ticks_remaining=0,
            mechanical_attributes=dict(edge.mechanical_attributes),
        ))
    return graph


# ---------------------------------------------------------------------------
# BELT LADDER — YAML strings → BeltRank → ordinal
# ---------------------------------------------------------------------------
_BELT_STRING_TO_RANK: dict[str, BeltRank] = {
    "white":  BeltRank.WHITE,
    "yellow": BeltRank.YELLOW,
    "orange": BeltRank.ORANGE,
    "green":  BeltRank.GREEN,
    "blue":   BeltRank.BLUE,
    "brown":  BeltRank.BROWN,
}

_BELT_RANK_ORDER: dict[BeltRank, int] = {
    rank: i for i, rank in enumerate([
        BeltRank.WHITE, BeltRank.YELLOW, BeltRank.ORANGE,
        BeltRank.GREEN, BeltRank.BLUE, BeltRank.BROWN,
        BeltRank.BLACK_1, BeltRank.BLACK_2, BeltRank.BLACK_3,
        BeltRank.BLACK_4, BeltRank.BLACK_5,
    ])
}


def _belt_satisfies(
    actor_belt: BeltRank, minimum_belt_string: Optional[str],
) -> bool:
    """True when `actor_belt` is at or above the catalog's belt floor.

    Missing / unknown belt strings are treated as "no floor" — the
    technique is open to any belt. Mirrors the validator's lenient stance
    on the optional minimum_belt_for_competition_use field.
    """
    if not minimum_belt_string:
        return True
    floor = _BELT_STRING_TO_RANK.get(minimum_belt_string.lower())
    if floor is None:
        return True
    return _BELT_RANK_ORDER[actor_belt] >= _BELT_RANK_ORDER[floor]


# ---------------------------------------------------------------------------
# POSITION STRING MATCHING
# YAML uses substrate names (SIDE_CONTROL_RIGHT, sankaku_position, ...).
# Engine uses the Position enum (SIDE_CONTROL, MOUNT, ...). NORTH_SOUTH
# and SIDE_CONTROL_LEFT have no engine counterpart yet; those techniques
# stay filtered out until the position-machine substrate expansion lands.
# ---------------------------------------------------------------------------
def _yaml_pos_matches_engine(
    yaml_pos: Optional[str], engine_pos: Position,
) -> bool:
    if not yaml_pos:
        return False
    if yaml_pos == "any":
        return True
    name = engine_pos.name
    if yaml_pos == name:
        return True
    # SIDE_CONTROL_RIGHT / SIDE_CONTROL_LEFT both fold into SIDE_CONTROL.
    return yaml_pos.startswith(name + "_")


def _technique_position_matches(
    definition: NeWazaTechniqueDefinition,
    engine_position: Position,
    dominant_position_id: Optional[str],
) -> bool:
    """A technique passes its position gate if any of the following:
      - both parent_position and fires_from_position are null
        (position-agnostic — submissions);
      - parent_position matches the engine position;
      - fires_from_position matches the active dominant_position_id.
    """
    parent = definition.parent_position
    fires_from = definition.fires_from_position
    if parent is None and fires_from is None:
        return True
    if parent is not None and _yaml_pos_matches_engine(parent, engine_position):
        return True
    if fires_from is not None and dominant_position_id is not None:
        if fires_from == dominant_position_id:
            return True
    return False


# ---------------------------------------------------------------------------
# CONNECTION SATISFACTION
# ---------------------------------------------------------------------------
def _requirement_satisfied(
    graph: GroundConnectionGraph,
    requirement: ConnectionRequirement,
    threshold_fraction: float,
) -> bool:
    """True when at least one edge in `graph` is of the required type
    at quality >= `threshold_fraction * requirement.minimum_quality`.

    v0.1 matches by ConnectionType only. The substrate-strings ticket
    will tighten this to also match tori_part / target once those
    substrate strings have engine bindings.
    """
    needed = requirement.minimum_quality * threshold_fraction
    return graph.has_type_at_quality(requirement.type, needed)


def _connections_satisfied(
    graph: GroundConnectionGraph,
    requirements: list[ConnectionRequirement],
    threshold_fraction: float,
) -> bool:
    return all(
        _requirement_satisfied(graph, r, threshold_fraction)
        for r in requirements
    )


def _connection_quality_margin(
    graph: GroundConnectionGraph,
    requirements: list[ConnectionRequirement],
) -> float:
    """Sum of (best_matching_edge_quality - minimum_quality) across all
    required_connections. Used as Stage 2 tiebreak — the pin tori has
    the firmest grip on wins.

    Returns 0.0 for empty requirement lists (position-agnostic submissions
    fall back to alphabetical tiebreak).
    """
    if not requirements:
        return 0.0
    total = 0.0
    for r in requirements:
        best = 0.0
        for e in graph.edges:
            if e.type == r.type and e.quality > best:
                best = e.quality
        total += best - r.minimum_quality
    return total


# ---------------------------------------------------------------------------
# STAGE 1 — AVAILABILITY FILTER
# ---------------------------------------------------------------------------
def ne_waza_stage1_available_techniques(
    connection_graph: GroundConnectionGraph,
    position_state: Position,
    tori: "Judoka",
    uke: "Judoka",
    techniques: dict[str, NeWazaTechniqueDefinition],
    positions: dict[str, NeWazaPositionDefinition],
    dominant_position_id: Optional[str] = None,
) -> set[str]:
    """Return technique_ids whose required_connections are satisfied by
    the current ConnectionEdge set AND whose parent_position or
    fires_from_position matches the current state AND that tori knows.

    Per ticket §2: connection gate uses ENTRY_THRESHOLD (50% of authored
    minimum_quality). The 40% stay-threshold and danger-zone machinery
    is deferred to the hysteresis follow-up ticket; the STAY_THRESHOLD
    constant above is the documented hook for that work.

    Position gate: a technique passes if `parent_position` matches the
    engine position (e.g. engine SIDE_CONTROL satisfies YAML
    SIDE_CONTROL_RIGHT), OR if `fires_from_position` matches the active
    dominant_position_id, OR if both are null (position-agnostic
    submissions — Stage 1 only checks connections + belt).

    Belt gate: tori's belt rank must meet `minimum_belt_for_competition_use`.
    Missing belt strings are treated as no floor.

    Dominant-position terminal_techniques are appended automatically:
    if a position recognized as dominant has terminal_techniques, they're
    added to the result set as long as they also pass the belt gate. The
    fires_from_position binding on the catalog technique entries gives
    the same result via the position gate — we walk the position's
    explicit terminal list as a defense in depth in case authoring
    falls out of sync.
    """
    available: set[str] = set()

    for tid, defn in techniques.items():
        if not _belt_satisfies(
            tori.identity.belt_rank,
            defn.minimum_belt_for_competition_use,
        ):
            continue
        if not _technique_position_matches(
            defn, position_state, dominant_position_id,
        ):
            continue
        if not _connections_satisfied(
            connection_graph, defn.required_connections, ENTRY_THRESHOLD,
        ):
            continue
        available.add(tid)

    # Dominant-position terminal_techniques: include even if the technique
    # itself isn't pinned to `fires_from_position` in its YAML entry. This
    # makes the position graph the authoritative source for which finishes
    # are reachable from a dominant position.
    if dominant_position_id is not None:
        pos_def = positions.get(dominant_position_id)
        if pos_def is not None:
            for terminal_id in pos_def.terminal_techniques:
                terminal_def = techniques.get(terminal_id)
                if terminal_def is None:
                    continue
                if not _belt_satisfies(
                    tori.identity.belt_rank,
                    terminal_def.minimum_belt_for_competition_use,
                ):
                    continue
                available.add(terminal_id)

    return available


# ---------------------------------------------------------------------------
# DOMINANT-POSITION RECOGNITION
# Spec §3.3: when the active ConnectionEdge set matches a dominant-position
# entry's required_connections, that position is "in." For v0.1 the catalog
# has two: sankaku_position and back_turtle_with_hooks.
# ---------------------------------------------------------------------------
def recognize_dominant_position(
    connection_graph: GroundConnectionGraph,
    positions: dict[str, NeWazaPositionDefinition],
    engine_position: Optional[Position] = None,
) -> Optional[str]:
    """Return the position_id of the first dominant position whose
    required_connections are fully satisfied by the active graph, or
    None.

    Per spec §3.3 dominant-position entries declare `parent_position`,
    which may be `any` (sankaku) or a broad engine position
    (back_turtle_with_hooks: BACK_CONTROL). If `engine_position` is
    supplied, candidates with a non-`any` parent_position are filtered
    against it; passing None disables the check (mostly useful in tests).
    """
    for pid, defn in positions.items():
        if engine_position is not None and defn.parent_position != "any":
            if not _yaml_pos_matches_engine(defn.parent_position, engine_position):
                continue
        if _connections_satisfied(
            connection_graph,
            defn.required_connections,
            DOMINANT_POSITION_RECOGNITION_THRESHOLD,
        ):
            return pid
    return None


# ---------------------------------------------------------------------------
# STAGE 2 — MINIMAL FIRST-AVAILABLE COMMIT
# Per ticket §4: prefer techniques with higher base_difficulty that tori
# can plausibly execute (belt eligibility was the Stage 1 gate);
# connection-quality margin tiebreaks; alphabetical is the deterministic
# final tiebreak. Full effective-difficulty / fight-IQ-modulated selection
# is the danger-zone implementation ticket downstream.
# ---------------------------------------------------------------------------
def stage2_select_commit(
    available: set[str],
    connection_graph: GroundConnectionGraph,
    techniques: dict[str, NeWazaTechniqueDefinition],
) -> Optional[str]:
    if not available:
        return None
    # Score lower-is-better tuples so a single ascending sort handles
    # all three precedence levels: (-base_difficulty, -margin, tid).
    scored: list[tuple[int, float, str]] = []
    for tid in available:
        defn = techniques.get(tid)
        if defn is None:
            continue
        margin = _connection_quality_margin(
            connection_graph, defn.required_connections,
        )
        scored.append((-int(defn.base_difficulty), -float(margin), tid))
    if not scored:
        return None
    scored.sort()
    return scored[0][2]


# ---------------------------------------------------------------------------
# SUBMISSION RESOLUTION — minimal tap-check loop per ticket §6.
# Per-tick uke submission-defense roll; tap on failed defense; a
# configurable threshold of failed tori-effectiveness rolls → release +
# Matte. Full tap-resistance-curve machinery is deferred.
# ---------------------------------------------------------------------------
@dataclass
class SubmissionAttempt:
    technique_id: str
    aggressor_id: str
    defender_id: str
    failed_effectiveness_ticks: int = 0
    ticks_elapsed: int = 0


def submission_tick(
    attempt: SubmissionAttempt,
    tori: "Judoka",
    uke: "Judoka",
    rng: "_random_mod.Random",
) -> str:
    """One tick of submission resolution. Returns one of:
      - "tap"      — uke tapped this tick; match ends by submission
      - "release"  — tori has missed for SUBMISSION_RELEASE_FAILED_TICKS
                     consecutive ticks; abandon and Matte
      - "continue" — neither resolution fired; attempt advances

    Defense / effectiveness rolls read off ne_waza_skill scaled to a
    0-100 band. Both rolls are independent — uke can defend cleanly even
    while tori's effectiveness is high; the attempt only releases when
    tori's effectiveness fails repeatedly.
    """
    attempt.ticks_elapsed += 1

    uke_defense = max(0, min(100, int(uke.capability.ne_waza_skill) * 10))
    if rng.random() * 100.0 >= uke_defense:
        # Defense failed → tap.
        return "tap"

    tori_effectiveness = max(0, min(100, int(tori.capability.ne_waza_skill) * 10))
    if rng.random() * 100.0 >= tori_effectiveness:
        attempt.failed_effectiveness_ticks += 1
        if attempt.failed_effectiveness_ticks >= SUBMISSION_RELEASE_FAILED_TICKS:
            return "release"
    else:
        # Successful effectiveness roll resets the streak — tori is
        # making progress this tick.
        attempt.failed_effectiveness_ticks = 0

    return "continue"


# ---------------------------------------------------------------------------
# CONVENIENCE — pin retention check
# ---------------------------------------------------------------------------
def pin_still_satisfied(
    connection_graph: GroundConnectionGraph,
    technique_definition: NeWazaTechniqueDefinition,
) -> bool:
    """True when the technique's required_connections still satisfy the
    stay threshold. Used by the OsaekomiClock teardown path: when this
    goes False, the pin is broken.

    v0.1 uses STAY_THRESHOLD = ENTRY_THRESHOLD = 0.5. The hysteresis
    follow-up lowers STAY_THRESHOLD to 0.4 so a pin held lightly enough
    to slip below 50% but still grippy enough to keep tori on top doesn't
    drop instantly. This is the documented one-line change.
    """
    if technique_definition.score_mechanism is not ScoreMechanism.PIN_TIME_ACCUMULATION:
        return False
    return _connections_satisfied(
        connection_graph,
        technique_definition.required_connections,
        STAY_THRESHOLD,
    )
