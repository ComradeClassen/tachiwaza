# Grip Model Diagnosis — Notes 1 & 2

*Findings pass for the 2026-06-04 Claude.ai handoff. Source: match log `Hajime_Match_Test_-_6-3-26.md`, seed 1349309793. Diagnosis only — no fixes applied. Verified against repo at `haj-kuzushi-buffer-instrumentation` (HEAD 310816e).*

Both notes land where the handoff predicted: **calibration + narration, not a missing engine.** The grip-war model is more complete than the log reads. Detail and evidence below.

---

## Note 1 — "The first grip always looks like a double grip; it should be one grip building toward two."

**Verdict: calibration + narration (doc item A-2). The leader genuinely seats both hands in one tick — that part is real — but it is uncontested and narrated as a fait accompli.**

### What the code does

1. **The initiative winner seats *both* grips in a single tick.** `_stage_grip_cascade` computes initiative for both fighters, picks the leader, and immediately calls `_seat_grips_for(leader, follower, tick)` ([src/match.py:2353](src/match.py)). `_seat_grips_for` unconditionally appends *two* edges — dominant-hand→lapel and off-hand→sleeve ([src/match.py:2485-2511](src/match.py)). Both land at `POCKET` on the same tick. This is the t004 double `[grip]` in the log.

2. **There is no mechanism forcing the second grip to be a separate contested step — for the leader.** The two-sided contest *does* exist, but it is leader-vs-follower, not first-hand-vs-second-hand. The follower's response is deferred `GRIP_CASCADE_LAG_TICKS = 2` ticks ([src/match.py:329](src/match.py), gated at [src/match.py:2238](src/match.py)), then resolved by `_resolve_grip_cascade` → `select_response` (the five-branch model). So the design *does* model "one fighter ahead, the other responding" — it just resolves the leader's own two hands atomically.

3. **"Finds nothing" is the only authored follower outcome on the initiation tick.** The mat-side line is a hardcoded f-string with exactly two symmetric forms ([src/narration/altitudes/mat_side.py:242-248](src/narration/altitudes/mat_side.py)). It fires whenever the leader seated and the follower has not yet responded — there is no "intercepts / frames / fights for the inside" alternative. The follower's *actual* response (CONTEST/MATCH/etc.) only narrates 2 ticks later, so the initiation tick always reads as a clean shut-out.

### Why it reads wrong

The judo intent is one hand winning the inside, then the second hand following once the first is secured. The engine collapses that into one atomic two-edge seat. Mechanically defensible (POCKET depth is weak, and the follower contests on tick+2), but the *prose* presents it as an instantaneous double-grip with the opponent grabbing air — exactly the reviewer's complaint.

### Classification

- **A-2 (calibration):** should the leader seat both hands in one tick, or should the off-hand be a second beat? This is the "is the leader's grab too uncontested" open question, already parked in [grip-war-and-connective-tissue-v0_2.md:122](design-notes/grip-war-and-connective-tissue-v0_2.md).
- **D-1 (narration):** "secures the first grip — finds nothing" is an inline f-string with no variation and no follower-side alternative on the initiation tick. Migrating it to data-driven prose (D-1) plus authoring a contested/partial variant covers the "should be one grip building toward two" feel without touching the engine.

---

## Note 2 — "I can read deepening but never stripping."

**Verdict: calibration + narration. The five-branch model, the STRIP action, and the deterministic strip chain all exist and all fire. Strips are attempted constantly; they almost never *fully* succeed, and when they partially succeed the prose is cryptic — so the player only sees deepening.**

### 1. Five-branch model exists with the documented weights

`grip_initiative.py` defines all five responses ([src/grip_initiative.py:38-46](src/grip_initiative.py)). Base weights are **exactly** as the docs claim ([src/grip_initiative.py:267-273](src/grip_initiative.py)):

```
CONTEST 1.0   MATCH 1.5   PURSUE_OWN 1.0   DEFENSIVE 0.7   DISENGAGE 0.5
```

Archetype modulation is real, including `GRIP_FIGHTER ×1.6` on CONTEST ([src/grip_initiative.py:289-307](src/grip_initiative.py)).

### 2. Empirical branch selection (20 matches, seed 1349309793 + 19 neighbors)

| Branch | Count | Share |
|---|---|---|
| MATCH | 25 | 33% |
| PURSUE_OWN | 16 | 21% |
| DISENGAGE | 13 | 17% |
| **CONTEST** | **11** | **14%** |
| DEFENSIVE | 11 | 14% |

**CONTEST is not under-firing** — it fires ~1 in 7 cascades, behind only MATCH (which has the highest base weight by design). The reason the *match* feels strip-free is two-fold (below). Note both fighters here are **LEVER (Tanaka)** and **MOTOR (Sato)** — neither is GRIP_FIGHTER, so the ×1.6 CONTEST boost never engages; a GRIP_FIGHTER would push CONTEST materially higher.

### 3. The CONTEST cascade branch does **not** strip

When CONTEST fires, the follower just seats their *own* dominant-hand lapel grip ([src/match.py:2681-2704](src/match.py)) — "the second hand drops" is the only difference from MATCH. **No edge of the leader's is stripped or degraded.** So even when the player sees `[grip_cascade] → CONTEST` (t020), nothing gets ripped off and no strip sentence is possible. This is the single biggest contributor to the "never stripping" read.

