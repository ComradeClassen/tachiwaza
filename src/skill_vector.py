# skill_vector.py
# HAJ-137 — fine-grained skill axes per grip-as-cause.md §5.1.
#
# Pre-fix Judoka exposed `belt_rank`, `fight_iq`, `composure`, `cardio`,
# plus per-throw profiles. The fine-grained axes that differentiate
# "white-belt throw spam" from "brown-belt patient grip war" structurally
# didn't exist as data — earlier tickets (HAJ-131/133/134/135/136)
# stubbed specific axes with `fight_iq` placeholders.
#
# This module promotes the §5.1 axis list to first-class data:
# `SkillVector` is a 22-axis dataclass, `default_for_belt` derives
# belt-correlated default profiles per §6, and the wired skills are
# read from `judoka.skill_vector.<axis>` instead of `fight_iq / 10.0`.
#
# fight_iq stays as a compatibility signal for legacy code paths and
# action-ladder thresholds (white belts don't plan; below-floor IQ
# fighters don't probe foot attacks). The skill vector is authoritative
# for force / precision / perception math.

from __future__ import annotations
import math
from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING, Optional

from enums import BeltRank

if TYPE_CHECKING:
    from judoka import Judoka


# ---------------------------------------------------------------------------
# SKILL VECTOR
# ---------------------------------------------------------------------------
@dataclass
class SkillVector:
    """The 22 atomic skill axes that drive a fighter's mechanical
    behavior. Each axis is in [0.0, 1.0]; per §5.1, axes are
    independent — a fighter can be elite at lapel grip work and weak
    at foot sweeps. Belt rank is a *summary* of these, not a substitute.
    """

    # ----- Grip fighting (offensive depth + edge management) -----
    lapel_grip:    float = 0.5    # offensive lapel depth control
    sleeve_grip:   float = 0.5    # offensive sleeve depth control
    two_on_one:    float = 0.5    # committing two hands to control one
    stripping:     float = 0.5    # degrading opponent grips
    defending:     float = 0.5    # resisting opponent strips
    reposition:    float = 0.5    # transitioning grips without releasing
    pull_execution: float = 0.5   # clean pull conversion / no self-cancellation

    # ----- Footwork (defensive / stabilizing) -----
    tsugi_ashi:    float = 0.5    # following step, base-preserving
    ayumi_ashi:    float = 0.5    # walking step, distance-closing
    pivots:        float = 0.5    # hip rotation under load
    base_recovery: float = 0.5    # regaining balance after committed motion

    # ----- Footwork (offensive) -----
    foot_sweeps:        float = 0.5  # de-ashi-harai family
    leg_attacks:        float = 0.5  # ko-uchi / o-uchi setups
    disruptive_stepping: float = 0.5 # intentional positional moves

    # ----- Fight IQ (perception + planning) -----
    counter_window_reading: float = 0.5  # perception of opponent commits
    exposure_reading:       float = 0.5  # perception of opponent vulnerability
    pattern_reading:        float = 0.5  # recognizing setup sequences
    timing:                 float = 0.5  # uke-posture-state read for pull moments
    sequencing_precision:   float = 0.5  # elite combo coordination (§3.6)

    # ----- Composure -----
    pressure_handling: float = 0.5   # composure under sustained attack
    ref_handling:      float = 0.5   # response to ref calls
    score_handling:    float = 0.5   # response to being scored on

    def axis_names(self) -> list[str]:
        return [f.name for f in fields(self)]

    def __getitem__(self, name: str) -> float:
        return getattr(self, name)


# ---------------------------------------------------------------------------
# BELT-CORRELATED DEFAULTS (§6 belt profiles)
# ---------------------------------------------------------------------------
# Default vector for each rank. Per §6, axes scale monotonically with
# belt rank — a white belt sits around 0.20 across the board; a Black-5
# sits around 0.85. The intent is that defaults give a coherent fighter
# at any rank; per-fighter signature comes from later overrides on top
# of the default.
#
# v0.1 keeps all axes at the same value within a rank (uniform profile).
# §6's "different belts emphasize different clusters" (white belts good
# at striking, brown belts good at the grip war) is post-Ring-1 work;
# the architectural slot exists here as the rank-keyed table.
_BELT_BASE: dict[BeltRank, float] = {
    BeltRank.WHITE:   0.20,
    BeltRank.YELLOW:  0.28,
    BeltRank.ORANGE:  0.36,
    BeltRank.GREEN:   0.45,
    BeltRank.BLUE:    0.55,
    BeltRank.BROWN:   0.65,
    BeltRank.BLACK_1: 0.75,
    BeltRank.BLACK_2: 0.78,
    BeltRank.BLACK_3: 0.81,
    BeltRank.BLACK_4: 0.84,
    BeltRank.BLACK_5: 0.87,
}


def default_for_belt(rank: BeltRank) -> SkillVector:
    """Build the belt-default SkillVector. All axes = the rank's base
    value. Per-fighter signature overrides land on top after construction.
    """
    base = _BELT_BASE.get(rank, 0.50)
    sv = SkillVector()
    for f in fields(sv):
        setattr(sv, f.name, base)
    return sv


# ---------------------------------------------------------------------------
# READ HELPER
# ---------------------------------------------------------------------------
# Centralized accessor so call sites don't need to handle the "judoka
# has no skill_vector yet" case (legacy fixtures created before HAJ-137).
# Returns the named axis when the vector exists, else falls back to
# fight_iq / 10.0 (the pre-HAJ-137 stub everyone was using).
def axis(judoka: "Judoka", name: str) -> float:
    """Read a skill-vector axis with a graceful fight_iq fallback.

    Used at every call site that switched from `fight_iq / 10.0`. If
    the judoka has a skill_vector set, return the named axis; else
    derive a stand-in value from fight_iq so legacy tests that build
    Judoka instances directly without going through main.py builders
    still work.
    """
    sv = getattr(judoka, "skill_vector", None)
    if sv is None:
        return max(0.0, min(1.0, judoka.capability.fight_iq / 10.0))
    return float(getattr(sv, name, max(0.0, min(1.0,
        judoka.capability.fight_iq / 10.0))))


def set_uniform(judoka: "Judoka", value: float) -> None:
    """Test helper — set every skill-vector axis on `judoka` to `value`.

    Used by tests that previously drove behavior via `fight_iq` to drive
    behavior via the skill vector instead. Production code should never
    need this — fighters develop heterogeneous vectors, not uniform ones.
    """
    sv = getattr(judoka, "skill_vector", None)
    if sv is None:
        sv = SkillVector()
        judoka.skill_vector = sv
    clamped = max(0.0, min(1.0, value))
    for f in fields(sv):
        setattr(sv, f.name, clamped)
