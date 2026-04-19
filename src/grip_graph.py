# grip_graph.py
# The foundational data structure of Phase 2 Session 2.
# Implements the bipartite grip graph from grip-graph.md v0.1.
#
# A judo match is a relational state between two bodies: who is gripping what,
# with which hand, at what depth, with what strength. This module makes that
# state explicit as a list of GripEdge objects.
#
# Every throw, every ne-waza transition, every Matte call traces back to
# transitions on this graph.

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

from enums import (
    BodyPart, GripTarget, GripType, DominantSide,
    GripTypeV2, GripDepth, GripMode, BeltRank,
)

if TYPE_CHECKING:
    from judoka import Judoka
    from throws import EdgeRequirement


# ---------------------------------------------------------------------------
# EVENT
# A typed event produced by any subsystem. The match log is a sequence of
# these; the prose engine (Phase 4) will render them into full sentences.
# ---------------------------------------------------------------------------
@dataclass
class Event:
    tick: int
    event_type: str       # e.g. "GRIP_ESTABLISH", "KUZUSHI_WINDOW_OPENED"
    description: str      # functional log string for Phase 2
    data: dict = field(default_factory=dict)   # extra data for Phase 4 rendering


# ---------------------------------------------------------------------------
# GRIP EDGE
# One active grip connection. Each is owned by one fighter (grasper_id) and
# targets one location on the other fighter (target_id / target_location).
#
# Physics-substrate Part 2 fields: grip_type_v2 (canonical standing grip
# type), depth_level (discrete POCKET/STANDARD/DEEP/SLIPPING), mode
# (CONNECTIVE/DRIVING per tick), unconventional_clock (Part 2.6 passivity).
# The legacy `grip_type: GripType` field is derived from grip_type_v2 +
# depth_level so existing throw prereqs in throws.py keep working until
# Part 4 replaces EdgeRequirement with the four-dimension signature.
# The legacy float `depth` is a property on top of depth_level.
# ---------------------------------------------------------------------------
@dataclass
class GripEdge:
    grasper_id: str                       # fighter name who owns this grip
    grasper_part: BodyPart                # which body part is gripping (RIGHT_HAND etc.)
    target_id: str                        # fighter name being gripped
    target_location: GripTarget           # where on their gi/body
    grip_type_v2: GripTypeV2              # seven canonical standing grip types (Part 2.2)
    depth_level: GripDepth                # discrete seating level (Part 2.4)
    strength: float                       # current grip force (decays with fatigue)
    established_tick: int                 # when this edge was created
    mode: GripMode = GripMode.CONNECTIVE  # per-tick mode (Part 2.5); Part 3 flips it
    unconventional_clock: int = 0         # Part 2.6 per-grip counter for BELT/PISTOL/CROSS
    contested: bool = False               # opponent actively fighting this grip

    @property
    def depth(self) -> float:
        """Legacy float depth; derived from depth_level for back-compat with
        throws.py EdgeRequirement.min_depth checks.
        """
        return self.depth_level.modifier()

    @property
    def grip_type(self) -> GripType:
        """Legacy GripType, derived from grip_type_v2 + depth_level.

        Maps the canonical seven Part-2 types back onto the legacy 13-entry
        enum so existing throw prerequisites (throws.py) keep resolving.
        A DEEP lapel-high or collar reports as GripType.DEEP / HIGH_COLLAR
        to satisfy throws that demand deep collar control.
        """
        if self.depth_level == GripDepth.POCKET or self.depth_level == GripDepth.SLIPPING:
            return GripType.POCKET
        # STANDARD or DEEP:
        v2 = self.grip_type_v2
        if self.depth_level == GripDepth.DEEP:
            if v2 == GripTypeV2.COLLAR or v2 == GripTypeV2.LAPEL_HIGH:
                return GripType.HIGH_COLLAR
            if v2 == GripTypeV2.BELT:
                return GripType.BELT
            if v2 == GripTypeV2.PISTOL:
                return GripType.PISTOL
            if v2 == GripTypeV2.CROSS:
                return GripType.CROSS
            return GripType.DEEP
        # STANDARD:
        if v2 == GripTypeV2.PISTOL:
            return GripType.PISTOL
        if v2 == GripTypeV2.CROSS:
            return GripType.CROSS
        return GripType.STANDARD


