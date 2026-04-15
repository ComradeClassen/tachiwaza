# Play-as-Judoka Mode — Sketch v0.1
### A Future Direction. Not in Scope.

*This document captures the alternative-mode idea you raised in your notes
on the Dwarf Fortress research paper. It is explicitly **not** in scope
for any current ring. It exists so the idea is preserved and so the
architecture being built right now doesn't accidentally rule it out
later.*

---

## What It Is

The default mode of Tachiwaza is coaching: you sit beside the mat, you
watch the simulation run, you speak two words during Matte. The fighter
is theirs. You shape who they are over time but you don't move their
hands.

**Play-as-judoka mode is the inverse.** You ARE the fighter. The grip
graph is your chess board. You see the live edges as legible state. You
choose which of your graspers reaches for which target. You commit to
throw entries. You roll counter-actions in ne-waza. The simulation
runs around you instead of in front of you.

The architectural insight: **this mode is what Dwarf Fortress's
Adventure Mode wrestling already is, applied to judo.** When you wrestle
a goblin in DF Adventure Mode, the menu shows you the current grapple
state and offers context-dependent actions: grab the throat, lock the
joint, throw, gouge. You read the graph and pick a transition.

In play-as-judoka mode, the menu shows you the current grip graph and
offers context-dependent actions: reach for the high collar with your
right hand, strip the opponent's pistol grip, switch stance, commit to
seoi-nage (only available because you have the DEEP collar grip), force
attempt (with shido risk). You read the graph and pick a transition.

The grip graph is the chess board. Every match becomes a game of reading
position, planning sequences, and making committed moves under fatigue
and time pressure.

---

## Two Variants

### Single-player vs. AI

Same simulation. You control one fighter; the other runs on the existing
AI driven by their personality, archetype, signature throws, and graph
state. This is a different *way to play the same engine*.

Difficulty is governed by:
- AI quality (a stronger AI fighter reads the graph better, makes
  fewer mistakes, has tighter grip security)
- Time pressure on your decisions (a 3-second decision window per tick
  is hard; a 30-second window is easy)
- Information visibility (full graph + numeric depth at easy mode;
  position name + qualitative grip state at hard mode — same gating
  the coach IQ system uses, but applied to the player's own visibility)

### Multiplayer (the chess match)

Two human players. Each controls their own fighter. The grip graph is
the shared state both players read. Decisions can be:

- **Real-time** — both players issuing graph operations as ticks roll
  forward, racing to set up advantageous edges before the other does
- **Turn-based** — each tick is a discrete turn, both players submit
  their intended action, the simulation resolves both simultaneously,
  reveals the result, both players see the new graph and pick again
- **Hybrid** — real-time during grip war (sub-loop is reactive), pause
  for committed throw entries and ne-waza actions (these are the
  high-stakes decisions that benefit from thought)

The five-moves-ahead chess feeling comes from the prerequisite system.
You can't seoi-nage without the DEEP collar grip. So if you want to
seoi-nage in three ticks, you need to be securing that collar grip now,
which means breaking the opponent's controlling pistol grip first, which
means engaging the right hand, which leaves your left side vulnerable to
THEIR seoi-nage attempt — etc. Real planning, real anticipation, real
tradeoffs. Same texture as a real judo match where elite coaches talk
about reading three exchanges ahead.

---

## Why This Mode Makes Sense for Tachiwaza

**1. The architecture is already there.** The grip graph + position state
machine + ne-waza commitment chains being built in Phase 2 Session 2 are
exactly the systems this mode needs. Building play-as-judoka mode later
is mostly UI and networking work — the simulation engine is already
done.

**2. It's a different shape of fun.** The coaching mode is contemplative,
slow, dynastic. Play-as-judoka is tactical, immediate, competitive. They
serve different moods. A player who loves Tachiwaza for the dojo career
might still want to spin up a quick match against a friend on a Tuesday
night.

**3. Multiplayer is a longevity hook.** Single-player games eventually
get exhausted — even great ones. A multiplayer mode gives the game a
second life as a competitive scene. The chess analogy holds: chess is
infinite because two human minds in opposition produce inexhaustible
variety. Two human minds reading the same grip graph produce the same.

**4. It's a teaching tool.** A non-judoka who plays through a few
multiplayer matches will internalize the grip war in a way no amount of
coaching-mode spectating could teach. They'll feel why a deep collar
grip matters. They'll feel the moment when their forearms are too cooked
to hold the lapel anymore. The simulation becomes a sport literacy
trainer.

**5. The two modes share content.** The fighters you build in coaching
mode could be playable in play-as-judoka mode (or vice versa). The
training you do in the dojo carries to whichever mode you take that
fighter into. The dojo lineage matters in both modes. The economy of
Ring 3 doesn't apply to play-as-judoka but the *fighters* do.

---

## What Would Need to Be Built

This is just for awareness — none of this gets built until post-Ring 4.

**UI layer:**
- A play-as-judoka view of the match that's distinct from the spectator
  view used in coaching mode
- Action menu rendering from current graph state (the Adventure Mode
  wrestling pattern)
- Decision timer / pause logic depending on the variant

**AI layer:**
- An AI that competes against a human player (not just runs both sides
  in coaching-mode simulation)
- Difficulty scaling

**Networking (multiplayer only):**
- Turn submission + resolution sync
- Lobby / matchmaking
- Spectator mode (a third party watches the graph in real time, no
  control)

**Tutorial:**
- Onboarding for non-judoka players who don't know what a grip graph is
  showing them

**None of this is in scope until the coaching mode is solid through Ring
4.** The coaching mode is the soul of Tachiwaza. This is a parallel
offering, not a replacement.

---

## Discipline

This document exists to capture the idea. It is not a commitment.

The risk of writing this down is that it becomes a distraction from the
actual roadmap. The discipline:

- **Don't build for it.** Don't add features to the grip graph or the
  position machine "because play-as-judoka will need them." Build what
  the coaching simulation needs. The mode will inherit whatever shape
  the coaching simulation takes.

- **Don't promise it.** It's not on any release roadmap. The January 9,
  2027 release target (Player Two) doesn't apply here, and Tachiwaza's
  release target only covers the coaching mode through whatever rings
  ship by then.

- **Don't over-design it.** This sketch is enough. Don't write a full
  spec until the coaching mode is shipped and there's actual demand.

The reason to capture it now is that it's a genuinely good idea you had
while reading the DF research, and good ideas deserve a home. This is
the home.

---

*Document version: April 14, 2026 (v0.1).
Captured from a note on the Dwarf Fortress research paper.
Out of scope until post-Ring 4. Do not build for it; do not promise it;
do not lose it.*
