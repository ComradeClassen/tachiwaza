# From tissue layers to tatami: what Dwarf Fortress teaches Tachiwaza

**Dwarf Fortress's body-part simulation, nerve system, grapple graph, and prose engine constitute the deepest combat model in gaming history — and roughly 60% of its architecture translates directly to a judo coaching sim.** The other 40% would bury Tachiwaza in scope. This document maps what to take, what to leave, and what to build first, treating DF's design as a studied reference rather than a blueprint. The core lesson is this: DF's combat feels alive because every noun in every sentence maps to an actual simulation datum. Tachiwaza needs the same — every grip, every fatigue tick, every postural shift should generate prose that reads like it was written by a human who loves judo, because the simulation underneath is specific enough to support that level of detail.

---

## Part 1: Dwarf Fortress systems in mechanical detail

### The body is a tree, and every leaf can break

DF structures creature anatomy as a rooted tree. For a humanoid, the upper body is root. Everything connects downward through `CON` (connect to specific part) and `CONTYPE` (connect to any part with a given flag) tokens. A dwarf's full body is composited from modular templates — `HUMANOID`, `2EYES`, `HEART`, `BRAIN`, `GUTS`, `5FINGERS`, `RIBCAGE` — stitched together at parse time. The resulting tree for a dwarf has roughly **82 body parts**, from the upper body root down through neck → head → brain/eyes/ears/teeth, through shoulders → upper arms → elbows → lower arms → wrists → hands → individual fingers, and mirrored for the lower body through hips → upper legs → knees → lower legs → ankles → feet → toes.

Each body part carries **functional flags** that determine gameplay consequences. `GRASP` means the part can hold weapons and initiate wrestling. `STANCE` means it's needed to stand — lose both feet and you crawl. `THOUGHT` (brain) means damage equals instant death. `NERVOUS` (spine) means damage disconnects everything below it. `JOINT` means it can be broken through wrestling holds. `THROAT` means it can be strangled. `GUTS` means damage triggers nausea. `UNDER_PRESSURE` means organs eject if the containing body part is opened. These flags are the actual mechanical hooks — they're what make severing an arm different from bruising a muscle different from puncturing a lung.

The critical design pattern: **body parts have no hit points.** Each part instead has an ordered stack of tissue layers — skin, fat, muscle, bone for a limb; organ-specific tissue for internal organs — and each tissue layer has its own material properties. A `DEFAULT_RELSIZE` value per part (upper body = 2000, hand = 80, finger = 5) determines physical size, which affects both contact area in combat and how much tissue exists to damage.

Tarn Adams has stated this directly: *"Hit points are depressing to me. It's sort of a reflex to just have HP/MP, like a game designer stopped doing their job. You should really question all of the mechanics in the game from the bottom up."*

### Tissue layers are where the simulation lives

The tissue layer system is what makes DF's combat genuinely different from every other game. Each body part has an ordered stack of tissue layers applied from outermost to innermost. For a standard humanoid limb, the stack is:

| Layer (outer → inner) | Relative Thickness | Key Properties |
|---|---|---|
| Hair (STRANDS) | 1 | Cosmetic; edged attacks pass through |
| Skin | 1 | SCARS, CONNECTS |
| Fat | 1 (varies) | THICKENS_ON_ENERGY_STORAGE, CONNECTS |
| Muscle | 3 (THICKENS_ON_STRENGTH) | ARTERIES, MUSCULAR, CONNECTS |
| Bone | 2 | STRUCTURAL, CONNECTIVE_TISSUE_ANCHOR, SETTABLE |

Each tissue type references a material template with six stress modes — impact, shear, compressive, tensile, torsion, bending — each with yield, fracture, and strain-at-yield values. When a steel battle axe hits a goblin's arm, the engine doesn't roll against a defense number. It calculates the axe's momentum (mass × velocity × skill modifier), determines the contact area, then tests that force against each tissue layer's shear yield and shear fracture values, from skin inward.

**The layer-by-layer resolution algorithm works like this:** For an edged attack, momentum must exceed a threshold calculated from the ratio of the target tissue's shear properties to the weapon's shear properties, modified by contact area and weapon sharpness. If momentum exceeds threshold, the layer is cut — momentum drops ~5% — and resolution proceeds to the next layer inward. If momentum fails to exceed threshold, the edged attack converts to blunt damage for that layer specifically, with momentum drastically reduced (multiplied by strain-at-yield / 50000, which for most metals means a 98–99% reduction). This is why chain mail works — it has a strain-at-yield of 50000, meaning it doesn't reduce blunt momentum at all but does convert the edge to blunt, protecting against cuts while still transmitting impact.

For blunt attacks, the check is against impact fracture values. If exceeded: fracture. If not: bruise. Bruised tissue absorbs energy and stops deeper penetration. A blunt weapon that fractures the bone has punched through skin, fat, and muscle first — each absorbing a fraction of force — before reaching the structural layer.

