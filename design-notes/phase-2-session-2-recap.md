# Phase 2 Session 2 — Recap
## The Grip Graph, the Position Machine, the Ne-Waza Door, and the Referee

*Written after the session. What actually shipped, what surprised us, what to think about before Phase 3.*

*Date: April 15, 2026*

---

## What Was Built

Nine source files, all either new or significantly rewritten. The build order followed the plan exactly.

### `src/enums.py` — Complete rewrite

Eight new enums landed:

- **`BodyPart`** — 24 values (added head, hips, thighs, knees, wrists) plus DOMINANT_HAND / NON_DOMINANT_HAND / OPPOSITE_LAPEL / DOMINANT_SLEEVE symbolic aliases that resolve at match time based on DominantSide.
- **`GripType`** — 13 values with `dominance_factor()` (DEEP=1.3, BELT=1.4, TWO_ON_ONE=1.5, POCKET=0.5) and `fatigue_rate()` methods.
- **`GripTarget`** — standing (lapels, sleeves, belt, back) + ne-waza (neck, wrists, elbows, knees, etc.) + symbolic aliases.
- **`InjuryState`** — HEALTHY / MINOR_PAIN / IMPAIRED / MATCH_ENDING with `multiplier()` method.
- **`LandingProfile`** — FORWARD_ROTATIONAL / HIGH_FORWARD_ROTATIONAL / REAR_ROTATIONAL / LATERAL / SACRIFICE. Affects IPPON vs WAZA_ARI calls.
- **`MatteReason`** — SCORING / STALEMATE / OUT_OF_BOUNDS / PASSIVITY / STUFFED_THROW_TIMEOUT / INJURY / OSAEKOMI_DECISION.
- **`CounterAction`** — HAND_FIGHT / FRAME / HIP_OUT / BRIDGE / TURNOVER / SHRIMP. Available to bottom fighter each ne-waza tick.
- **`SubLoopState`** — ENGAGEMENT / TUG_OF_WAR / KUZUSHI_WINDOW / STIFLED_RESET / THROW_COMMITTED / NE_WAZA.
- **`Position`** — expanded to 15 values including TURTLE_TOP/BOTTOM, GUARD_TOP/BOTTOM, SIDE_CONTROL, MOUNT, BACK_CONTROL, DOWN, THROW_COMMITTED.

### `src/judoka.py` — Updated

- Body parts expanded 15 → 24. Nine new optional capability fields with defaults (right_hip, left_hip, right_thigh, left_thigh, right_knee, left_knee, right_wrist, left_wrist, head).
- `BodyPartState` now carries `injury_state: InjuryState` and `stun_ticks: int`. The `injured` property is a backward-compat alias for `injury_state != HEALTHY`.
- `effective_body_part()` now applies `InjuryState.multiplier()` and `stun_ticks` penalty: `stun_mult = max(0.7, 1.0 - stun_ticks * 0.05)`.
- `State` gets `stun_ticks: int = 0`.
- `Identity` gets arm_reach_cm, hip_height_cm, weight_distribution, mass_density, nationality — cultural layer hooks declared, dormant until Ring 2.

### `src/grip_graph.py` — New

The foundational module. A bipartite graph of GripEdge objects.

Key implementations:
- `GripEdge` dataclass: grasper_id, grasper_part, target_id, target_location, grip_type, depth (0–1), strength (0–1), established_tick, contested flag.
- `resolve_body_part_alias()` and `resolve_target_alias()` — turn DOMINANT_HAND → "right_hand" and OPPOSITE_LAPEL → "left_lapel" based on the attacker's DominantSide.
- `attempt_engagement()` — creates collar + sleeve grips per fighter. Depth is probabilistic: `random.uniform(0.3, 0.7) × (hand_eff / 7.0) × reach_factor`. Depth thresholds: DEEP ≥ 0.6, STANDARD ≥ 0.35, POCKET else.
- `tick_update()` — three-tier per-edge resolution: FAILURE (~8%), PARTIAL (~25%), SUCCESS. PARTIAL degrades depth 0.15, downgrades grip type if depth crosses boundary. Force-break fires at fatigue ≥ 0.85 with prob 0.25.
- `compute_grip_delta()` — `sum(depth × strength × dominance_factor)` for each side, returns A_total − B_total.
- `satisfies()` — resolves all aliases per requirement, checks grasper_part + target_location + grip_type_in + min_depth + min_strength.

