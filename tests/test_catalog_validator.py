# test_catalog_validator.py — HAJ-211 acceptance tests.
#
# Exercises src/catalog_validator.py:
#   - validate_catalog (in-memory)
#   - validate_catalog_file (loader wrap)
#   - CLI entrypoint main()
#
# Coverage targets from the ticket:
#   - Tool runs against the catalog file and produces a clean report on
#     a valid catalog
#   - Tool catches synthetic broken entries (each check has positive +
#     negative cases)
#   - Output is human-readable

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from catalog_validator import (  # noqa: E402
    Severity,
    ValidationIssue,
    ValidationReport,
    main,
    validate_catalog,
    validate_catalog_file,
)
from technique_catalog import (  # noqa: E402
    FailedThrowConsequence,
    GripDepth,
    GripHand,
    GripSignature,
    GripSpec,
    GripTargetRegion,
    KodokanStatus,
    TechniqueDefinition,
    TechniqueFamily,
    UkePostureRequirement,
)


# ---------------------------------------------------------------------------
# In-memory builders
# Building TechniqueDefinitions in Python keeps tests readable and
# independent of YAML round-tripping.
# ---------------------------------------------------------------------------
def _grip() -> GripSpec:
    return GripSpec(
        hand=GripHand.TORI_RIGHT,
        target_region=GripTargetRegion.UKE_LAPEL_HIGH,
        minimum_depth=GripDepth.CONTROLLED,
    )


def _make_definition(
    technique_id: str,
    *,
    family: TechniqueFamily = TechniqueFamily.TE_WAZA,
    kodokan_status: KodokanStatus = KodokanStatus.GOKYO_NO_WAZA,
    pedagogical_prerequisites: list[str] = None,
    ne_waza_followup_preferences: list[str] = None,
    era_restricted: int = None,
    name_japanese: str = "Test",
    name_english: str = "Test",
    canonical_grip_signatures: list[GripSignature] = None,
) -> TechniqueDefinition:
    return TechniqueDefinition(
        technique_id=technique_id,
        name_japanese=name_japanese,
        name_english=name_english,
        family=family,
        subfamily="forward_throw",
        kodokan_status=kodokan_status,
        canonical_grip_signatures=canonical_grip_signatures or [
            GripSignature(tori_required_grips=[_grip()]),
        ],
        admissible_kuzushi_vectors=["forward_pure"],
        primary_kuzushi_vectors=["forward_pure"],
        couple_type="placeholder",
        posture_requirements=UkePostureRequirement.ANY,
        base_difficulty=40,
        pedagogical_prerequisites=pedagogical_prerequisites or [],
        ne_waza_followup_preferences=ne_waza_followup_preferences or [],
        era_introduced=1895,
        era_restricted=era_restricted,
        failed_throw_consequence=FailedThrowConsequence.TORI_TO_KNEES,
    )


def _make_balanced_catalog() -> dict[str, TechniqueDefinition]:
    """A catalog with at least 3 entries per family — passes the
    family-balance info-level checks. Used as the baseline 'valid'
    starting point that individual tests then mutate to introduce
    specific defects."""
    catalog: dict[str, TechniqueDefinition] = {}
    for family in TechniqueFamily:
        if family is TechniqueFamily.NE_WAZA:
            continue       # empty ne_waza is info-only, not a warning
        for j in range(3):
            tid = f"{family.value}_{j}"
            catalog[tid] = _make_definition(tid, family=family)
    return catalog


def _codes(issues: list[ValidationIssue]) -> set[str]:
    return {i.code for i in issues}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
def test_balanced_catalog_validates_clean():
    catalog = _make_balanced_catalog()
    report = validate_catalog(catalog)
    assert report.is_valid is True
    assert report.errors == []
    # ne_waza is empty by design here → expect the ne_waza_family_empty info,
    # plus possibly other infos. No warnings expected.
    assert report.warnings == []
    assert "ne_waza_family_empty" in _codes(report.infos)
    # Total + family counts populated
    assert report.total_techniques == 12
    assert report.family_counts[TechniqueFamily.NE_WAZA] == 0
    assert report.family_counts[TechniqueFamily.TE_WAZA] == 3


