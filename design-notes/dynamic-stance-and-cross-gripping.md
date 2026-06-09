# Dynamic Stance & Cross-Gripping — design pass v0.1

*Design pass opened 2026-06-04 from a match-log review note (seed 1349309793). Two linked gaps: (1) a fighter's stance is fixed for the whole match, and (2) the engine never seats cross-grips, so the kenka-yotsu grip fight never actually happens. This is a design note, not an implementation spec — it captures the model, the open questions, and a phasing proposal so we can ticket deliberately. Status: draft for discussion.*

---

## 1. Why this exists

Two reviewer observations:

- **Stance is static.** The match header prints `Stance matchup: MATCHED (ai-yotsu)` and it never changes. Real judoka ebb and flow between stances within a match; some are only comfortable in one and suffer when forced out of it. The reviewer wants that discomfort to be **how lower-belt judoka gain experience** — forced inexperience converted into experience.
- **Cross-gripping doesn't exist.** We have no model for the cross-grip / same-side-lapel grip that defines the kenka-yotsu fight. The grip war currently only ever plays out as the symmetric sleeve-and-lapel pair.

These are one design surface: stance *is* the grip map, and cross-gripping is the tactic that lives in the seams between stances.

---

## 2. What exists today (substrate already built)

The engine has more of this modeled than the match log reveals:

- **`Stance`** (`src/enums.py:96`): `ORTHODOX` / `SOUTHPAW` — the handedness lead. Set once at `Judoka` init (`judoka.py:321`) and **never reassigned** anywhere in the codebase.
- **`StanceMatchup`** (`src/enums.py:104`): `MATCHED` (ai-yotsu — same stance) / `MIRRORED` (kenka-yotsu — opposite). Derived each tick from the two fighters' stances via `StanceMatchup.of(...)`, so the matchup computation is already dynamic — only the *inputs* are frozen.
- **Per-grip `stance_parity`** (`src/force_envelope.py`, HAJ-51): every grip type already declares a leverage multiplier (range 0.7–1.3) that shifts between matched and mirrored. Standard collar/lapel slightly favor MATCHED; **`CROSS` strongly favors MIRRORED (matched 0.80 / mirrored 1.25)** and `PISTOL` similarly (0.85 / 1.20). The model already "knows" cross-grips are the kenka-yotsu weapon — it just never deploys them.
- **`unconventional_clock`** (`grip_graph.py`): `CROSS` / `BELT` / `PISTOL` grips are flagged `is_unconventional()` and run a passivity clock that draws referee shido pressure if they don't lead to an attack — exactly the real-judo regulation that a cross-grip must be immediately attacking.
- **Grip seating** (`grip_graph.attempt_engagement`, `match._seat_grips_for`): only ever seats the symmetric `LAPEL_HIGH` + `SLEEVE_HIGH` pair. Cross/pistol grips are never created by the engine.

**So the gap is two concrete things:** stance never *changes*, and cross-grips are never *seated/selected*. The leverage math, the matchup derivation, and the regulation clock are already there.

---

## 3. Part A — Dynamic stance

### 3.1 Stance as fluid state, not a fixed attribute

Replace the single frozen `current_stance` with a small stance *state*:

- **`base_stance`** — the fighter's natural/handedness lead (today's `current_stance`). Doesn't change.
- **`current_stance`** — the stance they're actually carrying this exchange. Can shift.
- **`stance_comfort`** — a small **vector** of comfort axes (0–1), not a single value (resolved §6.3): per-stance comfort (`ORTHODOX` / `SOUTHPAW`) **and** a separate kenka-yotsu / cross-grip comfort axis. Base stance starts high; off-stance and kenka-yotsu axes start low and are **belt-gated** (see 3.3). The switch-cost term reads per-stance comfort; cross-grip fluency reads the kenka-yotsu/cross-grip axis.

The match recomputes `StanceMatchup.of(a.current_stance, b.current_stance)` exactly as it does now — no change to downstream consumers (grip cascade, stance_parity, sumi-gaeshi door). Only the inputs become live.

### 3.2 What makes a fighter switch

Stance changes are a *deliberate or pressured* event, not free. Candidate triggers:

- **Tactical choice** — a fighter switches to deny the opponent their preferred matchup (e.g. force kenka-yotsu against a pure ai-yotsu specialist), or to open their own signature (sumi-gaeshi already keys off MIRRORED).
- **Forced by grip pressure** — losing the grip war / getting steered can rotate a fighter off their stance involuntarily. This is the "forced out of comfort" path.
- **Fatigue / composure** — a gassed or rattled fighter drifts toward their comfortable base stance and resists switching.

Each switch carries a **cost in the off-stance proportional to `1 - stance_comfort[target]`**: a brief window of reduced grip initiative, weaker kuzushi, slower reach — i.e. you're clumsy in the unfamiliar stance. Comfortable switchers (high comfort in both) pay almost nothing; one-stance fighters pay a lot.

### 3.3 The experience loop (the reviewer's core ask)

