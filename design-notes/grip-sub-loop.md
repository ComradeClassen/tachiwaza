# The Grip Sub-Loop — Design Note v0.2
### The Mechanic That Gives a Match Its Texture

*This document specifies the continuous micro-cycle that runs between Hajime
and Matte. The sub-loop's job is to drive the grip war forward tick by tick
until something resolves it.*

**Changes from v0.1:**
- The sub-loop now operates on the **GripGraph** (see `grip-graph.md`) as
  its primary data structure. The v0.1 spec treated grip state abstractly;
  v0.2 reads and writes typed edges with depth and strength.
- TUG_OF_WAR computes `grip_delta` from the live edge list, not from
  hand/forearm values directly.
- KUZUSHI_WINDOW resolution checks throw prerequisites against the graph
  before the window can produce a throw attempt.
- STIFLED_RESET breaks all edges on both sides, not just abstractly clears
  the configuration.
- The sub-loop wires into the position state machine (also new in Phase 2
  Session 2) — sub-loop transitions trigger Position transitions and vice
  versa.

The conceptual heart of the sub-loop is unchanged. The mechanical heart is
now grounded in a real data structure.

---

## Why This Exists

Almost every fighting game — and every judo game that has ever existed —
models a match as: setup → throw attempt → result. Either the throw works
or it doesn't. The space between throws is either loading time or a minigame
abstraction.

Real judo doesn't look like that. **A real match is mostly grip fighting.**
Two bodies searching for purchase, breaking contact, re-engaging, wearing
each other down in ways that don't produce scores but absolutely produce
outcomes. A four-minute contest at elite level typically contains two to
four committed throw attempts. The rest is the grip war — the place where
fatigue accumulates, composure drifts, and most matches are actually decided
before anyone attempts a technique.

Phase 2 Session 1's match log had a rhythm problem: throw → throw → throw,
too fast, no texture between attempts. Phase 2 Session 1's recap correctly
diagnosed the cause: the simulation collapsed grip fight → kuzushi → entry
→ resolution into one probability roll per tick. Session 2 fixes this by
making grip state explicit (the grip graph) and making throw attempts
*conditional* on graph state (throw prerequisites). The sub-loop is the
runtime layer that drives those state changes.

---

## The Three Rhythms of a Match

Tachiwaza has three nested rhythms running simultaneously, each with its own
trigger and its own timescale:

### Rhythm 1 — The Tick
The simulation's fundamental heartbeat. ~240 ticks per match, one per
match-second. Every tick updates fatigue, composure, edge strength. Most
ticks are quiet — they accumulate change without producing visible events.

### Rhythm 2 — The Grip Sub-Loop
Runs continuously between Hajime and Matte. A single sub-loop cycle spans
maybe 5–20 ticks: engagement → tug-of-war → resolution (kuzushi window,
stifled reset, or committed throw attempt) → re-engagement. **The referee
is not involved.** Dozens of sub-loop cycles occur between any two Matte
calls.

### Rhythm 3 — The Matte Cycle
Ref-driven (Phase 2 Session 2 introduces the Referee class). Triggered by
stalemate, out-of-bounds, a stuffed throw the ref won't let breathe, or
penalties. Research shows 8–15 Matte cycles per 4-minute match at elite
level, with a 2:1 work-rest ratio (roughly 23 seconds of live action, 11
seconds of pause). This is the coach's window — the only time a coach may
speak.

The key insight: **Rhythm 2 can resolve the match without Rhythm 3 ever
firing.** A fighter who wins the opening grip war decisively, opens a
kuzushi window at tick 12, and lands seoi-nage for ippon has ended the
match before the referee ever needed to call Matte. The coach never got
to speak. That's not a bug. That's judo.

---

## The Sub-Loop State Machine

Every sub-loop cycle passes through these states. Each state corresponds to
operations on the GripGraph.

```
         ┌─────────────────────────────────────────┐
         │                                         │
         ▼                                         │
   ENGAGEMENT ──────► TUG_OF_WAR ──────► RESOLUTION
   (edges form)      (edges contest)     │
                                         │
                          ┌──────────────┼──────────────┐
                          ▼              ▼              ▼
                  KUZUSHI_WINDOW   STIFLED_RESET   THROW_ATTEMPT
                  (depth + posture) (all edges     (commits to a throw
                                     break)         that requires the
                                                    current graph)
                          │              │              │
                          │              │              │
                  ┌───────┴──┐           │          ┌───┴────┐
                  ▼          ▼           │          ▼        ▼
              throw        window       re-         lands   stuffed
              launched     closes       engage      (score) (ne-waza?)
```

### ENGAGEMENT
Both fighters close distance and attempt to establish initial grips. The
sub-loop calls `grip_graph.attempt_engagement(fighter_a, fighter_b)` which
produces 1–3 GripEdge objects based on:

- Reach asymmetry (longer-armed fighter grips first)
- Hand strength
- Style preference (Ring 2+; defaults to STANDARD/sleeve-lapel in Ring 1)
- Stance matchup

