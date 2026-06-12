# Godot Calibration Tool — Diagnosis Findings
### HAJ-150 state-of-the-build + viewer-foundation readiness

*June 12, 2026. Produced from `godot-tool-diagnosis-brief.md`. Diagnosis only —
no `.gd`, `.tscn`, `project.godot`, or Python files were modified. Evidence
gathered by reading source, exercising `src/run_match.py` from the CLI with a
UI-shaped config, and running the tool live (Godot 4.6.2, launched via
`--path`, observed and operated on-screen). Codebase at `17b4afa`.*

---

## Part 1 — Project inventory (Q1–Q3)

### Q1. Location, git, engine

| Question | Answer |
|---|---|
| Path | `C:\Users\jackc\hajime\hajime-debug-tool\` — a subdirectory of the main repo |
| In git? | Yes, in the **hajime** repo itself (commit `3d423e0`, "Added a Godot Project from HAJ-150" — 9 files, 1,056 insertions). Not a separate repo. `.godot/` cache is correctly ignored (`hajime-debug-tool/.gitignore`) |
| Godot version | 4.6 pinned (`project.godot:15`, `config/features=PackedStringArray("4.6", "Forward Plus")`); runs under 4.6.2-stable on this machine |
| Rendering method | **Forward+**, with `rendering_device/driver.windows="d3d12"` (`project.godot:29`) and Jolt physics for 3D (`project.godot:25`) |
| Window | `1600×1500` viewport (`project.godot:20-21`) — see defect D1 |

Forward+ is fine for the viewer's `_draw()`-heavy 2D work (CanvasItem drawing
is renderer-agnostic), but it is the heaviest backend for what is a pure
Control-node tool; Compatibility would widen export targets if that ever
matters. Not a defect — a note for the viewer ticket.

### Q2. Full inventory

Nine tracked files; the entire tool is **one scene + one script**:

```
hajime-debug-tool/
├── project.godot           # engine config (above)
├── calibration_tool.tscn   # the only scene (698 lines, text-format)
├── calibration_tool.gd     # the only script (275 lines), attached to scene root
├── icon.svg (+ .import)    # default Godot icon
├── .editorconfig / .gitattributes / .gitignore
```

No saved config JSONs or preset files live in the project; runtime artifacts
go to `user://` (i.e. `C:\Users\jackc\AppData\Roaming\Godot\app_userdata\HajimeDebugTool\`):
`hajime_match_config.json` (1.7 KB), `hajime_match_log.json` (**422 KB** for
one 240-tick match), `saved_config.json`.

**Main scene node tree** (`calibration_tool.tscn`), annotated:

```
CalibrationTool (Control, full-rect)         ← script: calibration_tool.gd
└── Root (VBoxContainer, full-rect anchors + offset_bottom=362  ⚠ D2)
    ├── TopRow (HBoxContainer, vexpand)
    │   ├── Fighter1Panel (VBoxContainer, vexpand)
    │   │   ├── Name        Label + LineEdit            (no default text ⚠ D6)
    │   │   ├── Age         Label + SpinBox 16–40, def 25
    │   │   ├── Height      Label + SpinBox 165–195, def 175
    │   │   ├── WeightClass Label + OptionButton ["-90kg"]
    │   │   ├── BodyArchetype Label + OptionButton (5 archetypes)
    │   │   ├── Belt        Label + OptionButton (WHITE…BLACK_5)
    │   │   ├── DominantSide Label + OptionButton (RIGHT/LEFT)
    │   │   ├── 4 personality facet Label + HSlider (0–10, step 0.1)
    │   │   └── 15 capability Label + HSlider (0–10, step 0.1):
    │   │       hands L/R, forearms L/R, legs L/R, core, lower_back, neck,
    │   │       cardio_capacity, cardio_efficiency, fight_iq,
    │   │       composure_ceiling, ne_waza_skill, other_body_parts_global
    │   ├── Fighter2Panel (identical 52-node structure)
    │   └── MatchPanel (VBoxContainer — no vexpand)
    │       ├── StartingPosition OptionButton (5 options ⚠ D4)
    │       ├── TimeOnClock SpinBox max 300, def 240
    │       ├── ForcedThrow OptionButton (NONE + 4 throws ⚠ D4)
    │       └── RefPersonality OptionButton (GENEROUS/STRICT/NEUTRAL ⚠ D7)
    ├── ButtonRow (HBoxContainer)
    │   ├── PresetSelector (OptionButton, filled at runtime)
    │   ├── RunMatchButton / SaveButton / LoadButton (Buttons)
    └── LogOutput (RichTextLabel, vexpand, scroll_following)
```

