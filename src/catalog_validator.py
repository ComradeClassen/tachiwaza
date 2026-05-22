# catalog_validator.py
# Catalog validation tooling (HAJ-211).
#
# Wraps src/technique_catalog.py's loader with additional checks beyond
# the loader's own syntactic validation:
#
#   - Cross-technique consistency (pedagogical_prerequisites and
#     ne_waza_followup_preferences resolve to real technique_ids; no
#     circular pedagogical_prerequisites).
#   - Habukareta Waza techniques carry era_restricted.
#   - Non-empty identity strings (loader rejects null; this rejects "").
#   - Suspicious empty grip signatures (warning).
#   - Family classification balance (informational + warning).
#
# Designed to be invoked during HAJ-205 authoring after each batch of
# entries to catch typos early. Loader-level checks (enum membership,
# kuzushi-vector wildcard rules, era year sanity, base_difficulty range,
# duplicate technique_id, etc.) are not duplicated here — they fire from
# the loader and bubble up as a single fatal error.
#
# Usage (from repo root):
#
#   python src/catalog_validator.py data/techniques.yaml
#   python src/catalog_validator.py data/techniques.yaml --quiet
#   python src/catalog_validator.py data/techniques.yaml --no-warnings
#
# Exit codes:
#   0 — no errors (warnings/infos may be present unless suppressed)
#   1 — errors present, or the file failed to load at all

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, Union

# Make src/ importable when invoked directly.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from technique_catalog import (  # noqa: E402
    CatalogValidationError,
    KodokanStatus,
    TechniqueDefinition,
    TechniqueFamily,
    load_catalog,
)


# ===========================================================================
# REPORT MODEL
# ===========================================================================
class Severity(Enum):
    ERROR   = "error"
    WARNING = "warning"
    INFO    = "info"


@dataclass(frozen=True)
class ValidationIssue:
    """One finding from a validation pass.

    `code` is a short, stable identifier (e.g. ``dangling_prereq``) so
    tests can assert on the kind of issue without coupling to the exact
    English message text.
    """
    severity: Severity
    code: str
    message: str
    technique_id: Optional[str] = None
    field: Optional[str] = None

    def format_line(self) -> str:
        head = f"[{self.severity.value.upper()}]"
        loc = self.technique_id or "<catalog>"
        if self.field:
            loc = f"{loc}.{self.field}"
        return f"{head} {self.code} @ {loc}: {self.message}"


@dataclass
class ValidationReport:
    """Aggregated validation result.

    `family_counts` and `total_techniques` are descriptive (not error
    signals) — they appear in the formatted report's summary footer
    regardless of error state.
    """
    issues: list[ValidationIssue] = field(default_factory=list)
    family_counts: dict[TechniqueFamily, int] = field(default_factory=dict)
    total_techniques: int = 0
    load_error: Optional[str] = None    # populated if the loader itself failed

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
        """True iff there are no error-severity findings and the loader succeeded."""
        return self.load_error is None and not self.errors

    def format_text(
        self,
        *,
        include_warnings: bool = True,
        include_infos: bool = True,
        include_summary: bool = True,
    ) -> str:
        """Human-readable multi-line report. The CLI prints this verbatim.

        `include_summary` controls the count/family-balance footer; when
        False, only issue lines are printed. Useful for --errors-only
        invocations where a clean catalog should produce no output.
        """
        if self.load_error is not None:
            return f"[FATAL] catalog failed to load: {self.load_error}\n"
        lines: list[str] = []
        for issue in self.errors:
            lines.append(issue.format_line())
        if include_warnings:
            for issue in self.warnings:
                lines.append(issue.format_line())
        if include_infos:
            for issue in self.infos:
                lines.append(issue.format_line())

        if include_summary:
            lines.append("")
            lines.append(f"  techniques: {self.total_techniques}")
            if self.family_counts:
                lines.append("  by family:")
                for family in TechniqueFamily:
                    count = self.family_counts.get(family, 0)
                    lines.append(f"    {family.value:<12} {count}")
            lines.append(
                f"  errors: {len(self.errors)}  "
                f"warnings: {len(self.warnings)}  "
                f"infos: {len(self.infos)}"
            )
        return ("\n".join(lines) + "\n") if lines else ""