### `src/throws.py` — Updated (backward-compatible)

- `EdgeRequirement` dataclass added: grasper_part, target_location, grip_type_in, min_depth, min_strength.
- `ThrowDef` dataclass: throw_id, name, requires (list[EdgeRequirement]), posture_requirement, primary_body_parts, landing_profile.
- `THROW_DEFS` dict — prerequisites for all 8 throws. Example: SEOI_NAGE requires DOMINANT_HAND on OPPOSITE_LAPEL (DEEP/HIGH_COLLAR, min_depth=0.6) AND NON_DOMINANT_HAND on DOMINANT_SLEEVE (STANDARD/PISTOL, min_depth=0.3). KO_UCHI_GARI requires only any dominant-hand grip with depth ≥ 0.1.
- `NewazaTechniqueID` enum and `NewazaTechniqueDef` dataclass added.
- `NEWAZA_REGISTRY`: OKURI_ERI_JIME (choke, chain_length=12), JUJI_GATAME (armbar, chain_length=10), KESA_GATAME / YOKO_SHIHO_GATAME (pins via clock).

### `src/position_machine.py` — New

Static class with no state of its own.

- `_LEGAL_TRANSITIONS` dict — covers all 15 position → position paths.
- `can_attempt_throw()` — requires GRIPPING or ENGAGED position AND `grip_graph.satisfies()`.
- `can_force_attempt()` — legal from GRIPPING if any live edge exists; carries 0.15 effectiveness multiplier.
- `determine_transition()` — implicit per-tick heuristics (DISTANT → GRIPPING when edges form, GRIPPING → ENGAGED on KUZUSHI_WINDOW, etc.).
- `ne_waza_start_position()` — rolls defender_top_prob = 0.55 + (def_skill − agg_skill) × 0.04, clamped 0.2–0.85. SIDE_CONTROL if defender on top, GUARD_TOP if aggressor scrambles.

### `src/referee.py` — New

Six personality parameters: newaza_patience, stuffed_throw_tolerance, match_energy_read, grip_initiative_strictness, ippon_strictness, waza_ari_strictness.

Derived timing constants:
- `_STALEMATE_MATTE_TICKS = int(20 - match_energy_read * 10)` — 10–20 ticks
- `_STUFFED_MATTE_TICKS = int(8 - stuffed_throw_tolerance * 6)` — 2–8 ticks
- `_NEWAZA_MATTE_TICKS = int(30 + newaza_patience * 30)` — 30–60 ticks
- `_PASSIVITY_SHIDO_TICKS = int(120 - grip_initiative_strictness * 60)` — 60–120 ticks

`should_call_matte()` — checks ne-waza stalemate, stuffed-throw timeout, standing stalemate TUG_OF_WAR duration.

`score_throw()` — called only for WAZA_ARI-or-better outcomes from resolve_throw(). Uses net-score units directly: `ippon_net_threshold = 4.0 + (ippon_strictness − 0.5) × 1.5`. Referee can downgrade IPPON → WAZA_ARI (by personality) but never NO_SCORES a scored throw. Small Gaussian noise (σ=0.3 net units) models referee inconsistency.

**Two pre-built personalities:**
- **Suzuki-sensei** — newaza_patience=0.7, stuffed_throw_tolerance=0.3, ippon_strictness=0.8. Patience for ground, quick reset on stuffed throws, strict ippon standard.
- **Petrov** — newaza_patience=0.5, stuffed_throw_tolerance=0.7, ippon_strictness=0.5. More time for scrambles, generous on landing angle.

### `src/ne_waza.py` — New

- `OsaekomiClock` — WAZA_ARI at 10 ticks, IPPON at 20 ticks. `start()`, `tick() → Optional[str]`, `break_pin()`.
- `NewazaResolver` — per-tick FSM for ground work.
  - `attempt_ground_commit()` — rolls whether fighters go to ground after stuffed throw.
  - `tick_resolve()` — escape check (BASE_ESCAPE_PROB=0.08 + skill×0.025, scaled by cardio and position difficulty), counter-action resolution, technique chain advancement, pin initiation.