All four signal connections are wired correctly in the scene
(`calibration_tool.tscn:695-698`): preset `item_selected`, and `pressed` on
Run/Save/Load → the four handlers in `calibration_tool.gd`.

Naming nit: one node is `"Cardio EfficiencyLabel"` (with a space,
`calibration_tool.tscn:268`) while its Fighter2 twin is
`CardioEfficiencyLabel` — harmless (labels are never looked up by the
script), but it's the kind of inconsistency that bites if labels ever are.

Dropdown contents are duplicated: baked into the `.tscn` **and** re-filled at
runtime by `_populate_dropdowns()` from the GDScript constants
(`calibration_tool.gd:48-57`). The script's `_fill()` clears first, so the
script constants are authoritative; the `.tscn` copies are dead weight that
will silently drift.

### Q3. Launch path and docs

- **Editor-only.** No `export_presets.cfg`, no exported build, no launch
  script. Launch is: open the project in Godot 4.6+, F5 — or headlessly-known
  path `Godot_v4.6.2-stable_win64_console.exe --path hajime-debug-tool` (used
  for this diagnosis; clean startup, zero script errors on console).
- **`docs/calibration-tool.md` does not exist.** `docs/` contains only
  `catalog-authoring-notes.md`. Acceptance criterion 9 is unmet in full: no
  launch docs, no file-location docs, no add-a-preset recipe, no
  extend-the-UI recipe.

---

## Part 2 — Build state against HAJ-150 (Q4–Q6)

### Q4. Acceptance-criteria audit

| # | Criterion | Verdict | Evidence |
|---|---|---|---|
| 1 | Scene loads and runs without errors | **MET** | Live run: clean console, all controls render. `calibration_tool.gd:44-46` |
| 2 | Full Identity layer per fighter | **MET** | All 8 spec'd controls present (`calibration_tool.tscn:31-166`, mirrored for Fighter2); ranges match spec (age 16–40, height 165–195, the exact archetype/belt/side lists) |
| 3 | Phase-1 Capability values | **MET** (with drift notes below) | All 14 named fields + `other_body_parts_global` (`calibration_tool.gd:89-105`); Python maps the global onto biceps/shoulders/feet **and** the v0.4 additions head/hips/thighs/knees/wrists (`run_match.py:113-128`) |
| 4 | Four preset templates | **ABSENT** | Dropdown lists all four names but selection prints `"Preset '%s' is a Phase 6 stub — not implemented yet."` (`calibration_tool.gd:271-275`). Verified live |
| 5 | Match-level configuration | **DIVERGED** | All four controls exist in the UI (`calibration_tool.tscn:609-669`) and are serialized (`calibration_tool.gd:108-114`) — but `starting_position` and `forced_throw` are **accepted and silently discarded** by Python (`run_match.py:214-217`, explicit "TODO Phase 6 … not yet honored"). `time_on_clock` → `max_ticks` and `ref_personality` are honored (`run_match.py:219-220`, `142-159`) |
| 6 | Run Match executes and displays | **PARTIAL** | Full loop works (verified live: config written, subprocess run, log rendered). Renders tick/type/prose (`calibration_tool.gd:185-189`). **No "show engineering events" checkbox** — the `engineering` payload is exported in every event (`run_match.py:190`) but never displayed; the toggle's data dependency is already satisfied |
| 7 | Display renders readably | **PARTIAL** | Scrollable, `scroll_following`, no crash on a 1,168-event match. **Not monospace** (default theme font). Most of the log box sits below the window edge (defect D2); tick stamps render as floats (D5) |
| 8 | Save/Load configuration | **MET** | Single fixed `user://saved_config.json` path, full round-trip verified live (`calibration_tool.gd:194-265`). No file picker — explicitly fine per spec |
| 9 | `docs/calibration-tool.md` | **ABSENT** | File does not exist (only `docs/catalog-authoring-notes.md`) |
| 10 | Existing pytest unaffected | **MET** | `src/run_match.py` is additive — new file, imports the engine, modifies nothing. Full suite re-run during this diagnosis: 1,569 tests, exit 0 |

