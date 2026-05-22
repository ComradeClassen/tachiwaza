# Catalog architecture — sibling catalogs with auxiliary loading

*v0.1, drafted 2026-05-21 alongside HAJ-217. Captures the pattern that
emerged from the tachiwaza + ne-waza split in HAJ-211 / HAJ-215, and
documents the alternative (unified catalog) as deferred.*

---

## The pattern: sibling catalogs, auxiliary loading

Hajime's vocabulary substrate is split across two catalogs:

- **Tachiwaza** ([data/techniques.yaml](../../data/techniques.yaml)) —
  stand-up throws. Schema in [src/technique_catalog.py](../../src/technique_catalog.py).
- **Ne-waza** ([data/ne_waza_techniques.yaml](../../data/ne_waza_techniques.yaml),
  [data/ne_waza_positions.yaml](../../data/ne_waza_positions.yaml),
  [data/defensive_struts.yaml](../../data/defensive_struts.yaml)) —
  ground techniques, dominant positions, defensive struts. Schema in
  [src/ne_waza_catalog.py](../../src/ne_waza_catalog.py).

The catalogs are **siblings, not parent-child**. Tachiwaza grips are
hand-on-garment at named regions; ne-waza connections are body-pressure /
anatomical wraps / limb triangles / lapel crosses that don't fit the
tachiwaza grip taxonomy. The two graphs share no schema and never
co-mingle data — they're authored, loaded, and validated independently.

But they're not fully disjoint. Tachiwaza throws declare
`ne_waza_followup_preferences` — which ne-waza techniques the engine
should weight after a successful throw. These are **cross-catalog
references**, and validation needs to resolve them.

The pattern: **the tachiwaza validator loads the ne-waza catalog as
auxiliary data**, then resolves followup refs against the union of
both catalogs. The ne-waza catalog itself does not know or care that
tachiwaza references into it.

```
tachiwaza_validator(tachiwaza_catalog, ne_waza_known_ids=None)
  - Default: tries to load ne-waza catalog; if it fails, skip
    cross-catalog checks with one summary warning rather than emitting
    per-reference false positives.
  - Explicit: caller passes the set of ne-waza technique_ids.
  - Cross-catalog check resolves a ref if it exists in EITHER catalog.

ne_waza_validator(ne_waza_catalog)
  - Pure ne-waza. No tachiwaza loading. The cross-catalog edges are
    one-directional (tachiwaza → ne-waza, via followup_preferences).
```

This keeps each validator's primary responsibility (its own catalog's
integrity) intact while resolving the one cross-catalog edge in v0.1.

## Why not a unified catalog

The natural alternative: one catalog with one schema, both stand-up and
ground techniques as entries. We rejected this in HAJ-212 design and the
reasons hold:

1. **The schemas don't unify.** Tachiwaza's `canonical_grip_signatures`,
   `kuzushi_vector_categories`, and `failed_throw_consequence` have no
   ne-waza counterparts. Ne-waza's `required_connections`,
   `applicable_defensive_struts`, `induced_transitions`, and
   `parent_position` have no tachiwaza counterparts. A unified schema
   would be the union with most fields optional — a shape that hides
   authoring errors (a missing `canonical_grip_signatures` on a throw
   reads as "ne-waza entry" rather than "incomplete throw").

2. **The mechanics diverge.** Throws resolve in 1–3 ticks via grip /
   kuzushi / commitment. Ne-waza resolves via connection-quality
   hysteresis, OsaekomiClock, danger zones, and induced transitions
   (per ne-waza-vocabulary-system addendum §6.5). The resolver paths
   are different code; sharing a catalog wouldn't share resolver logic.

3. **Authoring rhythms differ.** Tachiwaza authoring is per-throw with
   grip-and-kuzushi authoring as the bottleneck. Ne-waza authoring is
   per-position with strut-cross-referencing as the bottleneck. Bundling
   these in one file would make per-batch validation slower and noisier.

4. **The cross-catalog edges are sparse.** `ne_waza_followup_preferences`
   is the only field that bridges. v0.2 may add `tachiwaza_setup_for`
   on ne-waza techniques (the reverse edge) but the edge count stays
   small. Two siblings with one validator-resolved bridge is cheaper
   than a unified schema.

## When to revisit the unified pattern

If v0.2 or beyond introduces:

- More than 3–4 distinct cross-catalog edge types (current: 1)
- A resolver path that needs to walk freely between catalogs at runtime
  (current: edges are consulted at authoring + at one specific resolver
  branch, not as graph traversal)
- A shared schema field that authors keep getting wrong because the
  schema duplication makes drift easy (current: fields don't overlap)

— then unifying becomes worth reconsidering. None of these conditions
hold in v0.1.

## v0.1 implementation notes

- **Auxiliary loading is best-effort.** The tachiwaza validator tries
  to load the ne-waza catalog from the default path
  ([data/ne_waza_techniques.yaml](../../data/ne_waza_techniques.yaml)).
  If loading fails (file absent, syntax error), the validator emits
  **one** summary warning and skips cross-catalog checks rather than
  fabricating per-reference false positives. This keeps the tool usable
  in half-set-up environments (fresh clone before ne-waza authoring
  lands; engine teams running tachiwaza validation in isolation).

- **In-memory vs file APIs.**
  - `validate_catalog(catalog, *, ne_waza_known_ids=None)` — pure
    in-memory; caller decides whether to provide cross-catalog ids.
    `None` skips the cross-catalog check entirely.
  - `validate_catalog_file(path, *, ne_waza_techniques_path=...)` —
    file-level entry point; handles the best-effort load and skip-with-warning
    behavior.

- **Cross-catalog dangling is an error, not a warning.** Pre-HAJ-217
  the followup check raised warnings because the ne-waza catalog didn't
  exist yet. With the catalog authored, an unresolved ref is now a real
  bug — the throw points at a technique that doesn't exist anywhere.
  Promoted to error severity.

- **Pre-commit hook unchanged.** The hook already invokes both validators
  on any catalog file change; the tachiwaza validator now automatically
  picks up cross-catalog checks via default-path loading, and the
  ne-waza catalog is in the same repo so the path resolves naturally.

## Cross-references

- [src/catalog_validator.py](../../src/catalog_validator.py) — tachiwaza validator, owns the cross-catalog edge.
- [src/ne_waza_catalog_validator.py](../../src/ne_waza_catalog_validator.py) — ne-waza validator, primary responsibility only.
- [design-notes/triage/ne-waza-vocabulary-system.md](ne-waza-vocabulary-system.md) — ne-waza schema spec.
- [design-notes/triage/ne-waza-vocabulary-system-addendum-consumption-semantics.md](ne-waza-vocabulary-system-addendum-consumption-semantics.md) — consumption semantics addendum (HAJ-216).

---

*End of v0.1.*