# ===========================================================================
# CHECKS
# Each check function returns a list of issues. None of them mutate the
# catalog. Order is fixed so the formatted report is deterministic across
# runs.
# ===========================================================================
def _check_identity_strings(definition: TechniqueDefinition) -> list[ValidationIssue]:
    """Loader rejects null but accepts empty/whitespace — flag those here."""
    issues: list[ValidationIssue] = []
    for field_name in ("name_japanese", "name_english"):
        value = getattr(definition, field_name)
        if not isinstance(value, str) or not value.strip():
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                code="empty_identity_string",
                technique_id=definition.technique_id,
                field=field_name,
                message=f"{field_name} must be a non-empty string",
            ))
    return issues


def _check_grip_signatures_nonempty(definition: TechniqueDefinition) -> list[ValidationIssue]:
    """A signature with no tori_required_grips is suspicious (HAJ-211 ticket: flag).

    Loader allows it because some authoring intermediate states might be
    valid; flagging at warning level lets the author confirm intent
    without blocking development.
    """
    issues: list[ValidationIssue] = []
    for i, signature in enumerate(definition.canonical_grip_signatures):
        if not signature.tori_required_grips:
            issues.append(ValidationIssue(
                severity=Severity.WARNING,
                code="empty_tori_grips",
                technique_id=definition.technique_id,
                field=f"canonical_grip_signatures[{i}].tori_required_grips",
                message=(
                    "signature has no tori_required_grips — technique is then "
                    "available at any grip configuration, which is almost "
                    "always an authoring oversight"
                ),
            ))
    return issues


def _check_prereqs_resolve(
    definition: TechniqueDefinition,
    known_ids: set[str],
) -> list[ValidationIssue]:
    """pedagogical_prerequisites must resolve to a real technique_id.

    Errors at error severity — pedagogical prerequisites are tachiwaza-
    internal references that must exist before downstream curriculum
    logic (HAJ-207 / Ring 3 sensei AI) can consume them.
    """
    issues: list[ValidationIssue] = []
    for prereq in definition.pedagogical_prerequisites:
        if prereq not in known_ids:
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                code="dangling_prereq",
                technique_id=definition.technique_id,
                field="pedagogical_prerequisites",
                message=f"prerequisite '{prereq}' not found in catalog",
            ))
    return issues


def _check_ne_waza_followups_resolve(
    definition: TechniqueDefinition,
    known_ids: set[str],
    ne_waza_known_ids: Optional[set[str]] = None,
) -> list[ValidationIssue]:
    """ne_waza_followup_preferences must resolve to a real technique_id
    in either the tachiwaza catalog or the ne-waza catalog.

    Behaviour depends on whether `ne_waza_known_ids` was provided
    (cross-catalog mode, HAJ-217):

    - **None** (caller did not load a ne-waza catalog) — skip the check
      entirely. The CLI/file API may add a single summary warning at
      its own layer indicating that cross-catalog checks were skipped.
      Per-reference false-positives are explicitly avoided.
    - **set provided** — a followup resolves if it exists in either
      catalog. Unresolved refs are errors (the catalog now exists, so
      a dangling ref is a real bug, not an authoring-in-progress signal).
    """
    if ne_waza_known_ids is None:
        return []
    issues: list[ValidationIssue] = []
    for followup in definition.ne_waza_followup_preferences:
        if followup in known_ids or followup in ne_waza_known_ids:
            continue
        issues.append(ValidationIssue(
            severity=Severity.ERROR,
            code="dangling_ne_waza_followup",
            technique_id=definition.technique_id,
            field="ne_waza_followup_preferences",
            message=(
                f"ne-waza followup '{followup}' not found in either the "
                "tachiwaza catalog or the ne-waza catalog"
            ),
        ))
    return issues


