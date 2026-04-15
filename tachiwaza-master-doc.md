# TACHIWAZA — Master Design & Development Document
### A Living Brainstorm / Build Roadmap / Reference

*This document is a working artifact. Update it after every session.*

---

## THE CORE LOOP

You coach a stable of judoka. You train them in the dojo. You enter them in matches. You watch the matches simulate tick-by-tick as a stream of grip exchanges, fatigue events, throw attempts, scrambles, and ground transitions. When the referee calls Matte, the simulation pauses. You see your fighter's current state. You issue up to two short instructions. The simulation resumes — and how well your instructions land depends on the fighter's composure, fight IQ, fatigue, and trust in you. After the match, you return to the dojo and use what you learned to shape the next training cycle.

That's the loop. Everything else exists to make that loop deeper.

---

## THE ANCHORING SCENE

This is the scene the whole game is built around. When in doubt, return here.

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

The player picks B and D. The simulation resumes and Tanaka begins executing the new plan, biased by composure, fatigue, trust — and the physics of his body against Sato's.

This is the soul of the game. Everything in the rest of this document is in service of making this scene work.

---

## THE PHYSICS PRINCIPLE

*Added April 14, 2026.*

Two judoka walk onto the mat. They have never met before — not as people, and not as bodies. The height differential, the arm reach, the hip geometry, the weight distribution — these specific numbers have never been in this specific combination before.

**That is what makes every match unrepeatable.**

Not random numbers. Combinatorial physics.

A throw that wins one match loses the next — not because of luck, but because of geometry. The same seoi-nage that Tanaka lands on a 178cm opponent fails against a 165cm fighter who gets *under* his entry. The physics changes. The prose reflects the physics. The moments that get marked are the moments the physics resolves something unexpected.

This is the difference between an arcade simulation and *the* simulation. It is also what creates the game's skill ceiling: a casual player sees that Tanaka is strong on the right side; an advanced player sees that his moment arm advantage disappears against anyone under 172cm, and recruits accordingly.

**The five core physical variables** (fully described in `biomechanics.md`):
1. Height & limb length — moment arm advantage on hip throws
2. Arm reach — grip control radius, available configurations
3. Hip height & hip-to-shoulder ratio — kuzushi geometry, throw entry cost
4. Weight distribution — which directions are exploitable
5. Body type (mass & density) — inertia, power behind throws, recovery rate

These live in the Identity layer. They are who the judoka IS. They shape every calculation in every ring.

---

## THE GRIP GRAPH

*Added April 14, 2026 (Phase 2 Session 2). The bipartite state structure underneath every match. Full spec in `grip-graph.md`.*

The grip graph is the architectural piece that makes every other system in Tachiwaza work the way it should.

A judo match is not two fighters with stat sheets — it is a **relational state** between two bodies. Who is gripping what, with which hand, at what depth, with what strength, in which configuration. The grip graph models this state explicitly as a bipartite graph: each active grip is an edge connecting one fighter's grasping body part to one location on the other fighter's gi or body, with metadata for grip type, depth, strength, and how long it's been held.

Both fighters can have multiple edges into each other simultaneously. Edges form at engagement, contest each tick, slip or break under fatigue, and persist or transform across position transitions. The architecture is borrowed directly from Dwarf Fortress's grapple system, which models wrestling the same way — and which is the deepest combat model in gaming history.

**What the grip graph enables:**

- **Throws gated on real prerequisites.** A throw cannot be attempted unless the graph satisfies its requirements. No more throws-from-nothing. Seoi-nage requires a deep collar grip; without one, the fighter can't launch it. Or they can force-attempt with massive penalty (the desperate, sloppy attempt that earns shido).

- **Ne-waza becomes structural, not abstract.** Chokes, joint locks, and pins all read from the graph. A choke needs an edge on the neck (THROAT flag). An armbar needs edges on the wrist + elbow. A pin requires positional edges that prevent escape. Multi-turn commitment chains live on top of this — choke takes 3 ticks to set, the bottom fighter has counter-actions each tick, the contest is real.

