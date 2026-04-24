# main.py
# Entry point for Phase 2 Session 2.
# Builds Tanaka and Sato (with the new 24-part body model), assigns a referee,
# and runs a match.
#
# Run from the project root:
#   python src/main.py
#
# Phase 2 Session 2 success criterion:
#   - Match starts with Hajime
#   - Visible engagement: edges form before any throw fires
#   - Visible grip war: tug-of-war, edge contests, some edges break
#   - Kuzushi windows: at least one opens per typical match
#   - Throws only fire from satisfied graph prerequisites
#   - STUFFED throws occasionally open ne-waza
#   - Referee calls Matte for real reasons
#   - Match ends on ippon, accumulated waza-ari, or time

import sys
import os
import io

# Force UTF-8 output so arrow characters print correctly on Windows
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Allow running from the project root or from src/
sys.path.insert(0, os.path.dirname(__file__))

from enums import BodyArchetype, BeltRank, DominantSide
from throws import ThrowID, ComboID, JudokaThrowProfile
from judoka import Identity, Capability, State, Judoka
from body_state import place_judoka
from match import Match
from referee import build_suzuki, build_petrov
from debug_inspector import DebugSession, PAUSE_TRIGGERS, DEFAULT_PAUSE_ON


# ===========================================================================
# BUILD TANAKA
# LEVER archetype. Seoi-nage specialist. Age 26. Right-dominant.
# High right-hand, fight IQ, and shoulder strength — his grip is the weapon.
# ===========================================================================
def build_tanaka() -> Judoka:

    identity = Identity(
        name="Tanaka",
        age=26,
        weight_class="-90kg",
        height_cm=183,
        body_archetype=BodyArchetype.LEVER,
        belt_rank=BeltRank.BLACK_1,
        dominant_side=DominantSide.RIGHT,
        personality_facets={
            "aggressive": 4,
            "technical": 2,
            "confident": 3,
            "loyal_to_plan": 3,
        },
        arm_reach_cm=190,
        hip_height_cm=101,
        nationality="Japanese",
    )

    capability = Capability(
        right_hand=9,
        left_hand=6,
        right_forearm=8,
        left_forearm=6,
        right_bicep=8,
        left_bicep=6,
        right_shoulder=9,
        left_shoulder=7,
        right_leg=8,
        left_leg=7,
        right_foot=8,
        left_foot=7,
        core=8,
        lower_back=7,
        neck=7,
        cardio_capacity=7,
        cardio_efficiency=7,
        composure_ceiling=8,
        fight_iq=8,
        ne_waza_skill=5,
        # New v0.4 body parts
        right_hip=8,
        left_hip=7,
        right_thigh=7,
        left_thigh=6,
        right_knee=7,
        left_knee=6,
        right_wrist=8,
        left_wrist=6,
        head=5,
        throw_vocabulary=[
            ThrowID.SEOI_NAGE,
            ThrowID.HARAI_GOSHI,
            ThrowID.TAI_OTOSHI,
            ThrowID.O_UCHI_GARI,
            ThrowID.KO_UCHI_GARI,
            ThrowID.O_SOTO_GARI,
        ],
        throw_profiles={
            ThrowID.SEOI_NAGE: JudokaThrowProfile(
                ThrowID.SEOI_NAGE, effectiveness_dominant=9, effectiveness_off_side=3
            ),
            ThrowID.HARAI_GOSHI: JudokaThrowProfile(
                ThrowID.HARAI_GOSHI, effectiveness_dominant=7, effectiveness_off_side=4
            ),
            ThrowID.TAI_OTOSHI: JudokaThrowProfile(
                ThrowID.TAI_OTOSHI, effectiveness_dominant=6, effectiveness_off_side=5
            ),
            ThrowID.O_UCHI_GARI: JudokaThrowProfile(
                ThrowID.O_UCHI_GARI, effectiveness_dominant=6, effectiveness_off_side=5
            ),
            ThrowID.KO_UCHI_GARI: JudokaThrowProfile(
                ThrowID.KO_UCHI_GARI, effectiveness_dominant=7, effectiveness_off_side=6
            ),
            ThrowID.O_SOTO_GARI: JudokaThrowProfile(
                ThrowID.O_SOTO_GARI, effectiveness_dominant=5, effectiveness_off_side=4
            ),
        },
        signature_throws=[ThrowID.SEOI_NAGE, ThrowID.HARAI_GOSHI],
        signature_combos=[
            ComboID.KO_UCHI_TO_SEOI,
            ComboID.HARAI_TO_TAI_OTOSHI,
        ],
    )

    return Judoka(identity=identity, capability=capability, state=State.fresh(capability, identity))