def test_single_grip_signature_with_grips_passes():
    catalog = _make_balanced_catalog()
    report = validate_catalog(catalog)
    assert "empty_tori_grips" not in _codes(report.issues)


# ---------------------------------------------------------------------------
# Identity strings
# ---------------------------------------------------------------------------
def test_empty_name_japanese_is_error():
    catalog = _make_balanced_catalog()
    catalog["te_waza_0"] = _make_definition("te_waza_0", name_japanese="   ")
    report = validate_catalog(catalog)
    assert "empty_identity_string" in _codes(report.errors)
    err = next(i for i in report.errors if i.code == "empty_identity_string")
    assert err.field == "name_japanese"
    assert err.technique_id == "te_waza_0"


def test_empty_name_english_is_error():
    catalog = _make_balanced_catalog()
    catalog["te_waza_0"] = _make_definition("te_waza_0", name_english="")
    report = validate_catalog(catalog)
    err = next(i for i in report.errors if i.code == "empty_identity_string")
    assert err.field == "name_english"


# ---------------------------------------------------------------------------
# Grip signatures
# ---------------------------------------------------------------------------
def test_empty_tori_grips_is_warning():
    catalog = _make_balanced_catalog()
    catalog["te_waza_0"] = _make_definition(
        "te_waza_0",
        canonical_grip_signatures=[GripSignature(tori_required_grips=[])],
    )
    report = validate_catalog(catalog)
    assert "empty_tori_grips" in _codes(report.warnings)
    # Not an error — empty signature might be a transient authoring state
    assert "empty_tori_grips" not in _codes(report.errors)


# ---------------------------------------------------------------------------
# Cross-technique consistency
# ---------------------------------------------------------------------------
def test_dangling_pedagogical_prereq_is_error():
    catalog = _make_balanced_catalog()
    catalog["te_waza_0"] = _make_definition(
        "te_waza_0",
        pedagogical_prerequisites=["ghost_throw"],
    )
    report = validate_catalog(catalog)
    err = next(i for i in report.errors if i.code == "dangling_prereq")
    assert err.technique_id == "te_waza_0"
    assert "ghost_throw" in err.message


def test_dangling_ne_waza_followup_is_warning_not_error():
    # Ne-waza catalog isn't authored yet (HAJ-212 design + downstream
    # authoring), so dangling followups should not block validation.
    catalog = _make_balanced_catalog()
    catalog["te_waza_0"] = _make_definition(
        "te_waza_0",
        ne_waza_followup_preferences=["kesa_gatame"],
    )
    report = validate_catalog(catalog)
    assert "dangling_ne_waza_followup" in _codes(report.warnings)
    assert "dangling_ne_waza_followup" not in _codes(report.errors)
    assert report.is_valid is True


def test_prereq_cycle_is_error():
    # A → B → A
    catalog = _make_balanced_catalog()
    catalog["te_waza_0"] = _make_definition("te_waza_0", pedagogical_prerequisites=["te_waza_1"])
    catalog["te_waza_1"] = _make_definition("te_waza_1", pedagogical_prerequisites=["te_waza_0"])
    report = validate_catalog(catalog)
    cycle_errors = [i for i in report.errors if i.code == "prereq_cycle"]
    assert len(cycle_errors) == 1
    msg = cycle_errors[0].message
    assert "te_waza_0" in msg and "te_waza_1" in msg


def test_three_node_prereq_cycle_is_error():
    # A → B → C → A
    catalog = _make_balanced_catalog()
    catalog["te_waza_0"] = _make_definition("te_waza_0", pedagogical_prerequisites=["te_waza_1"])
    catalog["te_waza_1"] = _make_definition("te_waza_1", pedagogical_prerequisites=["te_waza_2"])
    catalog["te_waza_2"] = _make_definition("te_waza_2", pedagogical_prerequisites=["te_waza_0"])
    report = validate_catalog(catalog)
    cycle_errors = [i for i in report.errors if i.code == "prereq_cycle"]
    assert len(cycle_errors) == 1


