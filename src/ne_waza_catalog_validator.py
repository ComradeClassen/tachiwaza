# ne_waza_catalog_validator.py
# Ne-waza catalog validation tooling (HAJ-215).
#
# Sibling to src/catalog_validator.py (tachiwaza). Wraps the ne-waza
# loader and runs:
#
#   - Cross-reference integrity in collecting mode (loader raises on
#     first dangling; this collects all of them in a single report)
#   - Symmetry between technique.fires_from_position and
#     position.terminal_techniques (both directions)
#   - Warnings: joint_lock missing mechanical_class, dead struts (not
#     referenced by any technique or position), single-terminal positions
#     (per spec §3 dominant positions should have 2+ terminals), techniques
#     authored with no applicable_defensive_struts.
#
# Loader-level findings (enum membership, missing required fields, etc.)
# surface as a single fatal load_error rather than being re-checked here.
#
# Usage (from repo root):
#
#   python src/ne_waza_catalog_validator.py
#   python src/ne_waza_catalog_validator.py \
#       data/ne_waza_techniques.yaml data/ne_waza_positions.yaml \
#       data/defensive_struts.yaml --quiet
#   python src/ne_waza_catalog_validator.py --no-warnings --no-infos
#
# Exit codes:
#   0 — no errors (warnings/infos may be present unless suppressed)
#   1 — errors present, or any catalog file failed to load

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, Union

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from ne_waza_catalog import (  # noqa: E402
    NeWazaCatalog,
    NeWazaCatalogError,
    NeWazaSubfamily,
    NeWazaTechniqueDefinition,
    _parse_positions_file,
    _parse_struts_file,
    _parse_techniques_file,
    collect_cross_reference_issues,
)


# ===========================================================================
# REPORT MODEL — mirrors src/catalog_validator.py so output reads identically
# ===========================================================================
class Severity(Enum):
    ERROR   = "error"
    WARNING = "warning"
    INFO    = "info"


@dataclass(frozen=True)
class ValidationIssue:
    severity: Severity
    code: str
    message: str
    entity_id: Optional[str] = None
    field: Optional[str] = None

    def format_line(self) -> str:
        head = f"[{self.severity.value.upper()}]"
        loc = self.entity_id or "<catalog>"
        if self.field:
            loc = f"{loc}.{self.field}"
        return f"{head} {self.code} @ {loc}: {self.message}"


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)
    total_techniques: int = 0
    total_positions: int = 0
    total_struts: int = 0
    subfamily_counts: dict[str, int] = field(default_factory=dict)
    load_error: Optional[str] = None

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is Severity.WARNING]

    @property
    def infos(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is Severity.INFO]

    @property
    def is_valid(self) -> bool:
        return self.load_error is None and not self.errors

    def format_text(self, *, include_warnings: bool = True, include_infos: bool = True) -> str:
        if self.load_error is not None:
            return f"[FATAL] ne-waza catalog failed to load: {self.load_error}\n"
        lines: list[str] = []
        for issue in self.errors:
            lines.append(issue.format_line())
        if include_warnings:
            for issue in self.warnings:
                lines.append(issue.format_line())
        if include_infos:
            for issue in self.infos:
                lines.append(issue.format_line())

        lines.append("")
        lines.append(f"  techniques: {self.total_techniques}")
        lines.append(f"  positions:  {self.total_positions}")
        lines.append(f"  struts:     {self.total_struts}")
        if self.subfamily_counts:
            lines.append("  by subfamily:")
            for sf in (s.value for s in NeWazaSubfamily):
                count = self.subfamily_counts.get(sf, 0)
                lines.append(f"    {sf:<12} {count}")
        lines.append(
            f"  errors: {len(self.errors)}  "
            f"warnings: {len(self.warnings)}  "
            f"infos: {len(self.infos)}"
        )
        return "\n".join(lines) + "\n"


# ===========================================================================
# CHECKS
# ===========================================================================
def _check_cross_references(catalog: NeWazaCatalog) -> list[ValidationIssue]:
    """Re-run the loader's cross-ref pass, but as collecting issues so the
    author sees every dangling reference in one report instead of one at
    a time."""
    return [
        ValidationIssue(
            severity=Severity.ERROR,
            code="dangling_cross_reference",
            message=msg,
        )
        for msg in collect_cross_reference_issues(catalog)
    ]