**Key tissue properties that drive consequences:**
- **`PAIN_RECEPTORS`**: Bone has **50**, everything else has **5**. This means a broken bone generates roughly 10× the pain of bruised muscle. A single fracture (bone damage of 50×3 severity + surface tissue damage of 3×5) produces ~165 pain — which exceeds the ~150 unconsciousness threshold. This is why bone breaks are fight-enders in DF, mechanically identical to how a broken arm ends a judo match.
- **`VASCULAR`**: Heart tissue = 10 (highest), lungs = 8, muscle = 5, skin = 1. Controls bleed rate. Heart puncture = rapid death from hemorrhage.
- **`CONNECTS`**: A body part cannot be severed until ALL tissue layers with this flag are cut through. For a limb, that means skin, fat, muscle, and bone must all be penetrated.
- **`STRUCTURAL`**: Bone. If the structural layer is broken, the body part loses function.
- **`ARTERIES`**: Edged damage to tissues with this flag can sever arteries, dramatically increasing blood loss independent of the VASCULAR value.

The four-file pipeline that makes this work — material templates defining physics, tissue templates defining biology, body detail plans bridging them, creature definitions invoking the plans — is elegant modular architecture. A single tissue definition can be reused across hundreds of creature types, and changing a material's shear yield changes combat outcomes for every creature that uses that material.

### Nerves, pain, and the cascade from damage to incapacitation

DF models nerves at two levels. **Central nerves** (spine) use the `NERVE_TEMPLATE` tissue, applied to spine body parts tagged `[NERVOUS]`. Damage here disconnects all body parts below the damage point — upper spine damage paralyzes everything, including lungs, causing suffocation. **Peripheral nerves** are implicit properties of the `MUSCULAR` tissue layer in limbs. When muscle tissue is sufficiently damaged (particularly by edged weapons cutting through it), motor and sensory nerves in that limb can be severed.

**Motor nerve damage** disables the body part while leaving it attached. A dwarf with motor nerve damage to the right arm drops their weapon and cannot grasp with that hand, but the arm is still physically present and targetable. This is permanent — nerve tissue has no healing rate by default. Motor nerve damage to legs means "ability to stand lost" — the creature falls and cannot walk, ever (though a crutch compensates for one lost leg, and dwarves can eventually crutch-walk faster than their original walking speed due to Agility gains from practice).

**Sensory nerve damage** eliminates pain from the affected body part. This is mechanically double-edged: the creature loses tactile feedback, and attacks may weaken slightly, but it also means that body part can sustain further damage without contributing to pain-based unconsciousness. Edged weapons frequently sever sensory nerves while cutting through muscle, which paradoxically makes victims *more resistant* to pain from those specific wounds. DF players have discovered the "supersoldier" phenomenon — dwarves who survive severe burns that destroy all skin and fat tissue lose their sensory nerves entirely, becoming fighters who effectively have the `NOPAIN` creature tag.

**The pain system** is beautifully simple in structure but produces complex emergent behavior. Pain accumulates per tissue layer damaged: `damage_severity × PAIN_RECEPTORS`. At a threshold modified by the creature's Toughness attribute, all combat rolls are halved — attack accuracy, defense, dodge, parry all degraded by 50%. At approximately **150+ accumulated pain**, the creature "gives in to pain" and falls unconscious. Unconsciousness in DF is usually fatal because enemies automatically target the unconscious victim's head with perfectly accurate strikes.

The Toughness attribute gates how much pain a creature can endure. Creatures in a **martial trance** (triggered by fighting multiple enemies simultaneously) are immune to pain penalties entirely, with effective combat skill calculated as `(skill+1)×5` — a massive boost.

**Status effects stack multiplicatively**, not additively. A creature that is both stunned and dizzy doesn't lose 50% + 50% = 100% effectiveness — it loses 50% × 50% = **75% effectiveness** (25% remaining). This means multiple minor injuries accumulate into devastating combined penalties.

The full incapacitation cascade runs: tissue damage → functional loss per body part (motor nerve damage, structural failure, organ shutdown) → systemic effects (pain accumulation, blood loss, nausea from gut damage) → incapacitation (unconsciousness, prone from lost stance, suffocation from disabled lungs). **There is no single health bar.** A creature can be functionally destroyed through any of these cascading paths — all limbs operational but unconscious from a single broken bone; massive physical damage but fighting on because sensory nerves are destroyed; slowly dying from arterial bleed while still swinging a weapon.

As Tarn Adams told PC Gamer about the health interface: *"People miss the old health interface. We'd need to draw 100 more icons. Do you have sutures, do you have an overlapping fracture, are your intestines inside or outside your body? Sensory nerve damage, motor nerve damage, impaired ability to stand… and then the different levels of bleeding, arterial bleeds and whether or not your lungs are functioning properly. It just adds up."*

### The grapple graph: wrestling as relational state machine

DF's grappling system tracks wrestling as a **set of discrete grab relationships** between body parts — a bipartite graph where each edge connects one of your body parts to one of the opponent's body parts, with hold-type metadata. Both creatures can simultaneously hold each other. You might be grabbing their right arm with your left hand while they're grabbing your throat with their right upper arm.

Each grab tracks: which of your body parts is the grasper, which of their body parts is grasped, the hold type (grab → lock → choke → break → strangle), and directionality (who holds whom). **A grabbed body part cannot be used to attack.** An opponent with any active grabs on them cannot dodge to a different square or move until all grabs are broken. The grappler is also immobilized — mutual position lock.

The wrestling move taxonomy follows a hierarchical progression:

**Foundational:** Grab (any free grasper → any target body part). This is the entry point to the entire system.

