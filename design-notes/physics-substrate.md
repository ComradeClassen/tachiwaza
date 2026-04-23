# Physics Substrate — Hajime v0.1
### The physical model underneath Ring 1

*Session 3 output. Completed April 17, 2026 across a single six-hour design session. Mode B (design-only, per `session-3-mode-decision.md`). Written to be implemented in Ring 1, not Ring 1.5. Reference: `Kuzushi, Couples, and Levers: A Biomechanics Reference for a Judo Simulation` (research artifact produced April 17, 2026).*

**Status: v0.1 complete. Ready for Session 4 implementation.** All six parts specified: body state (Part 1), grips as force-couplings (Part 2), the force model and tick update (Part 3), the two throw templates (Part 4), four worked throws with variants (Part 5), and cross-cutting mechanics (Part 6). Remaining throws (O-goshi, Tai-otoshi, Ko-uchi-gari, O-uchi-gari, Harai-goshi, Tomoe-nage, O-guruma) are Session 4 backfill using the same template structure. All numerical parameters (commit thresholds, force envelope magnitudes, N values) are calibration targets for Phase 3, not commitments of this spec.

---

## PURPOSE

This document specifies the physical model that underlies the match simulation. It replaces the threshold-based `compute_grip_delta()` model shipped in Phase 2 Session 2 with a model in which kuzushi is an emergent property of grip-transmitted forces acting on uke's posture and center of mass — not a scalar crossing a line.

The model is grounded in peer-reviewed biomechanics literature (Sacripanti 2008–2024; Imamura et al. 2003, 2006, 2007; Blais & Trilles 2007; Ishii et al. 2019; Liu et al. 2021–2025; Hamaguchi et al. 2025; Matsumoto et al. 1978) and Kodokan canonical sources (Kano 1986; Daigo 2005; Kawamura & Daigo 2000).

This spec does not contain code. Session 4 (Phase 2 Session 3's successor) will implement what is specified here.

---

## DESIGN PRINCIPLES

Three commitments that guide every downstream decision.

**1. Emergence over enumeration.** Throws are not items on a list that a judoka picks from. A throw emerges when the physical state satisfies the throw's four-dimension signature (kuzushi vector, force application, body-part engagement, uke posture). If the conditions aren't met, the throw isn't available — not because a rule says so, but because the physics says so. This dissolves the entire class of "Seoi-nage forced without a grip" bugs by construction.

**2. Continuous over discrete.** Posture is not {UPRIGHT, SLIGHTLY_BENT, BROKEN}. It is a set of continuous angles, heights, and polygons. Kuzushi is not a boolean. It is a vector in uke's body frame. Classical labels (shizentai, jigotai, broken balance) are UI-and-commentary regions over the continuous space, not states that gate behavior.

**3. Skill as compression, not modifier.** A white belt throws in three or four pulses (pull… enter… throw). An elite throws in one. The same move by different judoka unfolds over different numbers of ticks, because skill compresses the kuzushi-tsukuri-kake sequence into overlapping — eventually simultaneous — action. The belt system stops being a stat multiplier and becomes a tick-level temporal property.

---

## COORDINATE FRAMES

**Uke's body frame.** Origin at uke's CoM projection on the mat. +X = uke's forward-facing direction. +Y = uke's left. +Z = up. All kuzushi directions, happo-no-kuzushi buckets, and throw signature directions are defined in this frame.

**Tori's body frame.** Same construction, for tori.

**Mat frame.** Origin at mat center. Fixed axes. Used only for: mat-edge logic (shido for step-out, corner zones), referee spatial awareness, and render-layer output.

Conversions between frames happen at the match-state layer. The physics model itself operates entirely in body frames.

---

## PART 1 — BODY STATE (the state of a judoka at a single tick)

### 1.1 Overview

A judoka's physical state at any tick is captured by a `BodyState` object. This replaces the implicit scalar bookkeeping of the Phase 2 Session 2 model with an explicit set of positions, velocities, angles, and contact states that together describe what a judoka's body is doing right now.

All angles in this section are stored in radians (the computing standard) but will be displayed in degrees in the log. A quick reference:

- 30° ≈ 0.52 rad (π/6)
- 45° ≈ 0.79 rad (π/4)
- 60° ≈ 1.05 rad (π/3)
- 90° = π/2 rad

### 1.2 Center of mass

The center of mass (CoM) is the point where a body's mass is effectively concentrated. For a standing judoka it sits roughly at the navel, slightly in front of the spine. Throws are successful when tori manipulates uke's CoM relative to uke's base of support (BoS).

- `com_position` — a 2D vector in the mat frame, measured in meters. This is the projection of the judoka's CoM onto the tatami (judo mat), viewed from above. The match is a top-down system for nearly all purposes; vertical CoM position is captured separately in `com_height`.

- `com_velocity` — a 2D vector in the mat frame, in meters per second. This field is what makes *hando-no-kuzushi* (reactive off-balancing — throwing with the motion uke already has) possible. A judoka who is stepping has nonzero CoM velocity, and a skilled opponent can read that motion and throw along it rather than fight against it. Typical ranges from the literature:
  - 0 m/s during a static hold
  - 0.2–0.4 m/s during normal shifting (oikomi)
  - 1.3–1.8 m/s during an attack-in (Sacripanti competition data)

- `com_height` — a scalar in meters. This captures posture stances like *jigotai* (defensive posture — knees bent, hips low, center of gravity dropped) versus *shizentai* (natural posture — knees relaxed, upright, weight centered) without making them discrete states. A tall upright judoka in shizentai has high com_height. Drop the knees into jigotai and it falls. Typical range for a 1.75 m judoka: 0.85–1.15 m.

### 1.3 Trunk orientation

The trunk (torso) is tracked with two separate lean angles, not one. The published biomechanics literature is overwhelmingly sagittal-plane (forward-back only); we fix that methodological limitation here by tracking frontal-plane (left-right) lean as well.

- `trunk_sagittal` — forward/backward lean angle. Range: −30° to +60° (−0.52 to +1.05 rad). Positive = forward lean (toward uke). Negative = backward lean (away from uke). 0° = upright. Shizentai sits near 0°. Jigotai registers as a positive forward lean, often combined with lowered com_height. A judoka being loaded for a Seoi-nage (shoulder throw) will show strongly positive sagittal lean. A judoka leaning away to defend O-soto-gari (major outer reap) will show negative.

- `trunk_frontal` — left/right lean angle. Range: −45° to +45° (−0.79 to +0.79 rad). Positive = rightward lean. Negative = leftward lean. Mostly 0° during neutral posture. Nonzero values emerge during kuzushi events and under lateral force transmitted through grips. Often combined with trunk_sagittal to represent the "corner" directions of Happo-no-Kuzushi (eight directions of off-balance — forward, back, left, right, and the four diagonals). A uke being pulled toward the forward-right corner will have positive trunk_sagittal and positive trunk_frontal simultaneously.

### 1.4 Base of support

The base of support (BoS) is the polygon of ground contact formed by the judoka's feet. Balance is maintained when the CoM projection falls inside this polygon; when it exits, kuzushi (off-balancing — the first phase of a throw) has begun.

- `foot_state_left` and `foot_state_right` — one struct per foot, each containing:
  - `position` — a 2D vector in the mat frame, meters. Where the foot contacts (or last contacted) the ground.
  - `contact_state` — an enum: `PLANTED`, `AIRBORNE`, `DRAGGING`. A planted foot bears weight. An airborne foot bears none (mid-step, mid-throw, mid-reap). A dragging foot is in transition with partial contact, typical during suri-ashi (sliding footwork) transitions.
  - `weight_fraction` — a float in [0.0, 1.0]. Fraction of the judoka's body weight supported by this foot. In normal standing, both feet are near 0.5. During single-support (one foot airborne for a sweep, step, or reap) the planted foot is at or near 1.0. The two feet's weight fractions sum to ≤ 1.0; any shortfall represents weight being supported externally (very rare — e.g., uke leaning on tori during a failed throw).

- `base_polygon` — derived, not stored. A function that returns the BoS polygon from the two foot positions and their contact states. During double-support (both feet planted), this is a quadrilateral stretching between the outlines of the two feet. During single-support, it collapses to roughly the footprint of the one planted foot. During no-contact (both feet airborne — mid-throw), it's empty and balance is impossible. This is the single biggest vulnerability window in a match.

### 1.5 Kuzushi as weight commitment

Kuzushi is the moment uke's weight commits fully to one leg and that leg can no longer step. This is the canonical framing. It is what a judoka feels, what a coach teaches, and what a referee perceives when watching a throw open up. The pulls, pushes, and reactive forces that fill the kuzushi-tsukuri-kake sequence do not cause kuzushi directly — they *redistribute uke's weight* onto one leg. Once that leg is loaded past its capacity to step out from under the load, the throw window has opened. The pull is the cause of the weight commitment; the weight commitment is the kuzushi.

The geometric formulation that follows is the mathematical equivalent of this event. The engine computes it; the prose layer and any coach-voice output should describe the mechanism.

**The recoverable envelope.**

The recoverable envelope is the region around the BoS that a judoka can step back into if displaced. It is *not stored — computed*. As one leg's `weight_fraction` rises toward 1.0, that leg becomes the sole contributor to the envelope, and the envelope collapses asymmetrically: it can no longer extend past the stepping range of the loaded leg, because the loaded leg cannot lift to step.

```
recoverable_envelope(weight_fraction_left, weight_fraction_right,
                    com_velocity, leg_strength, fatigue, composure)
```

Inputs that shape the envelope:
- `weight_fraction` on each foot — the primary input. A leg at 1.0 cannot contribute to envelope expansion in any direction. A leg at 0.5 contributes its full stepping range.
- `com_velocity` — narrows the envelope opposite the direction of motion (committed momentum cannot easily reverse).
- `leg_strength` — per-judoka attribute; larger envelope overall for stronger legs.
- `fatigue` — shrinks the envelope as the match progresses.
- `composure` — shrinks the envelope under pressure.

**The kuzushi predicate.**

```
is_kuzushi(judoka) := com_projection(t) outside recoverable_envelope(t)
```

This is mathematically equivalent to: *one leg's weight_fraction has approached 1.0, and that leg cannot step to extend the envelope past where the CoM is now traveling*. The two predicates witness the same event. Where this spec or future tickets describe the mechanism, weight commitment is the canonical language. Where the engine computes the test, the geometric predicate is the computational form.

**Why this matters for the rest of the substrate.** Forces applied through grips (Part 2) do not directly produce kuzushi. They produce CoM displacement and trunk lean, which together cause uke's weight to redistribute toward one leg. When that redistribution reaches the locked-leg condition, kuzushi has occurred. Future tickets that introduce defensive lockouts (uke cannot pivot or step from a fully-loaded leg — see HAJ-54) are therefore not new mechanics; they are the spec stating in code what was always true in mechanism.

### 1.6 Per body part state

Each of the 24 body parts (left hand, right hand, left foot, core, right thigh, etc., from the Phase 2 Session 2 data model) carries its own state. The efficiency and fatigue fields from the existing model are retained. Added for v0.1:

- `contact_state` — an enum per body part:
  - `FREE` — no contact with anything.
  - `GRIPPING_UKE` — currently holding a grip on uke (valid only for hands).
  - `SUPPORTING_GROUND` — bearing weight on the mat (valid for feet primarily; knees or hands if fallen).
  - `CONTACTING_UKE_NONGRIP` — in contact with uke but not gripping. A thigh pressed against uke's hip mid-Uchi-mata (inner thigh throw). A shoulder under uke's armpit mid-Seoi-nage (shoulder throw). A shin barred across uke's shin mid-Tai-otoshi (body drop).
  - `STRUCK_BY_UKE` — just received impact, typically during a failed throw or counter.

This enum lets a throw's body-part engagement requirement check things like: "is tori's left foot the sole `SUPPORTING_GROUND` part right now?" (Uchi-mata's single-support requirement) or "is tori's right hip `CONTACTING_UKE_NONGRIP`?" (O-goshi's hip-loading requirement) and get a clean answer from the state without inferring it from other fields.

