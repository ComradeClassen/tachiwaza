# HAJIME — Master Design & Development Document

> *Renamed from Tachiwaza on April 16, 2026. The title* Hajime *refers to the
> referee's call that starts every match — the game is everything that happens
> before Hajime is set, and everything that happens after. As of April 23, 2026,
> the title is also doing a second, structural job: the game is what happens
> when you start your dojo. The match is one of many things that happens inside
> the world the call opens.*

### A Living Brainstorm / Build Roadmap / Reference

*This document is a working artifact. Update it after every session.*

---

## THE PRIORITY DECISION — UPDATED APRIL 23, 2026

**Hajime is the primary creative project. Player Two remains paused. The
horizon is 2–3 years to Early Access — not nine months. January 9, 2027 is
preserved as a personal checkpoint, not a ship date.**

This is the second iteration of the priority decision. The first was made on
April 15, 2026, when Hajime was prioritized over Player Two on the assumption
that a substantial first version of the game could ship as Early Access on
January 9, 2027. That assumption rested on a working understanding of the game
that placed *the match* at the center, with the dojo as supporting context.
The April 23 reshape inverted this — *the dojo loop* is the actual game; the
match is one of several consequential events inside that loop. The implications
of that inversion (calendar, sessions, roster, conversations, lifecycle,
antagonist, pricing, lineage data, two play modes, narrative event framework)
exceed what nine months of solo development can ship.

The new shape:

1. **Hajime continues to be the primary project.** The April 15 prioritization
   stands. Player Two remains paused.

2. **The horizon extends.** Realistic Early Access is mid-2028 to mid-2029,
   roughly a 2–3 year arc from now. This is consistent with what an
   ambitious solo dev project of this scope actually takes. (Reference points:
   Wildermyth was ~6 years to 1.0 with a small team; Dwarf Fortress is its own
   thing; Football Manager has 30 years of iteration behind it. Hajime is more
   modest in scope than any of these but is still a serious multi-year build.)

3. **January 9, 2027 — Personal Checkpoint.** Not a ship date. The internal
   target is *further than where I began*. A working basement-dojo opening with
   the twins arriving, a calendar, a roster, watched randori, the conversation
   mechanic, the antagonist visiting once, three students moving through the
   beginning of their lifecycles. Not public, not for sale. A working
   slice of the game that proves the loop is real. Birthday gift to self
   from a more capable builder.

4. **Player Two architecture is now built earlier than planned.** The v17
   dojo-loop reshape committed Hajime to building Player Two's psychology layer
   (immediate needs + long-term goals + emergent goal evolution) as the
   student inner-lives mechanic in Ring 2. The relational/lineage data model
   is similarly Player-Two-shaped. By the time Player Two resumes, those
   architectures will already exist as working code. See *Relationship to
   Player Two* below.

5. **The decision protects future-Comrade from second-guessing.** When a weak
   moment arrives in November 2026 or July 2027 and the temptation is to feel
   behind schedule — the answer is here. The schedule was the wrong shape.
   The new schedule is the right shape. Build at the right pace.

---

## THE CORE LOOP

*Updated April 23, 2026. The April 13 framing put the match at center; the v17
dojo-loop reshape inverted it.*

You run a dojo. You set the weekly calendar — which sessions run, when, and
what each one contains. Procedurally generated students walk in at various
levels of commitment: some try a free week and disappear, some plateau at
yellow or green belt and stay for years, a few become champions. Inside each
session you choose where to spend your attention — watching one randori
match while four others run unwatched, or pulling a student aside for a
conversation that begins to reveal who they are. Your students have inner
lives — needs and goals — that you only learn about by spending time on them.
The dojo's culture emerges from your accumulated choices. The dojo's reputation
shapes who walks through the door next. And every so often, a tournament
arrives, and you sit in the chair beside the mat for the same Matte windows
you used to think the game was about.

That's the loop. The match engine that Ring 1 has been building is still real
and still load-bearing — but it lives inside the dojo loop now, not above it.
Most of a campaign is the dojo. The matches are the consequential events the
dojo produces.

---

## THE FIVE THESIS-LEVEL DESIGN PRINCIPLES

*Added April 23, 2026. Five organizing principles surfaced across the v17
dojo-loop work. Every system in the game traces back to at least one of these.
Naming them keeps future design decisions disciplined.*

### 1. Attention scarcity at every scale

The single most important mechanic. Originally identified as the Tournament
Attention Economy (three fighters, one chair); the v17 reshape generalized it
to every scale of the game. Inside a randori session, ten students on the mat
produce five sparring pairs and you can watch one. Across a week, fifteen
students need conversations and you have time for three. Across a season,
several students are ready for a tournament and you can only enter so many.
Attention is the universal scarce resource. Same primitive, different scales.

This is what makes coaching feel like coaching. Real coaches at every level
deal with this exact constraint. The mechanic captures something true about
the work.

### 2. The cultural feedback loop

Your accumulated choices produce a dojo with a character — chill, fun-for-kids,
companion-oriented, trial-by-fire. The character is emergent, not authored.
And the character then shapes who walks in. Trial-by-fire dojos attract
students looking for intensity. Fun kids' dojos attract families looking for
warmth. Your early choices cast a long shadow. The dojo you end up running
is downstream of the culture your first choices seeded.

This means there is no neutral move. Every decision is cultural input. The
six primary cultural inputs are listed in their own section below.

### 3. Continuous simulation, render on demand

Football Manager architecture. The simulation runs at a consistent base tick
rate; what changes with zoom level is how much of that simulation gets
rendered. Hour-by-hour session simulation when the player wants to watch a
specific moment; weekly or monthly time-lapse when the player wants to let the
calendar play. Events (injuries, quit notices, competitions, scheduled
milestones) pause the clock regardless of zoom. The match is always happening;
the player decides whether to watch each kick or just see the final score.

Hajime's match engine already IS the hour-by-hour zoom. The new work is the
calendar UI, the time-scaling controls, the aggregated-naturalistic-simulation
for zoomed-out views, and the event-pause infrastructure.

### 4. Compositional emergence

The big legible thing is built from small invisible events. A student's
"grip" stat at the top of the roster is emergent from thousands of atomic
exchanges in randori — a broken grip here, a successful strip there. A dojo's
culture is emergent from accumulated session content + pricing + promotion
decisions. A match's meaning is emergent from per-tick force application and
posture state. Nothing the player sees at the top is authored; everything is
the crystallization of lived simulation time.

This is the third system to express this pattern (Ring 1 physics; cultural
feedback; student stats), so it's worth naming. It's what makes the
simulation feel authentic — no number on the screen is a lie, because every
number traces back to events.

### 5. Either choice is okay

Major narrative events present binding decisions with no morally graded
answers. The game does not reward "correct" choices or penalize "wrong" ones —
it produces a *different* story from each choice. Inheritance Event: stay with
basement, take father's dojo. Succession at retirement: blood child, top
student. Push the reluctant fighter to compete, or honor their wishes. Both
paths are legitimate.

