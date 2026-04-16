# position_machine.py
# The position state machine. Owns the rules for which Position transitions are
# legal, what triggers them, and whether a throw attempt is currently possible.
#
# Position is a match-level state — both fighters share it. The machine is called
# per-tick from match.py's _advance_sub_loop() to gate transitions and throw attempts.

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from enums import Position, SubLoopState

if TYPE_CHECKING:
    from grip_graph import GripGraph, Event
    from throws import ThrowDef
    from judoka import Judoka


class PositionMachine:
    """Static collection of transition rules and gating queries.

    No state is stored here — the machine reads from the GripGraph and the
    fighters' current state, and returns decisions. All state lives in Match.
    """

    # -----------------------------------------------------------------------
    # LEGAL TRANSITION TABLE
    # Maps (from_position) → set of positions that can be transitioned to.
    # Only direct, single-step transitions are listed.
    # -----------------------------------------------------------------------
    _LEGAL_TRANSITIONS: dict[Position, set[Position]] = {
        Position.STANDING_DISTANT: {
            Position.GRIPPING,
        },
        Position.GRIPPING: {
            Position.ENGAGED,
            Position.STANDING_DISTANT,   # stifled reset
            Position.SCRAMBLE,           # sudden scramble (rare)
        },
        Position.ENGAGED: {
            Position.THROW_COMMITTED,
            Position.GRIPPING,           # fell back from engagement
            Position.SCRAMBLE,
            Position.STANDING_DISTANT,
        },
        Position.THROW_COMMITTED: {
            Position.SCRAMBLE,           # throw stuffed
            Position.STANDING_DISTANT,   # clean resolution with Matte
            Position.SIDE_CONTROL,       # successful throw → immediate pin
            Position.GUARD_TOP,          # successful throw → guard
            Position.DOWN,               # uke hit the mat
        },
        Position.SCRAMBLE: {
            Position.SIDE_CONTROL,
            Position.GUARD_TOP,
            Position.GUARD_BOTTOM,
            Position.TURTLE_TOP,
            Position.TURTLE_BOTTOM,
            Position.STANDING_DISTANT,   # both fighters recover standing
            Position.GRIPPING,
        },
        Position.TURTLE_TOP: {
            Position.BACK_CONTROL,
            Position.SIDE_CONTROL,
            Position.STANDING_DISTANT,   # escape
        },
        Position.TURTLE_BOTTOM: {
            Position.STANDING_DISTANT,   # escape
            Position.GUARD_BOTTOM,       # turtle → guard roll
        },
        Position.GUARD_TOP: {
            Position.SIDE_CONTROL,       # pass the guard
            Position.STANDING_DISTANT,   # both stand
            Position.MOUNT,              # guard pass → mount
        },
        Position.GUARD_BOTTOM: {
            Position.STANDING_DISTANT,   # escape
            Position.BACK_CONTROL,       # sweep to back
        },
        Position.SIDE_CONTROL: {
            Position.MOUNT,
            Position.BACK_CONTROL,
            Position.GUARD_BOTTOM,       # bottom fighter recovers guard
            Position.STANDING_DISTANT,   # escape
        },
        Position.MOUNT: {
            Position.BACK_CONTROL,
            Position.GUARD_BOTTOM,       # uke bucks out
            Position.STANDING_DISTANT,
        },
        Position.BACK_CONTROL: {
            Position.STANDING_DISTANT,   # escape
            Position.SIDE_CONTROL,       # uke turns in
        },
        Position.DOWN: {
            Position.SIDE_CONTROL,
            Position.GUARD_BOTTOM,
            Position.STANDING_DISTANT,
        },
    }

    @staticmethod
    def can_transition(from_pos: Position, to_pos: Position) -> bool:
        """Check whether a position transition is legal."""
        return to_pos in PositionMachine._LEGAL_TRANSITIONS.get(from_pos, set())

    @staticmethod
    def can_attempt_throw(
        current_pos: Position,
        graph: "GripGraph",
        throw_def: "ThrowDef",
        attacker: "Judoka",
    ) -> bool:
        """Return True if the attacker can attempt this throw right now.

        Requires:
          1. Position is GRIPPING or ENGAGED (not distant, not scramble, not ne-waza)
          2. The grip graph satisfies the throw's EdgeRequirements
        """
        if current_pos not in (Position.GRIPPING, Position.ENGAGED):
            return False
        return graph.satisfies(
            throw_def.requires,
            attacker.identity.name,
            attacker.identity.dominant_side,
        )

    @staticmethod
    def can_force_attempt(
        current_pos: Position,
        graph: "GripGraph",
        throw_def: "ThrowDef",
        attacker: "Judoka",
    ) -> bool:
        """A forced throw attempt — prerequisites NOT satisfied.

        Legal from GRIPPING if the attacker has at least one live edge.
        Carries a 0.15 effectiveness multiplier (from grip-sub-loop.md).
        This is the desperate attempt that earns shido for false attack.
        """
        if current_pos not in (Position.GRIPPING, Position.ENGAGED):
            return False
        return bool(graph.edges_owned_by(attacker.identity.name))

    @staticmethod
    def determine_transition(
        current_pos: Position,
        sub_loop_state: SubLoopState,
        graph: "GripGraph",
        fighter_a: "Judoka",
        fighter_b: "Judoka",
        tick_events: list["Event"],
    ) -> Optional[Position]:
        """Determine if the position should change based on current match state.

        Called once per tick from match.py. Returns the new position if a
        transition should happen, or None to stay in the current position.

        This is a heuristic — the sub-loop state machine in match.py is the
        real driver; this function handles implicit transitions the sub-loop
        doesn't explicitly trigger.
        """
        # If edges were just established, transition from DISTANT → GRIPPING
        if (current_pos == Position.STANDING_DISTANT
                and sub_loop_state == SubLoopState.TUG_OF_WAR
                and graph.edge_count() > 0):
            return Position.GRIPPING

        # If sub-loop is in KUZUSHI_WINDOW, fighters are ENGAGED
        if (current_pos == Position.GRIPPING
                and sub_loop_state == SubLoopState.KUZUSHI_WINDOW):
            return Position.ENGAGED

        # If stifled reset, fighters step back to STANDING_DISTANT
        if (sub_loop_state == SubLoopState.STIFLED_RESET
                and current_pos not in (Position.STANDING_DISTANT, Position.SCRAMBLE)):
            return Position.STANDING_DISTANT

        # If ne-waza sub-loop active but position hasn't reflected it yet
        if (sub_loop_state == SubLoopState.NE_WAZA
                and current_pos in (Position.SCRAMBLE, Position.DOWN, Position.THROW_COMMITTED)):
            return Position.SIDE_CONTROL  # default landing position

        return None

    @staticmethod
    def ne_waza_start_position(
        was_stuffed: bool,
        aggressor: "Judoka",
        defender: "Judoka",
    ) -> Position:
        """Determine the starting ne-waza position after a stuffed throw.

        The aggressor committed and was stopped. Their momentum and the
        defender's response determine who ends up on top.

        aggressor = the fighter who threw and was stuffed
        defender  = the fighter who blocked and may scramble to top
        """
        import random
        # Aggressor stuffed → usually ends up on bottom (they overcommitted)
        # But their ne_waza_skill and composure affect this
        aggressor_skill = aggressor.capability.ne_waza_skill
        defender_skill  = defender.capability.ne_waza_skill

        # Defender has positional advantage (they absorbed the throw attempt)
        defender_top_prob = 0.55 + (defender_skill - aggressor_skill) * 0.04
        defender_top_prob = max(0.2, min(0.85, defender_top_prob))

        if random.random() < defender_top_prob:
            return Position.SIDE_CONTROL   # defender on top
        else:
            return Position.GUARD_TOP      # aggressor scrambles to top
