# technique_catalog.py
# Schema + loader for the technique vocabulary substrate (HAJ-204, revised HAJ-213).
#
# Implements:
#   - TechniqueDefinition       — one entry in the canonical catalog
#   - TechniqueRecord           — per-judoka per-technique state
#   - TechniqueNamingOverlay    — dojo-local custom names
#   - load_catalog              — YAML/JSON → dict[technique_id, TechniqueDefinition]
#   - load_naming_overlays      — YAML/JSON → dict[(dojo_id, technique_id), overlay]
#
# Schema is locked by design-notes/triage/technique-vocabulary-system.md v1.2.
# Section 2 defines TechniqueDefinition and TechniqueNamingOverlay.
# Section 5 defines TechniqueRecord and its bidirectional ledger.
#
# HAJ-213 schema revision (v1.2): canonical_grip_signatures is a list (was a
# single signature) to express genuine multi-configuration variants; each
# signature carries mirror_eligible (engine auto-mirrors for opposite-stance
# judoka, not authored explicitly). kuzushi_vector split into admissible
# (required, gates Stage 2 selection) + primary (optional, scoring/prose).
# Admissible accepts the `any` wildcard for omnidirectional techniques.
#
# Validation here is intentionally basic: required fields, enum membership,
# grip-signature internal shape, kuzushi-vector parsing, sensible eras.
# Cross-technique and physics-substrate validation is HAJ-211.
# Catalog content (40–60 techniques) is HAJ-205.

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Union


# ---------------------------------------------------------------------------
# CATALOG ENUMS
# Mirror the schema in technique-vocabulary-system.md Section 2.
# Plain string-valued enums keep YAML/JSON round-trip trivial.
# ---------------------------------------------------------------------------
class TechniqueFamily(Enum):
    TE_WAZA     = "te_waza"
    KOSHI_WAZA  = "koshi_waza"
    ASHI_WAZA   = "ashi_waza"
    SUTEMI_WAZA = "sutemi_waza"
    NE_WAZA     = "ne_waza"


class KodokanStatus(Enum):
    GOKYO_NO_WAZA      = "gokyo_no_waza"
    SHINMEISHO_NO_WAZA = "shinmeisho_no_waza"
    HABUKARETA_WAZA    = "habukareta_waza"
    NON_KODOKAN        = "non_kodokan"  # named regional variants etc.


class GripHand(Enum):
    TORI_LEFT  = "tori_left"
    TORI_RIGHT = "tori_right"


class GripTargetRegion(Enum):
    UKE_LAPEL_HIGH   = "uke_lapel_high"
    UKE_LAPEL_LOW    = "uke_lapel_low"
    UKE_SLEEVE_UPPER = "uke_sleeve_upper"
    UKE_SLEEVE_LOWER = "uke_sleeve_lower"
    UKE_BACK         = "uke_back"
    UKE_BELT         = "uke_belt"
    # Hand-on-limb regions (Shinmeisho no Waza leg-grab throws — morote-gari,
    # kuchiki-taoshi, kibisu-gaeshi). minimum_depth is less semantically loaded
    # for these (no gi to grasp shallow-vs-deep), but the schema shape stays
    # uniform; authors should pick `controlled` as the neutral default.
    UKE_LEG_OUTER    = "uke_leg_outer"    # outside of thigh/calf
    UKE_LEG_INNER    = "uke_leg_inner"    # inside of thigh/calf
    UKE_HEEL         = "uke_heel"         # heel / ankle (kibisu-gaeshi)


class GripDepth(Enum):
    SHALLOW    = "shallow"
    CONTROLLED = "controlled"
    DEEP       = "deep"


class UkePostureRequirement(Enum):
    UPRIGHT_OR_FORWARD_COMPROMISED = "upright_or_forward_compromised"
    BENT_FORWARD                   = "bent_forward"
    EXTENDED_BACKWARD              = "extended_backward"
    ANY                            = "any"


