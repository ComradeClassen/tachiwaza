# Viewer Data Contract — Diagnosis Pass

*June 10, 2026. Answers to the seven diagnosis questions in
`viewer-data-contract.md` §"Exporter implementation notes", with file:line
references against the codebase as of commit e1f288d. Per the standing
caveat: where the codebase differs from the v0.1 contract sketch, the
codebase wins — the "contract revisions required" section at the end lists
every field where that happened.*

---

## Headline finding: most of the exporter already exists

The contract's hunch ("the exporter may be largely a serialization pass
over structures that exist") is correct, and more so than the draft
guessed. The codebase has a mature per-tick snapshot layer:

- **`src/viewer_capture.py`** — `capture_view(match, tick, events)`
  (viewer_capture.py:726) builds a frozen, immutable `MatchViewState`
  (viewer_capture.py:389) every tick: per-fighter body state (region
  damage for 19 anatomical regions, cardio, COM position, facing), score
  panels, match clock, grip edges (`GripEdgeView`, viewer_capture.py:250,
  already carrying an `edge_id`), grip node flashes, intent/actual arrows,
  text bursts (prose lines), referee flashes, and a minimap.
- **`RecordingViewCapture`** (viewer_capture.py:1081) — a renderer that
  accumulates one `MatchViewState` per tick into a list; already used by
  the viewer tests (tests/test_haj187_phase1_viewer.py).
- **`src/run_match.py:165–192`** — `_JSONCaptureRenderer`, an existing
  events-only JSON export (`{tick, type, prose, engineering}` per event).

What does **not** exist: JSONL file writing, a header line, a `--record`
flag, a serialization-stable edge id, and several contract field groups
that `MatchViewState` doesn't carry (kuzushi buffer, per-part fatigue in
contract shape, matte context, the `newaza` group, composure,
intent/actual as data rather than arrows).

**Scoping decision this raises:** `MatchViewState` is shaped for the
pygame viewer (arrows, flashes, bursts — view grammar, though still
sim-derived). The record contract wants raw simulation space. The exporter
should be a **sibling capture at the same hook point** (below), not a
serialization of `MatchViewState` — reuse the hook and the
`RecordingViewCapture` pattern, not the view-shaped dataclasses.

---

## Q1. Single hook point for frame emission

**Yes, and it's already plumbed.** The tick loop is
`Match.step()` → `Match._tick()` (match.py:1596–1604, 1659–2027), and
`Match._post_tick()` (match.py:2032–2163) ends with:

```python
if self._renderer is not None:
    self._renderer.update(tick, self, events)   # match.py:2157–2159
```

At that line, all grip-graph updates, physics, kuzushi, commits, and
fatigue for the tick have settled, the narrator has already consumed the
tick (match.py:2125), and the renderer receives the tick index, the live
`Match` (both fighters via `match.fighter_a`/`fighter_b`, the grip graph
via `match.grip_graph`, position/phase state), and the tick's full event
list. There is also a tick-0 call (match.py:1593) that can carry the
header. **The exporter is just another `Renderer` passed to
`Match(renderer=...)`** (match.py:1146, 1183) — zero cost when absent,
exactly the contract's "flag on the match runner" requirement. The flag
follows the existing `--viewer` pattern in main.py:509–517.

## Q2. Kuzushi buffer — real shape (contract revision required)

The contract's sketch (`{"front_right": 0.62, "rear": 0.10}`) is **wrong
in kind**: there are no discrete direction keys. The buffer is
`judoka.kuzushi_events`, a `deque[KuzushiEvent]` with maxlen 20
(judoka.py:377–379; capacity at kuzushi.py:94). Each `KuzushiEvent`
(kuzushi.py:62–75) stores:

- `tick_emitted: int`
- `vector: tuple[float, float]` — unit direction, continuous, mat frame
- `magnitude: float` — raw at emission (~30–100), **decay is computed on
  read**, exponential 5-tick half-life (kuzushi.py:97–105)
- `source_kind` — `PULL | FOOT_ATTACK | SELF_INFLICTED | THROW_RESOLUTION
  | OTHER` (kuzushi.py:45–56)

The derived read is `compromised_state(events, tick)` →
`CompromisedState(vector, magnitude, total_decayed_magnitude)`
(kuzushi.py:112–159), plus `dominant_kuzushi_source()`
(kuzushi.py:179–195). **Export both layers**: the raw event list (the
diagnostic instrument — watching individual events arrive and decay) and
the resolved `CompromisedState` resultant per tick.

## Q3. Log lines — already tick-stamped

Prose is generated per tick by `MatSideNarrator.consume_tick(tick, events,
bpe_slice, match)` (called at match.py:2125–2127; implementation at
src/narration/altitudes/mat_side.py:497–576). Every line is a
`MatchClockEntry(tick, prose, source, actors)`
(mat_side.py:42–46) — **the tick is already on every entry**; no
threading required. The `source` field is the tag system
(`"phase_transition"`, `"always_promote"`, `"self_cancel"`,
`"grip_strip_outcome"`, `"posture_change"`, …); engine-event echo sources
are the `_ECHO_SOURCES` set at match.py:2137–2149. Stream routing
(match/coach) happens at print time via `--stream`; the exporter should
capture entries before that split and record `source` as the tag.

