# tests/test_haj207_stage1_availability.py
# HAJ-207 — Stage 1 availability filter + minimal Stage 2 selection.
#
# Covers:
#   - Unit: stage1_available_techniques with various grip configurations
#     against a small test catalog.
#       * empty graph → empty set
#       * matched tori grips + no uke disqualifier → technique available
#       * shallow tori grip blocks (minimum_depth not met)
#       * uke disqualifying grip blocks (HAJ-199 regression)
#       * proficiency below PROFICIENT excludes (known / novice)
#       * mirror_eligible signature resolves correctly for left-dominant tori
#   - Stage 2 stochastic selection:
#       * empty available → returns None
#       * kuzushi direction must be admitted (or `any` wildcard)
#       * fire-probability gates on fight_iq / cardio
#   - Integration on _try_commit:
#       * Stage-1 empty → no scoring commit fires
#       * Stage-1 non-empty + high perceived signature → commit fires
#       * HAJ-199 regression: uke deep collar on tori blocks tori's commits

from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from enums import (
    BodyArchetype, BeltRank, BodyPart, DominantSide,
    GripMode, GripTarget, GripTypeV2,
    GripDepth as EngineGripDepth,
)
from grip_graph import GripEdge, GripGraph
from judoka import Capability, Identity, Judoka, State
from technique_catalog import (
    FailedThrowConsequence, GripDepth as CatalogGripDepth,
    GripHand, GripSignature, GripSpec, GripTargetRegion,
    KodokanStatus, ProficiencyTier, TechniqueDefinition, TechniqueFamily,
    TechniqueRecord, UkePostureRequirement,
)
from throws import ThrowID

from availability import (
    THROW_TO_TECHNIQUE_ID, stage1_available_techniques,
    stage2_select_technique, proficiency_tier_for,
    classify_kuzushi_direction,
)


# ---------------------------------------------------------------------------
# FIXTURES
# ---------------------------------------------------------------------------
def _judoka(name: str, dominant: DominantSide = DominantSide.RIGHT,
            vocabulary: list[ThrowID] | None = None,
            fight_iq: int = 7,
            technique_records: dict[str, TechniqueRecord] | None = None,
            ) -> Judoka:
    ident = Identity(
        name=name, age=26, weight_class="-90kg", height_cm=180,
        body_archetype=BodyArchetype.LEVER,
        belt_rank=BeltRank.BLACK_1, dominant_side=dominant,
        personality_facets={"aggressive": 5, "technical": 5,
                            "confident": 5, "loyal_to_plan": 5},
        arm_reach_cm=185, hip_height_cm=100, nationality="x",
    )
    cap = Capability(
        right_hand=8, left_hand=8, right_forearm=8, left_forearm=8,
        right_bicep=8, left_bicep=8, right_shoulder=8, left_shoulder=8,
        right_leg=8, left_leg=8, right_foot=8, left_foot=8,
        core=8, lower_back=8, neck=8,
        cardio_capacity=8, cardio_efficiency=8, composure_ceiling=8,
        fight_iq=fight_iq, ne_waza_skill=5,
        right_hip=8, left_hip=8, right_thigh=8, left_thigh=8,
        right_knee=8, left_knee=8, right_wrist=8, left_wrist=8, head=5,
        throw_vocabulary=list(vocabulary or [
            ThrowID.SEOI_NAGE, ThrowID.UCHI_MATA, ThrowID.O_SOTO_GARI,
        ]),
        throw_profiles={},
        signature_throws=[],
        signature_combos=[],
    )
    if technique_records is not None:
        # Capability has no technique_records field by default — attach
        # dynamically so the availability helper picks it up.
        cap.technique_records = technique_records  # type: ignore[attr-defined]
    return Judoka(identity=ident, capability=cap,
                  state=State.fresh(cap, ident))


def _seat(graph: GripGraph, grasper: str, hand: BodyPart,
          target: str, target_loc: GripTarget,
          grip_type: GripTypeV2, depth: EngineGripDepth,
          *, max_depth: EngineGripDepth | None = None) -> GripEdge:
    edge = GripEdge(
        grasper_id=grasper, grasper_part=hand,
        target_id=target, target_location=target_loc,
        grip_type_v2=grip_type,
        depth_level=depth, strength=1.0, established_tick=0,
        mode=GripMode.CONNECTIVE,
    )
    if max_depth is not None:
        edge.max_depth_reached = max_depth
    graph.edges.append(edge)
    return edge


