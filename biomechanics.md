# Biomechanics — Design Note v0.1
### The Physics Layer That Makes Every Match Unrepeatable

*This document captures the core design philosophy for how physical reality 
should shape the Tachiwaza simulation. It is written before the code exists 
so the architecture never accidentally rules it out. Update as the rings develop.*

---

## The Core Idea

Two judoka walk onto the mat. They have never met before — not as people, 
and not as bodies. The height differential, the arm reach, the hip geometry, 
the weight distribution — these specific numbers have never been in this 
specific combination before.

That is what makes every match unrepeatable.

Not random numbers. **Combinatorial physics.**

A throw that wins one match loses the next — not because of luck, but because 
of geometry. A 183cm Tanaka driving seoi-nage against a 178cm Sato is a 
different mechanical problem than that same Tanaka against a 165cm opponent 
who gets *under* his entry. The physics changes. The prose changes with it. 
The moments that get marked change too.

This is the difference between an arcade simulation and *the* simulation.

---

## The Dwarf Fortress Parallel

Dwarf Fortress tracks bone density, muscle attachment points, the specific 
nerve that gets severed. A goblin doesn't just "take damage" — a specific 
piece of their body fails in a specific way with specific downstream 
consequences. A leg wound three minutes ago changes how a fighter moves 
now. The system remembers.

Tachiwaza should do the same thing for a judo match.

Not "right_hand fatigue = 0.4." But: this hand, with this grip strength, 
fatiguing at this rate against this opponent's specific resistance, on 
this throw entry, at this moment in the match.

The prose then reflects the subtlety. Not "Tanaka's grip is weakening." 
But something the simulation *earns* — a specific moment where the numbers 
cross a threshold and the writing register shifts to mark it.

---

## The Five Core Physical Variables

These are the variables that separate one body from another. They live in 
the Identity layer — they are who the judoka IS, not what they can do.

### 1. Height & Limb Length
- Determines moment arm advantage on hip throws (harai-goshi, uchi-mata)
- Taller fighter has longer lever — more rotational force per unit of core strength
- But: lower center of gravity fighters get *under* a tall fighter's entry
- Height differential is the first thing the throw resolution system checks

### 2. Arm Reach
- Grip control radius — how much mat space a fighter can dominate from their center
- Longer reach = wider grip options, harder to circle out of
- Shorter reach = must close distance first, different grip war strategy
- Affects which grip configurations are physically available to each fighter

### 3. Hip Height & Hip-to-Shoulder Ratio
- The geometry of kuzushi — where you need to move the opponent's center of gravity
- A low-hipped, compact fighter is harder to lift and easier to stay under
- Seoi-nage requires tori's hips to drop *below* uke's center — if uke is compact, 
  the entry cost is higher
- Uchi-mata geometry changes completely based on hip height differential

### 4. Weight Distribution
- Where the mass sits — front-loaded vs. back-loaded stance
- A front-loaded fighter is easier to redirect forward (harai-goshi, seoi)
- A back-loaded fighter invites inner reaps (o-uchi, ko-uchi)
- Changes in weight distribution during a match (fatigue shifts posture) 
  open and close different throw windows dynamically

### 5. Body Type (Mass & Density)
- Heavy, dense fighter: harder to move, more inertia, but slower to change direction
- Light, wiry fighter: easier to redirect, but less power behind their own throws
- This is not just weight class — two -90kg fighters can have very different 
  mass distribution and body density

---

## How Physics Feeds the Rings

The biomechanics layer is not a Ring — it is the substrate underneath all of them.
Here is how it touches each ring as it develops.

### Ring 1 — The Match Engine
**Where physics lives:** throw success resolution.

Right now `effective_body_part()` multiplies a base capability score by age 
and fatigue. Phase 2 adds the physics:

```
throw_success_probability = 
    (kuzushi_force / opponent_stability) 
    × technique_effectiveness 
    × (1 - opponent_reaction_penalty)

kuzushi_force = 
    tori_rotational_power 
    × moment_arm(tori_height, uke_hip_height) 
    × grip_security

opponent_stability = 
    uke_mass × uke_stance_width × uke_posture_factor
```

A tall Tanaka driving seoi-nage against a compact opponent has a *smaller* 
moment arm — the formula produces lower success probability automatically, 
without special-casing. The physics generalizes.

**The prose reflects this:** when a throw succeeds against physics — 
when a smaller fighter lifts a larger one — the log marks it differently 
than a textbook throw working as expected.

