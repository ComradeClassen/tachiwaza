# tests/fixtures/archetypes.py
# Variety-harness fixture library — deliberately exaggerated, archetype-pure
# fighters for the engine's expressive-range battery.
#
# These are DIAGNOSTIC INSTRUMENTS, not gameplay rosters. Every fixture is
# built on one shared all-median skeleton and deviates on exactly one
# contrast axis, so any behavioral difference in a paired match is
# attributable to that axis. Exaggeration is the point: the grip monster has
# maxed grip stats so a failure to dominate the grip exchange is unambiguous.
#
# Design constants (see design-notes/triage/variety-harness-recon-2026-06-10.md):
#   - Belt is pinned to BLACK_1 on every fixture. Belt rank silently drives
#     the skill-vector defaults, the engagement reach race, and the stance
#     comfort vector, so it must never differ inside a pairing.
#   - LEVER is the control archetype for non-archetype-axis fixtures. There
#     is no neutral archetype (every value carries engine modifiers); LEVER's
#     are the smallest. Known, accepted impurity.
#   - All fixtures share one throw vocabulary with flat 5/5 profiles so throw
#     families never confound an axis.
#
# Fixtures are pure construction — deterministic by themselves. Match-level
# determinism additionally needs the runner's two-layer seeding
# (random.seed(s) + Match(seed=s)).

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from enums import BodyArchetype, BeltRank, DominantSide, PositionalStyle
from judoka import Identity, Capability, State, Judoka
from throws import ThrowID, JudokaThrowProfile


# ---------------------------------------------------------------------------
# SHARED SKELETON
# ---------------------------------------------------------------------------
# One vocabulary for everyone: Tanaka's six-throw set, flat 5/5 profiles.
_SHARED_VOCAB: list[ThrowID] = [
    ThrowID.SEOI_NAGE,
    ThrowID.HARAI_GOSHI,
    ThrowID.TAI_OTOSHI,
    ThrowID.O_UCHI_GARI,
    ThrowID.KO_UCHI_GARI,
    ThrowID.O_SOTO_GARI,
]

_MEDIAN_FACETS: dict[str, int] = {
    "aggressive": 5,
    "technical": 5,
    "confident": 5,
    "loyal_to_plan": 5,
}

# Capability body-part keys (all 24) — every one pinned to 5 on the skeleton,
# including the v0.4 parts whose dataclass defaults are 6-7. Purity beats the
# defaults here: a fixture's non-axis parts must be flat.
_ALL_PARTS_MEDIAN: dict[str, int] = {
    part: 5 for part in (
        "right_hand", "left_hand",
        "right_forearm", "left_forearm",
        "right_bicep", "left_bicep",
        "right_shoulder", "left_shoulder",
        "right_leg", "left_leg",
        "right_foot", "left_foot",
        "core", "lower_back", "neck",
        "head",
        "right_hip", "left_hip",
        "right_thigh", "left_thigh",
        "right_knee", "left_knee",
        "right_wrist", "left_wrist",
    )
}


def _median_identity(name: str, **overrides) -> Identity:
    """The shared Identity skeleton. Overrides patch single fields."""
    fields = dict(
        name=name,
        age=26,
        weight_class="-81kg",
        height_cm=175,
        body_archetype=BodyArchetype.LEVER,   # least-marked control archetype
        belt_rank=BeltRank.BLACK_1,           # pinned — belt is a stat
        dominant_side=DominantSide.RIGHT,
        personality_facets=dict(_MEDIAN_FACETS),
        arm_reach_cm=185,
        hip_height_cm=98,
        nationality="Fixture",
        positional_style=PositionalStyle.HOLD_CENTER,
    )
    facet_overrides = overrides.pop("personality_facets", None)
    fields.update(overrides)
    if facet_overrides:
        merged = dict(_MEDIAN_FACETS)
        merged.update(facet_overrides)
        fields["personality_facets"] = merged
    return Identity(**fields)


