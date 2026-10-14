# Decision log

One entry per choice that could reasonably have gone another way.  
Format (from assessment brief):

```markdown
## D-XX — Title
**Context:** …
**Options:** (a) … (b) … (c) …
**Chose:** …
**Evidence:** …
**Reversal trigger:** …
```

## Seeded from DESIGN (to be expanded with evidence during build/eval)

## D-01 — Alias auto on uniqueness only (no conf floor), ignore source
**Context:** Alias map mixes confirmed_order / inferred_match / manual_import with conf in {0.55, 0.72, 1.0}.
**Options:** (a) confirmed_order ∧ high conf (b) conf ≥ 0.72 only (c) any in-date unique active alias.
**Chose:** (c) — revised 2026-10-14 from (b).
**Evidence:** Train: all 9 `alias_low_trust` @0.55 matched GT; hard review was abstain cost with 0 FP saved on this set. See MINDLOG.
**Reversal trigger:** Low-conf unique alias FPs on holdout / another tenant’s alias mix → restore floor 0.72 or 1.0, or add source belt.

## D-02 — Low-trust alias hard review — retracted
**Context:** Unique active alias with conf &lt; 0.72.
**Options:** (a) hard review (b) fall through to text (c) auto anyway if unique.
**Chose:** (c) as of 2026-10-14 (was (a)).
**Evidence:** Same as D-01; 9/9 train low-conf uniques correct.
**Reversal trigger:** Same as D-01 — this assessment’s 0.55 band may not generalise.

## D-03 — Superseded alias → strip -OLD only if text confirms
**Context:** Map hits only `*-OLD` / disabled.
**Options:** (a) hard review (b) fall through to text (c) strip -OLD to active sibling always (d) strip -OLD → auto only if live code ∈ text candidates.
**Chose:** (d) as of 2026-10-14 (was (b)).
**Evidence:** Train `abstain_miss`+SKU: all 29 were OLD-only fallthrough; gated strip recovered 16/29 with 0 FP; 13 stay review when text misses the live code.
**Reversal trigger:** Holdout FP where `-OLD` sibling ≠ true successor but text still ranks it; or successor metadata makes naked (c) safer than text gate.

## D-04 — ID vs text soft verify; barcode≠alias → id_id_conflict
**Context:** ID lanes can disagree with each other or with strong text.
**Options:** (a) always ID wins (b) soft oppose → abstain on clash (c) text wins.
**Chose:** (b); ID/ID → review `id_id_conflict`.
**Evidence:** TBD; asymmetric cost of silent wrong ID.
**Reversal trigger:** If oppose checks rarely fire and add latency, simplify to (a) with documented risk.

## D-05 — Twin policy: required-attr abstain; ignore xN for SKU identity
**Context:** Size/grade/finish/colour twins; x6/x48 often outer qty.
**Options:** (a) required-attr abstain (b) always argmax (c) use xN as pack SKU key.
**Chose:** (a); (c) out for v1 except explicit Bulk naming.
**Evidence:** TBD; ACM-T-0006-style underspecification.
**Reversal trigger:** Pack-SKU FPs in EVAL → revisit pack tokens.