- Choke chain (okuri-eri-jime): INITIATING (3t) → SETTING (6t) → TIGHTENING → submission at chain_tick ≥ 12 if tighten roll succeeds.
- Armbar chain (juji-gatame): ISOLATING (3t) → POSITIONING (6t) → EXTENDING → submission at chain_tick ≥ 10.
- Pin: no chain — osaekomi clock runs when SIDE_CONTROL / MOUNT / BACK_CONTROL and no active technique.

### `src/match.py` — Complete rewrite

The conductor. All tuning constants in one block at the top:

```
KUZUSHI_THRESHOLD   = 0.45   # grip_delta needed to open a window
STALEMATE_THRESHOLD = 0.12   # below this → stalemate
STALEMATE_DURATION  = 18     # ticks before STIFLED_RESET
WINDOW_COMMIT_BASE  = 0.65   # commit probability per window tick
FORCE_COMMIT_PROB   = 0.025  # desperate attempt probability (~1/40 ticks)
NOISE_STD           = 2.0    # Gaussian noise in throw resolution
IPPON_THRESHOLD     = 4.0    # net score for throw → IPPON candidate
WAZA_ARI_THRESHOLD  = 1.5    # net score for throw → WAZA_ARI candidate
STUFFED_THRESHOLD   = -2.0   # net score below which = STUFFED
```

Eight-step `_tick()` pipeline: fatigue → grip graph → sub-loop → position machine → osaekomi clock → referee Matte check → passivity → print events.

Sub-loop FSM: ENGAGEMENT (waits for grip formation) → TUG_OF_WAR (grip delta tracking) → KUZUSHI_WINDOW (commitment roll + `_try_throw_from_window()`) → STIFLED_RESET → NE_WAZA.

`_pick_throw_for_graph()` — tries signature throws first, then full vocabulary, checking `grip_graph.satisfies()` for each.

`_apply_throw_result()` — only calls `referee.score_throw()` for IPPON/WAZA_ARI outcomes. The referee decides IPPON vs WAZA_ARI (never NO_SCORE a scored throw).

### `src/main.py` — Updated

UTF-8 stdout wrapper for Windows arrow characters. CLI args: `--referee suzuki|petrov`, `--runs N`, `--seed N`. Tanaka and Sato updated with new 24-part body model fields and Identity additions.

---

## Calibration Work Done This Session

Three calibration bugs found and fixed after the first smoke tests:

**1. KUZUSHI_THRESHOLD was 1.8 — too high.** The maximum grip_delta achievable with 2 edges per fighter (typical depth 0.3–0.7, strength 0.5–0.8, dominance_factor 1.0–1.3) is roughly 0.5–0.9. Lowered to 0.45, STALEMATE_THRESHOLD from 0.6 to 0.12.

**2. Referee `score_throw()` formula was broken.** Original formula: `raw_quality = (net × 0.6 + wq × 4.0) / 10.0`. A WAZA_ARI throw (net=2.0) produced raw_quality=0.24, below the waza_ari_threshold of 0.375 → NO_SCORE. Root cause: the denominator of 10 made the formula fight the net-score units from resolve_throw(). Fixed by redesigning score_throw() to use net-score units directly for the IPPON/WAZA_ARI decision, with ippon_net_threshold = 4.0 ± personality scaling. The referee now never strips a scored throw to NO_SCORE.

**3. Passivity shidos dominated match outcomes.** Original `_PASSIVITY_SHIDO_TICKS = 45` (Suzuki). Because `_last_attack_tick` defaults to 0, fighters are counted as passive from tick 31 onward — 45 passive ticks → shido at t120 in every match where no early throw happened. Doubled the base from 60 to 120: `_PASSIVITY_SHIDO_TICKS = int(120 - grip_initiative_strictness × 60)`, giving Suzuki 90 ticks instead of 45.

