# ne_waza_catalog.py
# Schema + loader for the ne-waza vocabulary substrate (HAJ-215).
#
# Implements three sibling dataclasses + a unifying NeWazaCatalog wrapper:
#   - NeWazaTechniqueDefinition  — one katame-waza entry (pin/strangle/joint_lock)
#   - NeWazaPositionDefinition   — one dominant position (sankaku, back-turtle-with-hooks)
#   - DefensiveStrutDefinition   — one defensive primitive (bridge-and-roll, etc.)
#   - NeWazaCatalog              — wraps the three dicts with convenience accessors
#
# Schema locked by design-notes/triage/ne-waza-vocabulary-system.md v0.1
# (sections 2.2, 3.3, 4.3 define the three dataclass shapes; section 5
# enumerates the 12 connection types; section 6 the mechanical-class enum).
#
# This catalog is a SIBLING to the tachiwaza catalog in src/technique_catalog.py
# — not an extension of it. Tachiwaza grips are hand-on-garment at named
# locations; ne-waza connections are distributed body-pressure / anatomical
# wraps / limb triangles / lapel crosses that don't fit the tachiwaza grip
# taxonomy. The two graphs are siblings, not parent-child (spec §3.1).
#
# Cross-reference resolution runs at load time: techniques must reference
# real strut_ids and position_ids; positions must reference real
# technique_ids and strut_ids. Dangling references raise CatalogError
# immediately so the engine never sees a broken catalog. The validator
# (src/ne_waza_catalog_validator.py) re-runs the same checks in collecting
# mode plus symmetry / warnings the loader doesn't surface.

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Union


# ===========================================================================
# ENUMS — spec §2.2, §4.3, §5, §6
# ===========================================================================
class NeWazaSubfamily(Enum):
    PIN        = "pin"
    STRANGLE   = "strangle"
    JOINT_LOCK = "joint_lock"


class NeWazaKodokanStatus(Enum):
    """Distinct value set from tachiwaza — katame_no_kata is the canonical
    ne-waza kata; habukareta currently has no ne-waza entries but the
    schema includes it for parity (spec §2.3)."""
    KATAME_NO_KATA = "katame_no_kata"
    SHINMEISHO     = "shinmeisho"
    HABUKARETA     = "habukareta"


class ScoreMechanism(Enum):
    PIN_TIME_ACCUMULATION = "pin_time_accumulation"
    IMMEDIATE_SUBMISSION  = "immediate_submission"


class JointTarget(Enum):
    """Joint targeted by a joint_lock technique. Required when subfamily=joint_lock."""
    ELBOW_EXTENSION   = "elbow_extension"
    ELBOW_ROTATION    = "elbow_rotation"
    SHOULDER_ROTATION = "shoulder_rotation"
    WRIST             = "wrist"
    KNEE              = "knee"
    ANKLE             = "ankle"


class MechanicalClass(Enum):
    """Lever / couple classification per Sacripanti biomechanics. Spec §6."""
    LEVER_EXTENSION   = "lever_extension"
    LEVER_ROTATION    = "lever_rotation"
    LEVER_COMPRESSION = "lever_compression"
    COUPLE_CHOKE      = "couple_choke"
    LEVER_CHOKE       = "lever_choke"
    COUPLE_PIN        = "couple_pin"
    LEVER_PIN         = "lever_pin"


class ConnectionType(Enum):
    """The twelve ne-waza connection types from spec §5. Sibling to
    tachiwaza's GripTargetRegion — same engine concept (a named contact
    that gates a technique), entirely different vocabulary."""
    # Pin context (§5.1)
    BODY_PRESSURE       = "BODY_PRESSURE"
    GARMENT_GRIP_NEWAZA = "GARMENT_GRIP_NEWAZA"
    ANATOMICAL_TRAP     = "ANATOMICAL_TRAP"
    POSITIONAL_BASE     = "POSITIONAL_BASE"
    ANATOMICAL_WRAP     = "ANATOMICAL_WRAP"
    # Submission context (§5.2)
    LAPEL_CROSS         = "LAPEL_CROSS"
    FOREARM_BAR         = "FOREARM_BAR"
    LIMB_TRIANGLE       = "LIMB_TRIANGLE"
    LIMB_ISOLATION      = "LIMB_ISOLATION"
    WRIST_GRIP          = "WRIST_GRIP"
    THREADED_VOID       = "THREADED_VOID"
    SELF_ANCHOR         = "SELF_ANCHOR"