def _check_no_prereq_cycles(
    catalog: dict[str, TechniqueDefinition],
) -> list[ValidationIssue]:
    """DFS-based cycle detection on the pedagogical_prerequisites graph.

    Cycles are an authoring error: A teaches B teaches C teaches A is not
    a teachable order. Cycles are reported once per detected cycle, with
    the cycle members named so the author can break it.
    """
    issues: list[ValidationIssue] = []
    reported: set[frozenset[str]] = set()

    # Build an adjacency map of only edges that resolve (so cycle
    # detection isn't muddled by dangling references already reported
    # by _check_prereqs_resolve).
    adjacency: dict[str, list[str]] = {
        tid: [p for p in d.pedagogical_prerequisites if p in catalog]
        for tid, d in catalog.items()
    }

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {tid: WHITE for tid in catalog}

    def dfs(start: str) -> None:
        # Iterative DFS with explicit stack so deep prereq chains can't
        # overflow Python's recursion limit.
        stack: list[tuple[str, list[str]]] = [(start, list(adjacency[start]))]
        path: list[str] = [start]
        color[start] = GRAY
        while stack:
            node, remaining = stack[-1]
            if not remaining:
                color[node] = BLACK
                stack.pop()
                path.pop()
                continue
            neighbor = remaining.pop()
            if color[neighbor] == GRAY:
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:]
                key = frozenset(cycle)
                if key not in reported:
                    reported.add(key)
                    cycle_str = " -> ".join(cycle + [neighbor])
                    issues.append(ValidationIssue(
                        severity=Severity.ERROR,
                        code="prereq_cycle",
                        technique_id=neighbor,
                        field="pedagogical_prerequisites",
                        message=f"circular prerequisite chain: {cycle_str}",
                    ))
            elif color[neighbor] == WHITE:
                color[neighbor] = GRAY
                path.append(neighbor)
                stack.append((neighbor, list(adjacency[neighbor])))

    for tid in catalog:
        if color[tid] == WHITE:
            dfs(tid)

    return issues


def _check_habukareta_has_restricted(definition: TechniqueDefinition) -> list[ValidationIssue]:
    """Habukareta Waza techniques are defined by their restricted status.

    If kodokan_status is habukareta_waza, era_restricted must be set —
    otherwise the era filter has nothing to consult and the technique
    will be erroneously available in modern competition.
    """
    if definition.kodokan_status is not KodokanStatus.HABUKARETA_WAZA:
        return []
    if definition.era_restricted is None:
        return [ValidationIssue(
            severity=Severity.ERROR,
            code="habukareta_missing_era_restricted",
            technique_id=definition.technique_id,
            field="era_restricted",
            message=(
                "kodokan_status is habukareta_waza but era_restricted is not "
                "set; habukareta techniques require an era_restricted year"
            ),
        )]
    return []


def _compute_family_counts(
    catalog: dict[str, TechniqueDefinition],
) -> tuple[dict[TechniqueFamily, int], list[ValidationIssue]]:
    """Family balance: counts as info, near-empty families as warnings.

    The 1.0 catalog target is 40–60 entries across 5 families (HAJ-205).
    Per the ticket, "very few entries" in a family signals authoring
    is incomplete — surface as warning so the author knows to fill in.
    """
    counts: dict[TechniqueFamily, int] = {f: 0 for f in TechniqueFamily}
    for definition in catalog.values():
        counts[definition.family] += 1

    issues: list[ValidationIssue] = []
    # Threshold below: 1.0 target is ~8-12 per family, so flag <3 as
    # likely-incomplete during authoring. ne_waza is in scope of HAJ-212
    # so its emptiness is expected until that ticket lands — info-only.
    LOW_THRESHOLD = 3
    for family, count in counts.items():
        if family is TechniqueFamily.NE_WAZA and count == 0:
            issues.append(ValidationIssue(
                severity=Severity.INFO,
                code="ne_waza_family_empty",
                message=(
                    "ne_waza family has 0 entries (expected — ne-waza catalog "
                    "authoring is a separate ticket downstream of HAJ-212)"
                ),
            ))
        elif count == 0:
            issues.append(ValidationIssue(
                severity=Severity.WARNING,
                code="family_empty",
                message=f"family '{family.value}' has 0 entries",
            ))
        elif count < LOW_THRESHOLD:
            issues.append(ValidationIssue(
                severity=Severity.INFO,
                code="family_low",
                message=(
                    f"family '{family.value}' has only {count} "
                    f"entr{'y' if count == 1 else 'ies'} "
                    f"(target: ~8-12 per family in 1.0)"
                ),
            ))
    return counts, issues


