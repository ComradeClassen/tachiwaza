# Viewer Data Contract — v0.1
### The match record file: the boundary between the Python engine and the Godot viewer

*Drafted June 10, 2026. First cut, meant to be pushed back on. Companion to
`viewer-visual-language.md` — that document specifies what the viewer shows;
this one specifies what the engine gives it to show. The contract is the
load-bearing artifact: the exporter, the viewer foundation, and every future
render layer (silhouettes now, sprites on a tileset mat later) all hang off
this schema.*

---

## The principle

The Python engine and the Godot viewer never talk live. The engine runs a
match and emits a **match record file** — a structured, append-only event
stream, one frame per tick, containing everything the viewer needs to render
that tick. Godot loads a record and plays it back. One match, one file.

Three consequences follow, and all three are the point:

**The viewer is dumb on purpose.** It renders only what is in the file. It
never recomputes simulation state, never infers, never reconstructs. If the
viewer needs something, the engine exports it. This is what makes the viewer
trustworthy as a diagnostic instrument: what you see on screen is what the
engine believed at that tick, not the viewer's interpretation of it. A
discrepancy between the record and the prose log is a finding, not a render
bug.

**Every match is a replayable artifact.** A bug report stops being "I saw
weird grip behavior around tick 40" and becomes a record file attached to a
Linear ticket. Anyone — Comrade, Claude Code, eventually a contractor — loads
it and scrubs to the tick. Running the same seed before and after an engine
commit produces two records that can be watched side by side, which is the
substrate the HAJ-150 calibration tooling line already wants.

**The render layer is swappable.** The contract carries simulation-space
data — positions in mat meters, states as enums, grips as graph edges. It
says nothing about pixels, silhouettes, or sprites. Phase 1 renders two
anatomical silhouettes from this data; the eventual pixel-art sprites on a
tileset mat read the exact same fields. Upgrading the art never touches the
engine or the contract.

---

## File format

**JSON Lines (`.jsonl`).** One JSON object per line. The first line is the
match header; every subsequent line is a tick frame. JSONL over a single
JSON document because the exporter can append as the match runs (no
end-of-match assembly step), a partially-written record from a crashed run
is still readable up to the crash, and the viewer can stream-parse rather
than loading the whole file before showing anything.