class MechanismFamily(Enum):
    """Underlying motion family that groups defensive struts. Spec §4.4."""
    ROTATIONAL_DISPLACEMENT = "rotational_displacement"
    LINEAR_EXTRACTION       = "linear_extraction"
    LIMB_RECAPTURE          = "limb_recapture"
    PRE_GRIP_SEIZURE        = "pre_grip_seizure"
    JOINT_PROTECTION        = "joint_protection"
    POSTURAL_DENIAL         = "postural_denial"
    COUNTER_ATTACK          = "counter_attack"


class DefensePhase(Enum):
    """When in the technique timeline a strut fires. Spec §4.4."""
    PRE_POSITION = "pre_position"
    PRE_COMMIT   = "pre_commit"
    POST_COMMIT  = "post_commit"


# ===========================================================================
# CONNECTION REQUIREMENTS — referenced from techniques and positions
# ===========================================================================
@dataclass
class ConnectionRequirement:
    """One ConnectionEdge requirement on a technique or position.

    `extras` carries type-specific fields the spec describes per type:
      - LIMB_TRIANGLE   → orientation (diagonal | direct)
      - LAPEL_CROSS     → cross_orientation (regular | reverse)
      - WRIST_GRIP      → rotational_lock_axis (extension | rotation | flexion)
      - others as the substrate grows
    Stored as a free-form dict; the validator currently does not enforce
    type-specific shapes (deferred to a later schema lockdown pass once
    authoring has surfaced what's load-bearing).
    """
    type: ConnectionType
    tori_part: str
    target: str
    minimum_quality: float
    extras: dict = field(default_factory=dict)


# ===========================================================================
# INDUCED TRANSITIONS — referenced from positions
# ===========================================================================
@dataclass
class InducedTransition:
    """One entry in a position's induced_transitions list.

    Spec §3.4: when uke's defensive strut against one terminal activates,
    tori can release pressure on that threat and commit to a different
    terminal at the given tick cost.
    """
    if_uke_strut_activates: str            # strut_id
    tori_can_pivot_to: str                 # technique_id
    transition_cost: int                   # ticks
    narrative: str = ""


# ===========================================================================
# DATACLASSES — spec §2.2, §3.3, §4.3
# ===========================================================================
@dataclass
class NeWazaTechniqueDefinition:
    """One katame-waza entry. Field order matches spec §2.2."""
    # Identity
    technique_id: str
    name_japanese: str
    name_english: str

    # Classification — `family` is always `ne_waza` (validated at load time)
    family: str
    subfamily: NeWazaSubfamily
    kodokan_status: NeWazaKodokanStatus

    # Substrate
    required_connections: list[ConnectionRequirement]

    # Score
    score_mechanism: ScoreMechanism

    # Difficulty
    base_difficulty: int

    # Position binding (one or both may be null per spec §2.4)
    parent_position: Optional[str] = None
    fires_from_position: Optional[str] = None

    applicable_defensive_struts: list[str] = field(default_factory=list)

    # Joint-lock-only — validated by subfamily field-presence rules
    joint_target: Optional[JointTarget] = None
    fulcrum_body_part: Optional[str] = None

    # Pedagogy
    pedagogical_prerequisites: list[str] = field(default_factory=list)
    minimum_belt_for_competition_use: Optional[str] = None

    # Mechanical class (spec §6) — joint-lock entries should set this;
    # pin / strangle entries may or may not. Validator warns on
    # joint_lock missing mechanical_class.
    mechanical_class: Optional[MechanicalClass] = None

    # Followup graph
    ne_waza_followup_preferences: list[str] = field(default_factory=list)

    # Metadata
    era_introduced: Optional[int] = None
    notes: str = ""


