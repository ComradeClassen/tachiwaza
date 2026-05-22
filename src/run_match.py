"""
src/run_match.py

Entry point invoked by the Godot debug calibration tool (HAJ-150).
Reads a JSON config, runs a real Hajime match, writes the structured event log.

Place this file at: C:\\Users\\jackc\\hajime\\src\\run_match.py
(alongside judoka.py, match.py, etc. — same directory level)

Usage from command line:
    python C:\\Users\\jackc\\hajime\\src\\run_match.py --config in.json --output out.json
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Force UTF-8 stdout/stderr.
#
# When this script runs from a terminal (PowerShell, cmd.exe), Python attaches
# stdout to the terminal which handles Unicode fine. When the script is
# launched via Godot's OS.execute on Windows, stdout is captured as bytes
# and Python falls back to cp1252 — which cannot encode the arrow characters
# (→, U+2192) that match prose prints in [move] events. The first tick that
# emits an arrow raises UnicodeEncodeError, the exception bubbles up through
# match.run(), and the script exits with code 2. Reconfiguring to utf-8
# makes both invocation paths behave identically.
# ---------------------------------------------------------------------------
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Sibling-module imports. Same import style main.py uses.
from enums import (
    BodyArchetype, BeltRank, DominantSide, PositionalStyle,
)
from throws import THROW_REGISTRY
from judoka import Identity, Capability, State, Judoka
from body_state import place_judoka
from match import Match, _load_default_technique_catalog
from referee import Referee


_PERSONALITY_KEY_MAP: dict[str, str] = {
    "aggressive_patient": "aggressive",
    "technical_athletic": "technical",
    "confident_anxious":  "confident",
    "loyal_improv":       "loyal_to_plan",
}


# ----------------------------------------------------------------------
# Config -> Judoka
# ----------------------------------------------------------------------
def _build_judoka(fighter_config: dict[str, Any]) -> Judoka:
    """Convert the Godot UI config dict into a real Judoka.

    Mismatches handled here:
      - Godot sends `hands_left` / `hands_right`; Capability uses
        `left_hand` / `right_hand` (and the same for forearms / legs).
      - Godot exposes one `other_body_parts_global` slider; Capability
        requires individual values for biceps, shoulders, feet, plus
        the v0.4 additions (hips, thighs, knees, wrists, head). They
        all read from the global slider so the fighter's overall
        robustness is consistent.
      - Godot sends bipolar facet labels ("aggressive_patient");
        Identity.personality_facets stores them under the first pole
        ("aggressive").
      - Godot sliders are floats 0-10; Capability fields are ints.
        Rounded here.
    """
    facets_in = fighter_config.get("personality_facets", {})
    facets = {
        _PERSONALITY_KEY_MAP[k]: int(round(v))
        for k, v in facets_in.items()
        if k in _PERSONALITY_KEY_MAP
    }

    identity = Identity(
        name=fighter_config["name"],
        age=int(fighter_config["age"]),
        weight_class=fighter_config["weight_class"],
        height_cm=int(fighter_config["height_cm"]),
        body_archetype=BodyArchetype[fighter_config["body_archetype"]],
        belt_rank=BeltRank[fighter_config["belt_rank"]],
        dominant_side=DominantSide[fighter_config["dominant_side"]],
        personality_facets=facets,
        positional_style=PositionalStyle.HOLD_CENTER,
    )

    cap_in = fighter_config["capability"]

    def cap(key: str) -> int:
        return int(round(cap_in[key]))

    other = cap("other_body_parts_global")

    capability = Capability(
        right_hand=cap("hands_right"),
        left_hand=cap("hands_left"),
        right_forearm=cap("forearms_right"),
        left_forearm=cap("forearms_left"),
        right_leg=cap("legs_right"),
        left_leg=cap("legs_left"),
        right_bicep=other, left_bicep=other,
        right_shoulder=other, left_shoulder=other,
        right_foot=other, left_foot=other,
        core=cap("core"),
        lower_back=cap("lower_back"),
        neck=cap("neck"),
        cardio_capacity=cap("cardio_capacity"),
        cardio_efficiency=cap("cardio_efficiency"),
        composure_ceiling=cap("composure_ceiling"),
        fight_iq=cap("fight_iq"),
        ne_waza_skill=cap("ne_waza_skill"),
        head=other,
        right_hip=other, left_hip=other,
        right_thigh=other, left_thigh=other,
        right_knee=other, left_knee=other,
        right_wrist=other, left_wrist=other,
        throw_vocabulary=list(THROW_REGISTRY.keys()),
        throw_profiles={},
        signature_throws=[],
        signature_combos=[],
    )

    state = State.fresh(capability, identity)
    return Judoka(identity=identity, capability=capability, state=state)


# ----------------------------------------------------------------------
# Config -> Referee
# ----------------------------------------------------------------------
def _build_referee(personality: str) -> Referee:
    if personality == "GENEROUS":
        return Referee(
            name="Generous Ref", nationality="Calibration",
            newaza_patience=0.7, stuffed_throw_tolerance=0.7,
            match_energy_read=0.4, grip_initiative_strictness=0.3,
            ippon_strictness=0.4, waza_ari_strictness=0.4,
            mat_edge_strictness=0.3,
        )
    if personality == "STRICT":
        return Referee(
            name="Strict Ref", nationality="Calibration",
            newaza_patience=0.3, stuffed_throw_tolerance=0.3,
            match_energy_read=0.7, grip_initiative_strictness=0.7,
            ippon_strictness=0.8, waza_ari_strictness=0.7,
            mat_edge_strictness=0.7,
        )
    return Referee(name="Neutral Ref", nationality="Calibration")


# ----------------------------------------------------------------------
# Event capture
# ----------------------------------------------------------------------
class _JSONCaptureRenderer:
    """Push-style Renderer that captures every per-tick events list."""

    def __init__(self) -> None:
        self.events: list = []
        self._open = True

    def start(self) -> None:
        return None

    def update(self, tick: int, match: "Match", events: list) -> None:
        self.events.extend(events)

    def stop(self) -> None:
        self._open = False

    def is_open(self) -> bool:
        return self._open


def _event_to_dict(ev: Any) -> dict[str, Any]:
    return {
        "tick": getattr(ev, "tick", 0),
        "type": getattr(ev, "event_type", "UNKNOWN"),
        "prose": getattr(ev, "description", ""),
        "engineering": _sanitize(getattr(ev, "data", {})),
    }


def _sanitize(value: Any) -> Any:
    """Recursively convert a value into JSON-safe primitives."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize(v) for v in value]
    return repr(value)