**Drift check, both directions** (UI ↔ `Judoka` in `src/judoka.py`):

- `Capability.foot_speed` (`judoka.py:173`, default 5) — added after the spec;
  **not exposed in the UI and not covered by the global slider**
  (`run_match.py:106-133` never sets it). Every configured fighter silently
  gets foot_speed 5.
- `Identity.tokui_waza` / `Capability.signature_throws` / `throw_profiles` —
  the spec's summary promises per-fighter signature throws (via templates);
  `run_match.py:129-132` hardcodes `throw_profiles={}`,
  `signature_throws=[]`, and `tokui_waza` defaults empty. **No path from the
  UI to a fighter with signatures.** With presets stubbed, no fighter ever
  has them.
- "Disguise-related attributes" (spec summary) — there is no disguise
  attribute to expose: disguise is *derived* from skill-vector axes
  (`reaction_lag.py:94-107`, from `sequencing_precision` + `pull_execution`).
  The **High-Disguise preset cannot be expressed as a config field**; it has
  to be built indirectly (belt/capability choices that move those axes) or
  wait for disguise to be promoted to a first-class axis (flagged as a v0.2
  possibility in that docstring).
- `Identity.positional_style` is hardcoded `HOLD_CENTER` (`run_match.py:96`);
  newer Identity fields (`arm_reach_cm`, `hip_height_cm`,
  `weight_distribution`, `mass_density`, `stance_matchup_comfort` —
  `judoka.py:106-116`) all ride defaults. Defensible for v0.1; listed for
  completeness.
- Sliders advertise 0.1 precision (`step = 0.1` throughout the `.tscn`) but
  Python rounds everything to int (`run_match.py:101-102`). The displayed
  precision is fake.
- `run_match.py` accepts an optional `match.seed` (`run_match.py:221-223`)
  that the **UI never sends** — reproducibility is one SpinBox away and is
  exactly what the record/replay workflow wants. Cheapest high-value gap in
  the audit.

### Q5. The subprocess contract as actually implemented

**Command** (`calibration_tool.gd:11-14`, `141-147`):

```
python C:/Users/jackc/hajime/src/run_match.py
    --config %APPDATA%/Godot/app_userdata/HajimeDebugTool/hajime_match_config.json
    --output %APPDATA%/Godot/app_userdata/HajimeDebugTool/hajime_match_log.json
```

- `PYTHON_EXECUTABLE := "python"` — PATH-dependent, no venv handling.
- `RUN_MATCH_SCRIPT := "C:/Users/jackc/hajime/src/run_match.py"` —
  **hardcoded absolute path to this machine** (`calibration_tool.gd:12`).
  The tool lives at `<repo>/hajime-debug-tool/`, so
  `res://../src/run_match.py` globalized would compute this relatively; today
  the project breaks if the repo moves.
- Working directory: inherited from the Godot process; harmless, because
  `run_match.py` uses sibling-module imports resolved off the script's own
  directory (`run_match.py:39-49`).
