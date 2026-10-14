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


| Rule                    | Decision                                                             |
| ----------------------- | -------------------------------------------------------------------- |
| Lookup key              | `(tenant, customer_id, buyer_sku)`                                   |
| Date                    | Use `order_date` vs `valid_from` / `valid_to`                        |
| OLD / disabled          | Drop; if nothing left → **fall through** to text                     |
| ≥2 different codes left | `review` / `ambiguous_alias` — stop                                  |
| 1 code, conf **≥ 0.72** | can auto `alias_exact` (ignore `source`)                             |
| 1 code, conf **< 0.72** | hard `review` / `alias_low_trust` — stop (do not keep going to text) |


Why ≥ 0.72: data is mostly 0.55 / 0.72 / 1.0. I want 0.72 to auto too, not only perfect 1.0.  
Why ignore source: one knob (confidence) is simpler; be ready to defend autoing some `inferred_match@1.0`.

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


| Code                                  | Rough meaning                          |
| ------------------------------------- | -------------------------------------- |
| `alias_exact`                         | Trusted unique alias auto              |
| `alias_low_trust`                     | Unique alias but conf too low → review |
| `ambiguous_alias`                     | Two+ codes for one buyer SKU           |
| `barcode_hit`                         | Barcode auto                           |
| `ambiguous_barcode`                   | Two+ active barcode hits               |
| `id_id_conflict`                      | Barcode vs alias disagree              |
| `id_text_conflict`                    | ID vs strong text disagree             |
| `ambiguous_twins`                     | Family clear, identity not             |
| `ambiguous_margin`                    | Scores too close                       |
| `lexical_unique`                      | Text path unique auto                  |
| `not_an_item` / `brand_not_in_tenant` | Junk / wrong world                     |
| `no_candidate_above_floor`            | Nothing good enough                    |


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
3. “Alias is dirty memory — conf ≥ 0.72 and unique after date/OLD filters; else review or fall through.”
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
| 2026-10-14 blank-GT FPs   | 17 exact-name `auto_wrong`; lean Option D — keep auto, explain in EVAL      |


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

| | slice 2 | slice 3 |
|---|---|---|
| auto correct | 125 | 176 |
| auto wrong | 4 | **17** |
| precision on auto | **0.969** | **0.912** |
| coverage | ~31% | ~46% |
| net value | **−12340** | **−19160** (worse) |
| `ambiguous_twins` | — | 117 |
| `ambiguous_margin` | 198 | 13 |

**Original 4 FPs after slice 3:**

| line | result | note |
|---|---|---|
| ACM-T-0066 Tolsen Bolt M8x50 | `review` / `ambiguous_twins` | fixed — finish underspec |
| ACM-T-0134 … M8x50 HDG | `review` / `ambiguous_twins` | fixed — bulk twin |
| NRD-T-0052 Breast Strips 5kg | `review` / `ambiguous_twins` | fixed — bulk twin |
| ACM-T-0028 Stallion Ball Valve 1-1/4" PVC | still `auto` wrong | unique name; no twin to disagree |

**Why wrong autos went 4 → 17:** attr filter removes near-siblings that used to create `ambiguous_margin`. Exact catalogue-name lines with **blank GT** then look unique @ 1.0 → `lexical_unique`. Twin policy worked; side effect unlocked blank-GT exact autos (see next note).

**Honesty / next architecture (not coded yet):** current brand denylist + `_PRODUCT_START` + global attr regexes are **tenant-hardcoded** and won’t travel. Proposed spine (catalogue-derived):

1. **Brand** vs tenant catalogue brands (exact + fuzzy typos); miss → brandless path, not auto-reject  
2. **Item phrase** within that pool from `item_group` leaf + brand-stripped `item_name`  
3. **Attrs last** on the shortlist only (discriminate twins)

Evidence for brandless path: ~28 labelled train lines have no brand token but still have GT (`Cable Tie…`, `GI Wire…`, `PVC 20mm…`). Blank-brand catalogue rows are MISC only.

**Paused here** — no further silent threshold tweaks; blank-GT policy locked below as Option D until EVAL.

### 2026-10-14 — Blank-GT `auto_wrong` (post-attrs smoke)

**What:** After attrs/twins, train smoke still has **17** `auto_wrong`. All blank `gt_item_code`, all `lexical_unique` @ 1.0, all exact catalogue `item_name` hits, no buyer_sku/barcode. Families: PVCP 7 / ANGL 4 / SELF 4 / NITR 1 / BALL 1.

**(checked) Not the cause:**

- UOM mismatch — vague `unit`/`ea`/`pcs` also on correct autos; when price present, **10/10** within 15% of `list_price` (no pack-price signal).
- Twins / OOS — no bulk twin on these 17; `available_qty=0` not discriminative.
- No feature separates blank-GT exact hits from labeled exact hits (same shape: **51 correct + 17 wrong = 68** no-ID exact lexical autos).

**Decision options considered:**

- **A** keep auto (accept train FPs)
- **B** abstain that whole shape → kills 17 FPs but also ~51 TPs; train net on those 68 improves because −800 asymmetry
- **C** raise floor/margin — useless here (already score 1.0)
- **D** keep A’s policy + document in EVAL (inseparable label edge)
- **E** UOM/price veto — rejected by data; out of DESIGN scope

**Lean: Option D.** Keep exact unique text autos. Carry the 17 as known FP class into EVAL/error analysis: model matches the item; label says unmatchable; abstaining the shape is inseparable collateral. Revisit only if holdout shows a worse blank-exact rate or Product wants precision over coverage.

**EVAL note to write later:** cite blank-GT policy from brief (~⅓ no correct answer); show inseparability counts; do not invent a gate without a separating signal.

---

*Append new dated notes below as you go.*