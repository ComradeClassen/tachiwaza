# Grip War, the Connective Tissue, and the Migration to One Model

*v0.2, drafted 2026-05-28. **Supersedes v0.1** (`grip-war-and-connective-tissue-v0_1.md`). v0.1 was written on a false premise — that the grip-as-cause symbolic layer was unbuilt — because `grip-as-cause.md`'s own status header reads "No code yet." The codebase audit (`AUDIT_MAP.md`, same date) proved that header stale: **the symbolic chain is built and wired.** This version corrects the premise. The grip-war design (v0.1 Part 1) survives, regrounded against the actual code. The "build the spine" framing (v0.1 Part 2) is retired and replaced with the real work: **finishing the migration to a single kuzushi model and retiring the old one.** The telegraph and narration sections are corrected — both turned out to be partly built. The issue inventory is reworked against current code status.*

*Companion to: `grip-as-cause.md` (parent design — **its status header must be fixed; see Task Zero**), `AUDIT_MAP.md` (the evidence base for every code claim here), `physics-substrate.md`, `ne-waza-substrate.md`, `ne-waza-vocabulary-system-addendum-consumption-semantics.md`.*

---

## Part 0 — Corrected summary, in one breath

The grip-as-cause chain is real: a first-class `PULL` action emits `KuzushiEvent`s into uke's per-fighter decaying buffer (5-tick half-life, maxlen 20); a computed `compromised_state` sums the decayed events; throws fire from a signature match that reads that buffer. The code even says so out loud: *"Throws fire because pulls composed, not because uke happens to be moving this tick."* What's wrong is not that the spine is missing — it's that **the old model still runs in parallel.** A direct geometric boolean (`body_state.is_kuzushi`, "CoM outside the recoverable envelope") still drives the `[physics] off-balance` event, the defensive-pressure feed, and a legacy throw-firing fallback — none of which read the buffer. So off-balance has no narratable cause not because the cause-engine is absent, but because the off-balance line is wired to the *wrong* engine.

The decision, now made: **one model.** Retire the boolean as a kuzushi signal; route all off-balance — opponent-induced and self-inflicted — through the single source-agnostic buffer. This is smaller and cleaner than v0.1's imagined build. The load-bearing nuance: retiring the boolean is *not* deleting `body_state` (a 13-importer hub), and it requires first auditing every non-pull source of off-balance so those states emit into the buffer instead of vanishing.

---

## Part 1 — The grip war (design — preserved from v0.1, regrounded to code)

### 1.1 It is a war, not a race