**State-dependent follow-ups from existing grabs:**
- Grab upper body → **Takedown** (opponent goes prone) or **Throw** (prone + stunned + distance)
- Grab throat → **Choke** → **Strangle** (unconsciousness → suffocation → death)
- Grab limb → **Lock** joint → **Break** joint (structural bone damage, no bleeding, limb disabled)
- Grab head with free hand → **Gouge** eyes (blindness + extreme pain)
- Bite + latch → **Shake** with teeth (can tear body parts apart)

Each progression is a multi-turn commitment. Choke → Strangle is a minimum 3-turn sequence (grab throat, place chokehold, strangle). Lock → Break is similar. This creates meaningful decision chains — committing to a stranglehold means spending multiple turns during which the opponent gets counter-actions.

**The three-tier outcome resolution** is critical to the system's feel. Every wrestling contest produces one of three results: **success** (hold advances or maintains), **partial failure** ("You adjust the grip of Your right upper arm on The creature's upper body" — grip slips but holds, must retry), or **total failure** ("The creature breaks the grip!" — grip lost entirely, must restart). This creates a probabilistic state machine where the grapple graph is constantly shifting.

What determines outcomes: **relative mass is the dominant factor** — a dwarf cannot effectively wrestle an elephant. Wrestling skill improves both offense and defense. Strength affects grip force, throw distance, and joint-breaking success. Endurance affects fatigue during extended grappling. And critically, **blood loss proportionally reduces a creature's effective mass** — wound a minotaur enough and it becomes wrestleable by a dwarf. Unconsciousness bypasses size entirely — any unconscious creature is vulnerable to wrestling regardless of mass.

### Adventure Mode's wrestling UI makes the grapple graph legible

This is the design pattern most directly relevant to Tachiwaza. Adventure Mode's wrestling screen is divided into two panels:

**Top panel — Current Holds Display:** Shows all active grab relationships with clear directionality. Format: `You [right upper arm] →→ GRAB →→ [upper body] Goblin`. Arrows pointing from you toward them mean you're holding them; reversed arrows mean they're holding you. This is the grapple graph rendered as readable text — every edge in the bipartite graph is displayed with its vertices and type.

**Bottom panel — Available Actions:** A scrollable, context-dependent list of wrestling moves. This list is **dynamically generated from the current hold state**. If you've grabbed the throat, "Choke" appears. If you've locked a joint, "Break" appears. If you have a free hand and are grabbing the head, "Gouge" appears. If you have no grabs, only "Grab [target] with [your body part]" options are listed. The action space is the current hold state's transition function.

The target list is extremely granular. PC Gamer described it: *"The menu for wrestling shows off a pretty exhaustive list of things to grab on the bad guys. Normal stuff like their hand, their weapon, and the like of course, but also very, very specific things. Things like the individual fingers, for example, or perhaps specific teeth."*

