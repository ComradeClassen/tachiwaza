# Grip Response Selection — the follower's per-tick choice

*Transcribed 2026-06-09 (HAJ-226) from `src/grip_initiative.py` + the cascade wiring in `src/match.py`. This is the A-1 deliverable of [grip-war-and-connective-tissue-v0_2.md](grip-war-and-connective-tissue-v0_2.md) §1.2/1.3: the response-selection model was fully built in code (HAJ-151) but had no design doc. This transcribes the existing behavior and documents the one net-new branch added by HAJ-226, `ACCEPT_BAIT`.*

*Naming discipline (per v0.2 §1.3): **"grip war"** is the design concept — the whole contested grip phenomenon. **"grip response selection"** is the code construct this doc describes — the follower's per-tick choice of how to react to losing the initiative race. They are different scopes; this doc is the latter.*

*Companion to: [grip-war-and-connective-tissue-v0_2.md](grip-war-and-connective-tissue-v0_2.md) (parent), [grip-as-cause.md](grip-as-cause.md), [grip-graph.md](grip-graph.md), [dynamic-stance-and-cross-gripping.md](dynamic-stance-and-cross-gripping.md) (kenka-yotsu / mirrored-stance interactions).*

---

## 1. Where this sits in the grip fight

Each grip-fight phase opens with an **initiative race** ([`grip_initiative.expected_initiative` / `sample_initiative`](../src/grip_initiative.py)): both fighters compute a weighted initiative score (aggressive facet, body archetype, fight_iq, composure, height-derived reach, fatigue, intra-match familiarity), plus a noise term, plus stance-matchup and clock-pressure overlays. The higher sample **reaches first** — the *leader*. The leader seats their lead grip; the other fighter — the *follower* — perceives the commitment (HAJ-149) and picks **one response** from the set below.

The response is a **modulated weighted random draw**, not a deterministic best-choice. The same fighter in the same spot will not always pick the same response; the modulation shifts the *odds*, so a fighter's archetype and facets read as a tendency over a match, not a script. Selection happens in [`select_response`](../src/grip_initiative.py); the mechanical outcome of the chosen branch is applied in [`Match._resolve_grip_cascade`](../src/match.py) → [`_apply_engaged_response`](../src/match.py) / [`_apply_disengage_response`](../src/match.py).

Every selection is logged (`_grip_cascade_log`) and surfaced as a `GRIP_CASCADE_RESPONSE` event with a coach-stream prose rendering, so any branch — including `ACCEPT_BAIT` — is inspectable in the cascade log exactly like the others.

---

## 2. The six response branches

| Branch | Intent | Mechanical outcome (v0.1) |
|---|---|---|
| **`CONTEST`** | Frame the bicep / parry the hand / slap-down. Active disruption of the leader's reach. | Follower seats **only their dominant-hand lead grip** (the reach that interposes on the leader's lead path); the off-hand sleeve drop is dropped. Models the contested race. |
| **`MATCH`** | Mirror the leader's reach (sleeve-and-lapel symmetric). | Follower's **full standard grip pair** seats — a symmetric configuration. |
| **`PURSUE_OWN`** | Commit to your own preferred grip; ignore the leader. A tempo trade. | Same seating as `MATCH` in v0.1 (follower seats their own pair); the strategic difference is that the follower did not try to contest. The cascade log distinguishes the two. |
| **`DEFENSIVE`** | Frame-and-deny; no offensive grip. Pure defense. | Follower seats **only their off-hand sleeve frame** on the leader (no lapel reach). Kenka-yotsu-capable followers may frame with a strip-resistant PISTOL sode-tori clamp instead (HAJ-238). |
| **`DISENGAGE`** | Backstep; reset the exchange. | Leader's grips **break**; both transition to `STANDING_DISTANT`; the closing-phase counter restarts. Follower absorbs a stamina cost; repeated disengages feed ref passivity / non-combativity pressure. |
| **`ACCEPT_BAIT`** *(HAJ-226)* | The counter-fighter who deliberately **does not strip**. Give them the grip, take the reaction. | Leader's grip is **left standing** (not contested, not stripped). The follower seats a **single grip on the leader's committed arm** — the dominant-side sleeve carrying the lead lapel grip — setting up off the commitment. The only engaged response that grips the leader's *loaded* arm by design. |

### Why `ACCEPT_BAIT` is its own mechanic, not a flavor of `DEFENSIVE`

`DEFENSIVE` and `ACCEPT_BAIT` both decline to race for the inside, but they are opposite postures:

- `DEFENSIVE` frames the leader's **off** side and seats a *defensive* grip — it denies the entry and concedes the initiative.
- `ACCEPT_BAIT` grips the leader's **committed** (lead-grip) arm and seats an *offensive setup* — it accepts the entry precisely because the leader has loaded base and posture into that grip, which is the exposure a counter exploits. "Two grips on you is dangerous" is true *unless you are set up to make the opponent pay.*

This is the single mechanic the v0.1 response set was missing (per the 2026-06-04 grip-model diagnosis: everything else flagged was calibration or narration). It is the only branch that does not seat the follower's own offensive grip and does not strip/break a leader edge.

---

## 3. Weights and modulation

