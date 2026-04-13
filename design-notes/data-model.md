# Judoka Data Model — Design Note v0.1

*This is the spec for the `Judoka` class. Code is implemented from this document, not the other way around. If we want to change the class, we change this doc first, then the code.*

---

## Design Philosophy

A `Judoka` holds three layers of information, kept structurally separate:

- **Identity** — who they are. Static or slow-changing across a career.
- **Capability** — what their body and mind can do *fresh*. Trained over months in the dojo. Persisted between matches.
- **State** — what's true *right now in this match*. Initialized fresh each match. Updated every tick.

This separation is what lets the same fighter have a great match one day and a terrible one the next: same Capability, different State trajectory.

For Ring 1, we build all three layers. We don't build the dojo system that *modifies* Capability — we just hand-build two judoka with reasonable values and let them fight.

---

## Layer 1 — IDENTITY

Static or near-static. Shapes how Capability and State express themselves but does not directly enter the tick loop.

| Attribute | Type | Range / Example | Notes |
|---|---|---|---|
| `name` | str | "Tanaka" | Display name. |
| `age` | int | 16–40 | Affects recovery rates and injury risk (Ring 3+). |
| `weight_class` | str | "-90kg" | For Ring 1, hardcoded to -90kg. |
| `height_cm` | int | 165–195 | Affects throw success biases (taller = better uchi-mata leverage, shorter = better seoi-nage). |
| `body_archetype` | enum | LEVER / MOTOR / GRIP_FIGHTER / GROUND_SPECIALIST / EXPLOSIVE | Modifies which throws and tactics the fighter is naturally suited to. |
| `belt_rank` | enum | WHITE / YELLOW / ORANGE / GREEN / BLUE / BROWN / BLACK_1 ... BLACK_5 | Determines throw vocabulary size (see Repertoire below). |
| `dominant_side` | enum | RIGHT / LEFT | A right-handed fighter naturally fights right-handed grip. Switching sides is possible but costs efficiency. |
| `personality_facets` | dict | see below | Shapes behavior under stress and instruction reception. |

### Personality Facets (subset for Ring 1)

Each on a 0–10 scale. These start as seed values; in later rings they shift over a career.

```
aggressive    ↔ patient
technical     ↔ athletic
confident     ↔ anxious
loyal_to_plan ↔ improvisational
```

Ring 1 uses these only to bias decision-making in close calls (e.g., an aggressive fighter is more likely to commit to a ne-waza window; an anxious fighter loses composure faster after a stuffed throw).

---

## Layer 2 — CAPABILITY

What the body and mind can do *fresh*. Each value represents the maximum the fighter can perform when uninjured and unfatigued.

### Body Capability — 15 parts

```
HANDS:        right_hand,        left_hand          (grip security, finger strength)
FOREARMS:     right_forearm,     left_forearm       (grip endurance, gripping pulls)
BICEPS:       right_bicep,       left_bicep         (pulling strength, frame breaking)
SHOULDERS:    right_shoulder,    left_shoulder      (throw entry, posture)
LEGS:         right_leg,         left_leg           (throw power, defense base)
FEET:         right_foot,        left_foot          (footwork, sweeping precision)
CORE:         core                                  (rotational power, posture stability)
LOWER_BACK:   lower_back                            (throw lift, posture defense)
NECK:         neck                                  (posture defense vs. forward bend)
```

Each on a **0–10 scale**. A 10 is world-class for that part; a 5 is solid club-level; a 2 is a weak point an opponent can exploit.

**Calibration honesty:** 15 parts is a lot. In Phase 1 of Ring 1, only ~6 of these will *meaningfully* participate in the simulation (hands, forearms, legs, core, lower_back, neck — the parts most active in grip + throw + defense). The other 9 are present in the data model but read as quiet. We add their behavior incrementally as we identify what they should *do*.

This is the right way to build a 15-part body: declare it once, animate it gradually.

### Cardio — global

```
cardio_capacity   (0–10)   — total endurance pool
cardio_efficiency (0–10)   — how slowly cardio drains under load
```

Cardio is global because it's lung/heart, not localized. It modifies the recovery rate of every body part.

### Mind Capability

```
composure_ceiling  (0–10)  — maximum composure when calm
fight_iq           (0–10)  — read speed, combo recognition, opening detection
ne_waza_skill      (0–10)  — separate from standing technique; many judoka are great standing and average on the ground
```

Composure is a *ceiling* in Capability and a *current value* in State. Same with cardio.

### Repertoire — Throws & Combos

This is where Q2 expands into a real system.

```python
throw_vocabulary: list[ThrowID]      # Throws this judoka knows at all
signature_throws: list[ThrowID]      # 2–4 throws they specialize in
signature_combos: list[ComboID]      # Sequences they've drilled
```

**Throw vocabulary size by belt rank** (initial proposal — calibrate with playtesting):

| Belt | Vocabulary size |
|---|---|
| White / Yellow | 3–5 |
| Orange / Green | 6–10 |
| Blue / Brown | 10–15 |
| Black 1–2 | 15–22 |
| Black 3+ | 22–30 |

A throw they don't know, they can't attempt. This is what makes a yellow-belt prospect feel different from a third-degree black belt.