def _check_symmetry(catalog: NeWazaCatalog) -> list[ValidationIssue]:
    """Bidirectional check between techniques and dominant positions.

    Forward: every technique with fires_from_position=X must appear in
    position X's terminal_techniques.
    Reverse: every technique listed in a position's terminal_techniques
    should have fires_from_position pointing back at that position.
    """
    issues: list[ValidationIssue] = []
    for tid, defn in catalog.techniques.items():
        if not defn.fires_from_position:
            continue
        pos = catalog.positions.get(defn.fires_from_position)
        if pos is None:
            continue   # already reported by cross-ref check
        if tid not in pos.terminal_techniques:
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                code="symmetry_terminal_missing",
                entity_id=tid,
                field="fires_from_position",
                message=(
                    f"technique declares fires_from_position='{defn.fires_from_position}' "
                    f"but that position's terminal_techniques does not include '{tid}'"
                ),
            ))

    for pid, pos in catalog.positions.items():
        for t in pos.terminal_techniques:
            tech = catalog.techniques.get(t)
            if tech is None:
                continue   # already reported by cross-ref check
            if tech.fires_from_position != pid:
                issues.append(ValidationIssue(
                    severity=Severity.ERROR,
                    code="symmetry_fires_from_mismatch",
                    entity_id=pid,
                    field="terminal_techniques",
                    message=(
                        f"position lists '{t}' as a terminal but that technique's "
                        f"fires_from_position is "
                        f"{('null' if tech.fires_from_position is None else repr(tech.fires_from_position))}, "
                        f"not '{pid}'"
                    ),
                ))
    return issues


def _check_joint_lock_mechanical_class(
    defn: NeWazaTechniqueDefinition,
) -> list[ValidationIssue]:
    """Joint locks should declare a mechanical class so the resolver can
    pick the right defensive applicability (spec §6). Warning, not error
    — early authoring may leave it null."""
    if defn.subfamily is not NeWazaSubfamily.JOINT_LOCK:
        return []
    if defn.mechanical_class is not None:
        return []
    return [ValidationIssue(
        severity=Severity.WARNING,
        code="joint_lock_missing_mechanical_class",
        entity_id=defn.technique_id,
        field="mechanical_class",
        message="joint_lock subfamily without mechanical_class set; resolver cannot pick lever class",
    )]


def _check_struts_authored(
    defn: NeWazaTechniqueDefinition,
) -> list[ValidationIssue]:
    """Empty applicable_defensive_struts is almost always an authoring
    oversight — every named ne-waza technique has at least one canonical
    defense in Kodokan-Judo."""
    if defn.applicable_defensive_struts:
        return []
    return [ValidationIssue(
        severity=Severity.WARNING,
        code="empty_applicable_defensive_struts",
        entity_id=defn.technique_id,
        field="applicable_defensive_struts",
        message="no defensive struts listed; likely incomplete authoring",
    )]


def _check_dead_struts(catalog: NeWazaCatalog) -> list[ValidationIssue]:
    """Surface struts that aren't referenced by any technique or position.

    Warning, not error — a strut might be authored ahead of the techniques
    it defends. Useful as authoring-completeness signal.
    """
    referenced: set[str] = set()
    for defn in catalog.techniques.values():
        referenced.update(defn.applicable_defensive_struts)
    for pos in catalog.positions.values():
        referenced.update(pos.applicable_defensive_struts)
        for trans in pos.induced_transitions:
            referenced.add(trans.if_uke_strut_activates)

    issues: list[ValidationIssue] = []
    for sid in catalog.struts:
        if sid not in referenced:
            issues.append(ValidationIssue(
                severity=Severity.WARNING,
                code="dead_strut",
                entity_id=sid,
                message="strut not referenced by any technique or position",
            ))
    return issues


def _check_single_terminal_positions(catalog: NeWazaCatalog) -> list[ValidationIssue]:
    """Per spec §3.2 / §3.4, dominant positions exist precisely because
    they offer 2+ named terminals. A single-terminal position belongs as
    `parent_position` on the technique, not as a position entry.
    Warning, not error — authoring may stage entries incrementally.
    """
    issues: list[ValidationIssue] = []
    for pid, pos in catalog.positions.items():
        if len(pos.terminal_techniques) < 2:
            issues.append(ValidationIssue(
                severity=Severity.WARNING,
                code="dominant_position_too_few_terminals",
                entity_id=pid,
                field="terminal_techniques",
                message=(
                    f"dominant position has {len(pos.terminal_techniques)} terminal(s); "
                    "spec §3 expects 2+ (single-terminal positions should be "
                    "parent_position on the technique instead)"
                ),
            ))
    return issues