**Naming:** `match_{seed}_{YYYYMMDD-HHMMSS}.jsonl`, written to a
`records/` directory in the repo (gitignored; records attach to tickets,
they don't live in version control).

**Versioning:** the header carries `schema_version`. The viewer checks it on
load and warns on mismatch rather than guessing. Any change to frame
structure bumps the version; this document is re-versioned alongside it.

**Snapshots, not deltas — for now.** Each frame is a full snapshot of
viewer-relevant state. Delta encoding is an optimization with real bug
surface (a missed delta corrupts every subsequent frame), and a four-minute
match at the current tick rate produces a file measured in hundreds of
kilobytes, not megabytes. Revisit only if file size actually becomes a
problem.

---

## The header line

One object, first line of the file. Everything the viewer needs before the
first tick renders.

```json
{
  "type": "header",
  "schema_version": "0.1",
  "engine_commit": "<git short hash>",
  "seed": 48214,
  "exported_at": "2026-06-10T19:42:00",
  "ruleset": { "duration_s": 240, "golden_score": false },
  "fighters": [
    {
      "id": "white",
      "name": "Tanaka",
      "belt": "shodan",
      "archetype": "GRIP_FIGHTER",
      "stance": "right",
      "dominant_side": "right",
      "height_cm": 172,
      "reach_cm": 175,
      "weight_kg": 73,
      "signature_throws": ["seoi_nage"]
    },
    { "id": "blue", "...": "..." }
  ]
}
```

Notes:

- `id` is `white`/`blue` (gi color), used as the fighter key in every frame.
- The identity block is a *snapshot*, not a reference into the roster — the
  record must be self-contained so it replays identically years later, after
  the roster data it came from has changed or gone.
- Height, reach, and weight are here so the renderer can proportion the
  figures — visible height differential is a Ring 5 commitment and the
  silhouettes should honor it from day one.
- `signature_throws` feeds the signature-readiness glow in the viewer's
  full-vocabulary phase; cheap to include now.

---

## The tick frame

One object per simulation tick. The shape, annotated:

```json
{
  "type": "tick",
  "tick": 47,
  "clock_s": 23.5,
  "phase": "TACHIWAZA",

  "fighters": {
    "white": {
      "pos": [2.1, 3.4],
      "facing_deg": 84,
      "posture": "UPRIGHT",
      "compromised": null,
      "kuzushi": { "buffer": { "front_right": 0.62, "rear": 0.10 } },
      "fatigue": { "cardio": 0.81, "parts": { "right_hand": 0.74, "right_forearm": 0.69 } },
      "composure": 0.88,
      "intent": { "action": "DEEPEN_GRIP", "target_edge": "e3" },
      "actual": { "action": "DEEPEN_GRIP", "result": "SUCCESS", "failed_dimension": null }
    },
    "blue": { "...": "..." }
  },

  "grips": [
    {
      "edge_id": "e3",
      "owner": "white",
      "grasper": "right_hand",
      "target": "left_lapel",
      "grip_type": "DEEP",
      "depth": 0.65,
      "strength": 0.71,
      "established_tick": 31,
      "contested": false,
      "dominant": true
    }
  ],

  "matte": null,

  "events": [
    { "kind": "GRIP_UPGRADE", "edge_id": "e3", "from_depth": 0.45, "to_depth": 0.65 }
  ],

  "log": [
    { "stream": "match", "tag": "grip", "text": "Tanaka works the collar grip deeper." }
  ]
}
```

### Field-by-field rationale

**`phase`** — `TACHIWAZA | NE_WAZA | MATTE | OSAEKOMI | ENDED`. The viewer
switches render grammar on this (the tachiwaza grammar and ne-waza states
are separate phases of the visual-language spec). The `matte` and `newaza`
field groups below are populated only in their corresponding phases.

**`pos` and `facing_deg`** — mat-space coordinates in meters, origin at mat
center, standard competition area dimensions assumed by the renderer. The
engine exports simulation space; the renderer owns the mapping to pixels or
tiles. This is the line that makes the tileset upgrade free. Mat-region
visual signals (danger area, out of bounds) are *derived by the renderer
from position* — the engine doesn't export "in danger zone" because that's
geometry the renderer can do, and keeping it out of the contract avoids a
sync bug class.

**`posture` / `compromised`** — posture as the enum, compromised states as
the enum value (the renderer maps enum → human description; the prose log
already renders the human form per HAJ-34, and the viewer should key off the
same enum, not parse prose).

**`kuzushi.buffer`** — the buffer model's per-direction values. This is a
direct export of the buffer-based kuzushi state, and it is the single most
important diagnostic field in the contract: watching the buffer fill, decay,
and trigger (or fail to trigger) a signature match, tick by tick, scrubbing
backward and forward, is exactly the instrument the grip-as-cause
calibration work needs. The exact direction keys come from the diagnosis
pass — export whatever the buffer actually stores, don't invent a
viewer-friendly abstraction over it.

**`fatigue.parts`** — only the ~6 body parts that meaningfully participate
in Phase 1 (hands, forearms, legs, core, lower_back, neck). The contract
grows as parts wake up.

**`intent` vs `actual`** — the chosen action and the resolved outcome,
separately. This feeds the dual intent-and-actual arrow system in the
visual-language spec, and it surfaces `failed_dimension` — one of the named
loose ends (desperation overlay and failed_dimension don't currently reach
the coach stream). The record file is where they become visible even before
the prose layer learns to narrate them.

**`grips`** — the full edge list, every tick, fields lifted directly from
the GripEdge dataclass (grasper, target, grip_type, depth, strength,
established_tick) plus `contested` and `dominant`. Stable `edge_id` across
the edge's lifetime so the viewer can animate continuity (the same line
thickening as depth grows) and so events can reference edges. This is the
field group that renders the Ring 5 promise — thickness from depth, opacity
from strength, flicker on contested — and it is the instrument for both live
grip-model questions: sequential build vs. simultaneous double-grip is
*visible* as edge appearance order, and the silent DEEPEN/STRIP oscillation
is *visible* as depth values sawtoothing on a stable edge even while the
prose log stays quiet.

**`matte`** — `null` outside the Matte phase. When `phase` is `MATTE`, the
field group carries the pause context:

```json
"matte": {
  "reason": "STIFLED_RESET",
  "instructions": {
    "white": ["BREAK_GRIP", "ATTACK_NOW", "GRIP_DEEPER", "RESET_STANCE"],
    "blue": ["DEFEND_LAPEL", "CIRCLE_LEFT"]
  }
}
```

`reason` is the engine's Matte trigger (out of bounds, stalemate, stuffed
throw resolving in defensive grip, post-score reset — whatever the enum
actually is in code). `instructions` is the engine's *filtered* per-fighter
instruction list — the design intent is that available instructions derive
from the live grip graph and position state, so exporting the engine's own
filtering is the only honest version of this field. If the instruction
system isn't yet computing filtered lists in code, the field ships as
`reason`-only and the viewer renders a Matte panel mock from the graph
state already in the frame. Either way, the Matte frames in real records
are the design surface for thinking about what coach options should even
exist — that's a primary purpose of including this group in v0.1.

**`newaza`** — per-fighter field group, `null` during tachiwaza. The
ne-waza substrate already models positional state; the contract exports
whatever that state actually stores (position, hooks/control edges beyond
the hand-grip graph, osaekomi progress when phase is `OSAEKOMI`,
multi-tick commitment-chain state for chokes and locks). The field shape
is deliberately not invented here — it gets fixed by the diagnosis pass
against the ne-waza code, not by this spec or by the design docs, which
may lag the codebase.