**Per-throw success modifiers.** For each throw in the vocabulary, the judoka has a personal effectiveness rating (0–10). Signature throws are 8–10. Throws barely in the vocabulary are 2–4. This rating combines with body archetype, height, opponent state, and current fatigue to produce the actual roll.

**Combos** are stored as ordered sequences: `[ko_uchi_gari → seoi_nage]`. When a judoka attempts the first move, there's a small chance to chain into the second if conditions allow. Signature combos chain at higher rates.

For Phase 1 of Ring 1, we hand-build:
- A `Throw` registry with maybe 8 throws (seoi-nage, uchi-mata, o-soto-gari, o-uchi-gari, ko-uchi-gari, harai-goshi, tai-otoshi, sumi-gaeshi)
- A `Combo` registry with maybe 3 combos
- Two judoka with chosen vocabularies and signatures

We expand the registries later. The data model supports any number.

---

## Layer 3 — STATE

Initialized at match start from Capability. Updated every tick. Fully resets at the next match start (with one exception — see Tournament Carryover below).

### Body State

For each of the 15 body parts:

```
fatigue:    float (0.0 – 1.0)   # 0.0 = fresh, 1.0 = completely cooked
injured:    bool                # set true if a serious event hits this part
```

Effective strength of a part at any moment:
```
effective = capability × (1 - fatigue) × (0.3 if injured else 1.0)
```

Fatigue accumulates based on what the part is *doing*. Recovery happens slowly during action and faster during Mate. Cardio modifies recovery rate.

### Cardio State

```
cardio_current   (float, 0.0 – 1.0)   # depleted by sustained action
```

### Mind State

```
composure_current   (float, 0.0 – composure_ceiling)
last_event_emotional_weight   (float)   # spike from significant events; decays over ticks
```

### Match State

```
position             enum   STANDING_DISTANT / GRIPPING / ENGAGED / SCRAMBLE / NE_WAZA / DOWN
posture              enum   UPRIGHT / SLIGHTLY_BENT / BROKEN
grip_configuration   dict   # which hand has what grip on which part of the opponent's gi
score                dict   # waza-ari count, ippon flag
shidos               int    # penalty count
recent_events        list   # last N tick events, used for short-term decision context
current_instruction  str    # most recent coach instruction; biases next decisions
instruction_received_strength  float (0.0 – 1.0)   # how cleanly it's being executed
```

### Tournament Carryover (Ring 2 prep — note this now)

Q7 introduces an architectural requirement: **some State must persist across matches in the same tournament day.** Specifically:

```
matches_today                     int
cumulative_fatigue_debt           dict[body_part, float]   # incomplete recovery between matches
emotional_state_from_last_match   enum   ELATED / RELIEVED / DRAINED / SHAKEN / FOCUSED
```

After each match, fatigue partially recovers but not fully. Composure ceiling is temporarily modified by the emotional state. An anxious fighter who just won a tough quarterfinal might enter the semi-final with elevated composure; a confident fighter who won easily might be reckless.

**For Ring 1, we do not implement this.** But we structure the State class so that "initialize from Capability" and "initialize from previous match's residual state" are two separate code paths. That way Ring 2 just adds the second path without rewriting.

---

## What Ring 1 Phase 1 Actually Builds

To be concrete about the scope of the first Claude Code session:

✅ All three layers as Python classes (`Identity`, `Capability`, `State`, composed into `Judoka`)
✅ The 15-body-part structure declared
✅ Throw and Combo registries with ~8 throws and ~3 combos hand-defined
✅ Two hand-built judoka in `main.py`: a Tanaka (LEVER, seoi-nage specialist) and a Sato (MOTOR, uchi-mata specialist)
✅ A `Match` class with a tick loop that runs for 240 ticks (one match-second per tick, 4-minute match)
✅ The tick loop *does not yet have real combat logic.* It just prints `"tick N: [placeholder event]"` and updates fatigue on a couple of body parts.
✅ Match ends with a placeholder winner.

That's it. No Mate window yet. No prose templates. No real grip state graph. We're proving the architecture is sound and the classes compose properly.

**Phase 1 success criterion:** you can run `python main.py`, see 240 lines of output, and the two judoka objects look correct when inspected at the end (fatigue accumulated reasonably, capabilities unchanged, state populated).

---

## What Comes After Phase 1

Once the skeleton compiles and runs, we add — one Phase per Claude Code session, roughly:

- **Phase 2:** Real grip state graph. Throw attempts with success rolls. The match log starts being readable.
- **Phase 3:** Mate detection. The simulation pauses. Stat panel renders in terminal. Instruction menu appears. Reception calculation. Resume.
- **Phase 4:** Prose template system. Events get wrapped in real sentences using the tone guide.
- **Phase 5:** Calibration pass. Watch many simulated matches. Tune curves. This is the work you correctly anticipated in your answer to Q5.

---

## Open Calibration Questions (for later)

These don't block Phase 1. They become real once we can watch matches:

- How fast does grip fatigue accumulate? (If too fast, every match ends in cardio collapse. If too slow, grip never matters.)
- How much does composure actually swing per event?
- What's the right base rate for throw attempts per minute?
- How often should Mate be called?
- How big is the ne-waza window after a stuffed throw, on average?

We will get these wrong on the first pass. That's expected. Calibration is a Phase 5 activity informed by watching 50+ simulated matches.

---

*Document version: April 13, 2026. Update before changing the class.*