## Q4. GripEdge identity (contract revision required on `depth`/`dominant`)

`GripEdge` (grip_graph.py:76–108) fields: `grasper_id`, `grasper_part`,
`target_id`, `target_location`, `grip_type_v2`, `depth_level`, `strength`,
`established_tick`, plus `mode` (CONNECTIVE/DRIVING),
`unconventional_clock`, `contested`, `max_depth_reached`,
`current_intent` (STEER/HOLD/BREAK), `steer_direction`.

- **Edges are stable objects mutated in place** — `GripGraph.edges` is a
  persistent list (grip_graph.py:221); deepen/strip/contest mutate fields
  (grip_graph.py:378–398, 409–481, 698).
- **`depth` is not a float.** `depth_level` is the discrete `GripDepth`
  enum (SLIPPING/POCKET/STANDARD/DEEP). The contract's `"depth": 0.65`
  becomes `"depth_level": "DEEP"`. The DEEPEN/STRIP-oscillation diagnostic
  still works — it's level changes sawtoothing, not a float.
- **`dominant` does not exist** on edges; drop it from v0.2 or derive it
  later.
- **Edge id today is `id(edge)`** — already emitted in event data
  (grip_graph.py:480, match.py:2298, 2407–2408) but it's a Python object
  address: unstable across runs, unserializable as identity. The
  **counter-handle precedent already exists**: the debug inspector assigns
  monotonic `G#NN` handles keyed off `id(edge)`
  (debug_inspector.py:122–128). Introduce `edge_id: int` on `GripEdge`,
  assigned from a `GripGraph` counter at the creation site
  (`_new_pocket_edge`, grip_graph.py:337–371 / `add_edge`,
  grip_graph.py:226–227), and migrate the event-data `edge_id` payloads to
  it. This is the only engine-side change the exporter needs; everything
  else is read-only.

## Q5. `failed_dimension` — reachable, via the tick's events

`FailureResolution` (failure_resolution.py:112–117) carries
`failed_dimension` — one of `"kuzushi" | "force" | "body" | "posture"`
(scored in `_dimension_scores()`, failure_resolution.py:249–260) — and
`dimension_score: float`. The resolution object itself is **not
persisted** (only the outcome enum survives, on
`match._compromised_states`, match.py:5982), **but** both fields are
written into the failure event's data at match.py:6030–6034 before
`_post_tick` runs. Since the frame-emission hook receives the tick's
events, `failed_dimension` is reachable at emission with no engine change
— the exporter lifts it from the event, same as the viewer-capture layer
lifts `edge_id`. Intent is separately inspectable via
`judoka.current_plan` (judoka.py:395; `Plan` at intent.py:58–81:
`target_throw_id`, `sequence`, `step_index`).

## Q6. Matte — reason enum exists; instructions are design-only

`MatteReason` exists (enums.py:430–446): `STALEMATE | OUT_OF_BOUNDS |
STUFFED_THROW_TIMEOUT | INJURY | OSAEKOMI_DECISION |
POST_SCORE_FOLLOW_UP_END | PENALTY`. At pause time
`should_call_matte()` (referee.py:188–239) evaluates a `MatchState`
snapshot (referee.py:74–112) carrying tick, position, sub-loop state,
per-fighter OOB flags and mat regions (HAJ-142), osaekomi holder/clock,
stalemate ticks, golden-score flag. No explicit "instigator" field — the
reason plus the state flags reconstruct it.

**Nothing in code computes filtered instruction lists.** The only traces
are a RING-2 placeholder comment (action_selection.py:683) and post-hoc
coach prose (cross_grip.py:321). So v0.1 ships `matte` as
**reason-only**, exactly the fallback the contract pre-authorized.

Note for the contract's `phase` field: there is **no single
TACHIWAZA|NE_WAZA|MATTE|OSAEKOMI|ENDED enum** in code. The real state is
`match.sub_loop_state` (`SubLoopState`: STANDING / THROW_COMMITTED /
NE_WAZA, enums.py:469–477) + `match.position` (`Position` enum,
enums.py:51–66) + `match.osaekomi.is_running` + matte/end events. The
exporter **derives** the contract's `phase` from these at emission — a
pure mapping, fine to own in the exporter, but it should *also* export
`sub_loop_state` and `position` raw so the derived field is auditable.

## Q7. Ne-waza — the `newaza` group's shape, fixed from code

The substrate is substantially built, as believed. Runtime state, all
readable from the hook point:

