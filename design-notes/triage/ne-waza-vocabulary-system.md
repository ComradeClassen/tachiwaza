# Ne-waza vocabulary system

### Schema spec for katame-waza catalog, dominant-position catalog, and defensive strut catalog

*v0.1, drafted 2026-05-19. Sibling to `technique-vocabulary-system.md` (tachiwaza). This document specifies how ne-waza techniques and positions are represented as catalog data, parallel to but structurally distinct from the tachiwaza catalog. Source corpus: `ne-waza-substrate.md` v0.1 (Cranford six-video synthesis); `Judo_Biomechanics_for_Simulation__Kuzushi__Couples__and_Levers.md` (Sacripanti); Kodokan Judo (Kano) — Chapter 7 Katame-waza, pages 110–130, covering osaekomi, shime, and kansetsu sections including paired offense/defense data for each named technique.*

*This is a v0.1 spec, not finished. The corpus is bounded — Kodokan-canonical techniques only, primary-finish defenses only, no positional defenses or scrambles. The substrate is designed to extend cleanly. The v0.1 commitments are what the current corpus supports.*

---

## Why this exists

Hajime's tachiwaza is data-driven: the catalog declares each throw's grip configuration, kuzushi vectors, mechanical class, and stake. The resolver consumes the catalog plus judoka attributes plus match context to produce outcomes. Stand-up reads as judo because the catalog encodes what makes each throw mechanically distinct, and the resolver consumes that as substrate.

Ne-waza has not had this. The position state machine declares enums (`SIDE_CONTROL`, `MOUNTED`, `TURTLE_TOP`, etc.), the `OsaekomiClock` accumulates pin time, and submissions resolve as multi-turn commitment chains, but there is no catalog of named ne-waza techniques with their connections, defenses, and finishes. Two fighters in `SIDE_CONTROL` could be in kesa-gatame, kata-gatame, or kuzure-yoko-shiho — the engine doesn't distinguish. Ne-waza reads as state transitions because the substrate doesn't encode what makes each technique mechanically distinct.

This spec closes that gap. It defines three sibling catalogs (techniques, dominant positions, defensive struts) plus the ne-waza-specific connection-type vocabulary that ties them together. Authoring against this spec produces the same kind of texture for ne-waza that the tachiwaza catalog produced for stand-up.

---

## How ne-waza differs from tachiwaza

The catalog forks because the substrate forks. Five differences drive the schema:

**Score mechanism varies per technique.** Tachiwaza techniques all produce a throw outcome (ippon/waza-ari/yuko based on the landing geometry). Ne-waza techniques split into two score families: osaekomi accumulates pin time toward ippon, while shime/kansetsu fire a tap-check loop with immediate submission as the outcome. The catalog declares which family each technique belongs to.

