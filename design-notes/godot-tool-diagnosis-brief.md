# Godot Calibration Tool — Diagnosis Brief for Claude Code
### HAJ-150 state-of-the-build + viewer-foundation readiness

*Drafted June 10, 2026. Sibling to `grip-model-handoff-2026-06-04.md` and
`viewer-data-contract-diagnosis.md` — same mandate: **diagnose before
implementing**. This session writes no code. Its deliverable is a findings
document with file references, from which two tickets get scoped: the
HAJ-150 completion pass, and the new Godot viewer-foundation ticket that
consumes HAJ-241's record files.*

---

## Orientation — read before touching anything

1. **HAJ-150** (Linear, now In Progress) — the original spec for the
   tool: per-fighter config UI, preset templates, subprocess invocation
   of the Python sim, log display, save/load config, docs. Written
   April 29; treat every claim in it as potentially stale in *both*
   directions — things specced may be unbuilt, things built may exceed
   or diverge from the spec. The spec also contains at least one known
   stale statement ("UE5 is the player-facing renderer" lives in the
   sibling HAJ-125; Godot is the engine target now). The ticket text is
   orientation, not ground truth.
2. **HAJ-241** (Linear) — the just-filed Python-side match record
   exporter (JSONL, one frame per tick, per `viewer-data-contract.md`
   v0.2). The Godot tool is the intended consumer: its "Run Match"
   subprocess call gains `--record`, and a playback scene loads the
   record. This diagnosis assesses how ready the existing project is to
   host that scene.
3. **`viewer-data-contract.md` v0.2** — the schema the playback scene
   will load. Read it for shape awareness; this session does not
   implement the loader.
4. Comrade has personally built a first version of the tool in Godot.
   It runs but "needs a little work" — part of this diagnosis is
   establishing precisely what that work is, as observed defects, not
   guesses.

**Hard rules for this session:**

- Diagnose, don't implement. No edits to `.gd`, `.tscn`,
  `project.godot`, or any Python file.
- Every finding carries a file reference (`scenes/main.tscn`,
  `scripts/config_panel.gd:42`, etc.). Godot scenes are text — `.tscn`
  files can be read and cited like source.
- Where the build diverges from the HAJ-150 spec, report the
  divergence neutrally. Divergence is data, not error — the spec may be
  the stale side.

---

## Part 1 — Locate and inventory

**Q1. Where does the Godot project live?** Find `project.godot`
(repo, sibling directory, or subdirectory of `C:\Users\jackc\hajime`).
Report: path, whether it's in git (and in *which* repo), Godot version
pinned in `project.godot` (`config/features`), and the rendering method
(Forward+ / Mobile / Compatibility) — the rendering method matters
later for `_draw()`-heavy viewer work and for export targets.

**Q2. Full project inventory.** Scene files, script files, any assets,
any saved config JSONs or presets. For the main scene, dump the node
tree (node names, types, script attachments). One tree, annotated, is
worth more than prose here.

**Q3. How is it launched?** From the editor only, or is there an
exported build / a documented launch path? Does
`docs/calibration-tool.md` exist (HAJ-150 acceptance criterion 9), and
if so, does it match reality?

## Part 2 — Build state against the HAJ-150 spec

**Q4. Acceptance-criteria audit.** For each of HAJ-150's ten
acceptance criteria, report MET / PARTIAL / ABSENT / DIVERGED, with the
file reference that proves it. Particular attention to:

- Which Identity/Capability fields the config panels actually expose
  vs. the spec's list (and whether any expose attributes that have
  since changed in `data-model.md` or the Python `Judoka` class — a
  drift check in both directions).
- Which preset templates exist and where they live (GDScript constants
  vs. JSON files — the spec's open question 3).
- Save/load config: present, partial, absent.

**Q5. The subprocess contract as actually implemented.** This is the
load-bearing question for the viewer extension. Report, with line refs
on both sides:

- What command does the tool actually run (interpreter path, module or
  script, flags, working directory)? Are paths hardcoded to this
  machine?
- What config JSON shape does the Godot side write, and what does the
  Python side expect? Does a `run_match.py --config/--output` entry
  point exist as the spec described, or did the integration land
  differently (e.g., against `src/run_match.py`'s existing
  `_JSONCaptureRenderer`)?
- What output does the tool read back today, and how does it render it
  (RichTextLabel? engineering-events toggle per criterion 6)?
- Blocking vs. non-blocking: `OS.execute()` (freezes the UI for the
  duration of the match) or `OS.create_process()` + polling? This
  decides whether the viewer ticket needs to fix responsiveness first.

**Q6. Observed defects.** Run the tool. List everything broken,
janky, or fragile as individual observations with reproduction notes —
startup errors, signal misfires, layout problems, path assumptions,
crashes on long logs. These become the HAJ-150 completion checklist.
File nothing yet; the ticket split happens after findings come back.

## Part 3 — Viewer-foundation readiness

**Q7. Scene architecture headroom.** Is the project structured so a
second top-level scene (the record playback viewer) can be added
cleanly — a main scene that could become a launcher/tab container, or a
single God-scene where everything is wired into one script? Report
what a `RecordViewer` scene would attach to and what, if anything,
would need restructuring first. Restructuring proposals are findings,
not actions.

**Q8. Reusable plumbing.** What JSON parsing, file I/O, and
path-resolution code already exists in the project that the record
loader should reuse rather than duplicate? Any existing autoloads/
singletons (settings, paths) the viewer scene should hang off?

**Q9. The run-to-watch seam.** Trace exactly where in the GDScript the
subprocess invocation is built and where the output path is consumed —
the two lines where `--record` and "open the record in the viewer
scene" will eventually splice in. Cite them.

---

## Output format

A single findings document
(`godot-tool-diagnosis-YYYY-MM-DD.md`), structured as: project
inventory (Q1–Q3), acceptance audit table (Q4), subprocess contract
(Q5), defect list (Q6), viewer readiness (Q7–Q9), and a closing
**proposed ticket split** — what belongs in a HAJ-150 completion
ticket vs. the new viewer-foundation ticket vs. explicitly deferred.
The split is a proposal; Comrade decides after reading.

No implementation in this session. The fastest way to make the viewer
real is to know precisely what it's being built into.