Disco Elysium / Citizen Sleeper / Wildermyth territory. Choices carry weight
because they reshape the story, not because they're evaluated.

---

## THE THREE ANCHORING SCENES

*The game must be able to produce these three scenes. If the systems can
produce them, the systems are right. If they can't, something is wrong. They
form an arc — match-level inside the loop, opening of the dojo arc, closing
of the dojo arc.*

### The Match Anchoring Scene — Tanaka vs. Sato

Existing scene. Still load-bearing. Drives Ring 1.

```
Round 1 · 0:00 — Tanaka (blue) vs. Sato (white)

0:03  Tanaka steps in. Right hand reaches for the lapel.
0:04  Sato's left hand intercepts — pistol grip on the sleeve.
0:06  Tanaka pulls — Sato's grip holds. Right grip strength -1.
0:09  Tanaka secures high collar. Deep grip.
0:11  Sato breaks posture forward, framing the bicep.
0:14  Grip battle. Both hands engaged. Tanaka's forearms fatiguing.
0:18  Tanaka attempts seoi-nage —
       → Sato sprawls. Hips back. Throw stuffed.
       → Slight scramble. Sato briefly exposes back.
       → ne-waza window: 11% — Tanaka does not commit.
       → Both stand. Grips reset.
0:22  Sato attacks o-uchi-gari — Tanaka's left leg absorbs.
0:24  Matte.
```

