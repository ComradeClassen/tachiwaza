# Hajime Restructure Session — Handoff (April 25, 2026, end-of-session)

Supersedes the earlier April 25 handoff. Pass 4 + Pass 5 + design notes all 
done in this session.

## What just happened (this session)

**Pass 4 — 22 new tickets filed across three batches:**

- *Batch 1 — Ring 1 Phase 3 audit gaps (HAJ-68 followups):* 
  HAJ-93 (golden score), HAJ-94 (direct hansoku-make), 
  HAJ-95 (time-expiration at max_ticks). HAJ-93 and HAJ-95 related-to linked.
- *Batch 2 — v17 sub-questions to Design & Triage:* HAJ-104 (lifecycle), 
  HAJ-106 (antagonist), HAJ-107 (opening tuning), HAJ-108 (session 
  composition), HAJ-109 (culture & psychology, **High**), HAJ-110 (rankings), 
  HAJ-111 (Inheritance Event), HAJ-112 (Career Mode, **High**), 
  HAJ-113 (lineage system, **High**).
- *Batch 3 — Ring 2 Phase 1 starter set, Personal Checkpoint milestone:* 
  HAJ-114 (calendar data model, **High**), HAJ-115 (calendar UI minimum), 
  HAJ-116 (time-scale controls), HAJ-117 (roster notepad mode), 
  HAJ-118 (basement-opening character creation, **High**), 
  HAJ-119 (three-class break-even economy), 
  HAJ-120 (opening Anchoring Scene event = scene presentation pattern, **High**), 
  HAJ-121 (Twins Arrive event hook), HAJ-122 (watched randori — Ring 1↔Ring 2 
  bridge), HAJ-123 (antagonist visit, one-time). Dependency edges set: 
  HAJ-115/116 ← HAJ-114; HAJ-121 ← HAJ-114, HAJ-118, HAJ-120; 
  HAJ-123 ← HAJ-114, HAJ-120.

**Pass 5 — cycle setup:** Cycle 1 (Apr 17 → May 1) already exists and is 
current; 54 issues in it. Decision: leave all 54 in cycle, treat 
HAJ-39, 40, 43, 44, 46 as the mental focus set without enforcement. 
Cycles 2 (May 1–15) and 3 (May 15–29) exist and are empty.

**Cowork — design-notes folder cleanup:** done.

**Design notes drafted (four):**

- `lineage-system.md` — new file, ~1,300 words. Resolves HAJ-113. Commits to: 
  4-piece bundle (tradition/techniques/philosophy/rituals), graph data model, 
  within-dojo multi-source transmission (head coach + assistants + senior 
  students), authored starting lineage from "the father" (no Papi naming), 
  three drift modes (preserve/extend/refuse), post-hoc visualization not 
  active management, cross-run persistence as second-run hook, bias-not-
  constrain on culture vector.
- `career-mode-and-narrative-events.md` — new file, ~1,800 words. 
  Resolves HAJ-112. Commits to: 5–10 in-game years per run, 15–25 hrs 
  real-time, two Anchoring Scenes (opening Twins Arrive + closing inheritance 
  scene — closing is condition-fixed not character-fixed), emergent middle, 
  **failure becomes succession not game-over** (time-skip + character handoff, 
  multiple successions per run possible, successor can buy a different dojo), 
  flat-with-shifting-kind difficulty, six event categories (Anchoring, 
  Succession, Antagonist, Lifecycle, Cultural, Ambient), three authoring 
  tiers (hand/templated/procedural).
- `dojo-as-institution.md` — unification expansion, ~1,800 words. Diff against 
  existing file before replacing. Central thesis: dojo is an institution, not 
  a place + coach + roster. Commits to: institutional identity (name, founding 
  date, founding lineage, history, public-facing identity) persists through 
  succession; physical layer as constraint not flavor; Six Cultural Inputs as 
  levers on the institution (succession finds them where they were left); 
  reputation institutional and persistent; material economy carries through 
  succession unless explicitly liquidated; rituals as institutional memory 
  with default-preserve on succession; basement and full-dojo are same entity 
  at different scales.