# ----------------------------------------------------------------------
# Simulation runner
# ----------------------------------------------------------------------
def _run_simulation(
    fighter1: Judoka, fighter2: Judoka, match_cfg: dict[str, Any],
) -> list[dict]:
    place_judoka(fighter1, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(fighter2, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))

    # TODO Phase 6: starting_position and forced_throw are accepted from
    # the UI but not yet honored. Match always begins STANDING_DISTANT.
    _ = match_cfg.get("starting_position", "STANDING_NEUTRAL")
    _ = match_cfg.get("forced_throw", "NONE")

    referee = _build_referee(match_cfg.get("ref_personality", "NEUTRAL"))
    max_ticks = int(match_cfg.get("time_on_clock", 240))
    seed = match_cfg.get("seed")
    if seed is not None:
        seed = int(seed)

    capture = _JSONCaptureRenderer()

    match = Match(
        fighter_a=fighter1,
        fighter_b=fighter2,
        referee=referee,
        max_ticks=max_ticks,
        seed=seed,
        stream="both",
        renderer=capture,
        technique_catalog=_load_default_technique_catalog(),
    )
    match.run()

    return [_event_to_dict(ev) for ev in capture.events]


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a Hajime match from a JSON config."
    )
    parser.add_argument("--config", type=Path, required=True,
                        help="Path to the input config JSON written by the Godot UI.")
    parser.add_argument("--output", type=Path, required=True,
                        help="Path to write the structured event log JSON.")
    args = parser.parse_args(argv)

    try:
        with args.config.open("r", encoding="utf-8-sig") as f:
            config = json.load(f)
    except Exception as exc:
        _write_error_log(args.output, "Failed to read config: %s" % exc)
        return 1

    try:
        fighter1 = _build_judoka(config["fighter1"])
        fighter2 = _build_judoka(config["fighter2"])
        match_cfg = config["match"]
        events = _run_simulation(fighter1, fighter2, match_cfg)
    except Exception:
        _write_error_log(
            args.output,
            "Simulation crashed:\n" + traceback.format_exc(),
        )
        return 2

    try:
        with args.output.open("w", encoding="utf-8") as f:
            json.dump({"events": events}, f, indent=2)
    except Exception as exc:
        sys.stderr.write("Failed to write output: %s\n" % exc)
        return 3

    return 0


def _write_error_log(output_path: Path, message: str) -> None:
    try:
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(
                {"events": [{"tick": 0, "type": "ERROR", "prose": message}]},
                f,
                indent=2,
            )
    except Exception:
        sys.stderr.write(message + "\n")


if __name__ == "__main__":
    sys.exit(main())
