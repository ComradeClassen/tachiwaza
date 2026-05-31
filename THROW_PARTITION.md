# Throw Partition — engine-usable standing throws

Read-only audit. Enumerates every `ThrowID`, its worked-template status, its
data source, and its live-reachability. Source of truth at audit time:
`src/throws.py`, `src/worked_throws.py`, `src/perception.py`, `src/main.py`,
`src/run_match.py`, `src/action_selection.py`, `src/availability.py`.

## The whole `ThrowID` enum (13 members)

Defined in [`src/throws.py:59`](src/throws.py:59) (`class ThrowID`). There are
**no other ThrowID definitions anywhere** in the tree.

| # | ThrowID | Template? | Data source / origin | Live? (assigned a `throw_profile`) |
|---|---------|-----------|----------------------|-------------------------------------|
| 1 | `SEOI_NAGE` | **TEMPLATED** (`SEOI_NAGE_MOROTE`) | hardcoded Python | **LIVE** — Tanaka, Yamamoto, Renard |
| 2 | `UCHI_MATA` | **TEMPLATED** | hardcoded Python | **LIVE** — Sato, Kimura |
| 3 | `O_SOTO_GARI` | **TEMPLATED** | hardcoded Python | **LIVE** — Tanaka, Sato, Yamamoto, Kimura |
| 4 | `O_UCHI_GARI` | **TEMPLATED** | hardcoded Python | **LIVE** — Tanaka, Sato, Renard (+clones) |
| 5 | `KO_UCHI_GARI` | **TEMPLATED** | hardcoded Python | **LIVE** — Tanaka, Sato, Renard (+clones) |
| 6 | `HARAI_GOSHI` | **TEMPLATED** | hardcoded Python | **LIVE** — Tanaka, Sato (+clones) |
| 7 | `TAI_OTOSHI` | **TEMPLATED** | hardcoded Python | **LIVE** — Tanaka, Renard (+Yamamoto) |
| 8 | `SUMI_GAESHI` | **NO-TEMPLATE** | hardcoded Python | **LIVE** — Sato, Kimura, Renard |
| 9 | `DE_ASHI_HARAI` | **TEMPLATED** | hardcoded Python | defined, never assigned |
| 10 | `O_GOSHI` | **TEMPLATED** | hardcoded Python | defined, never assigned |
| 11 | `HARAI_GOSHI_CLASSICAL` | **TEMPLATED** | hardcoded Python | defined, never assigned |
| 12 | `TOMOE_NAGE` | **TEMPLATED** | hardcoded Python | defined, never assigned |
| 13 | `O_GURUMA` | **TEMPLATED** | hardcoded Python | defined, never assigned |

Template column = whether `worked_template_for(throw_id)` returns non-`None`
([`src/worked_throws.py:842`](src/worked_throws.py:842)). `WORKED_THROWS`
([`worked_throws.py:824`](src/worked_throws.py:824)) holds 12 entries — every
ThrowID **except `SUMI_GAESHI`**.

## Data source — every throw is hardcoded; none come from the Kodokan YAML

This needs to be said plainly because the question framing assumes some throws
are YAML-sourced: **none of the 13 ThrowIDs are loaded from
`data/techniques.yaml`.** Every one originates from hardcoded Python:

- **Definition / display + grip prereqs:** `THROW_REGISTRY` and `THROW_DEFS`
  literals in [`src/throws.py`](src/throws.py) (lines 222 and 334).
- **Physics template (if any):** module-level literals in
  [`src/worked_throws.py`](src/worked_throws.py), collected into `WORKED_THROWS`.

The Kodokan/Gokyo YAML you added (`data/techniques.yaml`, loaded by
`technique_catalog.load_catalog`, [`technique_catalog.py:603`](src/technique_catalog.py:603))
is a **parallel catalog keyed by string `technique_id`**, not by `ThrowID`. It
is *not* a source for any throw definition. It touches the ThrowID world at
exactly one seam — the bridge in
[`src/availability.py:54`](src/availability.py:54):

```python
THROW_TO_TECHNIQUE_ID: dict[ThrowID, str] = {
    ThrowID.SEOI_NAGE:              "seoi_nage",
    ...
    ThrowID.HARAI_GOSHI:            "harai_goshi",
    ThrowID.HARAI_GOSHI_CLASSICAL:  "harai_goshi",   # note: two ThrowIDs → one catalog id
    ...
}
```

The catalog is consulted as a **Stage-1 availability / proficiency / naming
overlay** (`action_selection`, `availability`, `resolver`, `orchestrator`); the
throw that actually fires and its physics still come from the hardcoded
`ThrowDef` / worked template. So in the ThrowID partition there is no
"YAML-sourced vs legacy-hardcoded" split — **all 13 are legacy-hardcoded.**

## Live vs. defined-but-never-assigned

"Live" here means *can fire a scoring commit*. The scoring-commit selector
gates on `throw_profiles`, not merely vocabulary
([`action_selection.py:1027-1031`](src/action_selection.py:1027)):

```python
td = THROW_DEFS.get(tid)
if td is None:
    continue
if judoka.capability.throw_profiles.get(tid) is None:
    continue   # <-- no profile ⇒ never a scoring candidate
```

**Construction paths that populate `throw_profiles`:** only
[`src/main.py`](src/main.py) (the demo rosters: Tanaka, Sato, Renard; Yamamoto
and Kimura are clones of Tanaka/Sato). The union of assigned ThrowIDs across
all of them is the 8 marked **LIVE** above.

**`run_match.py` — the Godot/production runner — assigns no profiles at all.**
[`run_match.py:129-132`](src/run_match.py:129):