# ---------------------------------------------------------------------------
# ALIAS RESOLUTION HELPERS
# Converts symbolic BodyPart and GripTarget aliases to concrete string values
# based on the attacker's dominant side.
# ---------------------------------------------------------------------------

def resolve_body_part_alias(bp: BodyPart, dominant_side: DominantSide) -> list[str]:
    """Return the concrete body-part string key(s) for a BodyPart (including aliases)."""
    if bp == BodyPart.DOMINANT_HAND:
        return ["right_hand"] if dominant_side == DominantSide.RIGHT else ["left_hand"]
    if bp == BodyPart.NON_DOMINANT_HAND:
        return ["left_hand"] if dominant_side == DominantSide.RIGHT else ["right_hand"]
    return [bp.value]


def resolve_target_alias(target: GripTarget, attacker_dominant: DominantSide) -> list[str]:
    """Return the concrete target string(s) for a GripTarget (including aliases).

    Canonical view from a right-dominant attacker:
      OPPOSITE_LAPEL  → LEFT_LAPEL  (the lapel their right hand reaches for)
      DOMINANT_LAPEL  → RIGHT_LAPEL
      DOMINANT_SLEEVE → RIGHT_SLEEVE (the sleeve their left hand pulls)
      OPPOSITE_SLEEVE → LEFT_SLEEVE
    Left-dominant is mirrored.
    """
    if target == GripTarget.ANY:
        return []  # Empty = any target; caller treats as 'satisfied by any edge'

    r_dom = attacker_dominant == DominantSide.RIGHT
    alias_map: dict[GripTarget, str] = {
        GripTarget.OPPOSITE_LAPEL:  "left_lapel"  if r_dom else "right_lapel",
        GripTarget.DOMINANT_LAPEL:  "right_lapel" if r_dom else "left_lapel",
        GripTarget.DOMINANT_SLEEVE: "right_sleeve" if r_dom else "left_sleeve",
        GripTarget.OPPOSITE_SLEEVE: "left_sleeve"  if r_dom else "right_sleeve",
    }
    if target in alias_map:
        return [alias_map[target]]
    return [target.value]


