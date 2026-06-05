# throw_narration.py
# HAJ-221 — data-driven body-part narration for throw resolution phases.
#
# Loads `data/throw_narration.yaml` (or an injected dict) and selects a
# coach-stream line per (throw_id, phase, quality_band) and per
# (throw_id, "failures", failure_mode). Variants within a (throw, phase,
# band) bucket are picked deterministically from a per-tick seed so
# replays produce identical prose.
#
# Scope (engineering): schema, loader, fallback, selection logic. The
# actual narration content for the 13 engine-implemented throws lands
# in HAJ-223; until then this module gracefully falls back to a generic
# line so the coach stream stays legible against an empty data file.
#
# Schema (YAML):
#
#   ko_uchi_gari:
#     commit:
#       - "Tanaka commits to Ko-uchi-gari."
#     reach_kuzushi:
#       clean:    ["..."]
#       standard: ["..."]
#       sloppy:   ["..."]
#     kuzushi:    {...}
#     tsukuri:    {...}
#     kake:       {...}
#     failures:
#       sweep_bounces_off: ["..."]
#       forward_lean:      ["..."]
#       ...
#
# Phase keys are normalized to snake_case lower; failure mode keys
# accept either the FailureOutcome enum name (`SWEEP_BOUNCES_OFF`) or
# the lower-snake spelling. Variants must be lists of strings; a bare
# string is silently lifted to a single-entry list for authoring
# convenience.

from __future__ import annotations

import os
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence, Union

from execution_quality import (
    NARRATION_BAND_CLEAN, NARRATION_BAND_STANDARD, NARRATION_BAND_SLOPPY,
    narration_band_for,
)
from throws import ThrowID


# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------
PHASE_COMMIT:         str = "commit"
PHASE_REACH_KUZUSHI:  str = "reach_kuzushi"
PHASE_KUZUSHI:        str = "kuzushi"
PHASE_TSUKURI:        str = "tsukuri"
PHASE_KAKE:           str = "kake"
PHASE_FAILURES:       str = "failures"

# The four substrate resolution phases that body-part narration covers.
# `commit` is rendered separately at the top of the chain.
_RESOLUTION_PHASES: tuple[str, ...] = (
    PHASE_REACH_KUZUSHI, PHASE_KUZUSHI, PHASE_TSUKURI, PHASE_KAKE,
)

_BAND_ORDER: tuple[str, ...] = (
    NARRATION_BAND_CLEAN, NARRATION_BAND_STANDARD, NARRATION_BAND_SLOPPY,
)

_DEFAULT_DATA_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "throw_narration.yaml"
)


# ---------------------------------------------------------------------------
# DATA STRUCTURES
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ThrowNarration:
    """Loaded narration for a single throw_id.

    `phases` maps a phase name (commit / reach_kuzushi / kuzushi /
    tsukuri / kake) to either:
      - a list of variant strings (for `commit` where banding doesn't apply), or
      - a dict[band → list[str]] for the four resolution phases.

    `failures` maps a failure mode key (the FailureOutcome enum name or
    its lower-snake equivalent) to a list of variant strings.
    """
    throw_key: str
    phases:    dict[str, object]      = field(default_factory=dict)
    failures:  dict[str, list[str]]   = field(default_factory=dict)


class ThrowNarrationLoadError(ValueError):
    """Raised when the YAML file is malformed in a way that would
    silently produce wrong narration. Empty / missing data is NOT an
    error — fallback narration covers it."""


# ---------------------------------------------------------------------------
# LOADER
# ---------------------------------------------------------------------------
def load_throw_narration(
    path: Union[str, Path, None] = None,
) -> dict[str, ThrowNarration]:
    """Read narration data from disk. Returns an empty dict when the
    file is missing or empty — coach-stream callers fall back to a
    generic line in that case (HAJ-221 AC: empty data must not crash).

    A path of `None` resolves to the project's default
    `data/throw_narration.yaml`.
    """
    p = Path(path) if path is not None else _DEFAULT_DATA_PATH
    if not p.exists():
        return {}
    text = p.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    suffix = p.suffix.lower()
    if suffix in (".yaml", ".yml"):
        import yaml  # local import — keeps non-narration callers dep-free
        raw = yaml.safe_load(text) or {}
    else:
        raise ThrowNarrationLoadError(
            f"Unsupported narration file extension '{suffix}' for {p}; "
            "expected .yaml or .yml"
        )
    return parse_throw_narration(raw)