### 1.7 Non-physical state fields (carried over, lightly revised)

These fields drive physical behavior but aren't themselves physical quantities.

- `belt_rank` — determines the skill-compression factor N for throw attempts (see Part 6.1).
- `composure` — existing, unchanged. Feeds into recoverable envelope and force application.
- `cardio` — existing, unchanged.
- `fight_iq` — existing. Drives perception accuracy in counter-window detection.
- `stun_ticks` — integer. Nonzero after a hard impact (failed throw landing, being reaped but not fully thrown, a hip-check absorbed). Decrements one per tick until zero. While nonzero, the judoka's force application is capped and they cannot initiate new throw attempts — but they can still defend and apply grips. This captures the real-judo experience of being briefly dazed by a hard hip-block or a jarring contact without being fully disabled.

### 1.8 Initial state at t = 0

Both judoka spawn in:
- Standing in shizentai (natural posture), facing each other at 1.0 m separation (from CoM to CoM).
- `com_velocity` = (0, 0).
- `com_height` at their standing value (typically 0.95–1.05 m depending on height).
- `trunk_sagittal` = 0°, `trunk_frontal` = 0°.
- Both feet `PLANTED`, shoulder-width apart, weight 0.5 each.
- All body parts `FREE` except feet which are `SUPPORTING_GROUND`.
- No grips established.
- Full composure, full cardio, `stun_ticks` = 0.

The match begins (Hajime — the referee's command to start) from this state. Everything that happens in the match is a trajectory through `BodyState` space for both judoka, driven by their grips, their forces, and their reactions to each other.

---

## PART 2 — GRIPS AS FORCE-COUPLINGS

### 2.1 Overview

Grips are the coupling interface between tori's force and uke's body. A grip is not a location plus a depth number (as in the Phase 2 Session 2 model); it is a constrained force-coupling that carries a direction-dependent force envelope. Different grip types carry force differently. A collar grip rotates uke's trunk authoritatively but barely lifts. A belt grip lifts uke's CoM directly but rotates little. Choosing which grips to establish is choosing which throws become physically accessible.

Sacripanti (2014, arXiv:1411.2763) distinguishes grip *roles*: **connective** (binding the two judoka into a single dyadic system so a torque-based throw can act on it) and **driving** (transmitting large directed force over a long moment arm to rotate uke over a fulcrum). The same grip can play either role; which role it's playing on a given tick is a choice by the judoka.

### 2.2 Grip types (seven)

- **Sleeve (sode) grip** — the hand grips uke's sleeve, typically at the elbow or mid-forearm. Primary role: controlling uke's arm rotation. High moment arm for rotating uke's upper body around the shoulder. Low vertical lift capacity. In classical throws this is the `hikite` (pulling hand — the hand that pulls uke off balance).

- **Lapel low (eri-tori, lower) grip** — the hand grips uke's lapel at mid-chest. Standard competitive grip. Medium vertical lift, medium trunk rotation. The everyday working grip in judo.

- **Lapel high (eri-tori, upper) grip** — the hand grips uke's lapel near the collarbone. Higher moment arm for vertical lift because the grip sits further from uke's hips. More committed than lapel low, harder to strip. Often the `tsurite` (lifting hand — the hand that lifts and steers) in hip throws.

- **Collar (oku-eri) grip** — the hand reaches deep across uke's shoulder to grip the collar behind uke's neck. Maximum trunk-rotation moment arm. Dominant in modern competition. High rotational authority, less lift than a lapel grip. Georgian-style systems build entire throw games around this grip.

- **Belt (obi-tori) grip** — an arm wraps around uke's back to grip the belt. Highest direct CoM control (grip point is right at uke's waist). Critical for O-goshi (major hip throw) and traditional koshi-waza (hip techniques). Under current IJF rules, an unconventional grip: requires immediate attack or it's shido.

- **Pistol (sode-tori) grip** — the hand clamps around the end of uke's sleeve cuff, fingers inside the sleeve. Mutual-immobilization grip — both judoka struggle to do anything offensive while pistol grips are engaged. High defensive value, low offensive throughput. Unconventional under IJF rules.