class FailedThrowConsequence(Enum):
    TORI_FALLS_TO_BACK = "tori_falls_to_back"
    TORI_TO_KNEES      = "tori_to_knees"
    UKE_LANDS_STOMACH  = "uke_lands_stomach"
    TORI_THROWN        = "tori_thrown"


class ProficiencyTier(Enum):
    """Section 3 — eight-tier proficiency ladder.

    Order is meaningful — use the module-level PROFICIENCY_ORDER list for
    comparisons. `known` is the entry tier and the only tier that does not
    decay (Section 6).
    """
    KNOWN        = "known"
    NOVICE       = "novice"
    PROFICIENT   = "proficient"
    INTERMEDIATE = "intermediate"
    COMPETITIVE  = "competitive"
    EXPERT       = "expert"
    MASTER       = "master"
    LEGENDARY    = "legendary"


PROFICIENCY_ORDER: list[ProficiencyTier] = [
    ProficiencyTier.KNOWN,
    ProficiencyTier.NOVICE,
    ProficiencyTier.PROFICIENT,
    ProficiencyTier.INTERMEDIATE,
    ProficiencyTier.COMPETITIVE,
    ProficiencyTier.EXPERT,
    ProficiencyTier.MASTER,
    ProficiencyTier.LEGENDARY,
]


class AcquisitionSource(Enum):
    """Section 4 — vocabulary acquisition pathways."""
    SENSEI_TAUGHT        = "sensei_taught"
    THROWN_BY_OPPONENT   = "thrown_by_opponent"
    THROWN_BY_SENPAI     = "thrown_by_senpai"
    ACCIDENTAL_DISCOVERY = "accidental_discovery"
    DEDICATED_STUDY      = "dedicated_study"
    SEMINAR              = "seminar"


class NamingType(Enum):
    DOJO      = "dojo"
    SENSEI    = "sensei"
    HYBRID    = "hybrid"
    FREE_TEXT = "free_text"


# ---------------------------------------------------------------------------
# STAGE 1 — GRIP SIGNATURE
# Section 2 (v1.2) — `canonical_grip_signatures` is a list of these. A
# technique is Stage 1-available if ANY signature in the list is satisfied.
# Most techniques have a single-entry list; multi-entry lists express
# genuinely distinct grip variants of the same technique (e.g., classic
# vs. one-handed seoi-nage).
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class GripSpec:
    """One grip a signature names.

    Each signature's tori_required_grips / uke_disqualifying_grips contain
    a list of these.
    """
    hand: GripHand
    target_region: GripTargetRegion
    minimum_depth: GripDepth


@dataclass
class GripSignature:
    """One valid grip configuration for a technique.

    `mirror_eligible` declares the engine should auto-mirror this signature
    for opposite-stance judoka at Stage 1 filter time. Authors record only
    the canonical (right-stance) configuration; lefty equivalents are
    handled by the judoka substrate downstream, not by listing duplicate
    entries here.
    """
    tori_required_grips: list[GripSpec] = field(default_factory=list)
    uke_disqualifying_grips: list[GripSpec] = field(default_factory=list)
    mirror_eligible: bool = True


# ---------------------------------------------------------------------------
# KUZUSHI VECTORS
# Section 2 (v1.2) splits the v1.1 `kuzushi_vector` into:
#   - admissible_kuzushi_vectors — required; gates Stage 2 selection. The
#     special token "any" is a wildcard meaning all directions (used for
#     omnidirectional techniques like foot sweeps).
#   - primary_kuzushi_vectors    — optional; subset of admissible used for
#     scoring quality and prose surfaces. Defaults to a copy of admissible.
# Full physics-substrate validation remains HAJ-211.
# ---------------------------------------------------------------------------
KUZUSHI_ANY_TOKEN = "any"

KUZUSHI_DIRECTION_TOKENS: frozenset[str] = frozenset({
    "forward_pure",
    "forward_right_diagonal",
    "forward_left_diagonal",
    "rear_pure",
    "direct_rear",
    "rear_right_diagonal",
    "rear_left_diagonal",
    "side_right",
    "side_left",
})


