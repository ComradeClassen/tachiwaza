# actions.py
# Physics-substrate Part 3.2: the action space.
#
# A judoka's tick-action is a list of up to two Actions (plus an optional
# compound COMMIT_THROW that supersedes the two-action cap). Each Action
# is a discriminated union keyed by `kind`; unused fields stay None.
#
# Part 3 tick update consumes these in four buckets (matching spec 3.2):
#   - GRIP actions     : REACH / DEEPEN / STRIP / STRIP_TWO_ON_ONE / DEFEND_GRIP /
#                        REPOSITION_GRIP / RELEASE
#   - FORCE actions    : PULL / PUSH / LIFT / COUPLE / HOLD_CONNECTIVE / FEINT
#   - BODY actions     : STEP / PIVOT / DROP_COM / RAISE_COM / SWEEP_LEG /
#                        BLOCK_LEG / LOAD_HIP / ABSORB
#   - COMPOUND actions : COMMIT_THROW
#
# v0.1 implements the kinds we need to keep matches running end-to-end
# (REACH, DEEPEN, STRIP, RELEASE, PULL, PUSH, HOLD_CONNECTIVE, STEP, COMMIT_THROW).
# The remaining kinds are defined so that Parts 4–5 (worked throws) can add
# them without introducing new enum values mid-stream.

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Tuple, TYPE_CHECKING

from enums import GripTypeV2, GripTarget
from throws import ThrowID

if TYPE_CHECKING:
    from grip_graph import GripEdge


# ---------------------------------------------------------------------------
# ACTION KIND (Part 3.2)
# ---------------------------------------------------------------------------
class ActionKind(Enum):
    # Grip actions
    REACH            = auto()
    DEEPEN           = auto()
    STRIP            = auto()
    STRIP_TWO_ON_ONE = auto()
    DEFEND_GRIP      = auto()
    REPOSITION_GRIP  = auto()
    RELEASE          = auto()
    # Force actions
    PULL             = auto()
    PUSH             = auto()
    LIFT             = auto()
    COUPLE           = auto()
    HOLD_CONNECTIVE  = auto()
    FEINT            = auto()
    # Body actions
    STEP             = auto()
    PIVOT            = auto()
    DROP_COM         = auto()
    RAISE_COM        = auto()
    SWEEP_LEG        = auto()
    BLOCK_LEG        = auto()
    LOAD_HIP         = auto()
    ABSORB           = auto()
    # Compound
    COMMIT_THROW     = auto()


# Kind-bucket helpers — used by the tick update to split a judoka's chosen
# actions into the four processing buckets.
GRIP_KINDS: frozenset[ActionKind] = frozenset({
    ActionKind.REACH, ActionKind.DEEPEN, ActionKind.STRIP,
    ActionKind.STRIP_TWO_ON_ONE, ActionKind.DEFEND_GRIP,
    ActionKind.REPOSITION_GRIP, ActionKind.RELEASE,
})
FORCE_KINDS: frozenset[ActionKind] = frozenset({
    ActionKind.PULL, ActionKind.PUSH, ActionKind.LIFT, ActionKind.COUPLE,
    ActionKind.HOLD_CONNECTIVE, ActionKind.FEINT,
})
BODY_KINDS: frozenset[ActionKind] = frozenset({
    ActionKind.STEP, ActionKind.PIVOT, ActionKind.DROP_COM,
    ActionKind.RAISE_COM, ActionKind.SWEEP_LEG, ActionKind.BLOCK_LEG,
    ActionKind.LOAD_HIP, ActionKind.ABSORB,
})
DRIVING_FORCE_KINDS: frozenset[ActionKind] = frozenset({
    ActionKind.PULL, ActionKind.PUSH, ActionKind.LIFT,
    ActionKind.COUPLE, ActionKind.FEINT,
})


# ---------------------------------------------------------------------------
# ACTION
# Flat discriminated union. Most fields are optional; which ones are valid
# depends on `kind`. The alternative (separate subclasses per kind) adds a
# lot of boilerplate for no tick-loop benefit.
# ---------------------------------------------------------------------------
@dataclass
class Action:
    kind: ActionKind
    hand: Optional[str] = None                           # "right_hand" / "left_hand"
    foot: Optional[str] = None                           # "right_foot" / "left_foot"
    direction: Optional[Tuple[float, float]] = None      # 2D unit vector (x, y)
    magnitude: float = 0.0                               # Newtons for force actions, meters for steps
    throw_id: Optional[ThrowID] = None                   # for COMMIT_THROW
    grip_type: Optional[GripTypeV2] = None               # for REACH
    target_location: Optional[GripTarget] = None         # for REACH / REPOSITION_GRIP
    edge: Optional["GripEdge"] = None                    # for DEEPEN / STRIP / DEFEND_GRIP / RELEASE
    is_feint: bool = False                               # FEINT marker (3.6)


# ---------------------------------------------------------------------------
# CONVENIENCE CONSTRUCTORS
# ---------------------------------------------------------------------------
def reach(hand: str, grip_type: GripTypeV2, target: GripTarget) -> Action:
    return Action(kind=ActionKind.REACH, hand=hand,
                  grip_type=grip_type, target_location=target)

def deepen(edge: "GripEdge") -> Action:
    return Action(kind=ActionKind.DEEPEN, edge=edge,
                  hand=edge.grasper_part.value)

def strip(hand: str, opponent_edge: "GripEdge") -> Action:
    return Action(kind=ActionKind.STRIP, hand=hand, edge=opponent_edge)

def release(edge: "GripEdge") -> Action:
    return Action(kind=ActionKind.RELEASE, edge=edge,
                  hand=edge.grasper_part.value)

def pull(hand: str, direction: Tuple[float, float], magnitude: float) -> Action:
    return Action(kind=ActionKind.PULL, hand=hand,
                  direction=direction, magnitude=magnitude)

def push(hand: str, direction: Tuple[float, float], magnitude: float) -> Action:
    return Action(kind=ActionKind.PUSH, hand=hand,
                  direction=direction, magnitude=magnitude)

def hold_connective(hand: str) -> Action:
    return Action(kind=ActionKind.HOLD_CONNECTIVE, hand=hand)

def feint(hand: str, direction: Tuple[float, float], magnitude: float) -> Action:
    return Action(kind=ActionKind.FEINT, hand=hand,
                  direction=direction, magnitude=magnitude, is_feint=True)

def step(foot: str, direction: Tuple[float, float], magnitude: float) -> Action:
    return Action(kind=ActionKind.STEP, foot=foot,
                  direction=direction, magnitude=magnitude)

def commit_throw(throw_id: ThrowID) -> Action:
    return Action(kind=ActionKind.COMMIT_THROW, throw_id=throw_id)
