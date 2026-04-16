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
from match import Match
from referee import build_suzuki, build_petrov


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

    return Judoka(identity=identity, capability=capability, state=State.fresh(capability))


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

    return Judoka(identity=identity, capability=capability, state=State.fresh(capability))


# ===========================================================================
# ENTRY POINT
# ===========================================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run a Tachiwaza match.")
    parser.add_argument("--referee", choices=["suzuki", "petrov"], default="suzuki",
                        help="Which referee personality to use (default: suzuki)")
    parser.add_argument("--runs", type=int, default=1,
                        help="Number of matches to run (default: 1)")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed for reproducible runs")
    args = parser.parse_args()

    if args.seed is not None:
        import random
        random.seed(args.seed)

    ref_builder = build_suzuki if args.referee == "suzuki" else build_petrov

    for i in range(args.runs):
        if args.runs > 1:
            print(f"\n{'#' * 65}")
            print(f"# MATCH {i + 1} of {args.runs}")
            print(f"{'#' * 65}")

        tanaka = build_tanaka()
        sato   = build_sato()
        ref    = ref_builder()

        match = Match(fighter_a=tanaka, fighter_b=sato, referee=ref)
        match.run()