Duration: 1–3 ticks. Position transitions from `STANDING_DISTANT` →
`ENGAGEMENT` → `GRIPPING` once both fighters have at least one live edge.

### TUG_OF_WAR
The core state. The sub-loop computes `grip_delta` from the current edge
list:

```python
def compute_grip_delta(graph: GripGraph, tori: Judoka, uke: Judoka) -> float:
    tori_edges = graph.edges_owned_by(tori)
    uke_edges = graph.edges_owned_by(uke)
    
    tori_total = sum(
        e.depth * e.strength * e.grip_type.dominance_factor()
        for e in tori_edges
    )
    uke_total = sum(
        e.depth * e.strength * e.grip_type.dominance_factor()
        for e in uke_edges
    )
    
    # Stance matchup modulates: a grip that's structurally awkward in
    # the current stance contributes less.
    stance_factor = stance_modifier(
        tori.dominant_side, uke.dominant_side, current_stance_matchup
    )
    
    return (tori_total - uke_total) * stance_factor
```

Each tick, every edge ages, accumulates fatigue on its grasper, and rolls
the three-tier outcome. Edges that go PARTIAL lose depth. Edges that go
FAILURE are removed. New edges may be created if a free hand reaches for an
unfilled target.

The `grip_delta` drifts as fatigue shifts — the fighter with better cardio
and lower baseline fatigue gradually wins the delta even if they started
behind. This is where matches are actually won.

### RESOLUTION — The Three Outcomes

**KUZUSHI_WINDOW** — `grip_delta > kuzushi_threshold` for enough consecutive
ticks AND opponent's posture is broken or breaking. A 1–3 tick window opens
where tori can attempt a throw with elevated success probability. The
window's effective size depends on opponent's hip height and posture state.

Critically, **the throw attempted must satisfy graph prerequisites.** A
fighter with kuzushi window open but no DEEP collar grip cannot launch
seoi-nage; they can launch a throw the current graph does support
(o-uchi-gari from a sleeve grip, for example). If no throw in their
vocabulary fits the current graph, the window closes wasted.

**STIFLED_RESET** — `abs(grip_delta) < stalemate_threshold` for sustained
ticks (default 15+) with neither fighter able to dominate. The sub-loop
calls `grip_graph.break_all_edges()` and both fighters step back for 2–4
ticks. Position transitions back to `STANDING_DISTANT`. No Matte is called.
No composure hit for either fighter. Body part fatigue carries over. This
is the most common resolution in a match.

**THROW_ATTEMPT** — A fighter commits to a throw. This happens when:
(a) a kuzushi window is open and the fighter has graph-satisfying throw fit
(b) a fighter forces an attempt under stress (running clock, trailing on
    score, desperation) — this is `force_attempt` with the 0.15
    multiplier, and is also the path that earns shido for false attack

The throw attempt transitions Position to `THROW_COMMITTED` for one tick,
then resolves to landing outcome (see `data-model.md` v0.4 ThrowLanding).

---

## The Biomechanical Spine

The Grip Sub-Loop is where the five physical variables from
`biomechanics.md` first become *observable in play*. With the grip graph in
place, the variables now have specific edges they affect:

### Arm Reach
Determines who creates which edges first in ENGAGEMENT. The
`grip_graph.attempt_engagement()` rolls weighted by reach asymmetry. Longer
reach = higher chance of securing the preferred grip configuration before
the opponent does.

### Hand & Forearm Strength (× Fatigue)
The direct inputs to edge `strength` per tick. These are the variables that
drain most visibly during a long sub-loop. The first fighter whose forearms
cross their fatigue floor begins losing edges to FAILURE — even if they
started stronger. The grip war ends with edges breaking, not gradually
softening.

### Hip Height Differential
Determines what kuzushi force is *geometrically available* when a window
opens. Two fighters with identical grip strength but different hip heights
produce different kuzushi outcomes. A tall fighter who wins the grip delta
against a compact fighter may find the kuzushi window opens in a direction
that doesn't serve their signature throw — the throw's prerequisite check
passes on the graph but the moment arm modifier is poor — so they don't
commit.

### Height & Limb Length
Biases which grip configurations are reachable. A 170cm fighter trying to
establish a HIGH_COLLAR edge on a 195cm opponent pays higher forearm cost
per tick than the reverse. The grip war is not symmetrical.

### Weight Distribution
Affects edge resistance in TUG_OF_WAR. A front-loaded fighter has different
resistance characteristics than a back-loaded fighter. This also shifts as
fatigue alters posture — late in a match, a fighter whose weight has
drifted backward becomes vulnerable to inner reaps in a way they weren't at
tick 0, because their `dominant_thigh` becomes a viable target for o-uchi
that wasn't there earlier.

---

## Why the Coach Sometimes Doesn't Speak

The defining feature of this mechanic: **a match can end inside a single
sub-loop cycle.**

Scenario: Tanaka (183cm, strong right-hand grip, seoi specialist) fights
Sato (175cm, classical posture, grip vulnerable on left side in mirrored
stance). Stance matchup is mirrored. Sato's left-hand grip floor is low.