@dataclass
class NeWazaPositionDefinition:
    """One dominant position. Field order matches spec §3.3."""
    position_id: str
    description: str

    required_connections: list[ConnectionRequirement]

    terminal_techniques: list[str]

    # `parent_position` accepts the literal `any` (position-agnostic dominant
    # positions like sankaku can be entered from multiple broad states).
    parent_position: str = "any"

    induced_transitions: list[InducedTransition] = field(default_factory=list)
    applicable_defensive_struts: list[str] = field(default_factory=list)

    era_introduced: Optional[int] = None
    notes: str = ""


@dataclass
class DefensiveStrutDefinition:
    """One defensive primitive. Field order matches spec §4.3."""
    strut_id: str
    name_descriptive: str

    mechanism_family: MechanismFamily
    defense_phase: DefensePhase

    applicable_against_connection_types: list[ConnectionType]

    body_motion: str = ""
    required_uke_attributes: list[str] = field(default_factory=list)

    # Kodokan doesn't name defenses — most struts will have this null.
    name_japanese: Optional[str] = None

    effectiveness_axis: Optional[str] = None

    # Default false per spec §4.4 — flagged during authoring on a per-strut basis.
    referee_summons: bool = False

    era_introduced: Optional[int] = None
    notes: str = ""


# ===========================================================================
# UNIFYING CATALOG WRAPPER
# ===========================================================================
@dataclass
class NeWazaCatalog:
    """Bundle of the three sibling catalogs with convenience accessors.

    Cross-references between the three are resolved by the loader; once
    constructed, `get_*` returns None for missing ids (callers that want
    raise-on-miss should use `[]` indexing on the underlying dicts).
    """
    techniques: dict[str, NeWazaTechniqueDefinition] = field(default_factory=dict)
    positions: dict[str, NeWazaPositionDefinition] = field(default_factory=dict)
    struts: dict[str, DefensiveStrutDefinition] = field(default_factory=dict)

    def get_technique(self, technique_id: str) -> Optional[NeWazaTechniqueDefinition]:
        return self.techniques.get(technique_id)

    def get_position(self, position_id: str) -> Optional[NeWazaPositionDefinition]:
        return self.positions.get(position_id)

    def get_strut(self, strut_id: str) -> Optional[DefensiveStrutDefinition]:
        return self.struts.get(strut_id)


# ===========================================================================
# LOADER
# ===========================================================================
class NeWazaCatalogError(ValueError):
    """Raised when a ne-waza catalog file fails schema or cross-ref validation.

    Mirrors the role of CatalogValidationError in src/technique_catalog.py;
    distinct exception class so callers can differentiate which substrate
    raised when both catalogs are loaded together.
    """


# Public alias for callers that want a single "catalog error" symbol.
CatalogError = NeWazaCatalogError


def _read_structured_file(path: Union[str, Path]) -> Any:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        import yaml
        return yaml.safe_load(text)
    if suffix == ".json":
        return json.loads(text)
    raise NeWazaCatalogError(
        f"Unsupported catalog file extension '{suffix}' for {path}; "
        "expected .yaml, .yml, or .json"
    )


def _coerce_enum(enum_cls: type[Enum], raw: Any, *, context: str) -> Enum:
    if isinstance(raw, enum_cls):
        return raw
    if not isinstance(raw, str):
        raise NeWazaCatalogError(
            f"{context}: expected string for {enum_cls.__name__}, got {type(raw).__name__}"
        )
    for member in enum_cls:
        if raw == member.value or raw.upper() == member.name:
            return member
    valid = ", ".join(m.value for m in enum_cls)
    raise NeWazaCatalogError(
        f"{context}: '{raw}' is not a valid {enum_cls.__name__}; expected one of: {valid}"
    )