- **The Matte panel renders the graph.** When the referee pauses, the coach sees the edges as legible state — who has dominant grip, who's contesting which sleeve, where the asymmetry is. Coach IQ gates how much of the graph is visible: a novice coach sees position and qualitative fatigue; an elite coach sees numeric depth values and the opponent's fatigue distribution per body part.

- **The prose engine has specificity to draw on.** "Tanaka's right hand still on the collar" is a specific GripEdge with grip_type=DEEP and depth>0.6. "Sato strips the sleeve grip" is a specific edge transitioning to FAILURE. Every sentence in the log traces back to a transition on the graph.

The grip graph is the foundation. Phase 2 Session 2 builds it. Every ring beyond Ring 1 reads from it or writes to it.

---

## THE GRIP SUB-LOOP

*Added April 14, 2026. The continuous mechanic that drives the graph forward. Full spec in `grip-sub-loop.md` v0.2.*

Underneath the Matte cycle and the tick heartbeat, a third rhythm runs continuously: the **Grip Sub-Loop**. Two fighters engage, contest for grip dominance, and the micro-exchange resolves in one of three ways — a kuzushi window opens, a stifled reset breaks them apart, or a fighter commits to a throw attempt. Dozens of sub-loop cycles occur between any two Matte calls.

The sub-loop operates on the grip graph: TUG_OF_WAR computes a `grip_delta` from the live edge list; KUZUSHI_WINDOW checks throw prerequisites against the graph; STIFLED_RESET breaks all edges and steps both fighters back. The sub-loop is the runtime layer that drives the graph through its state changes.

**Three outcomes, not two.** Most judo games model throws as binary: attempted/not attempted. Tachiwaza models the space between throws as active, contested, and resolution-bearing. Most of a real match's time — and most of where matches are actually decided — lives inside this sub-loop.

**The coach is not always involved.** A match can end inside a single sub-loop cycle. A fighter who wins the opening grip war decisively, opens a kuzushi window at tick 12, and lands seoi-nage for ippon has ended the match before the referee called Matte. The coach never spoke. This is not a failure mode — it's one of the most beautiful outcomes in real judo, and the game has to allow for it.

This creates Tachiwaza's first real lesson about the limits of authorship: **preparation is the primary lever, not intervention.** Over a career, good coaching is distributed across training, not chair-time.

---

## THE SIMULATION RINGS

*Concentric layers. Inner rings get built first. Physics, the grip graph, and the sub-loop run underneath all of them.*

### RING 1 — The Match Engine (BUILD FIRST)

Event-driven tick simulation. Two judoka grappling on a relational state graph. The Grip Sub-Loop runs continuously, producing three resolution types — kuzushi window, stifled reset, throw attempt. Throw attempts themselves resolve to IPPON / WAZA_ARI / STUFFED / FAILED based on technique execution and landing angle. Stuffed throws can open ne-waza windows. Matte is called by the Referee based on personality.

**Grip graph in Ring 1:**
The graph IS the match's tactical state. Throws are gated on graph prerequisites — no throw fires without the edges to support it. Ne-waza graspers and targets activate when position transitions to NE_WAZA, allowing chokes, armbars, and pins to be modeled as commitment chains operating on the graph. The position state machine governs which graph operations are legal at each moment.

**Physics in Ring 1:**
Throw success resolution uses the first physical variable: height differential as a moment arm modifier. The formula is simple in Phase 2 and grows in precision each subsequent ring:

```
throw_success = technique_effectiveness 
              × moment_arm_modifier(height_differential, throw_type)
              × graph_satisfaction(throw_prerequisites)
              × (1 - fatigue)
              × (1 - opponent_reaction)
```

A taller fighter doesn't automatically win — their advantage is throw-specific. Seoi-nage rewards height. O-uchi-gari is neutral. Sumi-gaeshi may actually favor the shorter fighter.

