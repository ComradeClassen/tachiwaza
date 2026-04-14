# match.py
# Phase 2: Real throw attempt resolution and scoring.
#
# This module does three things:
#   1. resolve_throw() — the core formula: two judoka + a throw + stance matchup
#      → returns IPPON, WAZA_ARI, STUFFED, or FAILED.
#   2. Match.run() — the tick loop. Each tick, each fighter may attempt a throw.
#      resolve_throw() is called; the result updates scoring and fatigue.
#   3. Match._resolve_match() — reads the actual score dict (no longer a placeholder)
#      to declare the winner, or calls a draw on time if scores are tied.
#
# What's NOT here (Session 2 / Phase 3):
#   - Matte detection logic (the ne_waza_window flag exists but nothing acts on it yet)
#   - Referee class
#   - Composure changes from referee calls
#   - Ne-waza window resolution

import random
from dataclasses import dataclass, field
from typing import Optional

from enums import BodyArchetype, DominantSide, StanceMatchup
from judoka import Judoka
from throws import ThrowID, THROW_REGISTRY


# ---------------------------------------------------------------------------
# TUNING CONSTANTS
# All calibration knobs are collected here so the designer can find them
# without reading the formula code. Phase 5 is a calibration pass —
# everything below will be adjusted after watching many simulated matches.
# ---------------------------------------------------------------------------

# How often each archetype attempts a throw per tick.
# At 240 ticks, LEVER (0.06) attempts ~14 throws; MOTOR (0.08) attempts ~19.
# These rates are the first lever to pull if matches feel too slow or too fast.
ATTEMPT_PROB: dict[BodyArchetype, float] = {
    BodyArchetype.LEVER:             0.06,
    BodyArchetype.MOTOR:             0.08,   # relentless — always attacking
    BodyArchetype.GRIP_FIGHTER:      0.05,   # patient — sets up the grip war first
    BodyArchetype.GROUND_SPECIALIST: 0.06,
    BodyArchetype.EXPLOSIVE:         0.03,   # low volume, high commitment when it fires
}

# Throws that live and die on grip strength (hands + forearms do the entry work).
# Everything else is a leg-dominant or hip-dominant throw.
GRIP_DOMINANT_THROWS: frozenset[ThrowID] = frozenset({
    ThrowID.SEOI_NAGE,   # shoulder throw — the entry pull is entirely in the hands/forearms
    ThrowID.TAI_OTOSHI,  # body drop — no hip contact; the block and sweep rely on arm control
})

# Stance matchup effects on throw effectiveness.
# MIRRORED (one orthodox, one southpaw) disrupts the standard grip map —
# most throws get harder. Sumi-gaeshi is the exception: it was built for
# the inside-foot hook that only a mirrored stance creates.
MIRRORED_PENALTY:           float = 0.85   # most throws are 15% less effective in mirrored
SUMI_GAESHI_MIRRORED_BONUS: float = 1.20   # sumi-gaeshi is 20% MORE effective in mirrored

# Randomness spread for throw resolution. Gaussian with this std deviation.
# Higher = more variance per attempt; lower = outcomes feel more deterministic.
# At NOISE_STD=2.0, the 10th–90th percentile range is roughly ±2.6 net points.
NOISE_STD: float = 2.0

# Outcome thresholds. net = attack_strength − defender_resistance + noise.
# Read these as: "how much better does the attack need to be than the defense?"
IPPON_THRESHOLD:    float =  4.0   # decisive — opponent fully airborne and controlled
WAZA_ARI_THRESHOLD: float =  1.5   # substantial — opponent went down but rolled or stalled
STUFFED_THRESHOLD:  float = -2.0   # committed and stopped — ground window opens

# How much fatigue each outcome applies to the attacker's load-bearing body parts.
# FAILED costs the most — wasted burst energy with no technique to show for it.
# IPPON costs least — clean technique is more efficient than a struggle.
THROW_FATIGUE: dict[str, float] = {
    "IPPON":    0.015,
    "WAZA_ARI": 0.018,
    "STUFFED":  0.025,
    "FAILED":   0.030,
}

# Background drain per tick — applies every tick, not just on throws.
# Hands: constant grip resistance throughout a live match.
# Cardio: sustained cardiovascular output across the full 4 minutes.
CARDIO_DRAIN_PER_TICK: float = 0.002   # drains ~0.48 over 240 ticks
HAND_FATIGUE_PER_TICK: float = 0.001   # accumulates ~0.24 over 240 ticks