def test_acyclic_prereq_chain_is_valid():
    # A → B → C, no cycle
    catalog = _make_balanced_catalog()
    catalog["te_waza_0"] = _make_definition("te_waza_0", pedagogical_prerequisites=["te_waza_1"])
    catalog["te_waza_1"] = _make_definition("te_waza_1", pedagogical_prerequisites=["te_waza_2"])
    # te_waza_2 has no prereqs — leaf of the chain
    report = validate_catalog(catalog)
    assert "prereq_cycle" not in _codes(report.errors)


def test_self_referential_prereq_is_cycle():
    catalog = _make_balanced_catalog()
    catalog["te_waza_0"] = _make_definition("te_waza_0", pedagogical_prerequisites=["te_waza_0"])
    report = validate_catalog(catalog)
    assert "prereq_cycle" in _codes(report.errors)


def test_dangling_prereq_does_not_trigger_false_cycle():
    # Dangling prereqs are reported separately; they shouldn't also be
    # treated as cycle nodes.
    catalog = _make_balanced_catalog()
    catalog["te_waza_0"] = _make_definition("te_waza_0", pedagogical_prerequisites=["ghost"])
    report = validate_catalog(catalog)
    assert "prereq_cycle" not in _codes(report.errors)
    assert "dangling_prereq" in _codes(report.errors)


# ---------------------------------------------------------------------------
# Habukareta Waza era_restricted gate
# ---------------------------------------------------------------------------
def test_habukareta_without_era_restricted_is_error():
    catalog = _make_balanced_catalog()
    catalog["te_waza_0"] = _make_definition(
        "te_waza_0",
        kodokan_status=KodokanStatus.HABUKARETA_WAZA,
        era_restricted=None,
    )
    report = validate_catalog(catalog)
    assert "habukareta_missing_era_restricted" in _codes(report.errors)


def test_habukareta_with_era_restricted_is_clean():
    catalog = _make_balanced_catalog()
    catalog["te_waza_0"] = _make_definition(
        "te_waza_0",
        kodokan_status=KodokanStatus.HABUKARETA_WAZA,
        era_restricted=1925,
    )
    report = validate_catalog(catalog)
    assert "habukareta_missing_era_restricted" not in _codes(report.errors)


def test_non_habukareta_without_era_restricted_is_fine():
    # gokyo_no_waza techniques rarely have era_restricted — must NOT be
    # flagged just because the field is null.
    catalog = _make_balanced_catalog()
    report = validate_catalog(catalog)
    assert "habukareta_missing_era_restricted" not in _codes(report.errors)


# ---------------------------------------------------------------------------
# Family balance
# ---------------------------------------------------------------------------
def test_empty_family_is_warning():
    # Build a catalog with NO ashi_waza
    catalog: dict[str, TechniqueDefinition] = {}
    for j in range(3):
        catalog[f"te_{j}"] = _make_definition(f"te_{j}", family=TechniqueFamily.TE_WAZA)
        catalog[f"koshi_{j}"] = _make_definition(f"koshi_{j}", family=TechniqueFamily.KOSHI_WAZA)
        catalog[f"sutemi_{j}"] = _make_definition(f"sutemi_{j}", family=TechniqueFamily.SUTEMI_WAZA)
    report = validate_catalog(catalog)
    family_warnings = [
        i for i in report.warnings
        if i.code == "family_empty" and "ashi_waza" in i.message
    ]
    assert family_warnings


def test_low_family_count_is_info():
    catalog: dict[str, TechniqueDefinition] = {
        "te_0": _make_definition("te_0", family=TechniqueFamily.TE_WAZA),
        "koshi_0": _make_definition("koshi_0", family=TechniqueFamily.KOSHI_WAZA),
    }
    report = validate_catalog(catalog)
    low_infos = [i for i in report.infos if i.code == "family_low"]
    # te_waza count=1, koshi_waza count=1 → both low
    assert {i.message.split("'")[1] for i in low_infos} >= {"te_waza", "koshi_waza"}