**The referee as a personality:**
Not just a rules enforcer — a style that shapes the match. Four variables:
- `newaza_patience` — how long ground work breathes before Matte
- `stuffed_throw_tolerance` — how fast they reset after a stuffed throw with no ground attempt
- `match_energy_read` — do they factor in whether both fighters look spent?
- `grip_initiative_strictness` — how quickly passive grip behavior earns shido

Plus scoring tendencies (`ippon_strictness`, `waza_ari_strictness`) that decide borderline landing-angle calls. Belt rank gates composure hits from referee calls: GREEN belt and below take a small composure penalty from a quick Matte on a near-throw. Brown belt and above have seen it a thousand times. Nothing.

**Landing angles in Ring 1:**
Throw resolution computes a `ThrowLanding` with landing_angle, impact_speed, and control_maintained. The referee reads the landing and applies their personality: a flush dorsal landing with control = IPPON for any ref; an angled 30° landing with control = IPPON for a generous ref, WAZA_ARI for a strict ref. This is where the same throw produces different scores depending on who's wearing the white shirt.

### RING 2 — The Coach Instruction System & Tournament Attention

The Matte window. Two instructions max. Reception based on composure × trust × fight_iq × (1 - fatigue) × voice_compatibility.

**Grip graph in Ring 2:**
The Matte panel renders the graph as legible state. Coach IQ filters what's visible — see `grip-graph.md` for the three-tier visibility spec. A novice coach sees a position name and qualitative fatigue. An elite coach sees the full edge list with numeric depth values, opponent fatigue distribution per body part, and physics readouts. Instructions map to intended graph transitions: "BREAK GRIP" attempts to delete the opponent's highest-depth controlling edge; "ATTACK NOW" checks if any throw in vocabulary satisfies the current graph; "GRIP FIGHT" attempts to upgrade the lowest-depth friendly edge.

This makes the coaching feel responsive and informed rather than abstract. The instructions aren't flavor — they're targeted operations on a visible state.

**Physics in Ring 2:**
Instructions carry physical cost. "Switch stance" is not free — the efficiency penalty depends on the fighter's dominant-side strength differential. The Matte panel surfaces this: *"Switching stance will cost him. His left side isn't there yet."*

**Cultural layer in Ring 2:**
Coach voice (volume, emotional register, technical specificity, language mix, instruction length) compatibility with the fighter's training lineage modulates instruction reception. A Japanese-trained fighter under a Georgian-voiced coach receives instructions at ~0.7 efficiency even when trust is high. The seven-category instruction taxonomy becomes the formal structure. Full spec in `cultural-layer.md`.

The coach's job is to read not just the score but the body and the graph — what the fighter can physically execute right now versus what they were capable of at tick 0.

**Tournament Attention Economy** also begins here — when you have multiple judoka in one tournament, you can only sit in one chair at a time. See `dojo-as-institution.md`.

### RING 3 — The Dojo & Training System

The dojo as facility. Training items target specific attribute clusters. Weekly time advancement. Trust as the slowest variable in the game. Money & Prestige activate here — see `dojo-as-institution.md`.

**Grip graph in Ring 3:**
Training targets specific grip configurations and ne-waza graspers. You don't train "grip strength +1" abstractly — you drill HIGH_COLLAR security against resistance, you practice CROSS grips for stance-switch attacks, you spend mat time on UNDERHOOK control for ne-waza top position. Each training item improves the fighter's edge formation probability and depth-securing ability for that specific grip type.

**Coaching IQ as a trainable variable:**
The sensei's own coaching IQ improves with study, with experience coaching matches, and with mentorship from senior coaches. This directly affects what the Matte panel reveals. A sensei who started at coaching IQ 4 (sees only basic state) can train up to coaching IQ 8 (sees the full graph) over years. The progression has lived consequences — your fights start *feeling* clearer to read because the panel actually shows more.

**Physics in Ring 3:**
Training targets physical variables, not just abstract stats. Forearm endurance under resistance (uchikomi bands) improves grip endurance. Hip drop speed for seoi entry (mirror drills) improves throw entry cost. Stance width and stability under lateral force (balance boards) affects weight_distribution. The chain is complete: **dojo investment → physical variable improves → graph edge formation/maintenance improves → throw resolution produces different outcomes → match results change.**

