# Mind log — matcher design work notes

Personal work log. Not a graded deliverable.  
Use this while building: what I decided, why, what I’m still unsure about.  
Official write-up lives in `DESIGN.md` / `DECISIONS.md`.

---

## How I got here (short story)

1. Read the brief: wrong auto ≈ 20× worse than sending to a human. So this is **not** “guess the SKU as often as possible.”
2. Looked at train data: ~⅓ blank labels, dirty aliases, twins (same name, different size), junk lines (Cadbury, “same as last month”).
3. Walked two lines to feel the difference:
  - **Cadbury** (`ACM-T-0013`): refuse because it’s not catalogue stock — not because the fuzzy score was low.
  - **Stallion flap no size** (`ACM-T-0006`): fuzzy score can be *high* on several sizes → still refuse.
4. Sketch pipeline: tenant → barcode → buyer_sku → text (brand/family) → decide.
5. Stress-tested gaps one by one (alias trust, ID vs text, twins). Locked policies below.
6. Wrote `DESIGN.md` §1–§2; still iterating voice and edge cases.

Core mental model I want to keep:

> **“I don’t know” is a real answer**, with a reason code — not only “score too low.”

---



## Locked decisions (build to this)



### Goal / scoring mindset

- Optimise **expected net value** (correct auto +20, abstain −40, wrong auto −800).
- Prefer **fewer autos that are right** over many autos that are often wrong.
- Tune thresholds on **train only**. Never peek at holdout labels.
- Product owns the 20× number; Ops can push for safer (higher bar); commercial can push for more coverage.
- `review` and `reject` both count like abstain (−40) for now.
- `candidates` = help for humans / recall@3 — not the money objective.



### Pipeline order

```text
tenant → barcode → alias → ID checks → text (brand/family/attrs) → final decide
```

- Tenant from the `tenant` **column**, not from `ACM-` / `NRD-` in `line_id`.
- Each step either **stops** with a decision or **continues**.
- No embeddings / LLM in v1. Cheap text first. Measure later if needed.



### Alias lane (buyer_sku)


| Rule                         | Decision                                                                                                    |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------- |
| Lookup key                   | `(tenant, customer_id, buyer_sku)`                                                                          |
| Date                         | Use `order_date` vs `valid_from` / `valid_to`                                                               |
| OLD / disabled               | Drop; unique `*-OLD` → strip live sibling; auto iff ∈ text cands (`alias_old_successor`); else fall through |
| ≥2 different codes left      | `review` / `ambiguous_alias` — stop                                                                         |
| 1 code, unique after filters | auto `alias_exact` (ignore `source`; **no conf floor** — see 2026-10-14)                                    |
| ≥2 codes                     | `review` / `ambiguous_alias`                                                                                |


Why ignore source: one knob is simpler; be ready to defend autoing some `inferred_match@1.0`.  
**Conf floor removed (was ≥0.72):** on this train set every `alias_low_trust` (0.55) matched GT.

**Multi-active example to remember:**  
`acme/CUST-002/002469423` → hose **and** GI wire if order is on/before 2026-03-31. After expiry, often only one left. Still always check uniqueness.

**OLD map but live gt:** e.g. `ACM-T-0011` sku → `…-OLD`, label wants live code → fall through helps text recover.

### Barcode + ID fights

- Barcode: tenant catalogue, **active only**. 2+ actives → `ambiguous_barcode`.
- Barcode auto ≠ alias auto → `review` / `id_id_conflict` (no silent winner).
- One ID wants auto → **soft text check**: if text has one strong different code → `id_text_conflict`. Else allow ID auto.



### Text / twins

- Brand/family narrow first when possible.
- Extract size, grade, finish, colour, bulk-ish tokens.
- If several candidates still disagree on something the line **didn’t say** → abstain `ambiguous_twins` (don’t invent diameter/class).
- `x6` / `x48` on the line = usually order pack qty, **not** a different SKU in v1. Explicit `(Bulk)` can matter.
- Thin score gap top1 vs top2 → `ambiguous_margin`.



### Non-items (Cadbury etc.)