def _seoi_signature(min_lapel: CatalogGripDepth = CatalogGripDepth.CONTROLLED,
                    min_sleeve: CatalogGripDepth = CatalogGripDepth.SHALLOW,
                    uke_disqualifying: list[GripSpec] | None = None,
                    ) -> GripSignature:
    """Canonical right-stance seoi-nage signature: right hand on uke
    lapel-high, left hand on uke sleeve-upper."""
    return GripSignature(
        tori_required_grips=[
            GripSpec(
                hand=GripHand.TORI_RIGHT,
                target_region=GripTargetRegion.UKE_LAPEL_HIGH,
                minimum_depth=min_lapel,
            ),
            GripSpec(
                hand=GripHand.TORI_LEFT,
                target_region=GripTargetRegion.UKE_SLEEVE_UPPER,
                minimum_depth=min_sleeve,
            ),
        ],
        uke_disqualifying_grips=list(uke_disqualifying or []),
        mirror_eligible=True,
    )


def _technique(technique_id: str, signature: GripSignature,
               admissible: list[str] | None = None) -> TechniqueDefinition:
    return TechniqueDefinition(
        technique_id=technique_id,
        name_japanese=technique_id,
        name_english=technique_id,
        family=TechniqueFamily.TE_WAZA,
        subfamily="forward_throw",
        kodokan_status=KodokanStatus.GOKYO_NO_WAZA,
        canonical_grip_signatures=[signature],
        admissible_kuzushi_vectors=list(admissible or ["forward_pure"]),
        couple_type="forward_rotation",
        posture_requirements=UkePostureRequirement.ANY,
        base_difficulty=50,
    )


def _seat_canonical_engagement(graph: GripGraph, tori: Judoka, uke: Judoka,
                               depth: EngineGripDepth = EngineGripDepth.STANDARD,
                               ) -> None:
    """Seat the canonical right-stance engagement: tori_right on uke's
    LEFT_LAPEL (LAPEL_HIGH), tori_left on uke's RIGHT_SLEEVE (SLEEVE_HIGH)."""
    _seat(graph, tori.identity.name, BodyPart.RIGHT_HAND,
          uke.identity.name, GripTarget.LEFT_LAPEL,
          GripTypeV2.LAPEL_HIGH, depth)
    _seat(graph, tori.identity.name, BodyPart.LEFT_HAND,
          uke.identity.name, GripTarget.RIGHT_SLEEVE,
          GripTypeV2.SLEEVE_HIGH, depth)


# ---------------------------------------------------------------------------
# UNIT — stage1_available_techniques
# ---------------------------------------------------------------------------
def test_empty_graph_yields_empty_available_set() -> None:
    tori, uke = _judoka("T"), _judoka("U")
    graph = GripGraph()
    catalog = {"seoi": _technique("seoi", _seoi_signature())}
    assert stage1_available_techniques(graph, tori, uke, catalog) == set()


def test_matched_grips_make_technique_available() -> None:
    tori = _judoka("T", vocabulary=[ThrowID.SEOI_NAGE])
    uke = _judoka("U")
    graph = GripGraph()
    _seat_canonical_engagement(graph, tori, uke, EngineGripDepth.STANDARD)
    catalog = {"seoi_nage": _technique("seoi_nage", _seoi_signature())}
    available = stage1_available_techniques(graph, tori, uke, catalog)
    assert "seoi_nage" in available


def test_shallow_grip_below_minimum_depth_excludes_technique() -> None:
    """A POCKET-only grip (max_depth never reached STANDARD) fails the
    CONTROLLED minimum on the lapel spec."""
    tori = _judoka("T", vocabulary=[ThrowID.SEOI_NAGE])
    uke = _judoka("U")
    graph = GripGraph()
    _seat(graph, "T", BodyPart.RIGHT_HAND, "U", GripTarget.LEFT_LAPEL,
          GripTypeV2.LAPEL_HIGH, EngineGripDepth.POCKET)
    _seat(graph, "T", BodyPart.LEFT_HAND, "U", GripTarget.RIGHT_SLEEVE,
          GripTypeV2.SLEEVE_HIGH, EngineGripDepth.POCKET)
    catalog = {"seoi_nage": _technique("seoi_nage", _seoi_signature(
        min_lapel=CatalogGripDepth.CONTROLLED,
        min_sleeve=CatalogGripDepth.SHALLOW,
    ))}
    assert stage1_available_techniques(graph, tori, uke, catalog) == set()


