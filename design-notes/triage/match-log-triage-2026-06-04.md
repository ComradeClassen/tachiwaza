# Match-Log Triage — non-grip notes

*Second triage pass on the 2026-06-04 match log (seed 1349309793). Covers the ~17 inline reviewer notes outside the grip model (those are HAJ-224/225/226). Verified against code; file:line evidence below. Diagnosis only — no fixes applied. Grouped by cluster, each item classified **bug / calibration / narration / missing-feature / working-as-intended (WAI)**.*

---

## Cluster 1 — Kuzushi debug stream (the loudest cluster)

The `[kuzushi] … buf mag=… tot=… dir=… dom=PULL n=…` lines are a raw debug readout of each fighter's **kuzushi buffer** — a 20-deep deque of recent off-balance impulses (`Judoka.kuzushi_events`, `src/kuzushi.py`). Each line is one fighter's *aggregate* off-balance state this tick:

- **mag** = this tick's freshly-added impulse magnitude · **tot** = decayed sum across the buffer · **dir** = net direction · **dom=PULL** = dominant source kind (PULL / FOOT_ATTACK / SELF_INFLICTED / THROW_RESOLUTION) · **n** = how many impulses are in the buffer. Off-balance "fires" when **tot ≥ 70** (`OFF_BALANCE_MAGNITUDE_THRESHOLD`).