- **No early “is this a product?” gate** before barcode/alias (keeps pipeline simple).
- Usual path: no ID → text/final arb → `not_an_item` / `brand_not_in_tenant`.
- **Known hole:** bad barcode/alias on junk text could still try to auto. Soft oppose + alias floors are the safety net. If EVAL shows false autos here → add early gate.



### Cold start

- New customer = catalogue + barcodes, **empty aliases**.
- Same code path; alias step just never fires.
- Expect more review, fewer easy autos. That’s OK — not a second system.



### Embeddings

- Not in v1. If added later: must beat lexical on **net value**, offline only, easy to turn off.

---



## Reason codes I’m aiming for


| Code                                  | Rough meaning                                |
| ------------------------------------- | -------------------------------------------- |
| `alias_exact`                         | Trusted unique alias auto                    |
| `alias_old_successor`                 | OLD map stripped to live; text cands confirm |
| `alias_low_trust`                     | Unique alias but conf too low → review       |
| `ambiguous_alias`                     | Two+ codes for one buyer SKU                 |
| `barcode_hit`                         | Barcode auto                                 |
| `ambiguous_barcode`                   | Two+ active barcode hits                     |
| `id_id_conflict`                      | Barcode vs alias disagree                    |
| `id_text_conflict`                    | ID vs strong text disagree                   |
| `ambiguous_twins`                     | Family clear, identity not                   |
| `ambiguous_margin`                    | Scores too close                             |
| `lexical_unique`                      | Text path unique auto                        |
| `not_an_item` / `brand_not_in_tenant` | Junk / wrong world                           |
| `no_candidate_above_floor`            | Nothing good enough                          |


---



## Gaps we listed but didn’t fully lock

Use when building / editing DESIGN later:

- [ ] Catalogue junk rows (`DELIVERY FEE`, etc.) — never auto those names
- [ ] Lines with **no brand** but still matchable (`Cable Tie 450mm Black`) — brand gate must skip, not reject
- [ ] Typos / Malay / abbrev table (`Vermmont`, `ZP`, `S/S`, `skru`) — how big in v1?
- [ ] Exact soft-oppose rule when text says “not an item” (not only “other SKU”)
- [ ] Twin reason: one code `ambiguous_twins` vs split `missing_attr`
- [ ] Numeric τ / margin δ — set from train curve
- [ ] Whether `alias_superseded` is a visible reason or silent fall-through only

---



## Walkthrough anchors (say these out loud)

1. “Wrong auto is ~20× review — so I optimise net value and bias to precision.”
2. “Abstain is first-class: twins and junk can have high scores and still refuse.”
3. “Alias is dirty memory — unique after date/OLD filters autos (incl. 0.55 on this train); ambiguous still reviews.”
4. “Cold start = empty alias notebook, same pipeline.”
5. “Non-item early gate skipped on purpose; residual ID risk; soft oppose; EVAL may force a gate.”

---



## Session changelog


| When                      | What                                                                        |
| ------------------------- | --------------------------------------------------------------------------- |
| Task 1 brainstorm         | Objective = net value; balanced operating point; “I don’t know” first-class |
| Cadbury vs Stallion drill | Low-score abstain ≠ designed refuse                                         |
| Alias deep dive           | Unique after filters; ≥0.72; low trust hard review; OLD fall through        |
| ID conflict               | Soft text oppose; `id_id_conflict`                                          |
| Twins                     | Required-attr abstain; ignore xN for identity v1                            |
| DESIGN scaffold           | `submission/` + stubs                                                       |
| Assessor pass §1–§2       | Precision bias; admit non-item residual risk; clarify cold start            |
| 2026-10-13 slice 0+1      | Matcher scaffold + barcode/alias/ID arb under `submission/matcher/`         |
| 2026-10-13 slice 2        | Text normalize + brand/family + RapidFuzz; soft oppose live                 |
| 2026-10-13/14 slice 3     | Attr extract + twin/bulk filter; precision dipped; blank-GT FP class        |
| 2026-10-14 blank-GT FPs   | ACME-skewed blank-GT `auto_wrong`; question labels; keep logic; prod plan   |
| 2026-10-14 brand soft     | Drop denylist/`_PRODUCT_START`; catalogue exact+fuzzy; foreign=weak item    |
| 2026-10-14 item phrase    | Catalogue leaf + brand-stripped name shortlist before attrs                 |
| 2026-10-14 alias floor    | Drop 0.55/`alias_low_trust` gate — unique alias autos; train-only evidence  |
| 2026-10-16 Task 5 INV1–3  | Cursor drain ties; stable idem key; 409 different-payload → adopt remote    |


