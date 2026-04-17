# Hajime — Game Project Orientation

## What This Is

Hajime is a 2D coaching simulation game about judo. The player is not the fighter — the player is the coach. You build a stable of judoka, train them in your dojo, and watch their matches unfold as a deeply simulated, tick-by-tick stream of grip exchanges, throws, scrambles, and ground transitions. When the referee calls Matte and the action pauses, you step in. You get two words to your fighter. Then the simulation resumes — and how well your instruction lands depends on who that fighter is, how tired they are, and how much they trust you.

This document is the starting orientation. It captures the emotional and design intent. The mechanics live in the master doc. The code lives in `src/`.

---

## Who Is Making This

The designer is Comrade — a playwright, performer, and multidisciplinary artist working under Classen Creative LLC. He is also the author of *Player Two*, a parallel project that simulates entire human lives in the spirit of Dwarf Fortress's Legends Mode. Hajime shares Player Two's DNA — entity-driven simulation, prose generated from structured events, tick-based time, the philosophy that *systems are the author* — but it is its own game, with its own scope and release.

Hajime grew out of an earlier idea for a 3D physics-based judo game built in Godot, then Unreal. That project remains valid as a long-term ambition. This one is the version that can ship — and might be more *judo-true* than the physics version, because it can show what's actually happening in elite judo: the invisible grip war, the fatigue arithmetic, the read.

The designer brings: a real love of the sport, a Player-Two-built fluency in Python and tick-based simulation, and an instinct for the moments that matter inside a structured system.

---

## The Emotional Core

You are in the chair beside the mat. Your fighter walks out. You spent two seasons building their grip endurance, three months convincing them to trust your reads, and last week you finally got them to stop reaching with their right hand when they're tired. None of that is visible to anyone but you.

The match starts. You watch the log scroll. You see the fight you trained for — and the fight you didn't. The ref says Matte. Your fighter looks at you.

You have two words.

That's the game. The dojo is where you build the conditions. The match is where you witness what those conditions produce. The Matte window is where you get to *be there* — briefly, partially, never in full control.

---

## What the Player Should Feel

**Investment.** The judoka in your stable are not interchangeable. Each one has a body, a history, a relationship to you. When they win, you feel it. When they lose to someone you should have prepared them for, you feel that too.

**The pleasure of reading.** A great Hajime match is legible. You can see the grip war turning. You can feel the fatigue arriving. You notice the moment your fighter starts reaching out of panic instead of intent. The simulation rewards attention the way a real match does.

**Coach's calm.** You are not in the fight. You are beside it. The game's emotional register is steady — the warmth of a small dojo, the quiet between rounds, the long arc of building someone over years.

**The Matte moment as an event.** When the ref calls Mate and the simulation freezes and your fighter's stats appear and you have ten real seconds to type two instructions — that should feel *charged*. The game's whole architecture exists to make that moment matter.

---

## Primary Influences

**Dwarf Fortress (combat & legends).** The match log is the soul of the game. DF's combat reads as literature because every event is granular and every event has consequence — a tendon torn here changes a fight three minutes later. Hajime's match simulator should feel the same way: causally dense, narratively legible, generative of stories you didn't expect.

**Boxing Gym Story (and the Kairosoft school).** The dojo-as-facility, the roster of fighters with stats and quirks, the rhythm of training cycles between tournaments, the satisfaction of optimizing a small organization. Kairosoft games understand that the *back office* of a sport is its own pleasure.

**Football Manager.** The instruction layer at halftime. The way a coach's read can change a match without the coach playing it. The sense that your understanding of the game is itself a stat.

**Real judo.** Specifically the elite-level grip war that casual viewers don't see. Hajime is partly an attempt to make that war visible — to show why a match was won in the first thirty seconds of grip fighting before either fighter committed to a throw.

**Player Two (the designer's own work).** The principle that prose layered over a structured simulation creates emotion. The principle that variable weight matters — small variables (a fighter's favorite warm-up song) carry low divergence, big variables (a chronic shoulder injury) carry high divergence. The principle that *the soul of the simulation is in the sentence.*

---

## Core Design Principles

**The simulation runs. The coach influences.** You never directly control a judoka in a match. You shape who they are through training, and you shape their reads through instruction. The fight itself belongs to them.

**The body is the stat sheet.** Right grip strength, left grip strength, posture, legs, cardio, composure. Every body part has fatigue and recovery curves. Training in the dojo targets specific clusters. A fighter with elite cardio holds grip strength deeper into a match. A fighter with weak posture gets bent and broken.

**Matte is the agency window.** The referee calls Matte naturally — stalemate, out of bounds, a stuffed throw resolving in defensive grip. The simulation pauses. Two instructions, max. Then it resumes. This is the only time the player speaks into the fight.

**Reception depends on the fighter.** The same instruction lands differently on different judoka. A fighter with high composure and high trust executes it cleanly. A panicked or distrustful fighter half-executes or freelances. Trust is built in the dojo over time — it is its own slow-growing variable.

**Training is strategic, not grindy.** Items in the dojo (uchikomi bands, specific sparring partners, video study, meditation cushion, weight room, ice bath) target specific attribute clusters. Overtraining one cluster fatigues others. Pushing a young judoka too hard raises injury risk. You are making real coaching decisions with tradeoffs.

**Prose over data.** The match log is not just `THROW_ATTEMPT seoi-nage RESULT stuffed`. It reads like a sportswriter who knows judo: *"Tanaka steps in. Right hand reaches for the lapel. Sato's left hand intercepts — pistol grip on the sleeve."* The data is the skeleton. The prose is the body.

**No graphics until the simulation sings.** The first prototype is text. A scrolling match log, a stat panel, the Matte window. Only when the loop is undeniably fun do we add the 2D pixel layer.

---

## Technical Foundation

- **Language:** Python (same as Player Two — same toolchain, same patterns)
- **Format:** Terminal/text prototype first; 2D pixel-art layer planned for v0.5+
- **Likely libraries:** Pygame for the 2D layer when ready; no engine dependency for the simulation core
- **Long-term engine target:** Godot 2D if Pygame becomes a constraint
- **Repo:** `C:\Users\jackc\Documents\hajime` synced to GitHub
- **Development method:** Collaborative with Claude. Designer provides judo knowledge, design instincts, and prose voice. Claude writes architecture and code.

---

## The North Star

Hajime should make a non-judoka understand why a grip exchange matters. It should make a judoka feel seen — like someone finally built a game that knows what the sport actually is. And it should make the player feel, after a long arc of building a fighter from a 16-year-old prospect to a national medalist, that they were *present* for it.

Not playing. Not watching. Coaching. Beside the mat, two words at a time.

---

*This document will evolve as the game does. It is a starting point, not a contract.*