- Config/output flow through `user://`, globalized at call time
  (`calibration_tool.gd:127-128`). Matches the spec's "known path" intent.

**Entry point**: the spec's `hajime/run_match.py --config/--output` landed as
`src/run_match.py` with exactly that interface (`run_match.py:246-254`). The
`_JSONCaptureRenderer` (`run_match.py:165-182`) is a push-style `Renderer`
handed to `Match(renderer=…)` (`run_match.py:227-237`) — i.e. the integration
landed **precisely on the hook HAJ-241's exporter will use**. Failure
contract is solid: config errors → exit 1, sim crashes → exit 2 with the
traceback written *into the output JSON as an ERROR event* (`run_match.py:285-294`),
so failures surface in the log panel rather than vanishing.

**Config JSON shape**: Godot writes `{fighter1, fighter2, match}`
(`calibration_tool.gd:67-114`); Python consumes exactly that, absorbing the
known mismatches in `_build_judoka()` (`run_match.py:63-136`): `hands_left` →
`left_hand` renames, bipolar facet keys → first-pole keys
(`run_match.py:52-57`), global slider fan-out, float→int rounding. Verified
end-to-end this session: a UI-shaped config run from the CLI produced exit 0,
1,168 events, **1.1 s** for a full 240-tick match.

**Output read-back**: Python writes `{"events": [{tick, type, prose,
engineering}, …]}` (`run_match.py:185-191`, `277`); Godot parses the whole
file in one `JSON.parse_string` (`calibration_tool.gd:163`) and renders
`[t=%s] [%s] %s` per event into the RichTextLabel via `append_text`
(`calibration_tool.gd:181-189`). The `engineering` dict — already sanitized
JSON-safe (`run_match.py:194-202`) — is parsed and dropped on the floor;
criterion 6's toggle needs zero Python work.

**Blocking vs non-blocking**: **blocking** — `OS.execute()`
(`calibration_tool.gd:147`), and the script itself prints the warning
("This blocks the UI", `calibration_tool.gd:138`). Measured freeze is small
today (~1–2 s sim + interpreter startup), and tolerable for a
configure-and-read loop. Two aggravators worth knowing:

1. `run_match.py` leaves the Match on `stream="both"` (`run_match.py:233`),
   so the full dual-stream prose render (~150 KB for one match) is printed to
   stdout and captured into Godot's `stdout` array for no consumer. Pure
   waste; also the reason a past `UnicodeEncodeError` crash existed (the
   cp1252 fallback under `OS.execute`, now fixed by the utf-8 reconfigure at
   `run_match.py:35-37`).
2. The viewer workflow changes the calculus: once `--record` exists and
   matches are watched rather than skimmed, a frozen window during the run +
   a 422 KB single-shot parse is the wrong shape. **The viewer ticket should
   move to `OS.create_process()` + polling**; the calibration tool as-is does
   not need it fixed first.

### Q6. Observed defects (live run)

Run conditions: Godot 4.6.2, primary display 1920×1080, tool launched via
`--path`, match run with all defaults.