**4. Hand fatigue death spiral.** Two fatigue sources compound: EDGE_FATIGUE_PER_TICK (grip edges drain the grasping body parts) and HAND_FATIGUE_PER_TICK (background per-tick drain). By mid-match, hand effectiveness dropped to ~3/10, which reduced `attempt_engagement()` depth to POCKET-only (<0.35). POCKET grips have dominance_factor=0.5 → grip_delta stays below KUZUSHI_THRESHOLD → no windows → all stalemates. Fixed by halving both: EDGE_FATIGUE_PER_TICK 0.004 → 0.002, HAND_FATIGUE_PER_TICK 0.001 → 0.0003.

**5. OsaekomiClock log bug.** `break_pin()` resets `ticks_held = 0` before the log message reads it, so "Clock stopped at 0 ticks" always appeared. Fixed by capturing `ticks_held` before calling `break_pin()`.

**6. `announce_matte(None, tick)` crash.** When IPPON was scored, the code called `announce_matte(None, tick)` for a cosmetic Matte. `reason.name` crashed on None. Fixed: import `MatteReason`, pass `MatteReason.SCORING`.

---

## Open Questions Resolved During the Session

All five pre-session open questions from the plan resolved naturally in code:

1. **`attempt_engagement()` rolls weighted by reach.** Correct — probabilistic with reach_factor = clamp(reach_a / reach_d, 0.7, 1.4).
2. **Force attempt uses same `resolve_throw()` with 0.15 multiplier.** Confirmed — simpler path, same physics.
3. **SCRAMBLE → NE_WAZA vs STANDING_DISTANT decision.** Resolved via `attempt_ground_commit()` — either fighter committing transitions both. The ne_waza_skill + fatigue + window_quality roll handles the probability.
4. **OsaekomiClock lives on Match.** Confirmed — it's match state, Referee just reads `osaekomi_ticks` from MatchState.
5. **Counter-actions: one per tick, picked by AI.** Confirmed — bottom fighter gets one counter-action picked by skill level; player control is Ring 2 / play-as-judoka territory.

---

## What Surprised Us

**The POCKET grip problem was non-obvious.** We expected grip depth to vary meaningfully across the match. What actually happened: the compounding of two fatigue sources (background + edge drain) collapsed hand effectiveness to ~30% of starting value by mid-match, and `attempt_engagement()` used `hand_eff / 7.0` as a linear multiplier on depth. By mid-match, every new grip was POCKET. POCKET grips have 0.5 dominance_factor, so grip_delta never exceeded the threshold. The visual tell in the log: "left_lapel, POCKET, depth 0.26" appearing everywhere after tick 80. The fix (halving both fatigue rates) kept grips in the STANDARD range for more of the match without making them unrealistically fresh.

**The referee scoring formula needed a complete redesign, not tuning.** The original formula tried to normalize net scores and window quality into a 0–1 scale, then compare against a threshold. The problem was that net scores from `resolve_throw()` are in one unit system (WAZA_ARI ≥ 1.5, IPPON ≥ 4.0) and the formula's denominator of 10 was fighting that. The fix was to abandon the normalization and let the referee reason directly in net-score units — which is what the match engine already uses. Once the referee stayed in the same unit system as resolve_throw(), the IPPON/WAZA_ARI distinction became clean.

**Seoi-nage fires less often than expected.** Tanaka's signature throw requires DEEP collar grip (depth ≥ 0.6), which is achievable early in a match. But DEEP grips slip to STANDARD within a few ticks via the PARTIAL resolution path. Once STANDARD, seoi-nage is unavailable and Tanaka falls back to leg throws (O-uchi-gari, Ko-uchi-gari) with lower effectiveness_dominant (6–7 vs 9). This is correct behavior — seoi-nage IS a grip-dependent throw that rewards fighters who can maintain deep collar control. But it means Tanaka's ippon rate is lower than his raw effectiveness would suggest. Good realism, worth understanding for Phase 3.