# ===========================================================================
# ENTRY POINTS
# ===========================================================================
def validate_catalog(
    catalog: dict[str, TechniqueDefinition],
    *,
    ne_waza_known_ids: Optional[set[str]] = None,
) -> ValidationReport:
    """Run all validation checks against an already-loaded catalog.

    Useful when the caller has the catalog in memory (e.g., tests
    constructing TechniqueDefinition objects directly). For loading from
    disk plus validation, use `validate_catalog_file`.

    `ne_waza_known_ids` enables cross-catalog resolution of
    `ne_waza_followup_preferences` (HAJ-217). When provided, followup
    refs that don't exist in either catalog are flagged as errors.
    When None, the cross-catalog check is skipped entirely — the caller
    (or the CLI) is responsible for deciding whether to emit a
    skipped-catalog summary warning.
    """
    known_ids = set(catalog.keys())
    issues: list[ValidationIssue] = []

    for definition in catalog.values():
        issues.extend(_check_identity_strings(definition))
        issues.extend(_check_grip_signatures_nonempty(definition))
        issues.extend(_check_prereqs_resolve(definition, known_ids))
        issues.extend(_check_ne_waza_followups_resolve(
            definition, known_ids, ne_waza_known_ids,
        ))
        issues.extend(_check_habukareta_has_restricted(definition))

    issues.extend(_check_no_prereq_cycles(catalog))

    family_counts, family_issues = _compute_family_counts(catalog)
    issues.extend(family_issues)

    return ValidationReport(
        issues=issues,
        family_counts=family_counts,
        total_techniques=len(catalog),
    )


def _try_load_ne_waza_known_ids(
    path: Optional[Union[str, Path]],
) -> tuple[Optional[set[str]], Optional[str]]:
    """Best-effort load of ne-waza technique_ids for cross-catalog checks.

    Returns (known_ids, skip_reason):
      - (set, None) on successful load.
      - (None, None) when `path` is None — caller explicitly opted out.
      - (None, str) when `path` was given but loading failed; the string
        is a short human-readable reason suitable for a skip warning.

    The ne-waza catalog loader is imported lazily so this module stays
    usable in environments where the ne-waza substrate isn't installed.
    """
    if path is None:
        return None, None
    p = Path(path)
    if not p.exists():
        return None, f"ne-waza techniques file not found at {p}"
    try:
        from ne_waza_catalog import _parse_techniques_file  # type: ignore
        techniques = _parse_techniques_file(p)
    except Exception as exc:
        return None, f"failed to load ne-waza techniques from {p}: {type(exc).__name__}: {exc}"
    return set(techniques.keys()), None


# Default location used when the caller does not pass an explicit override.
_DEFAULT_NE_WAZA_TECHNIQUES_PATH = Path("data/ne_waza_techniques.yaml")


# Sentinel: distinguishes "caller passed None to opt out" from "caller
# didn't pass anything — apply the module default".
_UNSET = object()


