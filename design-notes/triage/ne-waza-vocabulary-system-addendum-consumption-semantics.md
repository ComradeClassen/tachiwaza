# Ne-waza vocabulary system — addendum

### Consumption semantics for the v0.1 catalog

*v0.1 addendum, drafted 2026-05-21. Companion to `ne-waza-vocabulary-system.md` v0.1. This document settles three load-bearing questions about how the resolver consumes the catalog that the original spec specified at the data-format level but not the semantics level. Sourced from HAJ-216 design conversation.*

---

## Why this addendum exists

The original ne-waza spec specifies what the catalog **contains** (techniques, positions, struts, connection types, mechanical classes) without fully specifying how the resolver **consumes** that content. The HAJ-205 ne-waza authoring phase shipped 29 techniques without surfacing schema edge cases, but consumption-semantics gaps were lurking under the surface:

- Partial-connection matching — when uke's defenses partially nullify a pin's connections, is the pin still on?
- Strut activation semantics — what does *uke initiates the strut* actually mean for induced transitions?
- Defense gating — what determines which defenses uke can attempt against a given technique?

This addendum answers all three. It also surfaces a single load-bearing mechanic — **the danger zone** — that does four jobs at once and unifies behavior across pins, submissions, sensei coaching, and referee non-progress calls.

The addendum is structured as new section §6.5 ("Catalog consumption semantics") with four subsections, plus annotation callouts to earlier sections where field meanings are affected.

---

## §6.5 Catalog consumption semantics

### §6.5.1 Partial-connection matching and the danger zone

The Stage 1 availability check in §1 says a technique passes when its `required_connections` set is "satisfied by active ConnectionEdges." This subsection defines *satisfied*.

**The hysteresis pair.** Pin and submission techniques use two thresholds expressed as fractions of authored `minimum_quality`:

| Technique class | Enter threshold | Stay threshold | Break point |
|---|---|---|---|
| Pin (osaekomi) | 50% of authored minimum_quality, on every connection | 40% on every connection | First connection below 40% |
| Submission (shime, kansetsu) | 50% on every connection | 25% (default; modulated by defender's submission-defense skill) | First connection below 25% |

When tori is attempting a pin, the pin **enters active state** the moment all required connections cross 50% of their authored minimum_quality. The OsaekomiClock begins. The pin **stays active** as long as every connection remains at or above 40%. The pin **breaks** the moment any connection drops below 40%.

Note the asymmetry: enter requires *all* connections above threshold; break requires only *one* connection below threshold. This is by design — a pin needs full structure to establish, but loses its mechanical integrity the moment any structural element fails.

**The danger zone.** Between 30% and 50% of authored minimum_quality (for pins) or between 25% and 50% (for submissions), a connection is in the **danger zone**. The connection is still active but mechanically compromised. The danger zone does four jobs simultaneously:

1. **Hysteresis stay state.** The pin is held but at risk. If multiple connections are in the danger zone simultaneously, the pin is held by a thread.
2. **Sensei coaching window.** Sensei can identify which connection is failing and coach the appropriate response (see §6.5.4).
3. **Induced transition window.** When a connection enters the danger zone on a dominant-position terminal, tori may pivot to an alternative terminal (see §6.5.2).
4. **Referee no-progress timer accumulation.** Time spent with the position not advancing toward commit or transition accumulates against the referee's stall threshold (see §6.5.5).

The danger zone is the substrate-level state where most ne-waza dynamics resolve. Outside the danger zone (connections above 50% or below break threshold), the position is either firmly established or firmly lost; inside the danger zone, every mechanic is active.

**Break narration: most-broken-element names the strut.** When a connection drops below its break threshold and the technique fails, the engine selects the narrative strut by:

1. Identifying which connections crossed the break threshold on the same tick (tied breaks possible)
2. Among tied breaks, selecting the connection that is *furthest below* its break threshold (severity-based tiebreak)
3. Computing the set of struts whose `applicable_against_connection_types` field includes the broken connection's type
4. Selecting the strut from that set with the highest effectiveness given uke's attributes and any active sensei coaching

The selected strut is named in narration. The technique's `applicable_defensive_struts` field is *not* consulted for post-commit defenses — those are derived at runtime from connection-type intersection. The field semantically narrows to **pre-commit struts only** (see §6.5.1 annotation below).

**Tunability for future calibration.** The 50%/40% pair for pins and 50%/25% for submissions are starting values for v0.1. Two tuning dimensions are anticipated for v0.2:

- **Skill-gap modulation.** Large skill gaps between tori and uke may justify tighter stay thresholds (large gap → 50%/30%, the inferior judoka has less margin) or looser ones (60%/30%, the elite judoka pins more decisively but loses pin less easily). The resolver should log applied threshold pairs from match start; calibration follows from actual play data.
- **Submission-defense skill.** Uke's submission-defense attribute modulates the submission break threshold — a 0.8 submission-defense uke might break at 15% rather than 25%, holding out longer than baseline.

Both modulations are deferred. v0.1 ships with the fixed thresholds above.

**Annotation to §1.** The Stage 1 availability rule in §1 should be read as: technique passes availability when its `required_connections` set is **all at 50% or above of authored minimum_quality** (for entry from inactive state) or **all at 40% or above of authored minimum_quality** (for continuation from active state). Stage 1 is therefore stateful — the engine tracks per-technique active/inactive state and applies the threshold appropriate to the current state.

**Annotation to §2.2.** The `minimum_quality` field on `required_connections` should be read as the **authored baseline** against which enter and stay thresholds compute. The field is not itself a hard cutoff; it's the reference value for the percentage-based thresholds.

**Annotation to §4.5.** The `applicable_defensive_struts` field semantically narrows in v0.1 — it now lists only **pre-commit struts** (those that disrupt setup before the technique commits). Post-commit struts are derived at runtime by intersecting connection types between the broken connection and each strut's `applicable_against_connection_types` field. Existing catalog entries with post-commit struts authored in this field should be audited — those entries are not incorrect (the runtime cross-reference will find the same struts) but the field is now redundant for that purpose.

### §6.5.2 Induced transitions fire in the danger zone

The original spec §3.3 says an induced transition fires `if_uke_strut_activates: head_extraction`, without defining *activates*. This subsection defines it.

**The rule.** An induced transition fires when:

1. A connection that the named strut targets enters the **danger zone** (between break threshold and 50% of authored minimum_quality), AND
2. Tori passes a **fight-IQ check** to recognize the transition opportunity, AND
3. Tori chooses to pivot rather than reinforce the failing connection.

Outside the danger zone, induced transitions do not fire. Above 50%, uke has not committed enough to the defense for tori to read a signal; tori has no basis to abandon the original threat. Below break threshold, the original technique is already lost; tori is out of position and cannot smoothly pivot.

**Why this is the right window.** The danger zone is precisely the state where uke's defensive strut is **visibly working but not yet successful**. Tori can read the failing connection in real time, recognize that uke has committed energy to one specific defense, and pivot to a threat that exploits uke's commitment. The textbook sankaku flow — tori has the triangle, uke fights the choke by trying to slip the head out, tori releases the choke pressure and attacks the trapped arm — happens exactly in this window.

**Fight-IQ as the gating skill.** Whether tori recognizes the transition window is gated by judoka fight-IQ:

- Elite judoka recognizes danger-zone signals reliably. Transitions fire as soon as the window opens, regardless of which connection.
- Mid-level judoka recognizes the signal inconsistently — large drops are visible, marginal ones are not.
- Low-level judoka mostly does not recognize the signal independently. Transitions only fire when sensei coaching surfaces the opportunity (see §6.5.4).

Fight-IQ is judoka-state, not catalog data. The resolver consults the judoka's fight-IQ attribute against a per-tick recognition roll.

**The decision after recognition.** Even when fight-IQ recognizes the transition opportunity, tori may choose to *reinforce* the failing connection rather than *pivot*. The choice depends on:

- Whether the alternative terminal is mechanically reachable (the LIMB_TRIANGLE arm-side connection must be above 50% on its own to enter the alternative pin)
- Tori's stamina (reinforcing costs energy; pivoting also costs energy but differently)
- Tori's strategic preference (some judoka are pin-finishers, some are submission-hunters, some are positional)

These factors are engine-side decision logic, not catalog data. The catalog declares **which** transitions are possible (`induced_transitions` list on the position); the resolver decides **whether** to execute them.

**Pre-commit struts cannot trigger induced transitions.** Pre-commit struts (wrist_pre_grip, grip_strip_to_loose) fire before tori has committed to the technique. There is no danger zone yet because there is no active technique. If uke pre-grips her own wrist to prevent a juji-gatame setup, tori has not yet committed anything to pivot from — tori simply does not commit to juji-gatame and picks a different setup. This is tachiwaza-style technique selection, not an induced transition.

Induced transitions are therefore exclusively a **post-commit** mechanic. The original spec's optional defense_phase distinction is resolved: pre-commit and pre-position struts cannot trigger induced transitions; only post-commit struts can.

**Annotation to §3.3.** The `if_uke_strut_activates` field should be read as "fires when the connection that the named strut targets enters the danger zone." The strut named in the field must have `defense_phase: post_commit` — pre-commit and pre-position struts in this field are schema errors and should be caught by validator warning (see §6.5.6).

### §6.5.3 Effectiveness-proportional defenses with no minimum threshold

The original spec §4.3 lists `required_uke_attributes` on each strut without specifying what happens when uke's attribute values are low. This subsection settles that uke always attempts, but effectiveness scales with attributes.

**The rule.** A defensive strut is always *offered* as a candidate to uke. Its effectiveness is **proportional to uke's attribute values** on the strut's `required_uke_attributes` list. There is no minimum threshold below which uke cannot attempt the strut.

A uke with 0.3 bridge_strength against a kesa-gatame still attempts bridge-and-roll-right; the bridge applies 30% of normal pressure to the BODY_PRESSURE connection. The pin holds (the connection stays above its 40% stay threshold) but uke has burned stamina on the attempt. After enough failed bridges, uke is exhausted and pin time accumulates uncontested.

**Why this works mechanically.** Under the hysteresis model from §6.5.1, every defensive attempt translates to pressure on a specific connection, modulated by attribute strength. A 0.3 bridge_strength uke applying 30% of normal bridge pressure produces a small connection-quality decrement, not zero. The "effectiveness-proportional" rule is just the natural consequence of how the hysteresis model resolves pressure.

If we layered a minimum threshold on top (uke with bridge_strength below 0.4 applies zero bridge pressure), we'd contradict the continuous-pressure model. The current rule keeps everything continuous.

**Stamina cost is approximately constant.** A failed bridge costs uke roughly the same stamina as a successful one — possibly slightly more, because the attempt didn't relieve the pin pressure. This creates the realistic dynamic where a low-skill uke wastes stamina flailing through defenses while a high-skill uke escapes efficiently. The stamina cost surface is engine-side; the catalog data (`required_uke_attributes`) is unchanged.

**Use-driven attribute progression.** Every defensive attempt — successful or failed — produces a small increment to the relevant `required_uke_attributes` on the strut. This is the engine-side learning loop that makes the flailing-beginner pattern self-correcting over time. The increment is:

- Smaller for failed attempts than successful ones
- Larger for tournament conditions than dojo training
- Subject to diminishing returns at higher attribute values (0.3 → 0.4 is faster than 0.8 → 0.9)
- Smaller at higher belt levels (a brown belt's bridge_strength grows slower per attempt than a white belt's because the brown belt is closer to skill ceiling)

This progression mechanism is engine-side; the catalog contributes by declaring which attributes a strut exercises (`required_uke_attributes` field, already in the schema). No catalog change required.

**Senpai transmission and sensei weekly focus as additional progression channels.** Two engine-side mechanics beyond match attempts also produce attribute growth:

- **Senpai transmission.** Senior belts in the dojo drilling with junior belts transmit attribute boosts on the techniques and defenses the seniors use most. Designed separately in HAJ-218.
- **Sensei weekly focus.** Sensei picks a technique for the week; the class drills it; students get offensive, defensive, or both boosts depending on per-student differentiation. Also designed in HAJ-218.

Together with match attempts, these three channels produce defensive-attribute distributions that vary significantly across dojos at matched belt levels. This is the dojo-identity-shapes-students mechanic that justified removing belt-gating from the catalog (§6.5.4).

**Injuries as judoka-state modifiers.** A judoka with an injury has a negative modifier on defensive struts that involve the injured body part. The modifier ranges from -15% to -35% depending on injury severity. Beyond the effectiveness reduction, each use of the injured body part rolls against an **aggravation risk** — failed rolls increase injury severity.

This creates a real player decision: a uke with a sprained shoulder facing kesa-gatame can attempt bridge-and-roll-over-head (loads shoulders, suffers the -15% modifier, risks aggravation) or attempt bridge-and-roll-right (loads hips more, lower effectiveness against this particular pin but no shoulder load). Choosing the safer defense may concede the pin; choosing the optimal defense may worsen the injury.

To support this query efficiently, the catalog schema gains one new field:

**Schema addition: `involves_body_parts: list[str]` on DefensiveStrutDefinition.**

The field lists body parts the strut loads, drawn from an enum: `left_shoulder, right_shoulder, both_shoulders, neck, upper_back, lower_back, hips, abdomen, left_knee, right_knee, both_knees, left_ankle, right_ankle, both_ankles, left_elbow, right_elbow, both_elbows, left_wrist, right_wrist, both_wrists`. The validator should lock this enum.

Authoring task: populate `involves_body_parts` for the 17 existing struts. Approximate distribution:

| Strut | involves_body_parts |
|---|---|
| bridge_and_roll_right | hips, lower_back |
| bridge_and_roll_left | hips, lower_back |
| bridge_and_roll_over_head | both_shoulders, neck, upper_back |
| frame_and_shrimp | hips, both_elbows |
| leg_recapture | hips, both_knees |
| arm_extraction | right_shoulder, right_elbow (or left equivalents per stance) |
| preemptive_face_turn | neck, both_shoulders |
| armlock_counter | both_elbows, right_wrist |
| sleeve_pull_and_slip | both_shoulders, neck |
| elbow_push_and_roll | both_elbows, hips |
| grip_strip_to_loose | both_wrists, both_elbows |
| wrist_pre_grip | both_wrists |
| elbow_bend_and_clasp | both_elbows |
| elbow_rotate_and_bend | both_elbows, both_shoulders |
| posture_up_and_base | lower_back, both_knees |
| head_pivot_out | neck, upper_back |
| stand_up_from_lock | both_knees, hips |

Values above are starting estimates. Authoring pass during this addendum's implementation should review against the strut's `body_motion` prose to verify body-part involvement is accurate.

**Annotation to §4.3.** The `required_uke_attributes` field should be read as the list of attributes whose values modulate the strut's effectiveness, on a continuous scale, with no minimum threshold below which the strut cannot attempt. The new `involves_body_parts` field is sibling data for the injury-system query.

### §6.5.4 No belt-gating of defenses; three propagation channels instead

The original spec implied that defensive knowledge might be belt-gated (with `minimum_belt_for_defensive_use` as a possible schema addition). This subsection settles that belt-gating is not used; instead, three engine-side progression channels produce realistic defensive vocabulary distributions.

**The rule: no belt-gating of defenses.** Every defensive strut is universally available to every judoka regardless of belt level. Effectiveness varies based on the judoka's attributes for the strut's `required_uke_attributes`. A white-belt judoka has bridge-and-roll in their candidate decision-set the same as a black belt; the difference is that the white belt's bridge_strength and hip_mobility are low, so their bridge produces little pressure on the BODY_PRESSURE connection.

**Why not belt-gating.** Most defensive struts are *reflexive* — bending an arm when someone tries to straighten it, bridging when pressed down, posting a hand when pushed backward. These are pre-rational responses to body pressure, not curriculum-taught patterns. Belt-gating reflexive defenses produces wrong behavior (a white belt would fail to bend their arm against a juji-gatame). The struts that are genuinely curriculum-taught (armlock_counter requires recognizing tori's exposure; elbow_rotate_and_bend requires understanding lock geometry) are differentiated by *attribute thresholds*, not knowledge gating — a low-skill judoka with low fight-IQ won't recognize the armlock_counter window even if it's mechanically available to them.

The use-driven progression from §6.5.3 plus the three propagation channels below produce all the differentiation that belt-gating would have provided, more realistically.

**The three propagation channels.**

1. **Match attempts.** Every defensive attempt in randori or competition produces a small increment to relevant attributes. Successful attempts increment more; failed attempts still increment. Tournament conditions amplify; diminishing returns at high values; smaller increments at higher belt levels.

2. **Senpai transmission.** Senior belts drilling with junior belts produce attribute boosts on the defenses the seniors have high vocabulary scores on. Vocabulary score is computed from the senior's own match history — what they have attempted frequently, with what effectiveness. Senior judoka who specialize in defense propagate defensive skill; those who specialize in offense propagate offensive skill. Designed in HAJ-218.

3. **Sensei weekly focus.** Sensei picks a technique each week. The class drills it. Distribution of offensive-vs-defensive boost per student is modulated by student attributes, sensei differentiation skill, and the dojo's focus tree. Designed in HAJ-218.

**Dojo identity shapes defensive vocabulary.** Together, the three channels mean that two judoka at the same belt level in different dojos can have substantially different defensive profiles. A dojo with strong senpai culture and a Specialization-in-ne-waza focus tree produces students whose defensive attributes are well above curve for their belt; a dojo with weak culture and a Competitive focus tree on stand-up produces students whose defensive attributes are below curve. This is correct mechanics — real dojos differ in what they emphasize, and their students reflect those emphases.

**Procgen cross-discipline override.** The judoka procgen layer can instantiate judoka with prior-art knowledge from other grappling traditions — a BJJ blue belt entering the simulation as a judo white belt has elevated defensive attributes on the defenses BJJ emphasizes (especially submission escapes and guard recovery). The catalog's universal-defense-availability rule supports this naturally: the BJJ-experienced white belt attempts the same defenses as everyone else, but with much higher effectiveness on BJJ-emphasized struts than her judo belt would suggest.

This is the same architecture as tachiwaza procgen — the `minimum_belt_for_competition_use` field on tachiwaza techniques is the curriculum default, and procgen overrides per cross-discipline background. Ne-waza defenses have no such field, so the override is even simpler: it just sets attribute values directly.

**Schema implication: none.** No new fields added. The `applicable_defensive_struts` field on techniques does not gate defensive knowledge — it now serves only as a list of pre-commit struts per §6.5.1. Universal defense availability is the runtime rule, not a per-technique catalog declaration.

### §6.5.5 Referee no-progress timer for stalled positions

The original spec §4.5 introduces the referee summons mechanic on struts but does not address the case where the position **fails to advance** without any specific strut succeeding. This subsection settles the no-progress timer mechanic.

**The rule.** When the position is in the danger zone (any connection between break threshold and 50% of authored minimum_quality) and is *not* advancing toward either:

- Re-establishment (connections climbing back above 50%), or
- Termination (connections falling below break threshold), or
- Induced transition (per §6.5.2)

then the referee's no-progress timer accumulates. When the timer reaches the referee's stall threshold, the referee calls Matte for non-combativity.

**Referee personality thresholds (v0.1, ticks):**

| Personality | Stall threshold |
|---|---|
| Strict | 3–4 |
| Neutral | 5–7 |
| Generous | 8–11 |

These thresholds replace the placeholder values I had in earlier conversation. The numbers match the actual rhythm of competition judo (4-minute matches; 25-second non-progress windows are unrealistic).

**The timer is per-position, not per-match.** Each time the position transitions to a new state (a new connection set establishes, or position-state-machine moves to a new broad state), the no-progress timer resets. The referee is judging whether *the current configuration* is advancing; restarting effort on a different configuration restarts the clock.

**When the timer does not run.** The timer does not accumulate during:

- Active connection-quality changes in either direction (either judoka is doing something that changes the substrate state)
- Sensei coaching calls being absorbed and acted on (the judoka is responding to instruction)
- Position transitions in progress

This means the timer accumulates only during true stalemates — both judoka holding position without producing measurable substrate change. That's the actual behavior the no-progress call is meant to penalize.

**Pre-position struts and the pin-that-never-formed case.** When tori attempts a pin entry but fails to cross the 50% enter threshold within the no-progress window, the referee calls Matte. The pin "didn't form" — tori either didn't commit enough or uke's pre-position struts successfully refused. Either way, no pin time accumulates and the position resets to neutral. This is the natural outcome of pre-position defense being effective; no special mechanic needed.

**Half-guard stall as canonical case.** When uke's `leg_recapture` strut succeeds against a pin and the position transitions to HALF_GUARD_BOTTOM, the OsaekomiClock suspends. Tori runs a half-guard-pass sub-loop attempting to re-establish a pin. If tori does not progress within the no-progress threshold (strict 3–4 ticks, neutral 5–7, generous 8–11), the referee calls Matte. This is the mechanic that prevents half-guard from being a permanent neutralizer.

**Annotation to §3.2.1.** The position-categories discussion should note that transitional/neutral positions (half guard, scramble, NEWAZA_TRANSITION) all use the no-progress timer to determine when the referee resets the match to stand-up. The timer is per-position-state, resetting on broad-state transitions.

### §6.5.6 Sensei coaching window (two-stage probabilistic)

Sensei coaching is referenced throughout the prior subsections; this subsection consolidates its mechanics.

**The rule.** During the danger zone (any connection between break threshold and 50%), sensei can call corner advice. The coaching has effect through a two-stage probabilistic process:

**Stage 1: Sensei sees the failing connection.** Whether the sensei recognizes which specific connection is failing is gated by sensei skill:

- Olympic-level sensei: near-certain recognition of the failing connection within the danger zone
- Black-belt sensei: reliable recognition for major drops, inconsistent for marginal ones
- Lower-belt sensei: largely fails to recognize the specific failing connection; may coach generically ("defend!", "tighten!") rather than specifically

**Stage 2: Judoka hears and acts on the coaching.** Whether the judoka can integrate the coaching mid-engagement is gated by judoka skill and state:

- Elite judoka with composed state: near-reliable integration of correct coaching
- Mid-level judoka: integrates clear coaching, may not parse complex or contradictory advice
- Low-level judoka under pressure: may not hear coaching at all due to sensory overload; even when heard, may execute incorrectly
- Judoka in panic state (stamina depleted, position critically compromised): coaching effectiveness drops sharply

Both stages can fail independently. A senior sensei calling correct coaching may not reach a panicked white belt; a junior sensei calling generic coaching may still help an elite judoka who interprets the generic call correctly against their own read of the position.

**Effect of successful coaching.** When both stages succeed, the called strut receives an effectiveness multiplier proportional to sensei skill. The multiplier applies for the duration of the call (typically 2–3 ticks). After the multiplier window expires, the strut returns to baseline effectiveness.

**Coaching applies to both sides.** Sensei chooses whether to coach the dojo's student (always, in competition) or either student (in dojo randori where the sensei is teaching). In the dojo's-student case:

- If the dojo's student is uke (defending), sensei coaches the appropriate defensive strut to accelerate escape.
- If the dojo's student is tori (attacking), sensei coaches the appropriate connection-reinforcement to prevent uke's escape.

Same two-stage mechanic, same skill gating, applied to either side.

**Coaching does not gate the strut — it amplifies.** Without sensei coaching, an elite judoka with high fight-IQ may still recognize the danger-zone signal independently and execute the appropriate response (per §6.5.2). Sensei coaching is an *additional* signal source that boosts both recognition probability and execution effectiveness. A judoka with high enough fight-IQ may transition to alternative threats and execute appropriate defenses entirely without coaching.

**Annotation to §4.5.** The `referee_summons` field on struts is unrelated to this mechanic — sensei coaching is a separate substrate channel from referee actions. The fields can co-exist on the same strut without interaction (a strut may be coachable by sensei *and* trigger a referee summons hint when it succeeds).

---

## §6.5.7 Validator extensions

This addendum implies one optional validator extension to enforce the new consumption-semantics rules:

**Warning when `if_uke_strut_activates` references a strut with `defense_phase != post_commit`.**

Per §6.5.2, only post-commit struts can trigger induced transitions. A position entry with `induced_transitions[].if_uke_strut_activates` pointing at a pre-commit or pre-position strut is a schema error — the transition cannot fire because the strut doesn't operate in the post-commit window. The validator should warn (or error, at author's preference) when this occurs.

**Implementation note.** The validator already loads both the position catalog and the strut catalog (HAJ-215 deliverable). Adding this check is a few lines in `_check_induced_transition_strut_phases` per the existing validator's check-function pattern.

---

## §6.5.8 Cross-reference to related work

Three downstream tickets carry forward design surfaces this addendum names:

- **HAJ-218** — Senpai transmission and sensei weekly focus mechanics. Specifies the two engine-side propagation channels referenced in §6.5.3 and §6.5.4. Design only; engine implementation downstream.
- **HAJ-219** — Tachiwaza parity audit. Examines which mechanics from this addendum (hysteresis, most-broken-narrates, sensei coaching window, use-driven progression, injury body-part involvement) should also apply to stand-up.
- **HAJ-201 / HAJ-207 successors** — Resolver consumption of the ne-waza catalog. Implement the mechanics this addendum specifies.

The injury system itself (with aggravation risk, severity tracking, recovery curves) is not yet ticketed and lives further downstream. The catalog data (`involves_body_parts`) supports the system; the system needs its own design pass when it becomes the active surface.

---

## Schema changes summary

This addendum produces exactly one schema change and two field-semantic narrowings:

**Schema addition:**
- `involves_body_parts: list[str]` on `DefensiveStrutDefinition`, drawn from a 20-value enum of body parts. Required field on all struts. Validator locks the enum.

**Field-semantic narrowings (no field changes, just documented meaning shifts):**
- `applicable_defensive_struts` on techniques — now contains only pre-commit struts. Post-commit struts are derived at runtime from connection-type intersection.
- `minimum_quality` on `required_connections` — is the authored baseline against which 50%/40%/30%/25% thresholds compute, not a hard cutoff.

**Authoring tasks following from this addendum:**
- Populate `involves_body_parts` on all 17 existing struts in `data/defensive_struts.yaml`
- Audit existing techniques' `applicable_defensive_struts` lists — entries that were authored as post-commit struts are now redundant (engine derives them at runtime); should be removed or commented out for clarity, though leaving them in is not harmful since they'll still resolve correctly
- Verify all `induced_transitions[].if_uke_strut_activates` references in `data/ne_waza_positions.yaml` point at post-commit struts; correct any that point at pre-commit or pre-position struts

These are small authoring tasks (the strut count is 17, the position count is 2). Estimated half-session of work after the addendum lands in repo.

---

*End of v0.1 addendum.*