---



## While building — checklist

- [x] Implement lanes in the locked order *(ID + text + attrs; brand×item×attr rewrite still open)*
- [x] Every terminal path has a stable `reason_code` *(for paths that exist)*
- [x] Tenant filter on every catalogue/alias lookup
- [x] Train harness smoke + debug CSV (`scripts/run_train_smoke.py` → `debug/train_smoke.csv`)
- [ ] Full EVAL curve + `DECISIONS.md` evidence; adjust 0.72 if needed
- [x] Hand-check Cadbury, Stallion flap, one OLD-alias line, one duplicate-SKU case
- [x] Keep this file updated when a lock changes (date + why)

---



## Build notes



### 2026-10-13 — Slice 0+1 (ID lanes)

**Shipped:** `submission/matcher/` — loaders, barcode, alias (≥0.72 / low-trust stop / OLD fallthrough), ID arb (`id_id_conflict`), soft oppose **stubbed** (never opposes). Text → always `review` / `no_candidate_above_floor`.

**Layout choice:** all code under `submission/`; assessment `data/` + `starter/` stay at repo root.

**Deps:** stdlib only. `rapidfuzz` deferred to text lane.

**Train smoke** (`scripts/run_train_smoke.py`):


|                   |                                                                  |
| ----------------- | ---------------------------------------------------------------- |
| auto              | 26 (12 `barcode_hit` + 14 `alias_exact`)                         |
| auto wrong        | 0                                                                |
| precision on auto | 1.0                                                              |
| coverage          | ~6.2%                                                            |
| other             | 9 `alias_low_trust`, 1 `ambiguous_barcode`, 384 stub fallthrough |
| net value         | −15240 (mostly abstain cost — expected without text)             |


**Tests:** 15 unittest cases in `tests/test_id_lanes.py` — all green.

**Known gap carried forward:** soft oppose not real yet; alias low-trust hard-stops even if barcode already tentative (per DESIGN — revisit if EVAL shows barcode was right).

**Next:** slice 2 — normalize + brand filter + RapidFuzz retrieve.

### 2026-10-13 — Slice 2 (text lane)

**Shipped:**

- `normalize.py` — lower/slash cleanup, tiny synonyms (`Vermmont`, `ZP`, `S/S`, `skru`/`ayam`/`susu`), class-glue fix
- `lanes/text.py` — brand detect (+ multi-word), foreign-brand / non-item refuse, family leaf narrow, RapidFuzz `WRatio`, decide with floor/margin
- soft oppose now uses text retrieve (`id_text_conflict` fired once on train)
- `requirements.txt` — `rapidfuzz`

**Thresholds (v1, pre-attrs):** `AUTO_FLOOR=0.90`, `MARGIN=0.04`, `REVIEW_FLOOR=0.72`

**Train smoke:**


|                   |                                                |
| ----------------- | ---------------------------------------------- |
| auto              | 129 (104 lexical + 11 barcode + 14 alias)      |
| auto wrong        | **4** (all blank-GT / twin-ish)                |
| precision on auto | **0.969**                                      |
| coverage          | **~30.7%**                                     |
| reject            | 67 (`brand_not_in_tenant` 63, `not_an_item` 4) |
| review heavy      | 198 `ambiguous_margin`                         |
| net value         | −12340                                         |


**4 FPs (all blank gt — slice 3 fodder):**


