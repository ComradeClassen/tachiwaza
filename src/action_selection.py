# action_selection.py
# Physics-substrate Part 3.3: the v0.1 priority ladder.
#
# A deliberately-simple hardcoded decision function. Later rings (Ring 2
# coach instructions, Ring 3 cultural bias, Ring 4 opponent memory) layer
# on top by rewriting or filtering the ladder's output.
#
# The ladder produces up to two Actions per tick, or a single COMMIT_THROW
# compound action that supersedes the two-action cap.

from __future__ import annotations
import random
from typing import Optional, TYPE_CHECKING

from actions import (
    Action, ActionKind,
    reach, deepen, strip, release, pull, push, hold_connective, step, commit_throw,
)
from enums import (
    GripTypeV2, GripDepth, GripTarget, GripMode, DominantSide,
)
from throws import THROW_DEFS, ThrowID

if TYPE_CHECKING:
    from judoka import Judoka
    from grip_graph import GripGraph, GripEdge


# Tuning constants (calibration stubs).
COMMIT_THRESHOLD:             float = 0.65  # perceived signature must clear this to commit
DESPERATION_KUMI_CLOCK:       int   = 22    # tick count that triggers ladder rung 5
HIGH_FATIGUE_THRESHOLD:       float = 0.65  # hand-fatigue at which rung 6 prefers connective
DRIVE_MAGNITUDE_N:            float = 400.0 # PULL/PUSH force a non-desperation drive issues
PROBE_MAGNITUDE_N:            float = 120.0 # default-rung probing force
# Side-effect: match feeds us the grasper's kumi-kata clock; it's not
# visible on the Judoka itself because it belongs to the Match.


# ---------------------------------------------------------------------------
# TOP-LEVEL ENTRY POINT
# ---------------------------------------------------------------------------
def select_actions(
    judoka: "Judoka",
    opponent: "Judoka",
    graph: "GripGraph",
    kumi_kata_clock: int,
    rng: random.Random | None = None,
) -> list[Action]:
    """Return the judoka's chosen actions for this tick.

    Implements the Part 3.3 priority ladder. Returns 1-2 Actions, or a
    single-element list containing COMMIT_THROW.
    """
    r = rng if rng is not None else random

    # Rung 1: stunned → defensive-only (v0.1: just idle).
    if judoka.state.stun_ticks > 0:
        return _defensive_fallback(judoka)

    own_edges = graph.edges_owned_by(judoka.identity.name)
    opp_edges = graph.edges_owned_by(opponent.identity.name)

    # Rung 2: commit if a throw is perceived available.
    commit = _try_commit(judoka, opponent, graph, r)
    if commit is not None:
        return [commit]

    # Rung 5: kumi-kata clock nearing shido → escalate.
    escalated = (kumi_kata_clock >= DESPERATION_KUMI_CLOCK)

    # No grips yet → reach.
    if not own_edges:
        return _reach_actions(judoka)

    # If every grip is still shallow (POCKET/SLIPPING), spend both actions
    # seating them — deepen primary, strip the opponent's strongest grip.
    deep_enough = [e for e in own_edges
                   if e.depth_level in (GripDepth.STANDARD, GripDepth.DEEP)]
    if not deep_enough:
        out: list[Action] = [deepen(own_edges[0])]
        if opp_edges:
            target = max(opp_edges, key=lambda e: e.depth_level.modifier())
            strip_hand = _free_hand(judoka) or "right_hand"
            out.append(strip(strip_hand, target))
        else:
            out.append(hold_connective(_primary_hand(judoka)))
        return out

    # Rung 6: fatigued + composed → recover connective.
    hand_fat = _avg_hand_fatigue(judoka)
    if hand_fat > HIGH_FATIGUE_THRESHOLD and not escalated:
        return [
            hold_connective("right_hand"),
            hold_connective("left_hand"),
        ]

    # Rungs 4/5 overlap: drive through the seated grip toward kuzushi.
    drive_mag = DRIVE_MAGNITUDE_N if not escalated else DRIVE_MAGNITUDE_N * 1.3

    # Direction convention: actions carry a force vector in world frame that
    # acts ON THE OPPONENT. PULL draws opponent toward attacker → opp→me;
    # PUSH drives opponent away → me→opp.
    attacker_to_opp = _direction_toward(judoka, opponent)
    pull_dir = (-attacker_to_opp[0], -attacker_to_opp[1])
    push_dir = attacker_to_opp

    primary = deep_enough[0]
    # Secondary action: deepen a shallow grip if any, else push with 2nd hand.
    shallow = [e for e in own_edges if e.depth_level != GripDepth.DEEP
               and e is not primary]
    out = [pull(primary.grasper_part.value, pull_dir, drive_mag)]
    if shallow:
        out.append(deepen(shallow[0]))
    elif len(own_edges) > 1:
        secondary = own_edges[1] if own_edges[0] is primary else own_edges[0]
        out.append(push(secondary.grasper_part.value, push_dir, drive_mag * 0.5))
    return out