**Position dependence varies per technique.** Some ne-waza techniques fire only from specific positions (kesa-gatame requires side-attached side control; juji-gatame requires uke's arm extended with tori controlling it). Others are position-agnostic (gyaku-juji-jime: *"can be applied from above, from the sides, while on one's back, or while standing"* per Kodokan Judo p.118; hadaka-jime: *"can also be applied to an opponent who is standing or lying on the mat"* per p.120; ude-hishigi-sankaku-gatame: *"can be done from the front, the side or the rear"* per p.130). The catalog handles this with an optional `fires_from_position` field — required for position-dependent techniques, omitted for position-agnostic ones.

**Some positions are dominant.** Per substrate Part 5, certain ne-waza positions offer multiple terminal techniques and induced transitions between them — sankaku is the textbook case, with three named finishes (sankaku-jime choke, ude-hishigi-sankaku-gatame armlock, and the Cranford-identified sankaku pin) all firing from the same triangle geometry. Dominant positions are first-class catalog objects in their own right, parallel to techniques. Non-dominant positions (kesa-gatame, kata-gatame, etc.) are single-finish terminal states that don't need position entries.

**Defenses are reusable mechanical primitives.** In tachiwaza, defense is encoded per-throw as `failed_throw_consequence` and the kuzushi/grip filtering at Stage 1. In ne-waza, defenses are a small set of named primitives (bridge-and-roll, frame-and-shrimp, etc.) that apply across many techniques. The same `bridge_and_roll` strut defends against kesa-gatame, kata-gatame, kami-shiho, and tate-shiho with different parameters. This compression is real and load-bearing — fifteen primitives defend ~40 named techniques. Defensive struts are a third catalog file.

**Connection types are new vocabulary.** Tachiwaza grips are hand-on-uke-garment at named locations. Ne-waza connections are distributed body-pressure contacts, anatomical traps, lapel crosses, forearm bars, leg triangles, limb isolations — none of which fit the tachiwaza grip taxonomy. Per substrate Part 3.1: *"the substrate forks: ne-waza has its own grip graph with its own base types and its own mechanical attributes. The two graphs are siblings, not parent-child."* This spec enumerates twelve ne-waza connection types organized into two contexts (pin-context and submission-context).

The shape of the spec follows from these differences. Sections 2–4 define the three sibling catalogs. Sections 5–6 define the shared substrate vocabulary (connection types, defensive struts) the catalogs reference. Sections 7–8 handle naming overlay and belt thresholds, parallel to tachiwaza. Section 9 closes with open questions authoring will resolve.

---

## 1. Two-stage resolution for ne-waza

Parallel to tachiwaza's Stage 1 (grip-configuration availability) and Stage 2 (kuzushi-vector ranking), ne-waza resolution runs two stages:

**Stage 1 — availability.** Filters which techniques are available given the current ne-waza state. Inputs: (a) the broader position state from the position state machine (`SIDE_CONTROL`, `MOUNTED`, etc.), (b) the active set of `ConnectionEdge` instances from the ne-waza grip graph (per substrate Part 3.3), and (c) whether the active connections match any dominant-position pattern.

A technique passes Stage 1 if either:
- its `fires_from_position` field is present and matches the current dominant-position state, OR
- its `fires_from_position` field is absent (position-agnostic) and its `required_connections` set is satisfied by active ConnectionEdges, OR
- its `parent_position` matches the current broad position state AND its `required_connections` set is satisfied.

**Stage 2 — ranking by struts-nullified state.** Among Stage 1 candidates, rank by how close tori is to commit-readiness. The connection_quality from substrate Part 2 supplies one input. The active defensive struts from substrate Part 4 supply another: a technique whose `applicable_defensive_struts` are mostly active is harder to commit than one whose struts are mostly nullified. Stage 2 produces an effective-difficulty score per candidate, and the resolver selects from the ranked list.

The rule-of-thumb from tachiwaza holds: facts that don't change match-to-match go in the catalog; facts that depend on current state belong to the resolver. The catalog declares which struts apply to each technique; the resolver tracks which struts are currently active and computes effective difficulty.

---

## 2. The katame-waza technique catalog

### 2.1 File location

`data/ne_waza_techniques.yaml`. Parallel to `data/techniques.yaml`; loaded by a separate `NeWazaTechniqueDefinition` dataclass in `src/ne_waza_catalog.py`. The two catalogs are sibling files, not merged.

### 2.2 Schema fields

```yaml
- technique_id: hon_kesa_gatame              # snake_case, unique across ne-waza catalog
  name_japanese: Hon-kesa-gatame
  name_english: Scarf Hold
  family: ne_waza
  subfamily: pin                              # pin | strangle | joint_lock
  kodokan_status: katame_no_kata              # katame_no_kata | shinmeisho | habukareta
  
  parent_position: SIDE_CONTROL_RIGHT         # broad position state — required for position-dependent techniques
  fires_from_position: null                   # dominant position reference — null for non-dominant
  
  required_connections:                       # list of ConnectionEdge requirements
    - type: ANATOMICAL_WRAP
      tori_part: right_arm
      target: uke_neck
      minimum_quality: 0.7
    - type: ANATOMICAL_TRAP
      tori_part: left_armpit
      target: uke_right_arm
      minimum_quality: 0.8
    - type: BODY_PRESSURE
      tori_part: right_hip_and_chest
      target: uke_right_armpit_and_chest
      minimum_quality: 0.6
    - type: POSITIONAL_BASE
      tori_part: head
      target: mat
      minimum_quality: 0.5
    - type: POSITIONAL_BASE
      tori_part: left_leg
      target: mat_extended_rear
      minimum_quality: 0.5
  
  applicable_defensive_struts:                # strut_ids from data/defensive_struts.yaml
    - bridge_and_roll_right
    - bridge_and_roll_over_head
    - arm_extraction
  
  score_mechanism: pin_time_accumulation      # pin_time_accumulation | immediate_submission
                                              # waza-ari laddering and era-variable pin times handled by the rule-set layer, not the catalog
  
  joint_target: null                          # only for joint_lock subfamily
  fulcrum_body_part: null                     # only for joint_lock subfamily
  
  base_difficulty: 30
  pedagogical_prerequisites: []
  minimum_belt_for_competition_use: white
  
  ne_waza_followup_preferences:               # transitions if pin breaks
    - juji_gatame
    - kata_gatame
  
  era_introduced: 1900
  
  notes: |
    Foundational pin. Distinguishes from kata-gatame by the scarf wrap on the neck
    rather than the head-and-arm clasp. The arm trap in left armpit gates uke's
    arm_extraction strut — without it, the pin reduces to a generic side hold.
```

### 2.3 Field-by-field commentary

**`family` is always `ne_waza`** for this catalog. The tachiwaza catalog uses `te_waza`, `koshi_waza`, etc. — the two catalogs don't share family values. Validator should reject any other value.

**`subfamily` is one of three values**: `pin` (osaekomi-waza, time-accumulated), `strangle` (shime-waza, immediate submission via tap or pass-out), `joint_lock` (kansetsu-waza, immediate submission via tap). The three subfamilies have different required-field profiles — see field-presence rules in section 2.4.

**`kodokan_status` parallels the tachiwaza field** but uses a different value set. `katame_no_kata` covers the canonical pins and locks in the formal kata. `shinmeisho` covers newer additions recognized by the Kodokan. `habukareta` is reserved for techniques removed from canonical practice — currently empty for ne-waza but present for schema parity with tachiwaza.

**`parent_position` references the position state machine.** Required for position-dependent techniques. Values match the existing enum: `SIDE_CONTROL_LEFT`, `SIDE_CONTROL_RIGHT`, `MOUNTED`, `NORTH_SOUTH`, `BACK_CONTROL_TOP`, `GUARD_TOP`, `GUARD_BOTTOM`, etc. Mirror-eligibility (e.g., `SIDE_CONTROL_LEFT` vs `SIDE_CONTROL_RIGHT`) is handled the same way as tachiwaza — author one canonical side, engine auto-mirrors.

**`fires_from_position` references the dominant-position catalog.** Non-null only for techniques that fire from a dominant position with terminal-graph behavior. When non-null, the engine treats the technique as one of multiple finishes available from that position, and the dominant-position-graph induced-transition logic applies. When null, the technique is a single-finish terminal at its `parent_position`.

The two fields are not mutually exclusive but typically only one is populated. A technique like sankaku-jime has `fires_from_position: sankaku_position` and `parent_position: null` because the sankaku geometry is what defines availability, not the broader position state. A technique like kesa-gatame has `parent_position: SIDE_CONTROL_RIGHT` and `fires_from_position: null` because side-control is what defines availability and there's no dominant-position graph for it.

**`required_connections` is the Stage 1 gate.** Each entry references a connection type from section 5 and parameterizes it. The `minimum_quality` value supplies the connection-quality threshold per substrate Part 2 — below this quality, the technique cannot commit. Authors record the canonical (right-stance, right-side) configuration; mirror handling matches tachiwaza.

**`applicable_defensive_struts` is the Stage 2 input.** References strut_ids from `data/defensive_struts.yaml`. The order matters in one specific sense: list the *primary* defense first (the one Kodokan teaches as the canonical escape). Validator allows arbitrary length; authors should stay under five entries per technique unless the source material genuinely names more.

**`score_mechanism` determines the resolution loop.** Two values: `pin_time_accumulation` (osaekomi-waza, accumulates against the OsaekomiClock) and `immediate_submission` (shime/kansetsu, fires a tap-check loop). The waza-ari/ippon laddering — 10 seconds to waza-ari, 10 more to ippon if already holding waza-ari, era-variable per pre-2017 rules — lives in the rule-set layer, not in the catalog. The catalog declares only which resolution loop applies; the loop itself handles laddering. No per-technique pin-time field is needed because every osaekomi accumulates against the same shared clock.

**`joint_target` and `fulcrum_body_part` are joint_lock-only.** `joint_target` is one of: `elbow_extension`, `elbow_rotation`, `shoulder_rotation`, `wrist`, `knee`, `ankle`. `fulcrum_body_part` is the X in `ude-hishigi-X-gatame` — for juji-gatame, this is `hips_and_thighs`; for hiza-gatame, `knee`; for waki-gatame, `armpit`; for hara-gatame, `stomach`; for ashi-gatame, `leg`; for te-gatame, `hand`. The naming convention is sourced; the validator can lock it down to an enum once the catalog is authored.

**`ne_waza_followup_preferences` handles transitions on pin break.** Parallel to the tachiwaza field of the same name. When a pin's leg_recapture or bridge_and_roll strut succeeds, the position transitions to a follow-up state — often another pin attempt, sometimes a juji-gatame entry. Authoring this captures the empirical "what comes next" that experienced judoka demonstrate.

### 2.4 Field-presence rules by subfamily

The validator should enforce subfamily-specific field requirements:

**`subfamily: pin`** requires:
- `parent_position` (non-null) OR `fires_from_position` (non-null) — at least one
- `score_mechanism: pin_time_accumulation`
- `joint_target` is null
- `fulcrum_body_part` is null

**`subfamily: strangle`** requires:
- `score_mechanism: immediate_submission`
- `joint_target` is null
- `fulcrum_body_part` is null
- `parent_position` and `fires_from_position` may both be null (position-agnostic)

**`subfamily: joint_lock`** requires:
- `score_mechanism: immediate_submission`
- `joint_target` (non-null, from the enum)
- `fulcrum_body_part` (non-null, snake_case body part)
- `parent_position` and `fires_from_position` may both be null (position-agnostic)

### 2.5 Authoring scope estimate

From Chapter 7 of Kodokan Judo:
- **Pins (osaekomi-waza)**: 7–8 entries — hon-kesa, kuzure-kesa, kata-gatame, kami-shiho, kuzure-kami-shiho, yoko-shiho, kuzure-yoko-shiho, tate-shiho.
- **Strangles (shime-waza)**: ~12 entries — nami-juji-jime, gyaku-juji-jime, kata-juji-jime, hadaka-jime, okuri-eri-jime, kata-ha-jime, katate-jime, ryote-jime, sode-guruma-jime, tsukkomi-jime, sankaku-jime, and 1–2 from earlier in the chapter not captured in current photos.
- **Joint locks (kansetsu-waza)**: ~9 entries — ude-garami, ude-hishigi-juji-gatame, ude-hishigi-ude-gatame, ude-hishigi-hiza-gatame, ude-hishigi-waki-gatame, ude-hishigi-hara-gatame, ude-hishigi-ashi-gatame, ude-hishigi-te-gatame, ude-hishigi-sankaku-gatame.

Total: ~28–29 named techniques. Plus 2–3 dominant positions (section 3) and ~15 defensive struts (section 4). Authoring effort should be roughly comparable to one Gokyo group from tachiwaza — call it 2–3 focused sessions.

---

## 3. The dominant-position catalog

### 3.1 File location

`data/ne_waza_positions.yaml`. New file. Loaded by `NeWazaPositionDefinition` dataclass in `src/ne_waza_catalog.py` alongside the technique loader.

### 3.2 What goes here vs. what stays in the position state machine

The existing position state machine declares broad position states (`SIDE_CONTROL`, `MOUNTED`, `TURTLE_TOP`, `BACK_CONTROL_TOP`, `GUARD_TOP`, `GUARD_BOTTOM`, `NORTH_SOUTH`, `SCRAMBLE`, `NEWAZA_TRANSITION`). These stay where they are — they're engine-level state, not data.

The dominant-position catalog adds a layer *between* the broad state machine and the technique catalog: configurations that satisfy the substrate Part 5 pattern of "single position offering 2+ distinct terminal states with induced transitions between them." A dominant position is a substrate object the engine can ask: *given this active connection set, am I in a recognized dominant position?* If yes, the position's terminal-technique list becomes the candidate menu; if no, fall back to the broad state's catalog techniques.

Most pins are not dominant positions. Kesa-gatame is a single terminal state — uke can defend, but tori isn't choosing between multiple finishes from the same configuration. Sankaku is. Back-control-with-hooks is (Cranford's `BACK_TURTLE_WITH_HOOKS`).