| **line_id**    | **Line text**                  | **Matcher auto’d**                             | **Correct**                                                                    |
| -------------- | ------------------------------ | ---------------------------------------------- | ------------------------------------------------------------------------------ |
| **ACM-T-0028** | Stallion Ball Valve 1-1/4" PVC | `ACM-BALL0667` (exact name hit, score 1.0)     | **blank → abstain**May be a label-edge case                                   |
| **ACM-T-0066** | Tolsen Bolt M8x50              | `ACM-HEXB0675` (Tolsen Hex Bolt M8x50 **HDG**) | **blank → abstain** (finish not specified; several M8x50 finishes exist)       |
| **ACM-T-0134** | Tolsen Hex Bolt M8x50 HDG      | `ACM-HEXB0675` (non-bulk)                      | **blank → abstain** (likely because **Bulk twin** `ACM-HEXB0675B` also exists) |
| **NRD-T-0052** | Halberg Breast Strips 5kg      | `NRD-CHIC0167` (5kg non-bulk)                  | **blank → abstain** (Bulk twin `NRD-CHIC0167B` exists)                         |


**Hand checks:** Cadbury → `reject/brand_not_in_tenant`; Stallion flap → no auto; easy Tolsen wall plug → `lexical_unique` correct.

**Tests:** 21 green.

**Next:** slice 3 — attr extract + twin / bulk filter + retune τ/margin.

### 2026-10-13/14 — Slice 3 (attrs + twins)

**Shipped:**

- `attrs.py` — extract size / finish / colour / grade / bulk from text + item_name; `item_matches_query`; `unspecified_attr_disagreement`
- `lanes/text.py` — after brand/family: hard-filter pool by attrs the line stated → if remaining items disagree on an **unspecified** attr → `ambiguous_twins` → else RapidFuzz decide
- pack qty `xN` ignored for SKU identity; explicit `(Bulk)` is a discriminator
- twin regression tests in `tests/test_attrs.py`
- smoke now exports `submission/debug/train_smoke.csv` (per-line decision + `outcome`)

**Thresholds:** `AUTO_FLOOR=0.90`, `MARGIN=0.03`, `REVIEW_FLOOR=0.72`

**Train smoke (slice 2 → slice 3):**


|                    | slice 2    | slice 3            |
| ------------------ | ---------- | ------------------ |
| auto correct       | 125        | 176                |
| auto wrong         | 4          | **17**             |
| precision on auto  | **0.969**  | **0.912**          |
| coverage           | ~31%       | ~46%               |
| net value          | **−12340** | **−19160** (worse) |
| `ambiguous_twins`  | —          | 117                |
| `ambiguous_margin` | 198        | 13                 |


**Original 4 FPs after slice 3:**


| line                                      | result                       | note                             |
| ----------------------------------------- | ---------------------------- | -------------------------------- |
| ACM-T-0066 Tolsen Bolt M8x50              | `review` / `ambiguous_twins` | fixed — finish underspec         |
| ACM-T-0134 … M8x50 HDG                    | `review` / `ambiguous_twins` | fixed — bulk twin                |
| NRD-T-0052 Breast Strips 5kg              | `review` / `ambiguous_twins` | fixed — bulk twin                |
| ACM-T-0028 Stallion Ball Valve 1-1/4" PVC | still `auto` wrong           | unique name; no twin to disagree |


**Why wrong autos went 4 → 17:** attr filter removes near-siblings that used to create `ambiguous_margin`. Exact catalogue-name lines with **blank GT** then look unique @ 1.0 → `lexical_unique`. Twin policy worked; side effect unlocked blank-GT exact autos (see next note).

**Next architecture:** brand step done (below). Still open: catalogue-derived **item phrase** (leaf + brand-stripped name) before attrs; attrs stay last on shortlist.

### 2026-10-14 — Brand step (catalogue soft restrict)

**Shipped:** `matcher/brand.py` + rewired `lanes/text.py`

- Removed `_FOREIGN_BRAND_TOKENS` denylist and `_PRODUCT_START` allowlist
- Brand from **tenant catalogue only**: multi-word exact → unigram exact → glued prefix (`HitexNitrile`) → fuzzy typo (`BRAND_FUZZY_FLOOR=78`)
- **Hit** → soft-restrict pool to that brand; **miss** → full active catalogue (brandless path)
- Foreign refuse only if leading token looks brand-shaped **and** no tenant brand match **and** top item score < 0.72 → `brand_not_in_tenant` (Cadbury still rejects; Cable Tie does not)

