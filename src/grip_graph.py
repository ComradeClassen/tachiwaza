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
# ---------------------------------------------------------------------------
@dataclass
class GripEdge:
    grasper_id: str            # fighter name who owns this grip
    grasper_part: BodyPart     # which body part is gripping (RIGHT_HAND etc.)
    target_id: str             # fighter name being gripped
    target_location: GripTarget  # where on their gi/body
    grip_type: GripType        # how the grip is established
    depth: float               # 0.0 = shallow/wrist, 1.0 = deep/dominant
    strength: float            # current grip force (decays with fatigue)
    established_tick: int      # when this edge was created
    contested: bool = False    # opponent actively fighting this grip


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
    # ENGAGEMENT
    # Called when two fighters close from STANDING_DISTANT.
    # Creates the initial grip configuration: each fighter reaches for their
    # preferred targets. Returns the newly created edges.
    # -----------------------------------------------------------------------
    def attempt_engagement(
        self,
        fighter_a: "Judoka",
        fighter_b: "Judoka",
        current_tick: int,
    ) -> list[GripEdge]:
        """Create initial grip edges when fighters enter GRIPPING range.

        Ring 1: neutral default grip selection (collar + sleeve).
        Ring 2+ cultural layer will bias which grip types each fighter reaches for.

        Depth is probabilistic based on relative hand strength and reach advantage.
        """
        new_edges: list[GripEdge] = []

        for attacker, defender in [(fighter_a, fighter_b), (fighter_b, fighter_a)]:
            dom = attacker.identity.dominant_side
            is_right = dom == DominantSide.RIGHT

            # How quickly this fighter closes — affected by arm reach and hand strength
            reach_a = attacker.identity.arm_reach_cm
            reach_d = defender.identity.arm_reach_cm
            reach_factor = min(1.4, max(0.7, reach_a / max(reach_d, 1)))

            # Dominant hand → opposite lapel (collar grip)
            dom_hand_key  = "right_hand"   if is_right else "left_hand"
            lapel_target  = GripTarget.LEFT_LAPEL  if is_right else GripTarget.RIGHT_LAPEL
            dom_hand_eff  = attacker.effective_body_part(dom_hand_key)
            dom_depth     = min(0.9, random.uniform(0.3, 0.7) * (dom_hand_eff / 7.0) * reach_factor)
            dom_strength  = min(1.0, (dom_hand_eff / 10.0) * random.uniform(0.7, 1.0))

            # Depth determines grip type: above 0.6 → DEEP; above 0.35 → STANDARD; else POCKET
            if dom_depth >= 0.6:
                grip_type = GripType.DEEP
            elif dom_depth >= 0.35:
                grip_type = GripType.STANDARD
            else:
                grip_type = GripType.POCKET

            # Only create the edge if grip strength is meaningful
            if dom_strength > 0.15:
                dom_hand_part = BodyPart.RIGHT_HAND if is_right else BodyPart.LEFT_HAND
                edge = GripEdge(
                    grasper_id=attacker.identity.name,
                    grasper_part=dom_hand_part,
                    target_id=defender.identity.name,
                    target_location=lapel_target,
                    grip_type=grip_type,
                    depth=dom_depth,
                    strength=dom_strength,
                    established_tick=current_tick,
                )
                self.add_edge(edge)
                new_edges.append(edge)

            # Non-dominant hand → dominant sleeve (sleeve grip)
            non_hand_key   = "left_hand"   if is_right else "right_hand"
            sleeve_target  = GripTarget.RIGHT_SLEEVE if is_right else GripTarget.LEFT_SLEEVE
            non_hand_eff   = attacker.effective_body_part(non_hand_key)
            non_depth      = min(0.8, random.uniform(0.2, 0.6) * (non_hand_eff / 7.0))
            non_strength   = min(1.0, (non_hand_eff / 10.0) * random.uniform(0.6, 1.0))
            non_grip_type  = GripType.STANDARD if non_depth >= 0.3 else GripType.POCKET

            if non_strength > 0.15:
                non_hand_part = BodyPart.LEFT_HAND if is_right else BodyPart.RIGHT_HAND
                edge2 = GripEdge(
                    grasper_id=attacker.identity.name,
                    grasper_part=non_hand_part,
                    target_id=defender.identity.name,
                    target_location=sleeve_target,
                    grip_type=non_grip_type,
                    depth=non_depth,
                    strength=non_strength,
                    established_tick=current_tick,
                )
                self.add_edge(edge2)
                new_edges.append(edge2)

        return new_edges

    # -----------------------------------------------------------------------
    # PER-TICK MAINTENANCE
    # Called every tick: ages edges, accumulates fatigue, rolls 3-tier outcomes.
    # Returns events for anything worth logging.
    # -----------------------------------------------------------------------
    def tick_update(
        self,
        current_tick: int,
        fighter_a: "Judoka",
        fighter_b: "Judoka",
    ) -> list[Event]:
        """Update all edges for one tick. Returns loggable events."""
        events: list[Event] = []
        edges_to_remove: list[GripEdge] = []

        fighters: dict[str, "Judoka"] = {
            fighter_a.identity.name: fighter_a,
            fighter_b.identity.name: fighter_b,
        }

        for edge in list(self.edges):
            grasper = fighters.get(edge.grasper_id)
            if grasper is None:
                continue

            grasper_part_key = edge.grasper_part.value
            # Skip symbolic aliases (shouldn't be in live edges, but be safe)
            if grasper_part_key.startswith("__"):
                continue

            grasper_fatigue = grasper.state.body.get(
                grasper_part_key, None
            )
            if grasper_fatigue is None:
                continue

            current_fatigue = grasper_fatigue.fatigue

            # --- Force-break check ---
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

            # --- Fatigue accumulation on this tick ---
            drain_rate = (
                self.EDGE_FATIGUE_PER_TICK
                * edge.grip_type.fatigue_rate()
                * (self.CONTESTED_DRAIN_MULT if edge.contested else 1.0)
            )
            grasper_fatigue.fatigue = min(1.0, grasper_fatigue.fatigue + drain_rate)

            # --- 3-tier resolution roll ---
            # Success probability: edge strength scaled by grasper freshness
            effectiveness = edge.strength * (1.0 - current_fatigue)
            contest_penalty = 0.6 if edge.contested else 1.0
            success_prob = effectiveness * contest_penalty

            roll = random.random()
            if roll < 0.08 * (1.0 - success_prob + 0.1):
                # FAILURE — edge breaks
                edges_to_remove.append(edge)
                events.append(Event(
                    tick=current_tick,
                    event_type="GRIP_BREAK",
                    description=(
                        f"[grip] {edge.grasper_id} loses {edge.target_location.value} grip "
                        f"on {edge.target_id} — stripped."
                    ),
                ))
            elif roll < 0.25 * (1.0 - success_prob + 0.1):
                # PARTIAL — grip slips, depth and strength degrade
                old_depth = edge.depth
                edge.depth    = max(0.05, edge.depth    - self.DEPTH_DECAY_ON_PARTIAL)
                edge.strength = max(0.05, edge.strength - self.STRENGTH_DECAY_ON_PARTIAL)
                # Downgrade grip type if depth dropped below threshold
                if old_depth >= 0.6 and edge.depth < 0.6 and edge.grip_type == GripType.DEEP:
                    edge.grip_type = GripType.STANDARD
                    events.append(Event(
                        tick=current_tick,
                        event_type="GRIP_DEGRADE",
                        description=(
                            f"[grip] {edge.grasper_id} {grasper_part_key}: "
                            f"deep collar slips → standard (depth {edge.depth:.2f})."
                        ),
                    ))
            # else: SUCCESS — edge holds, no change needed

        # Remove broken edges
        for edge in edges_to_remove:
            self.remove_edge(edge)

        return events

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
                    description=f"[grip] Position reset — {len(broken)} edges broken.",
                ))

        # On transition to ne-waza: clear contested flag (new phase)
        elif new_pos in (Position.SIDE_CONTROL, Position.MOUNT, Position.BACK_CONTROL,
                         Position.GUARD_TOP, Position.GUARD_BOTTOM,
                         Position.TURTLE_TOP, Position.TURTLE_BOTTOM):
            for edge in self.edges:
                edge.contested = False

        return events