**Cultural layer in Ring 3:**
The seminar / visiting-specialist event framework goes live. A Georgian champion runs a one-week seminar at your dojo: every attendee gets a small style_dna addition and learns the BELT and OVER_BACK grip configurations. The dojo itself remembers the event forever. Style_dna shifts observable through training cycles. Full spec in `cultural-layer.md`.

### RING 4 — The Roster, Long Arcs, & Lineage

Recruitment of young prospects. Career arcs spanning 10+ in-game years. Multigenerational lineage when a sensei retires and a former judoka inherits the dojo.

**Grip graph in Ring 4:**
A fighter's signature grip preferences become a recruitment lens. When you scout a prospect, you read which grip configurations they instinctively reach for at engagement, and which throw prerequisites their preferred grips satisfy. A 16-year-old who naturally gravitates to HIGH_COLLAR and wants to attack rotational throws is a different recruit from one who reaches for BELT and wants to attack with body-lock takedowns. Same belt rank, same body weight, very different career trajectories.

**Sensei's grip patterns transmit to students.** The institutional style_dna of the dojo (see `cultural-layer.md`) carries grip preferences across generations. A dojo that's had three Georgian-influenced sensei in a row produces white belts who instinctively want OVER_BACK grips even though they've never met a Georgian. The grip graph captures this pattern transmission as data.

**Physics in Ring 4:**
Body type as the recruitment lens. When you scout a prospect, you are not just reading their current stats — you are reading what their body will *become* capable of.

A 16-year-old at 170cm with long arms and narrow hips: the physics points toward uchi-mata. A 16-year-old at 165cm with wide hips and explosive legs: the physics points toward seoi-nage or ko-uchi — lower entry cost, natural weight distribution for the technique.

The casual player recruits by current stats. The advanced player recruits by body type and projects the career arc. Same data, different depth of reading.

**Cultural layer in Ring 4:**
The full lineage system activates. School demographics bias the recruit pool by location (an American dojo gets mostly Classical Kodokan white belts with some BJJ crossover; a Tbilisi dojo gets 85% Georgian heritage recruits). Sensei style_dna passes to students and to the dojo's institutional style_dna. Over 3-4 generations, your dojo develops a hybrid style that doesn't match any of the thirteen seeds — a weird Georgian-BJJ-Japanese blend shaped by everyone who came through. The Wall remembers not just which champion fought, but which style they represented and which signature grips they carried. Full spec in `cultural-layer.md`.

### RING 5 — The 2D Visual Layer (POST-PROTOTYPE)

Pixel-art figures with stripe-based grip indicators. Kairosoft-style top-down dojo view. Always paired with the prose log, never replacing it. *Symbols that change state, not animation frames.*

**Grip graph in Ring 5:**
The visual layer renders the graph directly. Each GripEdge becomes a visible stripe or line connecting the grasping hand to the gripped location on the opponent. Edge depth shows as line thickness. Edge strength shows as line opacity. Contested edges flicker. The asymmetry of the graph becomes legible at a glance — you can SEE which fighter has dominant grip without reading the log.

This is the moment where a non-judoka spectator can finally watch a match and understand what's happening. The grip war stops being invisible.

**Physics in Ring 5:**
The visual layer makes the physics legible to players who don't want to read stats. Height differential is visible in the sprite proportions. Grip control radius shows as a subtle highlight around each fighter's hands. When posture breaks, the sprite reflects it.

The physics doesn't become decoration — the visuals become a second language for the same underlying numbers. A player who can't read the stat panel can still see that one fighter is longer and one is lower, and start to understand what that means.

### RING 6 — Sound (LATE)

Dojo ambient theme, match tension layers responsive to score and fatigue, signature motif when one of *your* judoka enters their finals. Built when the world is ready to hold it.