**Train smoke after brand rewrite:**


|                       | post-attrs (slice 3) | after brand soft |
| --------------------- | -------------------- | ---------------- |
| auto correct          | 176                  | 182              |
| auto wrong            | 17                   | 18               |
| precision             | 0.912                | 0.910            |
| coverage              | 46%                  | 48%              |
| `brand_not_in_tenant` | 63                   | **46**           |
| net value             | −19160               | −19560           |


Slightly more coverage; foreign rejects fewer (less hardcoded). Blank-GT Option D unchanged. Debug CSV: `submission/debug/train_smoke_*.csv` (fallback if Excel locks `train_smoke.csv`).

**Still open then:** item-phrase shortlist (done below); attr regexes still global (acceptable v1 — values mined from text/names, not tenant product lists).

### 2026-10-14 — Item phrase shortlist (catalogue-derived)

**Shipped:** `matcher/phrases.py` + text lane order now:

```text
brand soft → phrase shortlist (leaf + brand-stripped name) → attrs/twins → full-name fuzz decide
```

- Phrase key = brand-stripped `item_name`, with `item_group` leaf prepended when it adds tokens
- Query brand tokens stripped before phrase match
- If any catalogue leaf appears in query → prefer that family (no hand product list)
- `PHRASE_FLOOR=0.65`, top 15 → attrs run **only** on that shortlist
- Removed old `_family_narrow`-then-attrs-on-whole-family path

**Train smoke:**


|                   | after brand soft | after item phrase |
| ----------------- | ---------------- | ----------------- |
| auto correct      | 182              | **189**           |
| auto wrong        | 18               | 18                |
| precision         | 0.910            | **0.913**         |
| coverage          | 48%              | **49%**           |
| `ambiguous_twins` | 127              | **88**            |
| net value         | −19560           | **−19140**        |


Twins/Cadbury/brandless Cable Tie tests still green (41 tests). Debug CSV refreshed: `submission/debug/train_smoke.csv`.

**Spine status:** brand ✓ · item phrase ✓ · attrs last ✓ (regex extractors remain — not tenant-specific product lists).

### 2026-10-14 — Blank-GT `auto_wrong` (post-attrs smoke)

**Observation (train):** Current smoke has **18** `auto_wrong` — **all** `acme` (0 nordic). All blank `gt_item_code`, all `lexical_unique` (mostly @ 1.0), raw text is an exact / near-exact catalogue `item_name` hit, typically no buyer_sku/barcode. Families skewed hardware: PVCP / ANGL / SELF (+ a few others).

**No clear miss by the system:** Hand + checks found no separating bug pattern the matcher failed to encode.

- Not UOM — vague `unit`/`ea`/`pcs` also on correct autos; prices that exist sit near `list_price`.
- Not twins / OOS — no bulk twin to force abstain; stock qty not discriminative.
- Same shape as many **labeled** exact lexical autos → abstaining this shape would also kill true positives.

**Label stance:** These are the points I am **questioning as labeled**. Blank GT says “unmatchable / any auto is FP,” but the line text points at a real unique catalogue name. Treating that as a matcher flaw overfits noise; treat as **suspect / under-specified labels** until Product clarifies.

**Decision:** **Maintain current auto logic** (do not add an inseparable abstain gate). Explicitly **flag / list these** `line_id`**s** as contested train labels for EVAL and for anyone re-scoring the set.

**Production (what to counter later — not v1 code):**

- Human review queue / shadow mode on first-seen exact-name autos without ID corroboration
- Operator confirm → promote to trusted alias so next time is ID-backed
- Periodic label audit on blank-GT lines that exact-match catalogue names
- Only then consider a policy knob (e.g. require ID for auto) if ops cost of wrongs dominates — not from this train slice alone



### 2026-10-14 — Remove alias confidence floor (`alias_low_trust`)