# ===========================================================================
# BUILD SATO
# MOTOR archetype. Uchi-mata specialist. Age 24. Right-dominant.
# Elite legs and cardio — he attritions you into a mistake.
# ===========================================================================
def build_sato() -> Judoka:

    identity = Identity(
        name="Sato",
        age=24,
        weight_class="-90kg",
        height_cm=178,
        body_archetype=BodyArchetype.MOTOR,
        belt_rank=BeltRank.BLACK_1,
        dominant_side=DominantSide.RIGHT,
        personality_facets={
            "aggressive": 8,
            "technical": 6,
            "confident": 8,
            "loyal_to_plan": 6,
        },
        arm_reach_cm=183,
        hip_height_cm=96,
        nationality="Japanese",
    )

    capability = Capability(
        right_hand=7,
        left_hand=7,
        right_forearm=8,
        left_forearm=7,
        right_bicep=7,
        left_bicep=7,
        right_shoulder=7,
        left_shoulder=7,
        right_leg=9,
        left_leg=8,
        right_foot=7,
        left_foot=7,
        core=9,
        lower_back=8,
        neck=7,
        cardio_capacity=9,
        cardio_efficiency=9,
        composure_ceiling=7,
        fight_iq=6,
        ne_waza_skill=6,
        # New v0.4 body parts
        right_hip=8,
        left_hip=8,
        right_thigh=9,
        left_thigh=8,
        right_knee=7,
        left_knee=7,
        right_wrist=7,
        left_wrist=7,
        head=5,
        throw_vocabulary=[
            ThrowID.UCHI_MATA,
            ThrowID.O_UCHI_GARI,
            ThrowID.O_SOTO_GARI,
            ThrowID.KO_UCHI_GARI,
            ThrowID.HARAI_GOSHI,
            ThrowID.SUMI_GAESHI,
        ],
        throw_profiles={
            ThrowID.UCHI_MATA: JudokaThrowProfile(
                ThrowID.UCHI_MATA, effectiveness_dominant=9, effectiveness_off_side=5
            ),
            ThrowID.O_UCHI_GARI: JudokaThrowProfile(
                ThrowID.O_UCHI_GARI, effectiveness_dominant=7, effectiveness_off_side=6
            ),
            ThrowID.O_SOTO_GARI: JudokaThrowProfile(
                ThrowID.O_SOTO_GARI, effectiveness_dominant=7, effectiveness_off_side=5
            ),
            ThrowID.KO_UCHI_GARI: JudokaThrowProfile(
                ThrowID.KO_UCHI_GARI, effectiveness_dominant=6, effectiveness_off_side=6
            ),
            ThrowID.HARAI_GOSHI: JudokaThrowProfile(
                ThrowID.HARAI_GOSHI, effectiveness_dominant=6, effectiveness_off_side=4
            ),
            ThrowID.SUMI_GAESHI: JudokaThrowProfile(
                ThrowID.SUMI_GAESHI, effectiveness_dominant=5, effectiveness_off_side=7
            ),
        },
        signature_throws=[ThrowID.UCHI_MATA, ThrowID.O_UCHI_GARI],
        signature_combos=[ComboID.O_UCHI_TO_UCHI_MATA],
    )

    return Judoka(identity=identity, capability=capability, state=State.fresh(capability, identity))


# ===========================================================================
# BUILD YAMAMOTO / KIMURA (white-belt contrast pair)
# Structurally identical to Tanaka / Sato — same physical stats, same
# signature throws, same archetype. Only the belt rank and fight IQ change.
# The point is to see the same judo body with different skill compression.
# ===========================================================================
def build_yamamoto() -> Judoka:
    j = build_tanaka()
    j.identity.name       = "Yamamoto"
    j.identity.belt_rank  = BeltRank.WHITE
    j.capability.fight_iq = 3
    return j


def build_kimura() -> Judoka:
    j = build_sato()
    j.identity.name       = "Kimura"
    j.identity.belt_rank  = BeltRank.WHITE
    j.capability.fight_iq = 3
    return j


# ===========================================================================
# MATCHUPS
# ===========================================================================
MATCHUPS = {
    "1": (
        "Tanaka (BLACK_1, Seoi) vs Sato (BLACK_1, Uchi-mata)",
        build_tanaka, build_sato,
    ),
    "2": (
        "Yamamoto (WHITE) vs Kimura (WHITE)",
        build_yamamoto, build_kimura,
    ),
}


def _print_match_header(a: Judoka, b: Judoka, ref) -> None:
    from throws import THROW_REGISTRY as TR
    a_sig = TR[a.capability.signature_throws[0]].name
    b_sig = TR[b.capability.signature_throws[0]].name
    print()
    print("=== Match starting ===")
    print(f"{a.identity.name:<8} ({a.identity.belt_rank.name}) — {a_sig} specialist")
    print(f"{b.identity.name:<8} ({b.identity.belt_rank.name}) — {b_sig} specialist")
    print(f"Referee: {ref.name}")