**[ Match paused — coach's chair ]**

```
TANAKA          status
─────────────────────────
Composure       7/10  ↓ (-1 from stuffed throw)
Right grip      5/10  ↓↓ (fatigued)
Left grip       8/10
Legs            8/10
Read speed      6/10
Trust in coach  9/10  ← high. He'll listen.

Height advantage over Sato: +5cm  ← moment arm favors seoi entry
Hip height differential: neutral  ← neither fighter has leverage edge yet

GRIP STATE (visible at coach IQ 7+):
  Tanaka R.hand →→ DEEP COLLAR →→ Sato L.lapel  (depth: 0.8) ✓
  Tanaka L.hand →→ SLEEVE GRIP →→ Sato R.sleeve (depth: 0.5) ⚠️ fatiguing
  Sato R.hand   →→ STANDARD    →→ Tanaka L.lapel (depth: 0.4)
  Sato L.hand   →→ PISTOL      →→ Tanaka R.sleeve (depth: 0.7) ← controlling

What you saw: He went for his strongest throw too early.
Sato read it. The grip fight is going against him on the right side.

→ Choose 2 instructions (max):

  A. Switch stance. Attack the left side.
  B. Break his grip first. Don't engage until you have yours.
  C. Stay patient. Let him come to you.
  D. Go to the ground if he opens up again.
  E. Tighten up. He's reading you.
  F. [Write your own — short phrase]
```

This is the Ring 1 north star. Everything in the match engine — grip graph,
position state machine, throw resolution, referee personality, the
Matte window — exists to make this scene work and to make matches like it
emerge from any pair of fighters.

### The Opening Anchoring Scene — The Twins Arrive

Within the first month of a new dojo. Two boys walk in together — twin
brothers, maybe twelve, excited in a way that can't be faked. They saw the
small directory plate by the basement door and the family name on it, and
they ran home and asked their father, and their father said *yes, that's the
son. His father trained mine, decades ago, before I was anyone.* And so they
came to check.

The recognition lands. The sensei's father's name is real to them. They want
to be like *their* father, the way their father wanted to be like the sensei's
father. They want to become champions.

They sign up that day, both of them. The first two students whose presence in
the dojo is owed not to a flyer or a price point but to a story carried across
generations. The cultural feedback loop's opening iteration: reputation
preceded reality. The lineage is felt history now, not a stat.

This scene drives Ring 2's recognition-walk-in mechanic, the father's-style
seed (the cultural DNA the player chose at character creation), and the
hidden-needs/goals layer (the twins arrive with a stated long-term goal — *be
like our father, become champions* — which the player gets for free as the
opening scene's gift, and which can evolve over years of play).

### The Closing Anchoring Scene — The Twins as Disciples

Years later. Both brothers earned their black belts under you. Neither left.
Neither plateaued. Neither chose a different dojo when they had the chance.
They stayed. They competed. They won enough. They lost enough. They learned to
teach. And now they teach alongside you. Two of the lifecycle's terminal
states ("assistant") resolved for a pair of characters the player has known
since month one.

This is the happy ending, not the default outcome. Twins create a built-in
attention conflict — one will feel they're getting less of your time than the
other; one might plateau while the other advances; one might leave. Getting to
*both* of them as assistants is the payoff for managing the jealousy, the
pacing, the individual needs across years of in-game time. A game that can
produce this scene has every supporting system working: match engine, lifecycle,
needs/goals, cultural feedback, attention scarcity, calendar, session
composition, conversation, retention, promotion philosophy.

This is a valid design north star because it cannot be produced with a
shortcut. The arc is the architecture working.

---

## THE NORTH STAR — DESIGN BY STORY

*The working principle of the project.*

Tarn Adams described his design philosophy for Dwarf Fortress as: write the
stories you want the game to produce, then design the systems that produce
them. Narrative-first design.

Hajime is built the same way. The three Anchoring Scenes above are not
mockups. They are stories the designer wants to read. The grip graph exists
because the Tanaka-Sato scene needs a grip graph to be legible. The
recognition-walk-in mechanic exists because the twins-arrive scene needs the
father's name to be real. The full lifecycle and conversation mechanic exist
because the twins-as-disciples scene needs years of accumulated knowledge of
those two specific kids to feel earned.

Every architectural decision in this document traces back to a scene the
designer wanted to be able to witness.

**The discipline going forward:**

1. Write a scene. Concrete. A specific match, a specific training session, a
   specific coaching moment.
2. Identify what systems would be required to produce it.
3. Build the smallest version of those systems that lets the scene happen.
4. Run the simulation. See if the scene emerges. If it doesn't, refine.
5. Write the next scene. Build what it needs.

When in doubt about what to build next, do not look at the ring roadmap. Look
at the scenes. Write one that excites you. Ask: "What systems does this scene
require?" Build those.

The game is not a feature pile. The game is the collection of stories it can
produce.

---

## THE PHYSICS PRINCIPLE

*Added April 14, 2026. Drives Ring 1.*

Two judoka walk onto the mat. They have never met before — not as people, and
not as bodies. The height differential, the arm reach, the hip geometry, the
weight distribution — these specific numbers have never been in this specific
combination before.

That is what makes every match unrepeatable.

Not random numbers. **Combinatorial physics.**

A throw that wins one match loses the next — not because of luck, but because
of geometry. The same seoi-nage that Tanaka lands on a 178cm opponent fails
against a 165cm fighter who gets *under* his entry. The physics changes. The
prose reflects the physics. The moments that get marked are the moments the
physics resolves something unexpected.

This is the difference between an arcade simulation and *the* simulation. It
is also what creates the game's skill ceiling: a casual player sees that
Tanaka is strong on the right side; an advanced player sees that his moment
arm advantage disappears against anyone under 172cm, and recruits accordingly.

Five core physical variables (full spec in `biomechanics.md`):
1. Height & limb length — moment arm advantage on hip throws
2. Arm reach — grip control radius
3. Hip height & hip-to-shoulder ratio — kuzushi geometry, throw entry cost
4. Weight distribution — which directions are exploitable
5. Body type (mass & density) — inertia, recovery rate

These live in the Identity layer. They are who the judoka IS. They shape every
calculation in every ring.

---

## THE GRIP GRAPH

*Added April 14, 2026. Drives Ring 1. Full spec in `grip-graph.md`.*

A judo match is not two fighters with stat sheets — it is a relational state
between two bodies. The grip graph models this state explicitly as a
bipartite graph: each active grip is a typed edge connecting one fighter's
grasping body part to one location on the other fighter's gi or body, with
metadata for grip type, depth, strength, and how long it's been held.

Both fighters can have multiple edges into each other simultaneously. Edges
form at engagement, contest each tick, slip or break under fatigue, and persist
or transform across position transitions. Architecture borrowed directly from
Dwarf Fortress's grapple system.

What the graph enables:

- **Throws gated on real prerequisites.** No throw fires without the edges to
  support it. Seoi-nage requires a deep collar grip; without one, the fighter
  can't launch it (or force-attempts at massive penalty — the desperate, sloppy
  attempt that earns shido).
- **Ne-waza becomes structural, not abstract.** Chokes, joint locks, and pins
  all read from the graph. Multi-turn commitment chains operate on it.
- **The Matte panel renders the graph.** Coach IQ gates how much of the graph
  is visible: a novice coach sees position and qualitative fatigue; an elite
  coach sees numeric depth values and the opponent's fatigue distribution per
  body part.
- **The prose engine has specificity to draw on.** "Tanaka's right hand still
  on the collar" maps to a specific GripEdge. "Sato strips the sleeve grip"
  maps to a specific edge transitioning to FAILURE.

The grip graph is the foundation of Ring 1. Every other system reads from it
or writes to it.

---

## THE GRIP SUB-LOOP

*Added April 14, 2026. Drives Ring 1. Full spec in `grip-sub-loop.md`.*

Underneath the Matte cycle and the tick heartbeat, a third rhythm runs
continuously: the Grip Sub-Loop. Two fighters engage, contest for grip
dominance, and the micro-exchange resolves in one of three ways — a kuzushi
window opens, a stifled reset breaks them apart, or a fighter commits to a
throw attempt. Dozens of sub-loop cycles occur between any two Matte calls.

**Three outcomes, not two.** Most judo games model throws as binary:
attempted/not attempted. Hajime models the space between throws as active,
contested, and resolution-bearing. Most of a real match's time — and most of
where matches are actually decided — lives inside this sub-loop.

**The coach is not always involved.** A match can end inside a single sub-loop
cycle. A fighter who wins the opening grip war decisively, opens a kuzushi
window at tick 12, and lands seoi-nage for ippon has ended the match before
the referee called Matte. The coach never spoke. This is not a failure mode —
it's one of the most beautiful outcomes in real judo.

The lesson the sub-loop teaches: **preparation is the primary lever, not
intervention.** Over a career, good coaching is distributed across training,
not chair-time. The dojo loop (Ring 2) is where most coaching actually happens.

---

## THE TWO PLAY MODES

*Added April 23, 2026. Resolves how the game is structured at the campaign
level. Confirmed in v17.*

Hajime ships with two play modes, structured around a primary/secondary split:

### Career Mode — the EA entry point

Primary mode at Early Access. Closer to **Wildermyth** than to Dwarf Fortress.
The player lives a defined sensei's life — basement-dojo opening, through
decades of career, with recurring Anchoring-Scene-weight narrative events that
shape the story's direction. Same systems underneath the simulation, but the
Narrative Event Framework (Ring 3) is *on*, scripting the spine of the
campaign.

The opening is fixed: basement dojo, twins arrive, antagonist begins watching.
The middle has shape: Inheritance Event around year 2, First Team Tournament
shortly after, Antagonist's Fall (or rise), optional Marriage / Children arcs,
recurring "two rising stars same weight class" dilemmas. The closing is
defined: Retirement and Succession — the sensei chooses who inherits the dojo.
Most of a career run is the systemic dojo loop; a handful of moments per
in-game year are scripted narrative events.

Either-choice-is-okay applies throughout. There is no "good" or "bad" path —
each branch produces a different campaign.

### Sandbox Mode — post-EA, emergent

Closer to Dwarf Fortress. Open-ended simulation with the Narrative Event
Framework *off*. The player drops into a procedurally generated dojo (or
inherits a previous run's dojo via the successor-start variant) in a
procedurally generated world. No scripted events. Pure emergence. Whatever
story the simulation produces is the story.

Sandbox Mode ships post-EA, deeper into the 2.0 horizon. Career Mode is the
EA face of the game; Sandbox is the long tail.

### Why the split exists

Career Mode is *your sensei's story*, with a defined opening and inevitable
middle moments. Sandbox Mode is *a sensei in a simulated world*, where
emergence is the storyteller. Hajime serves both; the split lets each mode
do what it does best.

Architecturally, the systems are shared. The Narrative Event Framework is one
toggle on top of the simulation. This means every system built for Ring 1 and
Ring 2 serves both modes — no double-building.

---

## THE SIMULATION RINGS

*Reshaped April 23, 2026. The original Ring 2/3/4 split was built before the
v17 dojo-loop reshape revealed the real shape. New ring structure below.
Concentric layers, inner rings get built first. Physics, grip graph, sub-loop,
the dojo loop, lineage data, and narrative events build up in this order.*

### Ring 1 — The Match Engine

**Status: Phase 1 ✅ done, Phase 2 ✅ done, Phase 3 calibration in progress
(Session 4 just shipped, post-Session 4 QA active).**

Tick-driven simulation of two judoka grappling on a relational state graph.
The grip sub-loop runs continuously, producing kuzushi windows, stifled
resets, and throw attempts. Throw resolution computes landing geometry
(angle, impact, control) which the referee personality reads to award scores.
Stuffed throws can open ne-waza windows. The Referee class governs Matte
calls and shido escalation.

The grip-as-cause architectural shift is the active refactor — pulls are
becoming the cause of throws via emitted kuzushi events, replacing the
grip-as-gate model. Driven by `grip-as-cause.md`. Pending tickets and bugs
should be evaluated through this lens before implementation.

Match-end logic gaps surfaced by the HAJ-68 audit (golden score, direct
hansoku-make, time-expiration event) will land as Ring 1 polish tickets in
the new Linear structure.

Ring 1 also produces the *unattended-match* path that Ring 2 needs for
background simulation. When the sensei watches one randori pair, the other
four pairs run the unattended path silently — same simulation, no prose
output, coarse improvement deltas only. Building the unattended path now
pays forward.

### Ring 2 — The Dojo Loop

**Status: Not yet started. The largest and most consequential ring.
Substantially expanded from the original April 13 framing.**

This is the new center of gravity for the project. Originally three slim
sections (Coach Instructions, Tournament Attention, Dojo Training); the v17
reshape revealed the dojo loop is the actual game. Ring 2 now contains:

- **Calendar as primary surface.** Weekly schedule, session blocks, attendance
  patterns. Sessions cost money and capacity.
- **Session composition.** Each session is an ordered sequence of activity
  blocks (warm-up, technique drilling, randori, ne-waza, conditioning, kata,
  competition prep). Starting library of ~10 activity types, growing toward
  15–20 by Early Access.
- **Roster as second primary surface.** Notepad (early game, ~10 students,
  handwritten margin notes) → computer (Football Manager-style spreadsheet,
  unlocked as facility upgrade). The roster is where attachment accumulates
  mechanically. Visibility layer — fields fill in only as conversations
  uncover them.
- **Watched session as third primary surface.** Inside any session, attention
  scarcity operates: the sensei can watch one randori pair (full Ring 1
  rendering) while others run unattended. Conversations are an alternative
  attention spend during a session — pull a student aside, unlock visibility
  on one of their needs or goals.
- **Student lifecycle.** Procedural generation, trial week, paying student,
  belt advances, plateau, departure, late-game terminal states (assistant,
  starts own dojo, joins competition circuit, leads seminars). Quit
  probability has a floor — some students always leave, regardless of effort.
- **Hidden inner lives.** Each student has 1–3 immediate needs and one
  long-term goal, hidden by default, revealed through conversation.
  Goals evolve over months/years of in-game time based on accumulated
  experience. Direct lift from Player Two's psychology architecture, arriving
  earlier than planned.
- **The antagonist.** A specific named recurring NPC — the slimy suit who buys
  failing dojos and converts them into predatory Taekwondo kids' mills.
  Appears when savings drop below threshold. State machine: not-yet-met →
  visited-once → escalating → offering → buys-you-out / backs-off. Eventually
  acquires his own judo dojo (via the Inheritance Event in Ring 3) and
  becomes the first rival dojo on the circuit.
- **Pricing as demographic lever.** Base subscription, group/family discounts,
  belt-level discounts, mat fees. Price choice biases who walks in (high
  prices → status-conscious; low + group → families and kids; etc.). Engageable
  light (mid-range default) or deep (precise demographic targeting).
- **Six cultural inputs.** See *The Six Cultural Inputs* below.
- **Lineage data captured from day one.** Every student, every dojo, every
  sensei carries lineage fields. Full multi-dojo simulation is 2.0; the data
  model commits to the architecture in 1.0 so 2.0 isn't a migration project.
  See `lineage-system.md`.
- **Word-of-mouth reputation.** No reputation meter. Reputation propagates
  silently through procedural generation of new arrivals and through narrative
  surfacing (former students appearing at competitions in rival colors).
- **Facility progression.** Mat space (start with 2 simultaneous randori pairs,
  expand up to 5), weight room, mini sauna, eventual move out of basement.
  Each upgrade is a culture signal AND a capacity unlock.
- **Sponsorships.** Late-early-game unlock for sustaining talented students
  whose families can't pay. The thematic core: who deserves more vs who pays
  more — Hajime explicitly separates them.

All of the above is specified in `dojo-as-institution.md` (expanded version
incoming after the master doc rewrite).

### Ring 3 — The Narrative Event Framework

**Status: Not yet started. Sits on top of Ring 2, shapes Career Mode.**

The scripted-event spine of Career Mode. Each event is an Anchoring-Scene-
weight moment with multi-factor triggers (time elapsed, economic state, roster
state, prior-event history) and meaningful branches. Either-choice-is-okay
applies. Events ship incrementally — the EA library is 5–8 major events;
the post-EA library grows toward the full career arc.

Confirmed events:
- **Twins Arrive** (opening, fires within first month)
- **First Team Tournament** (mid-early game, against the antagonist's dojo)
- **The Inheritance Event** (~year 2, father offers his established dojo,
  player chooses; antagonist takes whichever the player doesn't)
- **The Antagonist's Fall** (mid-late game, if you've beaten him enough)
- **Marriage / Partner** (optional mid-campaign)
- **Children** (optional, may include twins as recursion)
- **Olympics Run** (late-career, a student qualifies)
- **Two Rising Stars Same Weight Class** (recurring structural dilemma)
- **Retirement & Succession** (closing, choose your successor)

Full spec lands in `career-mode-and-narrative-events.md`.

Ring 3 is also where the lineage system's *narrative* features live for 1.0
(succession choice, legacy screen, successor-start variant). The lineage
*data* is captured in Ring 2; Ring 3 surfaces it as story.

### Ring 4 — Sandbox Mode + Multi-Dojo World Simulation

**Status: 2.0 horizon. Out of EA scope.**

The full ambition. Every ranked judoka in the world simulated as a real
entity — named, nationality'd, trained somewhere, climbing or stalling on
the rankings ladder. Rival dojos run as parallel simulations alongside the
player's. Cross-dojo relationships persist and evolve. The web of dojos
becomes a living structure the player can explore — pin (Crusader-Kings-style)
any judoka and watch their career.

Sandbox Mode is the configuration that exposes this: drop into a procgen
dojo in a procgen world, no scripted events, watch what emerges across
generations.

Architecturally, Ring 4 is the 2.0 expansion of Ring 2's lineage data into
real continuous simulation. Same data model, deeper computation. The 1.0
lineage architecture is built specifically so 2.0 is a simulation layer
addition, not a data migration.

### Ring 5 — The 2D Visual Layer

**Status: Post-EA polish. Pixel-art figures, stripe-based grip indicators,
Kairosoft-style top-down dojo view.** Always paired with the prose log, never
replacing it.

Visual rendering of the grip graph (each edge as a visible stripe of varying
thickness/opacity). Dojo facility view (mats, weight room, sauna). Tournament
venue rendering. Calendar visualization that goes beyond the spreadsheet.
Symbols that change state, not animation frames.

### Ring 6 — Sound

**Status: Post-EA polish.** Dojo ambient theme, match tension layers responsive
to score and fatigue, signature motif when one of *your* judoka enters their
finals, audio language for graph state changes (different cue when a
controlling grip breaks vs when a deep grip secures). Built when the world
is ready to hold it.

---

## THE SIX CULTURAL INPUTS

*Added April 23, 2026. The mechanisms by which the dojo's culture emerges.
Drives the cultural feedback loop principle. Each input is a real player
decision with cumulative cultural weight.*

1. **Session content.** What you drill, week after week. A dojo that runs 30
   minutes of randori per session has a different feel than one that runs 30
   minutes of instruction. A dojo that drills O-Soto entries specifically is
   biasing students toward a particular style. Session content is the primary
   mechanism by which dojo culture gets built into student capability.

2. **Pricing.** High prices attract status-conscious committed students; low
   prices flood the room with kids and casual attendance; group plans build a
   family-social dojo; belt discounts retain advanced talent. Price choice
   shapes who walks through the door.

3. **Father's-style lineage.** The cultural DNA you started with. The style
   you chose at character creation seeds the dojo's initial reputation,
   biases which kinds of students are first attracted (family friends, old
   students of the father, judoka who recognize the name), and determines
   what the sensei teaches well. The starting cultural seed.

4. **Atmospheric choice.** Within a session, what the air feels like — game-
   based vs competitive, relaxed vs strict, collaborative vs trial-by-fire.
   The coach isn't manipulating student goals directly; they're shaping the
   environment that shapes the students. Students whose needs happen to align
   with the atmosphere thrive; others drift.

5. **Promotion philosophy.** "Compete to earn it" vs "time and discipline" vs
   "rigorous gatekeeping." The pattern of the player's belt-promotion decisions
   becomes a reputation signal across many students. *This dojo is where you
   actually have to earn it.*

6. **Competition readiness pattern.** Every student has an opinion about
   competing. The sensei can accept their preference, push them toward
   competing when they're reluctant, or hold them back when they want to go.
   The accumulated pattern reveals what the dojo is for: a "push everyone in"
   dojo produces one kind of student; a "wait until they're ready" dojo
   produces another.

The six inputs are not independent. A high-pricing trial-by-fire push-everyone-
into-tournaments rigorous-gatekeeping dojo is internally coherent. So is a
low-pricing companion-oriented wait-until-they're-ready dojo. Mixed signals
produce mixed results — and a dojo that hasn't settled on its culture
struggles to attract students of any kind.

---

## THE OPTIONAL MODE: PLAY-AS-JUDOKA

*Captured April 14, 2026. Repositioned April 23, 2026 as a 2.0+ direction
that the architecture must not foreclose. Sketch in `play-as-judoka-mode.md`.*

Coaching is the soul of Hajime. But the grip graph architecture also opens the
door to a separate mode where the player controls a judoka directly — the
same way DF's Adventure Mode lets you wrestle with explicit control over which
body part grabs which target.

In play-as-judoka mode, the grip graph IS the chess board. You see the live
edges. You choose which grasper goes for which target. You commit to throw
entries. You roll counter-actions in ne-waza. The action choices flow from the
visible graph state.

This could be:
- Single-player vs. AI
- Multiplayer (turn-based or real-time) where two players grapple through
  the same graph — a chess match of attacks, counters, and 5-moves-ahead
  planning

Architecturally requires Ring 1 (grip graph + ne-waza) to be solid, which the
EA work delivers. Out of scope until post-2.0. Discipline: don't build for
it; don't promise it; don't lose it.

---

## THE SKILL CEILING

*This is what separates Hajime from other sports sims. Updated April 23, 2026
to include dojo-loop depth.*

**Casual player, match-engine experience:**
- Tanaka is strong on the right side
- His seoi-nage works well
- He's getting tired in round two
- The ref is calling Matte quickly — should probably reset

**Advanced player, match-engine experience:**
- Tanaka's moment arm advantage disappears against anyone under 172cm —
  recruit opponents he can look down at
- His hip drop speed is the bottleneck, not his grip strength — train the
  mirror drills first
- The fatigue curve on his right forearm hits the threshold around tick 180 —
  build the game plan around early ippon, not attrition
- This ref has low stuffed_throw_tolerance and high match_energy_read —
  instruct conservative early
- His training lineage is 100% Classical Kodokan; under a Georgian-voiced
  coach in the chair, reception efficiency drops — train him into the dojo's
  voice or accept the penalty
- His preferred grip configuration is HIGH_COLLAR with sleeve — against a
  southpaw, the mirrored stance puts his right hand on the wrong side and
  his engagement edge formation drops 30%

**Casual player, dojo-loop experience:**
- Marco is improving on grip
- The new student wants to compete
- Savings are getting low — should run more classes
- The roster has too many gaps to fill in — better just trust the schedule

**Advanced player, dojo-loop experience:**
- Marco's grip is improving but only against light resistance partners — pair
  him with Sato in randori to expose him to a real grip war
- The new student wants to compete but their long-term goal (uncovered in
  three conversations) is "make dad happy" — pushing them into a tournament
  too early risks the goal evolution that turns them into a real competitor
- Savings are getting low because the kids' class roster has churned;
  running more classes won't help if the demographic isn't matched to the
  current schedule slots — drop the Saturday morning slot, add a Tuesday
  evening for the working-adult demographic
- Three students are crossing into yellow-belt threshold this week. Promoting
  all three reinforces the "fast cadence" reputation the dojo is becoming
  known for; holding back even one shifts the perception

Same simulation. Different depths of reading. Neither player is wrong. The
game rewards depth if you go looking for it.

The dojo loop has its own skill ceiling layered on top of the match engine's.
Together, they produce a game that can be enjoyed lightly across many runs
and studied deeply across one.

---

## THE INSTRUCTION TAXONOMY

*Initial set. Will grow with playtesting. Seven categories drawn from the
research doc `coaching-bible.md`.*

**Score / Time status** — You're up. Shido him. Two minutes. One minute.

**Grip-focused** — Break his grip first. Get the dominant grip before you
commit. Switch stance — attack the other side. Stop reaching with your tired
hand. Strip his pistol grip.

**Tempo-focused** — Stay patient. Let him come to you. Push the pace. Tire
him out. Slow it down. Reset. Attack on his next breath.

**Technique** — Seoi. Uchi-mata. Tokui-waza (your best). Ko-uchi first, then
seoi.

**Tactical** — Go to the ground if he opens up. Stay standing — he's better
on the mat. Attack his weak leg. Counter, don't initiate.

**Composure / Defensive** — Tighten up. He's reading you. Head up. Posture.
Block. Don't let him turn in. Breathe. You have time.

**Motivational / Risk** — Take the chance. Go for ippon. Play for shidos.
He'll panic. Defensive grip. Run the clock.

**Physics-aware** — Use your height. Make him reach up. Get lower than him.
Take away his entry. He can't sustain that grip. Wait him out. His left side
is weaker. Circle that direction.

---

## TONE RULES

**The voice of the match log is a knowledgeable sportswriter.** Specific.
Calm. Loves the sport. Doesn't explain what kuzushi is — assumes the reader
is paying attention or willing to learn. Neil Adams commentary register —
quiet, diagnostic, annotating deltas.

**The voice of the coach window is intimate.** It's the player's view of their
fighter. Quiet, focused, slightly worried. Physics-aware without being
clinical — *"His entry window is closing"* not *"moment arm modifier is below
threshold."*

**The voice of the dojo is warm.** This is home. This is where the work
happens. The dojo prose has the texture of routine — sweat, repetition, small
jokes, the smell of the mats. The notepad-stage roster is handwritten;
margin notes feel like a real sensei's real notes, not like a game surfacing
information.

**No hype. No announcer voice.** Hajime is not the UFC. It is judo — a sport
with deep roots, formal etiquette, and an understated culture. The writing
respects that.

**Every fighter is treated with dignity. Including the opponents. Including
the ones who lose. Especially the ones who lose.**

**Physics resolves; prose marks.** The simulation never announces the physics.
When a smaller fighter lifts a heavier one, the log doesn't say "moment arm
calculation succeeded." It says something that earns the moment.

**The graph is the source of specificity.** "Tanaka's right hand still on the
collar" maps to a specific GripEdge. "Sato strips the sleeve grip" maps to a
specific edge transitioning to FAILURE. The prose names what the graph has
just done.

**The grip sub-loop runs silently most of the time.** Stifled resets early in
a match are not narrated. The log gets denser as fatigue develops and the
sub-loop starts resolving things that matter.

**The dojo prose has its own register.** Different from match prose, different
from coach-window prose. Weekly roundups feel like the sensei sitting down
on a Sunday evening with the notepad. Conversations during sessions feel like
the moment they are — pulled aside, the rest of the room going on without
you.

---

## OPEN QUESTIONS

*Most pre-v17 questions answered. Remaining open work is the v17 sub-question
triage list (lifecycle, economic antagonist cadence, opening scenario tuning,
session composition, culture & psychology, rankings, Inheritance Event
specifics, Career Mode, lineage). Full open-question list lives in
`dojo-loop-design-questions-v17.md`. Top-level architectural questions worth
preserving here:*

**Q1: How real-time is the watched-match path?** Live-scrolling log with
player-controlled speed seems right for the match engine. Worth playtesting
with the dojo loop's zoom-level controls layered on top.

**Q2: How many students in a starting roster?** Trial-week walk-ins arrive
on a procedural cadence. Active enrolled count probably grows from 0 → 5–10
across the first in-game year, ceiling around 15–25 mid-game, larger for
established late-game dojos. Calibration target.

**Q3: How long is a "campaign"?** A complete Career Mode run spans 10–15
in-game years minimum to let the twins arc complete. Roughly one in-game
year per 20–60 minutes of real playtime, varying with zoom. Total: probably
10–30 hours of real time per campaign. Multiple campaigns possible.

**Q4: How does a non-judoka learn the sport through play?** Glossary tooltips
on every term. Hover "ko-uchi-gari" → see a one-line description and a tiny
diagram. Hover any GripEdge → see what that grip type is and what throws it
enables. Tutorial mode optional — for many players the basement-dojo opening
should be self-explanatory through play.

**Q5: AI prose generation for matches and dojo events?** Same architectural
question as Player Two. Build deterministic prose templates first as fallback;
layer Claude-in-Claude generation on top once the system works. The grip
graph and the rich dojo-state make Claude-generated prose dramatically more
grounded.

**Q6: How granular does the physics get in Ring 1?** Five variables specified.
Phase 3 calibration is tuning what we have. Adding more variables is post-EA
unless calibration reveals one is needed for the EA scene library.

**Q7: How does the advanced player *see* the dojo state?** The roster
(notepad → computer) is the primary surface. The weekly roundup is the
secondary surface. The session-watching mechanism is the tertiary surface.
All three layered with the visibility (hidden-info) principle.

**Q8: When does play-as-judoka mode get scoped?** Not until 2.0. The sketch
preserves the idea; the discipline holds.

---

## PROJECT ARCHITECTURE

*Sessions roll up into phases. Phases roll up into rings. Rings roll up into
the game. Each layer is a committable, reviewable unit. Ring 1 is mostly
done; Ring 2 is the next major build target.*

**Ring 1 — Match Engine**
- Phase 1 — Skeleton ✅ April 13, 2026
- Phase 2 — Real Combat + Grip Graph + Ne-Waza + Referee
  - Session 1 ✅ April 14, 2026 (throw resolution, scoring, fatigue, match-end)
  - Session 2 ✅ April 15, 2026 (grip graph, position machine, ne-waza, Referee)
  - Session 3 ✅ April 17, 2026 (physics substrate design, Mode B)
  - Session 4 ✅ April 22, 2026 (worked throws, four-dim signature, compromised states)
  - HAJ-20 / 35 / 36 ✅ April 21, 2026 (debug overlay, defensive desperation, grip-presence gate)
  - HAJ-31 through HAJ-34 ✅ Session 4 QA hotfixes (white-belt grip flow, log event order, oscillation suppression)
- Phase 3 — Calibration (current)
  - Watching matches at scale, tuning thresholds
  - HAJ-68 audit gaps land here (golden score, direct hansoku-make,
    time-expiration event)
  - Grip-as-cause refactor (the big architectural shift) lands here
  - Session 5 next (queued)

**Ring 2 — The Dojo Loop**
- Not yet started. Multiple phases ahead.
- Will likely break into: Phase 1 Foundation (calendar, roster notepad,
  basement opening), Phase 2 Sessions (session composition + watched-randori
  inside calendar), Phase 3 Inner Lives (conversations + visibility +
  needs/goals), Phase 4 Lifecycle + Economy (full lifecycle, antagonist,
  pricing), Phase 5 Cultural Inputs (six inputs functional + reputation
  propagation), Phase 6 Lineage Data (data model commitment for 1.0).
- Phase ordering and session breakdown to be detailed in
  `dojo-as-institution.md` after master doc rewrite.

**Ring 3 — Narrative Event Framework**
- Not yet started. Sits on top of Ring 2.
- Phase 1: Event triggering/sequencing infrastructure + first event (Twins
  Arrive opening).
- Phase 2: Inheritance Event + dojo-switching support.
- Phase 3: First Team Tournament + Antagonist arc events.
- Phase 4+: Marriage/Children/Olympics/Succession events.

**Ring 4 — Sandbox Mode + Multi-Dojo Simulation**
- 2.0 horizon. Out of EA scope. Architecture committed via lineage data
  in Ring 2.

**Ring 5 — Visual Layer / Ring 6 — Sound**
- Post-EA polish.

---

## THE SHIPPING PLAN

*Replaces the April 13 Scenario A/B/C framing. Drops the January 9, 2027 hard
ship date. Adds the 2–3 year horizon to Early Access.*

### What changed

The April 13 plan assumed the game could ship as Early Access on January 9,
2027. That plan was built before the v17 dojo-loop reshape. The reshape
revealed that what makes Hajime *Hajime* is not the match engine alone — it's
the multi-year dojo loop with attached match engine. The match engine is
nine months of work; the dojo loop with all its supporting architecture is
substantially more.

The scope of the design that emerged from v17 exceeds what any solo dev
ships in nine months. Forcing a January 9, 2027 release would mean shipping
something that isn't yet the game. The new plan accepts that and reshapes
the calendar.

### The new horizon

**Early Access target: mid-2028 to mid-2029.** A 2–3 year arc from now.
Specifically determined by the rate at which Ring 2 (the dojo loop) and
Ring 3 (narrative events) come together. Calendar-quartered detail sits in
ongoing chat work, not in this doc — the master doc commits to the horizon,
not to specific quarter-by-quarter milestones.

### January 9, 2027 — Personal Checkpoint

The original ship date is preserved as an internal checkpoint. The rule:
*further than where I began.* By Comrade's birthday in 2027, the project
should have visibly progressed past where it is now in a way that justifies
the year's work. A working basement-dojo opening with the twins arriving, a
calendar, a roster, watched randori, the conversation mechanic, the
antagonist visiting once, three students moving through the beginning of
their lifecycles. Not public, not for sale. A working slice of the game that
proves the loop is real.

This is achievable in ~9 months from now if Ring 1 calibration finishes by
end of June 2026 and Ring 2 Phase 1 (calendar + roster + basement opening)
is the second half of 2026. It is *not* achievable as a polished public
release. The checkpoint reframe keeps the date emotionally meaningful
without forcing the project to bend around it.

### What ships at Early Access

- **Career Mode as the entry point.** The dojo loop with all six cultural
  inputs functional. Calendar, sessions (15–20 activity types), roster
  (notepad → computer transition), conversations with hidden-info layer,
  lifecycle with quit floor, antagonist with full state machine and arc,
  pricing as demographic lever, lineage data fully captured.
- **Ring 1 polished.** All calibration debt paid. Grip-as-cause refactor
  complete. HAJ-68 gaps closed. Both ne-waza and tachi-waza feel like real
  judo at the four-minute scale.
- **Narrative Event Framework with 5–8 major events.** Twins Arrive,
  Inheritance Event, First Team Tournament, Antagonist's Fall (or evolution),
  one or two recurring "two rising stars" dilemmas, optional Marriage arc.
  Late-career arcs (Children, Olympics, Succession) ship in EA updates
  through 2028–2029.
- **Content.** Hand-built starting roster pool of 30–50 procgen seeds across
  several cultural styles. Three or four dojo opening configurations
  (basement city A, basement city B, suburb, Japan-village). Tournament
  generator at local + state tier with national gestured at narratively.
- **Prose templates.** ~80% coverage of common events. Multiple stress
  registers (warm when calm, flat when tired). Cultural flavoring in coach
  voices.
- **Visual layer.** Pixel-art top-down dojo + match views. Visible grip
  indicators. Stat panel rendering the filtered grip graph. Dojo facility
  scene that grows with upgrades.
- **Sound.** Ambient dojo theme, match tension layers, signature motif for
  *your* finalists.

### What does NOT ship at Early Access

- Sandbox Mode (Ring 4 — 2.0)
- Full multi-dojo world simulation (Ring 4 — 2.0)
- Play-as-judoka mode (post-2.0)
- Late-career narrative arcs in full depth (ship through 2028–2029 EA updates)
- Olympics simulated as a real event (narrative-layer endpoint at 1.0)

### Working principles for the 2–3 year build

- **Build by ring.** Ring 1 first (almost done). Ring 2 next. Ring 3 on top
  of Ring 2. Don't skip ahead.
- **Build by phase, ship by ring.** Each phase is a committable slice. The
  ring isn't done until all its phases ship and the calibration debt is paid.
- **Build to scenes.** When unsure what to build next, return to the
  Anchoring Scenes. Build what they need.
- **Calibrate continuously.** Don't accumulate calibration debt across ring
  boundaries. Phase 3 calibration of Ring 1 happens before Ring 2 Phase 1
  begins.
- **Cultural layer hooks stay modular.** Cranford-lineage implementation,
  sensei collaboration, deeper sensei-style content all stay optional and
  modular. Conversation about deeper involvement happens post-Ring 3.
- **Keep Player Two warm but closed.** Hajime gets all primary creative
  attention. Player Two ideas get noted in its repo and the chat returns
  to Hajime.

---

## DESIGN DOCUMENTS

*Living reference files. Read before building their corresponding ring.*

**Ring 1:**
- `data-model.md` — Judoka class spec (Identity / Capability / State).
- `grip-graph.md` — Bipartite state structure, edges, multi-turn chains, throw
  prerequisites, coach IQ visibility.
- `grip-sub-loop.md` — The continuous micro-cycle that drives the graph.
- `biomechanics.md` — Five physical variables and how they feed each ring.
- `physics-substrate.md` — Body state, force model, throw templates,
  compromised states, skill compression, counter-window state regions.
- `grip-as-cause.md` — The architectural shift from grip-as-gate to
  grip-as-cause. Active refactor target.

**Ring 2 (the dojo loop):**
- `dojo-as-institution.md` — *expanded version incoming after master doc rewrite.*
  Calendar, sessions, roster, conversations, lifecycle, antagonist, pricing,
  six cultural inputs, attendance signal, weekly roundup, facility progression,
  sponsorships.
- `cultural-layer.md` — 13 national styles as seeds, style_dna inheritance,
  seminars, school demographics, coach voice compatibility.
- `lineage-system.md` — *new doc.* Lineage data model from 1.0, succession,
  successor-start variant, legacy screen, 2.0 multi-dojo expansion path.
- `dojo-loop-design-questions-v17.md` — The triage doc from the v17 reshape.
  Open sub-questions live here until they're answered.

**Ring 3 (Career Mode events):**
- `career-mode-and-narrative-events.md` — *new doc.* Narrative Event Framework,
  event library, triggering/sequencing infrastructure, branch text patterns,
  either-choice-is-okay implementation, scope by EA vs post-EA.

**Future / parallel:**
- `play-as-judoka-mode.md` — 2.0+ direction. Don't build for; don't lose.

**Research / canonical references:**
- `The Chair, the Grip, and the Throw` (coaching bible) — National fighting
  styles, Matte window research, referee behavior, prose voice reference.
- `From Tissue Layers to Tatami` — Dwarf Fortress combat / grapple
  architecture and what translates to Hajime.
- `Judo Biomechanics for Simulation` — Kuzushi, couples, levers research.
- `Cranford five-video synthesis` — Sensei lineage video analysis. Modular
  hooks for post-Ring 3 deeper involvement.

---

## RELATIONSHIP TO PLAYER TWO

*Updated April 23, 2026. The April 15 framing was "Hajime earns the tools for
Player Two." The v17 dojo-loop reshape upgrades that to "Hajime is actively
building Player Two's psychology layer earlier than planned."*

Hajime remains the primary project through Early Access. Player Two remains
paused. The two projects are architecturally related, and Hajime's build now
*directly* advances Player Two — not just by skill transfer but by building
Player Two's architecture in advance.

### What Hajime is building that Player Two needs

**The psychology layer (immediate needs + long-term goals + emergent goal
evolution).** This was the single biggest architectural commitment Player Two
had ahead of it. v17's Q8 answer requires Hajime to build it in Ring 2 as the
student inner-lives mechanic. The structure (Dwarf-Fortress-style needs short
list + one current long-term goal + goal evolution based on accumulated
experience) IS the Player Two psychology layer. Marco starts with "make dad
happy" → his needs get met by the fun kids' class → his goal evolves to
"become a champion." That's the Player Two model. Hajime ships it first.

**The relational data model.** v17's Q15 answer commits Hajime to lineage-aware
data on every entity (sensei, dojo, student) from day one. The structure —
who-trained-whom, who-came-from-where, what-history-do-they-carry — is the
Player Two relational substrate (the boy's life thread intersects the
grandmother's, the grandmother's intersects the teacher's, etc.) at smaller
scope. Building it for Hajime first is building Player Two's data model.

**The hidden-information principle.** v17's Q9/Q11 answers establish
visibility-as-earned-information as a core Hajime mechanic — needs, goals,
preferences hidden by default, revealed through conversation. Player Two needs
the same thing for character interiority. Building it for Hajime is building
the Player Two visibility model.

**The continuous-simulation-with-zoom architecture.** v17's Q7 answer commits
Hajime to Football Manager-style time-scaling with event-pause infrastructure.
Player Two needs the exact same thing for life-scale simulation across years
and decades. Hajime builds the engine.

**The narrative-event-on-top-of-simulation pattern.** v17's Q14 answer
introduces the Narrative Event Framework — scripted scenes layered on top of
emergent simulation, branching with no morally graded answers. Player Two's
choice-prompt architecture is the same problem in a different context. Hajime
builds the framework.

### What changes about the resumption plan

When Player Two resumes (no specific date — when Hajime EA ships and the
horizon is clear), it will not be a from-scratch project. It will be a port of
Hajime's psychology, relational, visibility, simulation-zoom, and narrative-
event architectures into a different content domain (a human life across time,
rather than a dojo across generations). The scope of "build Player Two" drops
substantially. The scope of "design Player Two's content and prose" remains
what it always was.

### Working model

- Hajime has all primary creative attention through EA.
- Player Two's repo stays closed during Hajime sessions.
- Player Two's design documents remain valid and untouched.
- Ideas that arrive belonging to Player Two are noted in Player Two's repo
  as quick capture and the chat returns to Hajime.
- After Hajime EA, the resumption decision gets made deliberately. By that
  point, Player Two's hardest architectural problems will already be solved.

The April 15 decision protected future-Comrade from second-guessing the
priority. The April 23 reshape strengthens it: nine months on Hajime is no
longer "earning the tools." It is *actively building Player Two*. The ROI on
Hajime time has gone up.

---

## WHAT'S BEEN BUILT

**Ring 1 — Phase 1 Skeleton ✅** April 13, 2026.

**Ring 1 — Phase 2 Real Combat ✅** April 14–22, 2026.
- Session 1 (April 14): throw resolution, scoring, fatigue, match-end conditions.
- Session 2 (April 15): grip graph, position state machine, ne-waza door, Referee.
- Session 3 (April 17): physics substrate design (Mode B, design-only).
- Session 4 (April 22): worked throw templates, four-dimension signature,
  worked throw instances, failed-throw compromised states, skill-compression,
  counter-windows as state regions.
- HAJ-20 / 35 / 36 (April 21): debug overlay, defensive desperation,
  formal grip-presence commit gate.
- HAJ-31 through HAJ-34 (Session 4 QA): white-belt zero-grips hotfix,
  log event order canonicalization, counter outcome display, grip oscillation
  spam suppression. Four commits on main.

**Ring 1 — Phase 3 Calibration (in progress).**
- Session 5 queued.
- HAJ-68 audit completed (April 24): match-end logic gaps inventoried.
  Implemented: ippon end, two-waza-ari end, decision on unequal WA, third
  shido hansoku-make. Missing: golden-score transition on equal WA at time,
  direct hansoku-make for dangerous-technique/spirit violations, golden-score
  scoring win, golden-score third shido hansoku-make.
- Grip-as-cause architectural refactor pending (the big shift — pulls become
  the cause of throws via emitted kuzushi events).

**Design corpus.**
- `data-model.md` v0.4
- `grip-graph.md` v0.1
- `grip-sub-loop.md` v0.2
- `biomechanics.md` v0.1
- `physics-substrate.md` v0.1
- `cultural-layer.md` v0.1
- `dojo-as-institution.md` v0.2 (about to be expanded)
- `grip-as-cause.md` (active refactor target)
- `play-as-judoka-mode.md` v0.1
- `dojo-loop-design-questions-v17.md` (the triage doc)
- Coaching bible (research)
- Tissue layers (research)
- Cranford five-video synthesis
- Three Gemini prompt templates (QA, elite match, instructional)

**Tooling.**
- Linear for ticketing (HAJ- prefix, GitHub auto-close via commit magic words).
- Two-tier Gemini-assisted video analysis workflow for calibration ground
  truth and ticket synthesis.
- Debug overlay for live calibration observation.

---

## WHAT'S NEXT

Ordered by priority for the immediate cycle:

1. **Master doc rewrite** (this doc — current).

2. **Linear restructure.** New milestone/cycle/quarter framing for the 2–3
   year horizon. Reshape projects to reflect Ring 2 expansion. Triage HAJ-68
   gaps into tickets. Triage v17 sub-questions into design-work tickets.
   Proposal-first; full restructure on green light.

3. **`dojo-as-institution.md` expansion.** The v17 content lands here in
   structured form. Calendar, sessions, roster, conversations, lifecycle,
   antagonist, pricing, six cultural inputs, attendance signal, weekly
   roundup, facility progression, sponsorships.

4. **New design notes.**
   - `lineage-system.md` (lineage data model 1.0, succession, successor-start)
   - `career-mode-and-narrative-events.md` (Narrative Event Framework, event
     library, triggering/sequencing, branch patterns)

5. **`cultural-layer.md` light update.** Reference the six cultural inputs
   from `dojo-as-institution.md` rather than the older three-input framing.

6. **Design notes cleanup.** Sessions / plans / templates folder is getting
   crowded. Pass to consolidate, archive completed sessions, prune templates
   that have outlived their use.

7. **README rewrite** (eventually — after the doc layer settles).

8. **Session 5** (Ring 1 calibration work, queued).

9. **HAJ-68 gap implementation.** Golden score, direct hansoku-make,
   time-expiration event. Lands as Ring 1 Phase 3 work.

10. **Grip-as-cause refactor.** The big architectural shift in Ring 1.
    Plan and stage across multiple tickets per `grip-as-cause.md` §11.

---

*Document version: April 24, 2026. Substantial rewrite from the April 15
version. Reflects the v17 dojo-loop reshape, the new ring structure, the
shipping-plan reframe, and the upgraded relationship to Player Two. Update
after the next session that meaningfully changes scope or structure.*