Belt rank gates *initial* stance flexibility, and being forced out of comfort is how you earn more of it:

- **Lower belts** start with high comfort in `base_stance` and near-zero in the off-stance. When dragged into the off-stance (or kenka-yotsu against an opposite-handed opponent) they're at a real disadvantage — clumsy grips, conceded initiative. This is intended and visible.
- **Surviving / fighting through off-stance exchanges accrues stance XP** toward `stance_comfort[off_stance]`. Inexperience converts to experience exactly by being forced through the discomfort.
- **Higher belts** have already paid that tuition: comfort in both stances is high, so they ebb and flow freely (the fluidity the reviewer wants to see in elite matches).

This ties directly into the progression/grading layer (Ring 3 / career) — stance comfort is a trainable, gradable attribute, and "can fight both stances" becomes a real mark of an advanced judoka. **Open design question:** does stance XP accrue only in live matches, or also in randori/training sessions? (Leans: both, with matches worth more.)

---

## 4. Part B — Cross-gripping (kenka-yotsu)

### 4.1 What a cross-grip is

In kenka-yotsu (opposite stances), the lead hands collide and the grip fight becomes a battle for the inside position — pommeling, and the option to reach **across** to the opponent's same-side lapel (the cross grip) instead of the orthodox opposite-lapel grip. Cross-grips are powerful but **regulated**: you must attack off them quickly or concede passivity (a shido). The engine's `unconventional_clock` already models this.

### 4.2 Making the engine actually seat/select cross-grips

The grip cascade (`grip_initiative.py` five-branch model + `match._resolve_grip_cascade`) is the natural home. Today every branch seats the symmetric lapel/sleeve pair. Add cross-grip as a **grip-target choice** available primarily in MIRRORED:

- When the matchup is MIRRORED, a fighter (especially a grip specialist, or one whose signature wants the inside) can elect a **cross grip** instead of the orthodox lapel — seating a `CROSS` (or `PISTOL`) edge whose `stance_parity` already rewards it in kenka-yotsu.
- The `unconventional_clock` is already wired to demand a follow-up attack, so the "cross-grip-then-attack-or-get-penalized" rhythm comes mostly for free.
- Cross-grip selection is weighted by archetype/fight_iq (GRIP_FIGHTER and high-IQ fighters reach for it; novices don't), and gated by stance comfort — a fighter clumsy in the current stance shouldn't be fluently cross-gripping.

### 4.3 The kenka-yotsu grip fight as the missing texture

This also gives MIRRORED matches their own *feel*: the lead-hand pommeling, the fight for the inside, the threat of the cross grip and the shido clock on it. Right now MATCHED and MIRRORED differ only by quiet leverage multipliers; cross-gripping is what makes kenka-yotsu *read* as a different fight.

### 4.4 Cross-grip as disruptor — and the experienced counter (resolved 2026-06-04)

The cross-grip is **both a tactical weapon and a pressure-forced reaction**, and its most important role is as a *disruptor*:

- **Upsetting a dominant fighter.** When one fighter has been winning the grip war, the other can throw on a cross-grip to **break the pattern**: the dominant fighter now has to divert attention to *stripping the cross* (it threatens an immediate attack and carries the shido clock against the gripper, so it can't be ignored). The cross interrupts their rhythm and forces a response.
- **The experienced counter.** A skilled fighter doesn't just defend the cross — they **use it as a transition**. From the cross-grip exchange (theirs or the opponent's), an experienced judoka finds their way back to their *preferred* grip: the cross creates the scramble, and they exploit the scramble to seat the grip they actually wanted. So cross-gripping rewards experience on *both* sides — clumsy fighters get tangled in it; skilled fighters route through it.

This makes the cross-grip a **momentum lever** in the grip war, not just an alternate grip target: a way for the losing side to disrupt, and a way for the skilled side to convert disruption into position. It leans on the strip calibration (HAJ-224) — stripping the cross is exactly the kind of mid-exchange strip that work enables — and on stance comfort gating who can wield it fluently.

### 4.5 PISTOL grips — defensive frames and sode (resolved 2026-06-04)

`PISTOL` is **in** for v0.1 alongside `CROSS`. It already has kenka-yotsu-favoring `stance_parity` (0.85 / 1.20) and the unconventional shido clock. Two roles:

- **Defensive** — the pistol/end-of-sleeve grip as a *frame* that denies the opponent's attack without seating an offensive grip (pairs with the cascade's DEFENSIVE branch).
- **Offensive** — sleeve-end control is the setup for **sode-tsurikomi-goshi** and the sode family. A fighter whose signature is a sode throw should be able to seat a pistol grip as the entry to it.

---

## 5. How the two halves interlock

```
base_stance ──┐
              ├─► current_stance ──► StanceMatchup.of() ──► MATCHED / MIRRORED
opponent  ────┘                                                  │
                                                                 ├─ MATCHED → orthodox sleeve+lapel war (today)
                                                                 └─ MIRRORED → kenka-yotsu: cross-grip option,
                                                                       lead-hand fight, stance_parity rewards
                                                                       CROSS/PISTOL, unconventional shido clock
stance_comfort[current] ──► switch cost, grip fluency, cross-grip eligibility
        ▲
        └── stance XP from fighting through off-stance exchanges (belt-gated start)
```