@dataclass
class TechniqueDefinition:
    """One entry in the canonical technique catalog.

    Schema mirrors design-notes/triage/technique-vocabulary-system.md
    Section 2 (v1.2). Field order matches the design doc's section order so
    the YAML is readable next to the spec.
    """
    # Identity
    technique_id: str
    name_japanese: str
    name_english: str

    # Classification
    family: TechniqueFamily
    subfamily: str
    kodokan_status: KodokanStatus

    # Stage 1 — availability (list: any signature satisfied → available)
    canonical_grip_signatures: list[GripSignature]

    # Stage 2 — kinetic preconditions
    admissible_kuzushi_vectors: list[str]               # ["any"] wildcard supported
    couple_type: str
    posture_requirements: UkePostureRequirement

    # Difficulty & pedagogy
    base_difficulty: int                                # 0–100

    # Optional Stage 2 — primary (scoring/prose); defaults to admissible.
    primary_kuzushi_vectors: list[str] = field(default_factory=list)

    pedagogical_prerequisites: list[str] = field(default_factory=list)
    minimum_belt_for_competition_use: Optional[str] = None

    # Ne-waza linkage
    failed_throw_consequence: Optional[FailedThrowConsequence] = None
    ne_waza_followup_preferences: list[str] = field(default_factory=list)

    # Era
    era_introduced: Optional[int] = None
    era_restricted: Optional[int] = None

    # Kodokan Gokyo no Waza kyo grouping (1–5). Only meaningful when
    # kodokan_status == gokyo_no_waza; left unset for Shinmeisho /
    # Habukareta / non-Kodokan techniques. Preserves source-book
    # organisation for curriculum ordering and in-game lore surfacing.
    gokyo_kyo: Optional[int] = None

    def is_omnidirectional(self) -> bool:
        """True if admissible_kuzushi_vectors uses the `any` wildcard."""
        return KUZUSHI_ANY_TOKEN in self.admissible_kuzushi_vectors


# ---------------------------------------------------------------------------
# PER-JUDOKA RECORD
# Section 5 — the bidirectional ledger.
# ---------------------------------------------------------------------------
@dataclass
class TechniqueRecord:
    technique_id: str
    proficiency_tier: ProficiencyTier = ProficiencyTier.KNOWN
    proficiency_progress: int = 0                       # 0–100 toward next tier
    teaching_tier: ProficiencyTier = ProficiencyTier.KNOWN  # peak; does not decay

    # Offensive ledger
    executed_attempts: int = 0
    executed_successes: int = 0
    executed_ippons: int = 0
    last_executed_year: Optional[int] = None

    # Defensive ledger
    defended_attempts: int = 0
    defended_successes: int = 0
    defended_ippon_losses: int = 0
    last_defended_year: Optional[int] = None

    # Acquisition provenance
    source_of_acquisition: Optional[AcquisitionSource] = None
    year_acquired: Optional[int] = None
    acquired_from: Optional[str] = None                 # entity reference

    # Disuse tracking
    last_used_year: Optional[int] = None


# ---------------------------------------------------------------------------
# NAMING OVERLAY
# Section 2 — the dojo-local custom-name layer. Lives in its own file from
# day one because it grows during play, not at authoring time.
# ---------------------------------------------------------------------------
@dataclass
class TechniqueNamingOverlay:
    dojo_id: str
    technique_id: str
    custom_name: str
    named_by: str                                       # judoka or sensei id
    year_named: int
    triggering_event: str
    parent_overlay: Optional[tuple[str, str]] = None    # (dojo_id, technique_id)
    naming_type: Optional[NamingType] = None


# ===========================================================================
# LOADER
# ===========================================================================
class CatalogValidationError(ValueError):
    """Raised when a catalog or overlay file fails basic schema validation.

    The message names the offending entry by technique_id (or dojo+technique
    for overlays) plus the specific field, so authoring errors point at the
    right line of YAML.
    """


