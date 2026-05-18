# Catalog Authoring Notes

Working doc for HAJ-205 authoring. Source of truth for the catalog itself is `data/techniques.yaml`; this file is where authoring questions get tracked, triaged, and resolved.

---

## Resolved

### Schema (HAJ-213)
- **Multi-grip configurations** → `canonical_grip_signatures` is a *list* of complete configurations (e.g. classic vs one-handed seoi). Single-entry list is the common case. Mirror duplicates are NOT authored.
- **Lefty mirroring** → handled by the engine via judoka stance + `mirror_eligible: true` (default). Authors record one canonical (right-stance) configuration per variant. Override `mirror_eligible: false` only for genuinely asymmetric techniques.
- **Multi-direction kuzushi** → `admissible_kuzushi_vectors` (required, gates Stage 2 selection; accepts the `any` wildcard for omnidirectional throws like deashi-harai) + optional `primary_kuzushi_vectors` (subset used for scoring quality and prose). When primary is omitted it defaults to a copy of admissible.

### Schema extensions (post-HAJ-213)
- **`gokyo_kyo: int (1–5)`** added — captures Kodokan kyo grouping for source-book ordering, sensei curriculum logic, and player-facing lore. Backfilled across all Gokyo no Waza entries.

### Schema clarifications (vocab doc Section 2)
- **`failed_throw_consequence` stakes are explicit:** `tori_falls_to_back` and `tori_thrown` are *high-consequence* failures where uke commonly scores waza-ari or ippon — NOT neutral resets. `tori_to_knees` is low-stakes; `uke_lands_stomach` is a ne-waza opportunity for tori with no immediate score either way. Authoring it as `[]` or empty list is wrong — the field is an optional single value, not a list. Omit it entirely when failure mode is unremarkable.

### Difficulty and pedagogy decisions
- **White-belt minimum-belt list** → osoto-gari, deashi-harai, o-goshi, hiza-guruma, ouchi-gari are the canonical white-belt-deployable throws. Other Group 1 entries stay at yellow/green.
- **Difficulty threshold ≠ pedagogy** → a base_difficulty ≤ 35-40 heuristic is NOT authoritative for "white-belt teachable." The Gokyo kyo grouping is the pedagogical ordering. Author difficulty honestly per technique; let curriculum logic figure out what each sensei delivers to each student.
- **Per-judoka dynamic difficulty** → IS the design intent, but lives at the resolver layer (HAJ-201 / Stage 2 selection), not the catalog. Catalog stores `base_difficulty` (absolute, judoka-agnostic skill ceiling); resolver consumes it plus judoka attributes (timing, hip-height differential, etc.) plus context to compute *effective* difficulty per match.
- **Kosoto-gari 45 → 60** — timing demand is higher than osoto-gari's; the relative bump is correct even though kosoto stays in the same family.

### Validator (HAJ-211)
- Pre-commit hook active. Run manually with `python src/catalog_validator.py data/techniques.yaml`.