The decision loop for a player: **observe** the hold display → **assess** free resources (which hands/arms aren't committed) → **read** the dynamically filtered action list → **choose** an action → **read** the combat log for the three-tier result → **re-enter** the wrestling menu to continue the chain. This creates a rhythm of state-reading → decision → outcome → state-reading that Tarn Adams described as *"a good compromise between sort of a real-time game like the Elder Scrolls type game and the sort of strategy tactical combat of a SSI-type game."*

Tarn's own description of the system in action, from DF Talk #21: *"I increased my stealth quite a bit then fought against someone who didn't know what they were doing, and then using the observer skill you see they were coming in with a left-handed punch and so I just waited until the punch was imminent and then shot out a catch with my left hand. Which is just grabbing their hand with my hand, and then it knows what that means now. So it interprets that as intercepting their attack and stops their attack. So I caught the hand with my hand, and then I caught the other hand, put him into wristlocks and broke his wrists."*

### How simulation granularity becomes prose

DF generates combat text through an event-to-announcement pipeline. Each combat event type (defined in `announcements.txt`) has a corresponding prose template. The core strike sentence follows this pattern:

```
[The DESCRIPTOR ACTOR] [VERB] [The DESCRIPTOR TARGET] in the [BODY_PART] 
with [his/her MATERIAL WEAPON], [LAYER_1_RESULT], [LAYER_2_RESULT], 
and [LAYER_3_RESULT] through the [QUALITY MATERIAL ARMOR]!
```

Every slot is filled by querying the simulation state. "The tall swordsdwarf" — size attribute + profession. "Punches" — attack type from weapon/body-part definition. "The thin administrator" — target's size + profession. "In the right lower arm" — targeted body part from the tree. "With his left hand" — instrument body part. "Bruising the muscle" — damage type (from blunt resolution) to tissue layer (from layer-by-layer calculation). "Through the xlarge llama wool cloakx" — armor item with material and quality markers.

The damage verbs map directly to mechanical severity: "bruising" = below yield (tissue deformed but functional), "tearing" = between yield and fracture (permanent deformation), "fracturing" = bone between yield and fracture, "shattering" = bone beyond fracture, "pulping" = complete soft tissue destruction. Attack verbs map to weapon physics: swords "slash" and "stab" (EDGE:SLASH, EDGE:STAB), axes "hack" (EDGE:HACK), hammers "bash" (BLUNT:BASH), fists "punch," teeth "bite."

**The layer-by-layer revelation is the narrative technique that makes DF combat feel authored.** When a sword slash hits a leg, the combat log reads: *"...tearing the skin, bruising the fat, tearing the muscle, and fracturing the bone!"* Each comma-separated clause represents a real computation — the blow penetrating deeper, each tissue layer tested against material properties, the reader experiencing the weapon driving through anatomy. A weaker hit might read only: *"...bruising the skin!"* The depth of the prose reflects the depth of the penetration, which reflects the actual physics calculation.

Real examples from DF combat logs:

> "The axedwarf slashes the goblin in the right upper arm with her steel battle axe, tearing the skin, tearing the fat, tearing the muscle and fracturing the bone!"

> "The speardwarf stabs the troll in the upper body with his iron spear, piercing the fat, tearing the muscle and bruising the bone!"

> "The hammerdwarf strikes the goblin in the upper body with his steel war hammer, bruising the muscle, fracturing a rib and bruising the right lung!"

> "The dwarf grabs the goblin by the right hand and bends the right wrist backward! The joint is broken! The goblin drops the iron short sword!"

Follow-up lines report consequences: *"An artery has been opened by the attack and many nerves have been severed!" "A ligament has been torn and a tendon has been torn!" "The right lower leg flies off in a bloody arc!" "The force bends the left upper arm, fracturing the bone!"*

Wrestling generates its own announcement taxonomy: `COMBAT_WRESTLE_LOCK`, `COMBAT_WRESTLE_CHOKEHOLD`, `COMBAT_WRESTLE_TAKEDOWN`, `COMBAT_WRESTLE_THROW`, `COMBAT_WRESTLE_STRANGLE_KO`, `COMBAT_WRESTLE_ADJUST_GRIP`. Each maps to a template filled from the grapple graph state.

Tarn Adams on this philosophy, from his chapter in *Procedural Storytelling in Game Design*: *"When people play games, they tell stories about their experiences. If we view games as a storytelling companion, we can think systematically about what sorts of game mechanics encourage player stories of a certain kind or make the storytelling process easier for players."* And from the Stanford interview: *"Story and simulation are strictly different methods of handling the narrative. With a simulation, you're essentially letting the computer make narrative choices you don't want to make (or can't possibly make in such volume), instead of removing the related game mechanics entirely."*

The design process itself was narrative-first: *"That was the main reason we made the game — the storytelling potential — and our design process involved writing stories that we'd like the game to produce, in the same way you might draw several example maps while designing a map generator."*

---

## Part 2: Translation to Tachiwaza Ring 1–2

### Your 15-body-part model is probably the right granularity — with two additions

Tachiwaza's current model has 15 body parts: right/left hand, right/left forearm, right/left bicep, right/left shoulder, right/left leg, right/left foot, core, lower_back, neck. Each with 0–10 capability values, 0.0–1.0 fatigue, and an injury boolean.

DF's humanoid has ~82 body parts with full tissue layer stacks. The question is whether Tachiwaza should move toward that granularity.

**Honest answer: no, not for tissue layers. But yes for two structural additions.**

DF's tissue layer system exists because it needs to model swords cutting through skin into muscle into bone — the layer-by-layer penetration is the entire point of the combat resolution. Judo doesn't have penetrating damage. Nobody's sword is working through Sato's epidermis. The forces in judo are **compressive** (pins), **torsive** (joint locks), **constrictive** (chokes), and **impact** (throws landing on the mat). These don't propagate through tissue layers — they act on joints, the neck, the ribcage, and the overall musculoskeletal system.

What DF's architecture *does* teach Tachiwaza is that **the body part model should be as granular as your prose needs it to be.** If your combat log will never say "left knee," you don't need a left knee body part. If it will say "left knee," you need the knee in the model.

**Two additions to consider:**

**1. Split "leg" into upper_leg and lower_leg (or add knee as a joint node).** Judo leg techniques target different segments — an osoto-gari attacks the leg behind the knee, an ouchi-gari attacks the inner thigh, a deashi-barai sweeps the ankle/foot. Your current model has `right_leg` and `right_foot` but no knee/thigh distinction. For throw resolution — where the angle and height of the reaping/sweeping action matters — you probably want at least `right_thigh`, `right_knee_area`, `right_shin` or similar. This also matters for fatigue localization: a judoka who's been sprawling hard has different thigh fatigue than one who's been doing foot sweeps.

**2. Add jaw/chin as a sub-part of head (or just "head" as a body part).** You currently have `neck` but no head. Concussion from head impact on the mat during a hard throw is a real judo consideration. A judoka who gets blasted with a clean ura-nage and their head whips into the tatami is in a different state than one who lands on their back with chin tucked. The `neck` part is critical for choke mechanics in ne-waza, but `head` matters for slam impact and for the composure system (getting rattled after a hard landing).

**Don't add tissue layers.** Instead, make the injury boolean into a richer structure — see the recommendations section.

### What translates from the nerve/motor/sensory system — and what doesn't

Nobody's getting their spine severed in judo. But the *functional architecture* of DF's nerve/pain system maps remarkably well to judo's reality if you translate "tissue damage" to "sport-relevant impairment."

**What translates directly:**

**Fatigue as localized motor impairment.** DF's motor nerve damage makes a limb present but non-functional. In judo, extreme localized fatigue does the same thing — a judoka whose forearms are burned from a prolonged grip battle has arms that are physically present but can't maintain grip strength. Your current fatigue model (0.0–1.0 per body part) already captures this. The DF lesson is to make the functional consequences crisp: at what fatigue threshold does grip strength degrade? At what threshold does a judoka physically lose a grip involuntarily (DF equivalent: "drops the weapon")? Define thresholds, not gradients. **0.7 fatigue = grip strength halved. 0.9 fatigue = involuntary grip break is possible each tick.**

**Pain-adjacent effects from impact.** DF's pain system — where accumulated pain halves all combat rolls and eventually causes unconsciousness — maps to the impact and recovery dynamics of judo throws. A judoka who just got slammed hard with an osoto-gari and landed flat on their back experiences a moment of being stunned, winded, disoriented. In DF terms, this is the combination of the `COMBAT_EVENT_STUNNED`, `COMBAT_EVENT_WINDED`, and dizziness effects. For Tachiwaza, model this as a **stun/impact state** that decays over ticks: a hard landing produces 2–4 ticks of degraded capability (slower reactions, reduced scramble effectiveness, ne-waza vulnerability), modified by the judoka's toughness and conditioning.

**Adrenaline masking fatigue.** DF's martial trance — where fighting multiple enemies makes a dwarf immune to pain penalties with effective skill = (skill+1)×5 — is a direct analogue to the adrenaline state in competitive judo. A judoka who's losing by waza-ari with 30 seconds left fights through fatigue that would have degraded them earlier. Model this as a **composure_state modifier** on fatigue effects: when composure is high and the tactical situation is desperate (losing on score, late in the match), fatigue thresholds shift upward. The judoka can push through grip fatigue that would have caused them to release earlier.

**Cumulative status penalties.** DF's multiplicative status stacking (stunned + dizzy = 75% skill reduction) is exactly right for judo. A judoka who is fatigued (forearms burned) AND has just absorbed a hard throw (stunned) AND is losing on score (composure eroded) should have compounding penalties, not additive ones. Each factor multiplies the others. This naturally creates the "falling apart" dynamic that makes late-match collapses feel real.

**What doesn't translate (and shouldn't):**

