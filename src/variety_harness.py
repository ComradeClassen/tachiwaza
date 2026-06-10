# variety_harness.py
# Variety-harness runner — fights any two archetype fixtures and dumps one
# comparable, greppable log per match to a known output directory.
#
# This is a diagnostic instrument for eyeballing the engine's expressive
# range (recognition test), not gameplay. It never modifies engine logic.
# Recon basis: design-notes/triage/variety-harness-recon-2026-06-10.md.
#
# Usage from the project root:
#   python src/variety_harness.py --a grip_monster --b passive_median
#   python src/variety_harness.py --a professor --b brawler --seed 7 --reps 5
#
# Reproducibility: rep i runs with seed (--seed + i), applied in the same
# two-layer pattern main.py uses — random.seed(s) for the module-level RNG
# (throw resolution, ne-waza rolls) AND Match(seed=s) for the keyed
# per-purpose streams. Re-running with the same seed reproduces the match
# byte-for-byte.

from __future__ import annotations

import argparse
import contextlib
import os
import random
import re
import sys

_SRC = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_SRC)
sys.path.insert(0, _SRC)
sys.path.insert(0, os.path.join(_REPO, "tests", "fixtures"))

import archetypes
from body_state import place_judoka
from match import (
    Match, _load_default_technique_catalog, _load_default_ne_waza_catalog,
)
from referee import build_suzuki, build_petrov

DEFAULT_OUT_DIR = os.path.join(_REPO, "design-notes", "qa", "variety")
DEFAULT_REPS = 5   # QA-pass-size principle: small batches, eyeballable

# Coach-prose markers for the stance thread (stance.py stance_change_coach_prose).
_STANCE_SWITCH_RE = re.compile(
    r"drops into|squares back to|steered off", re.IGNORECASE
)
_NE_WAZA_RE = re.compile(r"\[ne-waza\]", re.IGNORECASE)


# ---------------------------------------------------------------------------
# SINGLE MATCH
# ---------------------------------------------------------------------------
def run_one_match(
    fixture_a: str,
    fixture_b: str,
    *,
    seed: int,
    stream: str,
    ref_builder,
    log_path: str,
) -> dict:
    """Run one seeded fixture match, captured to `log_path`. Returns a
    summary dict (winner / method / ticks / greppable-marker counts)."""
    # Two-layer seeding (main.py:_run_one_match pattern). random.seed must
    # come BEFORE fixture construction so any module-level draws downstream
    # of construction stay on the seeded stream.
    random.seed(seed)

    a = archetypes.build(fixture_a)
    b = archetypes.build(fixture_b)
    ref = ref_builder()

    place_judoka(a, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(b, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))

    match = Match(
        fighter_a=a, fighter_b=b, referee=ref,
        seed=seed, stream=stream,
        technique_catalog=_load_default_technique_catalog(),
        ne_waza_catalog=_load_default_ne_waza_catalog(),
    )

    # UTF-8 explicitly — match prose prints arrow glyphs that die on cp1252.
    with open(log_path, "w", encoding="utf-8", errors="replace", newline="") as f:
        with contextlib.redirect_stdout(f):
            match.run()

    with open(log_path, "r", encoding="utf-8") as f:
        log_text = f.read()

    winner = match.winner.identity.name if match.winner is not None else "-"
    return {
        "seed": seed,
        "winner": winner,
        "method": match.win_method or "-",
        "ticks": match.ticks_run,
        "ne_waza_lines": len(_NE_WAZA_RE.findall(log_text)),
        "stance_switches": len(_STANCE_SWITCH_RE.findall(log_text)),
        "log": log_path,
    }


