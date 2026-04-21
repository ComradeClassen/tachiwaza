# grip_presence_gate.py
# HAJ-36 — formal grip-presence commit gate.
#
# Before this module, the only precondition on a throw commit was (i) the
# attacker owns at least one edge and (ii) the perceived signature clears
# the commit threshold. Both checks lived inside action_selection.py, and
# the "one edge" rule was implicit in a single `if not own_edges` line.
#
# This module makes the gate formal: one function, four conjunctive
# checks, one bypass rule. action_selection calls it for every candidate
# throw before returning a COMMIT_THROW action. Match uses the bypass
# flag to annotate the log line.
#
# The four checks (all must pass, in priority order for failure reporting):
#
#   (a) Depth floor.      At least one edge owned by the attacker is
#                         at GripDepth.STANDARD or GripDepth.DEEP. A
#                         fighter with only POCKET / SLIPPING grips has
#                         not earned a commit.
#
#   (b) Both-hands rule.  If ThrowDef.requires_both_hands is True (the
#                         default), the attacker must own an edge with
#                         each of right_hand and left_hand. Sacrifice
#                         throws and low-commitment sweeps set the flag
#                         to False and are exempt.
#
#   (c) Edge prereqs.     GripGraph.satisfies(throw.requires) — the
#                         throw's EdgeRequirement list resolves against
#                         the live graph. This is the existing gate
#                         throws.py already defined; we just surface its
#                         result here instead of letting it fire only
#                         inside perception.
#
#   (d) No SLIPPING.      No edge owned by the attacker is at
#                         GripDepth.SLIPPING. A grip that is actively
#                         peeling off cannot carry the throw.
#
# Bypass: if either offensive OR defensive desperation is active, the
# gate returns allowed=True with bypassed=True, and the original failure
# reason is recorded so the log can say "(gate bypassed: all_shallow)"
# or similar. This is (e) from the scope discussion.

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from enums import GripDepth

if TYPE_CHECKING:
    from judoka import Judoka
    from grip_graph import GripGraph
    from throws import ThrowDef


# ---------------------------------------------------------------------------
# FAILURE REASONS — stable string keys for logs/tests
# ---------------------------------------------------------------------------
REASON_OK:               str = "ok"
REASON_NO_EDGES:         str = "no_edges"
REASON_ALL_SHALLOW:      str = "all_shallow"
REASON_NEEDS_BOTH_HANDS: str = "needs_both_hands"
REASON_EDGE_REQS_UNMET:  str = "edge_reqs_unmet"
REASON_SLIPPING_EDGES:   str = "slipping_edges"


@dataclass(frozen=True)
class GateResult:
    allowed: bool
    reason: str              # REASON_* constant
    bypassed: bool = False   # True when desperation overrode a real failure
    bypass_kind: Optional[str] = None   # "offensive" | "defensive" | None


# ---------------------------------------------------------------------------
# PRIMARY ENTRY POINT
# ---------------------------------------------------------------------------
def evaluate_gate(
    attacker: "Judoka",
    throw_def: "ThrowDef",
    graph: "GripGraph",
    *,
    offensive_desperation: bool = False,
    defensive_desperation: bool = False,
) -> GateResult:
    """Decide whether `attacker` may legally commit `throw_def` right now.

    Checks (a)–(d) in priority order. The first failing check becomes the
    reason. A desperation flag bypasses the gate but preserves the reason
    so callers can surface "committed in desperation despite X."
    """
    own_edges = graph.edges_owned_by(attacker.identity.name)

    fail: Optional[str] = None

    if not own_edges:
        fail = REASON_NO_EDGES
    else:
        # (a) Depth floor — "no commits from PURE POCKET/SLIPPING". We check
        # each edge's max_depth_reached rather than its live depth so a grip
        # that was once STANDARD (and is currently being stripped) still
        # satisfies the floor. A grip that has only ever been POCKET or
        # SLIPPING does not.
        has_standard_or_deep = any(
            (e.max_depth_reached or e.depth_level)
            in (GripDepth.STANDARD, GripDepth.DEEP)
            for e in own_edges
        )
        # (d) SLIPPING check (evaluated early to give a clean reason)
        no_slipping = all(
            e.depth_level != GripDepth.SLIPPING for e in own_edges
        )
        # (b) Both hands
        if throw_def.requires_both_hands:
            hands = {e.grasper_part.value for e in own_edges}
            both_hands_ok = ("right_hand" in hands) and ("left_hand" in hands)
        else:
            both_hands_ok = True
        # (c) Edge requirements
        edge_reqs_ok = graph.satisfies(
            throw_def.requires,
            attacker.identity.name,
            attacker.identity.dominant_side,
        )

        if not has_standard_or_deep:
            fail = REASON_ALL_SHALLOW
        elif not both_hands_ok:
            fail = REASON_NEEDS_BOTH_HANDS
        elif not edge_reqs_ok:
            fail = REASON_EDGE_REQS_UNMET
        elif not no_slipping:
            fail = REASON_SLIPPING_EDGES

    if fail is None:
        return GateResult(allowed=True, reason=REASON_OK)

    # (e) Desperation bypass — both kinds override the gate.
    if offensive_desperation:
        return GateResult(
            allowed=True, reason=fail,
            bypassed=True, bypass_kind="offensive",
        )
    if defensive_desperation:
        return GateResult(
            allowed=True, reason=fail,
            bypassed=True, bypass_kind="defensive",
        )

    return GateResult(allowed=False, reason=fail)
