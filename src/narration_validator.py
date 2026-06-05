# narration_validator.py
# Throw-narration validation tooling (HAJ-223).
#
# Checks data/throw_narration.yaml for authoring gaps, beyond the loader's
# own structural validation (which already rejects malformed bands, empty
# variant lists, and non-string variants — see throw_narration.py). This
# layer cross-references the *engine* so it can catch content gaps the
# loader can't see:
#
#   - missing_throw_narration (WARNING): a throw in the engine's
#     THROW_TO_TECHNIQUE_ID registry has no entry in the narration file.
#   - missing_phase (ERROR): an authored throw is missing a resolution
#     phase entirely (no clean / standard / sloppy authored, or the phase
#     key absent), or is missing the commit phase.
#   - thin_band (WARNING): a resolution-phase band has fewer than 2
#     variants (the HAJ-223 floor; an absent band counts as 0).
#   - missing_failure_narration (WARNING): a FailureOutcome the engine can
#     emit for this throw (its worked-throws FailureSpec primary/secondary/
#     tertiary) has no narration entry.
#   - thin_failure (WARNING): an authored failure entry has <2 variants.
#   - unknown_throw_narration (INFO): an entry whose key matches no throw
#     in the registry (orphaned authoring — e.g. a renamed ThrowID).
#
# Loader-level checks (band names, variant typing, top-level shape) are not
# duplicated here; they fire from throw_narration.parse_throw_narration and
# surface as a single fatal load error.
#
# Usage (from repo root):
#
#   python src/narration_validator.py data/throw_narration.yaml
#   python src/narration_validator.py data/throw_narration.yaml --errors-only
#   python src/narration_validator.py data/throw_narration.yaml --no-infos
#
# Exit codes:
#   0 — no errors (warnings/infos may be present unless suppressed)
#   1 — errors present, or the file failed to load at all

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

# Make src/ importable when invoked directly.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

# Reuse the shared issue model so tooling and tests speak one vocabulary.
from catalog_validator import Severity, ValidationIssue  # noqa: E402
from execution_quality import (  # noqa: E402
    NARRATION_BAND_CLEAN, NARRATION_BAND_STANDARD, NARRATION_BAND_SLOPPY,
)
from throw_narration import (  # noqa: E402
    PHASE_COMMIT, PHASE_REACH_KUZUSHI, PHASE_KUZUSHI, PHASE_TSUKURI, PHASE_KAKE,
    ThrowNarration, ThrowNarrationLoadError,
    load_throw_narration,
)

_RESOLUTION_PHASES: tuple[str, ...] = (
    PHASE_REACH_KUZUSHI, PHASE_KUZUSHI, PHASE_TSUKURI, PHASE_KAKE,
)
_BANDS: tuple[str, ...] = (
    NARRATION_BAND_CLEAN, NARRATION_BAND_STANDARD, NARRATION_BAND_SLOPPY,
)
_MIN_VARIANTS = 2


# ===========================================================================
# REPORT MODEL
# ===========================================================================
@dataclass
class NarrationValidationReport:
    """Aggregated narration-validation result. Mirrors catalog_validator's
    ValidationReport shape (errors/warnings/infos/is_valid/format_text) so
    callers can treat both uniformly, with a narration-specific footer."""
    issues: list[ValidationIssue] = field(default_factory=list)
    total_throws_authored: int = 0
    total_throws_implemented: int = 0
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

    def format_text(
        self,
        *,
        include_warnings: bool = True,
        include_infos: bool = True,
        include_summary: bool = True,
    ) -> str:
        if self.load_error is not None:
            return f"[FATAL] narration failed to load: {self.load_error}\n"
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
            lines.append(
                f"  throws authored: {self.total_throws_authored} / "
                f"{self.total_throws_implemented} engine-implemented"
            )
            lines.append(
                f"  errors: {len(self.errors)}  "
                f"warnings: {len(self.warnings)}  "
                f"infos: {len(self.infos)}"
            )
        return ("\n".join(lines) + "\n") if lines else ""


# ===========================================================================
# ENGINE INTROSPECTION
# Pulled behind helpers so the checks stay declarative and tests can inject
# their own maps when they want to validate a fixture in isolation.
# ===========================================================================
def _implemented_throws() -> dict[str, object]:
    """narration-key (ThrowID.name.lower()) -> ThrowID, for every throw the
    engine actually implements (has a technique mapping)."""
    from availability import THROW_TO_TECHNIQUE_ID
    return {tid.name.lower(): tid for tid in THROW_TO_TECHNIQUE_ID}


def _engine_failure_outcomes(throw_id) -> list[str]:
    """The lower-snake FailureOutcome names the engine can route this throw
    to — its worked-throws FailureSpec primary/secondary/tertiary. Returns
    [] when the throw has no worked-throws template (no routing to check)."""
    from worked_throws import WORKED_THROWS
    template = WORKED_THROWS.get(throw_id)
    if template is None:
        return []
    spec = getattr(template, "failure_outcome", None)
    if spec is None:
        return []
    out: list[str] = []
    for attr in ("primary", "secondary", "tertiary"):
        outcome = getattr(spec, attr, None)
        if outcome is not None:
            out.append(outcome.name.lower())
    # Preserve order, drop dupes (a spec may repeat an outcome).
    seen: set[str] = set()
    return [o for o in out if not (o in seen or seen.add(o))]


