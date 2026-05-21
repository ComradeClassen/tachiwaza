# Technique Vocabulary System

**Status:** Draft v1.2 — 2026-05-17
**Scope:** Supersedes the v2 worldgen spec's treatment of "signature strength" as a base resolver dimension. Establishes the full per-judoka technique vocabulary substrate.
**Related:** `ring-2-worldgen-spec-v2.md`, `physics-substrate.md`, `grip-as-cause.md`, `Judo_Biomechanics_for_Simulation__Kuzushi__Couples__and_Levers.md`, `ne-waza-substrate.md`

---

## Section 1 — Reframe

In the v2 worldgen spec (`ring-2-worldgen-spec-v2.md`, Part II), signature strength is named as one of the five resolver dimensions alongside tachiwaza, ne-waza, conditioning, and fight IQ. It was specified as a scalar — a single number on a 0–100 range per judoka, comparable to the other four.

This document supersedes that. Signature strength is not a base stat. It is a *derived signal* computed off a richer underlying substrate: the **technique vocabulary system**, which models per-judoka technique knowledge as a set of named techniques each carrying proficiency tier, usage ledger, acquisition provenance, and disuse history.

The other four resolver dimensions (tachiwaza, ne-waza, conditioning, fight IQ) remain base stats. Signature strength alone is replaced by this subsystem and computed downstream of it.

**Why this is load-bearing for game identity.** Judoka in Hajime are not statistically distinguishable scalars in five dimensions. They are practitioners with vocabularies, lineages, defensive specialties, and signature techniques whose individual histories the chronicle records. "The legends are the game" requires that signature work be more than a number — it requires that signature work be *legible*. A judoka must be readable as "the Cranford uchi-mata specialist" or "the Newark sumi-otoshi counter-puncher" — not as "judoka with signature_strength: 73." The vocabulary system is how that readability emerges.

**Engine implications.** This reframe is also load-bearing for the Ring 1 match engine. The vocabulary system implies a two-stage technique resolution model:

- **Stage 1 (availability):** The current grip configuration determines which techniques are available. Each technique in the catalog declares one or more `canonical_grip_signatures` — each signature has positive constraints (grips that must be present) and negative constraints (opponent grips that must be absent). A technique is available iff *at least one* signature is satisfied by the current grip graph (accounting for `mirror_eligible` and the judoka's stance).
- **Stage 2 (selection):** When kuzushi fires, one technique is selected from the available set based on the kuzushi vector being in the technique's `admissible_kuzushi_vectors`, the judoka's proficiency, fight IQ, conditioning, and a stochastic component. Scoring quality is influenced by whether the kuzushi vector is also in the technique's `primary_kuzushi_vectors`.

Grip configuration *gates the menu*. Kuzushi *selects the order from the menu*. Both stages are necessary; neither alone is sufficient.

The result is a match rhythm in which most ticks are grip exchange, kuzushi windows are rare, and throw attempts are rarer still. Ippons are punctuation events that the entire prior grip battle earned. This is the design target.

**What this changes downstream.** The Ring 1 calibration ladder gains a dependency: the existing match engine consults grip presence and kuzushi events through priority-laddered action selection logic. Under this model, that logic consults the catalog instead — per-technique availability filters and per-technique kinetic preconditions. The engine's foundational structures (grip graph, kuzushi events, action selector) remain; the data they consult and the gating logic change. This becomes a Ring 1 ticket downstream of catalog skeleton existing.

The HAJ-199 throw-gating bug filed 2026-05-11 is partially obsoleted by this model: throw suppression under opponent dominance becomes emergent from Stage 1 availability rather than a separate predicate. The bug ticket's note about "may dissolve into the grip-as-cause refactor" is now more specifically true — it dissolves into the Stage 1 availability filter, which is what the refactor will install.

---

## Section 2 — The Technique Catalog

The technique catalog is the authoritative list of named techniques in the game. It is a data file (not magic strings scattered through code) consulted by: the match engine's two-stage resolution model, the dojo coaching surface, the legends prose template system, the seminar mechanic, the player UI, and the chronicle entry generators.

Each entry in the catalog is a `TechniqueDefinition` with the following schema:

### Identity fields

- `technique_id` — stable string identifier (e.g., `uchi_mata`). Used as foreign key throughout the system.
- `name_japanese` — canonical Japanese name (e.g., "Uchi-mata").
- `name_english` — descriptive English name (e.g., "Inner Thigh Throw"). Used where Japanese isn't appropriate to the surface.

### Classification fields

- `family` — one of `te_waza` (hand), `koshi_waza` (hip), `ashi_waza` (foot/leg), `sutemi_waza` (sacrifice), `ne_waza` (ground). Drives UI grouping and curriculum organization.
- `subfamily` — finer-grained classification within family (e.g., `forward_throw`, `rear_throw`, `side_throw`, `pin`, `strangle`, `joint_lock`).
- `kodokan_status` — whether the technique appears in the official Kodokan 67-throw catalog, and if so which list (Gokyo no Waza, Shinmeisho no Waza, Habukareta Waza). Drives historical/era filtering: in 1960, Habukareta Waza techniques are technically forbidden in competition; some games-eras matter. Most techniques live here; a few "named regional variants" do not.

### Stage 1 fields — grip availability

- `canonical_grip_signatures` — a list of structured configuration constraints. A technique is available at Stage 1 if *any one* signature in the list is satisfied by the current grip graph. Most techniques have a single-entry list; multi-entry lists express genuinely distinct grip variants of the same technique (e.g., classic seoi-nage vs. one-handed seoi-nage — different grip configurations, same throw). Each entry has three parts:
  - `tori_required_grips` — list of grip specifications the executing judoka *must* hold. Each spec names a hand (tori_left | tori_right), a target region (uke_lapel_high | uke_lapel_low | uke_sleeve_upper | uke_sleeve_lower | uke_back | uke_belt | uke_leg_outer | uke_leg_inner | uke_heel), and a minimum depth (shallow | controlled | deep). The three `uke_leg_*` / `uke_heel` regions describe hand-on-limb contact for Shinmeisho leg-grab throws (morote-gari, kuchiki-taoshi, kibisu-gaeshi); `minimum_depth` is less semantically loaded for these — author as `controlled` unless there's a specific reason. Throws relying on these regions are also candidates for the `rule_set_restrictions` field (deferred — see catalog-authoring-notes) since the IJF 2010 leg-grab ban applies.
  - `uke_disqualifying_grips` — list of grip specifications that, if held by the opponent, *block* this signature from satisfaction. Often expressed as "opponent must not have controlled-or-deep grip on tori's throwing-side sleeve" or similar. May be empty.
  - `mirror_eligible` (boolean, default `true`) — declares that the engine should automatically test this signature's mirror image at Stage 1 against opposite-stance judoka. Set to `false` only for techniques that genuinely do not mirror. Authors do **not** write mirror variants explicitly — the catalog records one canonical configuration (by convention, right-stance) and the engine handles the lefty mirror via the judoka's stance attribute. This keeps the catalog compact and avoids the maintenance burden of duplicate mirror entries.

The Stage 1 availability filter takes the current grip graph and returns the set of techniques whose `canonical_grip_signatures` contain at least one satisfied signature (accounting for `mirror_eligible` and judoka stance). This is consulted every tick during action selection; performance matters at scale (Ring 2 resolver runs thousands of matches per simulated year).

### Stage 2 fields — kinetic preconditions

- `admissible_kuzushi_vectors` — the directions of opponent balance-break in which the technique *can* fire, in body-frame coordinates (e.g., `forward_right_diagonal`, `direct_rear`, `forward_pure`). Stage 2 selection consults this field: when kuzushi fires in direction D, a technique is eligible iff D is in its admissible list. The special token `any` is a wildcard meaning all directions — used for omnidirectional techniques like foot sweeps that admit kuzushi in whatever direction matches uke's step.
- `primary_kuzushi_vectors` (optional) — subset of `admissible_kuzushi_vectors` that represents the technique's *scoring* directions, used by the landing-quality roll and by prose surfaces ("M. Okada's forward-throw repertoire"). If omitted, defaults to equal `admissible_kuzushi_vectors`. For uchi-mata, primary equals admissible. For deashi-harai, admissible is `any` but primary is `[forward_right_diagonal, forward_left_diagonal]` — sweeping forward scores cleanest, even though the sweep can fire in any direction.
- `couple_type` — the biomechanical couple the technique exploits, from the physics substrate vocabulary (e.g., `forward_rotation_about_hip_axis`, `reverse_rotation_about_shoulder_axis`). Tied to the existing `Judo_Biomechanics_for_Simulation` framework.
- `posture_requirements` — opponent postural state that enables the technique (`upright_or_forward_compromised`, `bent_forward`, `extended_backward`, `any`). Often correlated with kuzushi vector but encoded separately for cases where they decouple.

### Schema-revision rationale (v1.2)

The v1.1 schema treated `canonical_grip_signature` and `kuzushi_vector` as single-configuration fields. Catalog authoring against Kodokan Judo (HAJ-205) immediately hit two cases the v1.1 shape couldn't represent cleanly:

1. **Multi-configuration grip variants.** Some techniques (seoi-nage classic vs. one-handed, etc.) admit genuinely distinct grip configurations that are not mirrors of each other. The v1.1 shape forced a single canonical, misrepresenting the technique.
2. **Lefty/righty mirroring.** Almost all judo techniques mirror, but the v1.1 shape conflated "the canonical right-stance grip" with "the only grip." Authoring mirror duplicates would double the catalog and risk drift.
3. **Omnidirectional and admissible-vs-primary distinction.** The v1.1 `kuzushi_vector` was being authored as the *primary scoring* direction, but Stage 2 selection actually wants the *admissible* set. Foot sweeps in particular admit kuzushi in any direction matching uke's step.

The v1.2 decisions:

- **Grip: list-of-signatures, not per-grip alternation.** Per-grip `target_region: [a, b]` alternation fails because alternations across grips are coupled (tori_left=sleeve goes with tori_right=lapel, not tori_right=sleeve). List-of-signatures captures coupled alternation naturally and treats each variant as a complete configuration.
- **Mirroring is engine-handled, not catalog-authored.** `mirror_eligible: true` (default) declares that the engine should auto-mirror at Stage 1 filter time based on judoka stance. The judoka stance attribute lives in the judoka substrate, not in the catalog. This keeps the catalog the size of "variants that actually differ" rather than 2× that.
- **Kuzushi semantics split: admissible (required) + primary (optional).** Admissible drives Stage 2 selection; primary drives scoring and prose. Defaulting primary to admissible keeps the common case ergonomic.
- **`any` wildcard for admissible kuzushi.** Foot sweeps and similarly omnidirectional techniques get to declare their nature compactly rather than listing all nine directions.

### Difficulty and pedagogical fields

- `base_difficulty` — a 0–100 value representing how hard the technique is to execute even with ideal conditions. Used by the resolver as a multiplier on proficiency. Uchi-mata might be 70 (hard to do well even when set up); osoto-otoshi might be 30 (forgiving).
- `pedagogical_prerequisites` — list of `technique_id` values that a sensei is expected to teach *before* this technique. Not enforced — a sensei *can* teach uchi-mata to a white belt, it's just unusual. Used by the dojo curriculum UI and by the sensei's vocabulary-teaching logic.
- `minimum_belt_for_competition_use` — informal rank threshold at which judoka typically deploy this technique in competition. Lower belts may know it but rarely attempt it. Soft signal for resolver weighting, not a hard gate.
- `gokyo_kyo` (optional, integer 1–5) — for techniques in Gokyo no Waza, which of the five kyo groups the technique belongs to (dai-ikkyo, dai-nikyo, …, dai-gokyo). Source-book ordering preserved here so curriculum logic (sensei AI teaches dai-ikkyo before dai-nikyo) and in-game lore surfaces (the "read the book" view of a throw) can consume it without re-deriving from external lookups. Only meaningful when `kodokan_status == gokyo_no_waza`.

### Ne-waza linkage fields

- `failed_throw_consequence` — what happens if the throw fails or is countered. Drives the post-throw branch — and crucially, drives *scoring against tori* on high-stakes failures. The resolver must distinguish neutral failures from failures that hand uke an immediate scoring opportunity. Options:
  - `tori_falls_to_back` — **high-stakes failure.** Tori has overcommitted and lands prone. Uke is in immediate scoring position: this is a common waza-ari-against-tori outcome, and ippon-against-tori is possible if uke converts cleanly (e.g., follows up with a pin or completes the toppling motion). The resolver should *not* treat this as "throw didn't work, neutral reset" — it's "uke gets a free shot at scoring." Throws with this consequence (kosoto-gake, the small reaps when miscommitted, hane-goshi when shrugged off) are high-risk-high-reward by their nature.
  - `tori_to_knees` — **low-stakes failure.** Tori drops to knees but stays facing uke. Engagement resets to neutral, or to a low-stakes ne-waza entry from a kneeling base. No score against tori. Typical of seoi-nage and similar forward-spin throws where tori's commitment doesn't carry them past uke.
  - `uke_lands_stomach` — **ne-waza opportunity for tori.** Uke ends up face-down (turtle / prone). No score for either side, but tori has access to ne-waza attacks against a turtled opponent. Typical of throws where uke's defense involves giving up the throw but presenting a hard-to-attack defensive shape.
  - `tori_thrown` — **catastrophic failure.** Uke has executed a counter-throw against tori. Score against tori is the *expected* outcome — waza-ari if the counter is shallow, ippon if it's clean. Reserved for throws whose committed motion is specifically exploitable by a named counter (e.g. uchi-mata sukashi against uchi-mata, te-guruma against poorly-loaded harai).
  - Field can be omitted entirely when the failure mode is genuinely undefined or unremarkable — but for throws where failure has stakes, populate this honestly. Authoring it as `[]` or empty is wrong; the field is an optional single value, not a list.
- `ne_waza_followup_preferences` — list of `technique_id` values (ne-waza techniques) that naturally chain from this technique's failure or partial success. Authoring data, used by the ne-waza substrate.

### Era fields

- `era_introduced` — earliest year the technique is part of standard competition vocabulary.
- `era_restricted` — year (if any) the technique becomes illegal or restricted in competition.

### Naming overlay subsystem

The catalog provides canonical names (Japanese and English). The naming overlay layer provides *dojo-local* alternative names that emerge from play.

A `TechniqueNamingOverlay` entry has:

- `dojo_id` — the dojo that owns this naming
- `technique_id` — the canonical technique being renamed
- `custom_name` — the player-authored or simulation-generated name
- `named_by` — judoka or sensei who introduced the name (entity reference)
- `year_named` — when it was named
- `triggering_event` — what earned the right to name it (e.g., "first mastery", "first legendary use in competition", "lineage inheritance from parent dojo")
- `parent_overlay` — if this naming was inherited from a parent dojo's lineage, reference to that overlay

**How naming is earned.** When a judoka in the player's dojo reaches `master` proficiency on a technique, the player is offered a naming option:

- Dojo-named: `"<dojo_name>'s <technique_japanese>"` (e.g., "Cranford's uchi-mata")
- Sensei-named: `"<sensei_surname>'s <technique_japanese>"`
- Hybrid template: combinations of the above
- Free-text: arbitrary player-authored string (mild content filtering with length cap and blocklist, otherwise free)

Naming is optional. A player who skips it leaves the technique using the canonical name in their dojo's chronicle and UI.

**How naming propagates.** When a sensei teaches a renamed technique to a student, the renaming travels with the teaching. The student's own dojo (if they later open one) inherits a `parent_overlay` reference and uses the parent name until they earn the right to rename it themselves (their own mastery). Seminars also propagate naming — attendees of a seminar on "the Dynamite Blast" learn it as "the Dynamite Blast" and refer to it that way in their dojo's chronicle if they reach a propagation threshold.

**How prose surfaces consume the overlay.** Chronicle prose, sensei dialogue, coaching surface UI, and player-facing technique displays consult the overlay first (scoped to the relevant dojo) and fall back to canonical names when no overlay exists. The match engine and resolver use canonical IDs only — naming is purely a prose layer.

**Why this matters for game identity.** Player-authored technique names are the most direct form of player narrative in the simulation. A player who has earned "the Dynamite Blast" by drilling uchi-mata for in-game decades will refer to that throw by that name in their screenshots, their forum posts, their chronicle exports. The simulation produces the conditions; the player produces the legend. This is one of the most direct expressions of the "the legends are the game" tagline.

### Catalog scope for 1.0

The catalog ships with approximately 40–60 techniques in 1.0, authored against Kodokan Judo (Jigoro Kano) for canonical classification and Judo Unleashed! (Neil Ohlenkamp) for modern competition-relevant detail. Popularity-weighted: the most commonly seen techniques in modern competition are authored first, with the long-tail Kodokan techniques and Habukareta Waza added incrementally.

The naming overlay starts empty — no pre-authored regional or lineage names. The Cranford anchor dojo, in the seed world fixture, may have a few pre-applied overlays representing its existing senseis' mastered techniques, but these are seeded as if they had been earned through play, not as authored catalog content. Everything else emerges from simulation.

### The catalog as data file

- Lives in `data/techniques.yaml` or `data/techniques.json` — human-editable, version-controlled, separable from code.
- The `TechniqueDefinition` Python dataclass mirrors the schema.
- The naming overlay lives in a separate file (or table, if persistence becomes DB-backed) since it grows during play rather than being authored once.

---

## Section 3 — The Eight Proficiency Tiers

Each technique in a judoka's vocabulary carries a proficiency tier and an internal progress counter toward the next tier. Tiers are discrete bands for chronicle and UI legibility; the internal counter provides smooth gradient for simulation purposes.

The eight tiers, in ascending order: **known, novice, proficient, intermediate, competitive, expert, master, legendary.**

The tier ladder maps approximately to belt progression but not strictly — a yellow belt may be novice on most techniques and proficient on their best one, while a black belt may be competitive on most and expert on a few. Belt progression is a function of tier distribution across vocabulary, not a function of any single technique's tier.

### Known

The judoka is aware the technique exists. They can name it, recognize it when watching others, and identify it when it is being done to them. If asked, they can demonstrate the rough shape in a static drill — they know where the feet go. They cannot fire the technique in live conditions; randori or competition use is not possible at this tier.

Acquired by: any vocabulary-acquisition pathway (being thrown by it, seeing a sensei demonstrate it, attending a seminar, accidental observation). This is the entry point for every technique in a judoka's vocabulary.

Mechanical effect in resolver: technique is in the vocabulary but cannot be selected by the action system. Does not contribute to signature strength.

Belt range: any. A white belt may be known on twenty techniques their sensei has demonstrated. A black belt may be known on dozens.

### Novice

The judoka can fire the technique in live conditions but poorly. Entries are telegraphed; grip configurations are approximate; kuzushi timing is missed more often than hit. In randori, they'll attempt it occasionally and it'll work occasionally. In low-level competition (against opponents of similar belt rank, in club tournaments or lower-tier brackets), they'll attempt it and it succeeds sometimes — usually against opponents who don't know how to defend it.

Acquired by: drilling repetitions plus initial live-condition exposure. A judoka can reach novice from known through any combination of dedicated practice and live-application attempts.

Mechanical effect: technique unlocks Stage 2 selection with a heavy base-difficulty penalty. Selection-roll failure outcomes (no-score, opponent recovery) dominate; landing-quality distribution skews toward no-score and waza-ari.

Belt range: typically white through green competitively.

### Proficient

The judoka can execute the technique reliably in cooperative practice and deploy it situationally in randori. Their entries are cleaner, the grip configurations are correct, the kuzushi timing lands often enough to be a real threat against equal-level opponents. In competition, they'll commit to it in mid-stakes matches against comparable opponents.

Acquired by: substantial drilling past novice with some live-application refinement.

Mechanical effect: Stage 2 selection with reduced (but still present) difficulty penalty. Contributes to signature strength derivation. Counts toward intermediate belt promotion thresholds.

Belt range: typically yellow through green.

### Intermediate

The judoka has internalized the technique's entry and execution. In randori, they select it when the configuration matches and land it often. In competition, they deploy it in mid-stakes matches with real success — they have moved past "trying it" and into "using it." Failures are tactical rather than mechanical: they executed correctly and the opponent defended correctly.

Acquired by: sustained drilling plus live competitive application across many matches.

Mechanical effect: full Stage 2 selection at base difficulty (no penalty). Contributes meaningfully to signature strength derivation. Counts toward upper-intermediate belt promotion thresholds.

Belt range: typically green through brown.

### Competitive

The judoka deploys the technique fluently in regional-level competition. The technique is a tested part of their game — they know its limits, its setups, and its counters. Other judoka in their bracket have likely seen them use it, though not yet at the level of regional scouting. Failures still happen against well-prepared opponents, but the technique is no longer a question mark in their repertoire — it's a known reliable tool. This is where brown belts and lower-dan black belts live for their primary techniques.

Acquired by: years of competitive use beyond intermediate. Cannot be reached through drilling alone — the tier requires sustained live-stakes refinement.

Mechanical effect: substantial contribution to signature strength derivation. Triggers early-stage signature recognition — opponents who have *recently* faced this judoka in competition adjust grip play in response to expectation, though not yet at the broader-scouting level expert produces. Counts toward black belt and lower dan promotion thresholds.

Belt range: typically brown through lower dan (shodan, nidan).

### Expert

The judoka is regionally fluent in this technique. Their competition record on it is identifiable — opponents who scout the region know to prepare for it specifically. Their execution is technically clean enough that landing quality skews toward waza-ari or ippon. They have a sense for when to commit and when to fake; they have developed setups and counter-counters.

Acquired by: years of high-level competitive use at the competitive tier, typically requiring participation in regional and national-level competition.

Mechanical effect: dominant contribution to signature strength derivation. Triggers full signature recognition — opponents *prepare* against this judoka before matches, bringing specific anti-technique grip play and posture. Counts toward upper dan promotion thresholds.

Belt range: typically high-dan black belt (nidan, sandan, yondan).

### Master

The judoka sets the regional standard for this technique. Their execution is studied by younger judoka. Landing quality skews ippon. Only equal-or-superior judoka with specific defensive specialization can stop the technique reliably. Their version of the technique has become identifiable enough that students of theirs are recognizable by it.

Acquired by: sustained excellence over a peak-career phase of high competitive volume at the expert tier.

Mechanical effect:

- Dominant contribution to signature strength derivation.
- Triggers the **player naming option** — the player may rename this technique within their dojo's prose overlay (Section 2).
- Eligible to teach this technique to others at high efficiency (Section 4).
- Counts toward upper-dan promotion thresholds.

Belt range: typically upper-dan (sandan, yondan, godan) at peak career.

### Legendary

Legendary is not "even better master." It is a *social* tier — the judoka's mastery has propagated beyond their own competitive use into the cultural memory of the region. Other dojos teach defense against them specifically. Their highlight reels circulate among younger generations.

Acquired by: master tier *plus* recognition criteria the chronicle tracks (see Section 7).

Mechanical effect (the slight-but-real boost):

- **Opponent recognition effect.** Non-legendary opponents enter matches against this judoka with altered fight-IQ application:
  - *Defensive preparation* — they bring anti-this-technique grip patterns and posture, slightly reducing Stage 1 availability against them.
  - *Composure dip under pressure* — in high-stakes match contexts (close score, championship rounds, golden score), opponent composure degrades slightly more than against non-legendary opponents. Decision quality on grip-fight choices drops by a small margin.
- **Finish quality bonus.** When the legendary-named technique fires in Stage 2, a small additional roll-bonus on landing quality. ~5–10% shift in landing-quality distribution toward cleaner outcomes.
- **Seminar eligibility.** This judoka can host seminars on this technique (Section 7). Seminars are how technique vocabulary spreads regionally beyond direct lineage.
- **Accelerated lineage propagation.** Students learning this technique from a legendary holder skip the `known` tier and arrive directly at `novice` — cultural saturation means they show up to the lesson already half-familiar with the shape.
- **Prose layer recognition.** Chronicle prose, sensei dialogue, and player-facing references treat the legendary holder with elevated language. Their overlay-named technique propagates through lineage faster and with broader recognition.

Legendary is rare. Most career-long master-tier judoka never reach legendary. In a region the size of NJ, a generation might produce a handful of legendary technique-holders total. Encountering one in the chronicle is an event.

### The internal progress counter

Within each tier, a hidden counter (0–100 or 0–1000, scale TBD) represents progress toward the next tier. Reps, randori uses, competition uses, successful executions, and failures feed it — with diminishing returns. The UI surfaces this as a progress bar within the tier label: "Intermediate (67% to Competitive)."

### Tier breakthroughs as chronicle events

Crossing a tier boundary is a `technique_milestone` chronicle entry (Section 9). "1968: M. Okada reached competitive proficiency in uchi-mata after the NJ State Open semifinal" is the kind of moment legend texture is built from. The chronicle records who, what, when, and the triggering event — was it a specific match win? A drilling milestone? A randori session? Different triggering events produce different prose flavors.

---

## Section 4 — Vocabulary Acquisition Pathways

A judoka's technique vocabulary grows over their career through five pathways. Each pathway has different probability shapes, different acquisition tier endpoints, and different chronicle texture.

### Pathway 1: Sensei-taught

The dominant pathway. A sensei teaches a technique to a student during a training session. Requires:

- The sensei has the technique at proficient or higher (you cannot teach what you cannot do). Teaching efficiency scales with sensei's tier in that technique — master-tier senseis teach faster and to better starting tier than proficient-tier senseis.
- The student has the prerequisite belt level (per the technique's `minimum_belt_for_competition_use`, used as a soft signal).
- The dojo curriculum allocates time to this technique. This is a Ring 3 surface — the player as sensei (or NPC senseis in worldgen) chooses what to drill.

Outcome:

- First exposure: student gains the technique at `known`.
- Continued instruction over weeks/months: progression to `novice`, then `proficient`, then potentially higher depending on student aptitude and time invested.
- A master-tier sensei teaching can move a willing student from `known` to `proficient` in roughly a season of dedicated drilling. Lower-tier senseis take longer and may cap their students at the sensei's own tier minus one.

Chronicle texture: `technique_learned` entry with `source = sensei_taught`, naming the sensei.

### Pathway 2: Thrown-by (opponent or senpai)

The reverse-engineering pathway. When a judoka is thrown by a technique — in randori, drilling, or competition — they gain awareness of it. The cleanness of the throw and the *context* of the thrower both determine how much they pick up.

**Two sub-pathways within Pathway 2.**

*Thrown-by-opponent* (competitive context). Randori or competition against a peer or rival. The thrower is not deliberately teaching — they are competing. The judoka picks up the technique by feeling it land, watching the entry from the receiving end, and post-match film review. Acquisition is meaningful but inefficient — opponents are not optimizing for the loser's learning.

*Thrown-by-senpai* (instructional context). A higher-belt training partner — a senpai, an assistant instructor, or the sensei themselves — uses the technique on the judoka in drilling or instructional randori, deliberately as part of teaching. The senpai is *demonstrating* by execution. They control the entry, they let the kohai feel each phase, they may slow down or repeat the technique multiple times in a session. Acquisition is significantly more efficient than thrown-by-opponent.

**Outcome.**

- First clean defeat by a technique (either sub-pathway): student gains the technique at `known`.
- Repeated defeats to the same technique by an opponent in competition: possible progression to `novice` over a competitive year, but slow.
- Repeated senpai-thrown demonstrations: faster progression. A senpai with high teaching aptitude (see below) can move a kohai from `known` to `novice` in a few weeks of drilling, and contribute progress toward `proficient` over months.
- Losing to a *legendary* holder of a technique teaches faster (Section 7's accelerated propagation), regardless of sub-pathway.
- To progress beyond `proficient` through Pathway 2 alone is unusual — the judoka cross-pollinates with sensei instruction, dedicated study, or active drilling.

**The teaching aptitude stat.**

Each judoka carries a `teaching_aptitude` value — a base stat (similar to fight IQ, conditioning, etc.) representing their innate capacity to transmit technique to others. Some judoka are simply better at teaching. They can break a technique down, demonstrate it patiently, calibrate their pressure to the kohai's level, and explain the why.

Teaching aptitude:

- Starts at a base value rolled at judoka creation.
- *Grows over time* through the act of teaching — every technique successfully transmitted to another judoka adds to the teaching aptitude counter. Like the technique vocabulary itself, teaching is a skill that improves with practice.
- Modulates senpai-thrown sub-pathway acquisition rate. A green belt with high teaching aptitude can run a kids' class effectively; a black belt with mediocre teaching aptitude is a great competitor but a poor teacher.
- Drives **assistant instructor selection** in Ring 3. When the sensei needs to delegate — running the children's class, taking over while the sensei is away at a seminar, leading specific drill sessions — the dojo logic ranks available judoka by teaching aptitude (modulated by their belt rank for credibility). A green belt with high teaching aptitude is the right choice for the kids' class; a black belt with high teaching aptitude is the right delegate for sensei-absent sessions.
- Becomes a Ring 3 surface where the player as sensei sees their dojo roster ranked by teaching capacity, and decides who to develop into instructional roles.

Teaching aptitude is *separate from* technique vocabulary. A judoka can be a master of uchi-mata and a mediocre teacher of it. A judoka can be merely competitive in their techniques but a brilliant teacher. The combination matters: the best instructors have both broad vocabulary and high teaching aptitude. The chronicle eventually records which senseis produced the most successful students, and teaching aptitude is part of why.

**Chronicle texture.**

`technique_learned` entry with `source = thrown_by_opponent` or `source = thrown_by_senpai`. The senpai sub-pathway records the senpai's identity; the opponent sub-pathway records the opponent and match context. These entries produce some of the best legend texture — "1968: K. Yamada first learned uchi-mata after being thrown by it three times by M. Okada at the NJ State Open" reads like a real career inflection.

### Pathway 3: Accidental discovery

The rarest pathway. A judoka stumbles into a technique without anyone teaching it to them and without having seen it used.

Probability: very rare. Weighted by:

- The judoka's fight IQ (higher IQ judoka improvise more)
- The technique's `base_difficulty` (low-difficulty techniques are discoverable; uchi-mata is not)
- The technique's prevalence in the judoka's environment

Outcome: the judoka gains the technique at `novice` directly (skipping `known`).

Chronicle texture: `technique_learned` entry with `source = accidental_discovery`. Rare and significant — marked specially in chronicle prose.

### Pathway 4: Dedicated study

The autodidact pathway. A judoka studies a technique outside formal instruction — watching film, reading texts, drilling alone or with a non-sensei partner.

Requires:

- The technique exists in the judoka's broader awareness.
- The judoka spends attention-hours on this study activity.

Outcome:

- Can move a judoka from no-vocabulary to `known` purely through study.
- Can move from `known` to `novice` with sustained study plus solo or partner drilling.
- Plateau at `proficient` is typical — dedicated study without live-stakes refinement caps progression.

Chronicle texture: `technique_learned` entry with `source = dedicated_study`.

### Pathway 5: Seminar attendance

The regional propagation pathway. When a legendary technique-holder hosts a seminar (Section 7), attendees gain the technique at an accelerated rate.

- No prior vocabulary: attendee gains the technique at `novice` (skipping `known`).
- Already at `known`: advances to `novice`.
- Already at `novice`: advances to `proficient`.
- Already at `proficient`: advances progress-counter substantially but does not auto-tier-up.
- Already at `intermediate` or higher: progress-counter advancement only.

Chronicle texture: `seminar_attended` entry on the attendee side, `seminar_held` entry on the host side.

### Pathway interactions and cross-pollination

Most real career vocabularies are built from pathway *combinations.* A judoka is sensei-taught uchi-mata at `known`, drills it to `proficient`, gets thrown by it twice by a regional opponent (reinforcing the body memory), attends a seminar by a legendary holder that bumps them to `intermediate`, then over years of competition reaches `competitive` through use. The chronicle entries from each pathway accumulate into the judoka's identifiable career narrative.

### The breakthrough moment

When a tier transition occurs, multiple pathways have typically contributed to it. The internal progress counter accumulates contributions from drilling, randori use, competition use, senpai demonstration, seminar attendance, and so on. The transition fires when the counter crosses the tier boundary.

The `technique_milestone` chronicle entry records *the pathway that contributed the final push* — the event or activity that took the counter from 98% to 100%. This is the "breakthrough moment" the prose layer can dramatize:

- A judoka grinding uchi-mata at 99% intermediate finally crosses into competitive after attending a Yonezuka seminar. The chronicle records the seminar as the breakthrough moment. "Tanaka's uchi-mata clicked at the Newark seminar in 1973."
- A judoka at 98% novice in osoto-otoshi is thrown by it cleanly by his senpai in a Tuesday drill session and finally feels the kuzushi vector. The breakthrough event is the senpai-thrown demonstration. "Yamada's osoto-otoshi came together after a Tuesday drill with senpai Watanabe in 1965."
- A judoka at 99% intermediate accidentally lands the technique cleanly in a tournament and the chronicle records the match as the breakthrough. "Okada's seoi-nage broke through in the quarterfinal of the 1968 NJ State Open."

Pathway contribution weights are calibrated, but the rough magnitudes are:

- **Largest single contributions**: seminar attendance from a legendary holder (one event can shift 20+ percentage points), interaction with a legendary technique-holder in competition (rare but high-impact).
- **Steady accumulation**: sensei-taught instruction over time, dedicated study, senpai-thrown drilling.
- **Smaller but real**: opponent-thrown competition exposure, randori reps, accidental discovery events (rare, but each one carries weight when it happens).

This means breakthrough moments tend to skew toward seminars and legendary interactions — the high-magnitude events — *but not always*. A judoka who has been steadily drilling and reaches threshold during a normal Tuesday class will record that Tuesday class as the breakthrough. The variety of breakthrough event types is what gives the chronicle prose its texture; not every legend is forged at the Olympics.

### Probability shape notes

Exact numerical values for pathway probabilities and progress-counter contributions are tuning parameters for calibration during HAJ-201/HAJ-202 and beyond. The shapes:

- Sensei-taught: deterministic given curriculum allocation. Progress counter advancement weighted by sensei's teaching aptitude and sensei's own tier in the technique.
- Thrown-by-opponent: probabilistic per loss event, weighted by cleanness and repetition. Smaller per-event contribution to progress counter.
- Thrown-by-senpai: deterministic given drilling allocation. Larger per-event contribution than opponent-thrown; weighted by senpai's teaching aptitude.
- Accidental discovery: very low base rate, weighted by judoka and technique factors. When it fires, contributes substantially to progress counter (and may directly grant `novice`).
- Dedicated study: deterministic given attention-hour allocation, slow progress curve.
- Seminar attendance: deterministic given seminar event participation. Large per-event contribution, especially from legendary hosts.
- Legendary holder interaction: facing a legendary holder in competition (regardless of win or loss) contributes to progress counter for that technique. Large per-event magnitude.

---

## Section 5 — The Bidirectional Ledger

Each `TechniqueRecord` in a judoka's vocabulary carries a usage ledger with both offensive and defensive history. This ledger is the substrate for resolver inputs, coaching surface, defensive specialty emergence, chronicle prose color, and the opponent-thrown-by acquisition pathway.

### Schema of a `TechniqueRecord`

```
TechniqueRecord:
  technique_id
  proficiency_tier         # known | novice | proficient | ... | legendary
  proficiency_progress     # 0–100 internal counter toward next tier
  teaching_tier            # peak tier ever achieved; does not decay (see Section 6)

  # Offensive ledger
  executed_attempts        # total times this judoka has attempted the technique
  executed_successes       # subset that produced a score (waza-ari or ippon)
  executed_ippons          # subset that produced a clean ippon
  last_executed_year

  # Defensive ledger
  defended_attempts        # total times this technique was attempted against this judoka
  defended_successes       # subset where defense held (no score against)
  defended_ippon_losses    # subset where the technique landed clean ippon against
  last_defended_year

  # Acquisition provenance
  source_of_acquisition    # sensei_taught | opponent_thrown_by | accidental | dedicated_study | seminar
  year_acquired
  acquired_from            # entity reference: sensei, opponent, seminar host, or null

  # Disuse tracking
  last_used_year           # max(last_executed_year, last_defended_year, last_drilled_year)
```

### Derived signals from the ledger

*Offensive signature strength* (per technique): a function of `proficiency_tier` and the execution ratio (`executed_successes / executed_attempts`). A judoka who attempts a technique 100 times and lands it 50 times has a stronger signal than one who attempts it 100 times and lands it 10.

*Defensive specialty* (per technique): a function of `defended_attempts` and `defended_successes`. A judoka who has been attacked with uchi-mata 200 times and defended 180 has developed *defensive specialty* against uchi-mata — separate from their offensive vocabulary.

*Defensive specialty is asymmetric with offensive vocabulary.* You can have defensive specialty against a technique without ever being able to execute it. A judoka who has defended uchi-mata 200 times but never drilled it is *expert at defending uchi-mata* without having uchi-mata in their offensive vocabulary at any tier above novice. This produces the "counter specialist" archetype.

*Acquired-from-opponent texture*: the `acquired_from` field combined with `source_of_acquisition = opponent_thrown_by` lets the chronicle write entries like "Tanaka's uchi-mata, which he first learned by being thrown with it three times by Yonezuka in 1967."

### The coaching read

A sensei reviewing their students' chronicle can see at a glance:

- "Okada has been hit with uchi-mata 20 times in the last 90 days, defended 4. Drill uchi-mata defense."
- "Hiraoka has hit competitive opponents with osoto-otoshi 35 times for 22 ippons — push for tournament selection."
- "Yamada has not attempted seoi-nage in over a year — at risk of disuse decay."

This is the Ring 3 sensei UI surfacing real ledger data.

### Defensive response model

When a technique is attempted against a judoka in match resolution, the defense calculation reads from the defensive ledger entry for that specific technique:

1. **Block roll** — can the defender prevent the technique entirely? Modulated by defensive specialty in this technique, fight IQ, conditioning, and the attacker's offensive strength. Common outcome at high defensive specialty.
2. **Counter roll** — given the attack landed in a recognizable configuration, can the defender execute a counter-technique? Only available if the defender has an appropriate counter in their offensive vocabulary at proficient or higher.
3. **Reduction roll** — given the technique is going to land, can the defender reduce its quality? An elite defender may force the throw down from ippon to waza-ari through mid-throw posture adjustment.
4. **Elite redirect** — a high-tier defender with high defensive specialty in this technique may, with low probability, *redirect the landing* — twisting in mid-air to land on stomach, denying the score entirely but opening immediate ne-waza. This is itself a deliberate choice: the elite trades score denial for ne-waza disadvantage, on the bet that their turtle-and-protect-neck transition will hold long enough to escape or reset. Available only to defenders with substantial ledger evidence (many defenses against this technique, high fight IQ, high conditioning).

Each roll is gated by the previous one failing. Most attempts terminate at the block roll.

### Specialty emergence over career

Defensive specialty against specific techniques emerges over a judoka's career based on what they face. A judoka in a region where uchi-mata is the dominant technique will accumulate uchi-mata defensive ledger entries faster than a judoka in a region dominated by seoi-nage. This produces *regional defensive culture* — a generation of judoka who came up under a uchi-mata specialist are uchi-mata-defenders.

This is one of the texture features the chronicle exists to make legible.

---

## Section 6 — Disuse Decay

A technique that is not used decays over time. The mechanism is gentle but real, and it produces important career-arc texture: retired masters whose execution rusts even as their teaching capacity remains, mid-career specialists who let their secondary techniques atrophy while focusing on their primary game, and the "comeback" arc.

### Decay rules

- Decay is evaluated annually, during the year-tick orchestrator.
- A technique is "in disuse" if `current_year - last_used_year >= disuse_threshold`. The threshold is calibrated but starts at approximately 3 years.
- A technique in disuse drops one proficiency tier per disuse window (every ~3 years of continued disuse). Internal progress counter also resets to mid-tier on a drop.
- Decay floor is `proficient`. A technique cannot decay below proficient through disuse alone.
- `known` techniques do not decay.

### What counts as use

Any of the following resets `last_used_year` to the current year:

- Executing the technique in randori or competition (offensive ledger)
- Defending against the technique in randori or competition (defensive ledger)
- Drilling the technique in formal training session (Ring 3 curriculum allocation)
- Teaching the technique to a student (master-tier and above)

### Teaching capacity does not decay

Important asymmetry: a retired master who hasn't executed uchi-mata in 20 years can still *teach* uchi-mata at master-tier efficiency. Their execution proficiency may have decayed to `competitive`, but their pedagogical capacity remains at master. This supports the retired-sensei archetype.

Encoded as two separate values on `TechniqueRecord`:

- `proficiency_tier` (decays with disuse)
- `teaching_tier` (does not decay; equals the highest `proficiency_tier` this judoka ever achieved)

### Comeback arcs

A judoka who returns to drilling a decayed technique recovers it faster than someone learning from scratch. The progress counter advances at accelerated rate while the current tier is below `teaching_tier`. Once they re-cross their old peak, normal advancement resumes.

### Chronicle texture

- `technique_disuse_drop` — when a technique decays a tier
- `technique_comeback` — when a judoka returns to a decayed technique and crosses back through tiers

---

## Section 7 — Legendary Status and the Seminar Mechanic

### Legendary qualification, formalized

A judoka qualifies for legendary tier in a specific technique when *all* of the following are true:

1. They are currently at master tier in the technique.
2. They have won at least N tier-weighted significant competitions using the technique. Tier weights (calibrated, start values):
   - Olympics: 10
   - World Championships: 7
   - Continental (Pan-Am, European, etc.): 4
   - National (US Open, US Senior): 3
   - Regional (NJ State, Northeast): 1.5
   - Club / local: 0.3
   - Required threshold: ~15 tier-weighted points
3. At least one student in their teaching lineage has reached competitive tier or higher in the same technique, *through teaching from this judoka*.
4. Minimum 5-year tenure at master tier.

All four criteria must hold. A judoka who meets criteria 1, 2, and 4 but has not taught anyone is *not legendary* — they are a great competitor whose technique died with them. This is intentional design: legendary is partly about teaching forward.

When a judoka qualifies, the chronicle writes a `legendary_recognition` entry.

### Seminar mechanic

A legendary technique-holder can host seminars on that technique. Seminar event structure:

- Host: the legendary judoka
- Host dojo: where the seminar is held
- Technique: the specific legendary-tier technique being taught
- Date: scheduled year and approximate season
- Capacity: bounded by dojo facility size (Ring 3 / Ring 6 facility data)
- Cost (host side): attention-hour expenditure for the host during the seminar period
- Cost (attendee side): travel cost (small) plus attention-hour expenditure for the attendee

### Attendance

- Attendees are judoka from other dojos in the region (or wider, for higher-prestige seminars).
- Attendance is voluntary and decided by attendee-side simulation logic.
- Player dojos can send students explicitly via Ring 3 curriculum decisions.

### Outcome (per attendee)

- No prior vocabulary: attendee gains the technique at `novice` (skipping `known`).
- Already at `known`: advances to `novice`.
- Already at `novice`: advances to `proficient`.
- Already at `proficient`: advances progress-counter substantially but does not auto-tier-up.
- Already at `intermediate` or higher: progress-counter advancement only.

### Chronicle entries

- `seminar_held` on host side (one entry per seminar event)
- `seminar_attended` on each attendee side (one entry per attendee)

Both reference the same `seminar_event_id`.

### Regional propagation as emergent system

Without seminars, technique vocabulary propagates only through direct sensei-student lineage. A technique invented in Newark in 1965 might never reach Cherry Hill by 1990 if no Newark-trained sensei opened a Cherry Hill dojo.

Seminars short-circuit this. A legendary holder hosting one seminar per ~3-year cadence over a 20-year peak career produces ~7 seminars, each attended by perhaps 10–30 judoka from across the region. Over a generation, this produces broad regional vocabulary without requiring direct lineage descent.

The result is *regional style identity*: in 1990, NJ as a region has identifiable signature techniques that emerged from the legendary holders of the 1960s–1980s.

### Named-technique propagation effect

If the legendary holder has set a custom name on this technique (Section 2's overlay), seminar attendees may pick up the custom name as well. Probability of name adoption is weighted by:

- Host's prestige
- Attendee's home dojo culture (TBD how this is modeled — possibly via a dojo-level "tradition" attribute in Ring 3)
- The name itself

When a name is adopted by an attendee's dojo, that dojo's overlay registers the name with `parent_overlay` pointing to the host's overlay. Over generations, named techniques cascade through regional dojos.

### Seminar visibility and player surface

For player-facing UI:

- Upcoming seminars in the region appear on a calendar surface (Ring 3 / Ring 6 calendar visualization)
- The player as sensei can decide whether to send students (curriculum decision, costs attention-hours)
- When the player's own students reach legendary tier, the option to host seminars appears as a player-side decision

This is a Ring 3 surface but the underlying mechanic is Ring 2 substrate.

### Legendary progress visibility (player surface)

For master-tier techniques in the player's dojo, the dojo UI surfaces a *legendary progress view*. Per master-tier judoka × master-tier technique, the player sees:

- Current tier-weighted competition score (e.g., "8.3 / 15 needed")
- Lineage inheritor status (e.g., "0 students at competitive+ — need 1")
- Tenure at master (e.g., "3 years / 5 needed")
- Aggregated readout: "Yonezuka, uchi-mata: 55% to legendary status"

This surfaces the strategic dimension of late-career judoka development. A player can see that one of their senseis is close to legendary in a technique and decide to push them — enter higher-tier competitions, focus drilling on the inheritor pipeline, extend their competitive career — to close the gap. Without the progress visibility, legendary qualification would feel arbitrary; with it, the player has a tangible target to chase, and the chronicle records the eventual qualification as the payoff of multi-year strategic investment.

For NPC dojos, this view is not exposed to the player. Legendary qualifications in other regions emerge as chronicle events when they happen.

---

## Section 8 — Belt Promotion Thresholds

Belt promotion in Hajime is *technique-vocabulary-driven*, not match-record-driven. The HAJ-202 placeholder of "win threshold of matches" is superseded by this section.

A judoka is eligible for promotion to the next belt when their technique vocabulary meets the threshold for that belt. Match record contributes (you have to actually deploy these techniques in competition for them to count toward tier progression), but the gating signal is *vocabulary depth and breadth*.

### The belt ladder (USJF/USJA standard, NJ 1960+ context)

**Adult ladder (judoka starting at age 18+):**
White → Yellow → Green → Brown (3 brown sub-grades, 3rd–1st kyu) → Black (Shodan through Judan, 10 dan grades).

**Junior ladder (judoka under 18):**
White → Yellow → Orange → Green → Blue → Brown (3 brown sub-grades) → Black.

Orange and Blue are *junior-only* belts within Hajime's NJ context — used to provide finer-grained progression for younger judoka whose technical development happens over a longer arc. Adult judoka skip Orange and Blue and progress directly Yellow → Green → Brown. A junior judoka who carries their rank into adult competition retains their belt; the junior-only belts continue to be recognized but are not re-used for adult progression.

This is partly a federation convention and partly a simulation simplification — different real-world federations and dojos have varying conventions. The Hajime baseline uses the adult/junior split because it matches Cranford JKC practice and produces a sensible technical progression for both age cohorts. Other dojos in the simulation may follow the same convention; federation-level variation is parking-lot work (Section 11 question 6).

### Promotion threshold table (draft, adult-track)

The thresholds below are for the **adult track**. The junior track applies the same vocabulary requirements at Yellow and Green; Orange and Blue interpolate between them with proportionally lower thresholds.

| Belt | Threshold |
|------|-----------|
| Yellow | 3 techniques at proficient or higher, drawn from at least 2 family classifications |
| Green | 7 techniques at proficient+; at least 2 at intermediate; at least 4 family classifications; covers tachiwaza and ne-waza both |
| Brown (3rd kyu) | 11 techniques at proficient+; at least 5 at intermediate; at least 2 at competitive |
| Brown (2nd kyu) | 13 techniques at proficient+; at least 7 at intermediate; at least 3 at competitive |
| Brown (1st kyu) | 15 techniques at proficient+; at least 9 at intermediate; at least 4 at competitive; at least 1 at expert |
| Shodan (1st dan) | 17 techniques at proficient+; at least 11 at intermediate; at least 5 at competitive; at least 2 at expert |
| Nidan (2nd dan) | 19 techniques at proficient+; at least 13 at intermediate; at least 7 at competitive; at least 3 at expert; at least 1 at master |
| Sandan (3rd dan) | 21 techniques at proficient+; at least 15 at intermediate; at least 9 at competitive; at least 5 at expert; at least 2 at master |
| Yondan (4th dan) | Ascending similarly |
| Godan (5th dan) | Ascending; at least 1 legendary tier |
| Rokudan and above | Increasingly recognition-based rather than execution-based; chronicle prestige metrics dominate |

For the junior track, Orange interpolates between Yellow and Green (5 techniques at proficient+, at least 1 at intermediate, at least 3 families), and Blue interpolates between Green and Brown 3rd kyu (9 techniques at proficient+, at least 4 at intermediate, at least 1 at competitive). Junior promotions also carry tenure requirements scaled to the longer development arc.

### Additional gating beyond vocabulary

- **Minimum tenure at current belt** — calibrated by belt, typically 6 months for low kyu, scaling to multiple years for upper dan.
- **Sensei recommendation** — the judoka's primary sensei must "submit" them for promotion.
- **Promotion test** — a chronicle-recorded event. Failure is possible (especially at higher dan grades).

### Promotion test outcomes

- **Pass with distinction** (rare) — exceptional demonstration, recorded specially.
- **Pass standard** (common) — promotion advances.
- **Conditional pass** (uncommon) — promotion granted with a noted weakness to address.
- **Fail** (rare) — promotion denied. Next attempt requires additional tenure plus addressing identified gaps.

Fail rate is intentionally low because the sensei's submission already filters most non-ready students.

### Dan grades above godan

Rokudan and above shift from execution-based to recognition-based criteria. Chronicle prestige, lineage contribution, regional reputation, and federation politics matter more than personal vocabulary at these grades. Hachidan and above are nearly always lifetime-achievement recognitions.

### Promotion as chronicle event

Each promotion is a `promotion` entry per Section 9. The entry records from_belt, to_belt, awarding sensei (or federation examiner), promotion test result (if applicable), year, and *vocabulary snapshot at time of promotion* — a frozen record of which techniques were at what tier when the belt was earned. Enables retrospective chronicle prose.

---

## Section 9 — Chronicle Entry Additions

Section 2 of the existing v2 spec defines the core chronicle entry types. This section adds the technique-vocabulary-specific entries that the HAJ-200 implementation needs.

### `technique_learned`

- judoka_id, technique_id, source_pathway, source_entity_id (sensei/opponent/seminar host or null), source_event_id (match reference or seminar reference or null), year, starting_tier
- Prose hook: "First learned X from Y in YYYY (via PATHWAY)"

### `technique_milestone`

- judoka_id, technique_id, new_tier, previous_tier, triggering_event_type (drilling_threshold / match_use / seminar / etc.), triggering_event_id, year
- Prose hook: "Advanced to TIER in X in YYYY following EVENT"

### `technique_disuse_drop`

- judoka_id, technique_id, new_tier, previous_tier, years_since_last_use, year
- Prose hook: "X dropped to TIER after PERIOD of disuse"

### `technique_comeback`

- judoka_id, technique_id, regained_tier, year, optional_triggering_event_id
- Prose hook: "Recovered X to TIER following return to training"

### `technique_named`

- dojo_id, technique_id, custom_name, naming_judoka_id (the master who earned the right), naming_type (dojo / sensei / hybrid / free_text), triggering_event_id (the mastery milestone), year
- Prose hook: "X within Dojo became known as 'CUSTOM_NAME', named by NAMER in YYYY"

### `technique_name_propagated`

- source_dojo_id, target_dojo_id, technique_id, custom_name, propagation_pathway (seminar_attendance / lineage_inheritance / regional_reputation), year
- Prose hook: "'CUSTOM_NAME' adopted by TARGET_DOJO via PATHWAY in YYYY"

### `seminar_held`

- seminar_event_id, host_judoka_id, host_dojo_id, technique_id, year, season, attendee_count, attendee_dojo_count
- Prose hook: "HOST taught TECHNIQUE seminar at HOST_DOJO in YYYY, attended by N judoka from M dojos"

### `seminar_attended`

- seminar_event_id, attendee_judoka_id, attendee_dojo_id, technique_id, year, outcome_tier_change (gained_tier / advanced_to_X / progress_only)
- Prose hook: "ATTENDEE attended HOST's TECHNIQUE seminar in YYYY (OUTCOME)"

### `legendary_recognition`

- judoka_id, technique_id, qualifying_competition_score, qualifying_lineage_inheritor_ids, tenure_years_at_master, year
- Prose hook: "Recognized as legendary in TECHNIQUE in YYYY (CRITERIA SUMMARY)"

### `promotion_test_held`

- judoka_id, from_belt, to_belt, examiner_id (sensei or federation examiner), examiner_type (sensei / federation), outcome (pass_distinction / pass_standard / pass_conditional / fail), conditions_noted (if applicable), vocabulary_snapshot_at_test, year
- Prose hook: "Tested for BELT in YYYY under EXAMINER (OUTCOME)"

### Schema notes

All entries inherit from a base `ChronicleEntry` with standard fields: `entry_id`, `year`, `quarter` (or finer if needed), `visibility_flags` (per v2 spec's fog-of-war architecture), `created_at_tick`.

The HAJ-200 ticket's entry type list expands to include all of the above. The HAJ-202 orchestrator writes these entries when the simulation triggers the corresponding events. The HAJ-203 CLI dump's `--event-type` filter accepts all of the above.

---

## Section 10 — Resolver Input Mapping

HAJ-201 specifies the resolver function signature as `resolve(judoka_a, judoka_b, context) → MatchOutcomeRecord` with five dimension inputs per judoka. This section specifies how the technique vocabulary system collapses into the *signature strength* dimension and contributes to the other four.

### Signature strength derivation

No longer a base stat. Derived per match from the judoka's vocabulary:

```
def signature_strength(judoka, context):
    # Top-K signature contribution
    top_techniques = sorted(
        judoka.vocabulary.values(),
        key=lambda r: tier_value(r.proficiency_tier) * execution_ratio(r),
        reverse=True
    )[:5]
    base = sum(tier_value(t.proficiency_tier) * execution_ratio(t) for t in top_techniques)

    # Breadth bonus
    intermediate_or_higher_count = sum(
        1 for r in judoka.vocabulary.values()
        if tier_value(r.proficiency_tier) >= tier_value("intermediate")
    )
    breadth_bonus = log(max(1, intermediate_or_higher_count - 5)) * BREADTH_WEIGHT

    # Era and rule-context adjustments
    context_adjustment = apply_era_filter(top_techniques, context.era, context.rules_version)

    return base + breadth_bonus + context_adjustment
```

The top-5 read captures *what this judoka actually brings to a match*. The breadth bonus rewards vocabulary depth without dominating the signal. Era/rules adjustments down-weight techniques that are restricted in the match's rules version.

### Defensive specialty contribution to other dimensions

The defensive ledger contributes to two of the other resolver dimensions:

*Tachiwaza* base stat is modulated by defensive-specialty depth across tachiwaza techniques. Computed at match time as a derived adjustment, not stored separately.

*Fight IQ* is modulated by *ledger breadth* — a judoka who has faced many different techniques across their career has more tactical pattern-matching to draw on.

Conditioning and ne-waza dimensions are not directly modulated by the technique vocabulary system (ne-waza has its own catalog and ledger, parallel structure but separate).

### The legendary modifiers

When a judoka is legendary in a technique that fires in a match, the Section 3 modifiers apply:

- Stage 1 availability: opponent's defensive preparation reduces availability against them
- Opponent composure dip in high-stakes context
- Finish quality bonus on Stage 2 landing quality roll

These are match-time adjustments, not stored stats.

### What the resolver does NOT consume

The resolver does not need the full vocabulary ledger every match. It needs:

- Top-5 signature techniques (precomputed per judoka, refreshed when vocabulary changes)
- Aggregate defensive specialty signal (precomputed, refreshed periodically)
- Aggregate ledger breadth signal (precomputed)
- Legendary flags per technique (sparse, only for legendary holders)

Precomputation matters at scale — Ring 2 worldgen runs thousands of matches per simulated year. Computing top-5 and aggregates on a per-judoka basis at vocabulary-change time (rare events) rather than per-match (frequent events) is the right tradeoff.

---

## Section 11 — Open Questions Parking Lot

Named here so they're not lost. Some have decisions; some remain genuinely open.

1. **Content filtering for free-text technique names.** *Resolved:* length cap and blocklist sufficient. No in-game social layer planned. Revisit only if community sharing features are ever added post-1.0.

2. **Calibration values throughout.** *Acknowledged:* all numerical thresholds in this document (promotion thresholds, tier-weighted seminar score, decay window, legendary qualifying score, signature strength formula weights, pathway contribution magnitudes, teaching aptitude growth curve) are first-draft. Calibration happens during HAJ-201/HAJ-202 testing and downstream tuning tickets. This document is the authoritative reference during calibration — when tuning a number, return here to confirm the design intent before adjusting.

3. **Ne-waza catalog parity.** *Confirmed scope:* a separate document — `ne-waza-vocabulary-system.md` — should mirror this one. The catalog is authorable directly from Kodokan Judo (Kano) and Judo Unleashed (Ohlenkamp); both books name ne-waza techniques and their family classifications. Existing `ne-waza-substrate.md` is the starting point for the substrate side. File as a separate design ticket.

4. **Weight-class interaction.** *Acknowledged and important:* weight classes interact with the vocabulary system in real ways. In randori, mixed-weight pairings are common and serve different purposes — a heavyweight working with a middleweight may be deliberately holding back, working on technique-side reps, or helping the lighter judoka build defensive skill against larger opponents. The simulation should support lower weights defeating heavyweights, especially in team-format competition (5v5 team battles where bracket pairings force cross-weight matches). The kuzushi-and-leverage mechanics of judo already produce this — a smaller specialist with a strong technique can throw a larger non-specialist. Worth a future design document on weight-class interaction with both vocabulary and resolver.

5. **Cross-discipline interaction.** *Confirmed:* the visible NJ map shows BJJ, boxing, wrestling icons alongside judo. Cross-discipline vocabulary translation is real and worth modeling:
   - BJJ practitioners have substantial ne-waza vocabulary that translates directly to judo (with naming differences — scarf hold has BJJ analogs; the technique is the same, the lineage and naming are different).
   - Wrestlers bring hip throws, leg trips, and takedown variants that translate to judo with weight-class-and-style adjustments.
   - The judoka's level in their cross-discipline determines what translates over: a black belt in BJJ entering judo brings master-tier ne-waza vocabulary; a regional-level wrestler brings competitive-tier takedown vocabulary.
   - Translation is not perfect — disciplines have different rules and emphases, so a technique that's at master in one discipline may translate as `intermediate` or `competitive` in judo, with progress potential to reach the original tier through judo-context refinement.
   - Out of scope for 1.0 player surface (player-side is judo-only); the *worldgen* should model cross-discipline emigration into judo (NJ wrestlers transitioning to judo in the late 1960s, BJJ practitioners adding judo throws in the 1990s+).
   - Revisit for sandbox/perspective-switch features in Ring 5.

6. **Federation politics on upper-dan grades.** *Parked:* hachidan-and-above promotions are partly political (federation relationships, regional power dynamics). Currently unmodeled; placeholder logic uses simple chronicle-prestige thresholds. Federation simulation in general is a Ring 4+ concern, well past 1.0.

7. **Technique prerequisite chains beyond `pedagogical_prerequisites`.** *Tentative direction:* learning a base technique likely teaches you (or makes available) its named variants — kosoto-gake and kosoto-gari may share enough mechanical DNA that proficiency in one accelerates the other. Not yet committed. Catalog authoring against Kodokan Judo and Judo Unleashed will surface real prerequisite relationships worth modeling. Decision deferred to catalog authoring phase.

8. **Catalog authoring tooling.** *Approach decided:* authoring is direct from book to markdown. Comrade will work through Kodokan Judo and Judo Unleashed page-by-page, photographing relevant pages and transcribing the technique entries into the catalog data file. This keeps the catalog grounded in the source material (the books were bought specifically to ensure correctness on names, classifications, and mechanics). A small validation tool (schema check, grip signature consistency, kuzushi vector validity) is still worth filing as a utility ticket post-skeleton, to catch typos and inconsistencies during authoring.

9. **The "Cranford anchor" seed data.** *Resolved:* nothing pre-authored. The Cranford JKC anchor remains a small Easter egg — Cranford emerges in 1962 as the first dojo in the simulation, but its senseis, techniques, and any custom names develop through procgen and play. No special-cased starting vocabulary, no pre-applied overlay names. This preserves the "everything emerges from simulation" design principle while keeping Cranford as a meaningful named touchstone.

10. **Per-dojo "tradition" attribute affecting name propagation.** *Parked:* Section 7 hand-waves this as a probability weight in seminar name adoption. Revisit when Ring 3 dojo attribute system is designed. Not blocking.