```python
throw_vocabulary=list(THROW_REGISTRY.keys()),   # all 13 in vocabulary
throw_profiles={},                              # but zero profiles
signature_throws=[],
```

So through the actual production entry point, *no throw is live as a scoring
commit* — every candidate trips the `throw_profiles.get(tid) is None` guard.
Worth flagging on its own: today only `main.py`'s demo fighters can throw.

**Defined but never assigned (5):** `DE_ASHI_HARAI`, `O_GOSHI`,
`HARAI_GOSHI_CLASSICAL`, `TOMOE_NAGE`, `O_GURUMA`. These are wired into engine
support tables (the availability bridge, `execution_quality` calibration,
`intent`, `counter_windows`, `compromised_state`) but never appear in any
fighter's `throw_profiles`. One subtlety: `DE_ASHI_HARAI` is also used as a
**sentinel default** for sen-sen-no-sen counters at
[`match.py:4715`](src/match.py:4715)
(`effective_throw_id = attacker_throw_id or ThrowID.DE_ASHI_HARAI`) — a metadata
fallback, not a fighter throwing it.

## ⚠ Flag: LIVE **and** NO-TEMPLATE → fires off the legacy two-factor fallback

Intersection of {LIVE} and {NO-TEMPLATE} = **`SUMI_GAESHI`, and only
`SUMI_GAESHI`.**

That is the lone throw that currently exercises the legacy path in
[`perception.actual_signature_match`](src/perception.py:126):

```python
template = worked_template_for(throw_id)
if template is not None:
    base = signature_match(template, ...)          # worked-template path
else:
    # --- Legacy two-factor path ---
    td_ = THROW_DEFS.get(throw_id)
    if td_ is None:
        return 0.0
    grip_score = 0.5 if graph.satisfies(td_.requires, ...) else 0.0
    ...
    kuzushi_score = 0.5 if is_kuzushi(...) else 0.0
    base = grip_score + kuzushi_score
```

Because `SUMI_GAESHI` has a `THROW_DEFS` entry
([`throws.py:532`](src/throws.py:532)) but no worked template, it lands in the
`else` branch — the two-factor `grip_score + kuzushi_score`. It is live on Sato,
Kimura, and Renard. This is the throw whose existence keeps the legacy fallback
reachable.

## The two questions, answered plainly

**(a) If you retire the no-template (legacy-signature) throw and keep only the
templated ones, do all remaining live throws have worked templates?**

Yes — with one definitional caveat. `SUMI_GAESHI` is the *only* live throw
without a template. Remove it from the rosters and the live set becomes
`{SEOI_NAGE, UCHI_MATA, O_SOTO_GARI, O_UCHI_GARI, KO_UCHI_GARI, HARAI_GOSHI,
TAI_OTOSHI}` — all 7 templated. So **yes.**

The caveat: I read "retire legacy" as *retire the template-less throw*, **not**
"keep only YAML-sourced throws." Taken literally, *no* ThrowID is YAML-sourced
(see Data source), so "keep only Kodokan-YAML throws" would empty the ThrowID
set entirely. The migration that's actually in flight is template-coverage of
the hardcoded ThrowIDs, not a swap to a YAML registry.

**(b) Would the legacy `actual_signature_match` fallback path then be
unreachable?**

For the scoring path: **yes, dynamically.** The `else` branch is entered only
when `worked_template_for(throw_id) is None`. `SUMI_GAESHI` is the sole ThrowID
that returns `None`. If it is fully removed from the `ThrowID` enum, then
`WORKED_THROWS` covers 12/12 members and `worked_template_for` can never return
`None` for any possible argument — the `else` block becomes statically dead.
If `SUMI_GAESHI` is merely dropped from rosters but left in the enum, the branch
is unreachable in practice but still live code (any caller passing that
ThrowID — e.g. a counter selection — would re-enter it).

**Important — this does NOT retire `THROW_DEFS`.** Even fully-templated throws
still depend on their `THROW_DEFS` entry on the live commit path:

- the selector requires `THROW_DEFS.get(tid) is not None`
  ([`action_selection.py:1027`](src/action_selection.py:1027));
- the grip-presence gate reads `td.requires` / `requires_both_hands`
  ([`grip_presence_gate.py`](src/grip_presence_gate.py));
- spatial-mismatch, stance-preference, and chase use `THROW_DEFS`
  ([`match.py:3266`](src/match.py:3266),
  [`perception.py:182`](src/perception.py:182)).

So retiring the legacy *signature-scoring* fallback (the two-factor
`grip_score + kuzushi_score`) is safe once `SUMI_GAESHI` is templated or
removed — but the `THROW_DEFS` registry itself is still load-bearing for all 13
throws and is not part of what becomes unreachable.

## Referenced only by tests (test-side breakage if retired)

No ThrowID is *exclusively* test-referenced — all 13 have engine references. But
the 5 **defined-but-never-assigned** throws — `DE_ASHI_HARAI`, `O_GOSHI`,
`HARAI_GOSHI_CLASSICAL`, `TOMOE_NAGE`, `O_GURUMA` — are never exercised *as a
fighter's throw* outside tests. Their behavioral coverage lives entirely in the
suite (heaviest in `tests/test_backfilled_throws.py` (22 refs),
`tests/test_worked_throws.py` (14), `tests/test_haj143_drive_throws.py`,
`test_hip_block.py`, `test_stance_parity.py`, `test_haj155_sacrifice_door.py`,
`test_haj156_locomotion.py`, `test_haj161_collar_grip.py`). Retiring any of them
breaks those tests but no live roster.

`SUMI_GAESHI` itself appears in tests too (e.g. `test_haj155_sacrifice_door.py`,
`test_stance_parity.py`) in addition to being live — so removing it would
require both roster and test edits.