### Deferred (decision recorded, work later)
- **`couple_type` enum** → keep permissive (free string) until the physics-substrate doc enumerates the canonical vocabulary. Validator does not check couple_type validity today. Means some authoring drift is tolerated.
- **`attribute_sensitivities` per technique** → useful future schema extension (per-throw list of which judoka attributes most modulate effective difficulty), but defer until all 40+ throws are authored so the calibration ladder has a real shape to inform it.
- **`base_difficulty` ladder calibration pass** → defer until all ~40 throws are in. Easier to calibrate relative values across the full set than piecemeal.
- **Disqualifying-grip sweep** → end-of-authoring pass. Author the *canonical* defense for each throw (e.g. seoi-nage = opponent's deep collar grip, harai-goshi = opponent's deep sleeve grip on tori's throwing side). Don't enumerate every theoretical block.
- **Player-facing throw lore / instructions** → not 1.0 catalog work. Punt to a separate authoring track that re-uses `technique_id`s and adds rich-text description, common setups, common defenses. The simulation doesn't need step-by-step instructions to compute outcomes — it uses grip + kuzushi + couple + posture. Photographing book pages for reference is fine for *your* authoring, but the text doesn't belong in `techniques.yaml`.

---

## Open — design decisions needed before/during Group 5

### Counter throws (go-no-sen-no-waza) — utsuri-goshi case
Some throws are *deliberate counters* to specific other throws. Utsuri-goshi against right hane-goshi is textbook. Others: ushiro-goshi (counters most hip throws), te-guruma (counters seoi/uchi-mata), tani-otoshi (opportunistic counter to multiple), ura-nage (counters several).

**The schema gap.** Today there's no way to express "this throw is a counter to X" — the entry just lists its grip and kuzushi, which can't differentiate "I initiate this freely" from "I fire this when uke commits to throw X."

**Direction I'd recommend.** Add an optional field:
```yaml
counter_class: deliberate     # none | opportunistic | deliberate
counters:                     # technique_ids this is a deliberate counter to
  - hane_goshi
```
- `deliberate` means the throw is *primarily* a counter (utsuri, ushiro-goshi, te-guruma) — the resolver gives it high weight only when uke just initiated a throw in `counters`.
- `opportunistic` means the throw works fine as a primary attack *and* as a counter (tani-otoshi).
- `none` (default) means no special counter behavior.

**Impact.** Small schema addition. Resolver work (HAJ-201) consumes it for Stage 2 selection. Worth filing as its own schema-revision ticket once Group 5 is in.

### Rule-set restrictions beyond Kodokan inclusion — leg-grab ban case
Sukui-nage and several Group 4-5 throws involve leg grabs, which the IJF banned in 2010. `era_restricted` is a single integer year, which works if the throw becomes *fully* illegal — but the leg-grab ban is a *partial* restriction (the throw is still legal in many rule sets, the leg-grab variant isn't).

**The schema gap.** No way to express "this technique is still legal but a specific variant or grip is banned under rule-set X from year Y."

**Direction I'd recommend.** Two options:
1. **Per-rule-set restriction list:** add `rule_set_restrictions: list[str]` referencing named bans (e.g. `["ijf_2010_leg_grab_ban"]`). The simulation maintains a separate rule-set evolution doc; matches at year X under rule-set Y consult both.
2. **Free-text rule_notes field:** add `rule_notes: str` for human-readable notes ("Leg-grab variant banned IJF 2010; throw remains legal in non-IJF rule sets"). Simpler, but not machine-consumable.

For 1.0, I'd lean **option 1** for the throws clearly affected (sukui-nage, te-guruma, kuchiki-taoshi, morote-gari), with a small companion file `data/rule_set_changes.yaml` enumerating the named bans. Engine consumption is HAJ-201/HAJ-205 downstream.

### O-guruma and the "specific vs general kuzushi vector" question
You moved o-guruma from `[forward_pure, forward_right_diagonal]` to `[forward_right_diagonal]` per the Kodokan book. Good call — and a useful general rule.

**My take.** Author what the book says. Be specific. The resolver provides creativity in other ways (stochastic selection, per-judoka attribute modifiers, fight IQ → improvisation chance). Over-broad admissible kuzushi sets make the resolver less discriminating and reduce the distinctness of each throw. If the book is wrong about a specific case, fix that case in authoring — but don't widen by default.

### Couple_type accuracy — copilot suggestions vs book accuracy
Copilot-suggested values are *plausible* but not necessarily book-correct. The validator doesn't catch wrong couple_types (it's a free string).

**My take.** Don't fix this now. The physics substrate doc (currently a design-philosophy outline, not a couple-type taxonomy) is where the canonical vocabulary will eventually live. Until then, copilot-plausible is acceptable noise. Flag specific ones you're uncertain about in the entry as a comment (`# couple_type uncertain — verify against Kodokan biomechanics`) so a later pass can find them.

### Soto-makikomi foot placement / body positioning
The book's instructions specify tori's foot placement and body angle for soto-makikomi. The simulation has body mechanics that handle foot placement during execution.

**My take.** The catalog encodes *the throw*, not *biomechanical execution detail*. Tori's exact foot placement is engine-level — derived from couple_type, posture_requirements, and the physics substrate's body-part vocabulary. Don't add it to the catalog. If the throw has a *required* tori posture (e.g. "tori must be hip-low for seoi-nage to load"), that's worth a `tori_posture_requirement` field eventually, but it's not blocking 1.0.

---

## Tactical: rule of thumb for "data in catalog vs. behavior in resolver"

If it's a property *of the technique* (doesn't change match-to-match), it goes in the catalog.
If it's a property *of the execution context* (depends on judokas' stats, stance, current state), it goes to the resolver.

This rule resolves most of the "should this be in the catalog?" questions:
- Counter-throw relationships: in catalog (the technique IS a counter, that's invariant)
- Per-judoka difficulty modifiers: in resolver (depends on whose throwing)
- Foot placement during execution: in resolver/physics (depends on current body state)
- Rule-set restrictions: in catalog (whether the throw is legal under rule X is invariant)
- Mirror-eligibility: in catalog (whether the throw mirrors is invariant); engine consumes it with judoka stance.

When in doubt, ask: *does this fact change based on who's throwing or what's happening right now?* If yes, resolver. If no, catalog.