| ID | Defect | Repro / evidence |
|---|---|---|
| **D1** | **Tool is unusable on a 1080p display as configured.** Viewport is 1600×1500 (`project.godot:20-21`); Windows clamps the window to screen height, and everything below the Cardio Capacity sliders — Fight IQ → Other Body Parts, the **preset selector, all three buttons, and the entire log panel** — is off-screen. There is no scroll container; the fighter-panel VBox minimum height (~1,450 px of stacked controls) exceeds any sane window, so resizing cannot fix it. This diagnosis could only click Run Match after force-moving the window to negative-Y via Win32. This is the single biggest "needs a little work" item. | Launch on a 1080p screen; observe. `calibration_tool.tscn` has no ScrollContainer nodes |
| **D2** | **`Root` extends 362 px below the window.** Full-rect anchors plus `offset_bottom = 362.0` (`calibration_tool.tscn:19`) — almost certainly an accidental editor drag. Net effect: even within the window, the log panel's lower 362 px are clipped; only ~7 lines of log are visible at once. | Read `.tscn:19`; observed live (log strip at the very bottom edge) |
| **D3** | **Presets are stubs.** Selecting any preset prints "Preset 'Elite Mirror' is a Phase 6 stub — not implemented yet." — and the selector then *stays* on the preset name while the sliders remain untouched, so the UI displays a configuration it isn't running. | Select any preset; verified live. `calibration_tool.gd:271-275` |
| **D4** | **Two match controls are decorative.** `starting_position` and `forced_throw` round-trip to Python and are discarded (`run_match.py:214-217`). Additionally the UI option lists are engine-unmoored: the five `STARTING_POSITIONS` strings (`calibration_tool.gd:25-26`) match no engine enum, and `FORCED_THROWS` hardcodes 4 throws (`calibration_tool.gd:27`) vs. the full `THROW_REGISTRY` every fighter actually gets (`run_match.py:129`). When these are wired, both lists need re-deriving from the engine. | Code refs both sides |
| **D5** | **Tick stamps render as floats** — `[t=271.0]` not `[t=271]`. JSON numbers parse as floats in GDScript; `_format_event` stringifies directly (`calibration_tool.gd:185-189`). Cosmetic but pervasive. | Observed live on every line |
| **D6** | **Empty default names produce nameless prose.** Name LineEdits default to ""; the sim runs happily and emits lines like "loses right_sleeve grip on  — stripped." (double space where a name belongs). No validation or default-name fill. | Run with defaults; observed live |
| **D7** | **Ref personality defaults to GENEROUS**, not NEUTRAL — it's simply item 0 of the list (`calibration_tool.gd:28`); nothing selects NEUTRAL on `_ready`. Operators will run "default" matches under a generous ref without noticing. | Observed live in dropdown |
| **D8** | **Save overwrites the log panel** — `log_output.text = "Config saved to: …"` (`calibration_tool.gd:202`) destroys the match log you were reading. Same for Load. Minor UX. | Verified live |
| **D9** | **BBCode fragility in the log path.** `append_text` parses BBCode (`calibration_tool.gd:182`). Current prose tags (`[move]`, `[grip]`, `[ref: …]`) are invalid BBCode and render literally — verified live — but any future prose containing a *valid* tag (`[i]`, `[b]`, `[center]`) will silently format instead of display. `add_text` is the correct call. | Code + live observation |
| **D10** | **Wasted stdout capture** — full dual-stream prose printed and captured per run (`run_match.py:233`, `stream="both"`); ~150 KB/match for no consumer, and historically the source of the cp1252 crash. `stream` should be quieted or the capture dropped. | Measured this session |
| **D11** | **No seed control** (UI side; Python already accepts it, `run_match.py:221-223`). Without it, no run is reproducible — which collides head-on with the record/replay workflow HAJ-241 exists for. | Code refs both sides |