```
Tick 0   — Hajime.
Tick 3   — Engagement. Tanaka's right_hand → Sato.left_lapel (DEEP, 0.6).
           Tanaka's left_hand → Sato.right_sleeve (STANDARD, 0.4).
           Sato's left_hand → Tanaka.right_lapel (STANDARD, 0.3).
Tick 4   — TUG_OF_WAR begins. Tanaka's deep collar dominates the delta.
Tick 9   — grip_delta crosses kuzushi_threshold. Window opens.
Tick 10  — Tanaka's seoi-nage prerequisites: DEEP collar ✓, sleeve ✓,
           posture (Sato is BROKEN forward) ✓, height advantage ✓.
           Tanaka commits.
Tick 11  — Throw lands. Landing angle: 15°. Control: maintained.
           IPPON.
Tick 12  — Match ends.
```

Twelve ticks. No Matte was ever called. The coach never opened their mouth.
The grip graph went from empty to three edges to throw resolution to over.

This is one of the most beautiful outcomes in real judo, the *ippon
seoi-nage ceremony* where everything aligned in the first exchange. The
game allows for it because the architecture allows for it.

---

## Prose Rules (unchanged from v0.1)

**The sub-loop runs silently most of the time.** A kuzushi window that
opens and closes without commitment is not narrated unless it's
significant. Stifled resets early in a match are not narrated. The log
doesn't say "sub-loop cycle 14 resolved with stifled reset."

**The log marks thresholds being crossed.** When a fighter's grip
genuinely fails after sustained resistance — when the GripEdge transitions
to FAILURE on a roll — that gets a sentence. When a kuzushi window opens
in a direction the fighter's signature throw can't exploit, and they let
it close — that gets a sentence when it matters to the match's trajectory.
When a fighter forces a throw under stress and stuffs it badly, the log
earns that moment.

**Stifled resets become visible through cumulative language.** Early in
the match: silent. Mid-match, once a pattern emerges: *"They've broken
apart four times now. Neither can find the grip he wants."* Late-match,
once fatigue is genuine: *"Another reset. Sato is breathing through his
mouth."*

**The sentence reflects the graph.** *"Tanaka's right hand secures the
collar — deep grip"* maps to a specific GripEdge with grip_type=DEEP,
depth>0.6. *"Sato strips the sleeve grip"* maps to a specific edge
transitioning to FAILURE. The prose names what the graph has just done.

---

## Calibration Knobs (extended from v0.1)

These are the tunable parameters. They do not have correct values yet;
they will be calibrated by watching many matches in Phase 3.

| Parameter | Role | Starting Estimate |
|---|---|---|
| `kuzushi_threshold` | grip_delta required to open window | 2.5 |
| `kuzushi_window_duration` | ticks the window stays open | 1–3 |
| `stalemate_threshold` | grip_delta band considered stalemate | ±0.8 |
| `stalemate_duration` | ticks of stalemate before reset | 15 |
| `reset_recovery_ticks` | breath time before re-engagement | 2–4 |
| `engagement_duration` | ticks to establish grips | 1–3 |
| `forearm_fatigue_rate_per_edge` | per-tick cost of holding an edge | 0.004 |
| `force_attempt_penalty` | success multiplier when no window | 0.15 |
| `edge_force_break_threshold` | grasper fatigue at which edges may break involuntarily | 0.85 |
| `engagement_edge_max` | max edges per fighter created at engagement | 3 |
| `contested_drain_multiplier` | how much faster contested edges fatigue | 2.0 |

All of these live in a single `sub_loop_config` dict that can be adjusted
per-fighter, per-match, or globally during calibration.

---

## What Phase 2 Session 2 Builds (sub-loop portion)

✅ Sub-loop reads the `grip_graph: GripGraph` from MatchState

✅ TUG_OF_WAR uses the new `compute_grip_delta()` function reading the
edge list

✅ ENGAGEMENT calls `grip_graph.attempt_engagement()` which creates real
GripEdge objects with grip_type, depth, strength

✅ KUZUSHI_WINDOW resolution checks throw prerequisites against the graph
before producing a throw attempt

✅ STIFLED_RESET calls `grip_graph.break_all_edges()` and transitions
Position back to STANDING_DISTANT

✅ Forearm fatigue accumulation per held edge per tick (replaces the v0.1
abstract fatigue cost)

✅ Force-break logic: edges may break involuntarily when grasper fatigue
crosses threshold

✅ Sub-loop transitions wire to position state machine transitions

✅ Log output that stays quiet on silent sub-loop activity, marks
threshold crossings, and increases density as fatigue develops

## What Phase 2 Session 2 Does NOT Build (sub-loop portion)

- Coach instructions affecting sub-loop targeting (Ring 2)
- Cultural style biasing which grip_type is reached for at engagement
  (Ring 2)
- Full prose templating (Phase 4; Session 2 uses placeholder log lines
  that mark the right moments)

---

*Document version: April 14, 2026 (v0.2).
Updated alongside grip-graph.md v0.1 and data-model.md v0.4.
Update after Phase 3 calibration reveals real parameter values.*