def _median_capability(**overrides) -> Capability:
    """The shared Capability skeleton: every part 5, every scalar 5."""
    fields: dict = dict(_ALL_PARTS_MEDIAN)
    fields.update(
        cardio_capacity=5,
        cardio_efficiency=5,
        composure_ceiling=5,
        fight_iq=5,
        ne_waza_skill=5,
        foot_speed=5,
        throw_vocabulary=list(_SHARED_VOCAB),
        throw_profiles={
            t: JudokaThrowProfile(t, effectiveness_dominant=5, effectiveness_off_side=5)
            for t in _SHARED_VOCAB
        },
        signature_throws=[ThrowID.SEOI_NAGE, ThrowID.O_UCHI_GARI],
        signature_combos=[],
    )
    fields.update(overrides)
    return Capability(**fields)


def _assemble(identity: Identity, capability: Capability) -> Judoka:
    return Judoka(
        identity=identity,
        capability=capability,
        state=State.fresh(capability, identity),
    )


# ---------------------------------------------------------------------------
# AXIS 1 — GRIP (grip war: initiative bundle + seated-grip force)
# ---------------------------------------------------------------------------
def build_grip_monster() -> Judoka:
    """GRIP_FIGHTER caricature. The grip axis is two systems — who reaches
    first (archetype + aggressive facet) and how strong a seated grip is
    (hands + core) — so both are maxed."""
    identity = _median_identity(
        "GripMonster",
        body_archetype=BodyArchetype.GRIP_FIGHTER,
        personality_facets={"aggressive": 9},
    )
    capability = _median_capability(
        right_hand=10, left_hand=10,
        core=10,
        right_forearm=9, left_forearm=9,
        right_wrist=9, left_wrist=9,
    )
    return _assemble(identity, capability)


def build_passive_median() -> Judoka:
    """The grip monster's foil: all-median body, passive temperament. Should
    lose the reach race and get stripped/dominated if the grip axis works."""
    identity = _median_identity(
        "PassiveMedian",
        personality_facets={"aggressive": 1},
    )
    return _assemble(identity, _median_capability())


# ---------------------------------------------------------------------------
# AXIS 2 — GROUND (ne-waza skill + ground-specialist biases)
# ---------------------------------------------------------------------------
def build_ground_hunter() -> Judoka:
    """GROUND_SPECIALIST caricature: max ne-waza skill. NOTE: the engine has
    no deliberate standing-to-ground action — entries come only from stuffed-
    throw spills (ground_continuation), sacrifice landings, and post-score
    chase. Near-zero ne-waza in this pairing's logs is itself a finding."""
    identity = _median_identity(
        "GroundHunter",
        body_archetype=BodyArchetype.GROUND_SPECIALIST,
    )
    capability = _median_capability(ne_waza_skill=10)
    return _assemble(identity, capability)


def build_standing_wall() -> Judoka:
    """Standing-defense specialist and entry-roll generator: maxed defender-
    resistance parts (legs/core/neck — the throw-resolution defender stats),
    bottomed ne-waza, and aggressive 8 so he attempts throws that get stuffed
    and feed the HAJ-236 ground-continuation roll."""
    identity = _median_identity(
        "StandingWall",
        personality_facets={"aggressive": 8},
    )
    capability = _median_capability(
        right_leg=10, left_leg=10,
        core=10, neck=10,
        ne_waza_skill=1,
    )
    return _assemble(identity, capability)


# ---------------------------------------------------------------------------
# AXIS 3 — HEIGHT (grip-initiative height term + CoM geometry)
# ---------------------------------------------------------------------------
def build_tower() -> Judoka:
    """Maximum plausible height. Height feeds exactly one roll (grip
    initiative, 0.4 weight per 30 cm) plus CoM geometry — expect a modest,
    grip-side expression. Mass/density is unwired, so this pairing is
    height-only by design."""
    identity = _median_identity("Tower", height_cm=196, hip_height_cm=110)
    return _assemble(identity, _median_capability())