# ===========================================================================
# CHECKS
# Each returns a list of issues; none mutate the data. Order is fixed so the
# formatted report is deterministic.
# ===========================================================================
def _check_phase_coverage(
    key: str, entry: ThrowNarration,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    # commit — required, flat list.
    commit = entry.phases.get(PHASE_COMMIT)
    if not commit:
        issues.append(ValidationIssue(
            severity=Severity.ERROR, code="missing_phase",
            technique_id=key, field=PHASE_COMMIT,
            message="commit phase is missing (required: tori's commit beat)",
        ))
    elif len(commit) < _MIN_VARIANTS:
        issues.append(ValidationIssue(
            severity=Severity.WARNING, code="thin_band",
            technique_id=key, field=PHASE_COMMIT,
            message=(
                f"commit has only {len(commit)} variant(s); "
                f"floor is {_MIN_VARIANTS}"
            ),
        ))

    # four resolution phases — banded.
    for phase in _RESOLUTION_PHASES:
        bucket = entry.phases.get(phase)
        if not isinstance(bucket, dict) or not any(bucket.get(b) for b in _BANDS):
            issues.append(ValidationIssue(
                severity=Severity.ERROR, code="missing_phase",
                technique_id=key, field=phase,
                message=(
                    f"phase '{phase}' is missing entirely "
                    "(no clean / standard / sloppy authored)"
                ),
            ))
            continue
        for band in _BANDS:
            count = len(bucket.get(band) or [])
            if count < _MIN_VARIANTS:
                issues.append(ValidationIssue(
                    severity=Severity.WARNING, code="thin_band",
                    technique_id=key, field=f"{phase}.{band}",
                    message=(
                        f"band '{band}' has {count} variant(s); "
                        f"floor is {_MIN_VARIANTS}"
                    ),
                ))
    return issues


def _check_failure_coverage(
    key: str, entry: ThrowNarration, throw_id,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for outcome_key in _engine_failure_outcomes(throw_id):
        variants = entry.failures.get(outcome_key)
        if not variants:
            issues.append(ValidationIssue(
                severity=Severity.WARNING, code="missing_failure_narration",
                technique_id=key, field=f"failures.{outcome_key}",
                message=(
                    f"engine can emit FailureOutcome '{outcome_key.upper()}' "
                    "for this throw but no narration is authored for it"
                ),
            ))
        elif len(variants) < _MIN_VARIANTS:
            issues.append(ValidationIssue(
                severity=Severity.WARNING, code="thin_failure",
                technique_id=key, field=f"failures.{outcome_key}",
                message=(
                    f"failure '{outcome_key}' has {len(variants)} variant(s); "
                    f"floor is {_MIN_VARIANTS}"
                ),
            ))
    return issues


# ===========================================================================
# ENTRY POINTS
# ===========================================================================
def validate_narration(
    data: dict[str, ThrowNarration],
    *,
    implemented: Optional[dict[str, object]] = None,
) -> NarrationValidationReport:
    """Run all checks against already-loaded narration data.

    `implemented` maps narration-key -> ThrowID for the engine-implemented
    set; defaults to the live THROW_TO_TECHNIQUE_ID registry. Tests can
    inject a fixture map to validate in isolation from the real engine.
    """
    if implemented is None:
        implemented = _implemented_throws()
    issues: list[ValidationIssue] = []

    # 1. Every implemented throw should be authored.
    for impl_key, throw_id in implemented.items():
        entry = data.get(impl_key)
        if entry is None:
            issues.append(ValidationIssue(
                severity=Severity.WARNING, code="missing_throw_narration",
                technique_id=impl_key, field=None,
                message=(
                    "throw is engine-implemented (in THROW_TO_TECHNIQUE_ID) "
                    "but has no entry in the narration file"
                ),
            ))
            continue
        issues.extend(_check_phase_coverage(impl_key, entry))
        issues.extend(_check_failure_coverage(impl_key, entry, throw_id))

    # 2. Orphaned entries — authored but not in the registry.
    for key in data:
        if key not in implemented:
            issues.append(ValidationIssue(
                severity=Severity.INFO, code="unknown_throw_narration",
                technique_id=key, field=None,
                message=(
                    "narration entry matches no throw in THROW_TO_TECHNIQUE_ID "
                    "(orphaned authoring — renamed/unimplemented ThrowID?)"
                ),
            ))

    return NarrationValidationReport(
        issues=issues,
        total_throws_authored=len(data),
        total_throws_implemented=len(implemented),
    )


def validate_narration_file(
    path: Union[str, Path],
) -> NarrationValidationReport:
    """Load and validate a narration file. A load failure surfaces as a
    fatal report (errors empty but load_error set)."""
    try:
        data = load_throw_narration(path)
    except ThrowNarrationLoadError as exc:
        return NarrationValidationReport(load_error=str(exc))
    except Exception as exc:  # YAML syntax etc. — clean message, no stack
        return NarrationValidationReport(
            load_error=f"{type(exc).__name__}: {exc}"
        )
    return validate_narration(data)


# ===========================================================================
# CLI
# ===========================================================================
def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="narration_validator",
        description=(
            "Validate data/throw_narration.yaml against the engine: flag "
            "unauthored throws, missing phases, thin bands, and uncovered "
            "failure modes (HAJ-223)."
        ),
    )
    parser.add_argument(
        "narration_file", type=Path,
        help="Path to the throw-narration YAML (e.g. data/throw_narration.yaml)",
    )
    parser.add_argument("--no-warnings", action="store_true",
                        help="Suppress warning-level findings")
    parser.add_argument("--no-infos", action="store_true",
                        help="Suppress info-level findings")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress the report; rely on exit code only")
    parser.add_argument("--errors-only", action="store_true",
                        help="Suppress warnings, infos, and the summary footer")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    report = validate_narration_file(args.narration_file)

    if not args.quiet:
        reconfigure = getattr(sys.stdout, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass
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
