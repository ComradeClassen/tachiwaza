# test_ne_waza_catalog.py — HAJ-215 loader + validator acceptance tests.
#
# Covers (per ticket §Tests):
#   - Loader: valid catalog round-trips through YAML successfully
#   - Loader: empty scaffold files load cleanly (NeWazaCatalog with empty dicts)
#   - Loader: each subfamily field-presence rule fires when violated
#     (pin missing position, joint_lock missing joint_target, etc.)
#   - Loader: enum validation (invalid subfamily, mechanism_family,
#     connection type, mechanical_class)
#   - Loader: cross-references resolved; dangling refs raise
#   - Loader: duplicate ids within a file raise
#   - Validator: cross-refs collected (not halt-on-first)
#   - Validator: symmetry between fires_from_position and terminal_techniques
#   - Validator: warnings (dead strut, single-terminal position,
#     joint_lock missing mechanical_class, empty applicable_defensive_struts)
#   - Validator: report format includes summary footer + counts
#   - Validator: CLI exits 0 on clean catalog, 1 on errors

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from ne_waza_catalog import (  # noqa: E402
    ConnectionRequirement,
    ConnectionType,
    DefensePhase,
    DefensiveStrutDefinition,
    InducedTransition,
    JointTarget,
    MechanicalClass,
    MechanismFamily,
    NeWazaCatalog,
    NeWazaCatalogError,
    NeWazaKodokanStatus,
    NeWazaPositionDefinition,
    NeWazaSubfamily,
    NeWazaTechniqueDefinition,
    ScoreMechanism,
    collect_cross_reference_issues,
    load_ne_waza_catalog,
)
from ne_waza_catalog_validator import (  # noqa: E402
    Severity,
    main,
    validate_catalog,
    validate_catalog_files,
)


# ---------------------------------------------------------------------------
# Builders — Python-side construction so tests don't depend on YAML round-trip
# ---------------------------------------------------------------------------
def _strut(strut_id: str = "bridge_and_roll_right") -> DefensiveStrutDefinition:
    return DefensiveStrutDefinition(
        strut_id=strut_id,
        name_descriptive="Bridge and roll",
        mechanism_family=MechanismFamily.ROTATIONAL_DISPLACEMENT,
        defense_phase=DefensePhase.POST_COMMIT,
        applicable_against_connection_types=[ConnectionType.BODY_PRESSURE],
    )


def _pin_technique(
    technique_id: str = "hon_kesa_gatame",
    parent_position: str = "SIDE_CONTROL_RIGHT",
    struts: list[str] | None = None,
) -> NeWazaTechniqueDefinition:
    return NeWazaTechniqueDefinition(
        technique_id=technique_id,
        name_japanese="Hon-kesa-gatame",
        name_english="Scarf Hold",
        family="ne_waza",
        subfamily=NeWazaSubfamily.PIN,
        kodokan_status=NeWazaKodokanStatus.KATAME_NO_KATA,
        required_connections=[
            ConnectionRequirement(
                type=ConnectionType.BODY_PRESSURE,
                tori_part="chest",
                target="uke_chest",
                minimum_quality=0.6,
            ),
        ],
        score_mechanism=ScoreMechanism.PIN_TIME_ACCUMULATION,
        base_difficulty=30,
        parent_position=parent_position,
        applicable_defensive_struts=struts if struts is not None else ["bridge_and_roll_right"],
    )


def _joint_lock(technique_id: str = "ude_hishigi_juji_gatame") -> NeWazaTechniqueDefinition:
    return NeWazaTechniqueDefinition(
        technique_id=technique_id,
        name_japanese="Ude-hishigi-juji-gatame",
        name_english="Cross Arm Lock",
        family="ne_waza",
        subfamily=NeWazaSubfamily.JOINT_LOCK,
        kodokan_status=NeWazaKodokanStatus.KATAME_NO_KATA,
        required_connections=[
            ConnectionRequirement(
                type=ConnectionType.LIMB_ISOLATION,
                tori_part="legs_and_hips",
                target="uke_right_arm",
                minimum_quality=0.7,
            ),
        ],
        score_mechanism=ScoreMechanism.IMMEDIATE_SUBMISSION,
        base_difficulty=50,
        joint_target=JointTarget.ELBOW_EXTENSION,
        fulcrum_body_part="hips_and_thighs",
        mechanical_class=MechanicalClass.LEVER_EXTENSION,
        applicable_defensive_struts=["bridge_and_roll_right"],
    )