Selection draws over the six branches' weights. Weights start at a diffuse base table and are then scaled by a chain of multiplicative modulators (archetype → aggressive facet → loyal-to-plan → fight_iq band → composure → stance matchup → clock-pressure role → fatigue → perception specificity). v0.1 keeps the base table diffuse on purpose so the per-fighter modulation carries the signature.

### 3.1 Base weights

```
CONTEST 1.0   MATCH 1.5   PURSUE_OWN 1.0   DEFENSIVE 0.7   DISENGAGE 0.5   ACCEPT_BAIT 0.4
```

`ACCEPT_BAIT` is the lowest base weight by design: it is a specialist read that should only surface when the modulators that favor it (counter-leaning archetype, patience, fight_iq, composure) line up.

### 3.2 Archetype bias

The archetypes split into **proactive** (take the grip war to the opponent, rarely concede a grip on purpose) and **counter-leaning** (exploit the opponent's commitment):

| Archetype | Signature branches | `ACCEPT_BAIT` |
|---|---|---|
| `GRIP_FIGHTER` | CONTEST ×1.6, MATCH ×1.2 | ×0.5 — contests; rarely concedes |
| `MOTOR` | CONTEST ×1.3 | ×0.5 — pressures forward, doesn't sit on a counter |
| `EXPLOSIVE` | PURSUE_OWN ×1.8 | ×1.8 — patient build → capitalize on the commit |
| `LEVER` | PURSUE_OWN ×1.2, DEFENSIVE ×1.1 | ×1.5 — counters off the opponent's commitment |
| `GROUND_SPECIALIST` | DEFENSIVE ×1.4, PURSUE_OWN ×1.1 | ×1.4 — accepts the grip on the way to the mat |

There is no dedicated `COUNTER_FIGHTER` archetype in the model; the "counter-fighter" of §1.2 of the parent doc is expressed as the counter-leaning archetypes above **plus** the facet/capability profile below.

### 3.3 Facets, capability, and context

- **Aggressive facet** (patient↔aggressive). Patient profiles favor `ACCEPT_BAIT` (×1.3 at aggressive=0) and aggressive ones shun it (×0.7 at aggressive=10): `×(0.7 + 0.6·(1−aggr))`. Accepting the bait is a *patient* read, not a *passive* one — distinct from `DEFENSIVE`/`DISENGAGE`, which key off pure low aggression.
- **fight_iq band.** Low IQ (<0.4) defaults to safe `MATCH` and damps `ACCEPT_BAIT` ×0.4 (baiting needs a read novices lack). Elite IQ (>0.7) boosts `ACCEPT_BAIT` ×1.4 (reads when to invite the grip).
- **Composure.** Rattled (<0.4) damps `ACCEPT_BAIT` ×0.6 (inviting a grip while loading a counter takes nerve). Composed (>0.7) boosts it ×1.3.
- **Stance matchup.** In `MIRRORED` (kenka-yotsu), the patience-rewarded variant lifts `ACCEPT_BAIT` ×1.3 alongside the existing DEFENSIVE/PURSUE_OWN boosts — crossing-grip contest is messy, so accepting the cross and countering off it is the cleaner read.
- **Clock-pressure role.** Either role (`leading` or `trailing`) damps `ACCEPT_BAIT` ×0.5: a leader protecting a lead won't gift a grip, and a trailing fighter needs the grip *now*, not a reaction two beats later.
- **Fatigue.** Loading a counter off a conceded grip is metabolically expensive; `ACCEPT_BAIT` scales by `max(0.3, 1 − 0.6·fatigue_frac)`.
- **Perception specificity.** Vague perception (high leader disguise, <0.3) pushes the follower toward safer responses and damps `ACCEPT_BAIT` ×0.6 — you can't bait a commit you can't read.

Net effect: a patient, high-IQ, composed `EXPLOSIVE`/`LEVER` counter-fighter selects `ACCEPT_BAIT` at a materially higher rate than an aggressive `MOTOR`/`GRIP_FIGHTER` pressure fighter, and the clock, fatigue, and a fogged read all suppress it — matching the §1.2 design intent (*up* by counter-archetype / composure / fight_iq, *down* by clock pressure and fatigue).

---

## 4. Familiarity bookkeeping

After resolution, the per-match familiarity tally moves: the leader is credited with winning the lead-grip race and the follower with losing it, **except** `DISENGAGE`, which flips the win/loss (the follower successfully denied the leader's plan). `ACCEPT_BAIT` stays on the leader-won side of the ledger: the leader *did* land their grip — the follower conceded it deliberately. (Whether a successful bait-and-counter should later flip familiarity is left as a v0.2 calibration question; v0.1 keeps it simple.)

---

## 5. Open questions / v0.2 calibration

- **`PURSUE_OWN` vs `MATCH`** are mechanically identical in v0.1 (distinguished only in the log). A real tempo/positioning difference is deferred.
- **`ACCEPT_BAIT` payoff is currently structural, not yet scored.** The branch correctly seats the counter-loading grip and leaves the leader's grip standing; the *reward* for having done so (a counter-throw window off the leader's committed arm) rides on the existing throw/counter machinery rather than a bespoke bonus. Whether the bait needs an explicit counter-window boost is a v0.2 question.
- **Base-weight tightening.** The base table is deliberately diffuse; v0.2 can tighten it once the modulation is calibrated against match data.
- **Familiarity flip for a paid-off bait** — see §4.
