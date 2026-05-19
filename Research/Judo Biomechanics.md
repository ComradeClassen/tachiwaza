# Kuzushi, Couples, and Levers: A Biomechanics Reference for a Judo Simulation

## 1. Executive summary

**The classical Kodokan model of happo-no-kuzushi is didactic, not physical.** Modern biomechanics — principally Attilio Sacripanti's theoretical framework (arXiv, 2008–2024) plus empirical work by Imamura, Ishii, Liu, Matsumoto (Kodokan 1978), Blais/Trilles, and others — unanimously treats the "eight directions" as a pedagogical partition of a continuous 2D (really 3D, including vertical unweighting and rotation about the vertical axis) vector field. No empirical study has ever identified eight statistically preferred "attractor" directions for uke's center of mass. For a simulation, kuzushi should be a continuous vector applied in uke's body frame; happo-no-kuzushi is useful only as a UI/commentary bucketing layer.

**Throws split cleanly into two biomechanical classes — Sacripanti's Couple vs. Physical Lever — and this is the single most useful abstraction for a simulation.** Couple-of-forces throws (O-soto-gari, Uchi-mata, O-uchi-gari, Ko-uchi-gari, Harai-goshi in its competitive form) rotate uke about uke's own CoM via a pure torque and can fire *without* classical kuzushi, exploiting uke's existing motion instead. Lever throws (O-goshi, Seoi-nage, Tai-otoshi, O-guruma, Tomoe-nage) establish a fulcrum on tori's body (hip, shoulder, shin, foot-on-belt) and require uke's CoM to be positioned over the fulcrum *before* the throw can fire — kuzushi is mandatory. This distinction directly dictates different commit-rules, different counter-vulnerabilities, and different energy costs in the physics substrate.

**The tsukuri–kuzushi–kake sequence does not exist as three discrete mechanical phases.** Matsumoto et al. (Kodokan Report V, 1978) established using force plates + EMG that the three phases overlap temporally in skilled performance and cannot be separated; every subsequent empirical study has confirmed this. Sacripanti reformulates the sequence as overlapping "General Action Invariants" (distance-closing, whole-body motion — universal to all throws) and "Specific Action Invariants" (kinetic-chain pose — required only by Lever throws). Novice and resisted execution show de-overlapped, pulse-like phases; elite and unopposed execution show tight compression into a single continuous action.

**Empirical force data is scarce, small-sample, and concentrated on five throws.** The best-documented throws are O-soto-gari (Imamura & Johnson 2003; Liu et al. 2021, 2022, 2025), Harai-goshi (Imamura 2006/2007; Pucsok 2001; Harter & Bates 1985), Seoi-nage (Blais & Trilles 2004, 2007; Ishii 2016–2019; Imamura 2006), and Uchi-mata (Hamaguchi 2025; Brito 2025; Hashimoto 1984). O-goshi, O-guruma, Ko-uchi-gari, Tai-otoshi, and Tomoe-nage have essentially no instrumented force-measurement literature; parameters for these must be inferred from analogues and flagged as such. Typical sample sizes are n = 1–22, often with a single non-resisting uke. Competitive-condition data exists only for Harai-goshi (Imamura 2007) and osoto-gari (Jagić 2005, showing ~19% faster execution and roughly 2× supporting-foot velocity vs. uchikomi).

**For simulation design the load-bearing insights are:** (1) model posture as continuous trunk-lean angles plus a base-of-support polygon — not as discrete shizentai/jigotai states; (2) implement grips as constrained force-couplings with distinct moment arms (sleeve ≈ arm-rotation control, lapel/collar ≈ vertical + trunk-rotation transmission, belt ≈ direct CoM moment, pistol ≈ mutual-immobilization); (3) treat kake as an off-center inelastic collision producing both a translational impulse and a couple on uke; (4) compute a continuous "commit scalar" based on delivered angular/linear impulse relative to retractable momentum, with three counter-windows (sen-sen / sen / go) mapped to specific dyad state regions; (5) when a throw fails, do not simply abort — transition tori into a compromised state (extended single-support, trunk flexion beyond nominal, CoM near or outside own base) that is the physical basis for kaeshi-waza.

---

## 2. Happo-no-kuzushi foundation

### 2.1 Kano's formulation and the canonical eight directions

Kano's definition in *Kodokan Judo* (Kodansha 1986): "To use strength most efficiently, it is vital to break the opponent's balance. In line with the principle of dynamics, he is then vulnerable and can be brought down with a minimum of effort. Breaking an opponent's balance is called *kuzushi*. With reference to the basic natural posture, it has eight forms as illustrated. The basis of *kuzushi* is pushing and pulling, which are done with the whole body, not just the arms... *Kuzushi* can be done in either straight or curved lines and in every direction." Kano explicitly generalized the classical *Roppo-no-Kuzushi* (six directions) of Tenjin Shin'yō-ryū jūjutsu into *Happo-no-Kuzushi* by adding the pure-lateral right and left directions.

The Kodokan-standard names, per the *Kodokan New Japanese-English Dictionary of Judo* (Kawamura & Daigo eds. 2000) and Daigo's *Kodokan Judo Throwing Techniques* (2005), are:

| # | Direction | Japanese |
|---|-----------|----------|
| 1 | Front | mae (真前) |
| 2 | Rear | ushiro (真後) |
| 3 | Right (side) | migi |
| 4 | Left (side) | hidari |
| 5 | Right-front corner | migi-mae-sumi |
| 6 | Left-front corner | hidari-mae-sumi |
| 7 | Right-rear corner | migi-ushiro-sumi |
| 8 | Left-rear corner | hidari-ushiro-sumi |

**The eight arrows are drawn at uniform 45° spacing in a plane parallel to the tatami**, with uke at the center in shizen-hontai. The reference frame is uke's own body axes (so "mae" is whichever way uke is facing), and the diagram is strictly 2D — it contains no vertical component. De Crée (2014, *Revista de Artes Marciales Asiáticas* 9(2)) emphasizes that "even to this day, the Kodokan does not elaborate much on kuzushi beyond Happo-no-Kuzushi's two-dimensional vectorial plane." Kudo's *Dynamic Judo* (1967) extends to 14 directions (*Jushiho-no-Kuzushi*); this is not Kodokan orthodoxy.

### 2.2 Biomechanical validity — **the eight-direction model has no empirical support as a physical discretization**

Sacripanti (2012, arXiv:1206.1135) states the consensus position directly: "The number of unbalance directions is... 'an infinity of the power of continuum.' The Happō-no-kuzushi directional principle is therefore only satisfactory on the condition that each of the eight fundamental and straight directions... is considered as 'representative vector' of a group... We must therefore approach Happō-no-kuzushi as a didactic example depicting what is essentially an 'innumerable' number of horizontal straight directions of unbalance now divided into eight classes."

**Empirical evidence for continuous kuzushi vectors:**