def test_max_depth_reached_satisfies_min_depth_after_strip() -> None:
    """A grip currently SLIPPING but with max_depth_reached=DEEP still
    earns Stage 1 availability for a CONTROLLED-min spec. Mirrors the
    HAJ-36 grip-presence gate convention."""
    tori = _judoka("T", vocabulary=[ThrowID.SEOI_NAGE])
    uke = _judoka("U")
    graph = GripGraph()
    _seat(graph, "T", BodyPart.RIGHT_HAND, "U", GripTarget.LEFT_LAPEL,
          GripTypeV2.LAPEL_HIGH, EngineGripDepth.SLIPPING,
          max_depth=EngineGripDepth.DEEP)
    _seat(graph, "T", BodyPart.LEFT_HAND, "U", GripTarget.RIGHT_SLEEVE,
          GripTypeV2.SLEEVE_HIGH, EngineGripDepth.SLIPPING,
          max_depth=EngineGripDepth.STANDARD)
    catalog = {"seoi_nage": _technique("seoi_nage", _seoi_signature())}
    assert "seoi_nage" in stage1_available_techniques(graph, tori, uke, catalog)


def test_uke_disqualifying_grip_blocks_technique() -> None:
    """HAJ-199 core regression: uke holding a disqualifying grip on tori
    blocks the technique even when tori's required grips are seated."""
    tori = _judoka("T", vocabulary=[ThrowID.UCHI_MATA])
    uke = _judoka("U")
    graph = GripGraph()
    _seat_canonical_engagement(graph, tori, uke, EngineGripDepth.STANDARD)
    # Uke holds a deep low-sleeve grip on tori — the classical uchi-mata
    # disqualifier from the catalog.
    _seat(graph, "U", BodyPart.RIGHT_HAND, "T", GripTarget.LEFT_SLEEVE,
          GripTypeV2.SLEEVE_LOW, EngineGripDepth.DEEP)
    disqualifier = GripSpec(
        hand=GripHand.TORI_RIGHT,
        target_region=GripTargetRegion.UKE_SLEEVE_LOWER,
        minimum_depth=CatalogGripDepth.DEEP,
    )
    catalog = {"uchi_mata": _technique(
        "uchi_mata",
        _seoi_signature(uke_disqualifying=[disqualifier]),
    )}
    assert stage1_available_techniques(graph, tori, uke, catalog) == set()


def test_proficiency_below_proficient_excludes_technique() -> None:
    """NOVICE / KNOWN techniques aren't selectable for live commit."""
    novice = TechniqueRecord(
        technique_id="seoi_nage",
        proficiency_tier=ProficiencyTier.NOVICE,
    )
    tori = _judoka(
        "T",
        vocabulary=[],  # not in legacy throw_vocabulary either
        technique_records={"seoi_nage": novice},
    )
    uke = _judoka("U")
    graph = GripGraph()
    _seat_canonical_engagement(graph, tori, uke, EngineGripDepth.STANDARD)
    catalog = {"seoi_nage": _technique("seoi_nage", _seoi_signature())}
    assert stage1_available_techniques(graph, tori, uke, catalog) == set()


def test_proficient_tier_via_explicit_record() -> None:
    proficient = TechniqueRecord(
        technique_id="seoi_nage",
        proficiency_tier=ProficiencyTier.PROFICIENT,
    )
    tori = _judoka("T", vocabulary=[],
                   technique_records={"seoi_nage": proficient})
    uke = _judoka("U")
    graph = GripGraph()
    _seat_canonical_engagement(graph, tori, uke, EngineGripDepth.STANDARD)
    catalog = {"seoi_nage": _technique("seoi_nage", _seoi_signature())}
    assert "seoi_nage" in stage1_available_techniques(graph, tori, uke, catalog)


def test_legacy_vocabulary_acts_as_proficient_fallback() -> None:
    """When no technique_records exist, presence in throw_vocabulary
    counts as PROFICIENT — preserves legacy fighter-builder behavior."""
    tori = _judoka("T", vocabulary=[ThrowID.SEOI_NAGE])
    assert proficiency_tier_for(tori, "seoi_nage") == ProficiencyTier.PROFICIENT