# When picking a throw, how often to pick from signature_throws vs full vocabulary.
SIGNATURE_PICK_RATE: float = 0.65


# ---------------------------------------------------------------------------
# RESOLVE THROW
# Module-level function (not a method) so it can be read and tested
# independently without needing a Match object.
#
# Why it lives in match.py and not throws.py:
#   throws.py is reference data — what a throw IS (name, description, profiles).
#   This function is match logic — what happens when a throw is ATTEMPTED.
#   Mixing them would make throws.py know about fatigue, stance matchups,
#   and Judoka state, which is the Match layer's business.
# ---------------------------------------------------------------------------
def resolve_throw(
    attacker: "Judoka",
    defender: "Judoka",
    throw_id: ThrowID,
    stance_matchup: StanceMatchup,
) -> str:
    """Resolve one throw attempt. Returns 'IPPON', 'WAZA_ARI', 'STUFFED', or 'FAILED'.

    The formula in plain English:
        1. How good is the attacker at this throw from their current attacking side?
        2. Does the stance matchup help or hurt this particular throw?
        3. How capable are the attacker's load-bearing body parts right now?
        4. How stable is the defender's base right now?
        5. Add a random noise term — same setup, different roll each time.
        6. net = attack_strength − defender_resistance + noise → compare to thresholds.

    Every weight and threshold here is a tuning knob, not a truth.
    Phase 5 calibration will revise these after watching many matches.
    """

    # --- 1. Throw effectiveness from the attacker's current attacking side ---
    profile = attacker.capability.throw_profiles.get(throw_id)
    if profile is None:
        # The attacker doesn't have a trained profile for this throw.
        # Should not happen if _pick_throw() checks vocabulary, but safe fallback.
        return "FAILED"

    # Is the attacker attacking from their trained (dominant) side right now?
    # A RIGHT-dominant fighter in ORTHODOX stance drives from the right = dominant.
    # If they've switched to SOUTHPAW, they're attacking from the off-side.
    # (Phase 1: both fighters are always ORTHODOX, so both always attack dominant.)
    attacking_dominant = (
        (attacker.identity.dominant_side == DominantSide.RIGHT and
         attacker.state.current_stance.name == "ORTHODOX")
        or
        (attacker.identity.dominant_side == DominantSide.LEFT and
         attacker.state.current_stance.name == "SOUTHPAW")
    )
    effectiveness = (
        profile.effectiveness_dominant if attacking_dominant
        else profile.effectiveness_off_side
    )
    # effectiveness is now 0–10, representing how well this fighter knows
    # this throw from the side they're currently attacking from.

    # --- 2. Stance matchup modifier ---
    # MATCHED stances (both orthodox or both southpaw) produce the standard grip war.
    # MIRRORED stances (one of each) disrupt the standard grip map: the collar-and-sleeve
    # positions swap, throw entries change, and most throws get harder.
    # Sumi-gaeshi is designed for exactly the inside-foot hook that mirrored creates.
    if stance_matchup == StanceMatchup.MIRRORED:
        stance_mod = (SUMI_GAESHI_MIRRORED_BONUS if throw_id == ThrowID.SUMI_GAESHI
                      else MIRRORED_PENALTY)
    else:
        stance_mod = 1.0  # MATCHED: no adjustment

    # --- 3. Attacker body part contribution ---
    # Not all body parts matter equally for every throw.
    # Grip throws (seoi-nage, tai-otoshi): the entry is a pulling action —
    #   the dominant hand and forearm do the work; core and lower_back provide the lift.
    # Leg throws (everything else): the reaping/sweeping leg is the engine;
    #   core and lower_back anchor the rotation.
    # Using effective_body_part() — which already folds in age modifier, fatigue,
    # and injury — means a fatigued seoi specialist is weaker in exactly the right parts.
    dom = attacker.identity.dominant_side
    if throw_id in GRIP_DOMINANT_THROWS:
        key_parts = (
            ["right_hand", "right_forearm", "core", "lower_back"]
            if dom == DominantSide.RIGHT
            else ["left_hand", "left_forearm", "core", "lower_back"]
        )
    else:
        key_parts = (
            ["right_leg", "core", "lower_back"]
            if dom == DominantSide.RIGHT
            else ["left_leg", "core", "lower_back"]
        )

    attacker_body_avg = (
        sum(attacker.effective_body_part(p) for p in key_parts) / len(key_parts)
    )

    # Body condition scales the throw between 50% (completely cooked) and 100% (fully fresh).
    # Formula: 0.5 + 0.5 × (body_avg / 10).
    # Why 0.5 as the floor: even an exhausted specialist doesn't forget their technique —
    # the throw just costs more and lands less cleanly. The floor prevents zeroing out.
    attacker_body_mod = 0.5 + 0.5 * (attacker_body_avg / 10.0)

    # Final attack strength (0–10 scale):
    # effectiveness: how well they know this throw from this side
    # stance_mod: whether the matchup helps or hurts
    # body_mod: how much their body can actually deliver right now
    attack_strength = effectiveness * stance_mod * attacker_body_mod

    # --- 4. Defender resistance ---
    # The defender's base stability comes from three things:
    #   Legs: the primary anchor against kuzushi — strong legs absorb the load
    #   Core: holds the torso upright; a weak core bends under pull
    #   Neck: the last line — resistance to forward bend before throw entry
    # Both legs are included because most throws can load either leg depending on the angle.
    defender_parts = ["right_leg", "left_leg", "core", "neck"]
    defender_avg = (
        sum(defender.effective_body_part(p) for p in defender_parts) / len(defender_parts)
    )
    defender_body_mod = 0.5 + 0.5 * (defender_avg / 10.0)
    defender_resistance = defender_avg * defender_body_mod
    # Also 0–10 scale, comparable to attack_strength.

    # --- 5. Randomness ---
    # Judo is not deterministic. A small weight shift, a half-second of hesitation,
    # a floor grip from the wrong angle. The Gaussian noise captures irreducible
    # variance so identical setups don't always resolve the same way.
    noise = random.gauss(0, NOISE_STD)

    # --- 6. Threshold comparison ---
    net = attack_strength - defender_resistance + noise

    if net >= IPPON_THRESHOLD:
        return "IPPON"
    elif net >= WAZA_ARI_THRESHOLD:
        return "WAZA_ARI"
    elif net >= STUFFED_THRESHOLD:
        return "STUFFED"
    else:
        return "FAILED"