- **Imamura, Hreljac, Escamilla & Edwards (2006, *J Sports Sci Med* 5(CSSI):122–131).** n = 4 black-belt tori, 1 uke, 60 Hz 3D video, three throws. Uke's CoM momentum during kuzushi for harai-goshi was +20.6 (kg·m)/s forward, weakly upward, and −8.9 (kg·m)/s mediolateral *away* from tori's pulling hand — i.e., not cleanly aligned with any of the eight nominal directions. Seoi-nage: +24.5 forward, upward, −11.3 mediolateral. Osoto-gari: initially slight forward, upward, *toward* tori's pulling hand (not "rear" as the nominal label predicts).
- **Kim Eui-Hwan et al. (2006/07, *Korean J Applied Biomechanics*).** Vicon 7-camera + two AMTI force plates, n=1 tori. Successful kuzushi produces GRF asymmetry ratios from ~1:1 up to ~100:1 for lateral lean, near-total unweighting of the off-side foot (down to ~1% BW), trunk inclinations of 10–15°, and CoM horizontal displacement 26.5–39.9 cm — all continuous scalars.
- **Matsumoto et al. (1978, Kodokan Report V).** Force-platform + EMG showed that kuzushi/tsukuri/kake are temporally inseparable muscle events.
- **Blais & Trilles (2004, *Science & Motricité* 51).** Five French-Federation seoi-nage experts produced substantially different force-vector directions; no clustering near eight attractors.
- **Hassmann et al. (2010, *Procedia Engineering* 2(2)).** A pulling-force device showed ~45° above horizontal as the optimal single pull angle, again a continuous optimum.

**Alternative models in the literature.** Kudo's 14-direction extension; Hirano Tokio's "wave" rotational kuzushi (De Crée 2014); Neil Adams's two-axis horizontal-vertical "balance lines" model; Sacripanti's dynamic unbalance framework that adds vertical and rotational components and replaces the static "CoM outside base polygon" test with a dynamic "CoM outside recoverable-step region" test. All of these converge on the same conclusion: the direction space is continuous and at minimum 2D, ideally 3D with a rotational component.

### 2.3 How kuzushi is mechanically produced

Four mechanisms operate concurrently, not sequentially:

1. **CoM displacement outside the base-of-support polygon** (the rigid-body classical model, implicit in Kano). Sacripanti argues this is insufficient because the human body is articulated — a *dynamic* criterion (CoM velocity vector directed outside the recoverable region) is correct.
2. **Grip-transmitted forces forming a force-couple on uke's upper body.** Hikite (pull) + tsurite (lift/steer) create both a net translation and a torque about uke's vertical axis. Ishii et al. (2019, ISBS) showed via sensor-judogi that elite judoka direct tsurite force along the nominal throwing axis via internal shoulder rotation.
3. **Tori's whole-body kinetic chain driven by ground reaction force.** Imamura (2006, 2007) shows uke's peak forward momentum occurs just after tori's pivot-foot touchdown, implicating GRF → leg → trunk → arm transmission as the source of most of the force. Yabune (1994) and Pucsok et al. (2001) confirm higher supporting-foot GRF in advanced judoka.
4. **Dynamic exploitation of uke's existing motion.** Sacripanti (2010, arXiv:1010.2658) argues that for Couple throws, classical kuzushi is often absent in competition: tori catches uke's step/reaction and applies the couple on the fly (*hando-no-kuzushi*).

**Relative contributions:** the Kodokan pedagogical model (Kano, Daigo) treats grip-driven kuzushi as primary. The biomechanical consensus (Matsumoto 1978, Imamura, Sacripanti) treats GRF-driven kinetic-chain force as primary, with grips as the coupling interface.

### 2.4 Measurable success criteria for kuzushi

A defensible composite predicate based on the literature combines four measurements:

- **Horizontal CoM projection leaving the dynamic recoverable-step region** (supersedes the static base polygon; Sacripanti 2012).
- **Vertical GRF drops below ~10–20% body weight on at least one foot** (Kim et al.; near-complete unweighting at extreme lateral kuzushi).
- **Trunk inclination exceeds ~10°–15° from vertical** (Kim et al.).
- **Uke's CoM acquires momentum that cannot be neutralized within one reaction-time window (~200–300 ms).**

Typical magnitudes during successful kuzushi: uke CoM horizontal displacement 26–40 cm (Kim); total impulse applied to uke during tsukuri+kake 89–113 N·s across three major throws (Imamura 2006); tori supporting-foot horizontal GRF ~1200 N (novice) to ~1800 N (advanced) in harai-goshi (Pucsok 2001); tori trunk angular velocity peaks 200–365 deg/s in successful harai-goshi (Imamura 2007); tori forward CoM velocity 2.74 ± 0.33 m/s (elite) vs. 1.62 ± 0.47 m/s (college) in seoi-nage turning phase (Ishii 2018).

---

## 3. Ten-throw biomechanics catalog

### 3.1 O-goshi (大腰, major hip throw)

**A. Kuzushi direction.** Mae or migi-mae-sumi (right-front corner) for a right-sided throw. Uke is lifted onto the balls of both feet — the vertical component is prominent because tori's hip sits *below* uke's CoG. Canonical Nage-no-Kata uses pure mae; competitive default is migi-mae-sumi.

**B. Force application.** Defining grip is a *belt/lower-back wrap* — tori's right arm wraps uke's waist, not the lapel (this is the textual signature distinguishing O-goshi from Tsurikomi-goshi and Uki-goshi). Left hikite pulls the sleeve diagonally forward-down. Tori pivots 180°, drives right hip *below* uke's belt line, bends knees on entry (load), then extends bilaterally (power stroke = partial deadlift). **Lever mechanics: first-class lever with fulcrum at tori's sacrum/hip-crest**, moment arm equal to uke's torso length above the fulcrum. Sacripanti's classification: *Physical Lever, minimum arm* — energetically the most expensive hip throw. Kinetic chain: bilateral floor push-off → pelvis/hip rotation → torso → arms. **No published force-plate study of O-goshi exists** (Imamura, Pucsok, Harter, and Sacripanti all treat harai-goshi, uchi-mata, seoi-nage, osoto-gari; O-goshi is typically excluded as "foundational/training only").

**C. Body parts.** Tori: **both feet** load-bearing during lift (distinguishes O-goshi from single-support throws), right hip-crest/sacrum is contact surface, lumbar extensors + glutes + quadriceps do the lift, right arm around uke's waist carries shear, left arm on sleeve provides rotation torque. Grip: **belt wrap (tsurite) + sleeve (hikite)** — not standard sleeve-lapel. Uke: lumbar region contacts tori's hip, both legs fully lifted off ground, rotates around sagittal axis of tori's hip. **No leg-to-leg contact** — a defining feature.

**D. Posture state.** Optimal: shizentai, upright. Fails against jigotai (tori cannot slide hip under a low CoG) and against heel-weighted uke. Tsukuri: pull uke onto balls of feet via hikite; against a defensive uke, a forward-step-inducing feint is typical.

### 3.2 Harai-goshi (払腰, sweeping hip throw)

**A. Kuzushi direction.** Migi-mae-sumi. Imamura 2007 competitive data confirms: uke CoM moves forward throughout kuzushi/tsukuri, with mediolateral displacement *toward tori's pulling hand* as the ideal pre-movement.

**B. Force application.** Tsurite grips lapel/collarbone and lifts upward-outward. Hikite grips sleeve at elbow and pulls forward-down with a winding elbow action — this combination is a rotational couple driving uke forward over tori's right hip. Tori pivots 180° (mawari-komi), plants **left foot as single support**, and the right leg becomes the sweeping leg — back of right thigh sweeps upward-backward against back of uke's right thigh (ideal contact low, near knee). **Lever mechanics:** Sacripanti *Physical Lever, medium arm* — fulcrum at tori's right hip-crest, effective moment arm extends to the sweep contact point on uke's leg. Imamura 2007 (n=1): tori shows a signature CCW-then-CW trunk-angular-velocity reversal (stretch-shortening cycle) with competitive peaks of 365 deg/s CCW and 266 deg/s CW (vs. 105 and 183 in nage-komi). Pucsok 2001 (n=28): supporting-foot horizontal GRF ~1800 N advanced vs ~1200 N novice, significantly correlated with sweeping-leg horizontal velocity. Harter & Bates (1985): tri-modal *pull-push-pull* AP GRF pattern. Total impulse on uke 100.1 N·s (Imamura 2006). Kinetic chain: support-leg GRF → pelvis CCW → trunk CW snap → sweep-leg whip → arms.

