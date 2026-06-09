# Ne-waza Entry Paths — Design Decision (HAJ-236)

*A Hajime design document. Resolves how a match *enters* ground work.
The ne-waza subsystem itself (osaekomi clock, escapes, submissions,
catalog) was already built and correct; the problem this doc addresses is
that ground work was almost never *entered* from a standing exchange.*

*Status: Decided and implemented (Q1). Q2 was already shipped (HAJ-152);
Q3 declined; Q4 governed by the Q1 probability model. v0.1 calibration —
v0.2 tunes weights against telemetry.*

*Companion to: `ne-waza-substrate.md`, `grip-sub-loop.md`. Supersedes the
hard-reset half of HAJ-155 for standing throws (the sacrifice routing is
unchanged).*

---

## 1. The problem

In the post-223 match-log review (seed 1081968535) the owner saw **zero
ne-waza** across a full match and asked whether ground work was working.
It was — but it was almost never entered.

At the time of that review there was exactly **one** entry path: a
stuffed or failed **sacrifice** throw (Sumi-gaeshi, Tomoe-nage) opened the
ne-waza door (`match.py` → `_resolve_newaza_transition`, sets
`sub_loop_state = NE_WAZA`). Per HAJ-155, stuffed/failed **standing**
throws deliberately reset to standing instead, so a stuffed O-soto-gari
and a stuffed Tomoe-nage wouldn't look mechanically identical.

The reviewed match threw only standing techniques (o-soto, o-uchi,
ko-uchi, harai-goshi, uchi-mata). None could reach the ground, so zero
ne-waza was the *expected* output of that build — not a broken loop. The
owner's t076 note — *"if a throw is stuffed, that's a chance for
ne-waza"* — is the motivating observation for this ticket.

### What changed underneath the ticket

Between the post-223 review and this ticket, **HAJ-152** shipped the
post-score follow-up window: a scoring-but-not-ippon throw (waza-ari, or
a downgraded no-score landing) now opens a chase decision, and a CHASE /
DEFENSIVE_CHASE routes into ne-waza via `_dispatch_post_score_newaza`.
That is *already* a non-sacrifice entry path, and it fires on standing
throws — re-running seed 1081968535 on the current build now enters
ne-waza at t113 (`[chase_decision] Sato → CHASE (p=0.87)` →
`[ne-waza] Ground! … GUARD_TOP`).

So design question 2 was effectively answered before this ticket opened.
The genuine remaining gap is question 1: a **stuffed** standing throw —
the t076 case — still always reset.

---

## 2. The four design questions, resolved

| # | Question | Decision |
|---|----------|----------|
| 1 | Should stuffed/failed **standing** throws continue to ground probabilistically rather than always resetting? | **Implement.** This is the new entry path. Scope v0.1 to **stuffed** throws (the t076 case); failed-throw extension is deferred (see §6). |
| 2 | Should a **scoring-but-not-ippon** throw flow into a pin/submission attempt instead of resetting? | **Already shipped (HAJ-152).** The post-score chase window owns this. No new code; documented here so the paths read as one system. |
| 3 | Should the referee force ground work from a near-stalemate scramble? | **Decline.** Real referees call *matte* on a stalled scramble — they do not push fighters to the ground. Forcing ne-waza from stalemate would be an unrealistic engine artifact. The existing `STALEMATE` / `STUFFED_THROW_TIMEOUT` matte paths stay as-is. |
| 4 | What governs entry rate so ne-waza appears realistically without dominating? | The Q1 probability model (§3): a low base, a modest ceiling, and throw/skill/fatigue modifiers. See §4 for expected rates. |

### Why Q1, and why stuffed-only at v0.1

A stuffed throw is the natural ne-waza opening: tori over-committed,
uke defended, and for **reaping and leg throws** the two bodies are
already tangled low — a scramble to the floor is the realistic
continuation. For a **clean hip or shoulder throw** that gets stuffed,
the bodies separate and a standing reset is realistic. So the entry must
be *conditional on the throw* (and the fighters), not a blanket "all
stuffs go to ground" — which is exactly what HAJ-155 was right to avoid.

The **failed** path (`_resolve_failed_commit`) is deferred because it
also carries counter-throw outcomes (uke throws tori), which are a
different geometry that should not route through this door. Keeping v0.1
to the clean STUFFED branch is surgical and matches the t076 note
verbatim.

---

## 3. The probability model

A stuffed **standing**, non-sacrifice throw (with no commit-motivation
tactical-drop label) rolls a single ground-continuation decision in
`ground_continuation.make_ground_continuation_decision`. The shape
mirrors `chase_decision.make_chase_decision`: additive, attribute-weighted
factors, clamped, rolled against a seeded RNG, with a factor breakdown
surfaced on the engineering stream.

```
P(continue) = clamp(
      BASE
    + W_THROW_GEOMETRY * (chase_advantage - 0.5) * 2      # throw signal
    + W_TOP_SKILL      * (uke_ne_waza/10 - 0.5) * 2        # who takes top
    + W_BOTTOM_SKILL   * (tori_ne_waza/10 - 0.5) * 2       # bottom appetite
    - W_FATIGUE        * avg_leg_hand_fatigue(both)        # gas to scramble
  , FLOOR, CEIL)
```

v0.1 constants (`ground_continuation.py`):