- `cultural-layer-update.md` — additive, ~1,300 words. **Fold into existing 
  cultural-layer.md, do not replace.** Names the Six Cultural Inputs as 
  canonical and complete lever set with a primary-axis mapping per lever and 
  cadence variation (fast/medium/slow/episodic). Commits to: 
  sustained-pattern inertia for vector movement; successor inherits vector 
  position, not lever positions; vector-level abstraction for the 
  student-inner-lives readout (students react to compounded vector, not to 
  individual decisions).

All four files in `/mnt/user-data/outputs/` for this session — copy into 
`C:\Users\JackC\Hajime\design-notes\`.

## Locked decisions (carry forward)

From prior session, all still hold:

- Hajime is primary through Jan 9, 2027 and beyond. Player Two paused.
- EA horizon: mid-2028 to mid-2029.
- **January 9, 2027 = Personal Checkpoint** (Comrade's birthday). Not public.
- Career Mode (Wildermyth-style) ships at EA. Sandbox post-EA.
- Player Two psychology built inside Hajime via student-inner-lives 
  (Ring 2 Phase 3).
- Five thesis principles named.
- Six Cultural Inputs (now formally specified — see `cultural-layer-update.md`).

New decisions locked this session:

- **Two Anchoring Scenes per run, not three.** Opening (Twins Arrive) and 
  closing (an inheritance scene). Tanaka vs Sato was illustrative of "what 
  watching a match feels like," not a fixed plot beat. The middle is fully 
  emergent. The closing is condition-fixed, not character-fixed — whoever's 
  running the dojo at run's end gets the closing.
- **Failure becomes succession, not game-over.** Collapse triggers a 
  time-skip + new player-character takeover. Lineage transmits; sometimes 
  the institution itself transmits, sometimes the successor buys a different 
  dojo and the original closes. Multiple successions per run possible.
- **Lineage is a graph, not a chain.** Multi-source within-dojo transmission. 
  The dojo (not the coach) is the unit of cultural and lineage transmission.
- **Design notes are now the load-bearing layer for High-priority Design & 
  Triage tickets:** HAJ-109, HAJ-112, HAJ-113 are partially or fully 
  resolved by the four notes above.

## Linear key IDs

**Projects** (unchanged from prior session):
- Ring 1 — Match Engine: `ab7d5e7b-808d-4461-bbc3-dc9005b40d69`
- Ring 2 — The Dojo Loop: `7ee40ad1-3001-4766-8438-39d270a9f976`
- Ring 3 — Narrative Event Framework: `3dd769ba-0a4a-4d32-b755-08815327c4e0`
- Ring 4 — Sandbox + Multi-Dojo: `f97f95b9-0ef5-447a-89f0-d84c0915dbc2`
- Ring 5 — Visual Layer: `fc60bde2-2adb-4cf1-ba04-d4dc926db9db`
- Ring 6 — Sound: `ecd0400e-bca2-4aff-aa73-d3ba1dc081f6`
- Infrastructure & Polish: `1d6391ec-594a-431d-8677-94b2fb2d67b4`
- Design & Triage: `f7bcfb5f-2c16-45c7-b523-a11a8331d78b`

**Cycles** (Hajime team `d5152ff1-0376-4607-bdbe-346a41bcb9b3`):
- Cycle 1 (current, Apr 17 – May 1): `1549b9b6-3693-4320-8d72-5f212154a81d`
- Cycle 2 (May 1 – May 15): `eea4ad6a-aac3-419c-8b23-6f3edb8a4de5`
- Cycle 3 (May 15 – May 29): `4e496467-5a8d-4e34-8b9e-a0cef5406607`

**Active milestones:**
- Ring 1 Phase 3 — Calibration & Grip-as-Cause Refactor (target 2026-06-30): 
  `0ae0cc78-0d1e-4f41-9376-3bd15ec9c73b`
- Ring 2 Phase 1 — Personal Checkpoint (target 2027-01-09): 
  `b6a10181-be96-4ceb-867e-d0d4f2f449b7`

## What's next (priority order)

1. **README rewrite.** Doc layer just settled — README is the next 
   structural pass. Should reflect the Ring/project structure, the two 
   Anchoring Scenes, the succession model, and the lineage-is-the-second-run-
   hook framing.

2. **Session 5 of Ring 1 calibration** (queued, post-restructure). Foundation 
   tickets: HAJ-39 (watch 5 Euro matches) gates HAJ-40 (draft what match 
   should look like). HAJ-52 (refine Gemini prompt) supports the calibration 
   workflow.

3. **Ring 2 Phase 1 implementation start.** HAJ-114 (calendar data model) 
   is the unblocking foundation — most other Ring 2 Phase 1 tickets depend 
   on it directly or transitively. HAJ-118 (character creation) and HAJ-120 
   (scene presentation pattern) are the other two High-priority foundations 
   and can land in parallel.

4. **Ring 1 Phase 3 audit-gap tickets implementation:** HAJ-93, HAJ-94, 
   HAJ-95 — close the rule-coverage holes the HAJ-68 audit found.

5. **Remaining Ring 2 Phase 1 design questions (Design & Triage):** 
   - HAJ-104 (lifecycle), HAJ-107 (opening tuning), HAJ-108 (session 
     composition), HAJ-110 (rankings), HAJ-111 (Inheritance Event), 
     HAJ-106 (antagonist) all need at least light design work before their 
     downstream Phase 1 tickets can land cleanly.
   - Drafting a `lifecycle.md` design note is the natural next-doc — it's 
     referenced by Personal Checkpoint requirement "3 students in lifecycle" 
     and HAJ-118 punts the attribute model to it.

## Active Phase 3 tickets to be aware of

23 active Todo/Backlog tickets in Ring 1 Phase 3 (was 20; +3 from this session):

- *Calibration:* HAJ-39, HAJ-40, HAJ-41, HAJ-52
- *Bugs:* HAJ-43, 44, 45, 46, 47, 48
- *Mechanics/Additions:* HAJ-51, 53, 54, 56, 57, 58, 64, 69, 70, 71
- *New audit-gap tickets:* HAJ-93, 94, 95

10 already-Done in Phase 3: HAJ-49, 50, 55, 59, 62, 65, 66, 67, 68, 77.

## Active Personal Checkpoint tickets

10 Backlog tickets in Ring 2 Phase 1 (Personal Checkpoint milestone):

- *Foundations (High):* HAJ-114 (calendar data model), HAJ-118 (basement-
  opening character creation), HAJ-120 (opening Anchoring Scene event = 
  scene presentation pattern).
- *Calendar surface:* HAJ-115 (UI minimum, blocked by HAJ-114), 
  HAJ-116 (time-scale controls, blocked by HAJ-114).
- *Roster:* HAJ-117 (notepad mode).
- *Economy:* HAJ-119 (three-class break-even).
- *First narrative events:* HAJ-121 (Twins Arrive, blocked by 114/118/120), 
  HAJ-123 (antagonist visit, blocked by 114/120).
- *Engine bridge:* HAJ-122 (watched randori — Ring 1 ↔ Ring 2).

## Active Design & Triage queue

9 design questions filed this session:

- **High:** HAJ-109 (culture & psychology — partially resolved by 
  cultural-layer update), HAJ-112 (Career Mode — resolved by 
  career-mode-and-narrative-events.md), HAJ-113 (lineage system — resolved 
  by lineage-system.md).
- **Normal:** HAJ-104 (lifecycle), HAJ-106 (antagonist), 
  HAJ-107 (opening tuning), HAJ-108 (session composition), 
  HAJ-110 (rankings), HAJ-111 (Inheritance Event).

## Known loose ends (carry forward)

1. Shallow-grips ladder — silent DEEPEN vs loud STRIP oscillation. HAJ-34 
   hides at log layer; may need rework.
2. HAJ-31's grip-presence commit gate not yet formalized in 
   `physics-substrate.md` Part 3.3.
3. Pin WAZA_ARI first-award has no `[score]` line — asymmetric with throw.
4. Desperation overlay and `failed_dimension` don't surface in coach stream.
5. ne-waza vs stand-up gap (ne-waza reads exciting; stand-up flat) — 
   calibration concern, not a bug.
6. **New:** `dojo-as-institution.md` was rewritten as unification rather than 
   strict additive expansion. Diff against existing file before replacing. 
   Some reorganization is intentional; check that no prior content was lost.
7. **New:** Cycle 1 has 54 issues. Disciplined cycle hygiene is deferred — 
   if cycle becomes useless as a focus signal, revisit the "leave all in" 
   choice.