# ---------------------------------------------------------------------------
# GRIP GRAPH
# The live graph. Contains all currently active GripEdge objects for a match.
# Owned by Match, not by either Judoka.
# ---------------------------------------------------------------------------
class GripGraph:

    # Tuning constants — Phase 3 calibration will adjust these
    EDGE_FATIGUE_PER_TICK:       float = 0.002   # per-edge per-tick forearm drain
    CONTESTED_DRAIN_MULT:        float = 2.0     # contested edges drain 2x faster
    FORCE_BREAK_THRESHOLD:       float = 0.85    # grasper fatigue above which edges may break
    FORCE_BREAK_PROB:            float = 0.25    # per-tick probability of involuntary break
    DEPTH_DECAY_ON_PARTIAL:      float = 0.15    # how much depth drops on a PARTIAL outcome
    STRENGTH_DECAY_ON_PARTIAL:   float = 0.10
    ENGAGEMENT_EDGE_MAX:         int   = 2       # edges created per fighter at engagement

    def __init__(self) -> None:
        self.edges: list[GripEdge] = []

    # -----------------------------------------------------------------------
    # EDGE OPERATIONS
    # -----------------------------------------------------------------------
    def add_edge(self, edge: GripEdge) -> None:
        self.edges.append(edge)

    def remove_edge(self, edge: GripEdge) -> None:
        if edge in self.edges:
            self.edges.remove(edge)

    def break_all_edges(self) -> list[GripEdge]:
        """Remove all edges. Returns the broken edges for logging."""
        broken = list(self.edges)
        self.edges.clear()
        return broken

    def edges_owned_by(self, fighter_id: str) -> list[GripEdge]:
        return [e for e in self.edges if e.grasper_id == fighter_id]

    def edges_targeting(self, fighter_id: str) -> list[GripEdge]:
        return [e for e in self.edges if e.target_id == fighter_id]

    def edges_on_target(self, fighter_id: str, location: GripTarget) -> list[GripEdge]:
        return [e for e in self.edges
                if e.target_id == fighter_id and e.target_location == location]

    def edge_count(self) -> int:
        return len(self.edges)

    # -----------------------------------------------------------------------
    # REACH-DURATION TABLE (Part 2.7 + Part 6.1 skill compression)
    # Ticks required for one hand's reach to complete and seat a POCKET grip.
    # Elite compresses to a single tick; novice fumbles for five.
    # -----------------------------------------------------------------------
    REACH_TICKS_BY_BELT: dict[BeltRank, int] = {
        BeltRank.WHITE:   5,
        BeltRank.YELLOW:  4,
        BeltRank.ORANGE:  4,
        BeltRank.GREEN:   3,
        BeltRank.BLUE:    3,
        BeltRank.BROWN:   2,
        BeltRank.BLACK_1: 1,
        BeltRank.BLACK_2: 1,
        BeltRank.BLACK_3: 1,
        BeltRank.BLACK_4: 1,
        BeltRank.BLACK_5: 1,
    }

    def reach_ticks_for(self, judoka: "Judoka") -> int:
        return self.REACH_TICKS_BY_BELT.get(judoka.identity.belt_rank, 3)

    # -----------------------------------------------------------------------
    # ENGAGEMENT (Part 2.7 — grips are not instantaneous)
    # Called when two fighters close from STANDING_DISTANT. Seats each
    # fighter's two hands at POCKET immediately after REACHING completes.
    #
    # Ring-1 grip selection is still the classical sleeve + collar/lapel
    # pair; cultural bias is a Ring-2+ concern.
    # -----------------------------------------------------------------------
    def attempt_engagement(
        self,
        fighter_a: "Judoka",
        fighter_b: "Judoka",
        current_tick: int,
    ) -> list[GripEdge]:
        """Create a fresh POCKET grip for each hand of each fighter.

        The match's sub-loop is expected to have already held both fighters
        in REACHING contact-state for `reach_ticks_for(...)` ticks before
        calling this. From this call onward, grips deepen via
        `deepen_grip(...)` on subsequent ticks.
        """
        new_edges: list[GripEdge] = []

        for attacker, _defender in [(fighter_a, fighter_b), (fighter_b, fighter_a)]:
            dom = attacker.identity.dominant_side
            is_right = dom == DominantSide.RIGHT

            # Dominant hand → opposite lapel. Competitive standard: lapel-high
            # (tsurite — the lifting hand). Deep-collar play is an upgrade via
            # REPOSITION_GRIP (Part 3 action; not wired here).
            dom_hand_part  = BodyPart.RIGHT_HAND if is_right else BodyPart.LEFT_HAND
            dom_hand_key   = "right_hand" if is_right else "left_hand"
            lapel_target   = GripTarget.LEFT_LAPEL if is_right else GripTarget.RIGHT_LAPEL
            dom_strength   = min(1.0, attacker.effective_body_part(dom_hand_key) / 10.0)

            new_edges.append(self._new_pocket_edge(
                attacker=attacker,
                grasper_part=dom_hand_part,
                target_id=fighter_b.identity.name if attacker is fighter_a else fighter_a.identity.name,
                target_location=lapel_target,
                grip_type_v2=GripTypeV2.LAPEL_HIGH,
                strength=dom_strength,
                current_tick=current_tick,
            ))

            # Non-dominant hand → dominant sleeve (hikite — the pulling hand).
            non_hand_part  = BodyPart.LEFT_HAND if is_right else BodyPart.RIGHT_HAND
            non_hand_key   = "left_hand" if is_right else "right_hand"
            sleeve_target  = GripTarget.RIGHT_SLEEVE if is_right else GripTarget.LEFT_SLEEVE
            non_strength   = min(1.0, attacker.effective_body_part(non_hand_key) / 10.0)

            new_edges.append(self._new_pocket_edge(
                attacker=attacker,
                grasper_part=non_hand_part,
                target_id=fighter_b.identity.name if attacker is fighter_a else fighter_a.identity.name,
                target_location=sleeve_target,
                grip_type_v2=GripTypeV2.SLEEVE,
                strength=non_strength,
                current_tick=current_tick,
            ))

        return new_edges

    def _new_pocket_edge(
        self,
        attacker: "Judoka",
        grasper_part: BodyPart,
        target_id: str,
        target_location: GripTarget,
        grip_type_v2: GripTypeV2,
        strength: float,
        current_tick: int,
    ) -> GripEdge:
        """Seat a freshly-established grip at POCKET depth. Hand transitions
        from REACHING → GRIPPING_UKE (handled by the caller via the body-part
        ContactState on the grasper's state.body map).
        """
        edge = GripEdge(
            grasper_id=attacker.identity.name,
            grasper_part=grasper_part,
            target_id=target_id,
            target_location=target_location,
            grip_type_v2=grip_type_v2,
            depth_level=GripDepth.POCKET,
            strength=strength,
            established_tick=current_tick,
        )
        self.add_edge(edge)

        # Update the grasper's hand contact state: REACHING → GRIPPING_UKE.
        # Imported lazily to avoid a circular import with body_state.
        from body_state import ContactState as _ContactState
        grasper_key = grasper_part.value
        if not grasper_key.startswith("__"):
            part_state = attacker.state.body.get(grasper_key)
            if part_state is not None:
                part_state.contact_state = _ContactState.GRIPPING_UKE
        return edge

    # -----------------------------------------------------------------------
    # DEEPEN (Part 2.7 — POCKET → STANDARD → DEEP)
    # Called by Part 3's DEEPEN action. For v0.1 we let match.py advance
    # depth each tick on its own until Part 3 lands the proper action model.
    # -----------------------------------------------------------------------
    def deepen_grip(self, edge: GripEdge, grasper: "Judoka") -> bool:
        """Attempt to deepen a grip by one step. Succeeds if the grasper's
        grip strength exceeds a depth-step threshold.

        Returns True if the step happened.
        """
        from force_envelope import grip_strength as _grip_strength
        required = {
            GripDepth.POCKET:   0.35,
            GripDepth.STANDARD: 0.55,
            GripDepth.DEEP:     1.0,   # terminal — deepen() no-ops
            GripDepth.SLIPPING: 0.25,
        }[edge.depth_level]
        if _grip_strength(grasper) < required:
            return False
        new_depth = edge.depth_level.deepened()
        if new_depth == edge.depth_level:
            return False
        edge.depth_level = new_depth
        return True

    # -----------------------------------------------------------------------
    # MODE SWITCH (Part 2.5)
    # -----------------------------------------------------------------------
    def set_mode(self, edge: GripEdge, mode: GripMode) -> None:
        edge.mode = mode

    # -----------------------------------------------------------------------
    # STRIPPING (Part 2.8 — deterministic chain)
    # -----------------------------------------------------------------------
    def apply_strip_pressure(
        self,
        edge: GripEdge,
        strip_force: float,
        grasper: "Judoka",
    ) -> Optional[Event]:
        """Compete a stripping force against the grip. If pressure exceeds
        the grip's resistance, depth degrades one step along the strip chain
        (DEEP → STANDARD → POCKET → SLIPPING → stripped).

        `strip_force` is in Newtons; Part 3's STRIP action will supply it.
        Until then, match.py does not call this — so grips only degrade via
        force_break (fatigue) and voluntary release.
        """
        from force_envelope import FORCE_ENVELOPES, grip_strength as _grip_strength

        # Resistance is the envelope's strip_resistance scaled by the
        # attacker's current grip strength (same modifier as 2.4 delivered
        # force). A fatigued, uncomposed grip is easier to strip.
        base_resistance = FORCE_ENVELOPES[edge.grip_type_v2].strip_resistance
        resistance = base_resistance * edge.depth_level.modifier() * _grip_strength(grasper)

        if strip_force <= resistance:
            return None

        next_depth = edge.depth_level.degraded()
        if next_depth is None:
            # Past SLIPPING: the grip is stripped.
            self.remove_edge(edge)
            from body_state import ContactState as _ContactState
            key = edge.grasper_part.value
            if not key.startswith("__"):
                ps = grasper.state.body.get(key)
                if ps is not None:
                    ps.contact_state = _ContactState.FREE
            return Event(
                tick=-1,
                event_type="GRIP_STRIPPED",
                description=(
                    f"[grip] {edge.grasper_id} loses {edge.target_location.value} grip "
                    f"on {edge.target_id} — stripped."
                ),
            )
        edge.depth_level = next_depth
        return Event(
            tick=-1,
            event_type="GRIP_DEGRADE",
            description=(
                f"[grip] {edge.grasper_id} {edge.grasper_part.value} "
                f"{edge.grip_type_v2.name} → {next_depth.name}."
            ),
        )

    # -----------------------------------------------------------------------
    # PER-TICK MAINTENANCE (Part 2.4 / 2.5 / 2.6 / 2.8)
    # Ages edges, applies mode-based fatigue to the grasping hand, and ticks
    # the per-grip unconventional-grip clock. Force-break-on-exhausted-hand
    # is kept (it's physics). Stripping is deterministic and driven by
    # apply_strip_pressure(); the old random FAILURE roll is gone —
    # stochastic edge-loss is no longer how this model works.
    # -----------------------------------------------------------------------
    def tick_update(
        self,
        current_tick: int,
        fighter_a: "Judoka",
        fighter_b: "Judoka",
    ) -> list[Event]:
        events: list[Event] = []
        edges_to_remove: list[GripEdge] = []

        fighters: dict[str, "Judoka"] = {
            fighter_a.identity.name: fighter_a,
            fighter_b.identity.name: fighter_b,
        }

        from force_envelope import MODE_FATIGUE_MULTIPLIER

        for edge in list(self.edges):
            grasper = fighters.get(edge.grasper_id)
            if grasper is None:
                continue

            grasper_part_key = edge.grasper_part.value
            if grasper_part_key.startswith("__"):
                continue

            part_state = grasper.state.body.get(grasper_part_key)
            if part_state is None:
                continue
            current_fatigue = part_state.fatigue

            # --- Force-break (hand cooked) — keeps matches from hanging on
            # totally exhausted grips. Not in Part 2 text but physically
            # correct: an exhausted forearm can't hold anything.
            if current_fatigue >= self.FORCE_BREAK_THRESHOLD:
                if random.random() < self.FORCE_BREAK_PROB:
                    edges_to_remove.append(edge)
                    events.append(Event(
                        tick=current_tick,
                        event_type="GRIP_BREAK",
                        description=(
                            f"[grip] {edge.grasper_id} {grasper_part_key} grip "
                            f"breaks — forearm cooked ({current_fatigue:.2f} fatigue)."
                        ),
                    ))
                    continue

            # --- Fatigue accumulation (Part 2.5): connective grips are cheap,
            # driving grips eat the hand fast.
            mode_mult = MODE_FATIGUE_MULTIPLIER[edge.mode]
            drain_rate = (
                self.EDGE_FATIGUE_PER_TICK
                * mode_mult
                * (self.CONTESTED_DRAIN_MULT if edge.contested else 1.0)
            )
            part_state.fatigue = min(1.0, part_state.fatigue + drain_rate)

            # --- Unconventional-grip clock (Part 2.6): BELT/PISTOL/CROSS
            # must lead to an immediate attack; ticks increment until an
            # attack event resets them via register_attack(). Shido is
            # issued from the Match layer when this crosses threshold.
            if edge.grip_type_v2.is_unconventional():
                edge.unconventional_clock += 1

        for edge in edges_to_remove:
            self.remove_edge(edge)

        return events

    # -----------------------------------------------------------------------
    # ATTACK EVENT (Part 2.6) — resets both passivity clocks for the
    # attacker. Called by Part 3 when a DRIVING-mode force exceeds the
    # attack-threshold for ≥ 2 ticks. Until Part 3 wires this up, the
    # legacy commit path in match.py calls register_attack at throw commit.
    # -----------------------------------------------------------------------
    def register_attack(self, attacker_id: str) -> None:
        """Reset the per-grip unconventional clock for every grip owned by
        attacker_id. The per-fighter kumi-kata clock lives on Match (so it
        survives grips coming and going within a single exchange).
        """
        for edge in self.edges_owned_by(attacker_id):
            edge.unconventional_clock = 0

    # -----------------------------------------------------------------------
    # GRIP DELTA
    # Computes the advantage of fighter_a over fighter_b in the current graph.
    # Positive = fighter_a is winning the grip war.
    # -----------------------------------------------------------------------
    def compute_grip_delta(
        self, fighter_a: "Judoka", fighter_b: "Judoka"
    ) -> float:
        """Grip advantage of fighter_a over fighter_b. Used by sub-loop for kuzushi check."""
        a_total = sum(
            e.depth * e.strength * e.grip_type.dominance_factor()
            for e in self.edges_owned_by(fighter_a.identity.name)
        )
        b_total = sum(
            e.depth * e.strength * e.grip_type.dominance_factor()
            for e in self.edges_owned_by(fighter_b.identity.name)
        )
        return a_total - b_total

    # -----------------------------------------------------------------------
    # SATISFIES — THROW PREREQUISITE CHECK
    # -----------------------------------------------------------------------
    def satisfies(
        self,
        requirements: list["EdgeRequirement"],
        attacker_id: str,
        attacker_dominant: DominantSide,
    ) -> bool:
        """Check whether the current graph satisfies all requirements for a throw.

        For each EdgeRequirement:
          - Find edges owned by the attacker
          - Resolve any symbolic aliases (DOMINANT_HAND etc.)
          - Check grasper part, target location, grip type, depth, strength
          - ALL requirements must be satisfied simultaneously (AND logic)
        """
        attacker_edges = self.edges_owned_by(attacker_id)
        if not attacker_edges:
            return False

        for req in requirements:
            if not self._requirement_met(req, attacker_edges, attacker_dominant):
                return False
        return True

    def _requirement_met(
        self,
        req: "EdgeRequirement",
        attacker_edges: list[GripEdge],
        dominant: DominantSide,
    ) -> bool:
        """Check one EdgeRequirement against the attacker's current edges."""
        # Resolve grasper part alias to concrete key(s)
        required_parts = resolve_body_part_alias(req.grasper_part, dominant)

        # Resolve target alias to concrete string(s)
        required_targets = resolve_target_alias(req.target_location, dominant)
        # Empty required_targets means ANY — satisfied by any target

        for edge in attacker_edges:
            part_key = edge.grasper_part.value
            if part_key.startswith("__"):
                continue  # skip symbolic alias edges (shouldn't exist)

            # Part match
            if part_key not in required_parts:
                continue

            # Target match (empty = any)
            if required_targets:
                edge_target_str = edge.target_location.value
                if edge_target_str not in required_targets:
                    continue

            # Grip type match (empty list = any type)
            if req.grip_type_in and edge.grip_type not in req.grip_type_in:
                continue

            # Depth and strength thresholds
            if edge.depth < req.min_depth:
                continue
            if edge.strength < req.min_strength:
                continue

            return True  # This edge satisfies the requirement

        return False

    # -----------------------------------------------------------------------
    # POSITION TRANSITION — edge transformation on position change
    # -----------------------------------------------------------------------
    def transform_for_position(
        self, old_pos, new_pos, current_tick: int
    ) -> list[Event]:
        """Transform or contest edges when position changes.

        Design rule from grip-graph.md: edges do NOT automatically reset.
        Edges surviving a stuffed throw into ne-waza carry their depth and
        strength into the ground exchange.
        """
        events: list[Event] = []

        from enums import Position
        # On scramble: mark all edges as contested
        if new_pos == Position.SCRAMBLE:
            for edge in self.edges:
                edge.contested = True

        # On escape to standing: break all edges (both fighters reset)
        elif new_pos == Position.STANDING_DISTANT:
            broken = self.break_all_edges()
            if broken:
                events.append(Event(
                    tick=current_tick,
                    event_type="GRIPS_RESET",
                    description="[grip] Position reset.",
                ))

        # On transition to ne-waza: clear contested flag (new phase)
        elif new_pos in (Position.SIDE_CONTROL, Position.MOUNT, Position.BACK_CONTROL,
                         Position.GUARD_TOP, Position.GUARD_BOTTOM,
                         Position.TURTLE_TOP, Position.TURTLE_BOTTOM):
            for edge in self.edges:
                edge.contested = False

        return events