**`events`** — typed events this tick, the announcement-taxonomy layer:
grip transitions (ESTABLISH, BREAK, FIGHT, UPGRADE, SWITCH), kuzushi events,
throw attempts (with throw family, signature-match result, and outcome),
scores, referee calls, penalties. Events are *in addition to* the state
snapshot, not a substitute — the snapshot says what is, the events say what
changed and why, and the viewer's timeline can render event markers (a score
tick, a Matte tick) as scrub targets.

**`log`** — the prose lines generated *from this tick*, with their stream
and tag. Tick-stamping the log lines at export is what enables the viewer's
highest-value diagnostic feature: click a line in the log pane, jump to the
tick. The causal ordering from HAJ-31–34 (`[throw]` commits → `[score]`
landing → `[ref]` calls) is preserved by line order within the frame.

---

## What the contract deliberately excludes

- **Screen-space anything.** No pixels, no colors, no silhouette geometry.
  Renderer's problem.
- **Mid-match RNG state.** Records are replays, not save games. Resume-able
  matches are a different (future) problem with a different file.
- **Full Capability/Identity dumps per tick.** Identity is in the header
  once; per-tick frames carry only state that changes.
- **Coach-IQ filtering.** The record is omniscient — it's a developer
  instrument. The coach-IQ visibility gating from the Matte panel design is
  a *player-facing* render policy applied much later, on top of the same
  data, not a property of the file.

---

## Exporter implementation notes (for the Claude Code session)

Standing rule applies: **diagnose before implementing.** Much of this state
already flows through the debug/log layer; the exporter may be largely a
serialization pass over structures that exist, plus tick-stamping the log
emission. The diagnosis pass should come back with file:line references for
where each frame field currently lives (or confirmation it doesn't), before
any ticket scope is fixed. Specific questions for that pass:

1. Where does the tick loop have access to both fighters' full state and the
   edge list in one place — is there a natural single hook point for frame
   emission?
2. What does the kuzushi buffer actually store (direction keys, value range,
   decay representation)? Export its real shape.
3. Are log lines currently generated with tick context available, or does
   tick-stamping require threading the tick index into the narration layer?
4. Do GripEdges already carry a stable identity across ticks, or is the edge
   list rebuilt per tick (in which case `edge_id` needs to be introduced)?
5. Is `failed_dimension` reachable at the point of frame emission?
6. What does the Matte handling actually have at pause time — is there a
   reason enum, and does anything in code compute filtered instruction
   lists yet, or is the instruction system design-only so far?
7. What does the ne-waza positional state actually store, with file:line
   references? The `newaza` field group's shape is fixed by this answer.

A standing caveat for the whole pass: **the design corpus may lag the
codebase in both directions** — features documented as designed may already
be built, and field shapes sketched in this spec may not match what exists.
Every frame field in this document is a hypothesis until the diagnosis
confirms it. Where the codebase differs, the codebase wins and this
contract is revised to match, not the other way around.

The exporter should be a flag on the match runner (`--record`), default off,
zero cost when off.

---

## Resolved questions

*Resolved June 10, 2026, same session as the draft.*

1. **Playback is snap-to-tick. Locked.** The viewer shows discontinuities;
   it doesn't smooth them. Interpolation becomes a toggle only if/when the
   viewer grows toward a player-facing mode.
2. **Matte context ships in v0.1.** The `matte` field group (above) carries
   the pause reason and, where the engine computes them, the filtered
   instruction lists. The explicit purpose: watching real Matte frames in
   real records is how the coach-option design gets thought through —
   the pause is a design surface, not just a phase.
3. **Ne-waza exports what exists.** The positional state is believed to be
   substantially built already; the `newaza` field group is populated from
   the diagnosis pass (question 7), not designed fresh here. Reserve the
   key, fix the shape from the code.
4. **Record retention convention accepted.** Records attached to Linear
   tickets persist with the tickets; everything else in `records/` is
   disposable and can be cleared freely. `records/` is gitignored.

---

## Next steps

1. Push back on this draft — particularly the frame shape and the
   snapshot-not-delta call.
2. Hand the diagnosis questions above to Claude Code; findings come back
   with file:line references.
3. File the exporter ticket (Ring 1 — Match Engine, cycle 2) scoped from the
   diagnosis, not from this spec.
4. Drop this document into the Obsidian vault and repo as
   `viewer-data-contract.md`.
5. Godot viewer foundation (load record, scrub timeline, two silhouettes,
   grip lines) starts the moment the first real record file exists.

---

*Drafted June 10, 2026, from the viewer-visual-language spec and the grip
model calibration needs. v0.1.*