Not defects, noted: horizontal layout wastes the right half of the window
(panels don't `size_flags_horizontal` expand — purely cosmetic, in-spec);
the duplicated dropdown contents (`.tscn` vs script constants, see Q2);
1,168 `append_text` calls per match render without visible stall.

---

## Part 3 — Viewer-foundation readiness (Q7–Q9)

### Q7. Scene architecture headroom

The project is a single scene with a single script — but it is **not** a
God-scene problem: all logic hangs off one root Control whose script touches
only its own subtree, no autoloads, no global state, no cross-scene
references. A `RecordViewer` scene can be added as a **sibling top-level
scene file** (`record_viewer.tscn` + script) with zero changes to the
calibration scene.

What *doesn't* exist is anything to host both: `project.godot:14` points
`run/main_scene` straight at `calibration_tool.tscn`. The realistic options,
in increasing order of restructuring:

1. **None (editor-launch).** Run whichever scene you want with Godot's
   "Play Scene" (F6). Zero changes; viewer development can start today.
2. **Run-to-watch button.** The calibration scene, on match completion,
   calls `get_tree().change_scene_to_file("res://record_viewer.tscn")` (or
   instances the viewer in a popup/window). Small, additive.
3. **Launcher/tab shell.** New thin root (TabContainer or two buttons)
   becomes `run/main_scene`; calibration and viewer become tabs/children.
   ~30 lines and a `project.godot` one-liner, no surgery on the existing
   scene — the existing root is a self-contained full-rect Control, which is
   exactly the shape a TabContainer child wants.

Recommendation embedded in the ticket split below: option 3 is cheap enough
to belong in the viewer-foundation ticket; nothing needs restructuring
*before* it.

One pre-existing wart the restructure should sweep up: defect D2's
`offset_bottom=362` means the calibration root currently only looks right
because nothing parents it; the moment it's reparented into a container the
stray offset is overridden by container layout — i.e. the tab shell
*accidentally fixes* D2's anchor weirdness, but D1's minimum-height problem
follows it into the tab and still needs ScrollContainers.

### Q8. Reusable plumbing

Inventory of what exists vs. what the record loader needs:

| Plumbing | Exists? | Where |
|---|---|---|
| JSON parse/stringify | Inline only — `JSON.parse_string` / `JSON.stringify` at four call sites | `calibration_tool.gd:135, 163, 200, 211` |
| File I/O | Inline `FileAccess.open` read/write pairs | `calibration_tool.gd:131-136, 156-161, 196-201, 208-210` |
| Path resolution | `ProjectSettings.globalize_path` on `user://` constants; machine-hardcoded `RUN_MATCH_SCRIPT` | `calibration_tool.gd:11-15, 127-128` |
| Autoloads / singletons | **None** | `project.godot` has no `[autoload]` section |
| JSONL / streaming read | **Nothing** — record loading (`FileAccess.get_line()` loop, per-line parse, header check) is greenfield | — |

There is genuinely reusable *knowledge* here (the `user://` convention, the
globalize-path pattern, the parse-null-check idiom) but no reusable *code
unit* — everything is welded into the one script. The viewer ticket should
create the project's first autoload (e.g. `paths.gd`: python executable,
repo root derived relatively instead of hardcoded, records directory) and
have **both** scenes consume it — that single move deletes the
machine-hardcoded path (Q5) and gives the viewer its hang-off point.

### Q9. The run-to-watch seam

Both splice points are tight and already isolated:

- **Where `--record` goes in:** the args array build,
  `calibration_tool.gd:141-145` — append `"--record"` (plus a destination
  path) here. Python side: the argparse block `run_match.py:250-253` grows
  the flag, mirroring the `--viewer` precedent in the main runner
  (`src/main.py:509-513`); the `RecordExporter` joins the run at the
  `Match(renderer=…)` construction, `run_match.py:227-237`, on exactly the
  hook `_JSONCaptureRenderer` already occupies.
- **Where "open the record in the viewer" goes in:** after the exit-code
  check at `calibration_tool.gd:149-153` and before/alongside the JSON
  read-back at `calibration_tool.gd:156-168` — at that point the record
  path is known and the match is finished. That is the line where v0.1
  renders text and v0.2 *additionally* hands the record path to the viewer
  scene.

One composition fact for the viewer ticket to resolve: `Match` takes a
**single** `renderer` (`run_match.py:234`), and the calibration path already
uses it for `_JSONCaptureRenderer`. Recording + capturing simultaneously
needs either a trivial tee-renderer (one class, forwards to N children) or
multi-renderer support in `Match`. HAJ-241 scopes the exporter against
`main.py`'s runner; the *calibration tool's* runner is `run_match.py` — the
ticket split should make sure `--record` lands on both, or the tool switches
to the main runner.

