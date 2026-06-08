# test_technique_catalog.py — HAJ-204 acceptance tests, revised under HAJ-213.
#
# Exercises src/technique_catalog.py against the hand-authored sample
# catalog (data/techniques.yaml) plus inline malformed fixtures.
#
# Coverage targets from HAJ-204 + HAJ-213:
#   - Dataclasses match Section 2 / Section 5 schema (v1.2)
#   - Loader reads YAML and returns dict[technique_id, definition]
#   - Loader handles missing optional fields gracefully
#   - Basic schema validation rejects malformed entries with clear errors
#   - All schema sections (identity, classification, grip signatures, kinetic
#     preconditions, difficulty, ne-waza, era) are exercised
#   - Multi-signature grip lists, mirror_eligible default + override
#   - admissible_kuzushi_vectors `any` wildcard and primary subset
#   - Naming overlay loader (including the empty file case)

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from technique_catalog import (
    AcquisitionSource,
    CatalogValidationError,
    CounterClass,
    CounterCommitWindow,
    FailedThrowConsequence,
    GripDepth,
    GripHand,
    GripSignature,
    GripSpec,
    GripTargetRegion,
    KodokanStatus,
    KUZUSHI_ANY_TOKEN,
    MechanicalClass,
    NamingType,
    PROFICIENCY_ORDER,
    ProficiencyTier,
    TechniqueDefinition,
    TechniqueFamily,
    TechniqueNamingOverlay,
    TechniqueRecord,
    UkePostureRequirement,
    load_catalog,
    load_naming_overlays,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_CATALOG = REPO_ROOT / "data" / "techniques.yaml"
SAMPLE_OVERLAYS = REPO_ROOT / "data" / "technique_naming_overlays.yaml"


# ---------------------------------------------------------------------------
# Dataclass shape — Section 2 + Section 5 schema
# ---------------------------------------------------------------------------
def test_proficiency_order_is_canonical():
    # Order matters — Section 3 names the eight tiers in ascending sequence.
    names = [tier.value for tier in PROFICIENCY_ORDER]
    assert names == [
        "known", "novice", "proficient", "intermediate",
        "competitive", "expert", "master", "legendary",
    ]


def test_technique_record_default_construction():
    record = TechniqueRecord(technique_id="uchi_mata")
    # Section 5 defaults: a fresh record sits at known with empty ledgers.
    assert record.proficiency_tier is ProficiencyTier.KNOWN
    assert record.teaching_tier is ProficiencyTier.KNOWN
    assert record.proficiency_progress == 0
    assert record.executed_attempts == 0
    assert record.executed_successes == 0
    assert record.executed_ippons == 0
    assert record.defended_attempts == 0
    assert record.defended_successes == 0
    assert record.defended_ippon_losses == 0
    assert record.source_of_acquisition is None
    assert record.year_acquired is None
    assert record.acquired_from is None
    assert record.last_used_year is None


def test_grip_signature_mirror_eligible_default():
    # Section 2 (v1.2): mirror_eligible defaults to True so authors record
    # only the canonical configuration; the engine handles lefty mirrors.
    sig = GripSignature()
    assert sig.mirror_eligible is True
    assert sig.tori_required_grips == []
    assert sig.uke_disqualifying_grips == []


def test_naming_overlay_round_trip_shape():
    overlay = TechniqueNamingOverlay(
        dojo_id="cranford_jkc",
        technique_id="uchi_mata",
        custom_name="Cranford's uchi-mata",
        named_by="sensei_yonezuka",
        year_named=1972,
        triggering_event="first_mastery",
        naming_type=NamingType.SENSEI,
    )
    assert overlay.parent_overlay is None
    assert overlay.naming_type is NamingType.SENSEI


# ---------------------------------------------------------------------------
# Loader against the hand-authored sample catalog
# ---------------------------------------------------------------------------
def test_load_sample_catalog_yaml():
    # End-to-end sanity check: real catalog loads, schema shape is intact.
    # Assertions pin schema/structure, not authoring content — content
    # drifts under HAJ-205 authoring (renames, kuzushi additions, base
    # difficulty recalibration) and shouldn't break this test.
    catalog = load_catalog(SAMPLE_CATALOG)
    assert {"deashi_harai", "uchi_mata", "osoto_gari", "seoi_nage", "tomoe_nage"}.issubset(catalog.keys())

    uchi = catalog["uchi_mata"]
    # Identity — Japanese name is canonical, English is authoring-fluid
    assert uchi.name_japanese == "Uchi-mata"
    assert uchi.name_english        # any non-empty string
    # Classification
    assert uchi.family is TechniqueFamily.KOSHI_WAZA
    assert uchi.subfamily == "forward_throw"
    assert uchi.kodokan_status is KodokanStatus.GOKYO_NO_WAZA
    # Stage 1 — grip signatures (list, populated)
    assert len(uchi.canonical_grip_signatures) >= 1
    sig = uchi.canonical_grip_signatures[0]
    assert sig.mirror_eligible is True
    assert len(sig.tori_required_grips) >= 2
    # Stage 2 — kinetic
    assert "forward_right_diagonal" in uchi.admissible_kuzushi_vectors
    assert uchi.primary_kuzushi_vectors        # populated (defaults to admissible)
    assert uchi.couple_type == "forward_rotation_about_hip_axis"
    assert uchi.posture_requirements is UkePostureRequirement.UPRIGHT_OR_FORWARD_COMPROMISED
    # Difficulty & pedagogy — bounds-check rather than pin
    assert 0 <= uchi.base_difficulty <= 100
    # Era
    assert uchi.era_introduced == 1895
    assert uchi.era_restricted is None


def test_gokyo_kyo_parses_when_present(tmp_path):
    path = tmp_path / "kyo.yaml"
    path.write_text(textwrap.dedent("""
        techniques:
          - technique_id: a
            name_japanese: A
            name_english: A
            family: te_waza
            subfamily: forward_throw
            kodokan_status: gokyo_no_waza
            canonical_grip_signatures:
              - tori_required_grips:
                  - hand: tori_right
                    target_region: uke_lapel_high
                    minimum_depth: controlled
            admissible_kuzushi_vectors: [forward_pure]
            couple_type: placeholder
            posture_requirements: any
            base_difficulty: 40
            gokyo_kyo: 2
    """).strip(), encoding="utf-8")
    catalog = load_catalog(path)
    assert catalog["a"].gokyo_kyo == 2


def test_gokyo_kyo_defaults_to_none(tmp_path):
    path = tmp_path / "no_kyo.yaml"
    path.write_text(textwrap.dedent("""
        techniques:
          - technique_id: a
            name_japanese: A
            name_english: A
            family: te_waza
            subfamily: forward_throw
            kodokan_status: shinmeisho_no_waza
            canonical_grip_signatures:
              - tori_required_grips:
                  - hand: tori_right
                    target_region: uke_lapel_high
                    minimum_depth: controlled
            admissible_kuzushi_vectors: [forward_pure]
            couple_type: placeholder
            posture_requirements: any
            base_difficulty: 40
    """).strip(), encoding="utf-8")
    catalog = load_catalog(path)
    assert catalog["a"].gokyo_kyo is None


def test_gokyo_kyo_out_of_range_is_rejected(tmp_path):
    path = tmp_path / "bad_kyo.yaml"
    path.write_text(textwrap.dedent("""
        techniques:
          - technique_id: a
            name_japanese: A
            name_english: A
            family: te_waza
            subfamily: forward_throw
            kodokan_status: gokyo_no_waza
            canonical_grip_signatures:
              - tori_required_grips:
                  - hand: tori_right
                    target_region: uke_lapel_high
                    minimum_depth: controlled
            admissible_kuzushi_vectors: [forward_pure]
            couple_type: placeholder
            posture_requirements: any
            base_difficulty: 40
            gokyo_kyo: 6
    """).strip(), encoding="utf-8")
    with pytest.raises(CatalogValidationError, match="gokyo_kyo"):
        load_catalog(path)


def test_sample_catalog_deashi_uses_any_wildcard():
    # Deashi-harai is the canonical omnidirectional foot sweep — admissible
    # is `any`, primary lists the forward-scoring directions. Pin the
    # wildcard semantics; let primary content drift under authoring.
    catalog = load_catalog(SAMPLE_CATALOG)
    deashi = catalog["deashi_harai"]
    assert deashi.admissible_kuzushi_vectors == [KUZUSHI_ANY_TOKEN]
    assert deashi.is_omnidirectional() is True
    assert "forward_right_diagonal" in deashi.primary_kuzushi_vectors
    assert "forward_left_diagonal" in deashi.primary_kuzushi_vectors


def test_load_sample_catalog_covers_each_family():
    catalog = load_catalog(SAMPLE_CATALOG)
    families = {definition.family for definition in catalog.values()}
    # Sample exercises four of the five families (ne_waza is HAJ-212 scope).
    assert TechniqueFamily.TE_WAZA in families
    assert TechniqueFamily.KOSHI_WAZA in families
    assert TechniqueFamily.ASHI_WAZA in families
    assert TechniqueFamily.SUTEMI_WAZA in families


# ---------------------------------------------------------------------------
# Optional-field handling
# ---------------------------------------------------------------------------
MINIMAL_YAML = textwrap.dedent("""
    techniques:
      - technique_id: minimal_throw
        name_japanese: Minimaru
        name_english: Minimal Throw
        family: te_waza
        subfamily: forward_throw
        kodokan_status: shinmeisho_no_waza
        canonical_grip_signatures:
          - tori_required_grips:
              - hand: tori_right
                target_region: uke_lapel_high
                minimum_depth: shallow
        admissible_kuzushi_vectors:
          - forward_pure
        couple_type: placeholder_couple
        posture_requirements: any
        base_difficulty: 40
""").strip()


def test_loader_accepts_minimal_entry_with_optional_fields_omitted(tmp_path):
    yaml_path = tmp_path / "minimal.yaml"
    yaml_path.write_text(MINIMAL_YAML, encoding="utf-8")

    catalog = load_catalog(yaml_path)
    definition = catalog["minimal_throw"]
    # Defaults must materialize cleanly when YAML omits optional sections.
    assert definition.pedagogical_prerequisites == []
    assert definition.minimum_belt_for_competition_use is None
    assert definition.failed_throw_consequence is None
    assert definition.ne_waza_followup_preferences == []
    assert definition.era_introduced is None
    assert definition.era_restricted is None
    sig = definition.canonical_grip_signatures[0]
    assert sig.uke_disqualifying_grips == []
    assert sig.mirror_eligible is True
    # primary defaults to admissible when omitted
    assert definition.primary_kuzushi_vectors == ["forward_pure"]


def test_loader_accepts_json_format(tmp_path):
    payload = {
        "techniques": [
            {
                "technique_id": "json_throw",
                "name_japanese": "Jeisonu",
                "name_english": "JSON Throw",
                "family": "te_waza",
                "subfamily": "forward_throw",
                "kodokan_status": "gokyo_no_waza",
                "canonical_grip_signatures": [
                    {
                        "tori_required_grips": [
                            {
                                "hand": "tori_right",
                                "target_region": "uke_lapel_high",
                                "minimum_depth": "controlled",
                            }
                        ]
                    }
                ],
                "admissible_kuzushi_vectors": ["forward_pure"],
                "couple_type": "placeholder",
                "posture_requirements": "any",
                "base_difficulty": 50,
            }
        ]
    }
    json_path = tmp_path / "catalog.json"
    json_path.write_text(json.dumps(payload), encoding="utf-8")

    catalog = load_catalog(json_path)
    assert "json_throw" in catalog
    assert catalog["json_throw"].base_difficulty == 50


# ---------------------------------------------------------------------------
# v1.2 schema — multi-signature lists, mirror_eligible, kuzushi any wildcard
# ---------------------------------------------------------------------------
def test_multi_signature_list_is_parsed(tmp_path):
    # Multi-entry signatures express genuinely distinct grip variants
    # (e.g., classic seoi-nage vs. one-handed seoi-nage).
    path = tmp_path / "multi_sig.yaml"
    path.write_text(textwrap.dedent("""
        techniques:
          - technique_id: variant_throw
            name_japanese: V
            name_english: V
            family: te_waza
            subfamily: forward_throw
            kodokan_status: gokyo_no_waza
            canonical_grip_signatures:
              - tori_required_grips:
                  - hand: tori_left
                    target_region: uke_sleeve_upper
                    minimum_depth: deep
                  - hand: tori_right
                    target_region: uke_lapel_high
                    minimum_depth: controlled
                mirror_eligible: true
              - tori_required_grips:
                  - hand: tori_right
                    target_region: uke_belt
                    minimum_depth: controlled
                mirror_eligible: false
            admissible_kuzushi_vectors: [forward_pure]
            couple_type: placeholder
            posture_requirements: any
            base_difficulty: 50
    """).strip(), encoding="utf-8")

    catalog = load_catalog(path)
    sigs = catalog["variant_throw"].canonical_grip_signatures
    assert len(sigs) == 2
    assert sigs[0].mirror_eligible is True
    assert sigs[1].mirror_eligible is False
    assert sigs[1].tori_required_grips[0].target_region is GripTargetRegion.UKE_BELT


def test_leg_grab_target_regions_load(tmp_path):
    # Hand-on-limb regions added for Shinmeisho leg-grab throws. Exercises
    # all three new enum values via a synthetic morote-gari-shaped entry.
    path = tmp_path / "leg_grab.yaml"
    path.write_text(textwrap.dedent("""
        techniques:
          - technique_id: leg_grab_probe
            name_japanese: L
            name_english: L
            family: te_waza
            subfamily: rear_throw
            kodokan_status: shinmeisho_no_waza
            canonical_grip_signatures:
              - tori_required_grips:
                  - hand: tori_left
                    target_region: uke_leg_outer
                    minimum_depth: controlled
                  - hand: tori_right
                    target_region: uke_leg_inner
                    minimum_depth: controlled
              - tori_required_grips:
                  - hand: tori_right
                    target_region: uke_heel
                    minimum_depth: controlled
            admissible_kuzushi_vectors: [rear_pure]
            couple_type: placeholder
            posture_requirements: any
            base_difficulty: 50
    """).strip(), encoding="utf-8")

    sigs = load_catalog(path)["leg_grab_probe"].canonical_grip_signatures
    assert sigs[0].tori_required_grips[0].target_region is GripTargetRegion.UKE_LEG_OUTER
    assert sigs[0].tori_required_grips[1].target_region is GripTargetRegion.UKE_LEG_INNER
    assert sigs[1].tori_required_grips[0].target_region is GripTargetRegion.UKE_HEEL


def test_primary_kuzushi_can_be_explicit_subset(tmp_path):
    path = tmp_path / "primary.yaml"
    path.write_text(textwrap.dedent("""
        techniques:
          - technique_id: subset_throw
            name_japanese: S
            name_english: S
            family: te_waza
            subfamily: forward_throw
            kodokan_status: gokyo_no_waza
            canonical_grip_signatures:
              - tori_required_grips:
                  - hand: tori_right
                    target_region: uke_lapel_high
                    minimum_depth: controlled
            admissible_kuzushi_vectors:
              - forward_pure
              - forward_right_diagonal
              - forward_left_diagonal
            primary_kuzushi_vectors:
              - forward_pure
            couple_type: placeholder
            posture_requirements: any
            base_difficulty: 50
    """).strip(), encoding="utf-8")

    definition = load_catalog(path)["subset_throw"]
    assert definition.primary_kuzushi_vectors == ["forward_pure"]
    assert len(definition.admissible_kuzushi_vectors) == 3


def test_kuzushi_any_wildcard_as_scalar(tmp_path):
    # `admissible_kuzushi_vectors: any` (scalar) is the canonical compact form.
    path = tmp_path / "any.yaml"
    path.write_text(textwrap.dedent("""
        techniques:
          - technique_id: omni_throw
            name_japanese: O
            name_english: O
            family: ashi_waza
            subfamily: forward_throw
            kodokan_status: gokyo_no_waza
            canonical_grip_signatures:
              - tori_required_grips:
                  - hand: tori_right
                    target_region: uke_lapel_high
                    minimum_depth: controlled
            admissible_kuzushi_vectors: any
            couple_type: placeholder
            posture_requirements: any
            base_difficulty: 50
    """).strip(), encoding="utf-8")

    definition = load_catalog(path)["omni_throw"]
    assert definition.is_omnidirectional() is True
    assert definition.admissible_kuzushi_vectors == [KUZUSHI_ANY_TOKEN]
    # primary defaults to a copy of admissible — keeps the wildcard sentinel
    assert definition.primary_kuzushi_vectors == [KUZUSHI_ANY_TOKEN]


# ---------------------------------------------------------------------------
# HAJ-214 — counter-throw fields
# ---------------------------------------------------------------------------
def _counter_yaml(counter_block: str) -> str:
    """A counter-shaped technique with the given trailing counter_block lines.

    `counter_block` is dedented then re-indented to the entry's field column
    (4 spaces) so callers can write it at any source indentation.
    """
    base = textwrap.dedent("""
        techniques:
          - technique_id: a_counter
            name_japanese: C
            name_english: C
            family: koshi_waza
            subfamily: rear_throw
            kodokan_status: shinmeisho_no_waza
            canonical_grip_signatures:
              - tori_required_grips:
                  - hand: tori_right
                    target_region: uke_lapel_high
                    minimum_depth: controlled
            admissible_kuzushi_vectors: [forward_pure]
            couple_type: placeholder
            posture_requirements: upright_or_forward_compromised
            base_difficulty: 75
    """).strip()
    block = "\n".join(
        ("    " + line) if line.strip() else line
        for line in textwrap.dedent(counter_block).strip().splitlines()
    )
    return base + "\n" + block


def test_counter_fields_parse_with_scalar_class(tmp_path):
    path = tmp_path / "counter.yaml"
    path.write_text(_counter_yaml("""
        fires_as_counter: true
        counter_class: kaeshi
        counter_window: turn_in
        counter_against_mechanical_class: hip_throw_forward
    """), encoding="utf-8")
    d = load_catalog(path)["a_counter"]
    assert d.fires_as_counter is True
    assert d.counter_class is CounterClass.KAESHI
    assert d.counter_window is CounterCommitWindow.TURN_IN
    # Scalar normalises to a single-element list (mirrors admissible kuzushi).
    assert d.counter_against_mechanical_class == [MechanicalClass.HIP_THROW_FORWARD]


def test_counter_against_accepts_list(tmp_path):
    # yoko-wakare counters both a hip throw and a shoulder throw.
    path = tmp_path / "counter_list.yaml"
    path.write_text(_counter_yaml("""
        fires_as_counter: true
        counter_class: sukashi
        counter_window: turn_in
        counter_against_mechanical_class:
          - hip_throw_forward
          - shoulder_throw_forward
    """), encoding="utf-8")
    d = load_catalog(path)["a_counter"]
    assert d.counter_against_mechanical_class == [
        MechanicalClass.HIP_THROW_FORWARD,
        MechanicalClass.SHOULDER_THROW_FORWARD,
    ]


def test_counter_fields_default_when_omitted(tmp_path):
    # A primary attack omits all four fields and stays valid.
    path = tmp_path / "primary.yaml"
    path.write_text(MINIMAL_YAML, encoding="utf-8")
    d = load_catalog(path)["minimal_throw"]
    assert d.fires_as_counter is False
    assert d.counter_class is None
    assert d.counter_window is None
    assert d.counter_against_mechanical_class == []


def test_invalid_counter_class_is_rejected(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(_counter_yaml("""
        fires_as_counter: true
        counter_class: bogus_class
        counter_window: turn_in
        counter_against_mechanical_class: hip_throw_forward
    """), encoding="utf-8")
    with pytest.raises(CatalogValidationError, match="bogus_class"):
        load_catalog(path)


def test_invalid_counter_window_is_rejected(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(_counter_yaml("""
        fires_as_counter: true
        counter_class: kaeshi
        counter_window: mid_air_backflip
        counter_against_mechanical_class: hip_throw_forward
    """), encoding="utf-8")
    with pytest.raises(CatalogValidationError, match="mid_air_backflip"):
        load_catalog(path)


def test_invalid_counter_against_mechanical_class_is_rejected(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(_counter_yaml("""
        fires_as_counter: true
        counter_class: kaeshi
        counter_window: turn_in
        counter_against_mechanical_class: spinning_pile_driver
    """), encoding="utf-8")
    with pytest.raises(CatalogValidationError, match="spinning_pile_driver"):
        load_catalog(path)


def test_empty_counter_against_list_is_rejected(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(_counter_yaml("""
        fires_as_counter: true
        counter_class: kaeshi
        counter_window: turn_in
        counter_against_mechanical_class: []
    """), encoding="utf-8")
    with pytest.raises(CatalogValidationError, match="counter_against_mechanical_class"):
        load_catalog(path)


def test_non_boolean_fires_as_counter_is_rejected(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(_counter_yaml("""
        fires_as_counter: "yes"
    """), encoding="utf-8")
    with pytest.raises(CatalogValidationError, match="fires_as_counter"):
        load_catalog(path)


def test_sample_catalog_counter_entries_load():
    # The authored Shinmeisho/Gokyo counters carry the HAJ-214 fields; the
    # split makikomi entries coexist (proactive + counter).
    catalog = load_catalog(SAMPLE_CATALOG)

    sukashi = catalog["uchi_mata_sukashi"]
    assert sukashi.fires_as_counter is True
    assert sukashi.counter_class is CounterClass.SUKASHI
    assert sukashi.counter_window is CounterCommitWindow.TURN_IN
    assert MechanicalClass.HIP_THROW_FORWARD in sukashi.counter_against_mechanical_class

    # uchi-mata-gaeshi keys off the stuffed-completion window, contrasting with
    # uchi-mata-sukashi's turn-in void (the design-doc distinction).
    assert catalog["uchi_mata_gaeshi"].counter_window is CounterCommitWindow.STUFFED_COMPLETION

    # Dual-use makikomi is split: proactive entry is a primary attack.
    assert catalog["osoto_makikomi"].fires_as_counter is False
    counter = catalog["osoto_makikomi_counter"]
    assert counter.fires_as_counter is True
    assert counter.counter_class is CounterClass.MAKIKOMI_WRAPAROUND


# ---------------------------------------------------------------------------
# Validation — malformed entries raise CatalogValidationError with context
# ---------------------------------------------------------------------------
def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "broken.yaml"
    path.write_text(textwrap.dedent(body).strip(), encoding="utf-8")
    return path


def test_missing_required_field_is_rejected(tmp_path):
    path = _write(tmp_path, """
        techniques:
          - technique_id: broken
            # name_japanese intentionally missing
            name_english: Broken
            family: te_waza
            subfamily: forward_throw
            kodokan_status: gokyo_no_waza
            canonical_grip_signatures:
              - tori_required_grips:
                  - hand: tori_right
                    target_region: uke_lapel_high
                    minimum_depth: controlled
            admissible_kuzushi_vectors: [forward_pure]
            couple_type: placeholder
            posture_requirements: any
            base_difficulty: 40
    """)
    with pytest.raises(CatalogValidationError, match="name_japanese"):
        load_catalog(path)


def test_invalid_family_enum_is_rejected(tmp_path):
    path = _write(tmp_path, """
        techniques:
          - technique_id: broken
            name_japanese: B
            name_english: B
            family: not_a_real_family
            subfamily: forward_throw
            kodokan_status: gokyo_no_waza
            canonical_grip_signatures:
              - tori_required_grips:
                  - hand: tori_right
                    target_region: uke_lapel_high
                    minimum_depth: controlled
            admissible_kuzushi_vectors: [forward_pure]
            couple_type: placeholder
            posture_requirements: any
            base_difficulty: 40
    """)
    with pytest.raises(CatalogValidationError, match="not_a_real_family"):
        load_catalog(path)


def test_invalid_grip_depth_is_rejected(tmp_path):
    path = _write(tmp_path, """
        techniques:
          - technique_id: broken
            name_japanese: B
            name_english: B
            family: te_waza
            subfamily: forward_throw
            kodokan_status: gokyo_no_waza
            canonical_grip_signatures:
              - tori_required_grips:
                  - hand: tori_right
                    target_region: uke_lapel_high
                    minimum_depth: featherlight
            admissible_kuzushi_vectors: [forward_pure]
            couple_type: placeholder
            posture_requirements: any
            base_difficulty: 40
    """)
    with pytest.raises(CatalogValidationError, match="featherlight"):
        load_catalog(path)


def test_empty_grip_signatures_list_is_rejected(tmp_path):
    path = _write(tmp_path, """
        techniques:
          - technique_id: broken
            name_japanese: B
            name_english: B
            family: te_waza
            subfamily: forward_throw
            kodokan_status: gokyo_no_waza
            canonical_grip_signatures: []
            admissible_kuzushi_vectors: [forward_pure]
            couple_type: placeholder
            posture_requirements: any
            base_difficulty: 40
    """)
    with pytest.raises(CatalogValidationError, match="canonical_grip_signatures"):
        load_catalog(path)


def test_non_boolean_mirror_eligible_is_rejected(tmp_path):
    path = _write(tmp_path, """
        techniques:
          - technique_id: broken
            name_japanese: B
            name_english: B
            family: te_waza
            subfamily: forward_throw
            kodokan_status: gokyo_no_waza
            canonical_grip_signatures:
              - tori_required_grips:
                  - hand: tori_right
                    target_region: uke_lapel_high
                    minimum_depth: controlled
                mirror_eligible: "yes"
            admissible_kuzushi_vectors: [forward_pure]
            couple_type: placeholder
            posture_requirements: any
            base_difficulty: 40
    """)
    with pytest.raises(CatalogValidationError, match="mirror_eligible"):
        load_catalog(path)


def test_unknown_kuzushi_direction_is_rejected(tmp_path):
    path = _write(tmp_path, """
        techniques:
          - technique_id: broken
            name_japanese: B
            name_english: B
            family: te_waza
            subfamily: forward_throw
            kodokan_status: gokyo_no_waza
            canonical_grip_signatures:
              - tori_required_grips:
                  - hand: tori_right
                    target_region: uke_lapel_high
                    minimum_depth: controlled
            admissible_kuzushi_vectors: [sideways_corkscrew]
            couple_type: placeholder
            posture_requirements: any
            base_difficulty: 40
    """)
    with pytest.raises(CatalogValidationError, match="sideways_corkscrew"):
        load_catalog(path)


def test_any_wildcard_cannot_combine_with_explicit_directions(tmp_path):
    path = _write(tmp_path, """
        techniques:
          - technique_id: broken
            name_japanese: B
            name_english: B
            family: te_waza
            subfamily: forward_throw
            kodokan_status: gokyo_no_waza
            canonical_grip_signatures:
              - tori_required_grips:
                  - hand: tori_right
                    target_region: uke_lapel_high
                    minimum_depth: controlled
            admissible_kuzushi_vectors: [any, forward_pure]
            couple_type: placeholder
            posture_requirements: any
            base_difficulty: 40
    """)
    with pytest.raises(CatalogValidationError, match="wildcard"):
        load_catalog(path)


def test_primary_kuzushi_not_in_admissible_is_rejected(tmp_path):
    path = _write(tmp_path, """
        techniques:
          - technique_id: broken
            name_japanese: B
            name_english: B
            family: te_waza
            subfamily: forward_throw
            kodokan_status: gokyo_no_waza
            canonical_grip_signatures:
              - tori_required_grips:
                  - hand: tori_right
                    target_region: uke_lapel_high
                    minimum_depth: controlled
            admissible_kuzushi_vectors: [forward_pure]
            primary_kuzushi_vectors: [rear_pure]
            couple_type: placeholder
            posture_requirements: any
            base_difficulty: 40
    """)
    with pytest.raises(CatalogValidationError, match="not in admissible"):
        load_catalog(path)


def test_primary_kuzushi_cannot_contain_any_wildcard(tmp_path):
    path = _write(tmp_path, """
        techniques:
          - technique_id: broken
            name_japanese: B
            name_english: B
            family: te_waza
            subfamily: forward_throw
            kodokan_status: gokyo_no_waza
            canonical_grip_signatures:
              - tori_required_grips:
                  - hand: tori_right
                    target_region: uke_lapel_high
                    minimum_depth: controlled
            admissible_kuzushi_vectors: any
            primary_kuzushi_vectors: [any]
            couple_type: placeholder
            posture_requirements: any
            base_difficulty: 40
    """)
    with pytest.raises(CatalogValidationError, match="primary_kuzushi_vectors"):
        load_catalog(path)


def test_base_difficulty_out_of_range_is_rejected(tmp_path):
    path = _write(tmp_path, """
        techniques:
          - technique_id: broken
            name_japanese: B
            name_english: B
            family: te_waza
            subfamily: forward_throw
            kodokan_status: gokyo_no_waza
            canonical_grip_signatures:
              - tori_required_grips:
                  - hand: tori_right
                    target_region: uke_lapel_high
                    minimum_depth: controlled
            admissible_kuzushi_vectors: [forward_pure]
            couple_type: placeholder
            posture_requirements: any
            base_difficulty: 250
    """)
    with pytest.raises(CatalogValidationError, match="base_difficulty"):
        load_catalog(path)


def test_implausible_era_year_is_rejected(tmp_path):
    path = _write(tmp_path, """
        techniques:
          - technique_id: broken
            name_japanese: B
            name_english: B
            family: te_waza
            subfamily: forward_throw
            kodokan_status: gokyo_no_waza
            canonical_grip_signatures:
              - tori_required_grips:
                  - hand: tori_right
                    target_region: uke_lapel_high
                    minimum_depth: controlled
            admissible_kuzushi_vectors: [forward_pure]
            couple_type: placeholder
            posture_requirements: any
            base_difficulty: 40
            era_introduced: 1492
    """)
    with pytest.raises(CatalogValidationError, match="era_introduced"):
        load_catalog(path)


def test_era_restricted_before_introduced_is_rejected(tmp_path):
    path = _write(tmp_path, """
        techniques:
          - technique_id: broken
            name_japanese: B
            name_english: B
            family: te_waza
            subfamily: forward_throw
            kodokan_status: gokyo_no_waza
            canonical_grip_signatures:
              - tori_required_grips:
                  - hand: tori_right
                    target_region: uke_lapel_high
                    minimum_depth: controlled
            admissible_kuzushi_vectors: [forward_pure]
            couple_type: placeholder
            posture_requirements: any
            base_difficulty: 40
            era_introduced: 1950
            era_restricted: 1940
    """)
    with pytest.raises(CatalogValidationError, match="era_restricted"):
        load_catalog(path)


def test_duplicate_technique_id_is_rejected(tmp_path):
    path = _write(tmp_path, """
        techniques:
          - technique_id: dup
            name_japanese: A
            name_english: A
            family: te_waza
            subfamily: forward_throw
            kodokan_status: gokyo_no_waza
            canonical_grip_signatures:
              - tori_required_grips:
                  - hand: tori_right
                    target_region: uke_lapel_high
                    minimum_depth: controlled
            admissible_kuzushi_vectors: [forward_pure]
            couple_type: placeholder
            posture_requirements: any
            base_difficulty: 40
          - technique_id: dup
            name_japanese: B
            name_english: B
            family: te_waza
            subfamily: forward_throw
            kodokan_status: gokyo_no_waza
            canonical_grip_signatures:
              - tori_required_grips:
                  - hand: tori_right
                    target_region: uke_lapel_high
                    minimum_depth: controlled
            admissible_kuzushi_vectors: [forward_pure]
            couple_type: placeholder
            posture_requirements: any
            base_difficulty: 40
    """)
    with pytest.raises(CatalogValidationError, match="duplicate"):
        load_catalog(path)


def test_unsupported_extension_is_rejected(tmp_path):
    path = tmp_path / "catalog.txt"
    path.write_text("anything", encoding="utf-8")
    with pytest.raises(CatalogValidationError, match="extension"):
        load_catalog(path)


# ---------------------------------------------------------------------------
# Naming overlay loader
# ---------------------------------------------------------------------------
def test_load_empty_overlay_file_returns_empty_dict():
    overlays = load_naming_overlays(SAMPLE_OVERLAYS)
    assert overlays == {}


def test_load_missing_overlay_path_returns_empty_dict(tmp_path):
    # Per Section 2 — a freshly seeded world ships with no overlays; the
    # file may not yet exist.
    overlays = load_naming_overlays(tmp_path / "does_not_exist.yaml")
    assert overlays == {}


def test_load_overlay_with_entries(tmp_path):
    path = tmp_path / "overlays.yaml"
    path.write_text(textwrap.dedent("""
        overlays:
          - dojo_id: cranford_jkc
            technique_id: uchi_mata
            custom_name: Cranford's uchi-mata
            named_by: sensei_yonezuka
            year_named: 1972
            triggering_event: first_mastery
            naming_type: sensei
          - dojo_id: newark_judo
            technique_id: uchi_mata
            custom_name: The Dynamite Blast
            named_by: judoka_okada
            year_named: 1981
            triggering_event: legendary_use_in_competition
            naming_type: free_text
            parent_overlay:
              dojo_id: cranford_jkc
              technique_id: uchi_mata
    """).strip(), encoding="utf-8")

    overlays = load_naming_overlays(path)
    assert set(overlays.keys()) == {
        ("cranford_jkc", "uchi_mata"),
        ("newark_judo", "uchi_mata"),
    }
    inherited = overlays[("newark_judo", "uchi_mata")]
    assert inherited.parent_overlay == ("cranford_jkc", "uchi_mata")
    assert inherited.naming_type is NamingType.FREE_TEXT


def test_duplicate_overlay_key_is_rejected(tmp_path):
    path = tmp_path / "overlays.yaml"
    path.write_text(textwrap.dedent("""
        overlays:
          - dojo_id: d
            technique_id: t
            custom_name: A
            named_by: x
            year_named: 1970
            triggering_event: first_mastery
          - dojo_id: d
            technique_id: t
            custom_name: B
            named_by: x
            year_named: 1971
            triggering_event: first_mastery
    """).strip(), encoding="utf-8")
    with pytest.raises(CatalogValidationError, match="duplicate"):
        load_naming_overlays(path)