### 3.2.1 Three position categories the engine handles

Worth being explicit because the spec touches all three:

1. **Broad position states** — the existing position state machine enum. SIDE_CONTROL, MOUNTED, GUARD_TOP, GUARD_BOTTOM, NORTH_SOUTH, TURTLE_TOP, BACK_CONTROL_TOP, SCRAMBLE, NEWAZA_TRANSITION. Engine-level state. Not catalog data. Extended only by adding new enum values when the engine needs new states.

2. **Dominant positions with terminal graphs** — this catalog. Configurations offering 2+ named finishes with induced transitions. Sankaku, back-turtle-with-hooks. First-class data with their own file.

3. **Transitional / neutral positions** — engine-level state, no terminal techniques, gate the pin clock or define a sub-loop. The clearest example is **half guard**: when uke's `leg_recapture` strut succeeds against a pin, the position transitions from (e.g.) SIDE_CONTROL_RIGHT → HALF_GUARD_BOTTOM. The OsaekomiClock suspends. Tori then runs a half-guard-pass sub-loop attempting to re-establish a pin position; if too much stalled time passes, the referee module triggers Matte (referee-personality-dependent — see section 4.5).

Half guard does *not* get a dominant-position catalog entry because it has no terminal finishes that fire from it. It's a neutral position en route to or away from pin states. Position state machine adds `HALF_GUARD_TOP` and `HALF_GUARD_BOTTOM` as enum values; OsaekomiClock logic stops accumulation when the state machine is in either; engine handles the rest via existing transition machinery.