- **Cross (katate-ai-gumi) grip** — tori reaches across with the "wrong" hand (right hand on uke's right lapel instead of left). Breaks standard grip geometry, opens unusual angles, disrupts uke's expected counter-grips. In many dojo (including Cranford's Georgian-influenced pedagogy) cross grip is taught as an entry to collar grab: right-hand cross-grip pull opens space for the left hand to reach over and grip the back of uke's collar. Unconventional under IJF rules — must lead to immediate attack.

### 2.3 Force envelope per grip

Each grip type carries a `ForceEnvelope` struct specifying what forces it can transmit at baseline:

- `max_pull_force` — maximum force toward tori, in Newtons.
- `max_push_force` — maximum force away from tori, in Newtons.
- `max_lift_force` — maximum vertical force (upward, against gravity).
- `moment_arm_to_uke_com` — distance from grip point to uke's CoM, in meters. Longer arm = more torque per unit force.
- `rotation_authority` — multiplier on the torque produced about uke's vertical axis.
- `strip_resistance` — how hard uke must work to strip the grip.

Exact numerical values are calibration work for Session 4 and Phase 3. What the spec commits to now is relative ordering:

| Grip | Pull | Push | Lift | Rotation auth. | Strip resist. |
|------|------|------|------|----------------|---------------|
| Sleeve | High | Low | Low | Medium | Medium |
| Lapel low | Medium | Medium | Medium | Medium | Medium |
| Lapel high | Medium | Medium | High | Medium-high | Medium-high |
| Collar | Medium | High | Medium | **Highest** | High |
| Belt | High | Medium | **Highest** | High | Very high (once seated) |
| Pistol | Low | Low | Low | Low | **Highest** |
| Cross | Medium | Medium | Medium | Variable | Low |

### 2.4 Depth, strength, fatigue, composure — modifiers on the envelope

The force a grip actually delivers on a given tick is:

```
delivered_force = envelope_max × depth_mod × strength_mod × fatigue_mod × composure_mod
```

All modifiers are in [0.0, 1.0]. A grip is never stronger than its baseline envelope; it can only be as strong or weaker.

**Depth modifiers** (carried forward from Phase 2 Session 2 with one addition):

- `POCKET` = 0.4. Fingertip grip. Tori barely has hold.
- `STANDARD` = 0.7. Normal grip, working well.
- `DEEP` = 1.0. Fully seated grip.
- `SLIPPING` = 0.2. A grip being actively stripped — still transmitting some force but degrading fast.

**Strength modifier.** A per-judoka derived attribute computed as:

```
grip_strength = (left_hand.efficiency + right_hand.efficiency + core.efficiency) / 3
```

Modulated by current fatigue of those parts. This is the same derivation pattern as `leg_strength` in Part 1.

**Fatigue modifier.** Hand-part fatigue directly multiplies into grip force. Iglesias (2003) measured ~15% grip decline across a four-match tournament; this is the mechanism by which that enters the simulation.

**Composure modifier.** A flustered judoka grips less effectively even with identical physical state. Same mechanism as composure's effect on the recoverable envelope in Part 1.

### 2.5 Grip mode — connective versus driving (per tick)

Each grip is in one of two modes on any given tick:

- **Connective mode.** The grip binds the dyad but transmits only light force — enough to maintain the connection, not enough to displace uke. Low fatigue cost per tick. A judoka can hold connective grips across many ticks without significant cost. This is what a judoka does while reading uke, waiting for an opening, or recovering from a failed attack.

- **Driving mode.** The grip actively transmits directed force toward a specific kuzushi vector. High fatigue cost per tick. Held too long, the grip-hand fatigues rapidly and the envelope collapses. This is attacking.

Mode is a per-tick choice made by the judoka's action selection (Part 3). A judoka with both grips in connective mode is neutral — probably reading the situation. Both in driving mode is actively attacking. One in each is common — a classical throw setup has the sleeve in driving mode (pulling) while the lapel holds in connective mode until the moment of kake (execution).

### 2.6 The passivity clocks

Current IJF rules impose two separate passivity mechanisms. The spec models both.

**The kumi-kata (gripping) clock.** As of the LA 2028 cycle rules (debuted Paris Grand Slam 2025): from the moment a judoka establishes any grip, they have 30 seconds to make an attack. Modeled as a per-judoka counter: starts at 30 when the first grip of an exchange seats, decrements each tick, resets when the judoka delivers a driving-mode attack (see "attack event" below). Reaches zero → referee calls shido for passivity.

**The unconventional grip clock.** Under current IJF rules, unconventional grips (cross, belt, pistol, pocket, one-sided) must lead to an immediate attack. The rule does not specify a hard numerical limit; referees judge intent, typically with 3–5 seconds of tolerance. Modeled as a per-grip counter that starts when an unconventional grip seats: ~5 ticks tolerance before the referee flags it, shido issued if no driving-mode attack occurs in that window. A classical grip (standard sleeve-lapel configuration) does not trigger this clock.

**What constitutes an "attack event" for clock purposes.** A driving-mode force application exceeding a threshold magnitude, held across at least 2 ticks, against uke's posture. This distinguishes a genuine attack from a grip shift or a brief twitch. Committing to a throw attempt is always an attack event; active kuzushi attempts via sustained driving-mode force are also attack events even if no throw is committed. Both reset both clocks.

### 2.7 Grip establishment — the REACHING state

Grips are not instantaneous. A grip attempt has a duration between "reaching for the gi" and "grip seated at DEEP." This duration is skill-compressed (see Part 6.1): a white belt takes 3–5 ticks; an elite does it in 1.

During the reach, the hand is in a third contact state (new for v0.1, added to the list in Part 1.6):

- `REACHING` — the hand is extended toward uke's gi, committed to a grip attempt, but not yet connected.

A hand in REACHING state is vulnerable:

- Uke can parry the reach (knock the extended arm away) — costs uke some force but eliminates the threat.
- Uke can counter-grip — seize the reaching hand, establishing a grip on tori's sleeve instead. If successful, tori's attempted offensive grip becomes uke's defensive sleeve grip. This is the mechanical origin of the chess-like grip fighting that defines high-level judo.
- Uke can slip backward — disengage the dyad entirely, breaking contact distance, which costs tori the reach.

When the reach completes successfully, the hand transitions from REACHING to GRIPPING_UKE at depth POCKET (a fresh grip). Further ticks can deepen the grip toward STANDARD and DEEP if strength and position allow.

### 2.8 Stripping — degrading an opponent's grip

Stripping is the inverse operation. Uke applies force against tori's grip — typically a circular motion of the gripped limb, a twist against the grip's weak axis, or a strike to the gripping wrist.

Each tick of stripping effort reduces the grip's depth by one step along the chain:

```
DEEP → STANDARD → POCKET → SLIPPING → stripped (grip ends)
```

The stripping force competes with tori's grip strength (the same strength that modulates the force envelope). If tori's grip strength at the current tick exceeds uke's stripping effort, the grip holds at current depth. If not, depth degrades by one step.

A grip that reaches SLIPPING is one tick from being lost. Tori has a choice: defend the grip (costs force that would otherwise be available for driving mode) or let it strip and try to re-establish (costs ticks, loses positional momentum). This dilemma is a core micro-decision of the grip sub-loop.

Stripping is itself a force application and therefore triggers fatigue costs on uke's hand-parts. Persistent strip attempts against a tenacious grip drain uke faster than they drain tori — the attacker's grip-defender has a favorable asymmetry.

### 2.9 Implications for Bucket 1 bugs

The grip model in this part structurally eliminates several bugs from the playthrough observation pass:

- *"Grips always seat at t002"* — dissolved. Grips now require 1–5 ticks to seat depending on skill, reach can be contested, and different grips take different times. Two judoka rarely complete all four grips on the same tick.
- *"Throw fires without required grip"* — dissolved. Throw signatures (Parts 4–5) require specific grip types in specific force-transmission modes; no grip, no signature match, no throw committable.
- *"Grips held 30+ ticks without attack"* — dissolved. The kumi-kata clock and unconventional-grip clock enforce passivity shido automatically from the model state.

---

## PART 3 — THE FORCE MODEL (what a judoka *does* on a tick)

### 3.1 Overview

This part specifies the update rule that takes both judoka's current `BodyState` (Part 1) and their grips (Part 2), applies each judoka's chosen actions for the tick, and produces the next tick's `BodyState`. This is the physics engine — runnable in pure Python, discrete-time, impulse-based. No continuous solver.

One tick = one second of match time in v0.1. This is coarser than elite biomechanical reality (a committed Seoi-nage completes in ~1 second) — the throw lands as a single event at commit, with prose covering the sub-second detail. Future versions may halve or tenth the tick; v0.1 accepts the coarseness for tractability.

### 3.2 The action space

A judoka's action on a tick is up to **two actions** selected from the space below — typically one per hand, or one body action plus one grip/force action, or a single compound action that supersedes the others.

**Grip actions** (modify the grip graph):
- `REACH(hand, target_grip_type)` — begin a reach for a specific grip. Transitions hand to `REACHING`.
- `DEEPEN(hand)` — push an existing grip one depth level down (POCKET → STANDARD → DEEP) if strength allows.
- `STRIP(hand, opponent_grip)` — apply stripping force to opponent's grip.
- `STRIP_TWO_ON_ONE(opponent_grip)` — a special strip variant using both hands on one opponent grip. Doubles stripping force but both of the judoka's hands become committed to the strip for the tick, leaving the judoka with no grips of their own during the attempt. High-reward, high-risk: if the strip succeeds, the opponent loses the grip and the judoka can re-establish fresh on the next tick. If the strip fails, the judoka has spent two hands' worth of force and ticks with nothing established, while the kumi-kata clock keeps ticking.
- `DEFEND_GRIP(hand)` — spend force to maintain a slipping grip.
- `REPOSITION_GRIP(hand, new_position)` — shift a held grip's position within its type without re-establishing. Example: slide a lapel grip from mid-chest to just below the collarbone to pre-load a Morote-seoi entry. Does not change the grip's type, only its precise location — but the new location changes which throw signatures the grip satisfies next tick.
- `RELEASE(hand)` — drop a grip voluntarily. Hand returns to `FREE`.

**Force actions** (transmit force through existing grips):
- `PULL(hand, direction, magnitude)` — driving-mode pull along a direction in uke's body frame.
- `PUSH(hand, direction, magnitude)` — driving-mode push.
- `LIFT(hand, magnitude)` — vertical-dominant force, typically through tsurite.
- `COUPLE(directions_pair, magnitude)` — coordinated two-hand action producing a torque rather than net translation. The core of Couple-class throw setups — e.g., right hand pushes uke's chest back while sleeve hand pulls forward-down, producing pure rotation about uke's vertical axis.
- `HOLD_CONNECTIVE(hand)` — keep the grip active in connective mode. Default if no driving action is chosen. Allows hand-part fatigue to recover at a slow rate (tuned in Phase 3 calibration).
- `FEINT(hand, direction, magnitude)` — apply a partial driving-mode force with no kake intent, intended to elicit a defensive reaction from the opponent. Mechanically identical to a full pull/push of similar magnitude, but carries a flag that it is *not* a setup for commitment. Whether the opponent reacts is determined by their perception (Section 3.5).

**Body actions** (modify self's body state):
- `STEP(foot, direction, magnitude)` — lift one foot and place it at a new position. Foot transitions to `AIRBORNE` during the step.
- `PIVOT(angle)` — rotate the standing frame around the supporting foot. Required for turn-in entries to hip and shoulder throws.
- `DROP_COM(magnitude)` — lower CoM by bending knees. Drives posture toward jigotai (defensive posture). Widens base polygon slightly, increases stability.
- `RAISE_COM(magnitude)` — straighten legs, raise CoM.
- `SWEEP_LEG(leg, direction, magnitude)` — reaping-foot action. The reaping leg goes `AIRBORNE`, transfers momentum to contact point on uke's leg.
- `BLOCK_LEG(leg, target_contact_on_uke)` — extend a leg as a static barrier (O-guruma's blocking axle, Tai-otoshi's shin bar).
- `LOAD_HIP(target_contact_on_uke)` — drive hip into a specific contact point on uke. Mechanical prerequisite for any hip throw.
- `ABSORB` — bend at knees and hips to dissipate incoming force. Reduces effective torque delivered through one's own grips but saves balance.

**Compound actions** (supersede the two-action limit):
- `COMMIT_THROW(throw_id)` — announce commitment to a specific throw. Validity depends on whether the four-dimension signature (Part 4) is currently satisfied. See Section 3.5 for how commit decisions are made.

### 3.3 Action selection (v0.1 priority ladder)

For v0.1, the action-selection logic lives inside the `Judoka` class as a hardcoded priority-ranked decision function. Later rings refine it with coach instructions, cultural style priors, and opponent-specific memory. The v0.1 ladder:

1. If `stun_ticks > 0`, only defensive actions are available. Pick the action that most reduces incoming threat.
2. If a throw signature is currently perceived as satisfied (see 3.5) and the throw is in the judoka's comfortable-set (tokui-waza or well-trained technique), commit.
3. If a throw signature is one or two tick-transitions from perceived satisfaction, select actions that close the gap (reposition grip, shift to driving mode, step to flank).
4. If the opponent's posture or motion suggests an emerging kuzushi window, select actions that exploit it.
5. If the kumi-kata clock is nearing shido threshold, escalate aggression (force an attempt even on weakly-perceived signatures).
6. If hand-part fatigue is high and composure is stable, drop to connective mode and recover.
7. Default: connective hold with small probing actions — small pulls, small pushes, small steps — that probe uke's reactions and keep a continuous flow of low-magnitude information about uke's defensive tendencies.

Higher fight_iq narrows the gap between "signature detected" and "action taken to close gap" and improves perception accuracy in step 2.

### 3.4 The tick update — 12 steps in order

Every tick, both judoka have chosen their actions. The update proceeds in strict order:

**Step 1 — Grip state updates.** REACH / DEEPEN / STRIP / STRIP_TWO_ON_ONE / RELEASE / REPOSITION_GRIP actions resolve first. The grip graph updates. After this step, which grips exist at what depth and which hands are in which contact state is known.

**Step 2 — Force accumulation.** For each judoka, sum all driving-mode forces being applied through their grips. Each grip contributes a force vector (direction × magnitude) up to its current envelope (Part 2.3–2.4). Feint forces contribute to this sum mechanically — the physical effect is real, only the commit-intent differs.

**Step 3 — Force application to opponent.** Tori's applied forces act on uke through the grips. By Newton's third law, equal and opposite forces act on tori through tori's own hands. A judoka who overcommits to a pull with no fulcrum pulls themselves toward their opponent — this is the physical basis for compromised posture after a failed throw (Part 6.3).

**Step 4 — Net torque and net translation on each CoM.** Sum the forces at each grip point to produce three quantities per judoka: (a) net translational force on the CoM, (b) net torque about the vertical axis (from forces applied off-center — produces twist), (c) net torque about the horizontal axis (from forces with a vertical component offset from the CoM — produces trunk lean).

**Step 5 — CoM velocity update.**
```
com_velocity_new = com_velocity_old + (net_force / mass) × dt
```
Damped by foot-floor friction. A judoka with both feet planted resists translation more than one mid-step.

**Step 6 — CoM position update.**
```
com_position_new = com_position_old + com_velocity_new × dt
```

**Step 7 — Trunk angle update.** Net horizontal torque changes `trunk_sagittal` and `trunk_frontal`. Damped by passive spinal restoration (trunk tends to return to vertical without applied force) and active postural control (composure-dependent).

**Step 8 — BoS update.** STEP or SWEEP_LEG actions update foot states. Feet can transition PLANTED → AIRBORNE → PLANTED within one tick or across multiple ticks depending on step magnitude.

**Step 9 — Kuzushi check.** For each judoka, compute `recoverable_envelope` from current velocity, leg_strength, fatigue, and composure (Part 1.5). Test whether `com_projection outside recoverable_envelope`. If true, that judoka is in kuzushi.

**Step 10 — Throw signature check (actual).** For each judoka, iterate through the throws they could commit given current state. For each throw, evaluate the four-dimension signature (Part 4) and produce a true signature-match percentage (0.0–1.0).

**Step 11 — Compound action resolution.** If either judoka issued COMMIT_THROW this tick, resolve it:
- If the *actual* signature match exceeds the throw's commit threshold, execute the throw's kake sequence (Parts 4–5).
- If not, the throw fails and the judoka enters a compromised state (Part 6.3) whose specifics depend on which signature dimension failed.

**Step 12 — Fatigue, composure, clock updates.** Driving-mode actions add hand-part and core fatigue proportional to force magnitude × ticks sustained. Connective-mode grips recover hand-part fatigue at a slow rate. Composure updates based on tick outcomes (kuzushi suffered → composure decreases; kuzushi induced on opponent → composure increases). Both passivity clocks (kumi-kata and unconventional-grip) increment or reset per Part 2.6.

Tick complete. Log events emit. Advance to t+1.

### 3.5 Perception — the gap between signature actual and signature perceived

The critical insight for skill variance: **a judoka's decision to commit is made against a *perceived* signature match, not the actual one.** Step 10 computes the actual match. Each judoka also computes a perceived match, which can differ.

```
perceived_match = actual_match + perception_error(fight_iq, fatigue, composure)
```

Where `perception_error` is a signed noise term. At high fight_iq, error is small and centered near zero — elite perception closely tracks reality. At low fight_iq, error is large and biased:

- **Novice-biased false positives:** a novice perceives 80% when actual is 40% and commits prematurely. They don't know when the throw is actually available.
- **Novice-biased false negatives:** a novice perceives 40% when actual is 80% and fails to commit on a real opening. They don't recognize the moment when it arrives.
- **Elite perception:** approaches 90%+ accuracy, with bias near zero.

This creates two emergent phenomena without explicit coding for them:

1. **Novices commit to doomed throws** — they perceive success where there is none. Failed throws produce compromised state (Part 6.3). The simulation naturally produces the "throw spam with no commitment" note from the playthrough observations as white-belt behavior, and the "elite only commits when real" feel as dan-rank behavior.

2. **Novices miss real openings** — uke exposes a kuzushi window, the novice perceives below threshold, no commit happens, the window closes. The same scenario with an elite produces the clean Ippon.

### 3.6 Feints — force without commitment

A feint is a driving-mode force application with no kake intent. Mechanically, the force is real: it reaches uke through the grip, it moves uke's CoM some amount, it may even induce minor posture shift.

The strategic value is that uke must *decide* whether it's a real attack. Uke's decision is the same perceived-vs-actual mechanism:

- If uke's perception says "this is a committed attack," uke spends force defending — absorbing, posture correcting, counter-gripping. This opens other lines for tori.
- If uke's perception accurately reads "this is a feint," uke does not over-commit to defense. The feint costs tori some force with no gain.

Feint effectiveness therefore emerges from the `perception_error(uke.fight_iq)` function. Against a low-IQ uke, a tori can cycle feints to drain uke's force and create real openings. Against a high-IQ uke, feints don't land — tori must commit to real attacks or be read.

### 3.7 What's not modeled in v0.1

- Aerial trajectories during a throw's fall (commit-to-landing arc) — handled narratively, not numerically.
- Mat friction variation by location.
- Grip force asymmetry beyond per-hand efficiency already tracked in the 24 body parts.
- Sweat or gi-moisture effects on grip strip resistance.
- Referee position and sightline effects on borderline score calls.
- Sub-second resolution for the micro-events inside a single tick.

All are real phenomena. None is worth v0.1 investment.

### 3.8 Random variation

To prevent identical setups from producing identical outcomes across matches, inject small stochastic noise:

- Force magnitudes: ±10% uniform.
- Trunk angle updates: ±5% uniform.
- Perception errors: Gaussian, with standard deviation inversely scaled by fight_iq.

Not enough to make the simulation chaotic. Enough to ensure that two matches between Tanaka and Sato don't produce identical tick sequences — the variety concern from the playthrough observations is addressed by the physics model + stochastic noise together, not by noise alone.

---

## PART 4 — THE TWO THROW TEMPLATES

### 4.1 The Couple / Lever distinction

Every throw in v0.1 is an instance of one of two templates, grounded in Sacripanti's biomechanical classification. The distinction is not cosmetic — it determines commit rules, failure modes, counter geometries, and energy costs.

- **Couple throw.** Applies a pure torque to uke's CoM via two opposing forces. Can fire on uke's existing motion (hando-no-kuzushi — reactive off-balancing). Does not require kuzushi to be pre-established. Characteristic examples: O-soto-gari (major outer reap), Uchi-mata (inner thigh throw), O-uchi-gari (major inner reap), Ko-uchi-gari (minor inner reap), competitive Harai-goshi (sweeping hip throw), and all ashi-waza foot sweeps.

- **Lever throw.** Establishes a fulcrum on tori's body and rotates uke over it. Requires uke's CoM to be positioned past the fulcrum — kuzushi must be already achieved before the throw can fire. Characteristic examples: O-goshi (major hip throw), Seoi-nage (shoulder throw), Tai-otoshi (body drop), O-guruma (major wheel), Tomoe-nage (circle/sacrifice throw), classical Harai-goshi.

For v0.1, each throw picks exactly one classification. Genuinely hybrid throws — for instance, Harai-goshi as executed competitively (Couple) versus classically (Lever) — are represented as two separate entries in the throw table, each inheriting the relevant template parameters. This keeps the model clean at the cost of slight terminology redundancy.

### 4.2 The four-dimension signature, formalized

Both templates share a common signature-match computation. The actual match score for a throw against the current state is:

```
actual_match = (
    w_kuzushi  × match_kuzushi_vector(state, throw) +
    w_force    × match_force_application(state, throw) +
    w_body     × match_body_parts(state, throw) +
    w_posture  × match_uke_posture(state, throw)
)
```

Each dimension returns a score in [0.0, 1.0]. Weights sum to 1.0 and vary by classification:

- **Couple throws** — kuzushi vector weighted lower (Couple can fire on imperfect balance state), force application and body-part engagement weighted higher (the two forces and the reaping/sweeping limb *are* the throw). Example weights: 0.2 / 0.35 / 0.35 / 0.1.

- **Lever throws** — kuzushi vector weighted higher (Lever requires established kuzushi before firing), body-part engagement weighted equally high (fulcrum must be loaded and positioned), force and posture medium. Example weights: 0.35 / 0.2 / 0.35 / 0.1.

Exact weight values are Phase 3 calibration work. The spec commits only to the relative ordering and the classification-dependent weighting pattern.

### 4.2.1 Execution quality within signature

Signature match above the commit threshold is not uniform. The same throw fired at marginal-match and elite-match produces materially different outcomes — different force transfer, different landing severity, different counter vulnerability, different scores awarded. This sub-section makes execution quality a first-class concept in the signature model.

**The execution quality score.**

For any throw whose `actual_match` exceeds `commit_threshold` and therefore fires, the engine derives an `execution_quality` score in [0.0, 1.0]:

```
execution_quality = clamp(
    (actual_match - commit_threshold) / (1.0 - commit_threshold),
    0.0, 1.0
)
```

A throw that fires at exactly the commit threshold has `execution_quality = 0.0`. A throw that fires at full signature match (1.0) has `execution_quality = 1.0`. Most live throws will fall somewhere in between, with the distribution skewing higher as belt rank rises.

**What execution quality flows through.**

Execution quality is consumed by four downstream systems. The specific multiplier curves and threshold values within each system are calibration work, not committed by this spec — but the *coupling* is committed.

1. **Force transfer.** The kake sequence delivers force to uke's CoM and trunk in proportion to execution quality. A heel-to-calf O-soto-gari at `execution_quality = 0.2` transfers far less rotational momentum than the same throw at `execution_quality = 0.8` — uke ends up displaced but not airborne, or airborne but not landing flat.

2. **Landing severity.** Score award decisions consume execution quality alongside the existing landing-position checks. A clean Ippon requires high execution quality combined with a back-flat landing. A waza-ari-eligible landing with low execution quality may award yuko-equivalent or no score at all, depending on Ring 1 scoring rules.

3. **Counter vulnerability.** A throw that fires at low execution quality leaves tori in a more compromised post-throw position — the kake didn't complete the rotation, the connective grips remained engaged, tori is closer to uke and slower to recover. Counter-window perception (Part 3.5) is computed against tori's post-throw vulnerability, which scales inversely with execution quality.

4. **Prose register.** The narration layer reads execution quality directly. A throw at 1.0 narrates as a clean technical action. A throw at 0.3 narrates as an "almost-threw" — uke staggers but recovers, or lands but rolls out, or absorbs the force without scoring. This is the texture that distinguishes white-belt sloppy success from elite-level clean execution in the log.

**Why this is in the spec, not deferred.**

A simulation that only models clean throws and clean failures cannot represent the central pedagogical fact of judo: that a sloppy throw can still work. White, yellow, and green belts succeed with technically incorrect execution all the time — the throw lands, the score is awarded, the simulation must be able to narrate it. Without execution quality as a first-class concept, the simulation collapses into a binary that the source material does not have.

This also resolves a class of failure-mode tickets that would otherwise need bespoke compromised states. Hip-engagement on a non-hip throw (HAJ-59), heel-to-calf O-soto-gari (HAJ-55), Tai-otoshi with hips loaded in front — these are not signature failures. They are signature-valid throws executed at low quality. Hard gates and new compromised states would over-correct by removing them from the throw space entirely. Within-signature quality is the truer model: the throws fire, but they fire badly.

**Implementation note.**

The mechanism is committed by this sub-section. The specific calibration — what curve maps execution quality to force transfer, what threshold separates ippon from waza-ari, how counter vulnerability scales — is the work of subsequent tickets. The first such tickets are HAJ-55 and HAJ-59 in revised form: they no longer add hard gates or new compromised states. They become specifications of how their respective execution patterns reduce execution quality and what the resulting outcomes look like.

### 4.3 The Couple throw template

```
CoupleThrow:
  name: str
  classification: "couple"
  
  # Four-dimension signature
  kuzushi_vector_requirement:
    direction: Vector2              # in uke's body frame
    tolerance: float                # angular tolerance (radians)
    min_velocity_magnitude: float   # uke's CoM must be moving at this speed along direction
    
  force_application_requirement:
    required_grips: List[GripRequirement]  # grip type, minimum depth, required mode
    couple_axis: Vector3                   # rotation axis (vertical, sagittal, transverse)
    min_torque: float                      # minimum torque to commit
    
  body_part_requirement:
    tori_supporting_foot: str                       # "left" or "right"
    tori_attacking_limb: str                        # delivers the reap/sweep
    contact_point_on_uke: BodyPart                  # where the attacking limb contacts
    contact_height_range: Tuple[float, float]       # vertical range of contact
    
  uke_posture_requirement:
    trunk_sagittal_range: Tuple[float, float]
    trunk_frontal_range: Tuple[float, float]
    com_height_range: Tuple[float, float]
    base_state: BaseState                           # e.g., WEIGHT_ON_REAPED_LEG
  
  # Commit threshold (range 0.4–0.6 for Couple — fires on imperfect conditions)
  commit_threshold: float
  
  # Failure / counter geometry
  sukashi_vulnerability: float                      # how badly a void counter punishes
  failure_outcome: FailureOutcome                   # see Section 4.5
```

**Commit rule for Couple throws.** Signature match computed at Step 10 of the tick update. Tori commits based on *perceived* match exceeding `commit_threshold` (perception per Part 3.5). If commit is taken and actual match also exceeds threshold → kake executes. If actual is below threshold → the couple's torque does not dissipate; it reverses. Sukashi outcome: uke's absent inertia causes tori to rotate themselves. Tori enters a compromised-posture state (Part 6.3).

Commit thresholds for Couple are deliberately lower than Lever because the throw works *with* uke's motion rather than against it. A partial signature match — uke moving in roughly the right direction with decent force coupled — is enough for a skilled judoka to commit.

### 4.4 The Lever throw template

```
LeverThrow:
  name: str
  classification: "lever"
  
  # Four-dimension signature
  kuzushi_vector_requirement:
    direction: Vector2
    tolerance: float
    min_displacement_past_recoverable: float  # uke's CoM must be this far outside recoverable region
    
  force_application_requirement:
    required_grips: List[GripRequirement]
    required_forces: List[ForceRequirement]         # specific pulls, pushes, lifts
    min_lift_force: float                           # vertical lift sustained through kake
    
  body_part_requirement:
    fulcrum_body_part: BodyPart                     # which of tori's 24 parts is the pivot
    fulcrum_contact_on_uke: BodyPart                # where the fulcrum contacts uke
    fulcrum_position_relative_to_uke_com: Vector3   # fulcrum below and behind uke's CoM
    tori_supporting_feet: SupportRequirement        # single or double support
    
  uke_posture_requirement:
    trunk_sagittal_range: Tuple[float, float]
    trunk_frontal_range: Tuple[float, float]
    com_height_range: Tuple[float, float]
    uke_com_over_fulcrum: bool                      # critical geometric predicate
  
  # Commit threshold (range 0.6–0.8 for Lever — higher than Couple)
  commit_threshold: float
  
  # Failure / counter geometry
  counter_vulnerability: float                      # how badly a redirection counter punishes
  failure_outcome: FailureOutcome
```

**Commit rule for Lever throws.** Signature check at Step 10. Tori commits on perceived match exceeding `commit_threshold`. Execution requires three conditions to all hold during the kake tick(s): actual match exceeds threshold, `uke_com_over_fulcrum` is true, `min_lift_force` can be sustained. If any condition fails mid-kake, the throw stalls — tori holds uke partially lifted without completing rotation. Tori then either re-commits (costs another tick of driving force, extending exposure to counter) or releases and eats compromised state.

Lever throw thresholds are higher because Lever throws cannot exploit imperfect conditions — you cannot lift a partially-resisting opponent over your hip. Real kuzushi is mandatory. The higher threshold reflects that mechanical demand.

### 4.5 Failure outcomes — open-ended, not binary

A failed throw is not a binary fail-reset event. The `failure_outcome` field expands into multiple possibilities, and which outcome occurs depends on the state of both judoka at the moment of failure. This replaces the current "throw failed; reset" logic from Phase 2 Session 2.

Possible failure outcomes:

- **Compromised state.** Tori ends in a physically vulnerable configuration (spine flexed, single-support on tired leg, both grips engaged, CoM outside own base). Immediately exploitable by uke. Specifics live in Part 6.3.

- **Partial throw (waza-ari-level landing).** Tori's commit did partial mechanical work. Uke was knocked off-balance but not cleanly thrown. Uke may take a yuko-level landing (knee, hip, buttocks touch-down without full back-landing). Scoring determined by referee judgment on the actual landing geometry.

- **Stance reset.** Both judoka end standing, separated by a step, neither in kuzushi. Grips may or may not survive. The attack is spent, the kumi-kata clock continues, nothing scored. Common outcome for underpowered foot sweeps and weak reaps.

- **Uke voluntarily hits ne-waza.** Uke chooses to drop to the mat and turtle (belly-down protective posture) rather than continue standing exchange. This is a real-judo defense against repeated attacks — a fatigued uke may decide the ne-waza defense is cheaper than another standing defense. Uke pays the cost of ceding the standing position but gains defensive stability. Tori then chooses whether to engage osaekomi (pin) / kansetsu (joint lock) / shime (choke) attempts against a turtled uke, or let the referee call Matte and reset standing.

- **Clean counter.** Uke actively exploits the failed throw with a counter technique. For Couple-class failures this is typically sukashi — uke's body-positional response converts tori's own torque against tori. For Lever-class failures this is typically kaeshi-waza — uke rides tori's committed momentum into a redirection throw (O-goshi-gaeshi, ura-nage). Counter success depends on uke's fight_iq, composure, cardio, and the specific compromised state tori entered.

The choice of which failure outcome occurs is not deterministic. It depends on:

- Which signature dimension failed (kuzushi? force? body parts? posture?)
- How badly it failed (small miss vs. large miss)
- Uke's current resources (fatigue, composure — a tired uke may turtle rather than counter)
- Uke's fight_iq (perception of the opportunity)
- Uke's tokui-waza and counter-specialty tendencies

This open-endedness is deliberate. It means failed throws produce varied outcomes across matches — directly addressing the "same text every match" complaint from the playthrough observations.

### 4.6 The foot-sweep timing-window variant

Ashi-waza foot sweeps (De-ashi-harai, Okuri-ashi-harai, Ko-soto-gari, Sasae-tsurikomi-ashi, Harai-tsurikomi-ashi) are Couple-class throws with a distinctive twist: their valid commit window is a **centered timing window**, not a monotonic above-threshold condition.

The Kodokan's own technical definition of De-ashi-harai specifies: *"the sweep must be executed at the moment uke's foot leaves the floor."* For Okuri-ashi-harai: *"at the precise moment when uke is raised onto his toes, just before the lateral motion begins."* The biomechanical research (Levitsldy & Matveyev 2016; Elipkhanov 2011) confirms the technique *"lives or dies by timing — sweep early, uke steps out; sweep late, uke is stable."*

Translated to simulation:

- A foot sweep's signature satisfaction depends on the targeted foot's `weight_fraction` being in a narrow transition window — typically `weight_fraction` between 0.1 and 0.3, meaning the foot is unweighting (lifting) but has not yet fully lifted.
- Before the window: the foot is still planted enough to resist the sweep. The sweep bounces off. Tori's sweeping leg momentum is wasted, possible compromised state.
- After the window: the foot has re-planted or uke has completed the lateral motion and stabilized. The sweep meets a weighted foot that won't move.
- Inside the window: the sweep hits a foot that is nearly airborne. Minimal force displaces it. Uke loses the support entirely and falls.

This is modeled in the Couple throw template by extending the `body_part_requirement` block with a `timing_window` field for ashi-waza variants:

```
body_part_requirement:
  ...
  timing_window: Optional[Dict]
    target_foot: str                    # "left" or "right"
    weight_fraction_range: (0.1, 0.3)   # valid capture range
    window_duration_ticks: int          # typically 1–2 ticks
```

A foot sweep's signature match plummets outside the timing window regardless of other dimensions — grip, force, posture can all be perfect, but if uke's target foot is solidly planted or fully airborne, the throw cannot fire cleanly.

This has an important narrative consequence: **foot sweeps are disproportionately rewarded when they land.** The Kodokan explicitly notes that De-ashi-harai is "often awarded Ippon-gachi due to the Judo sense it requires" — the technique is spectacular because the timing is hard. A white-belt tori with poor perception (Part 3.5) will miss the timing window more often than not; an elite will read uke's weight transfer and strike at the right tick. This naturally reproduces the real-judo pattern where foot sweeps are high-reward high-skill techniques that upset stronger opponents on the rare occasions they land.

### 4.7 Log emission when a throw commits

When a throw's signature matches and commit fires, the log emits prose describing the physical events that produced the match — not the scalar values underneath. Contrast the current Phase 2 Session 2 output:

```
t014: [grip] Kuzushi window — Tanaka dominant (delta +0.47). Window: 2 tick(s).
t014: [throw] Tanaka commits — Seoi-nage.
t014: [ref: Suzuki-sensei] Ippon!
t014: [score] Tanaka → Seoi-nage → IPPON (net +7.24, quality 1.00)
```

With the substrate-driven equivalent:

```
t014: Tanaka pulls Sato's sleeve forward-down. Right hand drives lapel forward.
t014: Sato's CoM passes the recoverable edge — forward corner.
t014: Tanaka's shoulder loads. Sato lifted over.
t014: Ippon — Seoi-nage.
```

The log renders physical facts because the physical facts are what the simulation actually computed. The scalars still exist in the engine; the prose layer (Phase 3+ work) reads from the same signature match values and translates each dimension's contribution into a sentence. This is the legibility fix the Bucket 4 playthrough observations called for.

### 4.8 Handoff to Part 5

Part 5 fills in the concrete four-dimension signature for six to ten specific throws. Each throw becomes a parameterized instance of the appropriate template. Adding a new throw post-v0.1 is then a parameters-only operation — no new physics code.

---

## PART 5 — WORKED THROWS

This part instantiates four throws as parameterized templates. Each throw is specified in two forms: a prose description of what the throw *is* in physical terms, followed by a pseudocode parameter block for Session 4 to implement against. Additional throws (O-goshi, Tai-otoshi, Ko-uchi-gari, O-uchi-gari, Harai-goshi, Tomoe-nage, O-guruma) are Session 4 backfill using the same two-form structure; v0.1 commits to the four below as the template-exercising set.

The four chosen for v0.1:
- **Uchi-mata** — canonical forward-rotation Couple throw
- **O-soto-gari** — canonical backward-rotation Couple throw
- **Seoi-nage (morote)** — canonical Lever throw
- **De-ashi-harai** — timing-window ashi-waza Couple variant

Together these exercise every mechanic defined in Parts 1–4.

---

### 5.1 Uchi-mata (内股, inner thigh throw)

**What it is, physically.** A forward-rotation Couple throw. Tori establishes a dyad where tori's upper body and uke's upper body are linked by the hikite-tsurite grip pair, then produces a force couple through the arms (tsurite lifts and steers upward-forward while hikite rotates downward-inward) while the right leg sweeps uke's inner thigh upward-backward. The two forces — arm-couple in the upper register, reaping-leg in the lower — produce a net torque that rotates uke forward around uke's own center of mass, not around a fulcrum on tori. Tori stands on the left (support) leg through the execution; the right leg is the reaping tool, not a post.

Hamaguchi et al. (2025) measured the kinetic chain: lower-limb drive initiates the rotation, upper-limb rotation follows. Head-forward-tilt angle at peak sweeping-leg height predicts sweep-leg velocity (adj R² = 0.53). The throw fails cleanly if uke drops into jigotai — the reaping leg meets outside thigh instead of inner, and without the inner-thigh catch the couple has nothing to rotate against. This failure mode is the classic uchi-mata-sukashi (void counter), in which uke pivots the knees together and tori's committed leg swing meets empty space, rotating tori instead.

Kuzushi direction: mae (front) or migi-mae-sumi (right-front corner). Tori draws uke onto the toes using tsurite lift. The Kodokan canonical setup is a circular drawing motion; competitive variants are more linear forward pulls.

```
Throw: Uchi-mata (morote grip, right-sided canonical)
Classification: couple

kuzushi_vector_requirement:
  direction: (+1.0, +0.3)        # forward and slightly right in uke's body frame
  tolerance: 30°
  min_velocity_magnitude: 0.4 m/s  # uke's CoM must be moving onto the toes

force_application_requirement:
  required_grips:
    - type: SLEEVE (left hand, hikite), min_depth: STANDARD, mode: DRIVING
    - type: LAPEL_HIGH or COLLAR (right hand, tsurite), min_depth: STANDARD, mode: DRIVING
  couple_axis: SAGITTAL         # rotation about uke's sagittal axis (forward pitch)
  min_torque: moderate-to-high   # calibration target

body_part_requirement:
  tori_supporting_foot: "left"
  tori_attacking_limb: "right_leg"
  contact_point_on_uke: "left_inner_thigh"   # canonical Daigo; variants: near leg
  contact_height_range: (upper_thigh, hip_crease)

  hip_engagement_penalty:                    # HAJ-59 — top-leg variant quality
    clean_trunk_sagittal: +15°               # tori near-vertical — clean execution
    engaged_trunk_sagittal: +35°             # tori bent forward — hip-loaded variant
    engaged_floor: 0.5                       # body-dim × 0.5 when fully hip-loaded

uke_posture_requirement:
  trunk_sagittal_range: (-5°, +20°)   # upright or slightly forward — NOT jigotai
  trunk_frontal_range: (-15°, +25°)
  com_height_range: HIGH              # weight rising onto toes
  base_state: WEIGHT_SHIFTING_FORWARD

commit_threshold: 0.55

sukashi_vulnerability: 0.75           # HIGH — uchi-mata-sukashi is a recognized counter
failure_outcome:
  primary: TORI_COMPROMISED_SINGLE_SUPPORT
  secondary (if uke high IQ, high cardio): UCHI_MATA_SUKASHI — uke pivots knees together
  tertiary (if uke fatigued): STANCE_RESET
```

**Hip-engagement quality (HAJ-59).** Sensei rejects the top-leg Uchi-mata variant where tori loads the hip as if driving a hip throw. The throw still fires — a novice sometimes still gets uke through — but the lift becomes a bump. The body-parts dimension is multiplied by an `engaged_floor` multiplier when tori's trunk sagittal at kake exceeds the clean threshold. Signature match drops, `execution_quality` drops, force transfer at kake is weak, landing severity reads as partial, and the post-throw counter window is wider. No separate compromised state is created; the phenomenon is quality variation within one signature.

---

### 5.2 O-soto-gari (大外刈, major outer reap)

**What it is, physically.** A backward-rotation Couple throw. Tori plants the left (pivot) foot alongside uke's right foot, tilts the trunk forward sharply while pushing uke's chest backward via the tsurite, and sweeps the right leg backward-upward against the back of uke's right thigh or calf. The chest push and the leg reap constitute the force couple: their lines of action are parallel but opposite, offset vertically by roughly uke's torso length, producing pure torque about uke's transverse axis. Uke rotates backward around uke's own CoM.

Imamura & Johnson (2003) identified the two variables that distinguish black belts from novices: peak trunk angular velocity and peak ankle plantar-flexion angular velocity of the sweeping leg. Liu et al. (2022) showed the pivot leg's knee-extension moment drives the whole-body rotation that accelerates the sweeping leg — floor → pivot knee → trunk → sweep leg, a clear kinetic chain. Daigo (2016) specifies uke's weight must be on the heel of the leg to be reaped; friction on a flat-footed stance defeats the reap in a single stroke. Imamura's CoM data show black belts pull uke forward first, loading the lead leg, then reverse direction for the reap — a hando-no-kuzushi pattern, pre-loading the opposite direction before the commit.

Kuzushi direction: ushiro-migi (right-back corner). But note the pre-loading: skilled execution first loads uke forward, then reaps backward when uke's defensive response weights the heel.

**Execution quality within the signature (HAJ-55 / Part 4.2.1).** Daigo (2016) names two Japanese variants — calf-contact and thigh-contact — and reports a ~52% / 48% split in competition footage. Earlier drafts of this spec treated them as separate throw entries. They are not. They are the same throw executed at different *quality* levels of the same signature. Thigh-to-thigh contact with torso closure is the coach-canonical execution; heel-to-calf at arm's length is the common novice error. Both fire — the signature match still crosses the commit threshold across the whole range — but the execution_quality score (Part 4.2.1) varies continuously between them, and downstream systems read the difference.

Two new sub-dimensions feed the body-part match and therefore execution_quality:

- `reaping_leg_contact_point` — where on uke's leg the reaping leg lands. High quality at thigh-to-thigh (leg enters between uke's legs and sweeps up the back of the thigh); low quality at heel-to-calf (leg kicks from distance and catches the lower shin or heel). Continuous.
- `torso_closure` — horizontal distance between tori's chest and uke's chest at kake. High quality at chest-to-chest; low quality at arm's length. Continuous.

The two are correlated — close torso closure tends to produce high contact — but they are separable because tori can be close with the reaping leg still misaligned, or far with a long leg that catches the thigh. The engine derives both from horizontal CoM-to-CoM distance and the template's `contact_quality_profile` (Part 5.2 calibration fields below).

A throw in the heel-to-calf-plus-arm's-length corner fires with a low eq, lands weaker (Part 4.2.1 point 1), scores lower (point 2), and leaves tori more exposed to osoto-gaeshi (point 3). A throw in the thigh-to-thigh-plus-chest-to-chest corner fires with high eq, hits harder, scores cleaner, and tori's recovery window is tight.

```
Throw: O-soto-gari (right-sided canonical)
Classification: couple

kuzushi_vector_requirement:
  direction: (-1.0, +0.5)       # backward and rightward in uke's body frame
  tolerance: 25°
  min_velocity_magnitude: 0.3 m/s   # uke is reacting to a pull or stepping onto heel

force_application_requirement:
  required_grips:
    - type: SLEEVE (left hand, hikite), min_depth: STANDARD, mode: DRIVING
    - type: LAPEL_LOW or LAPEL_HIGH (right hand, tsurite), min_depth: STANDARD, mode: DRIVING
  couple_axis: TRANSVERSE       # rotation about uke's transverse axis (backward pitch)
  min_torque: high               # requires strong pivot-knee extension

body_part_requirement:
  tori_supporting_foot: "left"   # planted alongside uke's right foot
  tori_attacking_limb: "right_leg"
  contact_point_on_uke: "right_thigh"   # ideal; calf/heel contact reduces execution_quality
  contact_height_range: (knee, mid_thigh)
  required_contact_state: uke_right_foot.weight_fraction > 0.6 AND weight_on_heel

  contact_quality_profile:      # HAJ-55 — feeds execution_quality, not commit gate
    ideal_torso_closure_m:       0.45   # chest-to-chest — reaping contact quality = 1.0
    max_torso_closure_m:         1.10   # arm's-length — closure quality = 0.0
    ideal_reaping_contact_m:     0.50   # contact point at thigh
    max_reaping_contact_m:       1.20   # contact point at heel/calf (quality = 0.0)

  hip_engagement_penalty:       # HAJ-59 — hip loading dilutes the transverse couple
    clean_trunk_sagittal: +15°
    engaged_trunk_sagittal: +35°
    engaged_floor: 0.5                  # ~0.3 eq reduction at full engagement

uke_posture_requirement:
  trunk_sagittal_range: (-10°, +5°)   # upright or slightly back-leaning — NOT forward
  trunk_frontal_range: (-15°, +20°)
  com_height_range: MEDIUM_HIGH       # not jigotai
  base_state: WEIGHT_ON_REAPED_LEG_HEEL

commit_threshold: 0.50          # fires across the whole contact-quality range

sukashi_vulnerability: 0.35           # low — osoto-sukashi exists but is rare
counter_vulnerability: 0.65           # osoto-gaeshi (redirection counter) is common

failure_outcome:
  primary: TORI_COMPROMISED_FORWARD_LEAN  # tori's trunk was already tilted; now vulnerable
  secondary (if uke strong, upright): OSOTO_GAESHI — uke rides the momentum for counter
  tertiary (if uke quick-read, low composure): STANCE_RESET with ko-uchi-gari follow-up window
```

**Calibration targets (Phase 3, not committed by this sub-section).** Thigh-to-thigh + chest-to-chest O-soto-gari should land around `execution_quality ≈ 0.85`; heel-to-calf + arm's-length around `≈ 0.25`. Mixed corners interpolate. The specific curve — linear falloff, sigmoid, or a floor — is calibration work; the spec commits only that both dimensions feed execution_quality continuously and that contact-point is *never* a hard gate.

Note on head-impact safety: Murayama et al. (2020) measured peak impulsive force on uke's head at 204.82 ± 19.95 kg·m·s⁻¹ for O-soto-gari — the highest of common throws. For simulation this means a landed O-soto-gari should have higher probability of Ippon scoring (uke's upper back hits cleanly) but also higher probability of referee intervention in edge cases where uke's ukemi (breakfall) fails. The eq-gated landing severity layer (Part 4.2.1 point 2) mediates between these: only high-eq throws reach the ippon-eligible ceiling.

---

### 5.3 Seoi-nage (背負投, shoulder throw — morote form)

**What it is, physically.** A Lever throw. Tori establishes a fulcrum at the back/shoulder line by turning the back fully to uke and lowering the hips below uke's hips. Both arms transmit force: the hikite pulls uke's sleeve forward-down across tori's body, the tsurite drives uke's lapel forward (and, per Ishii 2019, lifts via internal shoulder rotation along the throwing axis). Uke's CoM must be positioned over tori's back-and-shoulder line and driven past the fulcrum's potential-barrier maximum by the lift. Once past, gravity completes the rotation.

Blais, Trilles & Lacouture (2007) measured joint contributions: knee 24%, hip 29%, trunk 28%, upper limbs only 19% of total driving moment. The lower body does most of the work — the shoulder is just the fulcrum. Ishii et al. (2018) found elite CoM forward velocity in the turning phase at 2.74 ± 0.33 m/s vs. 1.62 ± 0.47 m/s in college athletes. Gutiérrez-Santiago et al. (2013) identified the #1 technical failure: insufficient knee bend leaves the hips above uke's hips and uke slides off the side rather than rotating over the shoulder.

Kuzushi direction: mae (front) or migi-mae-sumi. The optimal lapel pull is ~10° above horizontal (Sannohe 1986). Commit threshold is higher than Couple because Seoi-nage cannot exploit imperfect kuzushi — you cannot lift a partially-resisting uke over your shoulder.

```
Throw: Seoi-nage (morote, right-sided canonical)
Classification: lever

kuzushi_vector_requirement:
  direction: (+1.0, +0.2)        # forward, very slight right-corner bias
  tolerance: 20°
  min_displacement_past_recoverable: moderate   # kuzushi must be real, not incipient

force_application_requirement:
  required_grips:
    - type: SLEEVE (left hand, hikite), min_depth: STANDARD, mode: DRIVING
    - type: LAPEL_LOW to LAPEL_HIGH (right hand, tsurite), min_depth: STANDARD, mode: DRIVING
  required_forces:
    - hikite: PULL forward-down across tori's body, angle ≈ 30° below horizontal
    - tsurite: LIFT + PUSH forward, with internal shoulder rotation
  min_lift_force: HIGH           # tori must sustain lift through full kake duration

body_part_requirement:
  fulcrum_body_part: "upper_back_and_right_shoulder"
  fulcrum_contact_on_uke: "chest_and_right_armpit"
  fulcrum_position_relative_to_uke_com: BELOW uke's CoM by ≥ 0.15 m
    # Critical constraint: tori's hips MUST be below uke's hips
  tori_supporting_feet: DOUBLE_SUPPORT with deep knee flexion

uke_posture_requirement:
  trunk_sagittal_range: (0°, +30°)    # upright or forward-leaning
  trunk_frontal_range: (-15°, +15°)
  com_height_range: MEDIUM_HIGH       # NOT jigotai-low (cannot be loaded) NOT back-leaning (cannot be lifted)
  uke_com_over_fulcrum: REQUIRED

commit_threshold: 0.70

counter_vulnerability: 0.55           # ura-nage, sode-tsurikomi-gaeshi possible
failure_outcome:
  primary (hips above uke's hips): TORI_STUCK_WITH_UKE_ON_BACK — extreme vulnerability
  secondary (lift fails mid-kake): TORI_BENT_FORWARD_LOADED — go-no-sen counter window
  tertiary (uke jigotai): STANCE_RESET with tori's momentum lost
```

#### 5.3.1 Seoi-nage variants

Seoi-nage is a technique family, not a single throw. Four variants matter for v0.1: Morote standing (specified above), Ippon standing, Morote drop, and Ippon drop. Each is a separate entry in the throw table with shared structure. Drop variants further split into one-knee and two-knee forms. The risk/reward progression is systematic: **faster entry, lower commit threshold, higher failure penalty.**

**Morote standing** — the canonical specification above. Highest commit threshold (0.70), lowest failure penalty (compromised state but tori still on two feet).

**Ippon standing.** Tori's right arm slides under uke's right armpit, clamps uke's arm to tori's chest/shoulder as the lever. No tsurite lapel grip — the armpit clamp replaces it. Entry is faster because one arm moves less than two. Imamura (2006) notes kuzushi tends toward pure forward rather than the corner favored by morote.

Parameter deltas from Morote standing:
- `required_grips`: SLEEVE only (hikite). Right arm moves to `CONTACTING_UKE_NONGRIP` at uke's armpit.
- `fulcrum_body_part`: "right_shoulder_with_clamped_right_arm"
- `kuzushi_vector_requirement.direction`: (+1.0, +0.0) — pure forward, not corner.
- `commit_threshold`: 0.65 (slightly lower — one-arm entry is faster to achieve).
- **Added vulnerability:** the single hikite grip is a single point of failure. If stripped mid-entry, throw aborts immediately. `strip_vulnerability` is high.

**Morote drop, one knee.** Tori's right knee drops to the mat as the back turns in. The turn-in completes faster than standing entry because the body rotates around a lower pivot. The fulcrum (shoulder) ends at a lower height. This works better against uke with a lower CoM (taller opponents leaning forward, or jigotai defenders) because the reduced height differential matches.

Parameter deltas from Morote standing:
- `tori_supporting_feet`: `ONE_KNEE_DOWN_ONE_LEG_BENT` — not standard DOUBLE_SUPPORT.
- `fulcrum_position_relative_to_uke_com`: BELOW uke's CoM by ≥ 0.30 m (deeper offset than standing).
- `commit_threshold`: 0.60 (lower than standing morote).
- `entry_ticks` (skill-compression parameter): reduced by 1 tick at every belt rank vs. standing.
- **Failure penalty escalated:** if the throw fails, tori is on one knee with uke still standing. Primary failure outcome becomes `TORI_ON_KNEE_UKE_STANDING`, which is significantly more exploitable than `TORI_STUCK_WITH_UKE_ON_BACK`. Uke can pull down for direct osaekomi (pin) transition, step over for ura-nage, or disengage for an unchallenged standing position.

**Morote drop, two knees.** Both knees drop to the mat. Fastest entry of all Seoi-nage variants. Fulcrum at its lowest. Works against the tallest opponents because the biggest height differential produces the biggest rotational arc.

Parameter deltas from Morote drop one-knee:
- `tori_supporting_feet`: `BOTH_KNEES_DOWN` — fully kneeling.
- `fulcrum_position_relative_to_uke_com`: BELOW by ≥ 0.45 m.
- `commit_threshold`: 0.55 (lowest of the Seoi-nage family).
- `entry_ticks`: minimum at every belt rank.
- **Failure penalty maximal:** if the throw fails, tori is on both knees with uke fully standing. Primary failure outcome becomes `TORI_ON_BOTH_KNEES_UKE_STANDING`. Tori cannot recover to standing in one tick. Uke has an unchallenged kuzushi window on a kneeling tori, can transition directly to kesa-gatame (pin), can execute ura-nage, or can simply disengage and let the kumi-kata clock and passivity rules punish tori's compromised position. This is the "hail mary" variant — maximum speed, maximum commitment, maximum cost of missing.

**Ippon drop variants** (one-knee and two-knee) combine the single-arm force application of Ippon standing with the drop entry geometry. Parameter construction is compositional: take the Ippon standing deltas from Morote standing, then apply the drop deltas from Morote drop one-knee or two-knee.

#### 5.3.2 The variant selection logic

At Step 10 of the tick update (throw signature check), a judoka evaluates all variants of Seoi-nage (and every other multi-variant throw). Each variant has its own signature match score. The judoka commits to the variant with the highest *perceived* match that exceeds its commit threshold. Higher-risk variants (two-knee drop) will often show a higher signature match simply because their commit thresholds are lower — but a judoka with good fight_iq and high composure will prefer the safer standing variant when both are available, trading speed for recoverability.

This gives the simulation a rich behavioral texture without explicit coding. A desperate judoka whose kumi-kata clock is expiring will accept a two-knee drop that an unhurried judoka in the same physical state would never commit to. A fatigued judoka with low composure will reach for the fastest-entry variant even when slower-entry variants are cleaner. A confident judoka with a standing-Morote tokui-waza will hold out for the standing signature to match fully rather than take a drop.

---

### 5.4 De-ashi-harai (出足払, forward foot sweep)

**What it is, physically.** A Couple throw with the distinguishing timing-window mechanic. Tori waits for the moment uke's forward-stepping foot is transitioning from planted to airborne — the fraction of a second when weight is lifting off but the foot has not yet lifted clear of the mat. In that window, tori sweeps the unweighting foot laterally with the sole or arch of the sweeping foot, using minimal force. Uke's support is removed at the instant it was already in transition; the rest of uke's body, which was mid-step, continues its momentum into a fall.

The Kodokan's technical documentation is unusually precise here: *"the sweep must be executed at the moment uke's foot leaves the floor."* The biomechanics research (Levitsldy & Matveyev 2016; Elipkhanov 2011) confirms the technique fails both ways — too early bounces off a planted foot, too late meets a stabilized one. Per Section 4.6, the commit window is a centered `weight_fraction` range, not a monotonic threshold.

The throw is taught as "subtlety over strength" (judo.science summarizing Levitsldy 2016) — elite performers keep the torso upright (low-pitch variant), minimizing CoM commitment, letting the timing do the work. Muscle engagement studies show the long adductor (inner thigh) as the primary trigger, with core and upper back coordinating the sweep with hand control.

For the simulation this is where judo sense earns its name. Generic fight_iq gives a judoka a baseline perception of uke's foot-weight transitions. A De-ashi-harai specialist — the judoka whose tokui-waza is foot sweeps — has per-technique perception accuracy that exceeds their generic fight_iq for this specific window. Two judoka of equal belt rank, one a sweep specialist and one not, will catch the window at wildly different rates. This is exactly the "judo sense" asymmetry the Kodokan describes, modeled as per-technique perception rather than generic skill.

Kuzushi direction: the direction uke was already moving. If uke steps forward with the right foot, kuzushi is forward-right. If uke circles laterally, kuzushi is lateral. The sweep catches existing motion rather than creating it.

```
Throw: De-ashi-harai (forward foot sweep, right-sided canonical)
Classification: couple (with timing_window variant)

kuzushi_vector_requirement:
  direction: ALIGNED_WITH_UKE_EXISTING_VELOCITY   # throw redirects, does not create
  tolerance: 45°                                   # wide — the motion is uke's, not tori's
  min_velocity_magnitude: 0.3 m/s                  # uke must actually be stepping

force_application_requirement:
  required_grips:
    - type: SLEEVE (left hand, hikite), min_depth: STANDARD, mode: DRIVING
      # hikite provides downward pull to destabilize uke's upper body during sweep
    - type: LAPEL_LOW (right hand, tsurite), min_depth: POCKET, mode: DRIVING
  couple_axis: TRANSVERSE (slight lateral rotation of uke around CoM)
  min_torque: LOW                                   # the foot does the work; hands only destabilize

body_part_requirement:
  tori_supporting_foot: depends on which uke foot is targeted
  tori_attacking_limb: right_foot (for right-sided canonical)
  contact_point_on_uke: "right_ankle" OR "right_foot_arch"
  contact_height_range: (floor, mid_shin)
  
  timing_window:
    target_foot: "right"                            # uke's forward-stepping foot
    weight_fraction_range: (0.1, 0.3)               # narrow unweighting window
    window_duration_ticks: 1                        # one tick at dt = 1.0s resolution

uke_posture_requirement:
  trunk_sagittal_range: (-10°, +15°)
  trunk_frontal_range: any
  com_height_range: any                             # insensitive — the foot is the target, not the body
  base_state: MID_STEP                              # one foot transitioning

commit_threshold: 0.45                              # moderate, but useless without timing_window match

sukashi_vulnerability: 0.25                         # low — uke typically just resets if missed
counter_vulnerability: 0.20

failure_outcome:
  primary (too early — foot planted): TORI_SWEEP_BOUNCES_OFF — minor compromised, stance reset
  secondary (too late — foot replanted): STANCE_RESET — no compromised state, grips may survive
  tertiary (timing correct, force insufficient): PARTIAL_THROW — waza-ari or yuko depending on landing
```

**Note on de-ashi-harai and the prose layer.** Because this throw depends so heavily on judo sense (per-technique perception), the narrative opportunity is significant. When a specialist lands one, the prose can emphasize the *reading* — "Tanaka saw the foot lift half a beat early." When a novice misses, the prose can show the confusion — "Tanaka swept, but Sato's foot was already coming down." Same throw, same physics, different narrative registers driven by whether judo sense fired.

---

### 5.5 Remaining throws — Session 4 backfill

The following throws inherit the template structure but are not written in v0.1. Session 4 (or solo designer work over the weekend) fills them in using the same prose-then-pseudocode format:

- **O-goshi (major hip throw)** — Lever, both feet supporting, sacrum/hip fulcrum, belt-grip (tsurite) + sleeve (hikite). Template complete; research data thin (no instrumented studies).

- **Tai-otoshi (body drop)** — Lever, shin fulcrum, pure rotational throw with no lift. Couple-like force action but Lever geometry. Highest shoulder-impact velocity in the literature (Soldin 2022). HAJ-59: the shin-block geometry is incompatible with hip loading — `hip_engagement_penalty.engaged_floor ≈ 0.05`, which collapses the body-parts dimension when tori's trunk sagittal exceeds ~40°. The throw still fires; it lands as a stumble with tori entangled with uke afterward, narrated at the LOW quality band as "Tanaka loaded the hip — Tai-otoshi doesn't want the hip — the throw landed crooked."

- **Ko-uchi-gari (minor inner reap)** — Couple, most timing-sensitive ashi-waza, possibly gets the timing_window variant like de-ashi-harai. Research extremely thin.

- **O-uchi-gari (major inner reap)** — Couple, backward kuzushi, standard force-couple pattern. Rich pedagogical literature, thin kinetics.

- **Harai-goshi, competitive form** — Couple (Imamura 2007 confirms competitive form is Couple-class). Classical form as separate Lever entry.

- **Harai-goshi, classical form** — Lever, hip fulcrum, traditional hip-throw kinetics.

- **Tomoe-nage (circle / sacrifice throw)** — Lever with inverted commitment structure. Tori sacrifices own balance as part of kuzushi. Foot-on-belt fulcrum. Zero biomechanics literature; parameters inferred from Kashiwazaki coaching and first-principles.

- **O-guruma (major wheel)** — Lever, extended-leg fulcrum at hip-line. Maximum moment arm among Lever throws. No empirical studies.

All eight inherit the four-dimension signature from Parts 4.3–4.4 without modification. Adding them post-v0.1 requires only parameter specification, no new physics code.

---

## PART 6 — CROSS-CUTTING MECHANICS

Three mechanics that sit on top of the throw templates and make the simulation feel alive across a match rather than per-throw. These are the load-bearing pieces that turn the physics substrate from a collection of throw instances into a match engine with rhythm, tempo, and consequence.

### 6.1 Skill-compression of the tsukuri-kuzushi-kake sequence

Classical Japanese judo theory divides a throw into three phases:
- **Kuzushi** (崩し, "breaking balance") — off-balancing the opponent
- **Tsukuri** (作り, "making / fitting-in") — positioning self relative to the off-balanced opponent
- **Kake** (掛け, "execution / attack") — completing the throw

Matsumoto et al. (Kodokan Report V, 1978) established with force plates and EMG that these phases **overlap temporally** in skilled performance and cannot be separated. Every empirical study since has confirmed this. In the simulation, this overlap is modeled as a skill-dependent compression factor **N** — the number of ticks across which a throw attempt unfolds.

**Belt-rank to N mapping for v0.1:**

| Belt rank | N (ticks per attempt) | Behavior |
|-----------|----------------------|----------|
| White (mudansha beginner) | 5–6 | Three distinct pulses: pull → enter → throw. Wide gaps between sub-events. |
| Yellow / Orange | 4–5 | Pull and enter overlap slightly. Throw still distinct. |
| Green / Blue | 3–4 | Pull-enter compressed into one pulse. Throw is a separate event. |
| Brown | 2–3 | Kuzushi and tsukuri fully overlap. Kake still visible as its own tick. |
| Shodan (first-degree black belt) | 2 | Kuzushi-tsukuri-kake compressed into two ticks. |
| Advanced dan | 1–2 | Single continuous action. |
| Elite / Olympic | 1 | Throw fires in a single tick. No internal sub-events. |

These are starting calibration values. Exact N is Phase 3 work.

**Within-attempt structure for N > 1.** When N > 1, the throw unfolds as an explicit sequence of sub-events emitted to the log across N ticks:

```
Tick t    : REACH_KUZUSHI    (tori applies force, uke's CoM begins to move)
Tick t+1  : KUZUSHI_ACHIEVED (uke's CoM has exited recoverable region)
Tick t+2  : TSUKURI          (tori repositions — turn-in, hip load, fulcrum set)
Tick t+3  : KAKE_COMMIT       (throw executes)
```

For N = 1, all four of these collapse into a single tick event, emitted as one log line. For N = 2, KUZUSHI_ACHIEVED and TSUKURI emit together. For N = 5, each is its own tick and the log explicitly narrates the drawn-out attempt.

**How compression interacts with counter-windows.** Each sub-event is a potential counter-window for uke. A white belt's five-tick attempt exposes four counter-opportunities; an elite's one-tick attempt exposes none. This directly produces the real-judo pattern where novice attacks are easy to read and defend, while elite attacks arrive without warning.

**How compression affects failure outcomes.** A white belt who fails mid-attempt (say, at the TSUKURI tick) ends in a specific compromised state determined by *which sub-event* they were in when they failed. An elite who fails fails at KAKE only — there's no mid-attempt state for them to be caught in. This means lower-skilled judoka have a richer set of compromised states to land in, while elites have a narrow (but harder to exploit) set.

**Per-technique compression override.** A judoka's tokui-waza (specialist technique — the throw they've trained most) uses their N-value *minus one*, to a floor of 1. A brown belt who specializes in Uchi-mata attempts Uchi-mata with N = 2 rather than N = 3, while attempting all other throws with N = 3. This is the mechanical signature of mastery: the compressed attempt is the specialist's advantage. It combines with the judo-sense perception boost (Part 3.5 / open questions) to make a judoka's specialty genuinely theirs.