Dynamic stance *creates* kenka-yotsu situations; cross-gripping is *what you do* in them; stance comfort *gates how well* you do it; and getting forced into the discomfort is *how you get better at it*.

---

## 6. Resolved decisions (2026-06-04 design pass)

1. **Stance switch agency — RESOLVED: both tactical and pressure-forced.** A fighter can switch deliberately (deny the opponent's matchup, open a signature) *and* be rotated off-stance involuntarily by losing the grip war / getting steered. See §4.4 for the disruptor role this enables.
2. **Switch cost shape — RESOLVED: hybrid.** A short flat *settling window* (the visible switch beat, prevents instant fluent switching, gives narration its moment) layered on a *continuous `(1 − comfort)` term* (the persistent disadvantage that carries the experience story and fades as comfort grows). Window serves game-feel; continuous term serves progression.
3. **Comfort granularity — RESOLVED: richer vector from v0.1.** Model multiple comfort axes from the start, not just base/off: **per-stance comfort** (orthodox / southpaw) AND a separate **kenka-yotsu / cross-grip comfort** (how well the fighter handles the mirrored inside-fight). This makes real archetypes expressible immediately — the kenka-yotsu hunter who *seeks* opposite stances, the cross-grip artist, the stance-ambidextrous fighter who still dislikes the inside fight. Each axis is independently trainable (its own XP track) and gradable. The switch-cost continuous term and cross-grip eligibility read from the relevant axis (off-stance switch → per-stance comfort; cross-grip fluency → kenka-yotsu/cross-grip comfort).
4. **XP source — RESOLVED.** Training/randori accrue stance XP *very lightly*, **except** for fighters who've already crossed an advanced threshold (they keep developing meaningfully in training). Matches give substantially more.
5. **Cross-grip scope — RESOLVED: CROSS and PISTOL both in v0.1.** PISTOL serves defensive frames and offensive sode setups (see §4.5).
6. **Narration — RESOLVED: yes.** Kenka-yotsu and cross-grips get their own prose family (the lead-hand fight, "reaches across for the cross grip," the passivity/shido warning, stance-switch lines). Folds into the HAJ-225 narration line of work.
7. **Header honesty — RESOLVED: live stance thread.** The static `Stance matchup: …` header becomes the opening state of a running thread; each mid-match switch emits a stance event — debug `[stance] Sato switches to southpaw — now kenka-yotsu` and a mat-side prose line ("Sato drops into southpaw, forcing the cross-grip fight"). The eventual Ring 6 viewer shows current matchup as a live indicator; the text stream carries it as events.

---

## 7. Phasing proposal (not yet ticketed)

- **Phase 1 — Dynamic stance state (Ring 1). ✅ IMPLEMENTED (HAJ-237).** `base_stance` / `current_stance` / the `stance_comfort` vector (per-stance + kenka-yotsu/cross-grip axes); make `_compute_stance_matchup` read live state; both switch triggers (tactical + grip-pressure-forced) with the hybrid cost (settling window + continuous `(1−comfort)` term). Live stance-event thread in the stream + header. *Landed as `src/stance.py` (comfort model + switch decision) wired into `match._tick` via `_evaluate_stance_switches`; cost applied as a grip-initiative penalty in `_stage_grip_cascade`; `STANCE_CHANGE` events carry mat-side `coach_prose`. Tactical-switch AI weighting by archetype/fight_iq is present in seed form; the fuller deliberate-strategy layer is still Phase 4. Tests: `tests/test_dynamic_stance.py`.*
- **Phase 2 — Cross-grip seating (Ring 1).** MIRRORED cross-grip cascade branch seating `CROSS` and `PISTOL` edges (incl. PISTOL defensive frame + sode setup); cross-grip-as-disruptor + the experienced "route through it to my preferred grip" counter (§4.4); lean on existing `stance_parity` + `unconventional_clock` and the HAJ-224 strip work. Kenka-yotsu narration family.
- **Phase 3 — Stance comfort & XP (Ring 1 ↔ Ring 3).** Belt-gated initial comfort per axis; per-axis XP accrual (matches > training; training near-zero except past an advanced threshold); integrate with the grading/progression layer so "fights both stances / wins the kenka-yotsu fight" are trainable, gradable marks of advancement.
- **Phase 4 — AI tactical stance choice.** Deliberate stance-switching as strategy (deny matchup, open signature), weighted by archetype/fight_iq/comfort.

Suggested home: a tracking issue in **Design & Triage** holding this design pass, graduating into Ring 1 (Phases 1–2) and Ring 3 (Phase 3 progression hook) implementation tickets. The §6 questions are now resolved, so Phase 1–2 are ready to scope into tickets when you want to build.
