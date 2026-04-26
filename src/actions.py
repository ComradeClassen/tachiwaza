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
#                        BLOCK_LEG / LOAD_HIP / ABSORB / BLOCK_HIP
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
    from commit_motivation import CommitMotivation


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
    BLOCK_HIP        = auto()        # HAJ-57 — uke's defensive hip drive (denies hip-loading throws)
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
    ActionKind.LOAD_HIP, ActionKind.ABSORB, ActionKind.BLOCK_HIP,
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
    # HAJ-35/36 — desperation + gate-bypass metadata for COMMIT_THROW. Lets
    # Match surface "(desperation)" / "(gate bypassed: X)" on the commit
    # line without reconsulting the ladder.
    offensive_desperation: bool = False
    defensive_desperation: bool = False
    gate_bypass_reason: Optional[str] = None             # non-None only when the gate was bypassed
    gate_bypass_kind: Optional[str] = None               # "offensive" | "defensive" | None
    # HAJ-67 — non-scoring commit motivation (CLOCK_RESET, GRIP_ESCAPE,
    # SHIDO_FARMING, STAMINA_DESPERATION). None for normal and desperation
    # commits. See src/commit_motivation.py. Replaces the HAJ-49
    # `intentional_false_attack: bool` (the legacy flag collapses to
    # `commit_motivation == CommitMotivation.CLOCK_RESET`).
    commit_motivation: Optional["CommitMotivation"] = None

    @property
    def intentional_false_attack(self) -> bool:
        """HAJ-49 compatibility shim — any non-scoring motivation counts
        as an intentional false attack from the physics/failure-routing
        perspective. The specific motivation is on `commit_motivation`."""
        return self.commit_motivation is not None


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


def block_hip() -> Action:
    """HAJ-57 — uke's defensive hip-drive-forward block.

    Denies tori the geometry of any in-progress hip-loading throw (a throw
    whose body_part_requirement.hip_loading is True). Resolved Match-side
    against tori's mid-flight attempt; the throw fails into a stance reset
    and the dyad falls back to grip battle. Posture-gated at action-
    selection time: a bent-over uke (trunk_sagittal > 0) cannot generate
    the forward hip drive."""
    return Action(kind=ActionKind.BLOCK_HIP)

def commit_throw(
    throw_id: ThrowID,
    *,
    offensive_desperation: bool = False,
    defensive_desperation: bool = False,
    gate_bypass_reason: Optional[str] = None,
    gate_bypass_kind: Optional[str] = None,
    commit_motivation: Optional["CommitMotivation"] = None,
) -> Action:
    return Action(
        kind=ActionKind.COMMIT_THROW, throw_id=throw_id,
        offensive_desperation=offensive_desperation,
        defensive_desperation=defensive_desperation,
        gate_bypass_reason=gate_bypass_reason,
        gate_bypass_kind=gate_bypass_kind,
        commit_motivation=commit_motivation,
    )