def _strangle(technique_id: str = "hadaka_jime") -> NeWazaTechniqueDefinition:
    return NeWazaTechniqueDefinition(
        technique_id=technique_id,
        name_japanese="Hadaka-jime",
        name_english="Naked Strangle",
        family="ne_waza",
        subfamily=NeWazaSubfamily.STRANGLE,
        kodokan_status=NeWazaKodokanStatus.KATAME_NO_KATA,
        required_connections=[
            ConnectionRequirement(
                type=ConnectionType.FOREARM_BAR,
                tori_part="right_forearm",
                target="uke_throat",
                minimum_quality=0.7,
            ),
        ],
        score_mechanism=ScoreMechanism.IMMEDIATE_SUBMISSION,
        base_difficulty=40,
        applicable_defensive_struts=["bridge_and_roll_right"],
    )


def _basic_catalog() -> NeWazaCatalog:
    return NeWazaCatalog(
        techniques={"hon_kesa_gatame": _pin_technique(), "hadaka_jime": _strangle()},
        positions={},
        struts={"bridge_and_roll_right": _strut()},
    )


def _write(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")


# ---------------------------------------------------------------------------
# Empty scaffold catalogs
# ---------------------------------------------------------------------------
def test_load_empty_scaffold_files(tmp_path):
    tp = tmp_path / "techs.yaml"
    pp = tmp_path / "positions.yaml"
    sp = tmp_path / "struts.yaml"
    _write(tp, "techniques: []\n")
    _write(pp, "positions: []\n")
    _write(sp, "struts: []\n")
    catalog = load_ne_waza_catalog(tp, pp, sp)
    assert catalog.techniques == {}
    assert catalog.positions == {}
    assert catalog.struts == {}


def test_load_real_repo_catalog_files():
    """The committed catalog files must always load cleanly and pass
    every validator check — this is the catalog the engine consumes."""
    catalog = load_ne_waza_catalog(
        REPO_ROOT / "data" / "ne_waza_techniques.yaml",
        REPO_ROOT / "data" / "ne_waza_positions.yaml",
        REPO_ROOT / "data" / "defensive_struts.yaml",
    )
    # Every technique declared in the spec §2.5 / §3.5 scope must load.
    # Hard-coding white-belt minimum (spec §8.2) so regressions to those
    # foundational entries fail loud.
    for required_id in (
        "hon_kesa_gatame",
        "yoko_shiho_gatame",
        "kami_shiho_gatame",
        "ude_hishigi_juji_gatame",
    ):
        assert required_id in catalog.techniques, f"missing white-belt entry {required_id!r}"
    # Dominant positions and their three sankaku terminals from spec §3.5
    assert "sankaku_position" in catalog.positions
    assert set(catalog.positions["sankaku_position"].terminal_techniques) == {
        "sankaku_jime", "ude_hishigi_sankaku_gatame", "sankaku_gatame",
    }
    # Validator clean (no errors, no warnings — full catalog is authored).
    report = validate_catalog(catalog)
    assert report.is_valid
    assert report.errors == []
    assert report.warnings == []


def test_validator_on_empty_scaffold_is_clean():
    report = validate_catalog(NeWazaCatalog())
    assert report.is_valid
    assert report.errors == []
    assert report.warnings == []
    assert report.total_techniques == 0


# ---------------------------------------------------------------------------
# Loader: YAML round-trip
# ---------------------------------------------------------------------------
def test_load_minimal_valid_catalog_round_trip(tmp_path):
    tp = tmp_path / "techs.yaml"
    pp = tmp_path / "positions.yaml"
    sp = tmp_path / "struts.yaml"
    _write(sp, """
        - strut_id: bridge_and_roll_right
          name_descriptive: Bridge and roll
          mechanism_family: rotational_displacement
          defense_phase: post_commit
          applicable_against_connection_types:
            - BODY_PRESSURE
    """)
    _write(tp, """
        techniques:
          - technique_id: hon_kesa_gatame
            name_japanese: Hon-kesa-gatame
            name_english: Scarf Hold
            family: ne_waza
            subfamily: pin
            kodokan_status: katame_no_kata
            parent_position: SIDE_CONTROL_RIGHT
            required_connections:
              - type: BODY_PRESSURE
                tori_part: chest
                target: uke_chest
                minimum_quality: 0.6
            applicable_defensive_struts:
              - bridge_and_roll_right
            score_mechanism: pin_time_accumulation
            base_difficulty: 30
    """)
    _write(pp, "positions: []\n")

    catalog = load_ne_waza_catalog(tp, pp, sp)
    assert list(catalog.techniques) == ["hon_kesa_gatame"]
    tech = catalog.get_technique("hon_kesa_gatame")
    assert tech is not None
    assert tech.subfamily is NeWazaSubfamily.PIN
    assert tech.applicable_defensive_struts == ["bridge_and_roll_right"]
    assert catalog.get_strut("bridge_and_roll_right") is not None


# ---------------------------------------------------------------------------
# Loader: subfamily field-presence rules (spec §2.4)
# ---------------------------------------------------------------------------
def test_pin_missing_position_raises_via_loader(tmp_path):
    tp = tmp_path / "t.yaml"
    _write(tp, """
        - technique_id: bad_pin
          name_japanese: X
          name_english: X
          family: ne_waza
          subfamily: pin
          kodokan_status: katame_no_kata
          required_connections: []
          applicable_defensive_struts: []
          score_mechanism: pin_time_accumulation
          base_difficulty: 30
    """)
    pp = tmp_path / "p.yaml"
    sp = tmp_path / "s.yaml"
    _write(pp, "[]\n")
    _write(sp, "[]\n")
    with pytest.raises(NeWazaCatalogError, match="parent_position or fires_from_position"):
        load_ne_waza_catalog(tp, pp, sp)


def test_pin_with_immediate_submission_score_raises(tmp_path):
    tp = tmp_path / "t.yaml"
    _write(tp, """
        - technique_id: wrong_score
          name_japanese: X
          name_english: X
          family: ne_waza
          subfamily: pin
          kodokan_status: katame_no_kata
          parent_position: SIDE_CONTROL
          required_connections: []
          applicable_defensive_struts: []
          score_mechanism: immediate_submission
          base_difficulty: 30
    """)
    pp = tmp_path / "p.yaml"; _write(pp, "[]\n")
    sp = tmp_path / "s.yaml"; _write(sp, "[]\n")
    with pytest.raises(NeWazaCatalogError, match="pin_time_accumulation"):
        load_ne_waza_catalog(tp, pp, sp)


def test_pin_with_joint_target_raises(tmp_path):
    tp = tmp_path / "t.yaml"
    _write(tp, """
        - technique_id: bad
          name_japanese: X
          name_english: X
          family: ne_waza
          subfamily: pin
          kodokan_status: katame_no_kata
          parent_position: SIDE_CONTROL
          required_connections: []
          applicable_defensive_struts: []
          score_mechanism: pin_time_accumulation
          base_difficulty: 30
          joint_target: elbow_extension
    """)
    pp = tmp_path / "p.yaml"; _write(pp, "[]\n")
    sp = tmp_path / "s.yaml"; _write(sp, "[]\n")
    with pytest.raises(NeWazaCatalogError, match="joint_target.*null"):
        load_ne_waza_catalog(tp, pp, sp)


def test_strangle_with_wrong_score_raises(tmp_path):
    tp = tmp_path / "t.yaml"
    _write(tp, """
        - technique_id: bad
          name_japanese: X
          name_english: X
          family: ne_waza
          subfamily: strangle
          kodokan_status: katame_no_kata
          required_connections: []
          applicable_defensive_struts: []
          score_mechanism: pin_time_accumulation
          base_difficulty: 30
    """)
    pp = tmp_path / "p.yaml"; _write(pp, "[]\n")
    sp = tmp_path / "s.yaml"; _write(sp, "[]\n")
    with pytest.raises(NeWazaCatalogError, match="immediate_submission"):
        load_ne_waza_catalog(tp, pp, sp)


def test_joint_lock_missing_joint_target_raises(tmp_path):
    tp = tmp_path / "t.yaml"
    _write(tp, """
        - technique_id: bad
          name_japanese: X
          name_english: X
          family: ne_waza
          subfamily: joint_lock
          kodokan_status: katame_no_kata
          required_connections: []
          applicable_defensive_struts: []
          score_mechanism: immediate_submission
          base_difficulty: 30
          fulcrum_body_part: hips
    """)
    pp = tmp_path / "p.yaml"; _write(pp, "[]\n")
    sp = tmp_path / "s.yaml"; _write(sp, "[]\n")
    with pytest.raises(NeWazaCatalogError, match="joint_target"):
        load_ne_waza_catalog(tp, pp, sp)


def test_joint_lock_missing_fulcrum_raises(tmp_path):
    tp = tmp_path / "t.yaml"
    _write(tp, """
        - technique_id: bad
          name_japanese: X
          name_english: X
          family: ne_waza
          subfamily: joint_lock
          kodokan_status: katame_no_kata
          required_connections: []
          applicable_defensive_struts: []
          score_mechanism: immediate_submission
          base_difficulty: 30
          joint_target: elbow_extension
    """)
    pp = tmp_path / "p.yaml"; _write(pp, "[]\n")
    sp = tmp_path / "s.yaml"; _write(sp, "[]\n")
    with pytest.raises(NeWazaCatalogError, match="fulcrum_body_part"):
        load_ne_waza_catalog(tp, pp, sp)


# ---------------------------------------------------------------------------
# Loader: enum and type validation
# ---------------------------------------------------------------------------
def test_invalid_subfamily_raises(tmp_path):
    tp = tmp_path / "t.yaml"
    _write(tp, """
        - technique_id: bad
          name_japanese: X
          name_english: X
          family: ne_waza
          subfamily: takedown
          kodokan_status: katame_no_kata
          required_connections: []
          applicable_defensive_struts: []
          score_mechanism: pin_time_accumulation
          base_difficulty: 30
          parent_position: SIDE_CONTROL
    """)
    pp = tmp_path / "p.yaml"; _write(pp, "[]\n")
    sp = tmp_path / "s.yaml"; _write(sp, "[]\n")
    with pytest.raises(NeWazaCatalogError, match="NeWazaSubfamily"):
        load_ne_waza_catalog(tp, pp, sp)


def test_wrong_family_raises(tmp_path):
    tp = tmp_path / "t.yaml"
    _write(tp, """
        - technique_id: bad
          name_japanese: X
          name_english: X
          family: te_waza
          subfamily: pin
          kodokan_status: katame_no_kata
          parent_position: SIDE_CONTROL
          required_connections: []
          applicable_defensive_struts: []
          score_mechanism: pin_time_accumulation
          base_difficulty: 30
    """)
    pp = tmp_path / "p.yaml"; _write(pp, "[]\n")
    sp = tmp_path / "s.yaml"; _write(sp, "[]\n")
    with pytest.raises(NeWazaCatalogError, match="must be 'ne_waza'"):
        load_ne_waza_catalog(tp, pp, sp)


def test_invalid_connection_type_raises(tmp_path):
    tp = tmp_path / "t.yaml"
    _write(tp, """
        - technique_id: bad
          name_japanese: X
          name_english: X
          family: ne_waza
          subfamily: pin
          kodokan_status: katame_no_kata
          parent_position: SIDE_CONTROL
          required_connections:
            - type: NOT_A_REAL_CONNECTION
              tori_part: chest
              target: uke_chest
              minimum_quality: 0.6
          applicable_defensive_struts: []
          score_mechanism: pin_time_accumulation
          base_difficulty: 30
    """)
    pp = tmp_path / "p.yaml"; _write(pp, "[]\n")
    sp = tmp_path / "s.yaml"; _write(sp, "[]\n")
    with pytest.raises(NeWazaCatalogError, match="ConnectionType"):
        load_ne_waza_catalog(tp, pp, sp)


def test_invalid_mechanical_class_raises(tmp_path):
    tp = tmp_path / "t.yaml"
    _write(tp, """
        - technique_id: bad
          name_japanese: X
          name_english: X
          family: ne_waza
          subfamily: joint_lock
          kodokan_status: katame_no_kata
          required_connections: []
          applicable_defensive_struts: []
          score_mechanism: immediate_submission
          base_difficulty: 30
          joint_target: elbow_extension
          fulcrum_body_part: hips
          mechanical_class: nonsense_class
    """)
    pp = tmp_path / "p.yaml"; _write(pp, "[]\n")
    sp = tmp_path / "s.yaml"; _write(sp, "[]\n")
    with pytest.raises(NeWazaCatalogError, match="MechanicalClass"):
        load_ne_waza_catalog(tp, pp, sp)


def test_minimum_quality_out_of_bounds_raises(tmp_path):
    tp = tmp_path / "t.yaml"
    _write(tp, """
        - technique_id: bad
          name_japanese: X
          name_english: X
          family: ne_waza
          subfamily: pin
          kodokan_status: katame_no_kata
          parent_position: SIDE_CONTROL
          required_connections:
            - type: BODY_PRESSURE
              tori_part: chest
              target: uke_chest
              minimum_quality: 1.5
          applicable_defensive_struts: []
          score_mechanism: pin_time_accumulation
          base_difficulty: 30
    """)
    pp = tmp_path / "p.yaml"; _write(pp, "[]\n")
    sp = tmp_path / "s.yaml"; _write(sp, "[]\n")
    with pytest.raises(NeWazaCatalogError, match=r"\[0\.0, 1\.0\]"):
        load_ne_waza_catalog(tp, pp, sp)


def test_invalid_strut_mechanism_family_raises(tmp_path):
    sp = tmp_path / "s.yaml"
    _write(sp, """
        - strut_id: bad
          name_descriptive: Whatever
          mechanism_family: not_a_family
          defense_phase: post_commit
          applicable_against_connection_types: [BODY_PRESSURE]
    """)
    tp = tmp_path / "t.yaml"; _write(tp, "[]\n")
    pp = tmp_path / "p.yaml"; _write(pp, "[]\n")
    with pytest.raises(NeWazaCatalogError, match="MechanismFamily"):
        load_ne_waza_catalog(tp, pp, sp)


def test_invalid_defense_phase_raises(tmp_path):
    sp = tmp_path / "s.yaml"
    _write(sp, """
        - strut_id: bad
          name_descriptive: Whatever
          mechanism_family: rotational_displacement
          defense_phase: mid_commit
          applicable_against_connection_types: [BODY_PRESSURE]
    """)
    tp = tmp_path / "t.yaml"; _write(tp, "[]\n")
    pp = tmp_path / "p.yaml"; _write(pp, "[]\n")
    with pytest.raises(NeWazaCatalogError, match="DefensePhase"):
        load_ne_waza_catalog(tp, pp, sp)


def test_duplicate_technique_id_raises(tmp_path):
    tp = tmp_path / "t.yaml"
    _write(tp, """
        - technique_id: dup
          name_japanese: A
          name_english: A
          family: ne_waza
          subfamily: pin
          kodokan_status: katame_no_kata
          parent_position: SIDE_CONTROL
          required_connections: []
          applicable_defensive_struts: []
          score_mechanism: pin_time_accumulation
          base_difficulty: 30
        - technique_id: dup
          name_japanese: B
          name_english: B
          family: ne_waza
          subfamily: pin
          kodokan_status: katame_no_kata
          parent_position: SIDE_CONTROL
          required_connections: []
          applicable_defensive_struts: []
          score_mechanism: pin_time_accumulation
          base_difficulty: 30
    """)
    pp = tmp_path / "p.yaml"; _write(pp, "[]\n")
    sp = tmp_path / "s.yaml"; _write(sp, "[]\n")
    with pytest.raises(NeWazaCatalogError, match="duplicate technique_id"):
        load_ne_waza_catalog(tp, pp, sp)


# ---------------------------------------------------------------------------
# Loader: cross-references
# ---------------------------------------------------------------------------
def test_dangling_strut_reference_raises(tmp_path):
    tp = tmp_path / "t.yaml"
    _write(tp, """
        - technique_id: hon_kesa_gatame
          name_japanese: X
          name_english: X
          family: ne_waza
          subfamily: pin
          kodokan_status: katame_no_kata
          parent_position: SIDE_CONTROL
          required_connections: []
          applicable_defensive_struts: [ghost_strut]
          score_mechanism: pin_time_accumulation
          base_difficulty: 30
    """)
    pp = tmp_path / "p.yaml"; _write(pp, "[]\n")
    sp = tmp_path / "s.yaml"; _write(sp, "[]\n")
    with pytest.raises(NeWazaCatalogError, match="ghost_strut"):
        load_ne_waza_catalog(tp, pp, sp)


def test_dangling_fires_from_position_raises(tmp_path):
    tp = tmp_path / "t.yaml"
    _write(tp, """
        - technique_id: sankaku_jime
          name_japanese: X
          name_english: X
          family: ne_waza
          subfamily: strangle
          kodokan_status: katame_no_kata
          fires_from_position: ghost_position
          required_connections: []
          applicable_defensive_struts: []
          score_mechanism: immediate_submission
          base_difficulty: 40
    """)
    pp = tmp_path / "p.yaml"; _write(pp, "[]\n")
    sp = tmp_path / "s.yaml"; _write(sp, "[]\n")
    with pytest.raises(NeWazaCatalogError, match="ghost_position"):
        load_ne_waza_catalog(tp, pp, sp)


# ---------------------------------------------------------------------------
# Validator: collecting cross-refs
# ---------------------------------------------------------------------------
def test_collect_cross_reference_issues_finds_multiple():
    catalog = NeWazaCatalog(
        techniques={
            "t1": _pin_technique("t1", struts=["ghost1"]),
            "t2": NeWazaTechniqueDefinition(
                technique_id="t2",
                name_japanese="X", name_english="X",
                family="ne_waza",
                subfamily=NeWazaSubfamily.STRANGLE,
                kodokan_status=NeWazaKodokanStatus.KATAME_NO_KATA,
                required_connections=[],
                score_mechanism=ScoreMechanism.IMMEDIATE_SUBMISSION,
                base_difficulty=30,
                fires_from_position="ghost_pos",
                applicable_defensive_struts=["ghost2"],
                ne_waza_followup_preferences=["ghost_tech"],
            ),
        },
        positions={},
        struts={},
    )
    issues = collect_cross_reference_issues(catalog)
    joined = "\n".join(issues)
    assert "ghost1" in joined
    assert "ghost2" in joined
    assert "ghost_pos" in joined
    assert "ghost_tech" in joined


def test_validator_surfaces_all_dangling_refs_as_separate_issues():
    catalog = NeWazaCatalog(
        techniques={"t": _pin_technique("t", struts=["a", "b", "c"])},
        struts={},
    )
    report = validate_catalog(catalog)
    dangling = [i for i in report.errors if i.code == "dangling_cross_reference"]
    assert len(dangling) == 3


# ---------------------------------------------------------------------------
# Validator: symmetry
# ---------------------------------------------------------------------------
def test_symmetry_terminal_missing_from_position():
    """Technique points at a position whose terminals don't include it."""
    tech = NeWazaTechniqueDefinition(
        technique_id="sankaku_jime",
        name_japanese="X", name_english="X",
        family="ne_waza",
        subfamily=NeWazaSubfamily.STRANGLE,
        kodokan_status=NeWazaKodokanStatus.KATAME_NO_KATA,
        required_connections=[],
        score_mechanism=ScoreMechanism.IMMEDIATE_SUBMISSION,
        base_difficulty=40,
        fires_from_position="sankaku_position",
    )
    pos = NeWazaPositionDefinition(
        position_id="sankaku_position",
        description="triangle",
        required_connections=[],
        terminal_techniques=["something_else", "yet_another"],
    )
    catalog = NeWazaCatalog(
        techniques={"sankaku_jime": tech, "something_else": _strangle("something_else"),
                    "yet_another": _strangle("yet_another")},
        positions={"sankaku_position": pos},
    )
    report = validate_catalog(catalog)
    codes = {i.code for i in report.errors}
    assert "symmetry_terminal_missing" in codes


def test_symmetry_fires_from_mismatch():
    """Position lists a terminal whose fires_from_position points elsewhere."""
    tech = _strangle("hadaka_jime")     # fires_from_position is None
    pos = NeWazaPositionDefinition(
        position_id="back_turtle_with_hooks",
        description="back",
        required_connections=[],
        terminal_techniques=["hadaka_jime", "okuri_eri_jime"],
    )
    catalog = NeWazaCatalog(
        techniques={"hadaka_jime": tech, "okuri_eri_jime": _strangle("okuri_eri_jime")},
        positions={"back_turtle_with_hooks": pos},
    )
    report = validate_catalog(catalog)
    codes = {i.code for i in report.errors}
    assert "symmetry_fires_from_mismatch" in codes


def test_symmetry_clean_when_both_directions_match():
    tech = NeWazaTechniqueDefinition(
        technique_id="sankaku_jime",
        name_japanese="X", name_english="X",
        family="ne_waza",
        subfamily=NeWazaSubfamily.STRANGLE,
        kodokan_status=NeWazaKodokanStatus.KATAME_NO_KATA,
        required_connections=[],
        score_mechanism=ScoreMechanism.IMMEDIATE_SUBMISSION,
        base_difficulty=40,
        fires_from_position="sankaku_position",
        applicable_defensive_struts=[],
    )
    tech2 = NeWazaTechniqueDefinition(
        technique_id="ude_hishigi_sankaku_gatame",
        name_japanese="X", name_english="X",
        family="ne_waza",
        subfamily=NeWazaSubfamily.JOINT_LOCK,
        kodokan_status=NeWazaKodokanStatus.KATAME_NO_KATA,
        required_connections=[],
        score_mechanism=ScoreMechanism.IMMEDIATE_SUBMISSION,
        base_difficulty=50,
        fires_from_position="sankaku_position",
        joint_target=JointTarget.ELBOW_EXTENSION,
        fulcrum_body_part="legs",
        mechanical_class=MechanicalClass.LEVER_COMPRESSION,
        applicable_defensive_struts=[],
    )
    pos = NeWazaPositionDefinition(
        position_id="sankaku_position",
        description="triangle",
        required_connections=[],
        terminal_techniques=["sankaku_jime", "ude_hishigi_sankaku_gatame"],
    )
    catalog = NeWazaCatalog(
        techniques={"sankaku_jime": tech, "ude_hishigi_sankaku_gatame": tech2},
        positions={"sankaku_position": pos},
    )
    report = validate_catalog(catalog)
    sym = [i for i in report.errors if i.code.startswith("symmetry_")]
    assert sym == []


# ---------------------------------------------------------------------------
# Validator: warnings
# ---------------------------------------------------------------------------
def test_joint_lock_without_mechanical_class_warns():
    tech = _joint_lock()
    tech.mechanical_class = None
    catalog = NeWazaCatalog(
        techniques={tech.technique_id: tech},
        struts={"bridge_and_roll_right": _strut()},
    )
    report = validate_catalog(catalog)
    codes = {i.code for i in report.warnings}
    assert "joint_lock_missing_mechanical_class" in codes


def test_empty_applicable_defensive_struts_warns():
    tech = _pin_technique(struts=[])
    catalog = NeWazaCatalog(techniques={tech.technique_id: tech})
    report = validate_catalog(catalog)
    codes = {i.code for i in report.warnings}
    assert "empty_applicable_defensive_struts" in codes


def test_dead_strut_warns():
    catalog = NeWazaCatalog(
        techniques={},
        positions={},
        struts={"unused_strut": _strut("unused_strut")},
    )
    report = validate_catalog(catalog)
    codes = {i.code for i in report.warnings}
    assert "dead_strut" in codes


def test_dead_strut_referenced_by_induced_transition_is_not_dead():
    pos = NeWazaPositionDefinition(
        position_id="p",
        description="d",
        required_connections=[],
        terminal_techniques=["t1", "t2"],
        induced_transitions=[
            InducedTransition(
                if_uke_strut_activates="some_strut",
                tori_can_pivot_to="t2",
                transition_cost=1,
            ),
        ],
        applicable_defensive_struts=[],
    )
    catalog = NeWazaCatalog(
        techniques={"t1": _strangle("t1"), "t2": _strangle("t2")},
        positions={"p": pos},
        struts={"some_strut": _strut("some_strut")},
    )
    # Symmetry will complain (t1/t2 fires_from_position is None, not "p") —
    # but the dead-strut check should NOT fire because the induced
    # transition keeps the strut referenced.
    report = validate_catalog(catalog)
    codes = {i.code for i in report.warnings}
    assert "dead_strut" not in codes


def test_single_terminal_position_warns():
    pos = NeWazaPositionDefinition(
        position_id="p",
        description="d",
        required_connections=[],
        terminal_techniques=["only_one"],
    )
    catalog = NeWazaCatalog(
        techniques={"only_one": _strangle("only_one")},
        positions={"p": pos},
    )
    report = validate_catalog(catalog)
    codes = {i.code for i in report.warnings}
    assert "dominant_position_too_few_terminals" in codes


# ---------------------------------------------------------------------------
# Validator: report format and CLI
# ---------------------------------------------------------------------------
def test_report_format_includes_summary_footer():
    report = validate_catalog(_basic_catalog())
    text = report.format_text()
    assert "techniques:" in text
    assert "positions:" in text
    assert "struts:" in text
    assert "by subfamily:" in text
    assert "errors:" in text and "warnings:" in text and "infos:" in text


def test_report_format_suppress_warnings():
    catalog = NeWazaCatalog(
        techniques={"t": _pin_technique("t", struts=[])},  # triggers empty-struts warning
    )
    report = validate_catalog(catalog)
    full = report.format_text(include_warnings=True)
    suppressed = report.format_text(include_warnings=False)
    assert "empty_applicable_defensive_struts" in full
    assert "empty_applicable_defensive_struts" not in suppressed


def test_load_error_format_is_terse():
    from ne_waza_catalog_validator import ValidationReport
    report = ValidationReport(load_error="boom")
    text = report.format_text()
    assert "FATAL" in text and "boom" in text


def test_cli_exit_zero_on_empty_scaffolds(tmp_path):
    tp = tmp_path / "t.yaml"; _write(tp, "techniques: []\n")
    pp = tmp_path / "p.yaml"; _write(pp, "positions: []\n")
    sp = tmp_path / "s.yaml"; _write(sp, "struts: []\n")
    exit_code = main([str(tp), str(pp), str(sp), "--quiet"])
    assert exit_code == 0


def test_cli_exit_one_on_dangling_cross_ref(tmp_path):
    tp = tmp_path / "t.yaml"
    _write(tp, """
        - technique_id: bad
          name_japanese: X
          name_english: X
          family: ne_waza
          subfamily: pin
          kodokan_status: katame_no_kata
          parent_position: SIDE_CONTROL
          required_connections: []
          applicable_defensive_struts: [ghost]
          score_mechanism: pin_time_accumulation
          base_difficulty: 30
    """)
    pp = tmp_path / "p.yaml"; _write(pp, "positions: []\n")
    sp = tmp_path / "s.yaml"; _write(sp, "struts: []\n")
    exit_code = main([str(tp), str(pp), str(sp), "--quiet"])
    assert exit_code == 1


def test_cli_exit_one_on_loader_failure(tmp_path):
    tp = tmp_path / "t.yaml"
    _write(tp, """
        - technique_id: bad
          family: not_real
          name_japanese: X
          name_english: X
          subfamily: pin
          kodokan_status: katame_no_kata
          required_connections: []
          applicable_defensive_struts: []
          score_mechanism: pin_time_accumulation
          base_difficulty: 30
    """)
    pp = tmp_path / "p.yaml"; _write(pp, "positions: []\n")
    sp = tmp_path / "s.yaml"; _write(sp, "struts: []\n")
    exit_code = main([str(tp), str(pp), str(sp), "--quiet"])
    assert exit_code == 1


def test_validate_catalog_files_surfaces_yaml_error(tmp_path):
    tp = tmp_path / "t.yaml"
    _write(tp, """
        - technique_id: a
          family: ne_waza
        bad_indent: oops
    """)
    pp = tmp_path / "p.yaml"; _write(pp, "positions: []\n")
    sp = tmp_path / "s.yaml"; _write(sp, "struts: []\n")
    report = validate_catalog_files(tp, pp, sp)
    assert report.load_error is not None
    assert report.is_valid is False