def _require_field(data: dict, field_name: str, context: str) -> Any:
    if field_name not in data:
        raise NeWazaCatalogError(f"{context}: missing required field '{field_name}'")
    value = data[field_name]
    if value is None:
        raise NeWazaCatalogError(f"{context}: required field '{field_name}' is null")
    return value


def _validate_era(raw: Any, context: str, field_name: str) -> Optional[int]:
    if raw is None:
        return None
    if not isinstance(raw, int):
        raise NeWazaCatalogError(
            f"{context}: {field_name} must be an integer year, got {type(raw).__name__}"
        )
    if raw < 1800 or raw > 2200:
        raise NeWazaCatalogError(
            f"{context}: {field_name} year {raw} is outside the sensible range [1800, 2200]"
        )
    return raw


def _parse_connection_requirement(raw: Any, context: str) -> ConnectionRequirement:
    if not isinstance(raw, dict):
        raise NeWazaCatalogError(f"{context}: connection requirement must be a mapping")
    known = {"type", "tori_part", "target", "minimum_quality"}
    type_val = _coerce_enum(
        ConnectionType,
        _require_field(raw, "type", context),
        context=f"{context}.type",
    )
    tori_part = _require_field(raw, "tori_part", context)
    target = _require_field(raw, "target", context)
    quality_raw = _require_field(raw, "minimum_quality", context)
    if not isinstance(quality_raw, (int, float)) or isinstance(quality_raw, bool):
        raise NeWazaCatalogError(
            f"{context}.minimum_quality: expected number, got {type(quality_raw).__name__}"
        )
    quality = float(quality_raw)
    if not (0.0 <= quality <= 1.0):
        raise NeWazaCatalogError(
            f"{context}.minimum_quality: {quality} is outside [0.0, 1.0]"
        )
    extras = {k: v for k, v in raw.items() if k not in known}
    return ConnectionRequirement(
        type=type_val,
        tori_part=str(tori_part),
        target=str(target),
        minimum_quality=quality,
        extras=extras,
    )


def _parse_connection_requirements(raw: Any, context: str) -> list[ConnectionRequirement]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise NeWazaCatalogError(f"{context}: required_connections must be a list")
    return [
        _parse_connection_requirement(item, f"{context}[{i}]")
        for i, item in enumerate(raw)
    ]