Same logic applies to other transitional/neutral states the engine may need: scramble exit configurations, butterfly guard, deep half guard, x-guard, etc. None are dominant positions in the substrate sense; all are engine-level state. The catalog does not enumerate them.

### 3.3 Schema fields

```yaml
- position_id: sankaku_position
  description: |
    Triangle configuration — tori's legs form a closed triangle around uke's
    head-and-arm. The diagonal sankaku geometry per Kodokan Judo p.124.
    Multiple terminal finishes available; tori chooses between them based on
    uke's defensive response.
  
  required_connections:                       # what defines this position
    - type: LIMB_TRIANGLE
      tori_part: legs
      target: uke_head_and_one_arm
      orientation: diagonal
      minimum_quality: 0.6
  
  parent_position: any                        # broad-state context — "any" means position-agnostic
  
  terminal_techniques:                        # technique_ids that fire from this position
    - sankaku_jime
    - ude_hishigi_sankaku_gatame
    - sankaku_gatame                          # Cranford-identified pin; verify in authoring
  
  induced_transitions:                        # per substrate Part 5
    - if_uke_strut_activates: head_extraction
      tori_can_pivot_to: ude_hishigi_sankaku_gatame
      transition_cost: 1                      # ticks
      narrative: |
        Uke fights the choke threat by attempting to slip the head out;
        tori releases the squeeze and attacks the trapped arm instead.
    
    - if_uke_strut_activates: arm_extraction
      tori_can_pivot_to: sankaku_jime
      transition_cost: 1
      narrative: |
        Uke fights the armlock threat by attempting to extract the arm;
        tori releases the elbow pressure and finishes the choke instead.
  
  applicable_defensive_struts:                # struts that defend the position itself
    - head_pivot_out
    - bridge_and_roll_right
    - posture_up_and_base
  
  era_introduced: 1900
  
  notes: |
    The single clearest substrate-vs-state-machine fork in v0.1. Kodokan names
    three terminals with sankaku in the name (jime, gatame-armlock, and the
    pin variant from Cranford). Resolver treats this as one position with
    three commit options, not three independent techniques.
```

### 3.4 Field-by-field commentary

**`required_connections` defines the position.** Same connection-type vocabulary as techniques. If tori's active ConnectionEdge set matches these requirements at the minimum quality thresholds, the engine recognizes the position as established.

**`parent_position` is broader-context.** Most dominant positions are accessible from multiple broad states — sankaku can be entered from guard-bottom (uke comes in to pass and gets caught), from north-south (tori transitions while passing), from back-control. The `any` value indicates position-agnosticism; specific values constrain when the position can be entered.

**`terminal_techniques` is the candidate menu.** Once the position is recognized, these technique_ids become available regardless of their individual `parent_position` fields. The technique catalog entries should reference back via `fires_from_position: sankaku_position` for consistency.

**`induced_transitions` encodes the multi-threat graph.** Per substrate Part 5.3, tori can release pressure on one threat specifically to bait uke's defense, then commit to a different threat. The `if_uke_strut_activates` field references the strut catalog — when that strut becomes active for uke, tori has the option to pivot to a different terminal. The `transition_cost` in ticks captures how quickly tori can re-orient.

**`applicable_defensive_struts` is uke's defense set against the position itself.** Distinct from per-technique defenses — these are the defenses uke runs *before* tori has committed to a specific terminal. Once tori commits, the technique's own `applicable_defensive_struts` take over.

### 3.5 v0.1 scope

Three dominant positions for v0.1, all corpus-confirmed:

- **`sankaku_position`** — Kodokan-named, three terminals, fully specified above.
- **`back_turtle_with_hooks`** — Cranford-identified per substrate Part 5.2. Terminals: okuri-eri-jime, sode-guruma-jime, hadaka-jime (the latter two confirmed by Kodokan as also-from-rear in pp.120, 123). Induced transitions deferred to authoring (the corpus shows them but not which strut triggers which pivot).
- **`head_and_arm_isolated`** — Cranford's name, but the same configuration the Kodokan book names sankaku. Likely fold into `sankaku_position` rather than maintain as separate position. Decision deferred to authoring.