### 6.2 The three counter-windows as state regions

Classical judo theory distinguishes three timings for counter techniques, each with its own Japanese name:

- **Sen-sen no sen** (先々の先, "before-before the initiative") — preempt the attack before it forms. Counter the attacker's intent.
- **Sen no sen** (先の先, "initiative before initiative") — strike at the moment the attack commits but before it delivers. Symmetric counter.
- **Go no sen** (後の先, "after the initiative") — counter after the attack has committed. Redirect the committed momentum.

These are not time windows — they are **state regions** in the dyad's BodyState space. A counter is committable when the dyad state falls into the corresponding region. Low-IQ defenders have trouble perceiving which region they're in; elite defenders read it accurately.

**Region definitions for v0.1:**

**Sen-sen no sen region.**
- Tori's grip state: driving mode on at least one grip, but no force application exceeding threshold yet.
- Tori's CoM velocity: > 0.3 m/s toward uke (committing distance).
- No throw sub-event has emitted yet (the attempt is only in preparation).
- Counter options: grip-fighting preempts (strip tori's driving grip), directional step-off (uke moves so tori's attack-in misses), or a fast direct attack (uke fires first — De-ashi-harai loves this region, catching tori mid-step-in).

**Sen no sen region.**
- Tori has emitted REACH_KUZUSHI or KUZUSHI_ACHIEVED sub-event.
- Tori's fulcrum (for Lever) is loading OR tori's couple forces (for Couple) are forming.
- Uke's CoM has **not yet** crossed the commit line.
- Counter options: symmetric counter-throw (if uke's grips and posture support a throw in the opposite direction). O-soto-gari vs. O-soto-gari collisions live here. Uchi-mata-sukashi fires in this region — uke pivots knees together as tori enters, voiding the couple.

**Go no sen region.**
- Tori has emitted TSUKURI or KAKE_COMMIT sub-event.
- Uke's CoM has already crossed the commit line OR the fulcrum is loaded and engaged.
- The attack cannot be resisted — it has delivered momentum.
- Counter options: redirection counters (kaeshi-waza 返技). Uke rides tori's committed momentum into a counter-throw. O-soto-gaeshi, O-uchi-gaeshi, Uchi-mata-gaeshi, Ura-nage. These do not generate new force — they redirect tori's already-applied force.

**Defender's perception of the region.** At each tick, a defender evaluates which region the dyad is in and whether they have a counter available. The evaluation uses the same perception-vs-actual split from Part 3.5:

```
perceived_region = actual_region + perception_error(defender.fight_iq)
```

A high-IQ defender with good cardio and composure reads the region accurately and can commit counters cleanly. A low-IQ defender may perceive sen no sen when the dyad is actually in go no sen (tries to resist committed momentum, eats the throw) or may perceive go no sen when the dyad is in sen no sen (attempts a redirection counter on momentum that hasn't arrived yet, and falls forward into nothing).

**Counter availability by defender resources.** Counters cost force, cardio, and composure to execute. A fatigued defender in go no sen region may have the *perception* to counter but not the *resources* to commit. This is the mechanical basis for why tired judoka get thrown by techniques they would have countered when fresh. The defender sees it coming and cannot do anything about it.

**Only committed throws go past go no sen.** Once a throw passes KAKE_COMMIT with signature fully satisfied and counter-window closed, the throw lands. The log emits the Ippon (or waza-ari or yuko depending on landing geometry).

### 6.3 Failed-throw compromised state specification

When a throw fails, tori does not reset to neutral. Tori enters a specific compromised state — a named `BodyState` configuration that leaves them vulnerable to specific counters. The throw templates (Part 4) reference these states by name in their `failure_outcome` fields.

**The compromised state types for v0.1:**

**TORI_COMPROMISED_FORWARD_LEAN.**
- Configuration: trunk_sagittal ≥ +30° (strongly forward-bent), CoM near or outside own base polygon in forward direction, both grips still engaged.
- Origin: failed forward-direction throw where the forward pull committed tori's own CoM forward without delivering force through a fulcrum. Common after a missed Uchi-mata or Seoi-nage standing entry.
- Counter vulnerabilities: uke can commit O-soto-gari against tori's forward-leaning posture (tori's weight already committed forward means uke's couple rotates tori backward easily), O-uchi-gari against tori's exposed forward leg, or ko-soto-gari to the rear.
- Recovery time: 2–3 ticks for tori to recover posture if not countered. Shorter for higher belts.

**TORI_COMPROMISED_SINGLE_SUPPORT.**
- Configuration: one foot in AIRBORNE state, other foot in SUPPORTING_GROUND, CoM near the edge of the single-foot base. Attacking leg (the one that was supposed to reap or sweep) is off the ground and decelerating.
- Origin: failed Couple throw where the reaping/sweeping leg swung without finding expected inertia. Common after a missed Uchi-mata (leg caught no inner-thigh) or a missed foot sweep (bounced off a planted foot).
- Counter vulnerabilities: uke can commit any throw that targets the supporting leg (O-soto-gari if the supporting leg is on the outside, O-uchi-gari if inside), or push tori to fall on the airborne-side.
- Recovery: tori must replant the attacking leg (1 tick minimum) before recovering full posture. Longer for fatigued or low-composure judoka.

**TORI_STUCK_WITH_UKE_ON_BACK.**
- Configuration: Seoi-nage-specific. Tori's back turned to uke, hips higher than uke's hips (the root cause of failure), uke's weight draped across tori's back, both grips engaged, tori's spine sharply flexed.
- Origin: failed Seoi-nage where tori did not bend knees enough to get hips below uke's hips. The #1 technical failure per Gutiérrez-Santiago (2013).
- Counter vulnerabilities: uke can pull down on tori's collar for direct ne-waza transition (tori rolls forward, uke maintains top position), commit Ura-nage (suplex — uke arches back and throws tori over uke's head), or simply step around and stay in top position as tori collapses. Extremely exploitable.
- Recovery: 3–4 ticks for tori to straighten spine and disengage, assuming uke doesn't counter first. Almost always countered at higher belt ranks.

**TORI_BENT_FORWARD_LOADED.**
- Configuration: Lever-specific, post-kuzushi but pre-completion. Tori's fulcrum is engaged but the lift failed to complete. Tori is bent forward with uke partially lifted but still in contact with the ground. Both grips maintained, high force currently applied.
- Origin: Lever throw where `min_lift_force` could not be sustained through the full kake. Common when tori attempts Seoi-nage or O-goshi with insufficient leg drive.
- Counter vulnerabilities: uke can commit a redirection counter (kaeshi-waza) by adding a small force along the direction tori was already pulling, tipping the partial kuzushi into a counter-throw. O-goshi-gaeshi and Seoi-nage counter-throws (sode-tsurikomi-gaeshi) fire here.
- Recovery: 2 ticks for tori to release and straighten. Usually countered before recovery completes.

**TORI_ON_KNEE_UKE_STANDING.**
- Configuration: Seoi-nage drop variant specific. Tori's one knee is on the mat, the other leg bent, hikite grip may be engaged or stripped, tsurite grip (if it existed) likely dropped during the knee descent. Uke is still standing.
- Origin: failed one-knee drop Seoi-nage (Morote or Ippon variant).
- Counter vulnerabilities: uke can pull down on tori's collar (if reachable) for direct osaekomi setup, step around behind tori for tate-shiho-gatame, execute a direct Ura-nage, or disengage and collect passivity time against a tori who cannot attack while on one knee. The kumi-kata and passivity clocks heavily penalize tori in this state.
- Recovery: 2–3 ticks to rise to single-support and then to stance. Fatigue and composure extend this significantly.

**TORI_ON_BOTH_KNEES_UKE_STANDING.**
- Configuration: two-knee drop Seoi-nage specific. Tori on both knees, possibly with some grip contact remaining. Uke fully standing, potentially with good grips of uke's own.
- Origin: failed two-knee drop Seoi-nage (Morote or Ippon variant). The "hail mary" failure.
- Counter vulnerabilities: maximum. Uke can commit Kesa-gatame (scarf hold pin) directly from standing against a kneeling tori, execute Ura-nage, drop down for Tate-shiho-gatame (mount pin), or simply back away and win by passivity rule. Tori cannot attack or effectively defend from this configuration.
- Recovery: 3–5 ticks to rise to standing, during which the defender has free action. Almost always results in uke gaining ippon, waza-ari, or a decisive positional advantage.

**TORI_SWEEP_BOUNCES_OFF.**
- Configuration: foot-sweep-specific. Tori's sweeping leg has met a planted foot and rebounded. Tori's support leg is intact but balance is briefly disrupted by the rebound.
- Origin: failed foot sweep due to timing window miss (too early — foot still planted).
- Counter vulnerabilities: modest. Uke can counter with a direct foot sweep of their own (timing advantage: uke knows tori just missed), apply a direct attack while tori rebalances, or simply accept the reset.
- Recovery: 1 tick. This is the lightest compromised state because the foot sweep's own force commitment is low.

**TORI_DESPERATION_STATE.**
- Configuration: any throw attempt that failed while tori's composure was low and kumi-kata clock was near expiry. Compound compromised state combining the primary failure state with additional penalties: composure drops further, next attempt's perception error widens, stun_ticks may increment.
- Origin: not a specific throw failure — a layered modifier that stacks on top of the primary compromised state when the judoka was in a desperate mental state at the moment of commit.
- Counter vulnerabilities: all the base state's vulnerabilities, amplified. Recovery extended by 1–2 ticks. Next attempt from this state is likely to fail again, producing a desperation spiral unless the judoka disengages and recovers.

**State transitions and recovery.** A compromised state is not permanent. Each state has a recovery duration; during recovery the judoka's available actions are limited to defensive and postural-recovery actions. If uke counters during the recovery window, the counter resolves as a normal throw attempt (with the compromised state's signature contributing to uke's own match score). If uke does not counter (because perception missed, resources insufficient, or uke chose not to), tori returns to neutral at the end of the recovery window.

**How the prose layer uses compromised states.** Each compromised state is a distinct narrative moment. The log emits different prose for each:

- `TORI_ON_BOTH_KNEES_UKE_STANDING` narrates the sudden drop and the crowd's intake of breath.
- `TORI_STUCK_WITH_UKE_ON_BACK` narrates Tanaka's spine arching in the wrong direction while Sato resets their feet.
- `TORI_SWEEP_BOUNCES_OFF` narrates a single beat of nothing-happened.
- `TORI_DESPERATION_STATE` narrates the weight of the clock.

This is the structural engine that addresses the Bucket 3 playthrough complaint about repetitive text: the simulation *produces* distinct mechanical situations, and the prose layer renders each distinctly rather than pulling from a single template.

---

## OPEN QUESTIONS NOT YET ASSIGNED TO A SECTION

*Captured as they arise during the session. Not every question gets answered in v0.1 — some move to a Session 4 backlog.*

- [ ] How does ne-waza relate to the physics substrate? Parallel system, or same system with different posture constraints? (Probably parallel for v0.1.)
- [ ] How does fatigue affect grip force ceilings specifically? (Iglesias 2003: ~15% grip decline across a four-match tournament.)
- [ ] Tokui-waza familiarity: does a judoka's specialist throw have compressed N *only for that throw*, and does it extend the committable-region for that throw's conditions?
- [ ] Player coach actions at Matte: which of the physical state variables does the coach's instruction affect? (Probably: targets grip intent, targets force application style, targets posture defense — not CoM directly.)
- [ ] Judo sense as per-technique perception accuracy: a judoka's specialty foot sweep isn't faster or stronger than the non-specialty's — it's more often caught in its timing window because the specialist *sees* the window open. Every judoka's perception vector across the throw catalog is individual, shaped by their training history and tokui-waza. Ring 2+ work: cultural styles become perception-vector shapes (Japanese sweep readers see foot-weight transitions cleanly; Georgian players see high-lapel openings; Cuban players see forward-drive kuzushi).
- [ ] Session 4 UX: in-script "press play to simulate another match" loop. The designer should be able to run `main.py` once and trigger repeated match simulations from a keypress, rather than re-running the script. Small scope, large calibration-speed payoff during Phase 3 observation work.

---

## RESEARCH SOURCES INTEGRATED INTO THIS SPEC

Primary: Sacripanti (2008, 2010, 2012, 2013, 2014, 2016, 2019), Imamura et al. (2003, 2006, 2007), Blais & Trilles (2004, 2007), Ishii et al. (2016, 2018, 2019), Liu et al. (2021, 2022, 2024, 2025), Hamaguchi et al. (2025), Matsumoto et al. (1978), Kim et al. (2006/2007), Brito et al. (2025).

Canonical: Kano (1986), Daigo (2005/2016), Kawamura & Daigo (2000), Kashiwazaki (1992).

Full citations: see accompanying research artifact.

---

*Document version: v0.1 complete. April 17, 2026. Written across a six-hour design session. Committed to repo at `design-notes/physics-substrate.md`. Next step: Session 4 implementation, beginning with Part 1 (BodyState) as the foundation, building upward through the stack.*