**Grip graph in Ring 6:**
Sound responds to graph state changes. A different musical motif when a deep grip secures. A specific cue when a controlling grip breaks. Ne-waza positional dominance shifts get their own audio language. Sound marks the moments the graph earns.

**Physics in Ring 6:**
Sound responds to physical thresholds. Music shifts when fatigue crosses a specific floor. A different motif when a throw succeeds against the physics — a smaller fighter lifting a heavier one, the numbers resolving something unexpected.

---

## THE OPTIONAL MODE: PLAY-AS-JUDOKA

*Added April 14, 2026. A future direction, not in scope for any current ring. Full sketch in `play-as-judoka-mode.md`.*

Coaching is the soul of Tachiwaza. But the grip graph architecture also opens the door to a separate mode where the player controls a judoka directly — the same way DF's Adventure Mode lets you wrestle with explicit control over which body part grabs which target.

In play-as-judoka mode, the grip graph IS the chess board. You see the live edges. You choose which grasper goes for which target. You commit to throw entries. You roll counter-actions in ne-waza. The action choices flow from the visible graph state, the way DF's Adventure Mode wrestling menu generates options dynamically from the current grapple state.

This could be:
- Single-player vs. AI (a different way to play the same simulation)
- Multiplayer (turn-based or real-time) where two players grapple through the same graph — a chess match of attacks, counters, and 5-moves-ahead planning

Out of scope until post-Ring 4. Architecturally, this mode requires the grip graph to be solid (Ring 1) and ne-waza to work (Ring 1 / Phase 2 Session 2) — which means the Phase 2 Session 2 work IS the foundation for this mode. The sketch is captured in `play-as-judoka-mode.md` so it doesn't get lost.

---

## THE SKILL CEILING

*This is what separates Tachiwaza from other sports sims.*

**Casual player experience:**
- Tanaka is strong on the right side
- His seoi-nage works well
- He's getting tired in round two
- The ref is calling Matte quickly — should probably reset

**Advanced player experience:**
- Tanaka's moment arm advantage disappears against anyone under 172cm — recruit opponents he can look down at, avoid compact fighters
- His hip drop speed is the bottleneck, not his grip strength — train the mirror drills first
- The fatigue curve on his right forearm hits the threshold around tick 180 — in a long match, his seoi window closes before the final minute — build the game plan around early ippon, not attrition
- This ref has low stuffed_throw_tolerance and high match_energy_read — instruct conservative early, don't waste energy on exploratory attacks that will get called dead
- His training lineage is 100% Classical Kodokan; putting him under a Georgian-voiced coach in the chair costs reception efficiency — either train him into the dojo's voice or accept the penalty
- His preferred grip configuration is HIGH_COLLAR with sleeve — against a southpaw, the mirrored stance puts his right_hand on the wrong side of the lapel and his engagement edge formation drops 30%; pre-match, run him through the stance switch drill

Same simulation. Different depths of reading. Neither player is wrong. The game rewards the depth if you go looking for it.

---

## THE INSTRUCTION TAXONOMY

*Initial set. Will grow with playtesting. Seven categories drawn from the research doc `coaching-bible.md`.*

**Score / Time status** — You're up. Shido him. Two minutes. One minute.

**Grip-focused** — Break his grip first. Get the dominant grip before you commit. Switch stance — attack the other side. Stop reaching with your tired hand. Strip his pistol grip.

**Tempo-focused** — Stay patient. Let him come to you. Push the pace. Tire him out. Slow it down. Reset. Attack on his next breath.

**Technique** — Seoi. Uchi-mata. Tokui-waza (your best). Ko-uchi first, then seoi.

**Tactical** — Go to the ground if he opens up. Stay standing — he's better on the mat. Attack his weak leg. Counter, don't initiate.

**Composure / Defensive** — Tighten up. He's reading you. Head up. Posture. Block. Don't let him turn in. Breathe. You have time.

**Motivational / Risk** — Take the chance. Go for ippon. Play for shidos. He'll panic. Defensive grip. Run the clock.