**C. Body parts.** Tori: **single support on left foot/ankle**, right hip as fulcrum, back of right thigh as sweeping tool, core/obliques for rotation, right arm for lift, left arm for pull. Grip: standard sleeve-lapel; competitive variants often use high-lapel/collar. Uke: right hip displaced over tori's hip; back of right thigh swept; trunk rotated around tori's sagittal axis. Leg-to-leg: tori's posterior right thigh → posterior uke right thigh, low (knee-level).

**D. Posture state.** Shizentai or slightly forward-leaning. Fails in jigotai: Imamura 2007 shows uke defensively drops into jigotai, forcing tori to generate 3–4× higher trunk angular velocity to overcome the resistance. Tsukuri: lateral movement *toward tori's pulling hand* is the ideal precursor.

### 3.3 O-guruma (大車, major wheel)

**A. Kuzushi direction.** Migi-mae-sumi. Same nominal direction as harai-goshi but with more circular/rotational pull and less downward lift.

**B. Force application.** Hikite on uke's sleeve at *armpit* (higher than harai-goshi's elbow grip); tsurite on side of collar. Kodokan emphasizes: **tori must NOT drive hips deep** — there is more space between the torsos than in harai-goshi. Tori swings the right leg around from the front, striking uke's weight-supporting leg **high — upper thigh / hip crease / lower abdomen**. The attacking leg is held **extended and rigid, toes off floor, no upward sweep** — it acts as a static blocking axle. Uke rotates over the bar like a wheel. **Lever mechanics:** Sacripanti *Physical Lever, maximum arm* — fulcrum at tori's extended leg (hip-line against uke), moment arm effectively uke's full body length above the bar. Mechanically more efficient per unit force than harai-goshi but requires greater placement precision. **No peer-reviewed kinetic study of O-guruma exists.** Kinetic chain: floor push-off → hip turn → trunk rotation drives the blocking leg across → arms wheel uke over the leg-bar.

**C. Body parts.** Tori: **left foot single support**, right leg extended as static bar (quadriceps isometric/eccentric), core/obliques rotate trunk, arms wheel uke. Grip: sleeve-at-armpit (hikite) + side of collar (tsurite). Leg-to-leg: tori's right leg (posterior/medial thigh or posterior knee) strikes uke's right leg between upper thigh and lower abdomen — contact HIGH (hip-line), not sweeping.

**D. Posture state.** Shizentai advancing forward — O-guruma works best when uke is stepping forward and the blocking leg catches the advancing weighted leg. Fails against jigotai (cannot be wheeled over a high bar) and if tori drives hips too deep (converts to harai-goshi or collapses).

### 3.4 O-uchi-gari (大内刈, major inner reap)

**A. Kuzushi direction.** For standard right ai-yotsu, tori reaps uke's *left* leg → kuzushi to uke's **rear-left corner (ushiro-hidari)**. (General rule: kuzushi corner = same side as uke's reaped leg, on uke's rear.) Modern drive-style variants push more straight-back (ma-ushiro) with chest pressure. Weight must be on the leg to be reaped.

**B. Force application.** Tori steps right foot deep between uke's legs. Right reaping leg hooks behind uke's left knee/calf from the inside, sweeping outward-forward or hooking rearward. Supporting left leg drives hip forward into uke. Lapel hand drives forward-down to push uke's torso back; sleeve hand pulls uke's right arm out. **Sacripanti classification: Couple in the transverse plane** — arms push uke's torso back while foot sweeps support leg forward; torque about uke's vertical axis. **Literature is thin:** no kinematic study of reaping velocity, GRF, or joint moments. Collateral head-impact data (Murayama 2020): impulsive force on uke's head 118.46 ± 63.62 kg·m·s⁻¹ — lower than osoto-gari (204.82) but head impact more vertical because uke falls straight down.

**C. Body parts.** Tori: right leg reaps (calf / back of knee), left leg supports and drives hip forward. Grip: standard right ai-yotsu. Leg-to-leg: tori's right leg hooks *inside* uke's left leg from behind the knee/calf; tori's right foot/instep often crosses behind uke's left ankle. Uke's left leg reaped; trunk rotates backward; head falls near-vertically.

**D. Posture state.** Uke retreating with weight loading onto the rear-left foot is ideal. LV Shaolin coaching rule: "you want weight on the foot you are trying to sweep — 70% weighted, then go." Classic tsukuri: threaten a forward throw → uke braces/steps back → reap the loaded rear leg. Fails against upright/even-weighted uke (just pushes without throwing) and against forward-shifting uke (exposes ouchi-gaeshi counter).

### 3.5 Ko-uchi-gari (小内刈, minor inner reap)