### Ring 2 — The Coach Instruction System
**Where physics lives:** instruction effectiveness depends on physical state.

"Switch stance" is not free. It costs efficiency — but *how much* depends on 
the fighter's hip flexibility, their dominant side strength differential, 
their current fatigue distribution. A physically asymmetric fighter 
(9 right_hand, 3 left_hand) switching stance is a bigger mechanical 
disruption than a two-sided fighter making the same switch.

The coach needs to know this. The stat panel in the Matte window should 
surface it: *"Switching stance will cost him. His left side isn't there yet."*

### Ring 3 — The Dojo & Training System
**Where physics lives:** training targets physical variables, not abstract stats.

You don't train "grip strength = +1." You train:
- Forearm endurance under resistance (uchikomi bands)
- Hip drop speed for seoi entry (mirror drills)
- Stance width and stability under lateral force (balance boards)

Each training item targets a specific physical variable. The physical 
variable then feeds into the throw resolution formula. The chain is 
complete: **dojo investment → physical improvement → match outcome**.

Over a career, a fighter's body changes — not just their stats. A young 
fighter at 20 has raw explosive power but incomplete hip mechanics. 
At 28 their body has learned to transfer force efficiently. At 35 the 
explosive power begins to fade but the mechanics are so refined they 
compensate. The age curves are physics curves.

### Ring 4 — The Roster & Long Arcs
**Where physics lives:** body type as inheritance and recruitment filter.

When you recruit a prospect, you are not just looking at their current stats. 
You are looking at their body — what it will *become* capable of.

A 16-year-old at 170cm with long arms and narrow hips: potential 
uchi-mata specialist. The physics of their body points toward that throw.
A 16-year-old at 165cm with wide hips and explosive leg strength: 
potential seoi-nage or ko-uchi specialist — lower entry cost, natural 
weight distribution for the technique.

The coach's job is to read the body, not just the current numbers.

---

## What Gets Marked

The prose system marks moments when physics does something unexpected — 
or when physics confirms something that's been building.

**Examples of marked moments:**

- A smaller fighter generates enough rotational force to lift a heavier opponent 
  → the log notes the improbability without explaining it. The number crossed 
  a threshold. The sentence earns it.

- A fighter's grip finally fails after 180 ticks of resistance — not because 
  of a single event, but because the fatigue curve crossed the stability floor. 
  The opponent didn't win the grip war. The physics resolved it.

- A throw that has failed three times finally lands — because hip height 
  differential shifted as the opponent's posture degraded under fatigue. 
  The same technique, different geometry, different outcome.

These are the moments that make a match feel true. Not scripted. **Resolved.**

---

## For the Physics Collaborator

If someone with a physics or biomechanics background is contributing to this 
document, this is where their work lives most directly.

**The questions that need real answers:**

1. What is the actual moment arm calculation for seoi-nage as a function of 
   height differential and hip drop depth?

2. What are the real athletic physiology curves for:
   - Explosive power (fast-twitch fiber output) by age
   - Grip endurance (forearm fatigue rate) by training level
   - Recovery rate differential between 24-year-old and 34-year-old judoka

3. How does center of gravity shift under different grip configurations? 
   Can we model kuzushi as a real force problem?

4. What is the biomechanical cost of stance switching? Is it expressible 
   as an efficiency multiplier, or does it require modeling the specific 
   muscle groups involved?

5. Where does body type (limb proportions, mass distribution) most 
   dramatically affect which throws are physically natural vs. physically costly?

The answers to these questions are what separate the numbers in this 
simulation from intuition. They are the difference between a 0-10 scale 
that *feels* right and a model that *is* right.

---

## Build Discipline

This document describes a destination, not a current state.

**Ring 1 Phase 2** implements a simplified version: height differential as 
a modifier on throw success probability. One physics variable, properly wired, 
observable in the output.

Each subsequent phase adds one more variable to the formula. The architecture 
is designed to accept these additions without refactoring — `effective_body_part()` 
already returns a float that can receive new multipliers. The physics layer 
grows ring by ring, not all at once.

The goal is a simulation where, by Ring 3, you can watch two fighters with 
different bodies produce a match that could not have happened any other way.

That is the infinite replayability. Not content volume. **Physical truth.**

---

*Document version: April 14, 2026 (v0.1). 
Written before Phase 2 code exists. 
Update as each ring implements a new physical variable.*
