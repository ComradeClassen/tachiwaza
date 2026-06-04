# grip_narration.py
# HAJ-225 — data-driven mat-side prose for grip-war beats (strip outcomes and
# the first-grip line) that used to be inline f-strings in
# narration/altitudes/mat_side.py.
#
# Mirrors the throw_narration.py pattern (HAJ-221/HAJ-223): a YAML data file
# of keyed variant templates, a loader with graceful fallback, deterministic
# per-beat variant selection seeded so replays reproduce identical prose, and
# a module-level cache. Grip beats aren't throw-keyed, so this is a flat
# key → list[str] map rather than the throw/phase/band structure.
#
# Schema (data/grip_narration.yaml):
#
#   strip_full:
#     - "{stripper} rips {target}'s {grip} grip loose."
#   strip_partial:
#     - "{stripper} breaks {target}'s {grip} grip down to a {depth}."
#   ...
#
# Each value is a list of str.format templates (a bare string is lifted to a
# one-entry list). Fields available per key are documented in the YAML.

from __future__ import annotations

import random
from pathlib import Path
from typing import Optional, Union


# ---------------------------------------------------------------------------
# KEYS
# ---------------------------------------------------------------------------
STRIP_FULL:              str = "strip_full"
STRIP_PARTIAL:           str = "strip_partial"
STRIP_FAILED:            str = "strip_failed"
BOTH_GRIPS:              str = "both_grips"
FIRST_GRIP_UNCONTESTED:  str = "first_grip_uncontested"
FIRST_GRIP_CONTESTED:    str = "first_grip_contested"


_DEFAULT_DATA_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "grip_narration.yaml"
)


# ---------------------------------------------------------------------------
# FALLBACK PROSE
# Mirrors the pre-HAJ-225 inline strings so the coach stream stays legible if
# data/grip_narration.yaml is missing or empty (the loader returns {} then).
# ---------------------------------------------------------------------------
_FALLBACK: dict[str, list[str]] = {
    STRIP_FULL:             ["{stripper} rips {target}'s {grip} grip loose."],
    STRIP_PARTIAL:          ["{stripper} breaks {target}'s {grip} grip down to a {depth}."],
    STRIP_FAILED:           ["{actor} tries to rip {target_phrase} but can't budge it."],
    BOTH_GRIPS:             ["Both fighters lock onto their grips."],
    FIRST_GRIP_UNCONTESTED: ["{leader} secures the first grip — {follower} reaches but finds nothing."],
    FIRST_GRIP_CONTESTED:   ["{leader} gets the first grip, but {follower} fights for the inside."],
}


class GripNarrationLoadError(ValueError):
    """Raised when the YAML is malformed in a way that would silently produce
    wrong prose. Missing / empty data is NOT an error — fallback covers it."""


# ---------------------------------------------------------------------------
# LOADER
# ---------------------------------------------------------------------------
def load_grip_narration(
    path: Union[str, Path, None] = None,
) -> dict[str, list[str]]:
    """Read grip narration from disk. Returns {} when the file is missing or
    empty — callers fall back to the baked-in constants."""
    p = Path(path) if path is not None else _DEFAULT_DATA_PATH
    if not p.exists():
        return {}
    text = p.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    suffix = p.suffix.lower()
    if suffix not in (".yaml", ".yml"):
        raise GripNarrationLoadError(
            f"Unsupported narration file extension '{suffix}' for {p}; "
            "expected .yaml or .yml"
        )
    import yaml  # local import — keeps non-narration callers dep-free
    raw = yaml.safe_load(text) or {}
    return parse_grip_narration(raw)


def parse_grip_narration(raw: object) -> dict[str, list[str]]:
    """Validate + normalise an in-memory mapping (yaml.safe_load output or a
    hand-built test fixture) into key → list[str]."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise GripNarrationLoadError(
            f"Top-level grip narration must be a mapping of key → variants, "
            f"got {type(raw).__name__}"
        )
    out: dict[str, list[str]] = {}
    for key, variants in raw.items():
        k = str(key).strip().lower()
        if isinstance(variants, str):
            variants = [variants]
        if not isinstance(variants, list) or not variants:
            raise GripNarrationLoadError(
                f"Grip narration key '{key}' must map to a non-empty list of "
                f"strings (or a single string); got {type(variants).__name__}"
            )
        for i, v in enumerate(variants):
            if not isinstance(v, str):
                raise GripNarrationLoadError(
                    f"Grip narration '{key}'[{i}] must be a string, got "
                    f"{type(v).__name__}"
                )
        out[k] = list(variants)
    return out


# ---------------------------------------------------------------------------
# MODULE-LEVEL CACHE
# ---------------------------------------------------------------------------
_DEFAULT_DATA_CACHE: Optional[dict[str, list[str]]] = None


def get_default_data() -> dict[str, list[str]]:
    global _DEFAULT_DATA_CACHE
    if _DEFAULT_DATA_CACHE is None:
        _DEFAULT_DATA_CACHE = load_grip_narration()
    return _DEFAULT_DATA_CACHE


def reset_default_data(
    new_data: Optional[dict[str, list[str]]] = None,
) -> None:
    """Replace (or clear) the cached default data. Tests inject a fixture via
    `reset_default_data(parse_grip_narration({...}))` then revert with
    `reset_default_data(None)`."""
    global _DEFAULT_DATA_CACHE
    _DEFAULT_DATA_CACHE = new_data


# ---------------------------------------------------------------------------
# SELECTION
# ---------------------------------------------------------------------------
def select_line(key: str, *, seed: object = 0, **fields: object) -> str:
    """Pick one variant for `key` and render it with `fields`.

    Variant choice is deterministic in `(key, seed)` so the same beat on a
    replay lands on the same line. Falls back to the baked-in constant when
    the YAML has no entry for the key, and to the constant template again if
    an authored variant references a field the caller didn't supply (so a
    typo in the data file degrades gracefully instead of raising mid-match).
    """
    data = get_default_data()
    variants = data.get(key) or _FALLBACK.get(key)
    if not variants:
        return ""
    rng = random.Random(f"haj225:{key}:{seed}")
    template = rng.choice(list(variants))
    try:
        return template.format(**fields)
    except (KeyError, IndexError):
        fallback = _FALLBACK.get(key)
        if not fallback:
            return ""
        try:
            return fallback[0].format(**fields)
        except (KeyError, IndexError):
            return fallback[0]