**Evidence (this train):** 9 lines were `alias_low_trust` @ 0.55. Every one had candidate == `gt_item_code` (ACM-T-0008, 0035, 0063, 0076, 0158, 0185; NRD-T-0035, 0103, 0157). Hard-stopping them was pure abstain cost with zero FP savings on this set.

**Change:** `ALIAS_AUTO_FLOOR = 0.0` — unique in-date active alias → `alias_exact` tentative auto at any conf band in {0.55, 0.72, 1.0}. Ambiguous (≥2 codes) still `ambiguous_alias`. `alias_low_trust` path kept in code only as a reversal knob.

**Risk / caveat:** This is **fit to this assessment’s alias table**. Other customers or a dirtier `inferred_match@0.55` distribution can make low-conf unique aliases wrong. If holdout or a new tenant shows low-conf FPs → restore floor (0.72 or 1.0) or bring back source filter (`confirmed_order` only). Do **not** treat “0.55 always safe” as a universal law.

**Also update when doing DECISIONS.md:** reverse D-01/D-02 evidence; reversal trigger = low-conf alias FPs on holdout or production audit.

### 2026-10-14 — OLD alias + text-candidate confirm (`alias_old_successor`)

**Evidence (**`train_smoke_trust allias.csv`**):** 29 `abstain_miss` with buyer_sku — all OLD-only fallthrough. Strip `-OLD` == GT for all 29. Gate “live code ∈ text candidates” → **16** would auto correctly, **0** FP; **13** stay review (text never ranked the live code).

**Change:** Alias lane emits `pending_text_confirm` when only `*-OLD` maps and a unique active sibling exists. Service autos `alias_old_successor` only if that code is in text retrieval candidates; else unchanged text decide. D-03 → (d).

**Risk:** Assumes catalogue naming `FOO-OLD` ↔ live `FOO`. Wrong if successor is a different code. Gate limits blast radius vs naked strip-auto.

### 2026-10-14 — Cold-start safe tenant discovery + Task 2 `predictions.csv`

**Cold-start (minimal):**

- Removed hardcoded `tenant not in {"acme","nordic"}`.
- `load_default_catalogues` globs `catalogue_<tenant>.csv`; tenant = filename suffix.
- `match` rejects only if catalogue for that tenant was never loaded (`unknown_tenant`).
- Alias / barcode / text unchanged — already tenant-keyed. Empty alias history → continue (no hard stop).
- Verified with temp `catalogue_newco.csv` + empty `AliasIndex`: barcode auto; unknown SKU falls through to text; `ghost` → `unknown_tenant`.

**Deliverable:** `scripts/run_holdout.py` → `predictions.csv` (exact schema: `line_id,item_code,confidence,decision,reason_code,candidates`). Abstain rows force blank `item_code`.

**Current train vs holdout** (same matcher; train labelled, holdout unlabelled — no precision on holdout):


|                           | train (`order_lines_train.csv`) | holdout (`predictions.csv`) |
| ------------------------- | ------------------------------- | --------------------------- |
| lines                     | 420                             | 300                         |
| auto                      | 239                             | 160                         |
| review                    | 132                             | 103                         |
| reject                    | 49                              | 37                          |
| coverage (auto share)     | **56.9%**                       | **53.3%**                   |
| auto_correct / auto_wrong | 221 / 18                        | n/a (no labels)             |
| precision on auto         | **0.925**                       | n/a                         |
| net value (train only)    | **−17220**                      | n/a                         |


**Reason mix (counts):**


| reason                   | train | holdout |
| ------------------------ | ----- | ------- |
| lexical_unique           | 169   | 109     |
| ambiguous_twins          | 73    | 70      |
| alias_exact              | 23    | 14      |
| alias_old_successor      | 35    | 24      |
| barcode_hit              | 12    | 13      |
| brand_not_in_tenant      | 45    | 34      |
| no_candidate_above_floor | 40    | 20      |
| ambiguous_margin         | 18    | 13      |
| not_an_item              | 4     | 3       |
| ambiguous_barcode        | 1     | 0       |