Blood loss, arterial damage, organ puncture, bone fracture cascades, suffocation from spine damage, permanent nerve damage within a match. Judo injuries happen, but they're modeled better as binary match-enders (injury = medical stoppage = match over) or as persistent between-match conditions (a judoka with a chronic knee injury has permanently reduced capability values on that leg across their career). Don't simulate the medical pathology within a 4-minute match. If a judoka breaks their arm in a match, that's `injury = True` and the match ends. The richness should be in the competitive dynamics, not the medical ones.

### The grip graph: what a judo-specific grapple graph looks like

This is where DF's architecture translates most powerfully. Your current `grip_configuration` dict is a simplified version of DF's grapple graph. Let me propose what a judo-specific grip graph should look like, modeled on DF's bipartite body-part-to-body-part structure.

**Nodes:** Each judoka's gripping body parts (right_hand, left_hand, right_forearm, left_forearm — and in ne-waza, legs/hooks become graspers too) and grippable targets on the opponent's gi and body (right_lapel, left_lapel, right_sleeve, left_sleeve, back_collar, right_back_gi, left_back_gi, belt, right_leg_gi, left_leg_gi — and in body-clinch situations: right_underhook, left_underhook, waist, head_control).

**Edges:** Each grip is an edge connecting one of YOUR grasping body parts to one of THEIR grippable targets, with metadata:

```python
@dataclass
class GripEdge:
    grasper: BodyPart          # e.g., right_hand
    target: GripTarget         # e.g., opponent.left_lapel
    grip_type: GripType        # STANDARD, PISTOL, CROSS, DEEP, POCKET, COLLAR
    depth: float               # 0.0 (shallow) to 1.0 (deep/dominant)
    strength: float            # current grip force, degraded by fatigue
    established_tick: int      # when this grip was set
    dominant: bool             # whether this is the dominant-side grip
```

**The grip graph IS the tactical state.** Two judoka standing with mutual sleeve-lapel grips have a graph with 4 edges (your right hand → their left lapel, your left hand → their right sleeve, their right hand → your left lapel, their left hand → your right sleeve). The asymmetry of the graph encodes the tactical situation — who has the dominant grip, who has depth, who has the controlling sleeve grip.