# ---------------------------------------------------------------------------
# BATCH
# ---------------------------------------------------------------------------
def run_batch(
    fixture_a: str,
    fixture_b: str,
    *,
    base_seed: int,
    reps: int,
    stream: str,
    ref_builder,
    out_dir: str,
    label: str | None = None,
) -> list[dict]:
    """Run `reps` matches (seeds base_seed..base_seed+reps-1), one log file
    each, plus a summary.txt in the pairing directory."""
    pairing = label or f"{fixture_a}_vs_{fixture_b}"
    pair_dir = os.path.join(out_dir, pairing)
    os.makedirs(pair_dir, exist_ok=True)

    results: list[dict] = []
    for i in range(reps):
        seed = base_seed + i
        log_path = os.path.join(pair_dir, f"seed{seed}.log")
        print(f"  [{i + 1}/{reps}] seed {seed} ... ", end="", flush=True)
        result = run_one_match(
            fixture_a, fixture_b,
            seed=seed, stream=stream, ref_builder=ref_builder,
            log_path=log_path,
        )
        results.append(result)
        print(
            f"{result['winner']} by {result['method']} "
            f"({result['ticks']} ticks, ne-waza x{result['ne_waza_lines']}, "
            f"stance-switch x{result['stance_switches']})"
        )

    summary_lines = [
        f"Pairing: {pairing}  ({fixture_a} = blue, {fixture_b} = white)",
        f"Seeds: {base_seed}..{base_seed + reps - 1}   stream: {stream}",
        "",
        f"{'seed':>6}  {'winner':<16} {'method':<26} {'ticks':>5} "
        f"{'ne-waza':>8} {'switches':>9}",
    ]
    for r in results:
        summary_lines.append(
            f"{r['seed']:>6}  {r['winner']:<16} {r['method']:<26} "
            f"{r['ticks']:>5} {r['ne_waza_lines']:>8} {r['stance_switches']:>9}"
        )
    wins_a = sum(1 for r in results if r["winner"] == fixture_label_name(fixture_a))
    wins_b = sum(1 for r in results if r["winner"] == fixture_label_name(fixture_b))
    draws = reps - wins_a - wins_b
    summary_lines.append("")
    summary_lines.append(
        f"Record: {fixture_a} {wins_a} - {fixture_b} {wins_b}"
        + (f" - {draws} draw(s)" if draws else "")
    )
    summary = "\n".join(summary_lines) + "\n"

    summary_path = os.path.join(pair_dir, "summary.txt")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(summary)

    print()
    print(summary)
    print(f"Logs: {pair_dir}")
    return results


def fixture_label_name(fixture_key: str) -> str:
    """Registry key -> the Identity.name the match log prints (cached
    one-off construction; fixtures are cheap pure builders)."""
    return archetypes.build(fixture_key).identity.name


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fight two variety-harness fixtures and write comparable "
                    "per-match logs.",
    )
    parser.add_argument("--a", dest="fixture_a", metavar="FIXTURE",
                        help="Blue-side fixture name. Available: "
                             + ", ".join(sorted(archetypes.FIXTURES)))
    parser.add_argument("--b", dest="fixture_b", metavar="FIXTURE",
                        help="White-side fixture name.")
    parser.add_argument("--seed", type=int, default=1,
                        help="Base seed; rep i uses seed+i (default: 1).")
    parser.add_argument("--reps", type=int, default=DEFAULT_REPS,
                        help=f"Matches per pairing (default: {DEFAULT_REPS}).")
    parser.add_argument("--stream", choices=["debug", "prose", "coach", "both"],
                        default="both",
                        help="Log stream to capture (default: both — the "
                             "side-by-side view the owner reads).")
    parser.add_argument("--referee", choices=["suzuki", "petrov"],
                        default="suzuki")
    parser.add_argument("--out", default=DEFAULT_OUT_DIR,
                        help=f"Output root (default: {DEFAULT_OUT_DIR}).")
    args = parser.parse_args(argv)

    ref_builder = build_suzuki if args.referee == "suzuki" else build_petrov

    if not (args.fixture_a and args.fixture_b):
        parser.error("--a and --b are required (fixture names).")
    for name in (args.fixture_a, args.fixture_b):
        if name not in archetypes.FIXTURES:
            parser.error(
                f"unknown fixture {name!r}. Available: "
                + ", ".join(sorted(archetypes.FIXTURES))
            )
    if args.fixture_a == args.fixture_b:
        # Grip graph keys edges by Identity.name; a mirror match would
        # collapse both fighters into one node.
        parser.error("--a and --b must be different fixtures.")

    print(f"\n=== Variety harness: {args.fixture_a} vs {args.fixture_b} ===")
    run_batch(
        args.fixture_a, args.fixture_b,
        base_seed=args.seed, reps=args.reps, stream=args.stream,
        ref_builder=ref_builder, out_dir=args.out,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