**A. Kuzushi direction.** For right-sided ko-uchi-gari (tori reaps uke's *right* foot), kuzushi goes to uke's **rear-right corner (ushiro-migi)**. Note: ko-uchi reaps the same-side foot; o-uchi reaps the opposite-side leg. Pull-style and barai variants can shift toward straight back or even slightly forward (sweeping uke's heel toward uke's opposite toe). The Japanese Kodokan makes no distinction between *gari* (foot planted) and *barai* (foot in motion); some European systems do.

**B. Force application.** Tori's right foot sweeps uke's right ankle/heel from the inside, using **sole or instep** against inner-back of uke's heel/ankle. Lowest contact point of the three ashi-waza. Lapel hand drives forward into uke's near shoulder; sleeve pulls slightly upward-forward; hips drive forward into uke. **Sacripanti: Couple applied by Arm(s) and Leg**, transversal-plane force pair about uke's vertical axis. De Crée & Edmonds (2012, *Comprehensive Psychology* 1:1) is the sole peer-reviewed biomechanical paper — qualitative, no kinematic measurements. **No published GRF or sweeping-foot velocity data.** Numerical parameters must be scaled down from osoto-gari analogues to reflect (a) smaller contact area, (b) faster/smaller arc execution, (c) lower required arm force (Sacripanti: grips for Couple-class throws transmit less force than for Lever-class).

**C. Body parts.** Tori: right foot (sole/instep) reaps, left leg supports (may hop in competitive form). Grip: standard right ai-yotsu. Leg-to-leg: tori's right foot reaps uke's right foot/ankle from inside; tori's leg goes between uke's legs at low height. Uke's right ankle swept; fall is approximately vertical (a "soft" fall).

**D. Posture state.** Uke's right foot loaded AND in motion/just planting. Best moments: (1) as uke steps forward onto right foot (time the catch as it lands); (2) when uke's feet are on the same horizontal line after retreating from a forward feint; (3) as follow-up after a failed/feinted o-soto-gari. Most timing-sensitive of all three ashi-waza — reap window is a fraction of one step cycle. Sacripanti (2019, arXiv:1907.01220): in modern competition, ko-waza are increasingly applied *without classical kuzushi*, exploiting existing motion (hando-no-kuzushi) — this is the Couple-class signature.

### 3.6 Seoi-nage (背負投, shoulder throw)

**A. Kuzushi direction.** Mae or migi-mae-sumi for right-handed. **Ippon-seoi** tends to pure mae (the single-arm armpit lever rotates uke directly over the shoulder). **Morote-seoi** may use more migi-mae-sumi. Imamura 2006 confirms uke's CoM momentum is forward, weakly upward, and drifts toward the pulling hand in kake. Sannohe 1986: optimal lapel pull ~10° above horizontal.

**B. Force application.** **Hikite pulls sleeve forward-down across tori's body.** **Tsurite: Ishii et al. 2019 sensor-judogi study showed elite/pain-free athletes apply force in the throwing direction via internal shoulder rotation; injured athletes externally rotate and misalign the vector (this is the mechanical origin of elbow overuse in seoi-nage).** Ippon-seoi replaces tsurite with an arm hooked under uke's armpit, clamping uke's arm against tori's chest/shoulder as the lever. Tori's back/shoulder is the **fulcrum** — Sacripanti *Physical Lever*. Kinetic chain (Blais, Trilles, Lacouture 2007, *J Sports Sciences* 25(11), n=16): **lower limbs dominate** — knee 24% ± 4, hip 29% ± 3, trunk 28% ± 3, upper limbs only ~19% of total driving moment. Total energy ~880 ± 160 J per throw, peaking in tsukuri (~60%). Total attack duration ~1.14 s. Ishii 2018 (n=3 elite, 7 college): elite tori CoM forward velocity in turning phase 2.74 ± 0.33 m/s vs. 1.62 ± 0.47 m/s college (p=0.023). Imamura 2006: average force on uke 120.4 N over 0.74 s → impulse 89.0 ± 18.8 N·s — the *smallest* collision force of the three throws studied (harai-goshi 100.1 N·s, osoto-gari 113.0 N·s), because seoi-nage maintains forward momentum rather than dumping it into a collision. Uke shoulder impact (Soldin 2022, n=8): peak velocity 4.5 ± 0.6 m/s, acceleration 67.9 ± 9.9 m/s². Gutiérrez-Santiago et al. 2013 (n=46): the #1 technical error is insufficient knee bend → uke is thrown around the side rather than over the front of the shoulder.

**C. Body parts.** Tori: both feet (GRF), ankles, knees (flexion/extension), hips, trunk, both shoulders, both arms. **Morote:** upper back + right shoulder + right upper arm as load surface; both arms grip. **Ippon:** right shoulder + locked right arm only; one arm grips sleeve. Uke: hikite-controlled arm and collar/chest (morote) or clamped armpit (ippon); CoM lifted and rotated forward-over-shoulder; shoulder-first landing.

**D. Posture state.** Upright or slightly forward, weight coming onto balls of feet. **Tori's hips MUST be below uke's hips** — universal constraint, confirmed by Gutiérrez-Santiago as primary failure mode. Fails if uke leans back (cannot be loaded), squared-up heavy (lower-limb extension insufficient), heel-weighted (lift fails), or if tori stays too upright during kake (uke slides off side).

### 3.7 Uchi-mata (内股, inner thigh throw)

**A. Kuzushi direction.** Mae or migi-mae-sumi. Canonical Kodokan kuzushi is diagonally forward with a circular/rotational drag pulling uke onto toes (tsurite to uke's ear height, hikite to tori's eye height — both up-and-forward). Competitive variants with taller opponents shift toward straight mae.

**B. Force application.** Tsurite lifts upward (to above uke's ear, per Kodokan); hikite rotates wrist palm-out, pulls forward-up. Together they form a **couple of forces** that rotates uke forward around the frontal axis — Sacripanti's defining description. Tori pivots, ends in right hanmi with single-leg support on **left leg**. Right leg swings between uke's legs; back of right thigh reaps **medial inner** thigh of uke's far (left) leg in the canonical Daigo form; competitive koshi-uchi-mata contacts the near leg. **Sacripanti classification: Couple of forces applied by trunk and leg — theoretically friction-independent, energetically the cheapest throw family (~4.2 kJ vs. higher for Lever throws).** No fulcrum in the strict sense; rotation is about uke's own CoM. Rich empirical literature: **Hamaguchi et al. 2025, *Sports Biomechanics* 24(9), n=20 (10 skilled/10 less skilled), Mac3D 250 Hz** — peak CoM velocity (AP and vertical), hip angular velocity, shoulder angular velocity, and uke angular momentum all significantly greater in skilled; kinetic chain proceeds **lower-limb → upper-limb**; head-forward-tilt angle at max sweeping-leg height predicts sweep-leg velocity (adj R² = 0.53, p = 0.009). **Brito et al. 2025, *J Funct Morphol Kinesiol* 10(4):378, n=40 elite**: specialists 2× faster than non-specialists in approach and throw phases, with deeper support-leg squat (hip 61.9 vs 75.6 cm) and higher knee/foot (98.5 vs 86.3 / 121.0 vs 104.4 cm) in final position. GRF during judo throw execution exceeds 2000 N (Ren et al., cited therein). **Kwon, Cho & Kim 2005:** CoG height at kuzushi = 71 cm (type A kumi-kata) vs 73.8 cm (type B); no mediolateral CoG differences by grip type at that phase.

**C. Body parts.** Tori: **left foot single support** (ankle/knee/hip take tori's + uke's weight), right leg is reaping tool (posterior thigh), core/obliques produce trunk rotation, left arm lifts, right arm produces rotational couple. Grips: canonical standard sleeve-lapel; competitive variants include high collar, ogoshi (belt-wrap), cross-grip, armpit/triceps grip, reverse grip (Kosei Inoue family tree). Uke: inner thigh of reaped leg (canonically far leg, variants near leg); hip rotated over tori's right hip; trunk rotated forward; head/shoulders fall forward-down.

**D. Posture state.** Shizentai essential — uke must be upright for the reaping leg to reach under the CoG, with weight coming onto toes. Fails against jigotai (reap hits outside or misses; exposes **uchi-mata-sukashi** counter — Kodokan shinmeisho no waza 1989). Tsukuri: classic Nage-no-Kata draws uke in a large circular motion forcing widened stance rising onto toes; at the moment uke's stance widens with weight loaded on right foot and left leg about to step, the raised left inner thigh is exposed.

### 3.8 O-soto-gari (大外刈, major outer reap)

**A. Kuzushi direction.** Ushiro-migi (right-back corner) for a right-sided throw. Daigo (2016): weight must be on the **heel** of the leg to be reaped — not flat-footed, because "friction... will prevent tori from executing the reap in one stroke." Imamura 2006 shows black belts actually *pull uke forward first* (loading the lead leg) then drive back at kake, so the kuzushi vector is dynamic, not a pure backward pull.

**B. Force application.** **Sacripanti: Couple of forces, specifically trunk-to-calf** — not a lever. Two equal opposing forces: chest push backward (F1, delivered via trunk forward-tilt collision) + reaping-leg sweep forward-up of uke's leg (F2); resultant = pure torque about uke's CoM. Tori's right leg sweeps backward-upward with plantar-flexed ankle ("toes pointed"), contacting back of uke's right thigh/calf. Pivot leg = tori's left, planted alongside uke's right foot. **Quantified extensively:**

- Imamura & Johnson (2003, *Sports Biomech* 2(2):191–201, n=20): black belts differ from novices in exactly two variables — peak trunk angular velocity and peak ankle plantar-flexion angular velocity of sweeping leg.
- Liu et al. (2021, *Sports Biomech* 23(11):2021–2033, n=22, Mac3D 250 Hz): black belts have greater peak angular momentum of uke's trunk/leg; greater arm and trunk-twist angular velocity; time peak upper-body rotation closer to sweep contact.
- Liu et al. (2022, n=15 BB, force plates 1000 Hz): sweeping-leg velocity correlates with peak upward GRF of sweeping leg (r = −0.693), pivot-leg knee extension moment (r = 0.602), pivot-leg knee power (r = −0.618) — **pivot-leg knee extensors drive the whole-body rotation that accelerates the sweeping leg**.
- Liu et al. (2025, *PeerJ* 13:e18862): head-tilt and trunk-tilt kinematics explain 53% of sweeping-leg velocity variance (p = 0.009).
- Jagić et al. 2005: competitive execution ~1.05 s, ~19% faster than teaching; supporting-foot velocity roughly doubles under competition.

Kinetic chain: pivot-foot GRF → pivot-leg knee extension → pelvic/trunk forward rotation → upper-torso/arm angular velocity → sweeping-leg whip → ankle plantar flexion at impact ("whip crack").

**C. Body parts.** Tori: right (reaping) leg — thigh or calf per Daigo variant (52% of IJF-reviewed instances are calf-to-calf); left (pivot) leg, planted lateral to uke's right foot, knee-extensors generate rotational moment; trunk forward-tilt + twist; both arms. Grip: right on uke's left lapel (collar), left on uke's right sleeve; standard right ai-yotsu. Leg-to-leg: tori's right leg contacts uke's right leg from behind/outside. Uke: right leg reaped; trunk rotated backward by chest push; head accelerates downward — Murayama 2020 measured peak impulsive force on uke's head 204.82 ± 19.95 kg·m·s⁻¹ (highest of common throws — concussion risk).

**D. Posture state.** Optimal: uke upright or slightly extended backward, **weight on the heel of the leg to be reaped**. Commonly occurs when uke is stepping forward onto that leg, defensively leaning back, or pulling against tori's pull. Flat-footed → friction defeats reap. Forward-leaning uke → couple cannot rotate backward (tori often switches to harai-goshi). Tsukuri: Imamura's CoM data show black belts first pull uke forward (hando-no-kuzushi — pre-kuzushi loading) then drive back; threat of forward throw elicits backward brace that loads the heel.

### 3.9 Tai-otoshi (体落, body drop)

**A. Kuzushi direction.** Migi-mae-sumi (right-front corner) — universal across Daigo, Jimmy Pedro, Kashiwazaki, Koga tradition.

**B. Force application.** **Critical: tai-otoshi is rotational, NOT a lift.** Sacripanti classifies as *Physical Lever* where the blocking leg is the fulcrum; uke rotates around it via the force couple applied through the hands. Hikite (sleeve) pulls forward-downward across tori's body. Tsurite (lapel/collar) **pushes** forward — this is distinct from seoi-nage where tsurite lifts. Pedro: "The right hand... is used to push and the sleeve hand is used to pull." Tori steps right foot past outside of uke's right foot, pivots so back faces uke, extends right leg as a **barrier across uke's right shin/ankle**. **Tori's hips stay roughly level with uke's hips** — no vertical lift. Blocking leg must be across uke's **shin**, not thigh, for mechanical leverage. Soldin et al. 2022 (Applied Sciences 12(7):3613, n=8 BB, Kinovea 2D): uke shoulder peak velocity **5.1 ± 0.8 m/s** — significantly greater than morote-seoi 4.5 ± 0.6 m/s (p=0.030); peak acceleration 71.6 ± 12.4 m/s². Interpretation: tai-otoshi's short moment arm (shin-to-shoulder) and rapid rotation drive the shoulder into the mat harder than seoi-nage despite lower overall throw energy. **No joint-kinetics study exists** comparable to Blais 2007 for seoi-nage; Gomes et al. 2026 (BJMB, n=32 children) confirmed that tai-otoshi learning uniquely depends on live kuzushi practice.

**C. Body parts.** Tori: right leg extended (nearly straight knee, can flex-then-extend at contact for extra drive per Pedro); left leg = pivot foot bearing tori's weight; hips rotating; torso sharp left rotation; both arms couple; both hands grip sleeve + lapel. Contact with uke: right shin against uke's right shin only — **no back/shoulder loading**. Uke: right shin (barrier contact), both arms (grip-controlled), upper torso rotated. Landing: shoulder-first impact is the defining loading pattern.

**D. Posture state.** Uke stepping forward with weight transferring onto the leg that will be blocked. Failure modes: upright/weight-back uke → no forward rotation, tori's leg becomes self-trip risk; weight not on blocked foot → no fulcrum contact; tori bends at waist too early → loses postural power; blocking leg on thigh rather than shin → no leverage, converts to weak hip-check. Tsukuri: commonly set up with a feinted right-ouchi-gari that provokes uke to step back with right foot, then tai-otoshi executes as weight re-loads onto that forward-advancing right foot.

### 3.10 Tomoe-nage (巴投, circle/sacrifice throw)

**A. Kuzushi direction.** Mae or mae-migi. Nage-no-Kata form: tori first pushes uke backward; uke reacts by stepping forward; at that moment tori drops under. The kuzushi *exploits uke's forward reaction* (hando-no-kuzushi).

**B. Force application.** **This throw maximally tests the classical kuzushi model.** Unlike standing throws, tori **sacrifices his own balance simultaneously** — tori's voluntary backward fall IS part of the kuzushi action. Sacripanti's "advanced kuzushi" concept (arXiv:1010.2658) explicitly covers this case: kuzushi, tsukuri, and kake collapse into a single continuous event. Mechanics: both hands pull uke forward-down while tori drops. Left foot plants deep between uke's feet; buttocks to planted foot; tori drops onto back. Right foot places on uke's **lower abdomen, pelvis, or belt knot** — not on chest (ineffective) and not on thigh (fails). Tori's back contacts mat; right leg extends explosively at knee + hip; combined with continuous arm pull, uke rotates head-over-heels in arc. **Foot-on-belt is the pivot/fulcrum** → *Physical Lever with fulcrum at foot-on-belt*. Ground contact provides the Newton's-third-law reaction needed for leg extension to push uke's full body mass upward. **No peer-reviewed biomechanics data exist for tomoe-nage.** All claims derive from first-principles physics and coaching sources (Kashiwazaki 1992 Ippon Books Masterclass, Kano 1986, Mifune, Daigo). Inference from physics: high vertical impulse (leg push), high angular momentum about foot-fulcrum.

**C. Body parts.** Tori: both hands (grips high on uke's collar/lapels, or collar+sleeve), both arms (continuous pull), core (C-curve to roll), **right leg (primary force generator, knee + hip extension)**, left leg (plant, pivot for tori's fall), back (mat contact), head (tucked). Uke: lower abdomen/belt (foot contact — soft tissue/pelvis), both arms (grip-controlled), upper torso (pulled forward-down). Uke rotates around foot fulcrum and lands on upper back/shoulders after 180°+ arc.

**D. Posture state.** Uke upright or leaning/pushing forward — both work. Fails catastrophically against leaning-back uke (will not rotate; tori ends supine with uke on top — position reversal). Fails against low-wide jigotai (foot cannot reach abdomen; often converts to sumi-gaeshi). Foot too high (chest) → uke grabs foot and passes. Foot too low (thigh) → no vertical lift. Grip break → tori flat on back, worst case uke passes to mount. For the simulation: rather than requiring pre-throw kuzushi, model tomoe-nage's kuzushi as an *outcome* of tori's sacrifice — if uke has any forward component of velocity at fall initiation, kuzushi is achieved mid-action; if not, the throw reverses.

---

## 4. Cross-cutting synthesis

### 4.1 Posture as a continuous variable

Biomechanical evidence strongly supports modeling posture as continuous rather than discrete. The shizentai/jigotai labels map to regions of a continuous parameter space defined by (a) sagittal trunk lean angle θ_ap, (b) frontal/lateral trunk lean angle θ_ml, (c) CoM height h (captures jigotai knee flexion), (d) base-of-support polygon defined by foot placements. Liu 2025 demonstrates trunk-tilt and head-tilt are continuous predictors of throw effectiveness (53% variance explained). The Korean 1992 Olympic-silver uchi-mata case study showed uke's CoG displacement differs substantially between jigohontai (0.43–0.73 cm) and shizenhontai (0.27–0.53 cm) for the same attack — jigotai is a specific pose trading maneuverability for directional resistance, not a universal stability maximum. Paillard's work shows monopedal vs. bipedal postural control are distinct, skill-trainable stability envelopes. **For simulation: two continuous trunk-lean angles + CoM height + base polygon is the supported abstraction.** Classical labels should be UI/commentary regions, not gating states. A caveat: almost all published data is sagittal-plane only — frontal-plane lateral lean is an under-measured dimension.

### 4.2 Force through grips

Grips are the coupling interface between tori's force and uke's trunk. Ishii et al. (2019) sensor-judogi work provides the only in-vivo force-vector measurement: tsurite in skilled seoi-nage transmits force along the throwing axis via internal shoulder rotation; failed/injured athletes rotate off-axis. Sacripanti's framework (arXiv:1411.2763) divides grip roles into *connective* (binding the dyad into a single couple-of-athletes system — dominant in Couple throws) and *driving* (transmitting large directed force over a long lever arm — dominant in Lever throws). Handgrip *endurance* (not max strength) discriminates elite judoka (Franchini 2011; Bonitch-Góngora 2012); grip force declines ~15% across a four-match tournament (Iglesias 2003). Kashiwagura & Franchini 2022 scoping review (41 studies) is tactical rather than kinetic. **For simulation, each grip should be modeled as a constrained force-coupling with:**

- **Sleeve (sode)**: high moment-arm control of uke's arm rotation; low vertical-lift transmission.
- **Lapel low / lapel high / collar**: high vertical transmission and trunk-rotation coupling; collar gives longest rotational moment arm.
- **Belt (obi)**: direct CoM control, highest moment about uke's CoM, legally restricted → high-power short-duration.
- **Pistol (end of sleeve)**: mutual immobilization, high defensive stiffness, low offensive throughput for both athletes.
- **Cross-grip**: atypical force vectors, asymmetric access to uke's back.

Force envelopes should be scaled by a decaying max-force over bout time. **Research gap: no comprehensive dataset of per-grip force vectors or moment-arm tables exists.** Only tsurite in seoi-nage has been instrumented.

### 4.3 The tsukuri–kuzushi–kake sequence — overlapping, not sequential

The classical three-phase sequence is didactically useful but mechanically false. Matsumoto et al. (Kodokan Report V, 1978) first established, using film + force-plates + EMG, that the phases overlap and cannot be temporally separated in skilled execution. Every subsequent study concurs: Imamura 2006/2007 shows the largest impulse occurs during combined kuzushi+tsukuri (collision window), not in an isolated kake; Ishii 2017 shows elite athletes compress kuzushi and tsukuri into a shorter overlapped window; Blais & Trilles 2004 shows phase boundaries are reproducible within subject but vary substantially between experts. Sacripanti reformulates: all throws share *General Action Invariants* (whole-body distance-closing and pose alignment), and Lever throws additionally require *Specific Action Invariants* (kinetic-chain pose for the fulcrum). De Crée & Edmonds (2012) give a 7-phase model (kumu → kuzushi → tsukuri → kake → nageru → zanshin); Hirano 1969 gives a 5-phase model; Kano gives 3. All are nested decompositions of the same continuous event. **For simulation: model the throw as one continuous trajectory parameterized by a skill-dependent compression factor (novice = de-overlapped, elite = single pulse). Event markers (uke CoM exits base polygon; tori's contact point locks; tori CoM crosses commit line) can serve as *observables*, not as gating state transitions.** Under resistance, the sequence de-overlaps and kuzushi becomes a train of pulses rather than a single shift.

### 4.4 Commitment and recovery — the point of no return

No paper gives a single numerical threshold; irreversibility is a continuous scalar determined by the ratio of delivered momentum (angular for Couple throws, combined translation+rotation for Lever throws) to the momentum tori could still retract. Sacripanti formalizes three counter-windows corresponding to three dyad-state regions:

- **Sen-sen no sen** — preempt before uke's tsukuri locks. Counter is against a developing, retractable force. Applicable throughout tori's approach.
- **Sen no sen** — strike at the moment tori's couple or fulcrum loads but before uke's CoM is displaced past the commit line. The last window for a symmetric counter-throw.
- **Go no sen** — counter after tori commits; uke must redirect already-delivered momentum (osoto-gaeshi, ko-uchi-gaeshi, uchi-mata-gaeshi — all redirect rather than resist).

Dyad shifting velocity 0.2–0.4 m/s and attack-in speed 1.3–1.8 m/s put the elite commitment window at ~100–300 ms. Direct attacks account for ~66.6% of scoring actions; combinations and action-reaction (exploiting commitment windows) make up the remainder. **Two tori vulnerability windows** appear in practice: (1) the instant tori begins the turn-in on uke (weight transferred to pivot foot, other foot airborne — CoM often outside eventual base); (2) the instant after tori completes the turn but fails to raise uke ("stuffed") and begins to reverse. These are the mechanical opportunities for kaeshi-waza. **For simulation: commitment is continuous, roughly |Δp_uke(t)| / (m_uke · v_recover) with v_recover ≈ 2 m/s for elite; pass ~50% and the throw is practically irreversible. Different throw classes have different commit geometries — Lever throws commit at fulcrum-loading with uke's CoM past the potential-barrier maximum; Couple throws commit when angular velocity about the couple axis exceeds uke's stepping recovery capacity.**

### 4.5 Failed throws and counters

Outside of Ishii's sensor-judogi seoi-nage studies and Gutiérrez 2009 T-pattern analysis of uki-goshi errors, almost all published biomechanics analyzes *successful* throws — this is the thinnest area of the literature. The synthesized picture:

**Mechanical signature of a stuffed attack** (Ishii 2019; Imamura 2007 under resistance): grip-force vector rotates off-axis from nominal throwing direction; tori's trunk flexes compensatorily to supply lift the hip failed to produce; shoulder external rotation increases; tori's elbow moment spikes (chronic failure of this pattern produces the elbow overuse seen in Kamitani 2011). Tori's CoM may already be outside tori's own base polygon during single-support phases.

**Three failure outcomes the simulation should distinguish:**

- **Recoverable stuff**: tori's CoM stays within base; tori retracts and can re-attempt (renzoku-waza window — combination throws).
- **Sukashi (void counter)**: uke removes the expected load (e.g., uchi-mata-sukashi: uke pivots knees together; tori's sweeping leg meets empty space; tori's committed couple now acts only on tori → self-throw). Diagnostic: tori has committed angular momentum that was expected to be absorbed by uke's inertia but is not.
- **Kaeshi (redirection counter)**: uke adds a small moment along tori's already committed momentum vector (osoto-gaeshi, ko-uchi-gaeshi, uchi-mata-gaeshi). Low-energy coupling — uke does not generate new force, only redirects.

**For simulation:** a failed throw should not simply abort. It should transition tori to a compromised state with quantifiable mechanical signatures (extended single-support, trunk flexion beyond nominal, CoM near or outside tori's own base, high residual angular momentum) that are immediately exploitable by uke. Grip-force misalignment (Ishii 2019) is a useful internal observable for "about-to-fail."

---

## 5. Open questions and where research is thin

**Empirical gaps — no peer-reviewed kinetic or kinematic studies exist for:**
- O-goshi (only canonical Kodokan descriptions; treated as foundational/training in most literature)
- O-guruma (no GRF, joint-moment, or reap-velocity data)
- Ko-uchi-gari (only De Crée & Edmonds 2012 qualitative paper; no instrumented study)
- Tai-otoshi joint kinetics (only shoulder-impact kinematics, Soldin 2022)
- Tomoe-nage (zero biomechanics literature; physics inferred from Kashiwazaki coaching + first-principles)

For these five throws, simulation parameters must be transferred from analogues (seoi-nage for tai-otoshi and tomoe-nage levers; osoto-gari for ko-uchi-gari couple) and flagged as inferential.

**Methodological caveats:** Almost all empirical data is from n < 5 tori, often n = 1, often with a single non-resisting uke. Only Harai-goshi (Imamura 2007) and Osoto-gari (Jagić 2005) have been compared under competitive resistance. Population-scale parameter distributions must be inferred, not cited. Frame rates in older studies (60 Hz 2D video, Imamura & Johnson 2003) are too low for accurate peak-velocity values; Liu's 250 Hz Mac3D + 1000 Hz force-plate work is the gold standard but sample-limited (n ≤ 22).

**Unresolved questions:**
- Is the canonical uchi-mata contact the far (Daigo) or near leg? Both have elite exemplars; competition favors koshi-uchi-mata (hip-loaded, near-leg, blurs with hane-goshi).
- What is the force-vector profile of non-seoi-nage grips? Only tsurite in seoi-nage has ever been instrumented.
- No published CoM-displacement threshold for irreversibility — only phase-by-phase momentum curves.
- No instrumented study of any major counter or sukashi technique exists.
- No dataset of posture distribution during live randori/shiai — we know the parameter space but not which regions are actually visited.

**Conflicting claims:**
- O-soto-gari kuzushi direction: Kodokan/Daigo specifies ushiro-migi with heel-loading, but Imamura 2006 shows uke CoM actually moves forward during kuzushi before reversing — black belts first load the lead leg (hando-no-kuzushi), contradicting the naive "pull backward" reading.
- Sacripanti's Couple/Lever classification is theoretically coherent and empirically consistent with competition frequency data (arXiv:1308.0716) but has never been validated by direct per-throw force-axis measurement. The Kodokan does not adopt it (retains te/koshi/ashi/sutemi-waza categorization). For simulation design, Sacripanti's scheme is more useful; for nomenclature/UI, Kodokan's is standard.
- The often-cited Kano quote "It is not the technique itself that defeats the opponent, but the control of their balance" could not be located in primary sources; likely apocryphal.

---

## 6. Citations

### Primary / Kodokan
- Kano, J. (1986). *Kodokan Judo*. Tokyo: Kodansha International.
- Kano, J. (2006). *Mind Over Muscle: Writings from the Founder of Judo*. M. Naoki (ed.), N. H. Ross (trans.). Tokyo: Kodansha International.
- Kawamura, T. & Daigo, T. (eds.) (2000). *Kodokan New Japanese-English Dictionary of Judo*. Tokyo: Kodokan Institute.
- Daigo, T. (2005/2016). *Kodokan Judo Throwing Techniques*. Tokyo: Kodansha International. ISBN 9784770023308.
- Mifune, K. (2004). *The Canon of Judo*. Tokyo: Kodansha.
- Kudō, K. (1967). *Dynamic Judo: Throwing Techniques*. Tokyo: Japan Publications.
- Inokuma, I. & Sato, N. (1979). *Best Judo*. Tokyo: Kodansha International.
- Matsumoto, Y., Takeuchi, Y., Nakamura, R., Tezuka, M., & Takahashi, K. (1978). "Analysis of the Kuzushi in the Nage Waza." *Bulletin of the Association for the Scientific Studies on Judo, Kodokan*, Report V.
- Ikai, M. & Matsumoto, Y. (1958). "The Kinetics of Judo."
- Imamura, R., Iteya, M., & Ishii, T. (2007). "Kuzushi, Tsukuri and the theory of reaction resistance." *Kodokan Report XI*.
- Osawa, K. (1966). Technical definition of uchi-mata-sukashi. *Judo* magazine.
- Kodokan Waza Study Group (1989, March 14). Classification of uchi-mata-sukashi.

### Sacripanti (theoretical biomechanics)
- Sacripanti, A. (2008). "Biomechanical Classification of Judo Throwing Techniques (Nage Waza)." arXiv:0806.4091. (Originally 5th ISBS, Athens 1987.)
- Sacripanti, A. (2010). "Biomechanics of Kuzushi-Tsukuri and Interaction in Competition." arXiv:1010.2658.
- Sacripanti, A. (2012). "A Biomechanical Reassessment of the Scientific Foundations of Jigoro Kano's Kodokan Judo." arXiv:1206.1135.
- Sacripanti, A. (2013). London 2012 technique-frequency analysis. arXiv:1308.0716.
- Sacripanti, A. (2014). Direct-attack effectiveness. arXiv:1401.1102.
- Sacripanti, A. (2014). First-contact tactics; grips connective vs driving. arXiv:1411.2763.
- Sacripanti, A. (2016). Uchi-mata family. arXiv:1602.02165.
- Sacripanti, A. (2019). Ko-uchi family. arXiv:1907.01220.
- Sacripanti, A. (2010). *Advances in Judo Biomechanics Research*. VDM Verlag. ISBN 978-3-639-10547-6.
- Sacripanti, A. (1988). *Biomeccanica del Judo*. Roma: Ed. Mediterranee.

### Empirical kinematic/kinetic
- Imamura, R. T., Hreljac, A., Escamilla, R. F., & Edwards, W. B. (2006). "A Three-Dimensional Analysis of the Center of Mass for Three Different Judo Throwing Techniques." *Journal of Sports Science and Medicine* 5(CSSI), 122–131.
- Imamura, R., Iteya, M., Hreljac, A., & Escamilla, R. (2007). "A Kinematic Comparison of the Judo Throw Harai-Goshi during Competitive and Non-Competitive Conditions." *JSSM* 6(CSSI-2), 15–22.
- Imamura, R. T. & Johnson, B. F. (2003). "A kinematic analysis of a judo leg sweep: major outer leg reap — osoto-gari." *Sports Biomechanics* 2(2), 191–201.
- Imamura, R., Iteya, M., & Takeuchi, Y. (2005). "The Biomechanics of Osoto-gari." Association for the Scientific Studies on Judo.
- Liu, L., Deguchi, T., Shiokawa, M., Ishii, T., Oda, Y., & Shinya, M. (2021/2024). *Sports Biomechanics* 23(11), 2021–2033.
- Liu, L. et al. (2022/2024). *Sports Biomechanics* 24(3). doi:10.1080/14763141.2022.2125432.
- Liu, L., Deguchi, T., Shiokawa, M., Hamaguchi, K., & Shinya, M. (2025). *PeerJ* 13:e18862.
- Hamaguchi, K. et al. (2025). "A biomechanical study of judo uchimata." *Sports Biomechanics* 24(9).
- Brito, C. J., Almeida, N. R., Roa-Gamboa, I., et al. (2025). "Kinematic Analysis of the Lower Limb in Uchi-Mata." *JFMK* 10(4):378.
- Blais, L. & Trilles, F. (2004). "Analyse mécanique comparative d'une même projection de judo: Seoi-Nage…" *Science & Motricité* 51, 49–68.
- Blais, L., Trilles, F., & Lacouture, P. (2007). "Three-dimensional joint dynamics and energy expenditure during the execution of a judo throwing technique (Morote Seoï Nage)." *Journal of Sports Sciences* 25(11), 1211–1220.
- Ishii, T., Ae, M., Suzuki, Y., & Kobayashi, Y. (2018). Elite vs college seoi-nage. *Sports Biomechanics* 17(2), 238–250.
- Ishii, T., Ae, M., Koshida, S., & Fujii, N. (2016). ISBS Proceedings.
- Ishii, T. et al. (2019). Sensor-judogi seoi-nage. ISBS Proceedings, Oxford.
- Choi, H. & Song, Y. (2023). "Comparing the seoi-nage skill of elite and non-elite judo athletes." *Scientific Reports* (PMC10709631).
- Pucsok, J. M., Nelson, K., & Ng, E. D. (2001). "A kinetic and kinematic analysis of the harai-goshi judo technique." *Acta Physiologica Hungarica* 88(3-4), 271–280.
- Harter, R. A. & Bates, B. T. (1985). "Kinematic and temporal characteristics of selected judo hip throws." *Biomechanics in Sport II* (ISBS), 141–150.
- Tezuka, M., Funk, S., Purcell, M., & Adrian, M. (1983). "Kinetic Analysis of Judo Technique." *Biomechanics VIII-B*, 869–875.
- Hashimoto, T. et al. (1984). Uchi-mata biomechanics. *Bulletin of Nippon College of Physical Education* 13:73.
- Minamitani, N., Fukushima, M., & Yamamoto, H. (1988). "Biomechanical properties of judo throwing technique, uchimata." *Biomechanics in Sports VI*, 245–251.
- Kwon, Cho, & Kim (2005). Uchi-mata kinematic analysis by kumi-kata type. *Korean Journal of Sport Biomechanics*.
- Kim, Eui-Hwan et al. (2006/2007). "A Biomechanical Analysis of Judo's Kuzushi (balance-breaking) Motion." *Korean Journal of Applied Biomechanics*.
- Yabune (1994). Advanced vs novice supporting-foot GRF. *Bulletin of Kyoto University of Education*.
- Jagić, M., Hraski, Ž., & Mejovšek, M. (2005). Competitive vs teaching osoto-gari kinematic comparison.
- Soldin, M. et al. (2022). "Video Biomechanical Analysis of Shoulder Impact Kinematics in Tai-Otoshi and Morote-Seoi-Nage." *Applied Sciences* 12(7):3613.
- Gomes, F. R. F., Meira Jr., C. M., & Tani, G. (2026). "Whole practice combined with Kuzushi preparation enhances learning of Tai Otoshi." *Brazilian Journal of Motor Behavior* 19(1):e510.
- Santos, L. et al. (2014). "Three-dimensional assessment of judo throwing techniques." *Archives of Budo* 10:OA107–112.
- Murayama, H., Hitosugi, M., Motozawa, Y., Ogino, M., & Koyama, K. (2020). Head impact in osoto-gari and ouchi-gari. *Neurologia Medico-Chirurgica* 60(6), 307–312.
- Hassmann, M., Buchegger, M., Stollberg, K. P., Sever, A., & Sabo, A. (2010). "Motion analysis of performance tests using a pulling force device…" *Procedia Engineering* 2(2), 3329–3334.
- Möller, S. et al. (2009). "Movement profiles of the balance breaking (Kuzushi) of top judoka." In Hökelmann A et al. (eds.), *Current Trends in Performance Analysis*. Aachen: Shaker Verlag.
- Sterkowicz, S., Sacripanti, A., & Sterkowicz-Przybycień, K. (2013). "Techniques frequently used during London Olympic judo tournaments: a biomechanical approach." *Archives of Budo*. arXiv:1308.0716.

### Physiology, grip, posture
- Franchini, E., Del Vecchio, F. B., Matsushigue, K. A., & Artioli, G. G. (2011). "Physiological profiles of elite judo athletes." *Sports Medicine* 41(2), 147–166.
- Franchini, E., Miarka, B., Matheus, L., & Del Vecchio, F. B. (2011). Judogi grip endurance test. *Archives of Budo* 7, 1–4.
- Bonitch-Góngora, J. et al. (2012). "Lactate and handgrip in judo bouts." *Journal of Strength and Conditioning Research*.
- Kashiwagura, D. & Franchini, E. (2022). Scoping review of kumi-kata. *Revista de Artes Marciales Asiáticas* 17(1), 1–18.
- Detanico, D. et al. (2017). Handgrip decrement across tournament matches.
- Perrin, P., Deviterne, D., Hugel, F., & Perrot, C. (2002). "Judo, better than dance, develops sensorimotor adaptabilities involved in balance control." *Gait & Posture*.
- Maśliński, J., Witkowski, K., Cieśliński, I., et al. (2022). Postural stability in 11–14 y/o judokas. *Frontiers in Psychology*.
- Sterkowicz, S. (1995). Special Judo Fitness Test. *Antropomotoryka* 12, 29–44.

### Coaching / pedagogical
- Kashiwazaki, K. (1992). *Tomoe-Nage* (Judo Masterclass Techniques). London: Ippon Books.
- Kashiwazaki, K. *Attacking Judo* and *Fighting Judo* (Ippon Books).
- Okano, I. *Vital Judo: Throwing Techniques*. Tokyo: Japan Publications.
- Adams, N. Coaching materials and *Kuzushi Revolution* audio-visual materials (2014).
- Pedro, J. Tai-otoshi coaching (Judo Fanatics).
- Hicks, D. (2022). *Throwing for Ippon 3: Uchi-mata* (Kosei Inoue + 10 experts). Superstar Judo.
- Gutiérrez-Santiago, A., Prieto, I., Camerino, O., & Anguera, M. T. (2013). "Sequences of errors in the judo throw morote seoi nage." *Proc IMechE Part P: Journal of Sports Engineering and Technology* 227.
- Gutiérrez, A., Prieto, I., & Cancela, J. M. (2009). "Most frequent errors in uki-goshi." *JSSM* 8(CSSI3), 36–46.
- De Crée, C. (2014). "Nanatsu-no-kata, Endō-no-kata, and Jōge-no-kata: Hirano Tokio's kuzushi concept." *Revista de Artes Marciales Asiáticas* 9(2), 69–96.
- De Crée, C. & Edmonds, D. A. (2012). Technical-pedagogical reflection on ko-uchi-gari. *Comprehensive Psychology* 1(1), 1–13.
- Jones, L. (2018). "Kuzushi, Tsukuri and Kake in Kodokan Judo." *Kano Society Bulletin*, Issue 37.
- Pop, I.-N., Gombos, L., & Prodea, C. (2014). Biomechanical Classification of Nage-Waza Throwing Techniques (II).
- Trilles, F., Blais, L., & Cadière, R. (2010). "Facteurs biomécaniques de performance." In Paillard, T. (ed.), *Optimisation de la performance sportive en judo*, 143–156. Brussels: De Boeck.