**Tanaka's grip dominance is persistent.** With right_hand=9 vs Sato's right_hand=7, plus Tanaka's reach advantage (190 vs 183 cm), Tanaka almost always establishes higher grip_delta. Sato's superior legs (right_leg=9, left_leg=8 vs Tanaka's 8, 7) don't contribute to grip formation in the current model — they only matter in throw resolution. Sato can still win (seen in the 50-match test), but the matchup favors Tanaka significantly. This is Phase 3 calibration territory — the cultural layer (Phase 3/Ring 2) will add uchi-mata-centric grip selection that lets Sato reach for the configuration his technique requires.

---

## Match Distribution (50 matches, seed 7)

```
Draw (0-0)           31  (62%)  → golden score pending (Phase 3)
Tanaka wins decision 11  (22%)  → 1 waza-ari advantage
Tanaka wins 2x waza   2  ( 4%)  
Sato wins decision    2  ( 4%)  
Draw (1-1)            2  ( 4%)  → golden score pending
Tanaka wins ippon     1  ( 2%)  
Sato wins ippon       1  ( 2%)  
```

High draw rate (66%) is a Phase 3 calibration target. Likely causes: KUZUSHI_THRESHOLD still requires meaningful grip advantage; POCKET grips don't open windows; Suzuki-sensei's patience means matches go full time often. Both ippons did occur (rare but possible), confirming the physics is reachable. Sato wins DO occur (5-6% combined) despite the grip disadvantage.

**Design target for Phase 3**: draw rate 30–40%, ippon rate 15–20%, two-waza-ari rate 15–20%, decision rate 25–30%. Achievable by lowering KUZUSHI_THRESHOLD slightly and adjusting STALEMATE_DURATION.

---

## What This Session Does NOT Build

Carried forward explicitly:

- **Combo chains** — declared in throws.py, not wired into sub-loop. The KO_UCHI → SEOI and O_UCHI → UCHI_MATA combos live as data but don't fire as sequences. Phase 3 / Ring 2.
- **Cultural layer grip selection** — `attempt_engagement()` uses neutral default grips. Sato doesn't reach for the uchi-mata grip because the cultural layer isn't reading yet. Ring 2 Phase 1.
- **Coach window** — the Matte window UI doesn't exist. The simulation pauses for nothing, just resumes.
- **Golden score / overtime** — draws go unresolved. Phase 3.
- **Belt rank gating on composure hits** — declared in the plan, not implemented. The architecture supports it; the logic isn't there.
- **Physics variables beyond hand strength and reach** — hip height and weight distribution are declared on Identity, not yet used in throw resolution.

---

## What to Think About Before Phase 3

**Calibration priority list (high → low):**

1. Lower draw rate. KUZUSHI_THRESHOLD around 0.35–0.40 might open more windows. Try STALEMATE_DURATION 14–16 instead of 18.
2. POCKET grip kuzushi. Should a fighter with relative POCKET dominance (their grips are weak but opponent's are weaker) be able to open a window? Possibly — the current model requires absolute advantage above a fixed threshold, but relative advantage is what actually matters.
3. Seoi-nage ippon frequency. A clean Tanaka seoi-nage from a DEEP window has expected net ≈ 0.8, which means IPPON is rare. Real elite seoi-nage from proper kuzushi closes closer to 40% IPPON rate. This may require lowering Sato's defender_resistance multiplier or increasing the window quality bonus.
4. Sato win probability. Sato should win 30–40% of matches against Tanaka in a fair matchup. Currently ~6%. The uchi-mata cultural fix (Ring 2) will help; Phase 3 calibration should also check the defender_resistance formula against both fighters.
5. Ne-waza scoring. Osaekomi WAZA_ARI from pins is possible but hasn't been observed in 50 matches — pins break too fast (BASE_ESCAPE_PROB=0.08 + skill×0.025 ≈ 20% per tick, meaning 5-tick expected hold time vs the 10-tick WAZA_ARI threshold). Lowering BASE_ESCAPE_PROB or adjusting position_difficulty multipliers could produce pin scores.

**Architecture questions to revisit:**

- Should `update_passivity()` reset on Matte? Currently it doesn't — passive ticks carry across resets. This is arguably correct (passivity is cumulative within the match period), but it means a fighter who is genuinely fighting can accumulate a shido from the pre-engagement ticks at match start.
- The `_last_attack_tick` defaulting to 0 means fighters are "active" until tick 30, then "passive" forever unless they throw. Grip establishment should probably count as activity — a fighter establishing new grips after a Matte is not being passive.

---

*Session completed April 15, 2026. Phase 3 calibration is next.*