def test_mirror_eligible_signature_resolves_for_left_dominant_tori() -> None:
    """A left-dominant tori with mirror_eligible signature gets the
    grips resolved against the opposite physical hand."""
    tori = _judoka("T", dominant=DominantSide.LEFT,
                   vocabulary=[ThrowID.SEOI_NAGE])
    uke = _judoka("U")
    graph = GripGraph()
    # Left-dominant tori: tori_right (catalog) → physical LEFT_HAND.
    # That hand grips uke's right lapel; tori_left → physical RIGHT_HAND
    # grips uke's left sleeve.
    _seat(graph, "T", BodyPart.LEFT_HAND, "U", GripTarget.RIGHT_LAPEL,
          GripTypeV2.LAPEL_HIGH, EngineGripDepth.STANDARD)
    _seat(graph, "T", BodyPart.RIGHT_HAND, "U", GripTarget.LEFT_SLEEVE,
          GripTypeV2.SLEEVE_HIGH, EngineGripDepth.STANDARD)
    catalog = {"seoi_nage": _technique("seoi_nage", _seoi_signature())}
    assert "seoi_nage" in stage1_available_techniques(graph, tori, uke, catalog)


def test_multi_signature_technique_succeeds_when_any_signature_matches() -> None:
    """v1.2 multi-signature catalog entries are available if ANY entry
    in the list is satisfied."""
    tori = _judoka("T", vocabulary=[ThrowID.SEOI_NAGE])
    uke = _judoka("U")
    graph = GripGraph()
    _seat_canonical_engagement(graph, tori, uke, EngineGripDepth.STANDARD)
    impossible = GripSignature(
        tori_required_grips=[
            GripSpec(hand=GripHand.TORI_LEFT,
                     target_region=GripTargetRegion.UKE_BELT,
                     minimum_depth=CatalogGripDepth.DEEP),
        ],
    )
    catalog = {"seoi_nage": TechniqueDefinition(
        technique_id="seoi_nage",
        name_japanese="seoi_nage", name_english="seoi_nage",
        family=TechniqueFamily.TE_WAZA, subfamily="forward_throw",
        kodokan_status=KodokanStatus.GOKYO_NO_WAZA,
        canonical_grip_signatures=[impossible, _seoi_signature()],
        admissible_kuzushi_vectors=["forward_pure"],
        couple_type="x", posture_requirements=UkePostureRequirement.ANY,
        base_difficulty=50,
    )}
    assert "seoi_nage" in stage1_available_techniques(graph, tori, uke, catalog)


# ---------------------------------------------------------------------------
# STAGE 2
# ---------------------------------------------------------------------------
def test_stage2_returns_none_for_empty_available() -> None:
    tori = _judoka("T")
    rng = random.Random(0)
    result = stage2_select_technique(
        available=set(),
        catalog={"seoi": _technique("seoi", _seoi_signature())},
        tori=tori,
        kuzushi_vector=(1.0, 0.0),
        uke_facing=(-1.0, 0.0),
        perceived_signature={"seoi": 0.9},
        rng=rng,
    )
    assert result is None


def test_stage2_filters_by_admissible_kuzushi_vector() -> None:
    """A technique whose admissible_kuzushi_vectors don't include the
    current direction (and which is not `any`) is excluded."""
    proficient = ProficiencyTier.PROFICIENT
    records = {
        "seoi":  TechniqueRecord(technique_id="seoi",  proficiency_tier=proficient),
        "osoto": TechniqueRecord(technique_id="osoto", proficiency_tier=proficient),
    }
    tori = _judoka("T", fight_iq=10, technique_records=records)
    rng = random.Random(0)
    # Uke faces +x; kuzushi vector (1, 0) is "uke being pulled in their
    # own forward direction" → forward_pure.
    forward_only = _technique("seoi", _seoi_signature(),
                              admissible=["forward_pure"])
    rear_only = _technique("osoto", _seoi_signature(),
                           admissible=["rear_pure"])
    catalog = {"seoi": forward_only, "osoto": rear_only}
    # Run the selector many times — only seoi (forward_pure) should ever
    # come back.
    seen: set[str] = set()
    for _ in range(200):
        res = stage2_select_technique(
            available={"seoi", "osoto"},
            catalog=catalog,
            tori=tori,
            kuzushi_vector=(1.0, 0.0),
            uke_facing=(1.0, 0.0),
            perceived_signature={"seoi": 0.9, "osoto": 0.9},
            rng=rng,
        )
        if res is not None:
            seen.add(res)
    assert "seoi" in seen
    assert "osoto" not in seen