**`dom=PULL n=1`** (the reviewer's question) just means: one impulse in the buffer, and it came from a PULL. That's all.

The buffer is emitted **unconditionally every tick** by `_print_kuzushi_buffer_debug()` (`src/match.py` ~6410), called from `_post_tick()` (~1952). It has **no gate** on position, matte, match-over, or grip existence, and the buffer is **never explicitly cleared** at any boundary (matte, ne-waza entry, reset-to-standing, post-score, match end) — it only ages out via the deque's `maxlen=20` and a slow 5-tick-half-life decay (`decay_factor`, `kuzushi.py`).

| # | Note | Finding | Class |
|---|---|---|---|
| 1.1 | Kuzushi on the **ground** (t012+) | The off-balance *signal* is only computed standing (`_check_off_balance` runs in `_tick_standing`, not `_tick_newaza`) — so this is **debug noise only**, no sim effect. But it prints. | **narration/bug** (debug output ungated) |
| 1.2 | Kuzushi after **Matte** (t013) | Same root: `_handle_matte` doesn't clear the buffer, debug print isn't gated on matte. | **narration/bug** |
| 1.3 | Kuzushi with **no grips** (t014–t018) | Old impulses from the prior exchange decay slowly and keep printing after grips reset. Spec intends cross-exchange persistence, but reading it with zero grips is a ghost. | **narration** (+ calibration: clear on full reset?) |
| 1.4 | Kuzushi **after match end** (t047) | `_end_match` sets `match_over` but doesn't clear the buffer; print isn't gated on `match_over`. | **bug** (debug output ungated) |
| 1.5 | **4 ticks** of kuzushi before first grip (t014–t018) | Same slow-decay persistence as 1.3. | **calibration/WAI** |
| 1.6 | Whole stream is **unreadable** (t008, t026) | The raw per-tick buffer dump leaks substrate. Belongs behind a deeper debug verbosity level, not the default stream. | **narration** |

**Disposition:** one ticket. Gate `_print_kuzushi_buffer_debug` on `not match_over`, standing-only (or a `--debug-kuzushi` verbosity flag), and clear the buffer on the hard boundaries (matte, reset-to-standing, match end). The off-balance *mechanic* is fine; this is all presentation + buffer-lifecycle hygiene. (Note: this sits adjacent to the in-flight kuzushi-buffer instrumentation branch.)

---

## Cluster 2 — Matte / Hajime / tick ordering

| # | Note | Finding | Class |
|---|---|---|---|
| 2.1 | **Matte should be the last line of its tick** (t013) | Genuine ordering issue. `_check_off_balance` appends KUZUSHI events *before* `_post_tick` appends MATTE_CALLED, and the narrator renders events in list order (`mat_side.py` `_rule_always_promote`). Both are always-promoted, so kuzushi prints after matte. Fix: order/sort so reset events (MATTE) close the tick — or, with Cluster 1, the trailing kuzushi just disappears. | **bug** (ordering) |
| 2.2 | **Want a Hajime after the Matte** (t013) | The restart-hajime path **exists** — `referee.announce_hajime`, scheduled via `_pending_hajime_tick = tick + MATTE_TO_HAJIME_PAUSE_TICKS` in `_handle_matte`, fired ~`match.py:1542`. It did **not** surface after the t013 ne-waza-escape-to-standing reset, so verify that the escape→standing reset actually routes through the hajime scheduler (it may reset without scheduling). | **bug/narration** (wiring — exists but didn't fire here) |

---

## Cluster 3 — Post-score narration

| # | Note | Finding | Class |
|---|---|---|---|
| 3.1 | **"uke airborne and flat"** over-sells a waza-ari as ippon (t011) | Wording lives in `src/execution_quality.py:162` — the `QualityBand.HIGH` template for `UCHI_MATA`. It's attached by quality band, independent of whether the score was waza-ari or ippon, so a high-quality waza-ari inherits "flat." Reword (or gate the "flat" phrasing to ippon-grade landings). | **narration** |
| 3.2 | **Just-thrown fighter "tugs at the sleeve"** (t011) | Genuine bug. The deferred pull-without-commit rule (`mat_side.py` `_rule_deferred_pull_without_commit`, ~685–768) renders a PULL BPE K=3 ticks later as "tugs at the sleeve — rides it out", **without** checking that a throw landed / the phase changed in between. So a pre-throw pull narrates after the throw resolves. Gate it: suppress when the actor's opponent scored or the dyad moved to ne-waza/reset in the window. | **bug** (state-gating) |

---

## Cluster 4 — Ne-waza realism

| # | Note | Finding | Class |
|---|---|---|---|
| 4.1 | **One-tick escape from guard-top** (t012→t013) | Genuine bug. `ne_waza.py` `_roll_escape` (~838–865) runs from the first ground tick with **no minimum-ticks-on-ground / settle gate**, and `position_difficulty` for `GUARD_TOP` is **1.5** (~line 853) — which *increases* escape odds rather than gating them. An escape can resolve on tick 1. Add a min-ground-ticks gate and re-check the position-difficulty direction. | **bug/calibration** |

---

## Cluster 5 — Mechanics the reviewer questioned (mostly WAI — explanation, not fix)

| # | Note | Finding | Class |
|---|---|---|---|
| 5.1 | **Chase `p=0.98`** — how computed? (t012) | `src/chase_decision.py` `make_chase_decision` (~103–207). `p` = base 0.50 + weighted factors (throw advantage ±, ne-waza skill, archetype bonus, aggressive/confident facets, −fatigue, score context ±, clock-pressure ±), clamped to **[0.02, 0.98]**. Roll `random() < p` → CHASE. 0.98 = clamp ceiling: a strong throw-advantage + context push. Working as designed. | **WAI** (explain) |
| 5.2 | **Pressure direction** — who moves whom? (t005) | `action_selection.py` `_pressure_direction` (~1769–1816): the actor (Tanaka) **steps into** the opponent — 60% toward opponent CoM, 40% toward the nearest edge/corner. So `Tanaka → pressure` = **Tanaka is driving forward**, pressuring Sato back, not being moved. Narration could say "drives pressure" to disambiguate. | **WAI** (narration polish) |
| 5.3 | **Commit / intent feel** (t007, t022) | `[intent] → throw_commit` at tick N, `[throw] commits` at N+1, is the HAJ-149 perception window: the intent signal exists so the opponent's reaction-lag system can read it and brace before the throw lands (`match.py` ~4200–4247, `intent_signal.py`). It's deliberate, not a bug — but the reviewer's "doesn't feel right" is a legitimate **design-feel** question worth its own discussion (current v0.1 collapses the N−2/N−1 telegraph into a single N→N+1 gap). | **WAI / design discussion** |

---

## Cluster 6 — Bigger design ask

| # | Note | Finding | Class |
|---|---|---|---|
| 6.1 | **Stance never changes** + wants ebb/flow, lower belts stuck in one stance as an experience mechanic (t000 header) | `current_stance` is set once at init (`judoka.py:321`) and **never reassigned** — `_compute_stance_matchup` recomputes the matchup each tick, but no mechanic shifts a fighter's stance mid-match. This is a genuine **missing feature**, and the "lower belts locked in stance / gain experience by being forced out of it" framing is a new design direction, not a bug. Wants a design note before a ticket. | **missing-feature** |

---

## Suggested tickets (for discussion — not yet filed)

1. **Kuzushi debug stream hygiene** (Cluster 1 + 2.1) — gate emission (standing-only, not match-over, verbosity flag), clear the buffer on matte / reset-to-standing / match-end, and order reset events last. *bug/narration.*
2. **Restart-Hajime after ne-waza-escape matte** (2.2) — verify/wire the escape→standing reset into the hajime scheduler. *bug.*
3. **Post-score "tugs at the sleeve" suppression** (3.2) — gate the deferred pull-without-commit rule on intervening throw/phase change. *bug.*  *(could fold into the HAJ-225 narration ticket.)*
4. **"uke airborne and flat" rewording** (3.1) — gate ippon-grade phrasing. *narration.* *(could fold into HAJ-225.)*
5. **Ne-waza escape gate** (4.1) — min-ticks-on-ground + fix GUARD_TOP position-difficulty direction. *bug/calibration.*
6. **Dynamic stance + stance-experience mechanic** (6.1) — design note first, then ticket. *feature.*

No action needed: 5.1 (chase), 5.2 (pressure) — explanation only. 5.3 (intent/commit) — design conversation if the feel still bothers you.