Other dominant positions exist (mounted-with-arm-isolated for juji-gatame setup; ride-the-back with hooks-in-both-sides) but the corpus doesn't supply enough data to specify their terminals and transitions confidently. They become v0.2 work as the corpus grows.

---

## 4. The defensive strut catalog

### 4.1 File location

`data/defensive_struts.yaml`. New file. Loaded by `DefensiveStrutDefinition` dataclass.

### 4.2 Why struts are a separate file

Struts are reusable across many techniques. The same `bridge_and_roll_right` strut defends kesa-gatame, kata-gatame, kami-shiho, yoko-shiho, and tate-shiho with different parameters. Embedding defenses inside technique entries would duplicate strut definitions across the catalog, making it impossible to ask cross-cutting questions like "which techniques does this defense apply to?" or "what's the universal vocabulary of ne-waza defenses?"

The substrate work per Part 4 already treated struts as first-class — this file makes them first-class data.

### 4.3 Schema fields

```yaml
- strut_id: bridge_and_roll_right
  name_descriptive: Bridge-and-roll to tori's right
  name_japanese: null                         # Kodokan doesn't name defenses; mostly null
  
  mechanism_family: rotational_displacement   # see enum below
  defense_phase: post_commit                  # pre_position | pre_commit | post_commit
  
  applicable_against_connection_types:        # which connection types this strut nullifies
    - BODY_PRESSURE
    - ANATOMICAL_WRAP
  
  body_motion: |
    Arch the back to create space between bodies. Push tori upward with hands
    or by grabbing one of tori's legs with the opposite hand. Twist hips to
    the right while inserting knee(s) into the gap, then roll tori over to
    the right side. Direction-mirrored variants exist.
  
  required_uke_attributes:                    # what stats this strut depends on
    - bridge_strength
    - hip_mobility
  
  effectiveness_axis: rotation_clockwise_from_uke_supine
                                              # captures direction-specificity
  
  referee_summons: false                      # does success trigger referee Matte?
  
  era_introduced: 1900
  
  notes: |
    The universal pin-escape primitive. Kodokan teaches direction-specific
    variants per pin (over-the-head for kami-shiho, to-the-left for some
    variations). The strut is parameterized; direction is part of the per-
    technique applicable_defensive_struts reference.
```

### 4.4 Field-by-field commentary

**`mechanism_family` groups struts by underlying motion.** Enum:
- `rotational_displacement` — bridge-and-roll family. Uke uses bridge-power to rotate tori off.
- `linear_extraction` — frame-and-shrimp family. Uke creates space, slides body out laterally.
- `limb_recapture` — leg-recapture, arm-extraction. Uke gets a controlling limb back.
- `pre_grip_seizure` — wrist-pre-grip, grip-strip-to-loose. Uke disrupts before tori commits.
- `joint_protection` — elbow-bend-and-clasp, elbow-rotate-and-bend. Uke defeats lock geometry.
- `postural_denial` — preemptive-face-turn, posture-up-and-base, stand-up. Uke refuses the position.
- `counter_attack` — armlock-counter. Uke attacks tori's exposed limb.

The mechanism family is what generalizes struts across techniques. Bridge-and-roll on a pin and elbow-push-and-roll on a choke share the rotational_displacement family, applied against different connection types.

**`defense_phase` is when the strut fires.** Per the timeline finding from section 9 of the substrate-extension corpus:
- `pre_position` — fires during position transition; refuses the position entirely. Examples: preemptive-face-turn, stand-up-from-ude-garami.
- `pre_commit` — fires during the connection-quality tuning phase from substrate Part 2; disrupts tori's setup before commit. Examples: wrist-pre-grip, grip-strip-to-loose, elbow-push-during-choke-setup.
- `post_commit` — fires after the technique is committed; escapes the locked-on position. Examples: bridge-and-roll, leg-recapture, sleeve-pull-and-slip.

The phase determines which window the strut consumes. Pre-position struts run during transition states; pre-commit struts run during the tuning loop; post-commit struts run after commit declaration.

**`applicable_against_connection_types` is the filter.** When a strut is candidate-active for uke, the engine checks whether tori's active ConnectionEdges include any of the listed types. If yes, the strut can engage. This is how the same bridge-and-roll handles both pin and post-commit choke escape — both involve a BODY_PRESSURE or ANATOMICAL_WRAP connection it can rotate against.

**`required_uke_attributes` references judoka substrate stats.** The strut catalog declares which attributes the strut depends on; the resolver consumes uke's actual stat values to compute strut effectiveness. This parallels tachiwaza's `attribute_sensitivities` deferred field — but for struts, it's load-bearing from v0.1 because escape probability is the central ne-waza mechanic per substrate Part 4.4.

**`effectiveness_axis` captures direction-specificity.** Bridge-and-roll-to-the-right is mechanically different from bridge-and-roll-over-the-head — same family, different axis. The axis field lets the per-technique `applicable_defensive_struts` reference the right variant. Some struts have a single axis (sleeve-pull-and-slip is always rearward); others are parameterizable (bridge-and-roll has at least three named directions).

**`referee_summons` is a hint to the referee module, not a deterministic trigger.** When `true`, the strut declares that its activation *has the potential* to trigger a Matte under the right conditions — typically because it transitions the position to a stalled or neutral state, or because uke's defensive scramble may inadvertently put tori in an illegal configuration (e.g., do-jime trunk-lock in shiai, finger-locking in kansetsu, or — in tachiwaza — a leg-grab pre-2010-IJF rules). The actual call is made by the referee module, which consumes the flag plus referee-personality stats (strict / neutral / generous) plus rule-set context to decide whether to call Matte and how quickly.