# ---------------------------------------------------------------------------
# RUNGS / HELPERS
# ---------------------------------------------------------------------------
def _defensive_fallback(judoka: "Judoka") -> list[Action]:
    # Stunned: minimal-fatigue action.
    return [hold_connective("right_hand"), hold_connective("left_hand")]


def _reach_actions(judoka: "Judoka") -> list[Action]:
    dom = judoka.identity.dominant_side
    is_right = dom == DominantSide.RIGHT
    lapel_target  = GripTarget.LEFT_LAPEL if is_right else GripTarget.RIGHT_LAPEL
    sleeve_target = GripTarget.RIGHT_SLEEVE if is_right else GripTarget.LEFT_SLEEVE
    return [
        reach("right_hand" if is_right else "left_hand", GripTypeV2.LAPEL_HIGH, lapel_target),
        reach("left_hand"  if is_right else "right_hand", GripTypeV2.SLEEVE,     sleeve_target),
    ]


def _try_commit(
    judoka: "Judoka",
    opponent: "Judoka",
    graph: "GripGraph",
    rng: random.Random,
) -> Optional[Action]:
    """If there's a throw whose *perceived* signature clears the commit
    threshold, return a COMMIT_THROW Action for it. Otherwise None.
    """
    from perception import actual_signature_match, perceive

    # Try signature throws first, then full vocabulary.
    candidates: list[ThrowID] = list(judoka.capability.signature_throws)
    for t in judoka.capability.throw_vocabulary:
        if t not in candidates:
            candidates.append(t)

    best_id: Optional[ThrowID] = None
    best_perceived: float = 0.0
    for tid in candidates:
        td = THROW_DEFS.get(tid)
        if td is None:
            continue
        if judoka.capability.throw_profiles.get(tid) is None:
            continue
        actual = actual_signature_match(tid, judoka, opponent, graph)
        perceived = perceive(actual, judoka, rng=rng)
        # Small bonus for signature throws — tokui-waza bias.
        if tid in judoka.capability.signature_throws:
            perceived += 0.05
        if perceived > best_perceived:
            best_perceived = perceived
            best_id = tid

    if best_id is not None and best_perceived >= COMMIT_THRESHOLD:
        return commit_throw(best_id)
    return None


def _direction_toward(judoka: "Judoka", opponent: "Judoka") -> tuple[float, float]:
    """Unit vector from judoka's CoM toward opponent's CoM, in world frame."""
    ax, ay = judoka.state.body_state.com_position
    bx, by = opponent.state.body_state.com_position
    dx, dy = bx - ax, by - ay
    norm = (dx * dx + dy * dy) ** 0.5
    if norm < 1e-9:
        return (1.0, 0.0)
    return (dx / norm, dy / norm)


def _avg_hand_fatigue(judoka: "Judoka") -> float:
    rh = judoka.state.body.get("right_hand")
    lh = judoka.state.body.get("left_hand")
    if rh is None or lh is None:
        return 0.0
    return 0.5 * (rh.fatigue + lh.fatigue)


def _primary_hand(judoka: "Judoka") -> str:
    return ("right_hand"
            if judoka.identity.dominant_side == DominantSide.RIGHT
            else "left_hand")


def _free_hand(judoka: "Judoka") -> Optional[str]:
    from body_state import ContactState as _CS
    for key in ("right_hand", "left_hand"):
        ps = judoka.state.body.get(key)
        if ps is not None and ps.contact_state != _CS.GRIPPING_UKE:
            return key
    return None