def _compute_subfamily_counts(catalog: NeWazaCatalog) -> dict[str, int]:
    counts: dict[str, int] = {sf.value: 0 for sf in NeWazaSubfamily}
    for defn in catalog.techniques.values():
        counts[defn.subfamily.value] += 1
    return counts


# ===========================================================================
# ENTRY POINTS
# ===========================================================================
def validate_catalog(catalog: NeWazaCatalog) -> ValidationReport:
    """Run all collecting checks against an already-loaded catalog."""
    issues: list[ValidationIssue] = []

    issues.extend(_check_cross_references(catalog))
    issues.extend(_check_symmetry(catalog))

    for defn in catalog.techniques.values():
        issues.extend(_check_joint_lock_mechanical_class(defn))
        issues.extend(_check_struts_authored(defn))

    issues.extend(_check_dead_struts(catalog))
    issues.extend(_check_single_terminal_positions(catalog))

    return ValidationReport(
        issues=issues,
        total_techniques=len(catalog.techniques),
        total_positions=len(catalog.positions),
        total_struts=len(catalog.struts),
        subfamily_counts=_compute_subfamily_counts(catalog),
    )


def validate_catalog_files(
    techniques_path: Union[str, Path] = Path("data/ne_waza_techniques.yaml"),
    positions_path: Union[str, Path] = Path("data/ne_waza_positions.yaml"),
    struts_path: Union[str, Path] = Path("data/defensive_struts.yaml"),
) -> ValidationReport:
    """Load and validate the three ne-waza catalog files.

    Uses the per-file parsers directly (not the public load_ne_waza_catalog)
    so cross-ref violations surface as a full list of issues rather than
    halting at the first one. Per-entry schema failures still abort with
    a fatal load_error since downstream checks can't run on a malformed
    catalog.
    """
    import json
    import yaml
    try:
        catalog = NeWazaCatalog(
            techniques=_parse_techniques_file(techniques_path),
            positions=_parse_positions_file(positions_path),
            struts=_parse_struts_file(struts_path),
        )
    except NeWazaCatalogError as exc:
        return ValidationReport(load_error=str(exc))
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        return ValidationReport(load_error=f"{type(exc).__name__}: {exc}")
    return validate_catalog(catalog)


# ===========================================================================
# CLI
# ===========================================================================
def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ne_waza_catalog_validator",
        description=(
            "Validate the ne-waza catalog (techniques + positions + struts) "
            "beyond loader-level checks. Reports cross-reference dangling, "
            "symmetry violations between techniques and dominant positions, "
            "and authoring-incompleteness warnings."
        ),
    )
    parser.add_argument(
        "techniques_file",
        type=Path,
        nargs="?",
        default=Path("data/ne_waza_techniques.yaml"),
        help="Path to ne-waza techniques YAML (default: data/ne_waza_techniques.yaml)",
    )
    parser.add_argument(
        "positions_file",
        type=Path,
        nargs="?",
        default=Path("data/ne_waza_positions.yaml"),
        help="Path to ne-waza positions YAML (default: data/ne_waza_positions.yaml)",
    )
    parser.add_argument(
        "struts_file",
        type=Path,
        nargs="?",
        default=Path("data/defensive_struts.yaml"),
        help="Path to defensive struts YAML (default: data/defensive_struts.yaml)",
    )
    parser.add_argument("--no-warnings", action="store_true",
                        help="Suppress warning-level findings from the printed report")
    parser.add_argument("--no-infos", action="store_true",
                        help="Suppress info-level findings from the printed report")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress the report entirely; rely on exit code only")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    report = validate_catalog_files(
        args.techniques_file, args.positions_file, args.struts_file
    )
    if not args.quiet:
        reconfigure = getattr(sys.stdout, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass
        sys.stdout.write(report.format_text(
            include_warnings=not args.no_warnings,
            include_infos=not args.no_infos,
        ))
    return 0 if report.is_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