def test_stage2_any_wildcard_admits_regardless_of_vector() -> None:
    records = {"deashi": TechniqueRecord(
        technique_id="deashi", proficiency_tier=ProficiencyTier.PROFICIENT,
    )}
    tori = _judoka("T", fight_iq=10, technique_records=records)
    rng = random.Random(0)
    omnidirectional = _technique("deashi", _seoi_signature(),
                                 admissible=["any"])
    seen: set[str] = set()
    for _ in range(50):
        res = stage2_select_technique(
            available={"deashi"},
            catalog={"deashi": omnidirectional},
            tori=tori,
            # Below-threshold magnitude → no direction can be classified.
            kuzushi_vector=(0.0, 0.0),
            uke_facing=(-1.0, 0.0),
            perceived_signature={"deashi": 0.85},
            rng=rng,
        )
        if res is not None:
            seen.add(res)
    assert "deashi" in seen


def test_classify_kuzushi_direction_forward_pure_in_uke_frame() -> None:
    # Uke faces +x; a +x kuzushi vector pushes uke in their own forward
    # direction → forward_pure.
    assert classify_kuzushi_direction((1.0, 0.0), (1.0, 0.0)) == "forward_pure"


def test_classify_kuzushi_direction_rear_pure_in_uke_frame() -> None:
    # Uke faces +x; a -x kuzushi vector pushes uke into their rear.
    assert classify_kuzushi_direction((-1.0, 0.0), (1.0, 0.0)) == "rear_pure"


def test_classify_kuzushi_direction_below_magnitude_returns_none() -> None:
    assert classify_kuzushi_direction((0.0, 0.0), (1.0, 0.0)) is None


# ---------------------------------------------------------------------------
# INTEGRATION — _try_commit catalog path
# ---------------------------------------------------------------------------
def _run_try_commit(tori: Judoka, uke: Judoka, graph: GripGraph,
                    catalog: dict, *,
                    high_perceived: bool = True,
                    seed: int = 0):
    """Drive _try_commit with deterministic perception that puts at
    least one throw above the commit threshold."""
    from action_selection import _try_commit, COMMIT_THRESHOLD
    import perception
    # Monkey-patch perception so candidates clear the commit threshold.
    real_actual = perception.actual_signature_match
    real_perceive = perception.perceive
    target_value = (COMMIT_THRESHOLD + 0.10) if high_perceived else 0.10
    perception.actual_signature_match = lambda *a, **kw: target_value
    perception.perceive = lambda actual, *a, **kw: actual
    try:
        action = _try_commit(
            tori, uke, graph, random.Random(seed),
            catalog=catalog,
        )
    finally:
        perception.actual_signature_match = real_actual
        perception.perceive = real_perceive
    return action


def test_try_commit_fires_when_stage1_available_and_signature_clears() -> None:
    from throws import THROW_DEFS
    from actions import ActionKind
    # Use the canonical catalog mapping for seoi_nage so THROW_TO_TECHNIQUE_ID
    # resolves SEOI_NAGE → "seoi_nage".
    tori = _judoka("T", vocabulary=[ThrowID.SEOI_NAGE], fight_iq=10)
    tori.capability.throw_profiles[ThrowID.SEOI_NAGE] = type(
        "P", (), {"effectiveness_dominant": 9, "effectiveness_off_side": 3}
    )()
    uke = _judoka("U")
    graph = GripGraph()
    _seat_canonical_engagement(graph, tori, uke, EngineGripDepth.STANDARD)
    catalog = {"seoi_nage": _technique(
        "seoi_nage", _seoi_signature(), admissible=["any"],
    )}
    # Drive many seeds to overcome the stochastic fire gate.
    fired = False
    for seed in range(20):
        action = _run_try_commit(tori, uke, graph, catalog, seed=seed)
        if action is not None and action.kind == ActionKind.COMMIT_THROW:
            assert action.throw_id == ThrowID.SEOI_NAGE
            fired = True
            break
    assert fired, "Stage-1-available technique never fired across 20 seeds"