def build_fireplug() -> Judoka:
    """Minimum plausible height; otherwise identical to Tower."""
    identity = _median_identity("Fireplug", height_cm=158, hip_height_cm=86)
    return _assemble(identity, _median_capability())


# ---------------------------------------------------------------------------
# AXIS 4 — FIGHT IQ (the most-wired stat in the engine)
# ---------------------------------------------------------------------------
def build_professor() -> Judoka:
    """fight_iq 10 on a median body. IQ touches ~15 systems (perception,
    reaction lag, planning, counters, stance, edge play) — this should be
    the loudest contrast in the battery."""
    identity = _median_identity("Professor")
    capability = _median_capability(fight_iq=10)
    return _assemble(identity, capability)


def build_brawler() -> Judoka:
    """fight_iq 1, stat-identical body to Professor."""
    identity = _median_identity("Brawler")
    capability = _median_capability(fight_iq=1)
    return _assemble(identity, capability)


# ---------------------------------------------------------------------------
# AXIS 5 — CARDIO (fatigue feeds initiative, grip force, chase, desperation)
# ---------------------------------------------------------------------------
def build_diesel() -> Judoka:
    identity = _median_identity("Diesel")
    capability = _median_capability(cardio_capacity=10, cardio_efficiency=10)
    return _assemble(identity, capability)


def build_gasser() -> Judoka:
    identity = _median_identity("Gasser")
    capability = _median_capability(cardio_capacity=2, cardio_efficiency=2)
    return _assemble(identity, capability)


# ---------------------------------------------------------------------------
# AXIS 6 — KENKA-YOTSU COMFORT (stance comfort vector, HAJ-237/238)
# ---------------------------------------------------------------------------
# Both sides get fight_iq 8: tactical stance switching is IQ-gated, so a
# median IQ would mute the axis under test. Known, logged impurity — the two
# fixtures still differ only on the comfort vector.
def build_kenka_hunter() -> Judoka:
    """Lives for the mirrored inside-fight: max kenka comfort, near-max
    off-stance comfort. Should switch to force MIRRORED and thrive there."""
    identity = _median_identity(
        "KenkaHunter",
        stance_matchup_comfort={"kenka_yotsu": 1.0, "southpaw": 0.95},
    )
    capability = _median_capability(fight_iq=8)
    return _assemble(identity, capability)


def build_aiyotsu_purist() -> Judoka:
    """Helpless in the mirrored fight: kenka and off-stance comfort floored.
    Should avoid MIRRORED, eat penalties when forced into it."""
    identity = _median_identity(
        "AiyotsuPurist",
        stance_matchup_comfort={"kenka_yotsu": 0.05, "southpaw": 0.05},
    )
    capability = _median_capability(fight_iq=8)
    return _assemble(identity, capability)


# ---------------------------------------------------------------------------
# REGISTRY
# ---------------------------------------------------------------------------
FIXTURES: dict[str, "callable"] = {
    "grip_monster":   build_grip_monster,
    "passive_median": build_passive_median,
    "ground_hunter":  build_ground_hunter,
    "standing_wall":  build_standing_wall,
    "tower":          build_tower,
    "fireplug":       build_fireplug,
    "professor":      build_professor,
    "brawler":        build_brawler,
    "diesel":         build_diesel,
    "gasser":         build_gasser,
    "kenka_hunter":   build_kenka_hunter,
    "aiyotsu_purist": build_aiyotsu_purist,
}


def build(name: str) -> Judoka:
    """Build a fixture by registry name. KeyError with the roster on miss."""
    try:
        factory = FIXTURES[name]
    except KeyError:
        raise KeyError(
            f"Unknown fixture {name!r}. Available: {', '.join(sorted(FIXTURES))}"
        ) from None
    return factory()