Unchanged and confirmed. The grip exchange is a continuous two-sided contest; establishing one grip does not entitle you to the second for free; two grips on you is dangerous because it raises the opponent's pull capacity and your exposure. The audit confirms the mechanism for the *follower's* response already exists (§1.3); what the match log exposed — one fighter taking both grips uncontested while the other "finds nothing" — is a narration/sequencing symptom over a model that is more contested than it reads, not proof the model is a race. (Whether the *leader's* grab is too uncontested is a separate calibration question; see I-2.)

### 1.2 The counter-fighter who accepts the grips

The one genuinely net-new design element. A fighter built on countering may *choose* to accept the opponent's grips rather than strip them — two grips on you means the opponent has loaded base and posture into those grips, which is the exposure a counter exploits. "Two grips is dangerous" is true *unless you are set up to make the opponent pay.* This is an identity-expressing decision, weighted by counter skill and composure. The audit shows the response set has no such branch today (§1.3) — **accept-and-bait is the single addition the grip war needs.**

### 1.3 The grip-war response model — now grounded in actual code

v0.1 invented a response taxonomy. The audit found the real one already implemented in `grip_initiative.py` (HAJ-151), so the design defers to the code and adds one branch. The follower (the fighter who lost the initiative race) selects a response via a modulated weighted random draw. The five existing responses:

- **`CONTEST`** — frame the bicep / parry the hand / slap-down. Active disruption of the leader's grip.
- **`MATCH`** — mirror the leader's reach (sleeve-and-lapel symmetric). Establish your own grips in parallel.
- **`PURSUE_OWN`** — commit to your own preferred grip, ignore the leader's. A tempo trade.
- **`DEFENSIVE`** — frame-and-deny; no own grip seated. Pure defense.
- **`DISENGAGE`** — backstep, reset to `STANDING_DISTANT`. This is v0.1's "reset/break," already present.

Selection is a weighted draw off base weights `{CONTEST:1.0, MATCH:1.5, PURSUE_OWN:1.0, DEFENSIVE:0.7, DISENGAGE:0.5}`, modulated by body archetype (e.g. `EXPLOSIVE` ×1.8 on PURSUE_OWN, `GRIP_FIGHTER` ×1.6 on CONTEST), aggressive facet, loyalty-to-plan, fight_iq band, composure, stance matchup, clock-pressure role, and perception specificity.

**The addition: `ACCEPT_BAIT`** — deliberately do not strip or disengage; allow the leader's grips to stand while loading a counter. Base weight low; modulated *up* by counter skill, composure, and counter-archetype, *down* by clock pressure and fatigue. Per §1.2. This is the only response the war is missing.

**Documentation debt — now scoped to transcription.** This construct has no design doc; it lives only in the module header plus match wiring. The audit handed us its full behavior. The task is therefore not "design it" but "**transcribe the existing behavior into a design doc, then add `ACCEPT_BAIT`.**" See Task list, item A-1. Naming discipline: keep **"grip war"** as the design concept (the whole contested phenomenon) and name the code construct **"grip response selection"** (the follower's per-tick choice). They are different scopes; collapsing the names blurs the war into one of its mechanisms.

---

## Part 2 — The connective tissue is built; the work is the migration to one model

This replaces v0.1's "build the spine." Per the audit, the spine exists. What follows is the real, smaller, surgical job.

### 2.1 What is already true (the audit's verdict, condensed)

- **`PULL` emits kuzushi as a cause.** `match._compute_net_force_on` emits a `KuzushiEvent` into uke's buffer whenever the action is `PULL`, separate from any throw commit. `FOOT_ATTACK` is a parallel emitter. ✅
- **The decaying buffer and computed compromised state are real and complete.** Per-fighter buffer on `judoka.py`; 5-tick half-life decay; `kuzushi.compromised_state` sums decayed contributions into a vector + magnitude. ✅
- **Throws fire from the buffer.** The signature match's kuzushi dimension reads uke's decayed buffer; grip depth modulates force, it is not the firing precondition. ✅

### 2.2 What is wrong — two models in parallel, plus a third notion of "compromised"

Three things named "kuzushi/compromised" coexist, and that is the actual disorder:

1. **The buffer** (`kuzushi.compromised_state`) — uke's *accumulated, decaying, opponent-induced* physical compromise. The correct one. Drives throw signatures.
2. **The boolean** (`body_state.is_kuzushi`) — an *instantaneous, causeless* geometry flip ("CoM outside recoverable envelope"). Still drives the `[physics] off-balance` event and the defensive-pressure feed, and still backs a legacy throw-firing fallback. This is what makes off-balance (the t046 note) uncaused: it is fired by a predicate that by construction has no cause to report.
3. **The tori failed-throw state machine** (`compromised_state.py`, name-clashing with #1) — tori's *self-inflicted* compromise after a missed throw. A real third notion, currently living separate from the buffer.

"One model" means resolving all three into the buffer as the single sink.

### 2.3 The decision: retire the boolean as a signal, route everything through the buffer

Made. The reasoning matters because it dictates the work. The steelman for *keeping* the boolean is that the buffer only knows about off-balance someone *did to uke* — but off-balance has causes that aren't opponent pulls (the t075 "off-balance on one leg" after a whiffed uchi-mata; nobody pulled him there). Retire the boolean naively and those states silently vanish.

The reason it loses anyway: the architecture already specifies the buffer as **source-agnostic** — it "doesn't care about source, only the event's vector, magnitude, and tick." So the fix is not a parallel uncaused signal; it is to make the non-pull causes **emit self-sourced kuzushi events into the same buffer.** Then every off-balance state has a cause the narration can name — even when the cause is "you overcommitted" — and the boolean has no unique job left. The boolean's true purpose was never "geometric truth"; it was "represent off-balance from any cause," and a source-agnostic buffer does that job *with* cause attribution the boolean never had.

### 2.4 The hidden prerequisite — the non-pull-sources audit

This is the real labor of the migration and must happen **before** the boolean is cut, or off-balance states disappear. Inventory every way a fighter becomes off-balance *without* an opponent pull, and give each a self-sourced (or resolution-sourced) kuzushi event:

- Failed throw landing tori on one leg / out of posture (the t075 case). This is where the **`compromised_state.py` tori state machine folds into the buffer** rather than remaining a third notion.
- Foot-attack recovery / the attacker briefly on one foot.
- Footwork stumbles and self-inflicted balance loss.
- The throw resolution's own kake phase, where applicable.

Each becomes a `KuzushiSource` value other than `PULL`/`FOOT_ATTACK` (e.g. `SELF_INFLICTED`, `THROW_RESOLUTION`). The buffer already accepts arbitrary sources; this is authoring emitters, not re-architecting the buffer.

### 2.5 The migration moves, in dependency order

1. **(Prerequisite)** Run the §2.4 non-pull-sources audit; make each source emit into the buffer. Fold `compromised_state.py`'s tori state into the buffer here.
2. **Rewire the off-balance event and defensive-pressure feed** to read `kuzushi.compromised_state` (a threshold/direction on the buffer) instead of `body_state.is_kuzushi`. This is the direct fix for the t046 "off-balance has no cause" note.
3. **Retire the legacy `actual_signature_match` fallback** (the two-factor path for throws lacking a worked template). This moots the perception.py:148 attacker/defender `leg_strength` bug for free — that bug lives only in the path being deleted.
4. **Retire `is_kuzushi` as a kuzushi signal.** Keep the geometry function if any *non-kuzushi* consumer needs CoM/envelope math; cut its role as the off-balance trigger.

### 2.6 The load-bearing caveat — do not delete `body_state`

`body_state.py` is a hub: ~13 modules import it; posture vulnerability feeds the pull-force formula; CoM/envelope geometry is foundational substrate. **Retiring the boolean means retiring `is_kuzushi`'s *role as a kuzushi signal*, not deleting the module or its geometry.** If any refactor reframes this as "rip out body_state," stop it — that is a different and catastrophic change. Retire the predicate's job; keep the body.

---

## Part 3 — Telegraph and narration (both corrected: partly built)

### 3.1 Telegraph — exists, verify and wire (not build)

v0.1 said anticipation ("He's going for the O-soto!") required building a telegraph event. The audit found **`intent_signal.py` (HAJ-149, "pre-commit intent signals / advance-notice telegraph") already exists and is imported into `match.py`**, and `reaction_lag.py` (HAJ-149/222) is actively connected and recently touched. So the substrate for anticipation is present. The match log nonetheless showed only a terse `[intent] → throw_commit` firing adjacent to the commit, with no lean-forward.

The corrected task is therefore **verify-and-wire, not build**: determine whether `intent_signal` actually emits an advance-notice event before commit, how far ahead, and whether the narration layer marks it. The likely gap is one of three — it fires but the prose doesn't surface it richly; it fires only for counters (the log's intent lines cluster around counters); or it fires too close to commit to read as anticipation. The sumi-gaeshi foreshadowing (t026) leans additionally on `intent.py` (HAJ-135, multi-tick sequence planning), which also already exists. So both anticipation requests are wiring/surfacing questions over existing substrate.

### 3.2 Narration — already mid-migration, finish the decoupling

v0.1 said "build a data-driven narration layer." The audit found narration is **already split**: `throw_narration.py` (HAJ-221) is genuinely data-driven, loading `data/throw_narration.yaml` for throw-resolution phases; but the working mat-side voice (`narration/altitudes/mat_side.py`) authors most sentences as **inline f-strings**, and a few raw strings live directly in `match.py` (the `[physics] off-balance` line among them). The two sentences the reviewer wanted to edit ("secures the first grip — finds nothing", "commit lands crisp and explosive") are inline in `mat_side.py`.

So the task is **finish the migration**, not start it: extend the data-driven pattern from throw-resolution to the mat-side grip/movement/state prose, so the strings the reviewer wants to tune live in YAML keyed by event type, mirroring `throw_narration.yaml`. The honest caveat from v0.1 still holds — variety and bloat-cutting on *existing* events can begin now; anticipation and grip-battle density depend on Part 2/3.1 emitting the events first.

---

## Part 4 — Issue inventory (reworked against current code status)

Each item now carries a **status** drawn from the audit. Buckets reordered by what the corrected picture makes urgent.

### Task Zero — the one-line edit that stops the lying

- **Z-1 — Fix `grip-as-cause.md`'s status header.** It reads "Status: Design specification. No code yet." The chain is built and wired. This stale line already cost us a wrong premise (v0.1 Part 2). Change it to reflect built-and-migrating status. *Status: trivial; do first.*

### Bucket A — Grip war (design)

- **A-1 — Transcribe grip response selection into a design doc, add `ACCEPT_BAIT`.** *Status:* construct fully exists in `grip_initiative.py`; audit quoted its full behavior. Task is transcription + one new branch (§1.2/1.3), not design from scratch.
- **A-2 — Calibration: is the leader's grab too uncontested?** *Status:* addressed in HAJ-224. Three calibration changes landed: (1) strips degrade by a margin-scaled number of steps so a grip can be broken from any depth, not only after a forced four-step walk-down; (2) a universal archetype-weighted strip propensity in the driving rung so every fighter strips mid-exchange (GRIP_FIGHTER most), not only in the pre-deepen opening; (3) the leader seats a single lead grip at engagement with the off-hand following a later, contestable beat (`OFF_HAND_SEAT_LAG_TICKS`). Strip/partial-strip narration is the sibling ticket HAJ-225.

### Bucket B — The one-model migration (the real spine work — was "build", now "migrate")

- **B-1 — Non-pull-sources audit + emitters.** *Status:* prerequisite for everything else in B. Per §2.4. Fold `compromised_state.py` tori state into the buffer.
- **B-2 — Rewire off-balance event + defensive-pressure feed to the buffer.** *Status:* the t046 fix. Depends on B-1.
- **B-3 — Retire the legacy `actual_signature_match` fallback.** *Status:* moots the perception.py:148 bug. Enumerate live `ThrowID`s vs `worked_template_for` first (audit ambiguity #2) to confirm nothing in use depends on the fallback.
- **B-4 — Retire `is_kuzushi` as a kuzushi signal** (keep geometry per §2.6). *Status:* last move; depends on B-1/B-2/B-3.

### Bucket C — Telegraph (verify-and-wire — was "build")

- **C-1 — Verify `intent_signal` behavior and surface it.** *Status:* substrate exists and is wired; determine why anticipation doesn't read in the log (timing / counter-only / un-narrated) and fix the gap. Per §3.1.
- **C-2 — Surface the `intent.py` sequence plan** (sumi foreshadowing). *Status:* substrate exists; surfacing question.

### Bucket D — Narration (finish the migration — was "build")

- **D-1 — Extend data-driven narration to mat-side grip/movement/state prose.** *Status:* grip-war slice landed in HAJ-225. Added `data/grip_narration.yaml` + `src/grip_narration.py` (mirroring the `throw_narration.py` pattern) and migrated the inline mat-side strip / first-grip f-strings to it: successful strips now read as partial ("drags the lapel grip down to a pocket") or full ("rips the lapel grip loose"), distinct from the failed-strip "can't budge it"; the first-grip tick has a contested variant. Movement/state prose migration remains future work.
- **D-2 — Cut the "crisp and explosive" bloat / give grip-establish variety.** *Status:* content edit; most meaningful after D-1 and after A-2 makes the underlying event read as contested.

### Bucket E — Rendering / ordering bugs (untouched by audit; stand as-is)

- **E-1 — Within-tick causal ordering on ne-waza entry** (shrimp before "ground is on"). Same class as the HAJ-32/33 throw-ordering fix.
- **E-2 — Within-tick ordering of overlapping throw resolutions** (t052 nonsense).
- **E-3 — Phase gating: stand-up `grip_init` firing in ground state** (t027).
- **E-4 — Ground role legibility: GUARD_TOP must name top vs bottom** (t027).

### Bucket F — Ne-waza reachability (decision; stands)

- **F-1 — Decide guard→dominant bridge vs direct-entry-only.** *Status:* unchanged. Catalog authors only two dominant positions; guard entries dead-end. Recommendation remains direct-entry-only for Ring 1. The audit's note that `ne_waza_consumption.py` is real and wired confirms HAJ-220 works — it's reachability, not a loader bug.

### Bucket G — Parked design questions

- **G-1 — Movement / grip interleaving** (t035). Post-calibration; `action_selection` sequencing; connects to `DISENGAGE`.
- **G-2 — Commit gating during a scored-against resolution** (t052). Park until B lands.

### Bucket H — Cheap adds

- **H-1 — "Hajime!" after matte** (t030).
- **H-2 — "Both look to their coaches" seam** (t030) — placeholder that grows into the §6.5.6 sensei coaching window.

### Bucket I — Process / hygiene (the audit closed I-1; new items surfaced)

- **I-1 — Doc-vs-code audit. ✅ DONE** — this is `AUDIT_MAP.md`.
- **I-2 — `throw_signature.py` has no dedicated test** despite being grip-as-cause-critical. Add one; it is the most important untested module in the chain.
- **I-3 — Dead/orphan candidates:** `viewer_capture.py` (production-unreferenced; wire or retire) and `narration/bench_voice.py` (self-described "scaffold", no consumer; keep or cut). Small, deliberate calls.
- **I-4 — `position_machine.py`** — 1 importer, 0 test coverage. Decide if `match.py`/`ne_waza.py` absorbed its job (audit ambiguity #6).
- **I-5 — Pytest can't run normally** on this machine (Python 3.14 capture-teardown crash). Pin versions or add `-s` to the project test command so the suite is runnable as documented.
- **I-6 — Known test failure** `test_higher_fight_iq_yields_larger_magnitude`: cause now known — `pull_kuzushi_magnitude` reads the `pull_execution` axis, not `fight_iq`, so fighters differing only in fight_iq produce identical magnitudes. Decide whether the test encodes an abandoned intention (update the test) or the code has a gap (route some fight_iq into the magnitude).
- **I-7 — `design-notes/Hajime Design System/*.py`** — 9 reference snapshots duplicating engine filenames. Confirm they stay as artifacts, not drift into stale confusion.

---

## Part 5 — Sequencing: corrected priority stack

The shape changed completely. v0.1 said "build the spine first." The spine is built. The corrected order:

**Do immediately, no dependencies:** Z-1 (fix the status line — one minute, stops the lying). The rendering bugs E-1..E-4. The hygiene calls I-2..I-7. A-1 (transcribe the grip-response design). These are all independent and most are cheap.

**The real work — the one-model migration (Bucket B), in strict order:** B-1 (non-pull-sources audit + emitters; fold in the tori state machine) → B-2 (rewire off-balance to the buffer) → B-3 (retire the legacy fallback) → B-4 (retire the boolean signal). B-1 is the load-bearing prerequisite; nothing else in B is safe before it, because cutting the boolean before the non-pull sources emit into the buffer deletes real off-balance states.

**Verify-and-wire, after a quick read:** C-1/C-2 (telegraph) and D-1 (narration migration). These need a verification read first to size them, since both turned out partly built.

**Decisions, not builds:** F-1 (ne-waza reachability). Make the call.

**Parked until after B / after calibration:** G-1, G-2, D-2. (A-2 landed in HAJ-224.)

**The single recommended first action:** Z-1, then B-1. Z-1 because a lying status header is actively dangerous to planning. B-1 because it is the prerequisite that gates the entire migration, and the migration is now the load-bearing work — not a build, a consolidation of three parallel notions of "compromised" into the one source-agnostic buffer the architecture always wanted.

---

## Part 6 — How this fits the corpus

- **`grip-as-cause.md`** — parent. Z-1 fixes its status header. The grip-response design (A-1) is a new sibling section or doc transcribed from `grip_initiative.py`. The migration (Part 2) finishes what the parent's §11 specified and the engine already largely built.
- **`physics-substrate.md`** — owns `body_state`/CoM/envelope. Part 2.6 protects it: the geometry stays; only `is_kuzushi`'s role as a kuzushi signal is retired. Part 3.3 should eventually name the buffer as the source of the compromised state it references.
- **`compromised_state.py` vs `kuzushi.compromised_state`** — the name clash is real and is folded into the migration (B-1): the tori failed-throw state becomes a self-sourced contribution to the one buffer, not a third parallel notion.
- **`ne-waza-substrate.md`** — F-1 unchanged; the two authored dominant positions and deferred guard-passing are the documented cause of the reachability dead-end.
- **`ne-waza-vocabulary-system-addendum...md`** — §6.5.6 (sensei coaching) is what H-2's placeholder grows into.
- **`AUDIT_MAP.md`** — the evidence base. Every code claim in Part 2/3 traces to a file:line there.

---

*v0.2. The premise is corrected: the spine is built, the work is consolidation. One model, retire the old, route every off-balance through the single buffer. Start with Z-1, then B-1.*