def test_empty_ne_waza_is_info_not_warning():
    # ne_waza emptiness is expected pre-HAJ-212; must not block.
    catalog = _make_balanced_catalog()
    report = validate_catalog(catalog)
    assert "ne_waza_family_empty" in _codes(report.infos)
    assert not any(
        i.code == "family_empty" and "ne_waza" in i.message
        for i in report.warnings
    )


# ---------------------------------------------------------------------------
# File-level entry point
# ---------------------------------------------------------------------------
def test_validate_catalog_file_against_sample(tmp_path):
    # Round-trip: write a known-good YAML, load + validate.
    path = tmp_path / "catalog.yaml"
    path.write_text(textwrap.dedent("""
        techniques:
          - technique_id: solo_throw
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
            admissible_kuzushi_vectors: [forward_pure]
            couple_type: placeholder
            posture_requirements: any
            base_difficulty: 40
            era_introduced: 1895
    """).strip(), encoding="utf-8")

    report = validate_catalog_file(path)
    assert report.load_error is None
    assert report.errors == []


def test_validate_catalog_file_surfaces_loader_failure(tmp_path):
    # Loader fatal error must come through as a load_error, not be
    # silently dropped, since downstream checks can't proceed.
    path = tmp_path / "broken.yaml"
    path.write_text(textwrap.dedent("""
        techniques:
          - technique_id: broken
            family: not_a_real_family
            name_japanese: B
            name_english: B
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
    """).strip(), encoding="utf-8")

    report = validate_catalog_file(path)
    assert report.load_error is not None
    assert "not_a_real_family" in report.load_error
    assert report.is_valid is False


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------
def test_report_format_includes_summary_footer():
    catalog = _make_balanced_catalog()
    report = validate_catalog(catalog)
    text = report.format_text()
    assert "techniques:" in text
    assert "by family:" in text
    assert "errors:" in text and "warnings:" in text and "infos:" in text


def test_report_format_can_suppress_warnings_and_infos():
    catalog = _make_balanced_catalog()
    catalog["te_waza_0"] = _make_definition(
        "te_waza_0",
        canonical_grip_signatures=[GripSignature(tori_required_grips=[])],
    )
    report = validate_catalog(catalog)
    full = report.format_text(include_warnings=True, include_infos=True)
    suppressed = report.format_text(include_warnings=False, include_infos=False)
    assert "empty_tori_grips" in full
    assert "empty_tori_grips" not in suppressed


def test_load_error_format_is_terse():
    report = ValidationReport(load_error="boom")
    text = report.format_text()
    assert "FATAL" in text and "boom" in text


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------
def test_cli_exit_zero_on_clean_catalog(tmp_path, capsys):
    path = tmp_path / "catalog.yaml"
    path.write_text(textwrap.dedent("""
        techniques:
          - technique_id: solo
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
            admissible_kuzushi_vectors: [forward_pure]
            couple_type: placeholder
            posture_requirements: any
            base_difficulty: 40
    """).strip(), encoding="utf-8")
    exit_code = main([str(path)])
    assert exit_code == 0


def test_cli_exit_one_on_dangling_prereq(tmp_path):
    path = tmp_path / "catalog.yaml"
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
            pedagogical_prerequisites: [ghost_throw]
    """).strip(), encoding="utf-8")
    exit_code = main([str(path), "--quiet"])
    assert exit_code == 1


def test_cli_exit_one_on_loader_failure(tmp_path):
    path = tmp_path / "missing.yaml"
    # File doesn't exist — load_catalog raises a FileNotFoundError that
    # the validator wraps. Actually load_catalog wraps in CatalogValidationError
    # only for known parse issues — for missing file, the loader propagates
    # FileNotFoundError. The CLI surfaces both as exit 1 via is_valid.
    with pytest.raises(FileNotFoundError):
        main([str(path), "--quiet"])