| Constant | Value | Rationale |
|----------|-------|-----------|
| `CONTINUE_BASE` | 0.12 | A stuffed standing throw resets *by default*; the modifiers lift it where a scramble is natural. |
| `W_THROW_GEOMETRY` | 0.30 | The dominant lever. Reuses the throw's `post_score_chase_advantage` as the scramble-tendency signal — the same geometry that makes a *scored* throw chase-ready makes a *stuffed* one tangle to the floor. |
| `W_TOP_SKILL` | 0.25 | The defender elects whether to follow tori down; a grappler wants the floor, a stand-up player lets them up. |
| `W_BOTTOM_SKILL` | 0.10 | A ground-comfortable tori keeps fighting from the bottom. Smaller — the bottom fighter mostly reacts. |
| `W_FATIGUE` | 0.15 | Scrambles are explosive; gassed limbs disengage. |
| `CONTINUE_FLOOR` / `CONTINUE_CEIL` | 0.02 / 0.50 | Never a hard never; never more than a coin-flip even at the extreme — keeps ne-waza a flavor, not the norm. |

### Why reuse `post_score_chase_advantage` as the geometry signal

It already encodes exactly the right per-throw distinction and is already
authored across the throw vocabulary: reaping/leg throws score high
(O-soto 0.75, O-uchi 0.70, Ko-uchi 0.60, Uchi-mata 0.85 — bodies tangle),
clean shoulder throws sit neutral (Seoi-nage 0.50 — bounces off). Adding a
second, parallel "stuff scramble tendency" field would duplicate that
authoring and let the two drift. One signal, two readers.

### Geometry of the entry

Both the sacrifice door and the new standing-scramble door seat the
**stuffed aggressor on the bottom, the defender on top**, entering at
`GUARD_TOP`. The aggressor over-committed and ends up underneath either
way, so the standing-scramble path reuses the proven HAJ-155
`aggressor_on_bottom=True` plumbing in `_resolve_newaza_transition`. From
there the existing ne-waza substrate owns everything — escape attempts,
osaekomi, submission, and the ne-waza-patience matte.

---

## 4. Entry-rate governance (Q4)

Committed throws run ~2–4 per elite match, and only a fraction are clean
stuffs of reaping throws between two ground-hungry fighters. With
`BASE = 0.12` and a `0.50` ceiling, the model produces:

- A reaping throw (O-soto, adv 0.75) stuffed between two strong-ne-waza
  fighters: **~0.30–0.37** continuation — about one in three.
- A clean shoulder throw (Seoi, adv 0.50) stuffed by a stand-up player:
  **~0.04–0.08** — near the floor; it resets, as it should.

Across a match this adds, on average, well under one extra ne-waza
segment — a believable lift from "never" to "occasionally", layered on
top of the existing sacrifice and post-score-chase paths. The
`test_continuation_rate_is_realistic_not_dominant` test pins the reaping
rate into the `(0.05, 0.50)` band so a future re-tune can't silently make
ground work the norm.

---

## 5. Implementation map

- `ground_continuation.py` — the decision module (enum, result, tuning,
  `make_ground_continuation_decision`).
- `match.py`:
  - `_roll_ground_continuation` — seeds the RNG
    (`haj236:ground:<aggressor>:<seed>:<tick>`, reproducible) and calls
    the module. Exposed as a method so tests can force the branch.
  - STUFFED non-sacrifice branch — rolls the decision, diverges the
    prose (`… they tangle to the mat. Ne-waza scramble.` vs `… Resetting
    to standing.`), emits a prose-silent `GROUND_CONTINUATION` engineering
    event, and enqueues `NEWAZA_TRANSITION_AFTER_STUFF` with
    `aggressor_on_bottom=True`, `source="STANDING_SCRAMBLE"` on CONTINUE.
  - `NEWAZA_TRANSITION_AFTER_STUFF` handler — honors the explicit
    `aggressor_on_bottom` payload (falling back to the sacrifice check for
    legacy payloads) and tags the transition event's `source`.
- Tests: `test_haj236_standing_ground_entry.py` (continuation branch,
  geometry, source tag, rate model, sacrifice-unchanged). The HAJ-155
  reset-branch tests now pin the RESET decision deterministically via
  `_force_ground_reset`, so they keep testing "a standing stuff can
  cleanly reset" independent of HAJ-236 tuning.

### Demonstration seed

`python src/main.py --seed 2 --runs 1 --stream debug` shows **both** gate
directions in one match:

```
t015: [throw] Sato stuffed on Uchi-mata — Tanaka defends. Resetting to standing.
t015: [ground_continuation] Sato stuffed → RESET_TO_STANDING (p=0.35)
t020: [throw] Sato stuffed on O-soto-gari — Tanaka defends, but they tangle to the mat. Ne-waza scramble.
t020: [ground_continuation] Sato stuffed → CONTINUE_TO_GROUND (p=0.29)
t021: [ne-waza] Ground! Sato and Tanaka transition to GUARD_TOP.
t021: [ne-waza] Sato hip-out — partial success.
```

A standing O-soto-gari, stuffed, enters ne-waza from a standing exchange —
the acceptance criterion — with the stuffed aggressor (Sato) underneath
working escapes, exactly as the geometry intends.

---

## 6. Future work

- **Failed-throw extension.** Route a clean (non-counter) FAILED standing
  throw through the same roll. Requires teasing the counter-throw outcomes
  out of `_resolve_failed_commit` first so a countered tori isn't sent to
  the floor by this door.
- **v0.2 calibration.** Tune the five weights against match telemetry once
  the new path has run at scale; in particular, confirm the per-match
  ne-waza-segment count lands where the owner wants it across the full
  throw vocabulary, not just the o-soto/seoi endpoints.
- **Top-fighter choice.** v0.1 always seats the stuffed aggressor on the
  bottom. A future model could let a dominant stuff (uke completely
  shut tori down) seat *uke* on top in side-control rather than guard,
  reading the stuff's quality.