def validate_catalog_file(
    path: Union[str, Path],
    *,
    ne_waza_techniques_path: object = _UNSET,
) -> ValidationReport:
    """Load and validate a catalog file. Loader failures surface as a
    fatal report (errors empty but `load_error` set) since downstream
    checks can't run without a parsed catalog.

    Catches `CatalogValidationError` (loader's schema/enum complaints)
    and YAML/JSON parser errors (raw syntax bugs in the file). Other
    exceptions (FileNotFoundError, PermissionError) propagate — those
    are environment problems, not catalog content problems.

    `ne_waza_techniques_path` controls cross-catalog resolution of
    `ne_waza_followup_preferences` (HAJ-217):
      - omitted → use the repo-default ne-waza techniques path; if that
        file doesn't exist or fails to load, emit ONE summary warning
        and skip the cross-catalog check.
      - explicit path → same best-effort behavior at the given path.
      - explicit None → opt out; no cross-catalog check, no warning.
    """
    import json
    import yaml
    try:
        catalog = load_catalog(path)
    except CatalogValidationError as exc:
        return ValidationReport(load_error=str(exc))
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        # Authoring issues like indentation errors get a clean message
        # instead of a Python stack trace.
        return ValidationReport(load_error=f"{type(exc).__name__}: {exc}")

    if ne_waza_techniques_path is _UNSET:
        effective_ne_waza_path: Optional[Path] = _DEFAULT_NE_WAZA_TECHNIQUES_PATH
    else:
        effective_ne_waza_path = (
            Path(ne_waza_techniques_path)        # type: ignore[arg-type]
            if ne_waza_techniques_path is not None
            else None
        )

    ne_waza_known_ids, skip_reason = _try_load_ne_waza_known_ids(effective_ne_waza_path)
    report = validate_catalog(catalog, ne_waza_known_ids=ne_waza_known_ids)
    if skip_reason is not None:
        # The caller wanted cross-catalog resolution but the ne-waza
        # catalog couldn't be loaded. Emit ONE summary warning instead
        # of fabricating per-reference false positives.
        report.issues.append(ValidationIssue(
            severity=Severity.WARNING,
            code="ne_waza_catalog_skipped",
            message=(
                "cross-catalog ne_waza_followup_preferences check skipped — "
                f"{skip_reason}"
            ),
        ))
    return report


# ===========================================================================
# CLI
# ===========================================================================
def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="catalog_validator",
        description=(
            "Validate the technique catalog beyond loader-level checks. "
            "Reports cross-technique inconsistencies, habukareta era gaps, "
            "and family-balance findings."
        ),
    )
    parser.add_argument(
        "catalog_file",
        type=Path,
        help="Path to a YAML or JSON technique catalog (e.g. data/techniques.yaml)",
    )
    parser.add_argument(
        "--no-warnings",
        action="store_true",
        help="Suppress warning-level findings from the printed report",
    )
    parser.add_argument(
        "--no-infos",
        action="store_true",
        help="Suppress info-level findings from the printed report",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the report entirely; rely on exit code only",
    )
    parser.add_argument(
        "--errors-only",
        action="store_true",
        help=(
            "Suppress warnings, infos, and the count summary footer. "
            "A clean catalog produces no output."
        ),
    )
    parser.add_argument(
        "--ne-waza-techniques",
        type=Path,
        default=None,
        help=(
            "Path to ne-waza techniques YAML for cross-catalog resolution "
            "of ne_waza_followup_preferences. Default: "
            "data/ne_waza_techniques.yaml if present (otherwise skip "
            "cross-catalog check with one summary warning)."
        ),
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    if args.ne_waza_techniques is not None:
        report = validate_catalog_file(
            args.catalog_file,
            ne_waza_techniques_path=args.ne_waza_techniques,
        )
    else:
        # Use the module default (which gracefully skips if absent).
        report = validate_catalog_file(args.catalog_file)

    if not args.quiet:
        # Windows consoles default to cp1252 and mangle em-dashes / Japanese
        # romanization in the messages; force UTF-8 if the stream supports it.
        reconfigure = getattr(sys.stdout, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass        # non-tty streams (pipes, tests) may reject reconfigure
        include_warnings = not (args.no_warnings or args.errors_only)
        include_infos = not (args.no_infos or args.errors_only)
        include_summary = not args.errors_only
        sys.stdout.write(report.format_text(
            include_warnings=include_warnings,
            include_infos=include_infos,
            include_summary=include_summary,
        ))
    return 0 if report.is_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
