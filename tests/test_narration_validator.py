# test_narration_validator.py — HAJ-223 narration validator tests.
#
# Exercises src/narration_validator.py:
#   - validate_narration (in-memory, with injected implemented-set)
#   - validate_narration_file (loader wrap, against the real data file)
#   - each check has a positive (clean) and negative (gap) case
#   - CLI entrypoint main()

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import throw_narration as tn  # noqa: E402
from throws import ThrowID  # noqa: E402
from narration_validator import (  # noqa: E402
    Severity,
    NarrationValidationReport,
    validate_narration,
    validate_narration_file,
    main,
)

_NARRATION_FILE = REPO_ROOT / "data" / "throw_narration.yaml"


def _full_entry(*, failures: dict | None = None) -> dict:
    """A structurally complete entry: commit (3) + 4 banded phases (2/band)
    + an optional failures block."""
    band = {"clean": ["a", "b"], "standard": ["a", "b"], "sloppy": ["a", "b"]}
    entry = {
        "commit": ["c1", "c2", "c3"],
        "reach_kuzushi": dict(band),
        "kuzushi": dict(band),
        "tsukuri": dict(band),
        "kake": dict(band),
    }
    if failures is not None:
        entry["failures"] = failures
    return entry


def _codes(report: NarrationValidationReport) -> set[str]:
    return {i.code for i in report.issues}


# ---------------------------------------------------------------------------
# The shipped data file validates clean.
# ---------------------------------------------------------------------------
def test_real_narration_file_is_clean() -> None:
    report = validate_narration_file(_NARRATION_FILE)
    assert report.load_error is None
    assert report.is_valid, report.format_text()
    assert report.errors == []
    assert report.warnings == []
    assert report.total_throws_authored == report.total_throws_implemented == 13


# ---------------------------------------------------------------------------
# missing_throw_narration (WARNING)
# ---------------------------------------------------------------------------
def test_missing_throw_is_warned() -> None:
    impl = {"ko_uchi_gari": ThrowID.KO_UCHI_GARI, "o_soto_gari": ThrowID.O_SOTO_GARI}
    # ko_uchi_gari authored with a complete entry; o_soto_gari absent.
    data = tn.parse_throw_narration({
        "ko_uchi_gari": _full_entry(failures={
            "tori_sweep_bounces_off": ["a", "b"],
            "stance_reset": ["a", "b"],
            "partial_throw": ["a", "b"],
        }),
    })
    report = validate_narration(data, implemented=impl)
    miss = [i for i in report.issues if i.code == "missing_throw_narration"]
    assert len(miss) == 1
    assert miss[0].technique_id == "o_soto_gari"
    assert miss[0].severity is Severity.WARNING
    # A missing throw is a warning, not an error — doesn't fail the gate.
    assert report.is_valid


# ---------------------------------------------------------------------------
# missing_phase (ERROR)
# ---------------------------------------------------------------------------
def test_missing_resolution_phase_is_error() -> None:
    impl = {"ko_uchi_gari": ThrowID.KO_UCHI_GARI}
    entry = _full_entry()
    del entry["kake"]
    data = tn.parse_throw_narration({"ko_uchi_gari": entry})
    report = validate_narration(data, implemented=impl)
    errs = [i for i in report.errors if i.code == "missing_phase"]
    assert [e.field for e in errs] == ["kake"]
    assert not report.is_valid


def test_missing_commit_is_error() -> None:
    impl = {"ko_uchi_gari": ThrowID.KO_UCHI_GARI}
    entry = _full_entry()
    del entry["commit"]
    data = tn.parse_throw_narration({"ko_uchi_gari": entry})
    report = validate_narration(data, implemented=impl)
    errs = [i for i in report.errors if i.code == "missing_phase"]
    assert any(e.field == "commit" for e in errs)
    assert not report.is_valid


# ---------------------------------------------------------------------------
# thin_band (WARNING)
# ---------------------------------------------------------------------------
def test_thin_band_is_warned() -> None:
    impl = {"ko_uchi_gari": ThrowID.KO_UCHI_GARI}
    entry = _full_entry()
    entry["kuzushi"]["sloppy"] = ["only-one"]   # 1 variant < floor of 2
    data = tn.parse_throw_narration({"ko_uchi_gari": entry})
    report = validate_narration(data, implemented=impl)
    thin = [i for i in report.warnings if i.code == "thin_band"]
    assert [t.field for t in thin] == ["kuzushi.sloppy"]
    # A thin band is a warning, not an error.
    assert report.is_valid


# ---------------------------------------------------------------------------
# missing_failure_narration + thin_failure (WARNING)
# ---------------------------------------------------------------------------
def test_uncovered_engine_failure_is_warned() -> None:
    # ko_uchi_gari's engine FailureSpec is sweep_bounces_off / stance_reset /
    # partial_throw. Author only the first → the other two are flagged.
    impl = {"ko_uchi_gari": ThrowID.KO_UCHI_GARI}
    data = tn.parse_throw_narration({
        "ko_uchi_gari": _full_entry(failures={
            "tori_sweep_bounces_off": ["a", "b"],
        }),
    })
    report = validate_narration(data, implemented=impl)
    missing = {
        i.field for i in report.warnings
        if i.code == "missing_failure_narration"
    }
    assert missing == {"failures.stance_reset", "failures.partial_throw"}


def test_thin_failure_is_warned() -> None:
    impl = {"ko_uchi_gari": ThrowID.KO_UCHI_GARI}
    data = tn.parse_throw_narration({
        "ko_uchi_gari": _full_entry(failures={
            "tori_sweep_bounces_off": ["only-one"],
            "stance_reset": ["a", "b"],
            "partial_throw": ["a", "b"],
        }),
    })
    report = validate_narration(data, implemented=impl)
    thin = [i for i in report.warnings if i.code == "thin_failure"]
    assert [t.field for t in thin] == ["failures.tori_sweep_bounces_off"]


# ---------------------------------------------------------------------------
# unknown_throw_narration (INFO)
# ---------------------------------------------------------------------------
def test_orphaned_entry_is_info() -> None:
    impl = {"ko_uchi_gari": ThrowID.KO_UCHI_GARI}
    data = tn.parse_throw_narration({
        "ko_uchi_gari": _full_entry(failures={
            "tori_sweep_bounces_off": ["a", "b"],
            "stance_reset": ["a", "b"],
            "partial_throw": ["a", "b"],
        }),
        "made_up_throw": {"commit": ["a", "b"]},
    })
    report = validate_narration(data, implemented=impl)
    orphans = [i for i in report.infos if i.code == "unknown_throw_narration"]
    assert [o.technique_id for o in orphans] == ["made_up_throw"]
    # Info-only — doesn't fail the gate.
    assert report.is_valid


# ---------------------------------------------------------------------------
# load failure surfaces as a fatal report, not an exception.
# ---------------------------------------------------------------------------
def test_load_failure_is_fatal_report(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("ko_uchi_gari: [this, should, be, a, mapping]\n", encoding="utf-8")
    report = validate_narration_file(bad)
    assert report.load_error is not None
    assert not report.is_valid


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def test_cli_clean_file_exits_zero(capsys: pytest.CaptureFixture) -> None:
    rc = main([str(_NARRATION_FILE)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "throws authored: 13 / 13" in out