**State transitions on the grip graph map to judo moments:**
- `GRIP_ESTABLISH`: New edge added (Tanaka's right hand reaches for the lapel → edge created)
- `GRIP_BREAK`: Edge removed (Sato strips the sleeve grip → edge deleted)
- `GRIP_FIGHT`: Contest over an edge (both hands fighting for the same lapel → probabilistic resolution based on grip_fighter archetype, hand strength, fatigue)
- `GRIP_UPGRADE`: Edge metadata changes (shallow collar grip → deep collar grip; depth 0.3 → 0.8)
- `GRIP_SWITCH`: Grasper changes target (right hand moves from sleeve to cross-grip on opposite lapel)

**Throw attempts read from the grip graph.** A seoi-nage requires: dominant-side hand on lapel (depth ≥ 0.6), pulling hand controlling sleeve. The throw resolution system checks whether the current grip graph satisfies the throw's prerequisites, then modifies success probability based on grip depth, opponent's defensive grips, stance matchup, and fatigue. A throw attempt that fails but maintains grip shifts the graph state (both judoka now in closer range, posture disrupted). A throw attempt where the grip breaks resets to STANDING_DISTANT.

**DF's three-tier outcome system applies directly.** Every grip contest should produce one of three results: **success** (grip established/maintained as intended), **partial** (grip slips but adjusts — you wanted deep collar but got mid-lapel), **failure** (grip stripped entirely). This creates the dynamic, shifting grip battle that makes judo's tachi-waza compelling.

**Ne-waza extends the graph.** When position transitions to ground, new grasper body parts become available (legs as hooks, hips as pins) and new targets become available (opponent's turtle position exposes the back collar; opponent flat on back has exposed neck for choke). The grip graph doesn't reset — it transforms. A judoka who maintained a deep collar grip through the throw transition into ne-waza has an advantage over one whose grips broke on landing.

### The Mate window as Adventure Mode's wrestling menu

This is the most exciting design direction in the document. DF's Adventure Mode wrestling screen shows the player the grapple state explicitly — top panel displays all active holds, bottom panel shows context-dependent actions. The Mate window in Tachiwaza could work the same way: **when the referee pauses the match, the player sees the grip graph and positional state explicitly, and the available instructions are derived from that visible state.**

Here's what this could look like. When Mate is called, the Mate window displays:

**State panel (top):**
```
POSITION: GRIPPING · POSTURE: Tanaka upright / Sato slightly bent
GRIP STATE:
  Tanaka R.hand →→ DEEP COLLAR →→ Sato L.lapel (depth: 0.8, str: 7)
  Tanaka L.hand →→ SLEEVE GRIP →→ Sato R.sleeve (depth: 0.5, str: 4) ⚠️ fatiguing
  Sato R.hand →→ STANDARD →→ Tanaka L.lapel (depth: 0.4, str: 6)
  Sato L.hand →→ PISTOL →→ Tanaka R.sleeve (depth: 0.7, str: 8) ← controlling
SCORE: Tanaka 0 · Sato 0 | SHIDOS: 0-0 | TIME: 2:31 remaining
FATIGUE: Tanaka forearms 0.6 / cardio 0.4 | Sato forearms 0.3 / cardio 0.5
```

**Instruction panel (bottom) — context-dependent, filtered by grip state and fight IQ:**
The 2-word instruction taxonomy you've already designed works here, but the *available* instructions should be filtered by what's tactically relevant given the grip graph. If Tanaka has the deep collar, instructions like "ATTACK NOW" (throw attempt) and "GRIP FIGHT" (upgrade the weak sleeve grip) are prominent. If Sato's pistol grip is controlling, "BREAK GRIP" becomes urgent. The instruction list is the grip graph's transition function, filtered through the coach's perspective.

This is exactly DF's wrestling UI pattern: **state display + context-dependent action list**. The player reads the state, understands the tactical situation from the graph, and issues an instruction that maps to a state transition. The coach doesn't need to understand the simulation math — they read the grip graph like a judo coach reads the gripping situation, and they give the instruction they'd give if they were standing at matside.

The key difference from DF's Adventure Mode: the player doesn't control the judoka directly. They issue an instruction that the judoka *interprets* based on fight_iq, composure, trust, and fatigue. This is the coaching layer that makes Tachiwaza a coaching sim rather than a fighting game. The Mate window shows the state (like DF's wrestling menu) but the instruction is mediated through the judoka's reception system (unlike DF, where the player's choice is executed directly).

**Design implication:** The instructions should feel like reading from a naturally constrained menu, not like free text. The player sees the grip graph and the position state, and the available instructions emerge from those — just as DF's "Lock joint" only appears when you've already grabbed the limb. "ATTACK NOW" only appears when the grip graph supports a throw attempt. "BREAK GRIP" only appears when the opponent has a controlling grip. This makes the coaching feel responsive and informed rather than abstract.

### How DF's prose granularity maps to the sportswriter voice

DF's prose works because every element of the sentence maps to a simulation datum. Tachiwaza's prose should work the same way. Here's the translation:

**DF's template:**
```
[DESCRIPTOR ACTOR] [VERB] [TARGET] in the [BODY_PART] with [INSTRUMENT], 
[TISSUE_DAMAGE_1], [TISSUE_DAMAGE_2], and [TISSUE_DAMAGE_3]!
```

**Tachiwaza's equivalent template:**
```
[DESCRIPTOR ACTOR] [TECHNIQUE_VERB] [TARGET]'s [BODY_PART/GRIP_TARGET] — 
[ENTRY_QUALITY], [KUZUSHI_DETAIL], [LANDING_RESULT].
```

The sportswriter voice doesn't use damage verbs — it uses technique verbs and quality modifiers. Here are concrete examples, modeled on DF's sentence patterns, using the anchor scene format:

**Grip exchange (equivalent to DF's edged attack penetrating layers):**
> 0:03  Tanaka steps in. Right hand reaches for the lapel.
> 0:04  Sato's left hand intercepts — pistol grip on the sleeve. Firm.
> 0:06  Tanaka pulls against it. The grip holds. His forearms are beginning to work.

The simulation underneath: grip_establish event (Tanaka right_hand → Sato left_lapel, depth 0.3), grip_intercept event (Sato left_hand → Tanaka right_sleeve, grip_type PISTOL, depth 0.7), grip_contest event (Tanaka attempts to strip Sato's pistol grip, fails, Tanaka right_hand fatigue +0.05). Each line maps to a simulation event, the way DF's "tearing the skin, bruising the fat" maps to layer-by-layer resolution.

**Throw attempt (equivalent to DF's wrestling takedown):**
> 0:18  Tanaka loads his hips — the collar grip is deep enough. Seoi-nage.
>        → The entry is fast but Sato reads it. Hips back. Weight drops.
>        → The throw stalls. Tanaka's balance lurches forward.
>        → Sato's sprawl is clean. Brief scramble. Both hands break.
>        → Standing. Grips reset.

Simulation: throw_attempt event (throw_type SEOI_NAGE, grip_check PASS: right_hand depth 0.8 on left_lapel, left_hand on right_sleeve), throw_defense event (Sato defense_type SPRAWL, success based on fight_iq + read_skill vs. Tanaka's entry speed), throw_result STUFFED, grip_break events (Tanaka loses both edges, Sato loses both edges), position_reset to STANDING_DISTANT.

**Ground transition (equivalent to DF's wrestling → strike mode switch):**
> 0:22  Sato's osoto-gari catches Tanaka mid-step. Clean reap.
>        → Tanaka hits the mat hard. Flat on his back. Waza-ari.
>        → Sato follows down. Right hand still on the collar.
>        → Tanaka turtles immediately. Defensive posture. Protecting the neck.
>        → Ne-waza. Sato has back control, shallow hooks.

Simulation: throw_attempt event (OSOTO_GARI, success), throw_landing event (impact_severity HIGH, landing_surface BACK → score WAZA_ARI), transition_ground event (Sato maintained grip through transition: right_hand → Tanaka collar edge persists, new edges: Sato left_hook → Tanaka left_hip, Sato right_hook → Tanaka right_hip, depth SHALLOW), Tanaka defense_posture TURTLE.

**The DF lesson:** Every prose element should trace back to a simulation variable. "Clean reap" means the osoto-gari's execution score was high. "Flat on his back" means the landing_angle is directly dorsal. "Right hand still on the collar" means the grip edge persisted through the position transition. "Shallow hooks" means the ne-waza grasper edges have low depth values. The sportswriter voice isn't decoration over a generic event — it's a literary rendering of specific simulation state, the same way DF's "tearing the muscle and fracturing the bone" is a literary rendering of the material science calculation.

The announcement taxonomy for Tachiwaza should define event types analogous to DF's:

- `GRIP_ESTABLISH` / `GRIP_BREAK` / `GRIP_FIGHT` / `GRIP_UPGRADE`
- `KUZUSHI_ATTEMPT` (off-balancing)
- `THROW_ENTRY` / `THROW_EXECUTION` / `THROW_DEFENSE` / `THROW_LANDING`
- `SCRAMBLE_START` / `SCRAMBLE_RESOLUTION`
- `NEWAZA_TRANSITION` / `PIN_ATTEMPT` / `CHOKE_ATTEMPT` / `ARMBAR_ATTEMPT`
- `ESCAPE` / `TURNOVER`
- `STALL` / `PASSIVITY` (shido risk)
- `MATE_CALLED` / `INSTRUCTION_GIVEN` / `INSTRUCTION_RECEIVED`

Each event type gets a set of prose templates, and the specific simulation data fills the slots. The verb intensity scales with execution quality, just as DF's damage verbs scale with mechanical severity.

---

## Part 3: What not to build

### Tissue layers are a trap for Tachiwaza

DF needs tissue layers because weapons interact with anatomy at different depths. Judo doesn't. Adding skin → fat → muscle → bone to each of your 15 body parts would multiply your state space by 4× without producing better prose or more interesting decisions. The injury boolean is the right abstraction for within-match injury. Between matches, a richer injury model makes sense (sprained ankle → reduced right_foot capability for 3 tournaments), but that's a Ring 3+ concern. **Don't build tissue layers.**

### Material science calculations will waste months

DF's SHEAR_YIELD / IMPACT_FRACTURE math is mesmerizing but irrelevant. Judo throw resolution should be based on technique execution quality, grip prerequisites, defender reaction, and positional factors — not material science. The temptation to model impact force from throws landing on the mat (mass × height × velocity → mat compression → tissue response) will produce physics homework, not better gameplay. **Abstract throw impact into a severity rating (CLEAN / PARTIAL / BLOCKED / STUFFED) and move on.**

### Individual fingers and toes

DF models individual fingers because you can gouge an eye with a specific finger and a goblin can bite off your index finger. Tachiwaza's gripping system operates at the hand level. A judoka's grip is a whole-hand action — the biomechanics of how individual fingers wrap around the gi is real but below the resolution that produces interesting coaching decisions. Your `right_hand` and `left_hand` as atomic gripping units is correct. **Don't add fingers.**

### Nerve damage as a permanent within-match system

DF's permanent nerve damage (motor nerves never heal) creates the "supersoldier" phenomenon and long-term character evolution. In a 4-minute judo match, nerve damage is either "judoka is fine" or "match is stopped for medical." There's no mid-match state where a judoka has permanent motor nerve damage but continues fighting (except in extreme, rare cases that are better modeled as narrative events than simulation systems). **Keep nerve/sensory effects as temporary stun/fatigue states, not permanent damage.**

### Full pathfinding and spatial positioning

DF's combat includes facing, distance, charging, dodge-into-cliff-edge physics. Judo matches happen on a bounded mat with two judoka always within grappling range. Spatial position matters (center vs. edge for penalty risk, angle relative to opponent for throw direction) but doesn't need a pathfinding grid. **Model position as a few discrete zones (CENTER, EDGE, CORNER) and relative angle as a continuous variable, not a tile grid.**

### Exhaustion / blood volume tracking

DF tracks blood as a fluid with volume that depletes through wounds. Tachiwaza's cardio system (capacity + efficiency) already covers endurance. Don't add a fluid-volume tracker for anything. **Fatigue and cardio are sufficient abstractions for a sport context.**

---

## Part 4: Concrete next-step recommendations

### Before the first Claude Code session (Ring 1 additions)

**1. Expand the injury boolean into an injury state enum.**
Replace `injury: bool` with:
```python
class InjuryState(Enum):
    HEALTHY = "healthy"
    MINOR_PAIN = "minor_pain"      # can fight, slight penalty
    IMPAIRED = "impaired"          # significant function loss
    MATCH_ENDING = "match_ending"  # medical stoppage
```
This gives you DF-style graduated functional loss without tissue layers. A judoka with `right_shoulder: IMPAIRED` can still fight but throws loading that shoulder have reduced execution quality. This costs almost nothing in complexity but gives your prose engine meaningful gradations ("Tanaka's right shoulder is visibly bothering him" vs. "Tanaka is out").

**2. Add a stun/impact_recovery state with tick-based decay.**
When a judoka absorbs a hard throw or a jarring landing, add a `stun_ticks: int` to their match state. While stun_ticks > 0, all capability values are multiplied by a stun_factor (e.g., 0.5 for hard slam, 0.7 for moderate impact). Stun_ticks decays by 1 each tick. This gives you DF's "stunned" and "winded" effects without any of the underlying complexity.

**3. Define the GripEdge dataclass and replace grip_configuration dict with a proper graph.**
Model the grip graph explicitly as a list of `GripEdge` objects, each with grasper, target, grip_type, depth, and strength. This is the single highest-leverage architectural change. It enables: throw prerequisite checking (does the current grip graph satisfy seoi-nage's requirements?), grip-fight resolution (two edges contesting the same target), prose generation (every grip event maps to a specific edge creation/modification/deletion), and the Mate window state display.

**4. Add a throw_prerequisites dict to each throw in the throw vocabulary.**
Each throw should specify what grip graph state it requires:
```python
SEOI_NAGE = {
    "requires": [
        {"grasper": "dominant_hand", "target": "lapel", "min_depth": 0.6},
        {"grasper": "pull_hand", "target": "sleeve", "min_depth": 0.3}
    ],
    "stance_bonus": {"matched": 0.0, "mirrored": -0.15},
    "posture_requirement": "UPRIGHT_or_SLIGHTLY_BENT",
    ...
}
```
This directly mirrors DF's state-dependent action availability — you can only attempt seoi-nage when the grip graph supports it, just as you can only Lock a joint in DF when you've already Grabbed the limb.

**5. Define your announcement taxonomy.**
Create an enum of event types that your prose engine will handle. Start with the 15–20 most common match events. Each event type will eventually get prose templates, but defining the taxonomy now ensures the match engine generates typed events rather than raw state changes.

### For Ring 2 (Mate window and instruction system)

**6. Implement the Mate window as a state display + filtered instruction list.**
When Mate triggers, render the grip graph and position state in the coach's view. Filter the available 2-word instructions based on what the grip graph and position state make tactically relevant. This is the Adventure Mode wrestling UI pattern applied to coaching.

**7. Add instruction-to-grip-transition mapping.**
Each instruction should map to intended grip graph transitions: "BREAK GRIP" → attempt to delete the opponent's highest-depth controlling edge. "ATTACK NOW" → check if grip graph satisfies any throw prerequisites, attempt the highest-probability throw. "GRIP FIGHT" → attempt to upgrade the lowest-depth friendly edge. This makes instructions mechanically meaningful rather than flavor text.

### For Ring 3+ (defer these)

**8. Between-match injury persistence.** InjuryState that carries from match to match, with recovery timelines. A sprained ankle in the quarterfinal that degrades capability in the semifinal.

**9. Psychological momentum as a state variable.** DF's martial trance mechanic — where extreme situations enhance capability — mapped to judo momentum. A judoka who just scored waza-ari gets a brief capability boost (confidence surge). One who just gave up waza-ari gets a composure penalty that the coach can address through the Mate window.

**10. The ne-waza grip graph extension.** Ground work introduces new graspers (hooks, hips) and new targets (turtle back, guard position). This is a full system expansion of the grip graph and should be designed and built as its own Ring after standing grip exchange is solid.

The final word comes from Tarn himself, and it should guide your entire design process: *"Our design process involved writing stories that we'd like the game to produce, in the same way you might draw several example maps while designing a map generator."* Write ten more anchor scenes like the one you already have. Every scene that reads well and feels like judo will point you toward what the simulation needs to produce. Build only what the prose demands.