def _parse_str_list(raw: Any, context: str, field_name: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or any(not isinstance(x, str) for x in raw):
        raise NeWazaCatalogError(
            f"{context}: {field_name} must be a list of strings"
        )
    return list(raw)


def _parse_induced_transition(raw: Any, context: str) -> InducedTransition:
    if not isinstance(raw, dict):
        raise NeWazaCatalogError(f"{context}: induced transition must be a mapping")
    cost_raw = _require_field(raw, "transition_cost", context)
    if not isinstance(cost_raw, int) or isinstance(cost_raw, bool):
        raise NeWazaCatalogError(
            f"{context}.transition_cost: expected integer ticks, got {type(cost_raw).__name__}"
        )
    if cost_raw < 0:
        raise NeWazaCatalogError(
            f"{context}.transition_cost: {cost_raw} must be non-negative"
        )
    strut_id = _require_field(raw, "if_uke_strut_activates", context)
    pivot = _require_field(raw, "tori_can_pivot_to", context)
    return InducedTransition(
        if_uke_strut_activates=str(strut_id),
        tori_can_pivot_to=str(pivot),
        transition_cost=cost_raw,
        narrative=str(raw.get("narrative", "") or ""),
    )


# ---------------------------------------------------------------------------
# Per-entry parsers
# ---------------------------------------------------------------------------
def _parse_technique(raw: Any) -> NeWazaTechniqueDefinition:
    if not isinstance(raw, dict):
        raise NeWazaCatalogError(
            f"ne-waza technique entry must be a mapping, got {type(raw).__name__}"
        )
    technique_id = _require_field(raw, "technique_id", "<unidentified entry>")
    if not isinstance(technique_id, str) or not technique_id:
        raise NeWazaCatalogError("<unidentified entry>: technique_id must be a non-empty string")
    ctx = f"ne-waza technique '{technique_id}'"

    family = _require_field(raw, "family", ctx)
    if family != "ne_waza":
        raise NeWazaCatalogError(
            f"{ctx}.family: must be 'ne_waza' for entries in this catalog, got '{family}'"
        )

    base_difficulty = _require_field(raw, "base_difficulty", ctx)
    if not isinstance(base_difficulty, int) or not (0 <= base_difficulty <= 100):
        raise NeWazaCatalogError(
            f"{ctx}.base_difficulty: must be an integer in [0, 100], got {base_difficulty!r}"
        )

    subfamily = _coerce_enum(
        NeWazaSubfamily, _require_field(raw, "subfamily", ctx), context=f"{ctx}.subfamily"
    )
    score_mechanism = _coerce_enum(
        ScoreMechanism,
        _require_field(raw, "score_mechanism", ctx),
        context=f"{ctx}.score_mechanism",
    )

    joint_target_raw = raw.get("joint_target")
    joint_target = (
        _coerce_enum(JointTarget, joint_target_raw, context=f"{ctx}.joint_target")
        if joint_target_raw is not None else None
    )

    mechanical_class_raw = raw.get("mechanical_class")
    mechanical_class = (
        _coerce_enum(MechanicalClass, mechanical_class_raw, context=f"{ctx}.mechanical_class")
        if mechanical_class_raw is not None else None
    )

    # Subfamily field-presence rules (spec §2.4). Raising at load time
    # keeps the catalog internally consistent; validator re-runs in
    # collecting mode for richer reports.
    fulcrum = raw.get("fulcrum_body_part")
    parent_pos = raw.get("parent_position")
    fires_from = raw.get("fires_from_position")

    if subfamily is NeWazaSubfamily.PIN:
        if not parent_pos and not fires_from:
            raise NeWazaCatalogError(
                f"{ctx}: subfamily 'pin' requires parent_position or fires_from_position"
            )
        if score_mechanism is not ScoreMechanism.PIN_TIME_ACCUMULATION:
            raise NeWazaCatalogError(
                f"{ctx}: subfamily 'pin' requires score_mechanism 'pin_time_accumulation'"
            )
        if joint_target is not None or fulcrum is not None:
            raise NeWazaCatalogError(
                f"{ctx}: subfamily 'pin' must leave joint_target and fulcrum_body_part null"
            )
    elif subfamily is NeWazaSubfamily.STRANGLE:
        if score_mechanism is not ScoreMechanism.IMMEDIATE_SUBMISSION:
            raise NeWazaCatalogError(
                f"{ctx}: subfamily 'strangle' requires score_mechanism 'immediate_submission'"
            )
        if joint_target is not None or fulcrum is not None:
            raise NeWazaCatalogError(
                f"{ctx}: subfamily 'strangle' must leave joint_target and fulcrum_body_part null"
            )
    elif subfamily is NeWazaSubfamily.JOINT_LOCK:
        if score_mechanism is not ScoreMechanism.IMMEDIATE_SUBMISSION:
            raise NeWazaCatalogError(
                f"{ctx}: subfamily 'joint_lock' requires score_mechanism 'immediate_submission'"
            )
        if joint_target is None:
            raise NeWazaCatalogError(
                f"{ctx}: subfamily 'joint_lock' requires joint_target (non-null enum)"
            )
        if not fulcrum or not isinstance(fulcrum, str):
            raise NeWazaCatalogError(
                f"{ctx}: subfamily 'joint_lock' requires fulcrum_body_part (non-empty string)"
            )

    return NeWazaTechniqueDefinition(
        technique_id=technique_id,
        name_japanese=_require_field(raw, "name_japanese", ctx),
        name_english=_require_field(raw, "name_english", ctx),
        family=family,
        subfamily=subfamily,
        kodokan_status=_coerce_enum(
            NeWazaKodokanStatus,
            _require_field(raw, "kodokan_status", ctx),
            context=f"{ctx}.kodokan_status",
        ),
        required_connections=_parse_connection_requirements(
            raw.get("required_connections"), f"{ctx}.required_connections"
        ),
        score_mechanism=score_mechanism,
        base_difficulty=base_difficulty,
        parent_position=parent_pos if parent_pos else None,
        fires_from_position=fires_from if fires_from else None,
        applicable_defensive_struts=_parse_str_list(
            raw.get("applicable_defensive_struts"), ctx, "applicable_defensive_struts"
        ),
        joint_target=joint_target,
        fulcrum_body_part=str(fulcrum) if fulcrum else None,
        pedagogical_prerequisites=_parse_str_list(
            raw.get("pedagogical_prerequisites"), ctx, "pedagogical_prerequisites"
        ),
        minimum_belt_for_competition_use=raw.get("minimum_belt_for_competition_use"),
        mechanical_class=mechanical_class,
        ne_waza_followup_preferences=_parse_str_list(
            raw.get("ne_waza_followup_preferences"), ctx, "ne_waza_followup_preferences"
        ),
        era_introduced=_validate_era(raw.get("era_introduced"), ctx, "era_introduced"),
        notes=str(raw.get("notes", "") or ""),
    )


def _parse_position(raw: Any) -> NeWazaPositionDefinition:
    if not isinstance(raw, dict):
        raise NeWazaCatalogError(
            f"ne-waza position entry must be a mapping, got {type(raw).__name__}"
        )
    position_id = _require_field(raw, "position_id", "<unidentified position>")
    if not isinstance(position_id, str) or not position_id:
        raise NeWazaCatalogError("<unidentified position>: position_id must be a non-empty string")
    ctx = f"ne-waza position '{position_id}'"

    induced_raw = raw.get("induced_transitions") or []
    if not isinstance(induced_raw, list):
        raise NeWazaCatalogError(f"{ctx}.induced_transitions: must be a list")
    induced = [
        _parse_induced_transition(item, f"{ctx}.induced_transitions[{i}]")
        for i, item in enumerate(induced_raw)
    ]

    parent_pos_raw = raw.get("parent_position", "any")
    if parent_pos_raw is None:
        parent_pos = "any"
    elif not isinstance(parent_pos_raw, str) or not parent_pos_raw:
        raise NeWazaCatalogError(
            f"{ctx}.parent_position: must be a non-empty string (use 'any' for position-agnostic)"
        )
    else:
        parent_pos = parent_pos_raw

    return NeWazaPositionDefinition(
        position_id=position_id,
        description=str(_require_field(raw, "description", ctx)),
        required_connections=_parse_connection_requirements(
            raw.get("required_connections"), f"{ctx}.required_connections"
        ),
        terminal_techniques=_parse_str_list(
            raw.get("terminal_techniques"), ctx, "terminal_techniques"
        ),
        parent_position=parent_pos,
        induced_transitions=induced,
        applicable_defensive_struts=_parse_str_list(
            raw.get("applicable_defensive_struts"), ctx, "applicable_defensive_struts"
        ),
        era_introduced=_validate_era(raw.get("era_introduced"), ctx, "era_introduced"),
        notes=str(raw.get("notes", "") or ""),
    )


def _parse_strut(raw: Any) -> DefensiveStrutDefinition:
    if not isinstance(raw, dict):
        raise NeWazaCatalogError(
            f"defensive strut entry must be a mapping, got {type(raw).__name__}"
        )
    strut_id = _require_field(raw, "strut_id", "<unidentified strut>")
    if not isinstance(strut_id, str) or not strut_id:
        raise NeWazaCatalogError("<unidentified strut>: strut_id must be a non-empty string")
    ctx = f"defensive strut '{strut_id}'"

    against_raw = raw.get("applicable_against_connection_types") or []
    if not isinstance(against_raw, list):
        raise NeWazaCatalogError(
            f"{ctx}.applicable_against_connection_types: must be a list of connection-type values"
        )
    against = [
        _coerce_enum(
            ConnectionType, v, context=f"{ctx}.applicable_against_connection_types[{i}]"
        )
        for i, v in enumerate(against_raw)
    ]

    referee_raw = raw.get("referee_summons", False)
    if not isinstance(referee_raw, bool):
        raise NeWazaCatalogError(
            f"{ctx}.referee_summons: expected boolean, got {type(referee_raw).__name__}"
        )

    name_jp_raw = raw.get("name_japanese")
    name_japanese = name_jp_raw if (name_jp_raw is None or isinstance(name_jp_raw, str)) else str(name_jp_raw)

    return DefensiveStrutDefinition(
        strut_id=strut_id,
        name_descriptive=str(_require_field(raw, "name_descriptive", ctx)),
        mechanism_family=_coerce_enum(
            MechanismFamily,
            _require_field(raw, "mechanism_family", ctx),
            context=f"{ctx}.mechanism_family",
        ),
        defense_phase=_coerce_enum(
            DefensePhase,
            _require_field(raw, "defense_phase", ctx),
            context=f"{ctx}.defense_phase",
        ),
        applicable_against_connection_types=against,
        body_motion=str(raw.get("body_motion", "") or ""),
        required_uke_attributes=_parse_str_list(
            raw.get("required_uke_attributes"), ctx, "required_uke_attributes"
        ),
        name_japanese=name_japanese,
        effectiveness_axis=raw.get("effectiveness_axis"),
        referee_summons=referee_raw,
        era_introduced=_validate_era(raw.get("era_introduced"), ctx, "era_introduced"),
        notes=str(raw.get("notes", "") or ""),
    )


# ---------------------------------------------------------------------------
# File-level parsers
# ---------------------------------------------------------------------------
def _entries_from(data: Any, top_level_key: str, path: Any) -> list:
    """Unwrap one of:
        - a list of entry mappings
        - a mapping with `top_level_key` whose value is such a list
        - None / empty file (treated as empty list — scaffold catalogs)
    """
    if data is None:
        return []
    if isinstance(data, dict) and top_level_key in data:
        entries = data[top_level_key]
        if entries is None:
            return []
        if not isinstance(entries, list):
            raise NeWazaCatalogError(
                f"{path}: '{top_level_key}' must be a list, got {type(entries).__name__}"
            )
        return entries
    if isinstance(data, list):
        return data
    raise NeWazaCatalogError(
        f"{path}: top-level must be a list "
        f"or a mapping with a '{top_level_key}' list"
    )


def _parse_techniques_file(
    path: Union[str, Path],
) -> dict[str, NeWazaTechniqueDefinition]:
    entries = _entries_from(_read_structured_file(path), "techniques", path)
    out: dict[str, NeWazaTechniqueDefinition] = {}
    for entry in entries:
        defn = _parse_technique(entry)
        if defn.technique_id in out:
            raise NeWazaCatalogError(
                f"duplicate technique_id '{defn.technique_id}' in {path}"
            )
        out[defn.technique_id] = defn
    return out


def _parse_positions_file(
    path: Union[str, Path],
) -> dict[str, NeWazaPositionDefinition]:
    entries = _entries_from(_read_structured_file(path), "positions", path)
    out: dict[str, NeWazaPositionDefinition] = {}
    for entry in entries:
        defn = _parse_position(entry)
        if defn.position_id in out:
            raise NeWazaCatalogError(
                f"duplicate position_id '{defn.position_id}' in {path}"
            )
        out[defn.position_id] = defn
    return out


def _parse_struts_file(
    path: Union[str, Path],
) -> dict[str, DefensiveStrutDefinition]:
    entries = _entries_from(_read_structured_file(path), "struts", path)
    out: dict[str, DefensiveStrutDefinition] = {}
    for entry in entries:
        defn = _parse_strut(entry)
        if defn.strut_id in out:
            raise NeWazaCatalogError(
                f"duplicate strut_id '{defn.strut_id}' in {path}"
            )
        out[defn.strut_id] = defn
    return out


# ---------------------------------------------------------------------------
# Cross-reference resolution
# Pure function; returns a list of issue strings. Called by both the
# raising loader and the collecting validator.
# ---------------------------------------------------------------------------
def collect_cross_reference_issues(catalog: NeWazaCatalog) -> list[str]:
    """Return one descriptive string per dangling cross-reference.

    Empty list means every cross-reference resolves. Order is deterministic
    (techniques → positions → struts, fields in spec order) so callers can
    diff outputs across runs.
    """
    issues: list[str] = []
    strut_ids = set(catalog.struts.keys())
    position_ids = set(catalog.positions.keys())
    technique_ids = set(catalog.techniques.keys())

    for tid, defn in catalog.techniques.items():
        prefix = f"technique '{tid}'"
        for s in defn.applicable_defensive_struts:
            if s not in strut_ids:
                issues.append(f"{prefix}.applicable_defensive_struts: '{s}' not in strut catalog")
        if defn.fires_from_position and defn.fires_from_position not in position_ids:
            issues.append(
                f"{prefix}.fires_from_position: '{defn.fires_from_position}' not in position catalog"
            )
        for f in defn.ne_waza_followup_preferences:
            if f not in technique_ids:
                issues.append(
                    f"{prefix}.ne_waza_followup_preferences: '{f}' not in technique catalog"
                )

    for pid, defn in catalog.positions.items():
        prefix = f"position '{pid}'"
        for s in defn.applicable_defensive_struts:
            if s not in strut_ids:
                issues.append(f"{prefix}.applicable_defensive_struts: '{s}' not in strut catalog")
        for t in defn.terminal_techniques:
            if t not in technique_ids:
                issues.append(
                    f"{prefix}.terminal_techniques: '{t}' not in technique catalog"
                )
        for i, trans in enumerate(defn.induced_transitions):
            if trans.if_uke_strut_activates not in strut_ids:
                issues.append(
                    f"{prefix}.induced_transitions[{i}].if_uke_strut_activates: "
                    f"'{trans.if_uke_strut_activates}' not in strut catalog"
                )
            if trans.tori_can_pivot_to not in technique_ids:
                issues.append(
                    f"{prefix}.induced_transitions[{i}].tori_can_pivot_to: "
                    f"'{trans.tori_can_pivot_to}' not in technique catalog"
                )

    return issues


def load_ne_waza_catalog(
    techniques_path: Union[str, Path] = Path("data/ne_waza_techniques.yaml"),
    positions_path: Union[str, Path] = Path("data/ne_waza_positions.yaml"),
    struts_path: Union[str, Path] = Path("data/defensive_struts.yaml"),
) -> NeWazaCatalog:
    """Load and cross-reference-validate the three ne-waza catalog files.

    Raises NeWazaCatalogError on any per-entry schema violation, any
    duplicate id within a file, or any dangling cross-reference between
    the three files. The validator (src/ne_waza_catalog_validator.py)
    wraps this and surfaces failures as a single load_error in its
    ValidationReport.
    """
    catalog = NeWazaCatalog(
        techniques=_parse_techniques_file(techniques_path),
        positions=_parse_positions_file(positions_path),
        struts=_parse_struts_file(struts_path),
    )
    xref_issues = collect_cross_reference_issues(catalog)
    if xref_issues:
        joined = "\n  - " + "\n  - ".join(xref_issues)
        raise NeWazaCatalogError(
            f"ne-waza catalog cross-reference resolution failed:{joined}"
        )
    return catalog