**Physics-aware (Ring 2+)** — Use your height. Make him reach up. Get lower than him. Take away his entry. He can't sustain that grip. Wait him out. His left side is weaker. Circle that direction.

---

## TONE RULES (the writing guide)

**The voice of the match log is a knowledgeable sportswriter.** Specific. Calm. Loves the sport. Doesn't explain what kuzushi is — assumes the reader is paying attention or willing to learn.

**The voice of the coach window is intimate.** It's the player's view of their fighter. Quiet, focused, slightly worried. Physics-aware without being clinical — *"His entry window is closing"* not *"moment arm modifier is below threshold."*

**The voice of the dojo is warm.** This is home. This is where the work happens. The dojo prose has the texture of routine — sweat, repetition, small jokes, the smell of the mats.

**No hype. No announcer voice.** Tachiwaza is not the UFC. It is judo — a sport with deep roots, formal etiquette, and an understated culture. The writing should respect that.

**Every fighter is treated with dignity.** Including the opponents. Including the ones who lose. Especially the ones who lose.

**Physics resolves; prose marks.** The simulation never announces the physics. When a smaller fighter lifts a heavier one, the log doesn't say "moment arm calculation succeeded." It says something that earns the moment. The numbers crossed a threshold. The sentence reflects it.

**The graph is the source of specificity.** "Tanaka's right hand still on the collar" maps to a specific GripEdge. "Sato strips the sleeve grip" maps to a specific edge transitioning to FAILURE. The prose names what the graph has just done. Every sentence is grounded in a real simulation event.

**The grip sub-loop runs silently most of the time.** Stifled resets early in a match are not narrated. The log gets denser as fatigue develops and the sub-loop starts resolving things that matter.

---

## OPEN QUESTIONS

**Q1: How real-time is the match?** Live-scrolling log with player-controlled speed seems right, but worth playtesting.

**Q2: How many judoka in a stable?** 5 active fighters as a starting cap. Eventually unlock more — and competitive stables grow significantly across the multigenerational arc.

**Q3: How long is a "season"?** ~1 in-game month = 5 minutes of play. A full career arc fits in a play session of reasonable length.

**Q4: Single-discipline or multiple?** Pure judo for v1. BJJ, sambo, freestyle wrestling could be future expansions sharing the same engine. The grip graph generalizes naturally — sambo just unlocks LEG_GRAB targets that aren't legal in IJF judo.

**Q5: How does a non-judoka learn the sport through play?** Glossary tooltips on every term in the match log. Hover "ko-uchi-gari" → see a one-line description and a tiny diagram. Hover any GripEdge in the Matte panel → see what that grip type is and what throws it enables.

**Q6: AI prose generation for matches?** Same architectural question as Player Two. Build deterministic prose templates first as a fallback; layer Claude-in-Claude generation on top once the system works. The grip graph gives the prose engine rich, typed events to render — this makes Claude-generated prose dramatically more grounded.

**Q7: Does the Matte window have a real-time pressure element?** A 10-second window to issue instructions before the fighter goes back out alone? Mirrors real coaching pressure. Possibly toggleable difficulty.

**Q8: How granular does the physics get in Ring 1?** Start with height differential as a single modifier. Add hip height in Ring 2 calibration. Add arm reach when the grip sub-loop needs it to generalize. Each ring earns the next variable by making the previous one observable and meaningful.

**Q9: How does the advanced player *see* the physics?** The stat panel in the Matte window is the primary interface. Tooltips on throw attempts in the log. A "body analysis" view in the dojo that maps a fighter's physical variables to their optimal throw set.

**Q10: How often does a match end before the coach speaks?** Phase 2 Session 2 will produce real data on this. Design target: 10-20% of matches resolve inside a single sub-loop cycle.

**Q11: When does play-as-judoka mode get scoped?** Not until after Ring 4 ships. The sketch is captured to preserve the idea, but the discipline holds: build the coaching sim first.

---

## PROJECT ARCHITECTURE

*Sessions roll up into phases. Phases roll up into rings. Rings roll up into the game. Each layer is a committable, reviewable unit.*