def _read_structured_file(path: Union[str, Path]) -> Any:
    """Read .yaml/.yml/.json from disk into a Python structure.

    YAML is preferred per the design doc; JSON support is here so the
    catalog can be persisted from tooling without a YAML dependency
    downstream. The format is chosen by extension.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        import yaml  # local import keeps JSON-only callers dependency-free
        return yaml.safe_load(text)
    if suffix == ".json":
        return json.loads(text)
    raise CatalogValidationError(
        f"Unsupported catalog file extension '{suffix}' for {path}; "
        "expected .yaml, .yml, or .json"
    )


# ---------------------------------------------------------------------------
# enum coercion
# Accepts either a raw value ("te_waza") or the enum name ("TE_WAZA"), so
# hand-authored YAML can use whichever is more readable.
# ---------------------------------------------------------------------------
def _coerce_enum(enum_cls: type[Enum], raw: Any, *, context: str) -> Enum:
    if isinstance(raw, enum_cls):
        return raw
    if not isinstance(raw, str):
        raise CatalogValidationError(
            f"{context}: expected string for {enum_cls.__name__}, got {type(raw).__name__}"
        )
    for member in enum_cls:
        if raw == member.value or raw.upper() == member.name:
            return member
    valid = ", ".join(m.value for m in enum_cls)
    raise CatalogValidationError(
        f"{context}: '{raw}' is not a valid {enum_cls.__name__}; expected one of: {valid}"
    )


def _require_field(data: dict, field_name: str, context: str) -> Any:
    if field_name not in data:
        raise CatalogValidationError(f"{context}: missing required field '{field_name}'")
    value = data[field_name]
    if value is None:
        raise CatalogValidationError(f"{context}: required field '{field_name}' is null")
    return value


def _parse_grip_spec(raw: dict, context: str) -> GripSpec:
    if not isinstance(raw, dict):
        raise CatalogValidationError(f"{context}: grip spec must be a mapping")
    return GripSpec(
        hand=_coerce_enum(GripHand, _require_field(raw, "hand", context), context=context),
        target_region=_coerce_enum(
            GripTargetRegion, _require_field(raw, "target_region", context), context=context
        ),
        minimum_depth=_coerce_enum(
            GripDepth, _require_field(raw, "minimum_depth", context), context=context
        ),
    )


def _parse_grip_signature(raw: Any, context: str) -> GripSignature:
    if not isinstance(raw, dict):
        raise CatalogValidationError(
            f"{context}: grip signature must be a mapping"
        )
    tori_raw = raw.get("tori_required_grips", []) or []
    uke_raw = raw.get("uke_disqualifying_grips", []) or []
    if not isinstance(tori_raw, list) or not isinstance(uke_raw, list):
        raise CatalogValidationError(
            f"{context}: grip signature lists must be sequences"
        )
    mirror_raw = raw.get("mirror_eligible", True)
    if not isinstance(mirror_raw, bool):
        raise CatalogValidationError(
            f"{context}.mirror_eligible: expected boolean, got {type(mirror_raw).__name__}"
        )
    return GripSignature(
        tori_required_grips=[
            _parse_grip_spec(g, f"{context}.tori_required_grips[{i}]")
            for i, g in enumerate(tori_raw)
        ],
        uke_disqualifying_grips=[
            _parse_grip_spec(g, f"{context}.uke_disqualifying_grips[{i}]")
            for i, g in enumerate(uke_raw)
        ],
        mirror_eligible=mirror_raw,
    )


def _parse_grip_signatures(raw: Any, context: str) -> list[GripSignature]:
    if not isinstance(raw, list) or not raw:
        raise CatalogValidationError(
            f"{context}: canonical_grip_signatures must be a non-empty list of grip signatures"
        )
    return [
        _parse_grip_signature(sig, f"{context}[{i}]")
        for i, sig in enumerate(raw)
    ]


def _parse_admissible_kuzushi(raw: Any, context: str) -> list[str]:
    """Parse admissible_kuzushi_vectors.

    Accepts the literal string `any` (treated as `[\"any\"]`) or a non-empty
    list of direction tokens. The `any` wildcard may appear inside a list,
    in which case the list must contain only that token.
    """
    if isinstance(raw, str):
        if raw != KUZUSHI_ANY_TOKEN:
            raise CatalogValidationError(
                f"{context}: scalar string only valid as '{KUZUSHI_ANY_TOKEN}' wildcard, got {raw!r}"
            )
        return [KUZUSHI_ANY_TOKEN]
    if not isinstance(raw, list) or not raw:
        raise CatalogValidationError(
            f"{context}: admissible_kuzushi_vectors must be the '{KUZUSHI_ANY_TOKEN}' wildcard "
            "or a non-empty list of direction tokens"
        )
    if KUZUSHI_ANY_TOKEN in raw and len(raw) > 1:
        raise CatalogValidationError(
            f"{context}: '{KUZUSHI_ANY_TOKEN}' wildcard cannot be combined with explicit directions"
        )
    if raw == [KUZUSHI_ANY_TOKEN]:
        return [KUZUSHI_ANY_TOKEN]
    unknown = [v for v in raw if v not in KUZUSHI_DIRECTION_TOKENS]
    if unknown:
        valid = ", ".join(sorted(KUZUSHI_DIRECTION_TOKENS))
        raise CatalogValidationError(
            f"{context}: unknown kuzushi direction(s) {unknown}; expected from: {valid}"
        )
    return list(raw)


def _parse_primary_kuzushi(
    raw: Any,
    admissible: list[str],
    context: str,
) -> list[str]:
    """Parse primary_kuzushi_vectors (optional).

    If omitted, returns a copy of admissible. If given, must be a non-empty
    list of direction tokens, each present in admissible — except when
    admissible is the `any` wildcard, in which case primary may be any
    subset of known directions.
    """
    if raw is None:
        return list(admissible)
    if not isinstance(raw, list) or not raw:
        raise CatalogValidationError(
            f"{context}: primary_kuzushi_vectors must be a non-empty list of direction tokens"
        )
    if KUZUSHI_ANY_TOKEN in raw:
        raise CatalogValidationError(
            f"{context}: primary_kuzushi_vectors cannot contain the '{KUZUSHI_ANY_TOKEN}' wildcard; "
            "primary directions must be explicit"
        )
    unknown = [v for v in raw if v not in KUZUSHI_DIRECTION_TOKENS]
    if unknown:
        valid = ", ".join(sorted(KUZUSHI_DIRECTION_TOKENS))
        raise CatalogValidationError(
            f"{context}: unknown kuzushi direction(s) {unknown}; expected from: {valid}"
        )
    if admissible != [KUZUSHI_ANY_TOKEN]:
        not_in_admissible = [v for v in raw if v not in admissible]
        if not_in_admissible:
            raise CatalogValidationError(
                f"{context}: primary direction(s) {not_in_admissible} not in admissible_kuzushi_vectors {admissible}"
            )
    return list(raw)


def _validate_era(raw: Any, context: str, field_name: str) -> Optional[int]:
    if raw is None:
        return None
    if not isinstance(raw, int):
        raise CatalogValidationError(
            f"{context}: {field_name} must be an integer year, got {type(raw).__name__}"
        )
    # Sensible bounds: judo formalised 1882; chronicle horizon extends past 2100.
    if raw < 1800 or raw > 2200:
        raise CatalogValidationError(
            f"{context}: {field_name} year {raw} is outside the sensible range [1800, 2200]"
        )
    return raw


def _parse_definition(raw: Any) -> TechniqueDefinition:
    if not isinstance(raw, dict):
        raise CatalogValidationError(
            f"technique entry must be a mapping, got {type(raw).__name__}"
        )
    technique_id = _require_field(raw, "technique_id", "<unidentified entry>")
    if not isinstance(technique_id, str) or not technique_id:
        raise CatalogValidationError(
            f"<unidentified entry>: technique_id must be a non-empty string"
        )
    ctx = f"technique '{technique_id}'"

    base_difficulty = _require_field(raw, "base_difficulty", ctx)
    if not isinstance(base_difficulty, int) or not (0 <= base_difficulty <= 100):
        raise CatalogValidationError(
            f"{ctx}: base_difficulty must be an integer in [0, 100], got {base_difficulty!r}"
        )

    failed_consequence_raw = raw.get("failed_throw_consequence")
    failed_consequence = (
        _coerce_enum(FailedThrowConsequence, failed_consequence_raw, context=f"{ctx}.failed_throw_consequence")
        if failed_consequence_raw is not None else None
    )

    era_introduced = _validate_era(raw.get("era_introduced"), ctx, "era_introduced")
    era_restricted = _validate_era(raw.get("era_restricted"), ctx, "era_restricted")
    if era_introduced is not None and era_restricted is not None and era_restricted < era_introduced:
        raise CatalogValidationError(
            f"{ctx}: era_restricted ({era_restricted}) precedes era_introduced ({era_introduced})"
        )

    gokyo_kyo_raw = raw.get("gokyo_kyo")
    gokyo_kyo: Optional[int] = None
    if gokyo_kyo_raw is not None:
        if not isinstance(gokyo_kyo_raw, int) or not (1 <= gokyo_kyo_raw <= 5):
            raise CatalogValidationError(
                f"{ctx}: gokyo_kyo must be an integer in [1, 5], got {gokyo_kyo_raw!r}"
            )
        gokyo_kyo = gokyo_kyo_raw

    prereqs = raw.get("pedagogical_prerequisites") or []
    if not isinstance(prereqs, list) or any(not isinstance(p, str) for p in prereqs):
        raise CatalogValidationError(
            f"{ctx}: pedagogical_prerequisites must be a list of technique_id strings"
        )

    followups = raw.get("ne_waza_followup_preferences") or []
    if not isinstance(followups, list) or any(not isinstance(p, str) for p in followups):
        raise CatalogValidationError(
            f"{ctx}: ne_waza_followup_preferences must be a list of technique_id strings"
        )

    admissible = _parse_admissible_kuzushi(
        _require_field(raw, "admissible_kuzushi_vectors", ctx),
        f"{ctx}.admissible_kuzushi_vectors",
    )
    primary = _parse_primary_kuzushi(
        raw.get("primary_kuzushi_vectors"),
        admissible,
        f"{ctx}.primary_kuzushi_vectors",
    )

    return TechniqueDefinition(
        technique_id=technique_id,
        name_japanese=_require_field(raw, "name_japanese", ctx),
        name_english=_require_field(raw, "name_english", ctx),
        family=_coerce_enum(TechniqueFamily, _require_field(raw, "family", ctx), context=f"{ctx}.family"),
        subfamily=_require_field(raw, "subfamily", ctx),
        kodokan_status=_coerce_enum(
            KodokanStatus, _require_field(raw, "kodokan_status", ctx), context=f"{ctx}.kodokan_status"
        ),
        canonical_grip_signatures=_parse_grip_signatures(
            _require_field(raw, "canonical_grip_signatures", ctx),
            f"{ctx}.canonical_grip_signatures",
        ),
        admissible_kuzushi_vectors=admissible,
        primary_kuzushi_vectors=primary,
        couple_type=_require_field(raw, "couple_type", ctx),
        posture_requirements=_coerce_enum(
            UkePostureRequirement,
            _require_field(raw, "posture_requirements", ctx),
            context=f"{ctx}.posture_requirements",
        ),
        base_difficulty=base_difficulty,
        pedagogical_prerequisites=list(prereqs),
        minimum_belt_for_competition_use=raw.get("minimum_belt_for_competition_use"),
        failed_throw_consequence=failed_consequence,
        ne_waza_followup_preferences=list(followups),
        era_introduced=era_introduced,
        era_restricted=era_restricted,
        gokyo_kyo=gokyo_kyo,
    )


def load_catalog(path: Union[str, Path]) -> dict[str, TechniqueDefinition]:
    """Load and validate a technique catalog from YAML or JSON.

    The file's top-level structure must be a list of technique mappings, or
    a mapping with a "techniques" key containing such a list. Returns a
    dict keyed by `technique_id`.
    """
    data = _read_structured_file(path)
    if isinstance(data, dict) and "techniques" in data:
        entries = data["techniques"]
    else:
        entries = data
    if not isinstance(entries, list):
        raise CatalogValidationError(
            f"catalog at {path}: top-level must be a list of techniques "
            "(or a mapping with a 'techniques' list)"
        )

    catalog: dict[str, TechniqueDefinition] = {}
    for entry in entries:
        definition = _parse_definition(entry)
        if definition.technique_id in catalog:
            raise CatalogValidationError(
                f"duplicate technique_id '{definition.technique_id}' in {path}"
            )
        catalog[definition.technique_id] = definition
    return catalog


def _parse_overlay(raw: Any) -> TechniqueNamingOverlay:
    if not isinstance(raw, dict):
        raise CatalogValidationError(
            f"naming overlay entry must be a mapping, got {type(raw).__name__}"
        )
    dojo_id = _require_field(raw, "dojo_id", "<unidentified overlay>")
    technique_id = _require_field(raw, "technique_id", f"overlay for dojo '{dojo_id}'")
    ctx = f"overlay ({dojo_id!r}, {technique_id!r})"

    year_named = _require_field(raw, "year_named", ctx)
    if not isinstance(year_named, int) or not (1800 <= year_named <= 2200):
        raise CatalogValidationError(
            f"{ctx}: year_named must be a sensible integer year, got {year_named!r}"
        )

    parent_raw = raw.get("parent_overlay")
    parent: Optional[tuple[str, str]] = None
    if parent_raw is not None:
        if isinstance(parent_raw, dict):
            parent = (
                _require_field(parent_raw, "dojo_id", f"{ctx}.parent_overlay"),
                _require_field(parent_raw, "technique_id", f"{ctx}.parent_overlay"),
            )
        elif isinstance(parent_raw, (list, tuple)) and len(parent_raw) == 2:
            parent = (str(parent_raw[0]), str(parent_raw[1]))
        else:
            raise CatalogValidationError(
                f"{ctx}: parent_overlay must be a mapping with dojo_id/technique_id or a 2-element sequence"
            )

    naming_type_raw = raw.get("naming_type")
    naming_type = (
        _coerce_enum(NamingType, naming_type_raw, context=f"{ctx}.naming_type")
        if naming_type_raw is not None else None
    )

    return TechniqueNamingOverlay(
        dojo_id=dojo_id,
        technique_id=technique_id,
        custom_name=_require_field(raw, "custom_name", ctx),
        named_by=_require_field(raw, "named_by", ctx),
        year_named=year_named,
        triggering_event=_require_field(raw, "triggering_event", ctx),
        parent_overlay=parent,
        naming_type=naming_type,
    )


def load_naming_overlays(
    path: Union[str, Path],
) -> dict[tuple[str, str], TechniqueNamingOverlay]:
    """Load and validate the dojo-local naming overlay file.

    The file may be missing or empty — overlays accumulate during play and
    a fresh world has none. Returns a dict keyed by (dojo_id, technique_id).
    """
    path = Path(path)
    if not path.exists():
        return {}
    data = _read_structured_file(path)
    if data is None:
        return {}
    if isinstance(data, dict) and "overlays" in data:
        entries = data["overlays"]
    else:
        entries = data
    if not isinstance(entries, list):
        raise CatalogValidationError(
            f"naming overlay file {path}: top-level must be a list "
            "(or a mapping with an 'overlays' list)"
        )

    overlays: dict[tuple[str, str], TechniqueNamingOverlay] = {}
    for entry in entries:
        overlay = _parse_overlay(entry)
        key = (overlay.dojo_id, overlay.technique_id)
        if key in overlays:
            raise CatalogValidationError(
                f"duplicate naming overlay for {key} in {path}"
            )
        overlays[key] = overlay
    return overlays
