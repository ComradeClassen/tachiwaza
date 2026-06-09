# AUDIT_MAP.md

Read-only structural audit. No code was modified. Generated 2026-05-28.
Scope: `src/` (live engine), `tests/`, repo-root entry points. GDScript: **none found** — there are no `.gd` files and no `project.godot` in the tree, so the "every GDScript file" deliverable is empty. The only Godot touchpoint is `src/run_match.py` (a JSON-in/log-out entry point a Godot calibration tool calls).

A second copy of nine engine files exists under `design-notes/Hajime Design System/*.py` (all last touched 2026-04-26). Those are **reference/prototype snapshots**, not the live engine, and are listed separately at the end. A git **worktree** at `.claude/worktrees/lucid-meninsky-5d561c/` mirrors the whole repo; it is excluded from every count below.

---

> **Refresh (2026-05-31) — kuzushi-as-cause migration completed.**
> The central tension this audit flagged (two parallel "kuzushi" models running
> side by side) has been resolved. There is now **exactly one** kuzushi model
> wired into the engine: the decaying kuzushi buffer
> (`kuzushi.compromised_state`). It drives the off-balance `KUZUSHI_INDUCED`
> signal, the defensive-pressure feed, throw signatures, and failed-throw
> self-kuzushi.
> - The off-balance trigger was rewired to read the buffer
>   (`Match._check_off_balance`, magnitude threshold `OFF_BALANCE_MAGNITUDE_THRESHOLD`).
>   The old `match._is_kuzushi` wrapper is **deleted**; `body_state.is_kuzushi`
>   and the recoverable-envelope geometry remain as **latent CoM math** (unit-
>   tested in `test_body_state`, no live engine consumer).
> - The legacy two-factor `actual_signature_match` fallback is **retired**
>   (and the attacker-leg-strength-into-uke's-envelope oddity with it).
> - `SUMI_GAESHI` now has a worked template — **all 13 ThrowIDs are templated**.
>
> Inline §2 and §3 below are updated to current reality, and open ambiguities
> #1–#3 are marked resolved. The dated module table and "tension" notes are
> left as the original 2026-05-28 snapshot for historical context. Current
> suite: **1485 tests, 1 failure** — still only
> `test_higher_fight_iq_yields_larger_magnitude` (pre-existing, unrelated).

---

## Test suite result

- **Total collected: 1447 tests** (`tests/` only). **1446 passed, 1 failed, 0 errors, 0 skipped.** (JUnit: `tests=1447 failures=1 errors=0 skipped=0`, wall 13.2s.)
- **Only failing test: `tests/test_kuzushi_pull_emission.py::TestPullKuzushiMagnitude::test_higher_fight_iq_yields_larger_magnitude`** — `AssertionError: assert 27.93 > 27.93`. Two fighters whose only difference is `fight_iq` produce **identical** pull-kuzushi magnitudes, because `pull_kuzushi_magnitude` now reads the `pull_execution` skill-vector axis (not `fight_iq`) for its technique term (see [src/kuzushi.py:477](src/kuzushi.py)). This is the expected, known, single pre-existing failure — **it is still the only failure**.

### Note on how the suite was run
`python -m pytest` crashes during pytest's capture **teardown** on this machine (Python 3.14 + pytest fd-capture: `ValueError: I/O operation on closed file` in `_pytest/capture.py`), which suppresses the normal terminal summary and reports "no tests ran". Tests run correctly with capture disabled. Counts above come from a JUnit XML report (`--junitxml`, written before the crashing teardown):
```
python -m pytest tests/ -p no:cacheprovider -s -q --junitxml=report.xml
```
`report.xml` and `test_run.log` were written to the repo root by this audit and can be deleted.

---

## Module inventory

Descriptions are taken verbatim-ish from each file's top-of-file comment / primary definitions. Dates are `git log -1` last-commit dates. **⚠ = not touched since ~2026-05-07 (stale; see staleness section).**

### `src/` — physics-substrate engine core

| Module | Date | What it appears to do |
|---|---|---|
| `body_state.py` | 2026-05-31 | Physics Part 1: `BodyState` + geometry; recoverable-envelope + `is_kuzushi` (CoM-outside-envelope predicate, now **latent geometry only** — retired as a kuzushi signal 2026-05-31), posture derivation. |
| `grip_presence_gate.py` ⚠ | 2026-04-21 | HAJ-36: formal grip-presence commit gate (precondition layer on throw commit). |
| `commit_motivation.py` ⚠ | 2026-04-24 | HAJ-67: non-scoring attack motivations as a typed concept (extends false-attack pathway). |
| `compromised_state.py` ⚠ | 2026-04-26 | Physics Part 6.3: failed-throw compromised-state spec (tori-side state machine after a missed throw). |
| `failure_resolution.py` ⚠ | 2026-04-26 | Physics 4.5/6.3: failure-outcome routing when a committed throw doesn't clear threshold. |
| `perception.py` | 2026-05-31 | Physics 3.5: actual-vs-perceived signature gap; `actual_signature_match` (**single worked-template path** since 2026-05-31; legacy two-factor fallback retired). |
| `throw_signature.py` ⚠ | 2026-04-26 | Physics 4.2: four-dimension signature match; `match_kuzushi_vector` reads uke's decayed buffer. |
| `counter_windows.py` ⚠ | 2026-04-27 | Physics 6.2: the three counter-windows as state regions. |
| `position_machine.py` ⚠ | 2026-04-27 | Position state machine: legal transitions, throw-possibility gating. |
| `skill_vector.py` ⚠ | 2026-04-27 | HAJ-137: fine-grained skill axes (`axis()` lookup w/ fight_iq fallback). |
| `vulnerability_window.py` ⚠ | 2026-04-27 | HAJ-134: vulnerability windows as first-class machine-readable data. |
| `body_part_events.py` ⚠ | 2026-04-28 | HAJ-145: `BodyPartEvent` emission layer (substrate for prose); crispness/modifier model. |
| `debug_inspector.py` ⚠ | 2026-04-28 | HAJ-20: calibration-observation overlay (off by default; `--debug`). |
| `recognition.py` ⚠ | 2026-04-28 | HAJ-144 #5/#6: recognition mechanic, computed post-commit. |
| `significance.py` ⚠ | 2026-04-28 | HAJ-144 #1: per-Event `significance` 0–10 scoring. |
| `grip_initiative.py` ⚠ | 2026-04-29 | HAJ-151: grip-race initiative scoring + **five-response cascade** (CONTEST/MATCH/PURSUE_OWN/DEFENSIVE/DISENGAGE). |
| `intent_signal.py` ⚠ | 2026-04-29 | HAJ-149: pre-commit intent signals (advance-notice telegraph). |
| `chase_decision.py` ⚠ | 2026-04-30 | HAJ-152: tori's post-score (waza-ari) chase decision. |
| `defense_decision.py` ⚠ | 2026-04-30 | HAJ-152: uke's post-score defense decision. |
| `judoka.py` ⚠ | 2026-04-30 | Three-layer Judoka model (Identity/Capability/State); owns `kuzushi_events` buffer. |
| `skill_compression.py` ⚠ | 2026-04-30 | Physics 6.1: skill-compression of the tsukuri-kuzushi-kake sequence (N-tick compression). |
| `actions.py` ⚠ | 2026-05-01 | Physics 3.2: the action space; `ActionKind` enum incl. `PULL`, foot-attack kinds. |
| `body_part_decompose.py` ⚠ | 2026-05-02 | HAJ-145: decompose engine actions → `BodyPartEvent` sequences (`decompose_pull`, etc.). |
| `enums.py` ⚠ | 2026-05-02 | All shared enumerations (single file to avoid circular imports). |
| `force_envelope.py` ⚠ | 2026-05-02 | Physics 2.3/2.4: per-grip-type force envelopes; `grip_strength`, `delivered_pull_force`. |
| `grip_graph.py` ⚠ | 2026-05-02 | Bipartite grip graph (`GripEdge`, depths, modes, `edges_owned_by`). Foundational data structure. |
| `intent.py` ⚠ | 2026-05-02 | HAJ-135: multi-tick planning / sequence intent (combo pulls). |
| `kuzushi.py` ⚠ | 2026-05-02 | **Phase A.1 / HAJ-130**: event-driven kuzushi — decaying event buffer, `compromised_state`, `pull_kuzushi_event`, `foot_attack_kuzushi_event`. Core of grip-as-cause. |
| `throw_templates.py` ⚠ | 2026-05-02 | Physics 4: Couple/Lever templates + four-dimension signature framework. |
| `throws.py` ⚠ | 2026-05-02 | Throw/combo data types, `JudokaThrowProfile`, global throw registries. |
| `worked_throws.py` ⚠ | 2026-05-02 | Physics 5: parameterized template instances (the 12 worked throws); `worked_template_for`. |
| `match_viewer.py` | 2026-05-10 | HAJ-125/126: top-down match viewer (pygame render layer; pause/step/scrub/inspect). |
| `viewer_capture.py` | 2026-05-10 | Reusable capture/data layer for the dev viewer (extracted from phase1_viewer). |
| `chronicle.py` | 2026-05-12 | Ring 2 chronicle substrate (HAJ-200): the world's persistent memory. |
| `chronicle_cli.py` | 2026-05-12 | HAJ-203: developer-facing chronicle dump CLI (argparse). |
| `orchestrator.py` | 2026-05-12 | Ring 2 year-tick orchestrator (HAJ-202): `advance_year`. |
| `resolver.py` | 2026-05-12 | Ring 2 abstracted match resolver (HAJ-201): collapses a match → `MatchOutcome`. |
| `catalog_validator.py` | 2026-05-21 | HAJ-211: tachiwaza catalog validation CLI (wraps technique_catalog loader). |
| `ne_waza_catalog.py` | 2026-05-21 | HAJ-215: schema + loader for ne-waza vocabulary substrate. |
| `ne_waza_catalog_validator.py` | 2026-05-21 | HAJ-215: ne-waza catalog validation CLI (sibling to catalog_validator). |
| `technique_catalog.py` | 2026-05-21 | HAJ-204/213: schema + loader for technique vocabulary substrate. |
| `action_selection.py` | 2026-05-22 | Physics 3.3: v0.1 priority-ladder decision function; `select_actions`. PULL is the canonical primary drive. |
| `availability.py` | 2026-05-22 | HAJ-207: Stage-1 availability filter + minimal Stage-2 selection (catalog-driven gating). |
| `defensive_desperation.py` | 2026-05-24 | HAJ-35: defensive desperation mode. |
| `execution_quality.py` | 2026-05-24 | Physics 4.2.1: execution quality as first-class; `compute_execution_quality`, `commit_threshold_for`, `band_for`. |
| `reaction_lag.py` | 2026-05-24 | HAJ-149/222: fight_iq-modulated reaction lag (recalibrated against seed playtest). |
| `referee.py` | 2026-05-24 | Referee personality → Matte timing + scoring. |
| `throw_narration.py` | 2026-05-24 | **HAJ-221: data-driven** body-part narration for throw resolution phases (loads `data/throw_narration.yaml`). |
| `main.py` | 2026-05-27 | Entry point: builds Tanaka/Sato + referee and runs a match. |
| `match.py` | 2026-05-27 | **Physics Part 3: the tick loop IS the match.** Wires force, kuzushi emission, throw commit/resolve, ne-waza, narration. ~4800 lines. |
| `ne_waza.py` | 2026-05-27 | Ne-waza (ground) system: position progressions, osaekomi clock, commitment chains, escapes. |
| `ne_waza_consumption.py` | 2026-05-27 | HAJ-220: minimum-viable consumption of the ne-waza substrate (sibling to availability). |
| `run_match.py` | 2026-05-27 | Entry point invoked by the Godot debug calibration tool (HAJ-150): JSON config → event log. |

### `src/narration/` — narration package (HAJ-144)

| Module | Date | What it appears to do |
|---|---|---|
| `narration/__init__.py` ⚠ | 2026-04-28 | Package public API re-exports (MatSideNarrator, Reader, Voice, builders, WORD_VERBS, BenchProfile). |
| `narration/reader.py` ⚠ | 2026-04-28 | HAJ-144 #4: `Reader` (threshold, voice) abstraction. |
| `narration/word_verbs.py` ⚠ | 2026-04-28 | HAJ-144 C / HAJ-147: engine-verb → prose-word-verb mapping (novice/neutral/high registers). |
| `narration/bench_voice.py` ⚠ | 2026-04-28 | HAJ-144 #12: bench-voice scaffold (BenchProfile, VocabularyDepth). |
| `narration/altitudes/__init__.py` ⚠ | 2026-04-28 | Four altitude readers as separate modules. |
| `narration/altitudes/broadcast.py` ⚠ | 2026-04-28 | Broadcast-desk altitude voice. |
| `narration/altitudes/review.py` ⚠ | 2026-04-28 | Simulated-review altitude voice (past tense, summary). |
| `narration/altitudes/stands.py` ⚠ | 2026-04-28 | Stands / announcer altitude voice. |
| `narration/altitudes/mat_side.py` ⚠ | 2026-05-02 | HAJ-144/147: mat-side reader (working altitude); `MatSideNarrator` produces the match-clock log. **Authors most inline prose strings.** |

### `tests/` (90 files)
All 90 test files live flat in `tests/` plus `tests/fixtures/` (`__init__.py`, `seed_worlds/__init__.py`, `seed_worlds/tiny_nj.py`). They split into name-matched unit tests (`test_<module>.py`) and feature-tracked integration tests (`test_hajNNN_*.py`). Not individually described here; coverage mapping is in the next section.

---

## Module-level import / call graph

Intra-`src` dependency edges (who imports whom), derived from import statements. Trivial deps (`enums`, `judoka`, `throws`, `grip_graph` — imported almost everywhere) are the shared substrate; the interesting edges are the engine wiring.

```
main          → match, match_viewer, judoka, referee, body_state, throws, debug_inspector
run_match     → match, judoka, referee, body_state, throws            (Godot entry)
match         → action_selection, actions, perception, throw_signature(via perception),
                throw_templates, worked_throws, kuzushi, grip_graph, grip_initiative,
                force_envelope, body_state, body_part_decompose, body_part_events,
                compromised_state, counter_windows, vulnerability_window, failure_resolution,
                execution_quality, skill_compression, reaction_lag, recognition,
                commit_motivation, chase_decision, defense_decision, defensive_desperation,
                intent_signal, position_machine, significance, referee, narration,
                ne_waza, ne_waza_catalog, technique_catalog, throw_narration
action_selection → actions, availability, perception, worked_throws, grip_presence_gate,
                   kuzushi, intent, compromised_state, commit_motivation, technique_catalog
perception    → throw_signature(signature_match), worked_throws, body_state(is_kuzushi), grip_graph
throw_signature → throw_templates, force_envelope, kuzushi(compromised_state, KUZUSHI_PER_*), body_state
kuzushi       → force_envelope(grip_strength), skill_vector(axis), grip_graph, body_state, actions
worked_throws → throw_templates, throws
intent        → action_selection, actions, skill_vector, grip_graph
counter_windows → vulnerability_window, skill_compression, skill_vector, execution_quality,
                  defensive_desperation, worked_throws, body_state
failure_resolution → action_selection, compromised_state, throw_signature, throw_templates
recognition   → compromised_state, kuzushi, throw_templates, body_state
narration.*   → body_part_events, significance, match, grip_graph (altitudes ← narration.reader, narration.word_verbs)
ne_waza       → ne_waza_catalog, ne_waza_consumption, grip_graph, referee
Ring 2:  orchestrator → chronicle, resolver, technique_catalog ;  resolver → chronicle ;
         chronicle_cli → chronicle, orchestrator, fixtures
catalog tooling: catalog_validator → technique_catalog, ne_waza_catalog ;
                 ne_waza_catalog_validator → ne_waza_catalog
```

**Most-imported (hub) modules** (src + tests importer counts): `body_state` (13/76), `grip_graph` (25/61), `judoka` (32/10), `enums` (34/69), `throws` (23/45), `match` (15/67), `referee` (4/68). These are the load-bearing substrate.

### Candidate dead / unreferenced

**Be conservative** — entry points, CLI tools, dynamic/string dispatch, and package-relative imports make several things *look* unreferenced when they are not. Findings:

**Genuinely unreferenced by any `src/` module (real candidates):**
- **`src/viewer_capture.py`** — no `src/` module imports it. `match_viewer.py` is the canonical viewer and does **not** import it; the only mention in engine code is a *comment* at [src/match.py:1210](src/match.py). It is imported by 3 test files. So it is production-unreferenced but test-covered — likely a leftover from the `phase1_viewer` extraction. **Worth your judgement.**
- **`src/narration/bench_voice.py`** (`BenchProfile`, `VocabularyDepth`) — re-exported in `narration/__init__.py`'s public API but **no engine, viewer, or other src module consumes it**. Its own docstring calls it a "scaffold." Candidate dormant feature.

**Looked unreferenced but are NOT (false positives — do not treat as dead):**
- `narration/reader.py`, `narration/word_verbs.py`, `narration/altitudes/{mat_side,stands,review,broadcast}.py` — my bare-name importer scan reported 0 src importers, but they are all imported via **package-qualified** paths (`from narration.reader import …`, `from narration.altitudes.mat_side import …`) in `narration/__init__.py` and `narration/altitudes/__init__.py`, and `match.py` imports `narration`. Fully live.
- `main.py`, `run_match.py` — **entry points** (run as `__main__` / invoked by external Godot tool). Expected to have no importers.
- `catalog_validator.py`, `ne_waza_catalog_validator.py`, `chronicle_cli.py` — **CLI tools** (argparse `__main__`). Expected to have no src importers; each has a test.
- `debug_inspector.py` — imported by `match.py` (1 src importer) and gated behind `--debug`.
- `position_machine.py` — imported by 1 src module but **0 test files** (see coverage gaps); not dead, but lightly exercised.

**Function/class-level dead code** was **not** exhaustively traced (would require a call-graph tool). The one concrete signal surfaced: in `kuzushi.py`, `seed_kuzushi_from_velocity` is documented as **test-fixture-only** ("Production code does NOT call this", [src/kuzushi.py:188](src/kuzushi.py)) — intentional, not dead. String-based dispatch worth knowing about: `action_selection` and `intent_signal` use string keys (`"PULL"`, `SETUP_PULL`), and throw lookups go through `THROW_DEFS`/`THROW_REGISTRY` dicts keyed by `ThrowID` — these can hide references from a naive grep.

### Test-coverage presence (presence, not %)

Modules **with** a name-matching dedicated test file (`test_<module>.py` or close): `body_state, grip_presence_gate, kuzushi` (+`test_kuzushi_pull_emission`, `test_kuzushi_signature_read`), `compromised_state, counter_windows, failure_resolution, skill_vector, skill_compression, vulnerability_window, execution_quality, commit_motivation, defensive_desperation, reaction_lag, worked_throws, throw_templates, body_part_events, technique_catalog, ne_waza_catalog, catalog_validator, chronicle, chronicle_cli, resolver, orchestrator, grip_initiative, grip_graph`(`test_grips.py`)`, narration`(`test_narration.py`)`, intent`(`test_intent_planning.py`)`, force_envelope`(`test_force_model.py`)`, match_viewer`.

Modules with **no dedicated test file** (many are covered indirectly by `test_hajNNN_*` feature tests or the large `match`-driven integration suites — noted in parens):
- `action_selection` (indirect: haj207, intent_planning)
- `actions` (indirect)
- `availability` (test_haj207_stage1_availability)
- `body_part_decompose` (indirect via narration/body-part tests)
- `chase_decision`, `defense_decision` (test_haj152)
- `ne_waza` (test_haj185), `ne_waza_consumption` (test_haj220), `ne_waza_catalog_validator` (indirect via ne_waza_catalog)
- `throw_narration` (test_haj221_presentation)
- `throw_signature` (indirect: kuzushi_signature_read, backfilled_throws — **no dedicated `test_throw_signature.py`** despite being grip-as-cause-critical)
- `perception`, `recognition`, `intent_signal`, `significance` (indirect only)
- `referee` (no dedicated test; imported by ~68 test files as fixture)
- `judoka`, `main`, `match` (no dedicated test; `match` has heavy integration coverage, `main` is a harness)
- **`position_machine`** — no dedicated test **and** 0 test-file importers: the thinnest-covered engine module.
- **`debug_inspector`** — no test, only `--debug` path.
- `enums`, `throws` — pure data; no dedicated test (data-shape asserted indirectly).
- `viewer_capture`, `narration` submodules `reader`/`word_verbs`/`bench_voice` — no dedicated file (reader/word_verbs partially covered via `test_narration`; `bench_voice` appears untested).

### Not touched in 3+ weeks (since ~2026-05-07)

This is the "week-one thinking that may not have legs" signal, surfaced as data only. **The entire grip-as-cause / signature / throw core is in this stale set**, while the surrounding harness (`match.py`, `main.py`, ne-waza, viewer, Ring 2, catalogs) is recent. That gap is the headline.

Stale `src/` modules (last commit ≤ 2026-05-02):
```
2026-04-18  body_state.py
2026-04-21  grip_presence_gate.py
2026-04-24  commit_motivation.py
2026-04-26  compromised_state.py  failure_resolution.py  perception.py  throw_signature.py
2026-04-27  counter_windows.py  position_machine.py  skill_vector.py  vulnerability_window.py
2026-04-28  body_part_events.py  debug_inspector.py  recognition.py  significance.py
            narration/__init__.py  narration/reader.py  narration/word_verbs.py
            narration/bench_voice.py  narration/altitudes/{__init__,broadcast,review,stands}.py
2026-04-29  grip_initiative.py  intent_signal.py
2026-04-30  chase_decision.py  defense_decision.py  judoka.py  skill_compression.py
2026-05-01  actions.py
2026-05-02  body_part_decompose.py  enums.py  force_envelope.py  grip_graph.py  intent.py
            kuzushi.py  throw_templates.py  throws.py  worked_throws.py
            narration/altitudes/mat_side.py
```
**Recent** (touched after 2026-05-07, NOT stale): `match.py, main.py, ne_waza.py, ne_waza_consumption.py, run_match.py` (05-27); `action_selection.py, availability.py` (05-22); `defensive_desperation.py, execution_quality.py, reaction_lag.py, referee.py, throw_narration.py` (05-24); `catalog_validator.py, ne_waza_catalog.py, ne_waza_catalog_validator.py, technique_catalog.py` (05-21); `chronicle*.py, orchestrator.py, resolver.py` (05-12); `match_viewer.py, viewer_capture.py` (05-10).

> Tension to note (data, not judgement): `match.py` (05-27) actively wires `kuzushi.py`, `throw_signature.py`, `throw_templates.py`, `worked_throws.py`, `perception.py` — all frozen at 04-26→05-02. The wiring is being maintained; the symbolic core it calls has not been touched in a month.

---

## Grip subsystem archaeology

The B-1 question: how much of the **grip-as-cause** symbolic chain (PULL → kuzushi event → decaying buffer → compromised state → signature match → throw fires) actually exists in code, versus the older inverted model (throw fires → kuzushi induced as a side effect; off-balance as a direct state flip). Verdict up front: **the grip-as-cause chain is largely built and wired, but the OLD model still co-exists alongside it in two specific places** (the "off-balance" event and a legacy `actual_signature_match` fallback path). Details with code:

### 1. Is there a real PULL action that emits a kuzushi event (separate from a throw committing)?

**Yes.** PULL is a first-class `ActionKind` ([src/actions.py:47](src/actions.py)), is the canonical kuzushi-driving action ([src/actions.py:120-122](src/actions.py)), and is issued as the primary drive by the action selector ([src/action_selection.py:282](src/action_selection.py): "Plans never preempt the primary action (the standard PULL drive)").

A PULL emits a `KuzushiEvent` into uke's buffer **inside the per-tick force computation**, entirely separately from any throw commit. In `_compute_net_force_on` ([src/match.py:2892-2898](src/match.py)):
```python
# HAJ-131 — emit a KuzushiEvent into uke's buffer alongside the
# continuous physical force above. Only PULL emits in this ticket; ...
if act.kind == ActionKind.PULL:
    event = pull_kuzushi_event(
        attacker=attacker, edge=edge, victim=victim,
        pull_direction=act.direction, current_tick=tick,
    )
    if event is not None:
        record_kuzushi_event(victim, event)
```
`pull_kuzushi_event` ([src/kuzushi.py:487-521](src/kuzushi.py)) builds the event from `force = f(strength, technique, experience, grip_depth, uke_posture_vulnerability)` × self-cancellation factor, tagged `KuzushiSource.PULL`. FOOT_ATTACK is a parallel emitter ([src/match.py:3037-3051](src/match.py) → `foot_attack_kuzushi_event`, [src/kuzushi.py:641](src/kuzushi.py)).

So kuzushi is **emitted as a cause by PULL/FOOT_ATTACK actions**, not (only) as a throw side-effect. ✅ grip-as-cause.

### 2. Per-fighter decaying kuzushi-event buffer → compromised state? Or a direct off-balance flip?

**As of 2026-05-31: the buffer is the single model.** *(Original audit read "Both exist, for different consumers" — that has since been resolved by the migration; see below.)*

**The event-buffer model is real and complete.** Each `Judoka` owns a per-fighter buffer `kuzushi_events` (a `deque`, default factory `fresh_buffer()` with `maxlen=KUZUSHI_BUFFER_CAPACITY=20`; [src/kuzushi.py:160-169](src/kuzushi.py), wired on `judoka.py`). Decay is a 5-tick half-life ([src/kuzushi.py:88-100](src/kuzushi.py): `decay_factor(age) = 0.5 ** (age/5)`). The compromised state is **computed** by summing decayed event contributions ([src/kuzushi.py:124-154](src/kuzushi.py)):
```python
def compromised_state(events, current_tick) -> CompromisedState:
    rx = ry = total = 0.0
    for ev in events:
        d = decay_factor(current_tick - ev.tick_emitted)
        contribution = ev.magnitude * d
        rx += ev.vector[0] * contribution; ry += ev.vector[1] * contribution
        total += contribution
    mag = (rx*rx + ry*ry) ** 0.5
    return CompromisedState(vector=(rx,ry), magnitude=mag, total_decayed_magnitude=total)
```
This is consumed by the throw-signature layer (see §3) **and** by the off-balance signal (below).

**The off-balance signal now reads the same buffer (RESOLVED).** Each tick the kuzushi check emits a `KUZUSHI_INDUCED` "off-balance" event and feeds defensive pressure when a fighter's decaying buffer magnitude crosses a threshold — edge-triggered, with the dominant source named for narration ([src/match.py](src/match.py), `Match._check_off_balance` / `_emit_kuzushi_induced`):
```python
a_cs = compromised_state(self.fighter_a.kuzushi_events, tick)
a_kuzushi = a_cs.magnitude >= OFF_BALANCE_MAGNITUDE_THRESHOLD   # 70.0, calibrated
if a_kuzushi and not self._a_was_kuzushi_last_tick:
    # KUZUSHI_INDUCED event carries {magnitude, vector, source}; cause-named
    # description e.g. "[physics] X off-balance (pulled off balance)."
    self._defensive_pressure[...].record_kuzushi(tick)
```
The old direct CoM-envelope flip (`match._is_kuzushi` → `body_state.is_kuzushi`) **has been retired** as the off-balance signal. `body_state.is_kuzushi` ([src/body_state.py:275](src/body_state.py)) — "CoM projection outside recoverable_envelope" — remains **defined as latent geometry / CoM math** (unit-tested in `test_body_state`) but has **no live engine consumer**; `match._is_kuzushi` is deleted. So the off-balance event, the defensive-pressure feed, throw signatures, and failed-throw self-kuzushi all read the **one** decaying buffer. The two-parallel-notions tension the original audit recorded no longer exists.

### 3. Do throws fire from a signature match against accumulated kuzushi, or from a grip-depth precondition checked at commit time?

**Primarily from a signature match against the accumulated buffer** — with grip-presence used only as a coarse gate, not as the firing condition.

The commit resolver `_resolve_commit_throw` ([src/match.py:3186+](src/match.py)) computes throw quality from the signature, then execution quality from that ([src/match.py:3258-3275](src/match.py)):
```python
actual = actual_signature_match(throw_id, attacker, defender, self.grip_graph,
                                current_tick=tick)
...
commit_threshold = commit_threshold_for(throw_id)
eq = compute_execution_quality(actual, commit_threshold)
```
`actual_signature_match` → (for worked throws) `signature_match` ([src/throw_signature.py:530-560](src/throw_signature.py)), whose **kuzushi dimension reads uke's decayed buffer** ([src/throw_signature.py:117-168](src/throw_signature.py)):
```python
cs = compromised_state(defender.kuzushi_events, current_tick)
cv_body = _to_body_frame(cs.vector, facing)
...  # direction + magnitude scored vs the throw's KuzushiRequirement
```
Header at [src/throw_signature.py:110-113](src/throw_signature.py): *"This dimension now reads uke's decaying event buffer, not uke's current CoM-velocity snapshot. Throws fire because pulls composed, not because uke happens to be moving this tick."* ✅ grip-as-cause.

**Grip depth is not the firing precondition** — it feeds the *force-application* dimension ([src/throw_signature.py:174-243](src/throw_signature.py), via `delivered_pull_force(grip_type, depth_level, …)`) and the pull-magnitude formula, i.e. it modulates the score. The only hard preconditions checked at commit time are coarse gates, not depth: an **engagement-distance gate** (cannot commit in `STANDING_DISTANT` with no owned grip edges, [src/match.py:3220-3232](src/match.py)) and an **OOB gate** ([src/match.py:3241-3251](src/match.py)). A separate `grip_presence_gate.py` (HAJ-36) exists as a formal grip-presence gate and is consumed by `action_selection.py`, but it gates *whether the selector offers a commit*, not the signature firing math.

**Caveat (mixed model #2) — RESOLVED (2026-05-31).** `actual_signature_match` previously had a **legacy two-factor fallback** (grip-prereq + `is_kuzushi` boolean) for any throw without a worked template. That fallback has been **retired**: `SUMI_GAESHI` (the last template-less live throw) now has a worked template, so all 13 ThrowIDs route through the four-dimension `signature_match`, and the `else`-branch was deleted. A template-less `throw_id` now scores `0.0` (total-function guard). The attacker-leg-strength-into-uke's-`is_kuzushi` oddity flagged below lived only in that branch and is gone with it. `actual_signature_match` is now a single path:
```python
template = worked_template_for(throw_id)
if template is None:
    return 0.0                      # no scoring model — cannot fire
base = signature_match(template, attacker, defender, graph, current_tick=current_tick)
return _apply_stance_preference(base, throw_id, attacker, defender)
```

### 4. What is `grip_cascade` in code — definition, all branches, and what selects among them?

There are **two distinct things** the word "cascade" maps to. The construct you mean (the response-type set) is the **five-response grip cascade** in `grip_initiative.py` (HAJ-151).

**The five response kinds** ([src/grip_initiative.py:38-46](src/grip_initiative.py)):
```python
RESP_CONTEST    = "CONTEST"      # frame the bicep / parry the hand / slap-down
RESP_MATCH      = "MATCH"        # mirror leader's reach (sleeve-and-lapel symmetric)
RESP_PURSUE_OWN = "PURSUE_OWN"   # commit to own preferred grip; ignore leader
RESP_DEFENSIVE  = "DEFENSIVE"    # frame-and-deny; no own grip seated
RESP_DISENGAGE  = "DISENGAGE"    # backstep; reset to STANDING_DISTANT
ALL_RESPONSE_KINDS = (RESP_CONTEST, RESP_MATCH, RESP_PURSUE_OWN, RESP_DEFENSIVE, RESP_DISENGAGE)
```
So beyond `PURSUE_OWN` and `MATCH`, the other branches are **CONTEST, DEFENSIVE, DISENGAGE** — five total (the ticket's "five-response cascade").

**What selects among them:** a weighted random draw. The leader of the grip race is whoever wins an *initiative score* (`expected_initiative` / `sample_initiative`, [src/grip_initiative.py:164-222](src/grip_initiative.py) — a weighted sum of aggressive facet, archetype, fight_iq, composure, height, fatigue, familiarity, with Gaussian noise and a MATCHED/MIRRORED weight table). The **follower** then picks a response via `select_response` ([src/grip_initiative.py:376-418](src/grip_initiative.py)):
```python
weights = _modulate_response_weights(follower, leader, stance_matchup=…,
                                     clock_pressure_role=…, perception_specificity=…)
total = sum(weights.values()); roll = r.uniform(0.0, total)
for kind in ALL_RESPONSE_KINDS:
    cumulative += weights[kind]
    if roll <= cumulative: return GripResponseChoice(kind=kind, …)
```
`_modulate_response_weights` ([src/grip_initiative.py:276-373](src/grip_initiative.py)) starts from base weights `{CONTEST:1.0, MATCH:1.5, PURSUE_OWN:1.0, DEFENSIVE:0.7, DISENGAGE:0.5}` and multiplies by: body archetype (e.g. `EXPLOSIVE` ×1.8 on PURSUE_OWN; `GRIP_FIGHTER` ×1.6 on CONTEST), aggressive facet, loyal-to-plan, fight_iq band, composure, mirrored-stance bias, clock-pressure role, and perception specificity.

**Where the chosen branch is consumed:** `match.py` stages and resolves it. The staged-cascade machinery is `self._grip_cascade` / `self._grip_cascade_log` ([src/match.py:1244-1256](src/match.py)), resolved at [src/match.py:2223-2233](src/match.py): "the cascade resolver consumes `_grip_cascade` and may seat the follower's grips (MATCH/PURSUE_OWN), only some of them (CONTEST), none (DEFENSIVE), [or disengage]." Coach-facing prose for each branch is in `_grip_cascade_coach_prose` ([src/match.py:669-677](src/match.py)). The five `RESP_*` constants are imported into `match.py` at [src/match.py:86](src/match.py).

This construct has no design doc (confirmed: it lives only in `grip_initiative.py`'s own header + match wiring); the above is its full actual behavior for writing the retroactive design.

### 5. Where is narration generated? Inline strings or data-driven layer?

**Both — there are two narration layers, and the two sentences you quoted come from the inline one.**

**(a) Inline-string layer — `src/narration/altitudes/mat_side.py`** (the working "mat-side" altitude; `MatSideNarrator` produces the match-clock log). The exact sentences you asked about are authored here as inline f-strings:
- `"{leader} secures the first grip — {follower} reaches but finds nothing."` → [src/narration/altitudes/mat_side.py:242-248](src/narration/altitudes/mat_side.py) (templated comment at 226-227).
- `"{actor}'s commit fires off the line before uke can read it."` → [src/narration/altitudes/mat_side.py](src/narration/altitudes/mat_side.py), inside `_modifier_reveal_prose`, which branches on `BodyPartEvent` modifiers (`Crispness.CRISP` + `Speed.EXPLOSIVE`, etc.). Note HAJ-154 gated this so it only fires for `COUNTER_COMMIT` events now; HAJ-233 rewrote the branch strings from bare adjectives ("lands crisp and explosive") to consequence-bearing reads.

The sibling altitude voices (`stands.py`, `review.py`, `broadcast.py`, `bench_voice.py`) and the verb register `word_verbs.py` are also inline-string Python. So the **prose sentences themselves are authored inline in engine-adjacent Python**, driven by `BodyPartEvent` data the engine emits — a separate *module*, but not a data file.

**(b) Data-driven layer — `src/throw_narration.py` (HAJ-221)** loads `data/throw_narration.yaml` and selects body-part narration for throw **resolution** phases. This is the newer, genuinely data-driven path, and it co-exists with the inline mat-side prose. (The `"[physics] X off-balance."` line from §2 is a third source: an inline string built directly in `match.py`, not in the narration package.)

So: narration is **partly a separate data-driven layer (`throw_narration.py` + YAML) and partly inline f-strings (`narration/altitudes/*.py`, plus a few raw strings in `match.py`)** — it is mid-migration, not fully decoupled.

---

## Open ambiguities (need your judgement)

1. **Two coexisting kuzushi models — intended end state?** **RESOLVED (2026-05-31).** The direct `body_state.is_kuzushi` predicate was retired as a signal. The decaying buffer is now the single model: it drives throw signatures *and* the off-balance event / defensive-pressure feed (via `Match._check_off_balance`). `body_state.is_kuzushi` stays as latent CoM geometry with no live consumer.
2. **Legacy fallback reachability.** **RESOLVED (2026-05-31).** Enumerated: all 13 `ThrowID`s now have worked templates (`SUMI_GAESHI` was the last to migrate), so no live throw hit the two-factor path — which has since been deleted. The fallback is gone, not merely unreachable.
3. **Possible attacker/defender mix-up** at the old `perception.py` two-factor branch (`leg_strength` from the attacker fed into the defender's `is_kuzushi`). **RESOLVED (2026-05-31)** — moot: that branch was deleted with the legacy fallback, so the oddity no longer exists in the code.
4. **`viewer_capture.py` status** — production-unreferenced (only a comment in `match.py` and 3 tests reference it). Is it a deliberately-kept reusable layer, or dead since `match_viewer.py` became canonical? (Memory note says `viewer_capture` is the reusable capture layer, but no live viewer imports it.)
5. **`narration/bench_voice.py`** — public-API re-export but no consumer; scaffold or abandoned?
6. **`position_machine.py`** — 1 src importer, **0 test coverage**. Is the position state machine still authoritative, or has `match.py`/`ne_waza.py` absorbed its responsibilities?
7. **Pytest can't run normally on this machine** (Python 3.14 capture-teardown crash). Not a code issue per se, but it means the standard `pytest` invocation reports "no tests ran" — worth pinning pytest/Python versions or adding `-s` to the project's test command so the suite is runnable as documented.
8. **Function-level dead code** was not exhaustively traced (no call-graph tool run). The module-level candidates above are solid; intra-module unused functions would need a dedicated pass.
9. **`design-notes/Hajime Design System/*.py`** (9 files, all 2026-04-26: `enums, grip_graph, judoka, main, match, ne_waza, position_machine, referee, throws`) duplicate engine filenames. Confirmed they are reference snapshots, not imported by `src/` — but you should confirm they're intended to stay as design artifacts rather than drift into stale confusion.