def _run_one_match(
    build_a, build_b, ref_builder, debug=None, seed=None, stream="both",
) -> None:
    import random
    if seed is not None:
        random.seed(seed)

    a   = build_a()
    b   = build_b()
    ref = ref_builder()

    # Physics-substrate Part 1.8: both judoka face each other at 1.0 m
    # separation (CoM to CoM), centered on the mat origin.
    place_judoka(a, com_position=(-0.5, 0.0), facing=(1.0, 0.0))
    place_judoka(b, com_position=(+0.5, 0.0), facing=(-1.0, 0.0))

    _print_match_header(a, b, ref)
    match = Match(
        fighter_a=a, fighter_b=b, referee=ref,
        debug=debug, seed=seed, stream=stream,
    )
    match.run()


def _interactive_loop(
    ref_builder, debug_factory=None, seed_for_next=None, stream="both",
) -> None:
    while True:
        print()
        print("Choose a matchup:")
        for key, (label, _, _) in MATCHUPS.items():
            print(f"  [{key}] {label}")
        print("  [3] Quit")
        try:
            choice = input("> ").strip()
        except EOFError:
            break
        if choice == "3" or choice.lower() in ("q", "quit", "exit"):
            break
        if choice not in MATCHUPS:
            print(f"Unknown option: {choice!r}")
            continue
        _, build_a, build_b = MATCHUPS[choice]
        debug = debug_factory() if debug_factory else None
        seed = seed_for_next() if seed_for_next else None
        _run_one_match(
            build_a, build_b, ref_builder,
            debug=debug, seed=seed, stream=stream,
        )


# ===========================================================================
# ENTRY POINT
# ===========================================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run a Hajime match.")
    parser.add_argument("--referee", choices=["suzuki", "petrov"], default="suzuki",
                        help="Which referee personality to use (default: suzuki)")
    parser.add_argument("--runs", type=int, default=None,
                        help="Number of matches to run non-interactively. "
                             "If omitted, the interactive matchup menu opens.")
    parser.add_argument("--matchup", choices=list(MATCHUPS.keys()), default="1",
                        help="Which matchup to run for scripted --runs batches "
                             "(default: 1)")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed for reproducible runs")
    parser.add_argument("--debug", action="store_true",
                        help="Enable the calibration-observation overlay "
                             "(HAJ-20). Events are tagged with handles "
                             "(F#A, G#03, T#01, ...) and the match pauses "
                             "at key beats for inspection. Inside a pause, "
                             "type a handle to expand it, or `help`.")
    parser.add_argument("--pause-on", default=None,
                        help="Comma-separated pause triggers, or `all` / "
                             "`none`. Implies --debug. Available: "
                             + ", ".join(sorted(PAUSE_TRIGGERS))
                             + f". Default: {','.join(sorted(DEFAULT_PAUSE_ON))}.")
    parser.add_argument("--stream", choices=["debug", "prose", "both"],
                        default="both",
                        help="Which log stream to emit (HAJ-65). `debug` is "
                             "tick-prefixed with physics, grip edges and "
                             "handles; `prose` is reader-facing narrative "
                             "with no tick prefix or eq= numerics; `both` "
                             "(default) renders the two streams side-by-side "
                             "— engineer/tick on the left, prose with a "
                             "countdown match clock on the right.")
    args = parser.parse_args()

    import random
    # Per-match seeds. If --seed is given, match i uses args.seed+i (so every
    # printed seed reproduces its match exactly with --seed=<that> --runs=1).
    # If --seed is omitted, we draw a fresh seed per match from the OS RNG.
    _sys_rng = random.SystemRandom()
    _match_counter = [0]

    def seed_for_next():
        if args.seed is not None:
            s = args.seed + _match_counter[0]
        else:
            s = _sys_rng.randrange(2**31)
        _match_counter[0] += 1
        return s

    ref_builder = build_suzuki if args.referee == "suzuki" else build_petrov

    debug_enabled = args.debug or args.pause_on is not None
    if debug_enabled:
        if args.pause_on is None:
            pause_on = set(DEFAULT_PAUSE_ON)
        elif args.pause_on in ("all",):
            pause_on = set(PAUSE_TRIGGERS)
        elif args.pause_on in ("none", ""):
            pause_on = set()
        else:
            requested = {p.strip() for p in args.pause_on.split(",") if p.strip()}
            unknown = requested - set(PAUSE_TRIGGERS)
            if unknown:
                parser.error(
                    f"--pause-on: unknown trigger(s) {sorted(unknown)}. "
                    f"Available: {sorted(PAUSE_TRIGGERS)}"
                )
            pause_on = requested

        def debug_factory():
            return DebugSession(pause_on=pause_on)
    else:
        def debug_factory():
            return None

    if args.runs is None:
        _interactive_loop(
            ref_builder, debug_factory=debug_factory,
            seed_for_next=seed_for_next, stream=args.stream,
        )
    else:
        _, build_a, build_b = MATCHUPS[args.matchup]
        for i in range(args.runs):
            if args.runs > 1:
                print(f"\n{'#' * 65}")
                print(f"# MATCH {i + 1} of {args.runs}")
                print(f"{'#' * 65}")
            _run_one_match(
                build_a, build_b, ref_builder,
                debug=debug_factory(), seed=seed_for_next(),
                stream=args.stream,
            )