# ===========================================================================
# MATCH
# Runs the simulation. The tick loop calls resolve_throw() each time a fighter
# attempts a throw, then wires the result into scoring and fatigue.
# ===========================================================================
@dataclass
class Match:
    """Runs a single judo match between two judoka across a tick-based loop."""
    judoka_a: Judoka   # blue (ao) side
    judoka_b: Judoka   # white (shiro) side
    total_ticks: int = 240  # 240 ticks = 4 minutes at 1 tick/second (IJF senior)

    # Internal state — set during run(), not constructor parameters.
    # field(default=..., init=False) means these don't appear in Match(a, b).
    ne_waza_window: bool         = field(default=False,  init=False)
    match_over:     bool         = field(default=False,  init=False)
    winner:         Optional[Judoka] = field(default=None, init=False)
    ticks_run:      int          = field(default=0,      init=False)

    def run(self) -> None:
        self._print_header()
        self._run_tick_loop()
        self._resolve_match()

    # -----------------------------------------------------------------------
    # HEADER
    # -----------------------------------------------------------------------
    def _print_header(self) -> None:
        a = self.judoka_a.identity
        b = self.judoka_b.identity
        print()
        print("=" * 60)
        print(f"  MATCH: {a.name} (blue) vs {b.name} (white)")
        print(f"  {a.name}: {a.body_archetype.name}, {a.dominant_side.name}-dominant, age {a.age}")
        print(f"  {b.name}: {b.body_archetype.name}, {b.dominant_side.name}-dominant, age {b.age}")
        print("=" * 60)
        print()

    # -----------------------------------------------------------------------
    # TICK LOOP
    # The engine. Every tick:
    #   1. Clear the ne-waza window flag from last tick.
    #   2. Apply background fatigue (hands + cardio).
    #   3. Possibly attempt a throw for each fighter.
    #   4. Check match-over after each throw.
    # -----------------------------------------------------------------------
    def _run_tick_loop(self) -> None:
        for tick in range(1, self.total_ticks + 1):
            self.ticks_run = tick

            # The ne-waza window flag from a stuffed throw lasts exactly one tick.
            # Session 2 / Phase 3 will read this flag before it clears and resolve
            # the ground scramble. For now it just exists as a seam.
            self.ne_waza_window = False

            # Background drain: grip resistance and cardio happen every tick,
            # not only on throw attempts.
            self._accumulate_base_fatigue(self.judoka_a)
            self._accumulate_base_fatigue(self.judoka_b)

            # --- Fighter A throw attempt ---
            prob_a = ATTEMPT_PROB[self.judoka_a.identity.body_archetype]
            if random.random() < prob_a:
                throw_id     = self._pick_throw(self.judoka_a)
                matchup      = self._compute_stance_matchup()
                result       = resolve_throw(self.judoka_a, self.judoka_b, throw_id, matchup)
                self._apply_throw_result(self.judoka_a, self.judoka_b, throw_id, result, tick)
                if self.match_over:
                    break

            # --- Fighter B throw attempt (only if A didn't just win) ---
            if not self.match_over:
                prob_b = ATTEMPT_PROB[self.judoka_b.identity.body_archetype]
                if random.random() < prob_b:
                    throw_id = self._pick_throw(self.judoka_b)
                    matchup  = self._compute_stance_matchup()
                    result   = resolve_throw(self.judoka_b, self.judoka_a, throw_id, matchup)
                    self._apply_throw_result(self.judoka_b, self.judoka_a, throw_id, result, tick)
                    if self.match_over:
                        break

    # -----------------------------------------------------------------------
    # HELPERS
    # -----------------------------------------------------------------------
    def _compute_stance_matchup(self) -> StanceMatchup:
        """Both fighters start ORTHODOX → MATCHED. Changes if one switches stance (Phase 3+)."""
        a = self.judoka_a.state.current_stance
        b = self.judoka_b.state.current_stance
        return StanceMatchup.MATCHED if a == b else StanceMatchup.MIRRORED

    def _pick_throw(self, judoka: "Judoka") -> ThrowID:
        """Pick a throw to attempt. Signature throws chosen ~65% of the time.

        Signature throws are the ones a fighter has drilled most — they're the first
        thing a fighter reaches for under pressure. The other 35% represents variation:
        mixing in setups, combos, and throws from outside the usual game plan.
        """
        if judoka.capability.signature_throws and random.random() < SIGNATURE_PICK_RATE:
            return random.choice(judoka.capability.signature_throws)
        return random.choice(judoka.capability.throw_vocabulary)

    def _apply_throw_result(
        self,
        attacker: "Judoka",
        defender: "Judoka",
        throw_id: ThrowID,
        result: str,
        tick: int,
    ) -> None:
        """Log the attempt, update the score dict, apply fatigue, flag ne-waza window."""
        throw_name = THROW_REGISTRY[throw_id].name
        a_name = attacker.identity.name
        d_name = defender.identity.name

        print(f"tick {tick:03d}: {a_name} attempts {throw_name} - {result}")

        if result == "IPPON":
            # A clean, complete throw. Match ends immediately.
            attacker.state.score["ippon"] = True
            self.match_over = True
            self.winner = attacker
            print(f"         IPPON. {a_name} wins.")

        elif result == "WAZA_ARI":
            attacker.state.score["waza_ari"] += 1
            wa = attacker.state.score["waza_ari"]
            print(f"         Waza-ari. {a_name} scores ({wa}/2).")
            if wa >= 2:
                # Two waza-ari equals ippon under current IJF rules.
                self.match_over = True
                self.winner = attacker
                print(f"         Two waza-ari. {a_name} wins.")

        elif result == "STUFFED":
            # Attacker committed fully and was stopped. In real judo this is
            # exactly when the defender can transition to the ground. We flag it
            # here; Session 2 will resolve what happens during that window.
            self.ne_waza_window = True
            print(f"         Stuffed. {d_name} defended. Ne-waza window open.")

        else:  # FAILED
            # Attacker didn't get far enough in for defense to be interesting.
            # No ground window. Just wasted energy.
            print(f"         Failed. {a_name} didn't commit.")

        # Apply throw-specific fatigue to the attacker's relevant body parts.
        # This happens for every result — even IPPON costs energy.
        self._apply_throw_fatigue(attacker, throw_id, result)

    def _apply_throw_fatigue(
        self, attacker: "Judoka", throw_id: ThrowID, result: str
    ) -> None:
        """Add throw fatigue to the attacker's load-bearing parts for this throw type."""
        delta = THROW_FATIGUE[result]
        dom = attacker.identity.dominant_side

        if throw_id in GRIP_DOMINANT_THROWS:
            parts = (
                ["right_hand", "right_forearm", "core", "lower_back"]
                if dom == DominantSide.RIGHT
                else ["left_hand", "left_forearm", "core", "lower_back"]
            )
        else:
            parts = (
                ["right_leg", "core", "lower_back"]
                if dom == DominantSide.RIGHT
                else ["left_leg", "core", "lower_back"]
            )

        for part in parts:
            attacker.state.body[part].fatigue = min(
                1.0,
                attacker.state.body[part].fatigue + delta,
            )

    def _accumulate_base_fatigue(self, judoka: "Judoka") -> None:
        """Background drain every tick: both hands from grip, cardio from sustained output."""
        s = judoka.state
        s.body["right_hand"].fatigue = min(1.0, s.body["right_hand"].fatigue + HAND_FATIGUE_PER_TICK)
        s.body["left_hand"].fatigue  = min(1.0, s.body["left_hand"].fatigue  + HAND_FATIGUE_PER_TICK)
        s.cardio_current = max(0.0, s.cardio_current - CARDIO_DRAIN_PER_TICK)

    # -----------------------------------------------------------------------
    # MATCH RESOLUTION
    # Reads the actual score dict. Handles time expiry.
    # -----------------------------------------------------------------------
    def _resolve_match(self) -> None:
        """Declare the winner from real scoring, or call a draw on tied time expiry."""
        print()
        print("=" * 60)

        if self.winner:
            # Won during the tick loop by ippon or two waza-ari.
            method = "ippon" if self.winner.state.score["ippon"] else "two waza-ari"
            print(f"  MATCH OVER - {self.winner.identity.name} wins by {method}")
            print(f"  Ended at tick {self.ticks_run} / {self.total_ticks}")
        else:
            # Time expired. Highest waza-ari count wins.
            a_wa = self.judoka_a.state.score["waza_ari"]
            b_wa = self.judoka_b.state.score["waza_ari"]
            a_name = self.judoka_a.identity.name
            b_name = self.judoka_b.identity.name

            if a_wa > b_wa:
                self.winner = self.judoka_a
                print(f"  MATCH OVER - {a_name} wins by decision ({a_wa}-{b_wa} waza-ari)")
            elif b_wa > a_wa:
                self.winner = self.judoka_b
                print(f"  MATCH OVER - {b_name} wins by decision ({b_wa}-{a_wa} waza-ari)")
            else:
                # Tied on waza-ari at time. Golden score (sudden death) is Phase 3.
                print(f"  MATCH OVER - Draw ({a_wa}-{b_wa} waza-ari). Golden score pending (Phase 3).")

        print("=" * 60)
        self._print_final_state(self.judoka_a)
        self._print_final_state(self.judoka_b)

    def _print_final_state(self, judoka: "Judoka") -> None:
        """End-of-match summary: score, fatigue on the parts that worked, effective values."""
        ident = judoka.identity
        cap   = judoka.capability
        state = judoka.state

        print()
        print(f"  {ident.name} - end of match")
        print(f"    score:        waza-ari={state.score['waza_ari']}  ippon={state.score['ippon']}")
        print(f"    cardio:       {state.cardio_current:.3f}  (drained from 1.0)")
        print(f"    right_hand:   fatigue={state.body['right_hand'].fatigue:.3f}"
              f"  effective={judoka.effective_body_part('right_hand'):.2f}"
              f"  (base cap {cap.right_hand})")
        print(f"    right_leg:    fatigue={state.body['right_leg'].fatigue:.3f}"
              f"  effective={judoka.effective_body_part('right_leg'):.2f}"
              f"  (base cap {cap.right_leg})")
        print(f"    core:         fatigue={state.body['core'].fatigue:.3f}"
              f"  effective={judoka.effective_body_part('core'):.2f}"
              f"  (base cap {cap.core})")
        print(f"    lower_back:   fatigue={state.body['lower_back'].fatigue:.3f}"
              f"  effective={judoka.effective_body_part('lower_back'):.2f}"
              f"  (base cap {cap.lower_back})")

        from throws import THROW_REGISTRY
        sig_display = [THROW_REGISTRY[t].name for t in cap.signature_throws]
        print(f"    signature:    {', '.join(sig_display)}")
