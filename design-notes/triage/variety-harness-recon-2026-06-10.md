# Variety Harness — Phase A Recon (2026-06-10)

Codebase-grounded answers to the four Phase A questions from the variety-harness brief,
plus the proposed fixture roster. All references are `file:line` on `main` @ `b94aab2`.
Where `data-model.md` and the implementation disagree, the implementation is reported
and the conflict flagged.

**Status: awaiting owner sign-off on the roster (hard gate). No harness code written.**

---

## 1. Constructor reality

A fighter is `Judoka(identity=Identity(...), capability=Capability(...), state=State.fresh(capability, identity))`
([judoka.py:367](../../src/judoka.py#L367), built exactly this way for Tanaka at
[main.py:44-137](../../src/main.py#L44) and Sato at [main.py:145-241](../../src/main.py#L145)).

**`Identity` required fields** ([judoka.py:82-93](../../src/judoka.py#L82)):
`name, age, weight_class, height_cm, body_archetype, belt_rank, dominant_side`.
Optional with defaults: `personality_facets` (dict, 0–10 per facet), `tokui_waza`,
`arm_reach_cm=185`, `hip_height_cm=98`, `weight_distribution="NEUTRAL"`,
`mass_density="AVERAGE"`, `nationality`, `training_lineage`, `style_dna`,
`stance_matchup_comfort`, `positional_style` (defaults `HOLD_CENTER` via
`__post_init__`, [judoka.py:126-132](../../src/judoka.py#L126)).

**`Capability` required fields** ([judoka.py:139-166](../../src/judoka.py#L139)):
the original 15 body parts (0–10 ints), `cardio_capacity`, `cardio_efficiency`,
`composure_ceiling`, `fight_iq`, `ne_waza_skill`. Optional: `foot_speed=5`
([judoka.py:173](../../src/judoka.py#L173)), `throw_vocabulary`, `throw_profiles`,
`signature_throws`, `signature_combos`, and the 9 v0.4 body parts with defaults
([judoka.py:181-191](../../src/judoka.py#L181)).

**Hidden third input — `skill_vector`:** `Judoka.__post_init__` auto-seeds a 22-axis
skill vector from **belt rank** ([judoka.py:405-409](../../src/judoka.py#L405),
[skill_vector.py](../../src/skill_vector.py)). Many code paths read
`skill_vector.axis()` with a `fight_iq/10` fallback. Consequence for fixtures:
**belt rank is a stat**, not flavor — it drives skill-vector defaults, engagement
reach ticks ([grip_graph.py:271-272](../../src/grip_graph.py#L271)), and the stance
comfort vector. The roster holds belt constant (BLACK_1) on every fixture so it never
confounds an axis.

**`body_archetype`** is set on Identity ([judoka.py:89](../../src/judoka.py#L89)).
**All five enum values are live in engine logic** — none is merely defined:

| Where | What it does | Ref |
|---|---|---|
| Grip initiative bonus | GRIP_FIGHTER +1.5 / MOTOR +0.6 / EXPLOSIVE +0.5 / LEVER +0.4 / GROUND_SPECIALIST −0.2 (matched table; mirrored shrinks GRIP_FIGHTER to 0.8) | [grip_initiative.py:82-98](../../src/grip_initiative.py#L82) |
| Grip response weights | per-archetype multipliers on CONTEST/PURSUE_OWN/ACCEPT_BAIT etc. | [grip_initiative.py:297-330](../../src/grip_initiative.py#L297) |
| Strip propensity | GRIP_FIGHTER 0.60 … GROUND_SPECIALIST 0.20 | [action_selection.py:508-523](../../src/action_selection.py#L508) |
| Post-score chase | GROUND_SPECIALIST +0.30 | [chase_decision.py:74-80](../../src/chase_decision.py#L74) |
| Ne-waza defense decision | scramble/defend-bottom bonuses | [defense_decision.py:83-98](../../src/defense_decision.py#L83) |
| Cross-grip seeking | GRIP_FIGHTER 1.6 … GROUND_SPECIALIST 0.7 | [cross_grip.py:112-116](../../src/cross_grip.py#L112) |
| Tactical stance switch | GRIP_FIGHTER 1.5 … GROUND_SPECIALIST 0.7 | [stance.py:196-202](../../src/stance.py#L196) |

**Existing fighter builders:** Tanaka (LEVER), Sato (MOTOR), Yamamoto/Kimura
(white-belt clones, [main.py:250-263](../../src/main.py#L250)), Renard
(GROUND_SPECIALIST grinder, [main.py:274-337](../../src/main.py#L274)). Also relevant:
**[run_match.py:63-136](../../src/run_match.py#L63)** (`_build_judoka`) already builds
a Judoka from a JSON config dict — the Godot calibration tool's entry point (HAJ-150).
It is precedent for config-driven fixtures, but see §3 for its seeding gap.

---

## 2. Which stats are wired to outcomes

### Grip — WIRED, but split across two distinct mechanics

The grip axis is **two separate systems** and a grip-fighter caricature must max both:

1. **Who reaches first / how exchanges are contested (initiative)** — does **NOT**
   read hand stats at all. `expected_initiative` is aggressive facet (weight 2.0,
   the largest), archetype bonus, fight_iq, composure, height delta, fatigue,
   familiarity ([grip_initiative.py:170-214](../../src/grip_initiative.py#L170)).
   The pre-grip engagement "reach race" is **belt-based ticks only**
   ([grip_graph.py:271-272](../../src/grip_graph.py#L271)).
2. **How strong a seated grip is (force/strip)** — DOES read hand stats.
   `force_envelope.grip_strength` = avg effective `right_hand + left_hand + core`
   ([force_envelope.py:168-174](../../src/force_envelope.py#L168)) and multiplies into
   delivered pull force ([force_envelope.py:196-211](../../src/force_envelope.py#L196)),
   strip force ([match.py:2314](../../src/match.py#L2314)), strip resistance
   ([grip_graph.py:429-435](../../src/grip_graph.py#L429)), grip-seat strength
   ([match.py:2774](../../src/match.py#L2774), [grip_graph.py:307](../../src/grip_graph.py#L307)),
   and **kuzushi pull magnitude** ([kuzushi.py:514-522](../../src/kuzushi.py#L514)).
   Forearms/biceps/wrists fatigue-side parts matter less directly; hands + core are
   the load-bearing stats.

Trace, stat → outcome: `right_hand=10` → `effective_body_part` ([judoka.py:420-450](../../src/judoka.py#L420))
→ `grip_strength` → `delivered_pull_force` / strip contests → grip dominance and
kuzushi events → throw windows.

### Ground — WIRED on the mat; entry is the bottleneck

- `ne_waza_skill` feeds escape rolls (`_roll_escape`,
  [ne_waza.py:874-899](../../src/ne_waza.py#L874); +0.008/point,
  [ne_waza.py:198](../../src/ne_waza.py#L198)), submission advance/defense
  ([ne_waza.py:790-791](../../src/ne_waza.py#L790), [ne_waza.py:843-845](../../src/ne_waza.py#L843)),
  counter-action choice (which also reads `effective_body_part` of hands/core/hips,
  [ne_waza.py:916-943](../../src/ne_waza.py#L916)), catalog consumption rolls
  ([ne_waza_consumption.py:492-504](../../src/ne_waza_consumption.py#L492)),
  position transitions ([position_machine.py:198-200](../../src/position_machine.py#L198)),
  post-score chase ([chase_decision.py:143-148](../../src/chase_decision.py#L143)),
  and defense decisions ([defense_decision.py:166-191](../../src/defense_decision.py#L166)).
- `GROUND_SPECIALIST` archetype biases chase (+0.30), scramble (+0.15),
  defend-bottom (+0.20) — refs in §1 table.
- **Entry paths that exist:** stuffed-throw spill via the HAJ-236 ground-continuation
  roll (reads both fighters' `ne_waza_skill`,
  [ground_continuation.py:141-146](../../src/ground_continuation.py#L141)), sacrifice-throw
  landings, and post-score chase. **There is NO deliberate standing→ground action**
  (no snap-down / drop-to-guard / drag-down). A ground specialist cannot *initiate*
  ground work; he can only capitalize when the standing game produces a spill.
  **Roster consequence:** the ground pairing must pair the specialist against an
  aggressive, low-quality thrower so stuffed attempts generate entry rolls. If the
  log still shows near-zero ne-waza, that is the diagnostic result, not a fixture bug.

### Physical — partially wired

| Stat | Wired? | Where |
|---|---|---|
| `height_cm` | **Yes, one place** | grip initiative, weight 0.4 per 30 cm delta ([grip_initiative.py:196-200](../../src/grip_initiative.py#L196)). A 38 cm caricature gap ≈ +0.5 on a ~0–6 score — real but modest. |
| `hip_height_cm` | Yes (geometry) | seeds CoM height ([judoka.py:317](../../src/judoka.py#L317)); kuzushi/recovery geometry + viewer. |
| Body-part strength | **Yes** | throw success: attacker key-part avg vs defender legs/core/neck ([match.py:1028-1066](../../src/match.py#L1028)); leg strength → recoverable envelope ([judoka.py:411-418](../../src/judoka.py#L411), [body_state.py:224-296](../../src/body_state.py#L224)). |
| `foot_speed` | Yes | per-tick locomotion ([action_selection.py:1508-1560](../../src/action_selection.py#L1508)). |
| `cardio_capacity/efficiency` | Yes | `cardio_current` → fatigue fraction → initiative penalty, grip force, chase, desperation. |
| `arm_reach_cm` | **NO** | declared with comment "who grips first at engagement" ([judoka.py:106](../../src/judoka.py#L106)) but **never read**. Engagement reach is belt-based. `data-model.md` drift. |
| `mass_density`, `weight_distribution`, `weight_class` | **NO** | never read by engine logic. There is **no mass term anywhere in throw physics**. |
| `tokui_waza` | **NO** | declared ([judoka.py:100](../../src/judoka.py#L100)), never read. The comment claims grip-modulator reads; none exist. |
| "explosive/speed" stat | **Doesn't exist** | EXPLOSIVE expresses only through archetype tables (PURSUE_OWN ×1.8, ACCEPT_BAIT ×1.8, tactical stance ×1.2). `foot_speed` is the only speed-like stat and feeds locomotion only. |

**Unbuildable axes:** "short **dense** fighter" (no mass mechanic — density can only be
faked as high core/leg strength, which confounds with the strength axis), reach
(arm_reach unwired), and a stat-driven EXPLOSIVE caricature.

### fight_iq — the most-wired stat in the engine

Beyond the HAJ-237 stance-switch roll ([stance.py:239-272](../../src/stance.py#L239)):
grip initiative (weight 1.0 matched, **2.0 mirrored**,
[grip_initiative.py:104-114,193](../../src/grip_initiative.py#L104)), grip response
selection ([grip_initiative.py:356-365](../../src/grip_initiative.py#L356)), perception
noise ([perception.py:45](../../src/perception.py#L45)), reaction lag
([reaction_lag.py:133](../../src/reaction_lag.py#L133)), multi-tick planning gate
([intent.py:157](../../src/intent.py#L157)), foot-attack setups
([action_selection.py:596-598](../../src/action_selection.py#L596)), false-attack gate
([action_selection.py:1297](../../src/action_selection.py#L1297)), edge pressure
([action_selection.py:743-749](../../src/action_selection.py#L743)), counter windows
([counter_windows.py:345](../../src/counter_windows.py#L345)), failure resolution
([failure_resolution.py:180](../../src/failure_resolution.py#L180)), sweep-counter gate
([defense_decision.py:190](../../src/defense_decision.py#L190)), shido/throw weighing
([match.py:6703](../../src/match.py#L6703)), cross-grip fluency
([cross_grip.py:129-130,202](../../src/cross_grip.py#L129)), and the skill-vector
fallback ([skill_vector.py:126-140](../../src/skill_vector.py#L126)). An IQ-contrast
pairing should be the loudest axis in the battery.

### Stance comfort (HAJ-237/238) — seedable at construction

`State.fresh` calls `stance.initial_stance_comfort(identity, base_stance)`
([judoka.py:345](../../src/judoka.py#L345)). Belt-gated defaults
([stance.py:94-128](../../src/stance.py#L94)), and **`Identity.stance_matchup_comfort`
overrides any axis directly** — keys `"orthodox"`, `"southpaw"`, `"kenka_yotsu"`
([stance.py:124-128](../../src/stance.py#L124)). So fixtures set it deliberately via
Identity, no post-construction mutation needed.

**Caveat:** `base_stance` is **hardcoded ORTHODOX for everyone**
([judoka.py:334-336](../../src/judoka.py#L334)) — `DominantSide.LEFT` flips which hand
counts as dominant but does NOT start a fighter southpaw. A "natural southpaw" fixture
requires mutating `state.base_stance`/`state.current_stance` after construction
(test-only mutation, acceptable in a fixture factory; flagged for owner awareness).

---

## 3. Existing run/batch machinery

- **Batch + seed already exist:** `python src/main.py --runs N --matchup K --seed S --stream debug`
  ([main.py:445-451,560-572](../../src/main.py#L445)). Per-match seed = `seed + i`, so
  every printed match is replayable with `--seed <that> --runs 1`
  ([main.py:494-507](../../src/main.py#L494)).
- **Two-layer seeding pattern (must copy):** `_run_one_match` calls
  `random.seed(seed)` for module-level RNG ([main.py:375-377](../../src/main.py#L375))
  AND passes `seed` to `Match`, which derives keyed per-purpose streams like
  `random.Random(f"haj151:init:{name}:{seed}:{tick}")`
  ([match.py:2543-2547](../../src/match.py#L2543) and ~15 similar sites). Both are
  required: throw resolution ([match.py:1069](../../src/match.py#L1069)) and ne-waza
  ([ne_waza.py:794,847](../../src/ne_waza.py#L794)) still use module-level `random`.
- **Finding — run_match.py reproducibility gap:** [run_match.py](../../src/run_match.py)
  passes `seed` to Match but never calls `random.seed`, so its module-level rolls are
  unseeded → Godot-tool runs are not fully reproducible. Not our bug to fix under this
  brief, but the harness must use main.py's two-layer pattern, not run_match.py's.
- Matchups are hardcoded in `MATCHUPS` ([main.py:343-357](../../src/main.py#L343)); the
  harness runner should take fixture names instead.

## 4. Log comparability

- Match output is `print()` to stdout in three streams (`debug` / `coach` / `both`
  side-by-side; [main.py:464-475](../../src/main.py#L464)). Nothing writes to a file
  today.
- Capture options, both viable without engine changes:
  1. **stdout redirection** per match (`contextlib.redirect_stdout` to a UTF-8 file) —
     gets exactly what the owner reads today. `--stream debug` (single-column,
     tick-prefixed) is the greppable choice for side-by-side comparison.
  2. **Renderer event capture** — `run_match._JSONCaptureRenderer`
     ([run_match.py:165-182](../../src/run_match.py#L165)) already proves the pattern:
     a renderer receives every per-tick event list (structured, with prose + data).
- Recommendation: the runner writes one `.log` (redirected stdout, debug stream) per
  match to `design-notes/qa/variety/<pairing>/<seed>.log`, plus a one-line result
  summary (winner / method / ticks / ne-waza-entered count) per repetition so 5-rep
  batches can be eyeballed as a set. UTF-8 explicitly (Windows cp1252 kills the arrow
  glyphs — same issue run_match.py:24-37 works around).

---

## 5. Proposed fixture roster (for sign-off)

**Shared skeleton** (every fixture, only the named axis deviates): all 24 body parts 5,
cardio 5/5, composure 5, fight_iq 5, ne_waza_skill 5, foot_speed 5, height 175,
hip_height 98, belt **BLACK_1** (constant to neutralize skill-vector/reach/comfort
gating), all facets 5, `positional_style=HOLD_CENTER`, shared 6-throw vocabulary with
flat 5/5 profiles (same list for everyone so throw families never confound). Archetype
for non-archetype-axis fixtures: **LEVER** as the least-marked control — there is no
neutral archetype (every value carries modifiers); LEVER's are smallest. This is a
known impurity, accepted and logged.

Pairings are polar caricature pairs, one axis varied per preset:

| # | Preset | Fixture A | Fixture B | Binary question |
|---|---|---|---|---|
| 1 | `grip` | **Grip Monster** — GRIP_FIGHTER, hands+core 10 (forearms/wrists 9), aggressive 9 | **Passive Median** — LEVER, all median, aggressive 1 | Does A visibly win reach + strip + depth, and convert grip dominance to kuzushi? |
| 2 | `ground` | **Ground Hunter** — GROUND_SPECIALIST, ne_waza 10 | **Standing Wall** — LEVER, ne_waza 1, legs/core/neck 10, aggressive 8 (high attempt rate feeds the stuffed-throw entry roll) | Does ground work get *entered*, and does A dominate once there? (Near-zero entry is itself the finding — no deliberate drag-down exists.) |
| 3 | `height` | **Tower** — LEVER, height 196, hip_height 110 | **Fireplug** — LEVER, height 158, hip_height 86 | Does the height delta show in grip initiative at all? (Expect modest: 0.4-weight axis. "Dense" dropped — mass is unwired.) |
| 4 | `iq` | **Professor** — fight_iq 10 | **Brawler** — fight_iq 1 (same body) | Do plans/combos/reads/reaction beat a stat-identical novice? Loudest wired axis. |
| 5 | `cardio` | **Diesel** — cardio 10/10 | **Gasser** — cardio 2/2 | Does fatigue visibly flip the match in the second half? |
| 6 | `kenka` | **Kenka Hunter** — `stance_matchup_comfort={"kenka_yotsu":1.0,"southpaw":0.95}`, fight_iq 8 | **Ai-yotsu Purist** — `{"kenka_yotsu":0.05,"southpaw":0.05}`, fight_iq 8 | Does A force/thrive in MIRRORED (cross/pistol grips, tactical switches) while B avoids it? (Both get IQ 8 — tactical switching is IQ-gated; flagged impurity.) |

**Axes I cannot build meaningfully (reported, not patched):**
- **Mass/density** — no mass term in any roll. "Tall lever vs short dense" reduces to a height-only pairing.
- **Reach** — `arm_reach_cm` unwired; engagement reach is belt ticks.
- **EXPLOSIVE-as-stat** — archetype-table expression only; a stat-pure explosive fixture has no stat to max. (An archetype-bundle EXPLOSIVE fixture is possible later if wanted.)
- **Natural southpaw** — `base_stance` hardcoded ORTHODOX; needs post-construction state mutation if the owner wants it.

**Proposed locations (Phase B, post-sign-off):** fixtures in `tests/fixtures/archetypes.py`
(`tests/fixtures/` already exists); runner CLI at `src/variety_harness.py` (imports
mirror run_match.py), default N=5, logs to `design-notes/qa/variety/`.

---

## data-model.md conflicts found (summary)
1. `arm_reach_cm` — claimed grip-radius input; never read (belt-based reach instead).
2. `tokui_waza` — claimed read by grip-configuration modulators; never read.
3. `mass_density` / `weight_distribution` / `weight_class` — declared physical variables; no engine reads, no mass term in throw resolution.
4. `dominant_side=LEFT` does not produce a southpaw starting stance (`base_stance` hardcoded ORTHODOX).
5. run_match.py (HAJ-150 tool) seeds Match streams but not module-level RNG — replays from the Godot tool are not exact.
