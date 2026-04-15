# The Grip Graph — Design Note v0.1
### The Bipartite State Structure Underneath Every Match

*This document specifies the data structure that holds the relational state
of two grappling judoka. The grip sub-loop reads from it. Throw resolution
reads from it. The Matte window renders it. The ne-waza system extends it.
Every observable moment of a match traces back to a transition on this
graph. It is the most foundational change of Phase 2 Session 2 — and the
architectural piece that makes the rest of Tachiwaza possible.*

---

## The Conceptual Claim

A judo match is not two fighters with stat sheets — it is a **relational
state** between two bodies. Who is gripping what, with which hand, at what
depth, with what strength, in which configuration. Tachiwaza models this
state explicitly as a bipartite graph.

The architecture is borrowed directly from Dwarf Fortress's grapple system,
which tracks each wrestling encounter as a set of discrete grab
relationships between body parts. Two creatures wrestling in DF are not in
"a grappling state" — they are in a graph of edges, each edge connecting one
of your body parts to one of theirs, with hold-type metadata. Either side
can have multiple edges into the other simultaneously. Both can be holding
each other at once.

That is what judo's tachi-waza and ne-waza actually are. The grip graph
makes it computable.

---

## Nodes

The graph has two kinds of nodes — **graspers** (the body parts of each
fighter that can establish a grip) and **targets** (the locations on the
opponent's gi or body that can be gripped). Both fighters contribute
graspers; both fighters offer targets.

### Graspers (per fighter)

**Standing graspers (always available):**
- `right_hand`, `left_hand` — primary gripping units
- `right_forearm`, `left_forearm` — frame, secondary anchor

**Ne-waza graspers (available only in NE_WAZA position):**
- `right_arm`, `left_arm` — encircling control (cross-face, underhook)
- `right_leg`, `left_leg` — hooks, triangle, leg entanglement
- `right_hip`, `left_hip` — pinning weight distribution
- `head` — head pressure, kuzure variants

### Targets (offered by opponent)

**Standing targets (gi-based, always available):**
- `left_lapel`, `right_lapel` — collar grips
- `left_sleeve`, `right_sleeve` — sleeve control
- `back_collar` — over-the-shoulder, cross-collar
- `left_back_gi`, `right_back_gi` — pulling positions, kuzure-kesa
- `belt` — over-the-top, Georgian-style

**Ne-waza targets (body-based, available in NE_WAZA position):**
- `neck` — chokes
- `left_wrist`, `right_wrist` — control, kote-gaeshi family
- `left_elbow`, `right_elbow` — joint isolation for armbars
- `left_shoulder`, `right_shoulder` — control, posture break
- `left_knee`, `right_knee` — joint isolation, leg locks (rare in judo)
- `left_ankle`, `right_ankle` — control, escape prevention
- `head` — turtle break, rear control
- `waist` — body control for mount/back/side

The `head` and `neck` distinction is deliberate: `neck` is the choke target
(throat-side), `head` is the control target (skull-side). A judoka with a
hand on the head and another on the neck is in a profoundly different
position from one with both hands on the lapels.

---

## Edges — The GripEdge Dataclass

Each active grip is one edge connecting one grasper (with its owning
fighter) to one target (with its owning fighter).

```python
@dataclass
class GripEdge:
    grasper_id: str            # which judoka owns the grasping body part
    grasper_part: BodyPart     # right_hand, left_forearm, right_leg, etc.
    target_id: str             # which judoka is being gripped
    target_location: GripTarget # left_lapel, neck, right_wrist, etc.
    grip_type: GripType        # see enum below
    depth: float               # 0.0 (shallow) to 1.0 (dominant)
    strength: float            # current force; degrades with fatigue
    established_tick: int      # when this edge was created
    contested: bool            # opponent is actively trying to break it
```

### GripType enum

The grip_type captures *how* the grasper is anchored, not just *where*. Two
right-hand-on-left-lapel edges can be radically different:

- `STANDARD` — classical sleeve/lapel hold
- `PISTOL` — sleeve choke-grip, palm down, locked thumb
- `CROSS` — reaching across the body to opposite side
- `DEEP` — hand far inside the collar, controlling posture
- `POCKET` — gripping at the seam, brief and weak
- `HIGH_COLLAR` — grip up near the back of the neck
- `BELT` — Georgian over-the-top
- `OVER_BACK` — chidaoba-style across the shoulder
- `RUSSIAN` — wrist control with arm hook (sambo/wrestling crossover)
- `UNDERHOOK` — arm under armpit, ne-waza control
- `TWO_ON_ONE` — both hands on opponent's one limb (control, isolation)

Different grip types have different strength profiles, fatigue rates, and
throw prerequisites they satisfy. A `DEEP` collar grip enables seoi-nage
prerequisite checks; a `STANDARD` does not.

---

## How Edges Form, Live, and Die

The graph is dynamic. Every tick, edges may be created, modified, or
destroyed.

### Edge creation — ENGAGEMENT

When two fighters close distance from `STANDING_DISTANT` to `ENGAGEMENT`,
each fighter attempts to establish initial grips. The probability of
successfully creating an edge depends on:

- **Reach asymmetry** — the longer-armed fighter has higher chance of
  gripping first
- **Hand strength** — stronger hand has higher chance of securing a grip
- **Style preference** — Ring 2+ cultural layer biases which targets each
  fighter reaches for
- **Stance matchup** — mirrored stance changes which targets are
  geometrically natural

A typical engagement produces 1–3 edges in the first 1–3 ticks.

### Edge contest — TUG_OF_WAR

Once edges exist, the sub-loop's TUG_OF_WAR state drives them. Each tick:

- Edge `strength` degrades proportionally to held duration and grasper
  fatigue
- If both fighters are contesting the same target, the weaker edge loses
  strength faster
- If a grasper is being attacked (the opponent is targeting that hand to
  strip the grip), the edge enters `contested = True` and degrades faster

### Edge resolution — three tiers

DF's three-tier outcome system applies to every grip contest. Per tick,
each contested edge resolves to one of three states:

**SUCCESS** — edge maintains or upgrades. Strength holds. If the grasper is
deepening (e.g., shallow collar → deep collar), `depth` increases.

**PARTIAL** — edge slips. `depth` decreases by a step (deep → shallow).
Strength drops. The grip is still live but degraded. Mirror DF's *"You
adjust the grip of Your right upper arm on The creature's upper body"* —
the prose marks the slip without ending the contest.

**FAILURE** — edge is broken. The GripEdge object is removed from the
graph. The grasper is now free; the target is now ungripped. Future
attempts must restart from creation.

### Edge fatigue

Edges drain the grasping body part's fatigue at a rate proportional to:

- How long the edge has been held (`current_tick - established_tick`)
- How contested the edge is (contested edges drain ~2x faster)
- The grasper's `cardio_efficiency` (better cardio = slower drain)
- The grip type (a `DEEP` collar drains the hand faster than a `POCKET`)

Once a grasper crosses a fatigue threshold (default 0.85), a die-roll per
tick may force-break the edge involuntarily. The fighter is gripping
through cooked forearms; the body releases regardless of intent.

### Edge persistence through position transitions

Critical design decision: **edges do not automatically reset on a position
change.** A judoka who maintains a deep collar grip through a stuffed
throw and into a scramble enters NE_WAZA with that collar grip *still
live*. This is one of the most beautiful dynamics in real judo — the
fighter who keeps their grips through the chaos has a structural advantage
the moment things settle.

Specific transitions:

- `GRIPPING → SCRAMBLE`: edges marked `contested = True`. Each takes a
  per-tick break-roll for the next 3 ticks.
- `SCRAMBLE → NE_WAZA`: surviving edges persist. New ne-waza graspers
  (legs, hips) become available and can establish new edges.
- `NE_WAZA → STANDING_DISTANT` (escape): all edges break. Both fighters
  reset.
- `THROW_COMMITTED → success`: tori's edges may persist into ne-waza
  follow-up; uke's edges all break (they hit the mat).

---

## Throw Prerequisites Read from the Graph

This is the architectural fix to the "throws fire every tick" problem from
Phase 2 Session 1. **A throw cannot be attempted unless the graph satisfies
its prerequisites.**

Each throw in the registry declares the edges it requires:

```python
SEOI_NAGE = ThrowDef(
    name="seoi-nage",
    requires=[
        # Tori needs deep collar grip on their dominant side
        EdgeRequirement(
            grasper_part=BodyPart.dominant_hand,
            target_location=GripTarget.opposite_lapel,
            grip_type_in=[GripType.DEEP, GripType.HIGH_COLLAR],
            min_depth=0.6,
        ),
        # Tori needs sleeve control on the pulling side
        EdgeRequirement(
            grasper_part=BodyPart.pull_hand,
            target_location=GripTarget.dominant_sleeve,
            grip_type_in=[GripType.STANDARD, GripType.PISTOL],
            min_depth=0.3,
        ),
    ],
    posture_requirement=[Posture.UPRIGHT, Posture.SLIGHTLY_BENT],
    primary_body_parts=[BodyPart.lower_back, BodyPart.core,
                        BodyPart.dominant_hip, BodyPart.dominant_thigh],
    landing_profile=LandingProfile.FORWARD_ROTATIONAL,
)
```

The match engine, before allowing a throw attempt, queries the graph:
**does the current set of GripEdges satisfy this throw's requirements?**

- Yes + kuzushi window open → high success probability
- Yes + no window → moderate, possible to force
- No → throw cannot be attempted at all, OR can be forced with massive
  penalty (the desperate, sloppy attempt that earns shido)

This is exactly DF's state-dependent action availability. You can only
"Lock joint" if you've already "Grabbed limb." You can only seoi-nage if
the grip graph supports it.

The natural consequence: a fighter who loses the grip war cannot attack.
Their offensive options collapse. The opponent's grip dominance becomes
visible through the simulation outcome rather than narration.

---

## Multi-Turn Commitment Chains — Ne-Waza Progressions

Ne-waza techniques are not single events. They are sequences of edge state
changes across multiple ticks, each step depending on the previous.

### The choke chain (e.g., okuri-eri-jime, sliding lapel choke)

```
TICK N    — Establish neck edge (requires NE_WAZA position with back
            control or side control). Edge type: STANDARD on neck.

TICK N+3  — Set the choke edge. Upgrade neck edge to grip_type CHOKE_HOLD.
            Adds an opposing-lapel edge for cross-cinching.

TICK N+8  — Tighten. Both choke edges roll for SUCCESS each tick. Opponent
            rolls for ESCAPE each tick.

TICK N+12 — If choke edges still live and opponent has not escaped:
            tap-out / ippon by submission.
```

During the chain, the bottom fighter has counter-actions available each
tick: frame the cross-face, hand-fight the lapel grip, hip-out to create
space, scramble for a turn-over. Each counter-action is itself a graph
operation (adding edges of their own, or contesting existing edges).

### The joint lock chain (e.g., juji-gatame, cross armlock)

```
TICK N    — Isolate the arm. Establish edges on opponent's wrist + elbow.

TICK N+3  — Position the legs across opponent's body. Establish edges from
            tori's legs to opponent's torso/head.

TICK N+6  — Hip onto the shoulder. Edge type upgrades to ARMBAR_THREAT.

TICK N+10 — Extend. Roll for SUCCESS vs. opponent's defensive grip
            (their hand-fight to keep the arm bent).

TICK N+13 — If extension succeeds: tap / ippon. If opponent's defensive
            grip survives: armbar attempt fails, tori loses position.
```

### The pin (osaekomi)

```
TICK N    — Establish pin position (NE_WAZA + side_control or
            kesa_gatame). Referee starts osaekomi clock.

TICK N+10 ticks (10 seconds) — Waza-ari awarded. Pin continues.

TICK N+20 ticks (20 seconds) — Ippon awarded. Match over.

DURING:   Opponent rolls escape attempts each tick. A successful escape
            breaks the pin edges; clock stops; both fighters scramble.
```

The opponent's escape probability per tick depends on their `ne_waza_skill`,
their remaining cardio, their composure, and the specific pin type
(kesa_gatame allows certain escapes that kuzure-kami-shiho-gatame doesn't).

### Counter-actions per turn

Every commitment chain gives the bottom fighter *something to do* each
tick. This is the design discipline that makes ne-waza interesting rather
than passive. The choke isn't a 12-tick cutscene — it's 12 ticks of
contested, edge-by-edge resolution where the bottom fighter is fighting
for their life and the top fighter is committing real resources.

---

## The Announcement Event Taxonomy

Every change to the graph fires a typed event. The prose engine reads these
events and renders sentences. This is DF's `announcements.txt` pattern
applied to judo.

### Standing events

- `ENGAGEMENT_BEGUN` — fighters close to grip range
- `GRIP_ESTABLISH` — new edge created
- `GRIP_BREAK` — edge removed
- `GRIP_FIGHT` — contested edge enters tug-of-war
- `GRIP_UPGRADE` — edge depth increases
- `GRIP_DEGRADE` — edge depth decreases (PARTIAL outcome)
- `GRIP_DOMINANT_ACHIEVED` — one fighter has multiple deep edges, opponent has shallow or none
- `KUZUSHI_WINDOW_OPENED` — sub-loop produces an opening
- `KUZUSHI_WINDOW_CLOSED` — opening passed without commitment
- `STIFLED_RESET` — sub-loop stalemate, both fighters break and breathe
- `THROW_ENTRY` — fighter commits to a throw
- `THROW_DEFENSE` — opponent reads it, executes defense
- `THROW_LANDING` — outcome resolution with landing angle
- `STUFFED` — throw blocked, scramble window opens

### Scoring events

- `IPPON_AWARDED` — clean dorsal landing, control maintained
- `WAZA_ARI_AWARDED` — partial landing or angled
- `NO_SCORE` — throw failed to register
- `SHIDO_AWARDED` — passivity, false attack, etc.
- `HANSOKU_MAKE` — third shido or direct DQ

### Ne-waza events

- `NEWAZA_TRANSITION` — fight goes to ground
- `POSITION_ESTABLISHED` — side control, mount, back, etc.
- `POSITION_LOST` — bottom fighter improved
- `OSAEKOMI_BEGIN` — pin clock starts
- `OSAEKOMI_BROKEN` — escape successful
- `CHOKE_INITIATED` / `CHOKE_TIGHTENING` / `CHOKE_RESOLVED`
- `ARMBAR_INITIATED` / `ARMBAR_EXTENDING` / `ARMBAR_RESOLVED`
- `ESCAPE_ATTEMPT` / `ESCAPE_SUCCESS`
- `TURNOVER` — bottom fighter reverses position

### Match-flow events

- `HAJIME_CALLED` — match begins
- `MATTE_CALLED` — referee pause
- `MATTE_REASON` — out_of_bounds / stalemate / penalty / scoring / safety
- `INSTRUCTION_GIVEN` — coach issues call (Ring 2)
- `INSTRUCTION_RECEIVED` — fighter parses and applies
- `MATCH_OVER` — final score, winner

Each event carries the graph state that produced it. The prose engine has
access to the full edge list, position, scores, and fatigue at the moment
of every event. This is how the sportswriter voice gets the specificity to
say *"Tanaka's right hand still on the collar"* instead of *"Tanaka has a
grip."*

---

## Coach IQ Gates Visibility

The full graph is always computed by the simulation. **The coach's view of
the graph in the Matte window is filtered by their coaching IQ.** This is
the architectural hook for the design idea you noted: a low-IQ coach sees
less of what's happening; a high-IQ coach reads the whole board.

### Visibility tiers (Ring 2 implementation)

**Coach IQ 1–4 (novice):**
- See: position name, score, fatigue qualitative ("getting tired")
- Hidden: edge list, depth values, opponent's fatigue distribution
- Instructions: 3 broad options ("attack," "defend," "rest")

**Coach IQ 5–7 (developed):**
- See: edge list with grip_type and qualitative depth ("deep collar,"
  "shallow sleeve")
- See: which side has dominant grip
- Hidden: numeric depth, opponent's fatigue numbers
- Instructions: 5 options, including grip-specific ones

**Coach IQ 8–10 (elite):**
- See: full graph with numeric depth and strength
- See: opponent's fatigue distribution per body part
- See: physics readout (height differential, hip geometry, moment arm
  status)
- Instructions: full 7-category taxonomy, plus physics-aware options

This gives Ring 3 (dojo training) a meaningful long-term progression
vector: training your coaching IQ over time literally makes the Matte
panel more legible. Your fights start *feeling* clearer to read because
you can see more of what's actually there.

The simulation underneath never changes. The fighter still does what the
graph says they do. Only the coach's view of it changes. This means a
coach with low IQ giving instructions on a state they can't fully see
will sometimes give *wrong* instructions — and that's the lived
experience of being a developing coach.

---

## What This Doesn't Build (and Where It Will)

- **Coach instructions and reception** — Ring 2 / Phase 3. The graph
  exists; the coach reading it and translating to instructions is a
  separate layer.
- **Style preference biases on grip selection** — Ring 2+. The cultural
  layer modifies which graspers reach for which targets at engagement.
  Ring 1 uses neutral defaults.
- **Full prose templating** — Phase 4. Session 2 uses placeholder log
  strings that mark the right moments. Pretty sentences come later.
- **Physics-aware dynamic edge strength** — partially in Session 2 (height
  differential affects who grips first), more comprehensive in later
  calibration passes.
- **Visual rendering of the graph** — Ring 5. The 2D layer eventually
  shows edges as visible stripes between fighters; Ring 1 keeps it all in
  the prose log.

---

## How This Connects

- **`biomechanics.md`** — the five physical variables modulate edge
  strength, edge formation probability, and which throw prerequisites are
  geometrically satisfiable.
- **`grip-sub-loop.md` v0.2** — the sub-loop math now operates on the
  GripEdge list. TUG_OF_WAR computes grip_delta from edge strengths.
  KUZUSHI_WINDOW depends on edge depth + posture state.
- **`data-model.md` v0.4** — the GripEdge fields live in the Match
  object's State (a list, not a dict). Body part expansion to 24 parts
  enables ne-waza graspers and targets.
- **`cultural-layer.md`** — Ring 2+ modifies grip preference at
  engagement and instruction phrasing in the Matte panel.

---

*Document version: April 14, 2026 (v0.1).
Written before Phase 2 Session 2 code exists.
Update after the Session 2 implementation reveals what the spec missed.*