A version note for the same ticket: the in-repo `viewer-data-contract.md` is
**v0.1**; the brief and HAJ-241 cite v0.2 (vault-side). HAJ-241's own
acceptance includes landing the v0.2 contract doc in the repo — the viewer
foundation should pin against whatever `schema_version` actually ships, and
warn-on-mismatch per the contract's own versioning rule.

---

## Proposed ticket split

*A proposal; Comrade decides.*

### Ticket A — HAJ-150 completion pass (the "needs a little work" list)

Everything that makes the **existing text tool** usable and honest, no new
capability:

1. **Layout rescue (D1+D2):** window to ≤1280×800; fighter panels each
   wrapped in a ScrollContainer (or two-column compaction); kill the stray
   `offset_bottom=362`; give the log panel real height. This is the blocker
   for everything else — the tool can't be operated on the dev machine's
   own display today.
2. **Implement the four presets (D3):** GDScript dictionaries reusing
   `_apply_config()` (`calibration_tool.gd:218-260`) — the load path already
   does exactly what preset-application needs, so this is data-entry plus
   one function. High-Disguise preset needs a design call first (disguise is
   derived, not settable — see drift check).
3. **Honest match controls (D4):** either wire `starting_position` /
   `forced_throw` through Python or visibly mark them inert. Wiring is
   engine work (position seeding, forced-throw injection) — recommend
   *marking inert now*, wiring under the engine cluster that owns it.
4. **Seed SpinBox (D11):** UI-only; Python already accepts it. Outsized
   value for record/replay.
5. **Engineering-events toggle (criterion 6):** CheckBox + render the
   already-exported `engineering` dict. No Python changes.
6. Small fixes: default names (D6), default ref NEUTRAL (D7), int tick
   stamps (D5), `add_text` not `append_text` (D9), monospace log font
   (criterion 7), don't clobber the log on save/load (D8), quiet
   `stream="both"` (D10), de-duplicate dropdown contents (Q2 note).
7. **Write `docs/calibration-tool.md`** (criterion 9), documenting the
   python-path assumption (open question 1) honestly.

### Ticket B — Godot viewer foundation (consumes HAJ-241's records)

1. **Shared-paths autoload** (`paths.gd`): python executable, relative repo
   root (kills the hardcoded `RUN_MATCH_SCRIPT`), `records/` location.
2. **Launcher/tab shell** as the new main scene; calibration scene and
   `RecordViewer` scene as children (Q7 option 3).
3. **Record loader:** JSONL stream-read, header `schema_version` check with
   warn-on-mismatch, frame index.
4. **Playback scene v0:** scrub timeline over frames (render fidelity per
   `viewer-visual-language.md` is its own later work; foundation = load,
   scrub, inspect a frame).
5. **Run-to-watch splice:** `--record` appended at `calibration_tool.gd:141-145`,
   record path handed to the viewer after `:149-153`. Includes the
   tee-renderer (or `--record` on `run_match.py` mirroring HAJ-241's
   `main.py` flag) — coordinate with HAJ-241 so the flag lands once, not
   twice.
6. **Non-blocking run** (`OS.create_process` + poll): required here, not in
   Ticket A — watching is what makes the freeze unacceptable.

### Explicitly deferred

- Honoring `starting_position` / `forced_throw` in the engine (belongs to
  the match-engine cluster; the tool just stops lying about them).
- Disguise as a first-class attribute (engine design question flagged in
  `reaction_lag.py:98-102`).
- Per-throw effectiveness UI, signature-throw editing (spec's own v0.2 list).
- Export builds / theming / Compatibility-renderer switch.
- Delta encoding, live tweak-mid-match — per the contract and original spec.

---

*Pytest note (criterion 10): full suite run during this diagnosis —
1,569 tests collected, exit code 0 (run with `-s`; without it pytest's
capture teardown crashes on this machine). `src/run_match.py` is
structurally additive (new file, engine imports only, no engine edits).*