| State | Where | Fields |
|---|---|---|
| Coarse ne-waza phase | `NewazaResolver.state(osaekomi)` → `NeWazaState` (ne_waza.py:58–62, 264–276) | TRANSITIONAL / OSAEKOMI / SUBMISSION_ATTEMPT |
| Position | `match.position` (match.py:1206) | TURTLE_TOP/BOTTOM, GUARD_TOP/BOTTOM, SIDE_CONTROL, MOUNT, BACK_CONTROL, DOWN |
| Top fighter | `match.ne_waza_top_id` (match.py:1229) | fighter id or null |
| Pin clock | `match.osaekomi` → `OsaekomiClock` (ne_waza.py:103–166) | holder_id, position, ticks_held, is_running, technique_id; waza-ari at 10, ippon at 20 ticks |
| Submission chain (legacy) | `ne_waza_resolver.active_technique` → `ActiveTechnique` (ne_waza.py:89–95) | name, technique_state (CHOKE_INITIATING/SETTING/TIGHTENING/RESOLVED, ARMBAR_ISOLATING/POSITIONING/EXTENDING/RESOLVED, PIN_HOLDING/BROKEN — enums.py via ne_waza.py:69–86), aggressor_id, defender_id, chain_tick |
| Submission attempt (catalog, HAJ-220) | `ne_waza_resolver._submission_attempt` → `SubmissionAttempt` (ne_waza_consumption.py:471–477) | technique_id, aggressor_id, defender_id, ticks_elapsed, failed_effectiveness_ticks (tap-or-release logic at ne_waza_consumption.py:480–514) |
| Ground connection graph | `ne_waza_resolver._connection_graph` → `GroundConnectionGraph` (ne_waza_consumption.py:87–107; `ConnectionEdge` at 65–84) | per-edge: type, tori_part, target, quality, setup_ticks_remaining; plus `_dominant_position_id` |
| Escape gate (HAJ-231) | `ne_waza_resolver._ground_ticks` (ne_waza.py:221; min at 195–200) | settle counter, threshold 3 |

Phase transitions: into NE_WAZA at match.py:6172 (via
ground_continuation.py:107–172), back to STANDING at match.py:6530
(`_reset_dyad_to_distant`). So the `newaza` group exports: coarse state,
position, top_fighter_id, the osaekomi block, whichever submission state
object is live, the connection-graph edges, and the escape-gate counter.
Note the multi-tick commitment-chain state the contract hoped for
**exists twice** (legacy `ActiveTechnique` stages + catalog
`SubmissionAttempt`); export both while both are live in the engine, and
let the record show which path a given match exercised.

---

## Supplementary facts the contract needs

- **Coordinates**: meters, origin at mat center, `MAT_HALF_WIDTH = 4.0`
  (match.py:305) → 8 m × 8 m area. Positions live on
  `judoka.state.body_state.com_position` (`BodyState`,
  body_state.py:74–103); per-foot positions also available.
- **Facing is a unit vector** (body_state.py:103), not degrees. Export
  the vector (`"facing": [x, y]`) — converting to degrees in the engine
  would be inventing a viewer-friendly abstraction; the renderer can
  trig.
- **Fatigue**: per-part `judoka.state.body[part].fatigue` ∈ [0,1]
  (judoka.py:197–206), **24 parts** tracked (judoka.py:40–61), so the
  contract's "~6 parts" is a *selection* at export, not the engine's
  limit. Cardio: `judoka.state.cardio_current` (judoka.py:225).
  Composure: `judoka.state.composure_current` (judoka.py:228) — seeded
  from a 0–10 `composure_ceiling` (judoka.py:164), so it is **not a 0–1
  value** as the contract example implied; export raw and let the
  renderer normalize against the ceiling (which belongs in the header's
  identity block).
- **Compromised state**: `match._compromised_states[name]` holds the
  `FailureOutcome` enum (match.py:5982) — that's the contract's
  `compromised` field.
- **Trunk angles** (`trunk_sagittal`/`trunk_frontal`, radians,
  body_state.py:92–93) exist and are worth adding to the frame — the
  silhouette renderer will want lean.

## Contract revisions required for v0.2 (codebase wins)

1. `kuzushi.buffer` per-direction dict → **event list + resolved
   resultant** (`CompromisedState`) per Q2.
2. `grips[].depth: float` → `depth_level: enum string`; add `mode`,
   `current_intent`; **drop `dominant`**.
3. `edge_id` → must be **introduced** (counter on `GripGraph`); the only
   engine change the exporter requires.
4. `facing_deg` → `facing: [x, y]` unit vector.
5. `phase` → derived at export; also export raw `sub_loop_state` +
   `position`.
6. `matte` → reason-only in v0.1 (instruction system is design-only),
   reason values from `MatteReason`.
7. `composure` → raw value against a 0–10 ceiling, ceiling in header.
8. `newaza` shape → as fixed in Q7's table.
9. `intent`/`actual` → intent from `judoka.current_plan`
   (throw id + step index, not a single action enum); actual from the
   tick's events (incl. `failed_dimension`/`dimension_score`).

## Suggested exporter ticket scope (Ring 1, cycle 2)

1. `edge_id` counter on `GripGraph` + migrate `id(edge)` event payloads.
2. `RecordExporter(Renderer)` in a new `src/match_recorder.py`: header
   line on the tick-0 call, one sim-space JSONL frame per
   `update(tick, match, events)`; serialize from the live structures per
   this diagnosis (not from `MatchViewState`).
3. `--record` flag in main.py following the `--viewer` pattern
   (main.py:509–517); `records/` + .gitignore entry.
4. Revise `viewer-data-contract.md` to v0.2 per the list above.