**Ring 1 consists of three phases:**
- **Phase 1 — Skeleton** (✅ complete, April 13, 2026)
- **Phase 2 — Real Combat + Grip Graph + Sub-Loop + Ne-Waza + Referee**
  - Session 1 (✅ complete, April 14, 2026): throw resolution, scoring, fatigue, match-end conditions
  - Session 2 (current target): grip graph + position state machine + ne-waza window + Referee class — see `phase-2-session-2-plan.md`
- **Phase 3 — Calibration** (watch many matches, tune thresholds, adjust curves; single long session)

After Ring 1 Phase 3, work opens onto Ring 2 Phase 1 (first real Matte window). The ring-phase-session architecture holds for the entire project.

---

## WHAT TO BUILD FIRST (priority order)

**Phase 1 — The Match Engine Skeleton.** ✅ COMPLETE (April 13, 2026)

**Phase 2 — Real Combat + Grip Graph + Ne-Waza + Referee.**

  **Session 1 — Throw Resolution & Scoring.** ✅ COMPLETE (April 14, 2026)
  - Mate → Matte rename
  - effective_body_part() implementation
  - Throw resolution: IPPON / WAZA_ARI / STUFFED / FAILED
  - Scoring wired to match state; match end conditions
  - Identified the "throws fire every tick" problem → drove Session 2 scope

  **Session 2 — The Grip Graph, the Position Machine, the Ne-Waza Door, and the Referee.** (NEXT)
  - Body parts expand from 15 to 24 (head, hips, thighs, knees, shins, wrists)
  - GripEdge / GripGraph as Match-level state, replacing grip_configuration dict
  - Position state machine gates throw attempts on graph satisfaction
  - Throws rewritten with EdgeRequirement prerequisites
  - Ne-waza window opens on STUFFED with multi-turn commitment chains for choke / armbar / pin
  - OsaekomiClock for pin scoring
  - Referee class with four personality variables (newaza_patience, stuffed_throw_tolerance, match_energy_read, grip_initiative_strictness)
  - Landing angle resolution for borderline IPPON / WAZA_ARI calls
  - Belt rank gating on composure hits from referee calls
  - Hajime / Matte / Ippon ceremonial calls
  - Full plan: `phase-2-session-2-plan.md`

**Phase 3 — Ring 1 Calibration.**
Watch many simulated matches. Tune the grip sub-loop thresholds, the throw resolution modifiers, the referee personality defaults, the edge fatigue rates, the ne-waza commitment chain timings. Adjust until the match rhythm looks like real judo at elite level.

**Phase 4 (Ring 2 Phase 1) — The Matte Window.**
Pause logic. Stat panel including physical variable readout and graph rendering filtered by coach IQ. Instruction menu with seven-category taxonomy. Reception calculation including voice compatibility. Resumption.

**Phase 5 (Ring 3 Phase 1) — A Single Training Cycle.**
Dojo class. Training items target physical variables AND specific grip configurations / ne-waza graspers. Coaching IQ as a trainable variable that affects Matte panel legibility. Weekly time. Attribute changes. Injury risk.

**Phase 6 (Ring 4 Phase 1) — A Roster & Career.**
Recruitment. Body type and signature grip preferences as recruitment lens. School demographics biasing the recruit pool. Tournament schedule. Multiple judoka in parallel. First version of Tournament Attention Economy. Career arcs.

**Later — The 2D Layer.** Only after the loop is undeniably fun in pure text.

**Even later — Play-as-Judoka mode.** Sketched in `play-as-judoka-mode.md`. Post-Ring 4.

---

## DESIGN DOCUMENTS

*Living reference files. Read before building their corresponding ring.*