def parse_throw_narration(raw: object) -> dict[str, ThrowNarration]:
    """Validate + normalise an in-memory mapping (e.g. from yaml.safe_load
    or a hand-built dict in a test fixture)."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ThrowNarrationLoadError(
            f"Top-level narration must be a mapping of throw_id → entry, "
            f"got {type(raw).__name__}"
        )
    out: dict[str, ThrowNarration] = {}
    for throw_key, entry in raw.items():
        if not isinstance(throw_key, str):
            raise ThrowNarrationLoadError(
                f"Throw keys must be strings; got {throw_key!r}"
            )
        key = throw_key.strip().lower()
        if not isinstance(entry, dict):
            raise ThrowNarrationLoadError(
                f"Throw '{throw_key}' must map to a dict, got "
                f"{type(entry).__name__}"
            )
        phases:   dict[str, object]    = {}
        failures: dict[str, list[str]] = {}
        for phase_key, phase_value in entry.items():
            phase_lc = str(phase_key).strip().lower()
            if phase_lc == PHASE_FAILURES:
                if not isinstance(phase_value, dict):
                    raise ThrowNarrationLoadError(
                        f"Throw '{throw_key}' failures must be a dict, "
                        f"got {type(phase_value).__name__}"
                    )
                for fail_key, variants in phase_value.items():
                    failures[_normalise_failure_key(fail_key)] = (
                        _coerce_variants(variants, context=(
                            f"{throw_key}.failures.{fail_key}"
                        ))
                    )
                continue
            if phase_lc == PHASE_COMMIT:
                phases[PHASE_COMMIT] = _coerce_variants(
                    phase_value, context=f"{throw_key}.{phase_lc}",
                )
                continue
            if phase_lc in _RESOLUTION_PHASES:
                if isinstance(phase_value, (list, str)):
                    # Flat list / single string — treat as `standard` band.
                    phases[phase_lc] = {
                        NARRATION_BAND_STANDARD: _coerce_variants(
                            phase_value, context=f"{throw_key}.{phase_lc}",
                        )
                    }
                    continue
                if not isinstance(phase_value, dict):
                    raise ThrowNarrationLoadError(
                        f"Throw '{throw_key}' phase '{phase_lc}' must be a "
                        f"dict of band→variants (or a list of strings to "
                        f"default to standard band); got "
                        f"{type(phase_value).__name__}"
                    )
                bands: dict[str, list[str]] = {}
                for band_key, variants in phase_value.items():
                    band_lc = str(band_key).strip().lower()
                    if band_lc not in _BAND_ORDER:
                        raise ThrowNarrationLoadError(
                            f"Throw '{throw_key}' phase '{phase_lc}' band "
                            f"'{band_key}' not recognised; expected one "
                            f"of: {', '.join(_BAND_ORDER)}"
                        )
                    bands[band_lc] = _coerce_variants(
                        variants,
                        context=f"{throw_key}.{phase_lc}.{band_lc}",
                    )
                phases[phase_lc] = bands
                continue
            # Unknown phase — preserve it as a flat list so future schema
            # extensions don't lose data, but don't enforce a structure.
            phases[phase_lc] = _coerce_variants(
                phase_value, context=f"{throw_key}.{phase_lc}",
            )
        out[key] = ThrowNarration(
            throw_key=key, phases=phases, failures=failures,
        )
    return out


def _coerce_variants(value: object, *, context: str) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        items: list[str] = []
        for i, item in enumerate(value):
            if not isinstance(item, str):
                raise ThrowNarrationLoadError(
                    f"{context}[{i}] must be a string, got "
                    f"{type(item).__name__}"
                )
            items.append(item)
        if not items:
            raise ThrowNarrationLoadError(
                f"{context} variants list is empty; need at least one entry"
            )
        return items
    raise ThrowNarrationLoadError(
        f"{context}: variants must be a list of strings or a single "
        f"string; got {type(value).__name__}"
    )


def _normalise_failure_key(raw: object) -> str:
    """Failure-mode keys accept either the FailureOutcome enum name
    (`SWEEP_BOUNCES_OFF`, machine-tag-friendly) or the lower-snake
    spelling (`sweep_bounces_off`, author-friendly). Normalise to
    lower-snake internally so lookup matches either spelling."""
    return str(raw).strip().lower()


# ---------------------------------------------------------------------------
# THROW_ID NORMALISATION
# ---------------------------------------------------------------------------
def _throw_key_for(throw_id: ThrowID) -> str:
    """Engine ThrowID enum name → narration YAML key. The YAML uses
    lower-snake (`ko_uchi_gari`) which is just the enum name lowered."""
    return throw_id.name.lower()


# ---------------------------------------------------------------------------
# SELECTION
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class NarrationLookup:
    """The full narration set for one throw. Returned by `select_for` so
    callers (the throw-resolution path) can render the chain in one
    walk and emit one Event per line."""
    commit:        Optional[str]
    reach_kuzushi: Optional[str]
    kuzushi:       Optional[str]
    tsukuri:       Optional[str]
    kake:          Optional[str]


def select_phase_line(
    data: dict[str, ThrowNarration],
    throw_id: ThrowID,
    phase: str,
    *,
    quality: Optional[float] = None,
    seed: object = 0,
) -> Optional[str]:
    """Pick one line for (throw_id, phase, quality_band). Returns None
    when no entry exists for the throw or phase — the caller falls back
    to a generic line or to the existing phase-label rendering.

    Variant selection: a deterministic RNG seeded by `(throw_id, phase,
    seed)` picks an index into the variants list, so the same seed +
    same throw + same phase always lands on the same variant — important
    for the calibration-tool replay determinism AC.
    """
    entry = data.get(_throw_key_for(throw_id))
    if entry is None:
        return None
    phase_lc = phase.strip().lower()
    bucket = entry.phases.get(phase_lc)
    if bucket is None:
        return None
    variants: Sequence[str]
    if isinstance(bucket, dict):
        band = (
            narration_band_for(quality) if quality is not None
            else NARRATION_BAND_STANDARD
        )
        variants = bucket.get(band) or _band_fallback(bucket, band)
        if not variants:
            return None
    elif isinstance(bucket, list):
        variants = bucket
    else:
        return None
    if not variants:
        return None
    rng = random.Random(f"haj221:{throw_id.name}:{phase_lc}:{seed}")
    return rng.choice(list(variants))


def _band_fallback(
    bucket: dict[str, list[str]], band: str,
) -> list[str]:
    """If the asked-for band has no variants authored, walk to the
    adjacent bands so the coach stream still gets a line. Order:
    standard first (most likely populated), then the unseen extreme.
    Returns an empty list if no band is populated at all."""
    for fallback in (NARRATION_BAND_STANDARD,) + _BAND_ORDER:
        if fallback == band:
            continue
        variants = bucket.get(fallback)
        if variants:
            return variants
    return []


def select_failure_line(
    data: dict[str, ThrowNarration],
    throw_id: ThrowID,
    failure_mode: str,
    *,
    seed: object = 0,
) -> Optional[str]:
    """Pick a line for (throw_id, failure_mode). `failure_mode` should
    be the FailureOutcome enum name (the engine spelling); the loader
    accepts both that and lower-snake in the YAML."""
    entry = data.get(_throw_key_for(throw_id))
    if entry is None:
        return None
    key = _normalise_failure_key(failure_mode)
    variants = entry.failures.get(key)
    if not variants:
        return None
    rng = random.Random(f"haj221:{throw_id.name}:failure:{key}:{seed}")
    return rng.choice(list(variants))


def select_commit_line(
    data: dict[str, ThrowNarration],
    throw_id: ThrowID,
    *,
    seed: object = 0,
) -> Optional[str]:
    """Convenience wrapper for the commit phase."""
    return select_phase_line(data, throw_id, PHASE_COMMIT, seed=seed)


# ---------------------------------------------------------------------------
# FALLBACK PROSE (engine-authored generic lines when YAML has no entry)
# These exist so the coach stream remains legible against an empty
# `data/throw_narration.yaml` file — HAJ-221 explicitly calls for
# graceful fallback rather than a crash, and lets HAJ-223 author the
# real content incrementally without breaking matches in the interim.
# ---------------------------------------------------------------------------
_GENERIC_PHASE_FALLBACK: dict[str, str] = {
    PHASE_REACH_KUZUSHI: "{tori} steps in and presses against {uke}'s stance.",
    PHASE_KUZUSHI:       "{uke}'s balance shifts under {tori}'s pressure.",
    PHASE_TSUKURI:       "{tori} sets up the technique.",
    PHASE_KAKE:          "{tori} delivers the throw.",
}


def render_line(line: str, *, tori: str, uke: str) -> str:
    """Substitute {tori}/{uke} placeholders in an authored narration line
    with the live fighter names. Authored content (HAJ-223) uses these
    placeholders so the lexicon is matchup-stable. Tolerant of lines that
    carry no placeholders, and of stray braces an author might introduce
    (a KeyError/ValueError from str.format falls back to the raw line
    rather than dropping the coach line entirely)."""
    try:
        return line.format(tori=tori, uke=uke)
    except (KeyError, IndexError, ValueError):
        return line


def generic_phase_line(
    phase: str, *, tori: str, uke: str,
) -> Optional[str]:
    """Coach-stream fallback when the YAML has no entry for a throw or
    a specific phase. Returns a generic body-part-flavoured line keyed
    only by phase — the player gets *something* legible, just without
    the throw-specific colour HAJ-223 will add."""
    template = _GENERIC_PHASE_FALLBACK.get(phase.strip().lower())
    if template is None:
        return None
    return template.format(tori=tori, uke=uke)


# ---------------------------------------------------------------------------
# MODULE-LEVEL CACHE
# Most callers (Match._tick) want the same loaded data across every tick;
# avoid re-reading + re-parsing the YAML on each call. The cache is
# invalidated explicitly via `reset_default_data` (used by tests that
# want to inject a fixture).
# ---------------------------------------------------------------------------
_DEFAULT_DATA_CACHE: Optional[dict[str, ThrowNarration]] = None


def get_default_data() -> dict[str, ThrowNarration]:
    global _DEFAULT_DATA_CACHE
    if _DEFAULT_DATA_CACHE is None:
        _DEFAULT_DATA_CACHE = load_throw_narration()
    return _DEFAULT_DATA_CACHE


def reset_default_data(
    new_data: Optional[dict[str, ThrowNarration]] = None,
) -> None:
    """Replace (or clear) the cached default narration data. Tests inject
    a fixture via `reset_default_data(parse_throw_narration({...}))`
    then call `reset_default_data(None)` to revert to a fresh load."""
    global _DEFAULT_DATA_CACHE
    _DEFAULT_DATA_CACHE = new_data