### 4. Stripping as an *action* exists and fires — but is gated to a narrow window and rarely fully succeeds

- The STRIP action and the deterministic chain (DEEP→STANDARD→POCKET→SLIPPING→removed) exist: `apply_strip_pressure` ([src/grip_graph.py:395-447](src/grip_graph.py)) and the STRIP action handler ([src/match.py:2121-2148](src/match.py)). *(Note: the `apply_strip_pressure` docstring at [src/grip_graph.py:406-408](src/grip_graph.py) is **stale** — it says "match.py does not call this," but match.py does, via the action ladder. Minor doc fix.)*
- **But STRIP is only issued in one branch of action selection:** the `if not deep_enough` rung ([src/action_selection.py:418-437](src/action_selection.py)) — fired only while the fighter has *no* grip of their own at STANDARD/DEEP. The moment a fighter deepens one own-grip (which the same ladder does aggressively, every tick), they exit that rung **permanently** and switch to pure driving/deepening/foot-attack ([src/action_selection.py:450-484](src/action_selection.py)) — which never strips. So strips only happen in the brief opening before own-grips deepen.
- **Strip force is calibrated so full removal is nearly impossible.** `strip_force = 1.1 × strip_resistance × grip_strength(stripper)` vs `resistance = strip_resistance × depth_modifier × grip_strength(owner)` ([src/match.py:2126-2128](src/match.py), [src/grip_graph.py:414-417](src/grip_graph.py)). With comparable grip strength, a strip wins only when `1.1 > depth_modifier`. Modifiers are SLIPPING 0.2 / POCKET 0.4 / STANDARD 0.7 / DEEP 1.0. So a single strip degrades a grip **one step**, but walking a DEEP grip all the way off needs 3–4 consecutive wins while the owner re-deepens every tick — which never happens.

### 5. Empirical strip vs deepen (same 20 matches)

| Event | Count |
|---|---|
| `deepens …` lines | 458 |
| `tries to rip … can't budge it` (failed strip, narrated) | 88 |
| `→ POCKET.` (GRIP_DEGRADE, partial strip success) | 61 |
| `stripped.` (full GRIP_STRIPPED removal) | **0** |
| forearm-cooked breaks | 0 |

So ~149 strip *events* fire against 458 deepens — strips are ~25% of grip activity, **but zero ever fully succeed**, and the player can't tell:
- The failed-strip line **"tries to rip on the lapel but can't budge it"** ([src/narration/altitudes/mat_side.py:836](src/narration/altitudes/mat_side.py), fired off a `BREAK`/`SNAP` BodyPartEvent) **is the strip** the reviewer says is missing — they saw it at t007/t021/t041 and didn't recognize it as a strip attempt.
- The partial-success line is the raw debug `Sato right_hand LAPEL_HIGH → POCKET.` (t007, t021) — degrade-by-one-step, but it reads as noise, not "Sato stripped Tanaka's lapel down."
- There is **no authored success sentence** for GRIP_DEGRADE or GRIP_STRIPPED in the mat-side voice.

### Classification

- **Calibration:** (a) the CONTEST cascade branch should actually contest/degrade a leader edge, not just seat the follower's own grip; (b) the STRIP rung is gated too tightly (own-grip-shallow only) so mid-exchange strips never happen; (c) strip force vs DEEP resistance makes full removal unreachable. Any one of these is a small numeric/branch change.
- **Narration (D-1):** failed and partial strips fire but read as noise; there is no plain-language strip sentence. A "X rips Y's lapel grip loose" / "X breaks the grip down to a pocket" line family closes most of the perceived gap.
- **Genuine engine gap:** only **`ACCEPT_BAIT`** (doc A-1) — the counter-fighter who deliberately *doesn't* strip — is actually missing. Everything else is wiring/tuning/prose.

---

## Recommended tickets

Nothing net-new beyond what the docs already track. Suggested:

1. **A-2 (calibration) — leader grab contestedness + first-grip sequencing.** Decide whether the leader seats both hands atomically or in two beats, and whether the follower can contest the *initiation* tick. Covers Note 1's "one grip building toward two."
2. **D-1 (narration) — mat-side strip/degrade prose.** Author success + partial-strip sentences and a contested first-grip variant; migrate the inline f-strings (`secures the first grip — finds nothing`, `can't budge it`) to the data-driven pattern. Covers the perceived half of both notes.
3. **Grip-war calibration sub-ticket (new, small) — make strips bite.** Widen the STRIP rung beyond own-grips-shallow, and/or let the CONTEST cascade branch degrade a leader edge, and/or revisit `1.1×` strip force vs DEEP. Pick the minimum that makes full strips occur at a believable rate.
4. **A-1 — `ACCEPT_BAIT` branch** (the only real engine addition) + transcribe the response model into a design doc.
5. **Trivial:** fix the stale `apply_strip_pressure` docstring ([src/grip_graph.py:406-408](src/grip_graph.py)).

*Out of scope for this pass but flagged: the match log carries ~20 other inline reviewer notes (kuzushi-buffer readability, ne-waza on the ground, matte/kuzushi tick ordering, chase probability, "uke airborne and flat" wording, intent/commit feel). Those are separate from the grip model and want their own triage.*