- `data-model.md` v0.4 — Judoka class spec (Identity / Capability / State). 24 body parts. GripEdge fields. Code is implemented from this doc.
- `grip-graph.md` v0.1 — The bipartite state structure. Edges, types, targets, three-tier resolution, multi-turn chains, throw prerequisites, coach IQ visibility tiers.
- `grip-sub-loop.md` v0.2 — The continuous micro-cycle that drives the graph. Now reads from GripEdge list.
- `biomechanics.md` v0.1 — The physics layer. Five physical variables and how they feed each ring.
- `cultural-layer.md` v0.1 — 13 national styles as seeds, style_dna inheritance, seminars, school demographics, coach voice compatibility. Ring 2-4 scope.
- `dojo-as-institution.md` v0.2 — Tournament Attention Economy, Multigenerational Lineage, Dojo Prestige & Economy.
- `phase-2-session-2-plan.md` — The Claude Code brief for the next session.
- `play-as-judoka-mode.md` — Sketch of the future direct-control mode.
- `The Chair, the Grip, and the Throw` (coaching bible) — Research document on national fighting styles, Matte window research, referee behavior, prose voice reference.
- `From Tissue Layers to Tatami` — Research document on Dwarf Fortress combat / grapple architecture and what translates to Tachiwaza.

---

## RELATIONSHIP TO PLAYER TWO

Tachiwaza and Player Two are **parallel projects of equal priority.**

Both share architectural DNA:
- Tick-based simulation
- Prose layered over structured events
- Systems as the author
- Python and the same toolchain

Both compete for the same finite hours. Whichever project is generating real creative pull on a given day earns that day's session. The discipline is not which project ranks higher — it's that whichever one gets a session today gets a *clean* session: focused, committed at the end, with a clear next entry point recorded in the dashboard.

**Practical working model:**
- Each project has its own repo, its own folder, its own dashboard, its own orientation doc
- When a session is for one project, the other repo stays closed
- Once a week, a 10-minute meta-check: which project am I excited to open this week? That answer is data, not a contract — and over 3–4 weeks a pattern emerges
- That pattern *is* the real roadmap

Player Two has a January 9, 2027 release target. If Tachiwaza turns out to be the alive project for an extended stretch, Player Two's date or scope adjusts. The release date serves the work. The work does not serve the release date.

---

## WHAT'S BEEN BUILT

- ✅ Phase 1 skeleton — April 13, 2026
- ✅ Phase 2 Session 1 — April 14, 2026 (throw resolution, scoring, fatigue)
- ✅ `data-model.md` v0.4 — 24 body parts, GripEdge fields, landing angles, coach IQ visibility hooks
- ✅ `grip-graph.md` v0.1 — bipartite graph spec, multi-turn chains, throw prerequisites
- ✅ `grip-sub-loop.md` v0.2 — sub-loop math operates on GripEdge list
- ✅ `biomechanics.md` v0.1 — physics layer
- ✅ `cultural-layer.md` v0.1 — 13 styles, style_dna, seminars
- ✅ `dojo-as-institution.md` v0.2 — Attention Economy, Lineage, Economy
- ✅ `phase-2-session-2-plan.md` — Claude Code brief for next session
- ✅ `play-as-judoka-mode.md` — sketch of future mode
- ✅ Coaching bible — research doc on national styles
- ✅ Tissue layers research doc — DF architecture translation

## WHAT'S NEXT

1. **Phase 2 Session 2 — The Grip Graph, the Position Machine, the Ne-Waza Door, and the Referee** (next Claude Code session)
   - Follow `phase-2-session-2-plan.md` file by file
   - Build order: enums → judoka → grip_graph → throws → position_machine → referee → ne_waza → match → main
   - Validation: 20 match runs showing grip war development, prerequisite-gated throws, ne-waza windows, varied match lengths
   - Write `phase-2-session-2-recap.md` after the session
2. **Phase 3 — Ring 1 Calibration** — watch many matches, tune thresholds
3. Review `biomechanics.md` with physics collaborator (Adrian) when the sub-loop is producing real data to react to
4. Consider whether to start sketching `referee.md` as its own design note after Session 2 ships and the Referee class is real

---

*Document version: April 14, 2026. Updated alongside grip-graph.md v0.1, data-model.md v0.4, grip-sub-loop.md v0.2, and phase-2-session-2-plan.md v0.1.*