Coverage is close (train a bit higher — more alias history on train customers). Holdout reason shape tracks train; no holdout labels so do not invent precision. Re-run: `python scripts/run_train_smoke.py` / `python scripts/run_holdout.py`.

### 2026-10-15/16 — Task 3 noise classes → eval harness

**Brief ask:** one-command harness on `order_lines_train.csv`; print metrics with **per-tenant** and **per-noise-class** breakdowns. Classes are not labelled → define own segmentation and justify.

#### What “noise class” is (and is not)

- **Not** `reason_code`. That is *why the matcher stopped* (`lexical_unique`, `ambiguous_twins`, …). Bucket by it and classes move when you change thresholds — circular.
- **Is** *line shape / input population*: what kind of mess (or signal) is on the row, assigned from raw fields + catalogue shape, independent of the decision path.
- Discovery workflow: run matcher → stare at failures + raw text → name clusters → turn clusters into **deterministic rules** → spot-check. Do not hand-label 420 rows forever.

Also clarified outcome math for EVAL: `abstain_ok` = refuse correct (blank GT), **not** auto. Wrong refuse = `abstain_miss` (−40), **not** `auto_wrong` (−800). Only a wrong auto is the expensive failure.

#### Nine primary classes (priority, first match wins)

Locked taxonomy in `matcher/input_class.py`:


| #   | Class                   | Intent                                                                          |
| --- | ----------------------- | ------------------------------------------------------------------------------- |
| 1   | `non_item`              | Junk / chat crumbs / empty (`same as last`, `subtotal`, `pls confirm stock`, …) |
| 2   | `id_barcode`            | `raw_barcode` present (signal channel, not “noise”)                             |
| 3   | `id_alias`              | `buyer_sku` present                                                             |
| 4   | `foreign_brand`         | Brand-shaped leading token not in tenant catalogue (Cadbury, Makita, …)         |
| 5   | `conversational_prefix` | Chat wrapper (`need`, `urgent`, `pls`, `item:`, `-`, `1)`)                      |
| 6   | `typo_or_abbrev`        | Known abbrev/Malay/typo markers + leading-brand fuzzy typo                      |
| 7   | `pack_uom_underspec`    | Pack qty `xN`, pack-like `uom_text`, bulk, or twin attr underspec               |
| 8   | `brandless_clean`       | No catalogue brand; product-word lead (e.g. Cable Tie)                          |
| 9   | `clean_named`           | Default: catalogue brand hit, otherwise clean                                   |


Dropped `blank_gt` as a primary class / tag after trying it — redundant with `gt_item_code` empty and the outcome already splits abstain_ok vs auto_wrong. Kept as analysis note in EVAL, not a harness axis.

#### Build sequence

1. **First pass classifier** — hand lists + twin shortlist; wired into `run_train_smoke.py`.
2. **Audit vs** `train_smoke.csv` — tagging was loose; **lanes looked fine** (barcode→`barcode_hit`, Cadbury→`brand_not_in_tenant`). Bad buckets were classifier rules, not matcher bugs.
3. **Bug fixes kept (partial rewrite, not full data-driven redo):**
  - Class-glue regex was matching normal `25mm Class C` → tighten to broken `mmC lass` / `mmclass` only.
  - Brand fuzzy: `white`≈`Hitex` was tagging `Cable White` as typo → only count fuzzy when **leading** token is the brand match.
  - Expand `non_item` for chat crumbs; add `pls` / `1)` to conversational; add `packet` to pack UOMs.
4. **Harness** — `scripts/run_train_smoke.py`:
  - Prints overall (P on auto, coverage, misleading accuracy, net, recall@3 on abstain_miss, cross-tenant, latency) + per-tenant + per-noise-class.
  - Writes **one pair** per run: `train_smoke_<stamp>.csv` + `train_metrics_<stamp>.csv` (no “latest” duplicate copies).
  - Sequential integer column `id` (1, 2, …) inside both files; stamp stays in the filename.
5. **Tests** — `tests/test_input_class.py` for the buckets that previously misfired.



#### What the breakdown taught (after fixes)