def test_try_commit_blocks_when_stage1_empty_haj199_regression() -> None:
    """HAJ-199 regression: uke holds a heavy disqualifying grip; tori's
    perceived signature would clear the threshold under legacy gating,
    but the catalog-driven Stage 1 returns empty, so no scoring commit
    fires this tick."""
    from actions import ActionKind

    tori = _judoka("T", vocabulary=[ThrowID.SEOI_NAGE], fight_iq=10)
    tori.capability.throw_profiles[ThrowID.SEOI_NAGE] = type(
        "P", (), {"effectiveness_dominant": 9, "effectiveness_off_side": 3}
    )()
    uke = _judoka("U")
    graph = GripGraph()
    _seat_canonical_engagement(graph, tori, uke, EngineGripDepth.STANDARD)
    # Uke clamps a deep low-sleeve grip on tori — the catalog seoi_nage
    # entry has this as a disqualifier so Stage 1 returns empty.
    _seat(graph, "U", BodyPart.RIGHT_HAND, "T", GripTarget.LEFT_SLEEVE,
          GripTypeV2.SLEEVE_LOW, EngineGripDepth.DEEP)
    disqualifier = GripSpec(
        hand=GripHand.TORI_RIGHT,
        target_region=GripTargetRegion.UKE_SLEEVE_LOWER,
        minimum_depth=CatalogGripDepth.DEEP,
    )
    catalog = {"seoi_nage": _technique(
        "seoi_nage",
        _seoi_signature(uke_disqualifying=[disqualifier]),
        admissible=["any"],
    )}
    # Run many seeds; no scoring commit should ever fire.
    for seed in range(50):
        action = _run_try_commit(tori, uke, graph, catalog, seed=seed)
        if action is not None and action.kind.name == "COMMIT_THROW":
            # The false-attack path uses commit_motivation; only a
            # commit_motivation-tagged action is acceptable here.
            assert action.commit_motivation is not None, (
                "Stage-1-empty path produced an un-motivated scoring commit "
                "(HAJ-199 regression)"
            )


def test_try_commit_empty_catalog_blocks_all_commits() -> None:
    """An empty catalog (catalog_active but stage1 set is empty) must
    suppress the scoring-commit path."""
    tori = _judoka("T", vocabulary=[ThrowID.SEOI_NAGE], fight_iq=10)
    tori.capability.throw_profiles[ThrowID.SEOI_NAGE] = type(
        "P", (), {"effectiveness_dominant": 9, "effectiveness_off_side": 3}
    )()
    uke = _judoka("U")
    graph = GripGraph()
    _seat_canonical_engagement(graph, tori, uke, EngineGripDepth.STANDARD)
    for seed in range(20):
        action = _run_try_commit(tori, uke, graph, {}, seed=seed)
        if action is not None and action.kind.name == "COMMIT_THROW":
            assert action.commit_motivation is not None, (
                "Empty catalog should not allow un-motivated scoring commits"
            )


def test_legacy_path_unchanged_when_no_catalog_passed() -> None:
    """No catalog argument → legacy grip-presence-gate path runs and
    fires the throw."""
    from action_selection import _try_commit
    from actions import ActionKind
    import perception
    tori = _judoka("T", vocabulary=[ThrowID.SEOI_NAGE], fight_iq=10)
    tori.capability.throw_profiles[ThrowID.SEOI_NAGE] = type(
        "P", (), {"effectiveness_dominant": 9, "effectiveness_off_side": 3}
    )()
    uke = _judoka("U")
    graph = GripGraph()
    # Legacy SEOI_NAGE EdgeRequirement wants DEEP/HIGH_COLLAR on the
    # dominant hand AND STANDARD/PISTOL on the sleeve hand — match the
    # legacy throw spec exactly so evaluate_gate clears.
    _seat(graph, "T", BodyPart.RIGHT_HAND, "U", GripTarget.LEFT_LAPEL,
          GripTypeV2.LAPEL_HIGH, EngineGripDepth.DEEP)
    _seat(graph, "T", BodyPart.LEFT_HAND, "U", GripTarget.RIGHT_SLEEVE,
          GripTypeV2.SLEEVE_HIGH, EngineGripDepth.STANDARD)
    real_actual = perception.actual_signature_match
    real_perceive = perception.perceive
    from action_selection import COMMIT_THRESHOLD
    perception.actual_signature_match = lambda *a, **kw: COMMIT_THRESHOLD + 0.10
    perception.perceive = lambda actual, *a, **kw: actual
    try:
        action = _try_commit(
            tori, uke, graph, random.Random(0),
            # catalog defaulted to None → legacy path.
        )
    finally:
        perception.actual_signature_match = real_actual
        perception.perceive = real_perceive
    assert action is not None
    assert action.kind == ActionKind.COMMIT_THROW
    assert action.throw_id == ThrowID.SEOI_NAGE


if __name__ == "__main__":
    for n, fn in list(globals().items()):
        if n.startswith("test_") and callable(fn):
            fn()
            print(f"PASS  {n}")