Concretely: when uke's `leg_recapture` strut transitions a pin to half-guard, the flag fires *that* a summons is potentially warranted, but no immediate Matte — there's still active engagement. If tori sits in half guard without progressing toward a re-pass, the referee personality determines the stall threshold: strict referee at 8–10 seconds, neutral at 15–20, generous at 25–30. Same architecture handles stalled turtle, no-engagement-on-the-ground, etc. v0.1 defaults `referee_summons: false` for all struts; specific cases get flagged during authoring as the referee-personality system specifies its consumption logic.

### 4.5 v0.1 strut catalog

The fifteen primitives surfaced by corpus analysis:

| strut_id | mechanism_family | defense_phase | typical targets |
|---|---|---|---|
| `bridge_and_roll_right` | rotational_displacement | post_commit | pins with right-side BODY_PRESSURE |
| `bridge_and_roll_left` | rotational_displacement | post_commit | pins with left-side BODY_PRESSURE |
| `bridge_and_roll_over_head` | rotational_displacement | post_commit | kami-shiho family |
| `frame_and_shrimp` | linear_extraction | post_commit | upper-body pins, mount |
| `leg_recapture` | limb_recapture | post_commit | side-control, mount — restores guard |
| `arm_extraction` | limb_recapture | post_commit | kesa, kata-gatame, kuzure variants |
| `preemptive_face_turn` | postural_denial | pre_position | refuses yoko-shiho, kata-gatame entry |
| `armlock_counter` | counter_attack | post_commit | yoko-shiho variant (Kodokan-named) |
| `sleeve_pull_and_slip` | rotational_displacement | post_commit | rear chokes (hadaka, okuri-eri) |
| `elbow_push_and_roll` | rotational_displacement | post_commit | front chokes (nami-juji, gyaku-juji, kata-juji) |
| `grip_strip_to_loose` | pre_grip_seizure | pre_commit | front chokes during setup |
| `wrist_pre_grip` | pre_grip_seizure | pre_commit | hyperextension locks (juji-gatame family) |
| `elbow_bend_and_clasp` | joint_protection | post_commit | juji-gatame, ude-gatame |
| `elbow_rotate_and_bend` | joint_protection | post_commit | straightening locks |
| `posture_up_and_base` | postural_denial | pre_position | rear attacks (kata-ha-jime) |
| `head_pivot_out` | postural_denial | post_commit | sankaku, kata-gatame, kami-shiho |
| `stand_up_from_lock` | postural_denial | pre_position | low-position locks (ude-garami v1) |

Seventeen entries actually, after enumerating directional variants of bridge-and-roll. Authoring may consolidate or split; the schema supports either.

---

## 5. Ne-waza connection types

The ne-waza ConnectionEdge taxonomy from substrate Part 3 forks from tachiwaza. v0.1 declares twelve types organized into two contexts:

### 5.1 Pin context (osaekomi)