Rough shape on train: ID lanes (`id_barcode` / `id_alias`) near P=1 / high cov; `foreign_brand` almost all abstain; `pack_uom_underspec` and `clean_named` hold most residual FPs; `typo_or_abbrev` is small after tightening (hand list still misses typos under conversational prefixes — priority steals them). All 18 `auto_wrong` still live on blank-GT exact lexical hits (label/policy, not a noise-class fix).

#### Still imperfect (document, don’t over-engineer)

- Conversational as **primary** means typo-under-prefix never lands in `typo_or_abbrev`.
- `pack_uom_underspec` still uses phrase shortlist / twin disagreement → partly overlaps matcher twin logic (acceptable for v1; note in EVAL).
- `foreign_brand` also catches out-of-tenant *products* (Copper pipe) — bucket name is slightly wider than “brand”; justify as wrong-world / out-of-catalogue lead token.
- Separate lane note (not fixed in this slice): `detect_brand` fuzzes early tokens so colours can soft-restrict brand — classifier now ignores non-leading fuzzy; text lane still has the behaviour.

**Commands:** `python scripts/run_train_smoke.py` · numbers / curve live in `EVAL.md` + `scripts/sweep_operating_point.py`.

### 2026-10-16 — Task 5 sync: INV1 + INV2 + INV3

Working in `starter/sync/`. Symptom reporter: `python run_sync.py`. Do **not** patch `fake_erp.py` (vendor semantics).

#### Assessment cheat-sheet (how to say it)

1. **INV1 — wording to keep precise:**  
   Not “end-of-page `updated_at` equals `since` so that row is skipped.”  
   We *do* ingest the page, then set `cursor = page[-1].updated_at`. Next call asks `updated_at > cursor`. Any **other** rows that share that same second but sorted *after* the page cut (e.g. `EXT-0050` after `EXT-0049`) are never returned → neglected forever until edited.

2. **INV2:** Idempotency key hashed `attempt` + `at` (`time.time()`). After **504-after-commit**, retry bumped attempt/time → **different key** → ERP treated it as a new write; stale `base_version` → 409 → conflict handler wrote again → duplicate.

3. **INV3 / what is 409?**  
   `ErpConflict` = HTTP-style **409**: your `base_version` ≠ current remote version. Someone (or your own timed-out commit) already moved the row.  
   Fix: if remote payload **differs**, do **not** force-write — adopt ERP copy, clear dirty.  
   **Does this break normal local → ERP push?** No. Happy path is `write(base_version=rec.remote_version)` with matching version → **no 409** → unchanged. INV3 only changes the conflict branch.

#### INV1 / MAIA-812 — missing records on first pull

**Symptom:** First `pull` already short one row (`EXT-0050`); INV1 `missing locally`.

**Mechanism:** `list_changes` is `updated_at > since` at **second** resolution; ties are common. Cursor parked on last page timestamp → same-second siblings past the page boundary skipped forever.

**Fix (in `pull`):** On a full page, set cursor to last row with `updated_at < page[-1].updated_at` (re-read incomplete bucket). Short page → park on last ts and stop.

**Invariant:** Full pull → every remote record local at remote version.

#### INV2 / MAIA-830 — one edit → two ERP writes

**Symptom:** `EXT-0042` twice in `write_log` with `price=999`.

**Fix:** Stable key = hash`(id, payload)` only; one key per retry loop. On 409 with **same** payload → adopt (504-after-commit), don’t rewrite.

**Invariant:** One dirty edit → at most one new ERP version.

#### INV3 / MAIA-844 — remote edit clobbered

**Symptom:** ERP set `EXT-0011` `uom=Box`; after push remote is `{price:999, uom:Nos}`.

**Mechanism:** Local dirty push with `base_version=1` while ERP already at `v2` with different payload → **409** → old handler force-wrote local over remote.

**Fix:** On 409 with **different** payload → adopt remote (`payload` / version / ts), clear dirty. No second write.

**Invariant:** Concurrent remote edit is not silently lost. (Unpushed local edit dropped on conflict — no merge UI yet.)

**Verify:** `cd starter/sync && python run_sync.py` → all three invariants hold.

---

*Append new dated notes below as you go.*