| Type | Definition | Mechanical attribute |
|---|---|---|
| `BODY_PRESSURE` | Distributed contact between tori's body surface and uke's body | Contact-area-dependent; weight-distribution-dependent; not a grip |
| `GARMENT_GRIP_NEWAZA` | Hand grip on uke's gi, ground-context | Same as tachiwaza GARMENT_GRIP but with ground-specific target vocabulary |
| `ANATOMICAL_TRAP` | Limb (uke's) caught in tori's body geometry (armpit, between thighs) | Trap-strength-dependent; resists extraction proportional to surrounding pressure |
| `POSITIONAL_BASE` | Tori's body part anchored to the mat for stability | Stability anchor, not a grip; required for posture maintenance |
| `ANATOMICAL_WRAP` | Tori's arm or leg wraps a uke body part (neck, body) | Connective; wrap-completion gates technique |

### 5.2 Submission context (shime / kansetsu)

| Type | Definition | Mechanical attribute |
|---|---|---|
| `LAPEL_CROSS` | Two hands gripping opposing lapels with arms crossed | `cross_orientation: regular | reverse`; wringing-action mechanical |
| `FOREARM_BAR` | Tori's forearm pressed against uke's throat or carotid | Leverage-via-limb, not garment; pressure quality depends on bone-against-soft-tissue contact |
| `LIMB_TRIANGLE` | Tori's legs forming a closed triangle around uke body part | `orientation: diagonal | direct`; closing-the-loop gates submission |
| `LIMB_ISOLATION` | Uke's limb separated from uke's body, controlled by tori | Isolation completeness gates lock; uke's hand-clasp counter-attack on this |
| `WRIST_GRIP` | Tori's hand on uke's wrist as load-input to a lever | `rotational_lock_axis: extension | rotation | flexion` |
| `THREADED_VOID` | Limb passes through uke's defensive grip without breaking it (substrate v0.1) | Uses uke's own grip as pathway; ceases when uke releases |
| `SELF_ANCHOR` | Tori grips own gi to close a mechanical loop (substrate v0.1) | Self-anchored; immune to grip-strip; loop-completion gates technique |

### 5.3 Cross-cutting attributes

Every ConnectionEdge regardless of type has the substrate-v0.1 fields:
- `type` (one of the twelve)
- `target` (where on uke or tori the connection lives)
- `quality` (0.0–1.0)
- `setup_ticks_remaining` (0 once fully established)
- `mechanical_attributes` (type-specific dict)

### 5.4 What's deferred

The substrate v0.1 base types `LEG_CLAMP`, `FAR_SIDE_REACH` are retained from the Cranford corpus but don't surface in the Kodokan pin/choke/lock material. They're real connection types for dynamic ground (turtle attacks, scrambles) and will populate as the substrate grows. v0.1 of the catalog doesn't reference them; v0.2 will.

`THREADED_TWIST` from substrate v0.1 — Cranford derived it from belt-and-lapel-loop chokes that the Kodokan section doesn't cover. Retained in the connection-type vocabulary; not used in v0.1 authoring.

---

## 6. Substrate mechanical-class enum (catalog reference)

Per the kansetsu authoring, joint locks have a mechanical lever class that affects effective difficulty and defense applicability. The enum (sourced from Sacripanti / biomechanics doc Section 4):

- `lever_extension` — straightening lock (juji-gatame, ude-gatame, hiza-gatame). Defended by elbow-bend-and-clasp.
- `lever_rotation` — twisting lock (ude-garami, te-gatame variant). Defended by elbow-rotate-and-bend.
- `lever_compression` — squeezing lock (sankaku-gatame applied as armlock). Defended by limb-extraction.
- `couple_choke` — bilateral pressure on carotids (juji-jime family, sankaku-jime, ryote-jime). Defended by elbow-push-and-roll, grip-strip.
- `lever_choke` — unilateral pressure with bone-on-soft-tissue (hadaka-jime, sode-guruma-jime). Defended by sleeve-pull-and-slip.
- `couple_pin` — bilateral body weight distributing on uke (kami-shiho, tate-shiho). Defended by frame-and-shrimp, leg-recapture.
- `lever_pin` — asymmetric weight with a moment arm (kesa-gatame, kata-gatame, yoko-shiho). Defended by bridge-and-roll.

The catalog's per-technique `mechanical_class` field uses this enum. Validator locks it down once the enum is finalized.

---

## 7. Naming overlay

Parallel to tachiwaza. Each ne-waza technique has:
- `technique_id` — internal snake_case
- `name_japanese` — formal name (Hon-kesa-gatame)
- `name_english` — Kodokan-English (Scarf Hold)

Plus the same naming overlay scheme: judoka may know `hon_kesa_gatame` colloquially as "the scarf hold" or "kesa" depending on dojo culture and belt level. The naming-overlay system from tachiwaza applies unchanged — sensei vocabulary, regional variants, formal-vs-casual rendering. No new schema needed.

---

## 8. Belt threshold logic for ne-waza

Ne-waza belt requirements merge into the HAJ-210 tachiwaza ladder rather than maintaining a parallel ladder. Single judoka, single belt, single curriculum — a green belt should know foundational pins and submissions the same way they know foundational throws. The HAJ-210 ladder gets a `minimum_belt_for_competition_use` field on ne-waza entries the same as tachiwaza entries; the curriculum logic merges them when computing what each sensei teaches at each belt.

### 8.1 Catalog field vs. procgen judoka knowledge

The `minimum_belt_for_competition_use` field declares the *judo-curriculum-track* minimum — the canonical "at this belt, this technique is taught in the standard ladder." It is **not** a biographical claim about every individual judoka.

Procgen judoka can enter the simulation with prior-art knowledge from BJJ, sambo, wrestling, or other grappling traditions where the ne-waza vocabulary is learned at different stages. A BJJ blue belt converting to judo may have full juji-gatame and rear-naked-choke proficiency at judo white belt; a wrestler converting may have advanced pin proficiency but no submission knowledge. The procgen layer overrides the curriculum default with prior-art knowledge during judoka instantiation. Same architecture as tachiwaza — the field is curriculum data, not biography data.

### 8.2 White-belt ne-waza minimum (judo curriculum track)

Sourced from actual Cranford JKC instructional practice:

- `hon_kesa_gatame` — foundational pin
- `yoko_shiho_gatame` — foundational side-pin
- `kami_shiho_gatame` — north-south pin (Comrade's note: kita-shiho in colloquial usage)
- `ude_hishigi_juji_gatame` — foundational armlock

Notably **not** in the white-belt minimum: rear chokes (hadaka-jime, okuri-eri-jime, kata-ha-jime). Chokes appear later in the curriculum — likely yellow or orange belt. This matches the actual Cranford progression and is more conservative than the spec's earlier draft. Authoring fills in the full ladder.

---

## 9. Open questions — authoring will resolve

Documented now so they don't surprise the authoring session:

**9.1 Pin time variance handled entirely by rule-set layer.** Current IJF: 20 seconds for ippon, 10 for waza-ari, 10 more for ippon if already holding waza-ari. Pre-2017: 25/20/15 for ippon/waza-ari/yuko. None of this is per-technique data — every osaekomi accumulates against the same shared OsaekomiClock with the same ladder. The catalog declares only `score_mechanism: pin_time_accumulation`; the rule-set layer (HAJ-214's companion `data/rule_set_changes.yaml`) owns era-variable thresholds and the waza-ari ladder logic. Schema needs no per-technique pin-time field; earlier drafts of this spec had one and it was redundant.

**9.2 Tap resistance curves.** Submission techniques resolve via tap-or-pass-out per the substrate, but the current spec doesn't parameterize how long uke holds out. A `tap_resistance_curve` field (deferred to v0.2) would encode this per-technique — choke timings differ from joint-lock timings; arm-bar tap is faster than choke pass-out. v0.1 uses an engine-level default; v0.2 makes it per-technique.

**9.3 Variant consolidation.** Kuzure-variants (kuzure-kesa, kuzure-kami-shiho, kuzure-yoko-shiho) are authored as separate technique_ids per the tachiwaza precedent. But ude-hishigi-X-gatame is *eight* variants of a single mechanical pattern (armlock via X body part as fulcrum). Two options: (a) eight separate entries, parallel to the Kuzure approach; (b) one ude-hishigi-gatame entry with an embedded `fulcrum_variants` list. Recommendation: (a), consistent with Kodokan naming. Each variant has different connection-set requirements and applicable defensive struts, so they're not the same technique.

**9.4 Sankaku vs head-and-arm-isolated reconciliation.** Cranford v0.1's `HEAD_AND_ARM_ISOLATED` and Kodokan's `sankaku_position` describe the same configuration with different vocabulary. v0.1 spec collapses them into `sankaku_position` (Kodokan name wins, since it's the sourced canonical name). Substrate v0.2 documentation should update `ne-waza-substrate.md` Part 5 to use `sankaku_position` for consistency.

**9.5 Submission-context connection-type completeness.** `LIMB_ISOLATION`, `WRIST_GRIP`, `LAPEL_CROSS`, `FOREARM_BAR`, `LIMB_TRIANGLE` were extracted from the photographed corpus. The kansetsu section in particular surfaces several locks (waki-gatame, hara-gatame) that may need new types or attributes. Authoring will surface gaps; treat new types the way HAJ-213 was treated mid-tachiwaza-authoring.

**9.6 Defensive strut parameterization vs splitting.** Bridge-and-roll has at least three directional variants (right, left, over-head). v0.1 lists them as separate strut_ids. An alternative is one `bridge_and_roll` strut with a `direction` parameter on the per-technique reference. Recommendation: keep them split for v0.1, since the directional variants have different effectiveness against different pins and authoring is easier with concrete IDs. Consolidate to parameters later if the catalog gets unwieldy.

**9.7 Cranford-only struts not in the Kodokan corpus.** Substrate v0.1 Part 4.3 mentions struts the six-video corpus surfaced (e.g., the granby roll, specific scramble defenses) that don't appear in the Kano-Kodokan instructional material. These belong in the strut catalog as v0.2 additions when an uke-perspective or competition-pace corpus is added. v0.1 sticks to Kodokan-sourced struts.

**9.8 Naming the unnamed struts.** Kodokan describes defenses in prose without naming them ("Arch your back and push your opponent upward"). This spec coins names (bridge_and_roll_right, etc.). The names become substrate vocabulary; they should be reviewed during authoring to make sure they're memorable and not misleading. If a name is bad, change it during authoring — the strut catalog is small enough that renaming is cheap.

---

## 10. Loader and validator scope

For the HAJ-212-successor implementation ticket:

**Loader (`src/ne_waza_catalog.py`):**
- `NeWazaTechniqueDefinition` dataclass mirroring section 2.2 fields
- `NeWazaPositionDefinition` dataclass mirroring section 3.3 fields
- `DefensiveStrutDefinition` dataclass mirroring section 4.3 fields
- `load_ne_waza_catalog(techniques_path, positions_path, struts_path)` returns three dicts keyed by id
- Cross-reference resolution: technique → strut, technique → position, position → technique resolved at load time; raises on dangling reference

**Validator (`src/ne_waza_catalog_validator.py`):**
- Subfamily field-presence rules per section 2.4
- Enum locks: `subfamily`, `kodokan_status`, `score_mechanism`, `joint_target`, `mechanical_class`, `mechanism_family`, `defense_phase`
- Cross-reference integrity (struts referenced by techniques exist; positions referenced by techniques exist; terminals listed in positions exist as techniques)
- Required-connection minimum-quality bounds (0.0–1.0)
- Symmetry check: if a technique has `fires_from_position` set, the referenced position's `terminal_techniques` should include the technique_id
- Pre-commit hook integration parallel to HAJ-211's tachiwaza validator

**CI integration:** Same GitHub Actions workflow that validates the tachiwaza catalog should be extended to validate the ne-waza catalogs on push/PR.

---

## 11. Relationship to substrate documents

This spec sits *on top of* `ne-waza-substrate.md` v0.1, not parallel to it. The substrate document specifies the engine-level mechanics (connection_quality continuous variable, DefensiveStrut as runtime object, DominantPositionGraph behavior). This spec specifies the catalog-data format that feeds those mechanics.

The two documents should be read together. Substrate v0.1 answers "what does the engine do with this data at runtime"; this spec answers "what data does the engine consume." Substrate v0.2 (deferred) will extend the engine; corresponding catalog schema extensions land here.

The biomechanics doc (`Judo_Biomechanics_for_Simulation__Kuzushi__Couples__and_Levers.md`) supplies the mechanical-class vocabulary in section 6. As the biomechanics doc evolves, the enum may grow; coordinate updates across all three documents.

---

## 12. Authoring approach

When HAJ-205 ne-waza authoring begins, the recommended order is:

1. **Defensive strut catalog first.** Fifteen-ish entries, small, names everything else references.
2. **Connection-type vocabulary review.** Verify the twelve types are correctly enumerated; add any surfaced by the first few technique authorings.
3. **Dominant positions** — the 2–3 v0.1 entries.
4. **Single-finish pins** (kesa, kata, kami-shiho family, yoko-shiho, tate-shiho) — these use the most stable schema.
5. **Position-agnostic submissions** (juji-jime family, hadaka, okuri-eri, kata-ha) — exercise the optional-parent-position field.
6. **Joint locks** (ude-garami plus the eight ude-hishigi-X-gatame entries) — exercise the joint-target + fulcrum-body-part fields and the mechanical_class enum.
7. **Sankaku-cluster terminals** (sankaku-jime, ude-hishigi-sankaku-gatame, sankaku-gatame pin) — exercise the fires_from_position + dominant-position machinery.

If the schema flexes through (1)–(7) without surfacing structural gaps, the spec is healthy. If a structural gap surfaces (the way HAJ-213 surfaced during tachiwaza authoring), file a revision ticket and continue — that's the precedent. Don't author against a known-broken schema.

---

*End of v0.1 spec.*
