# EVAL.md — Task 3

Source run for numbers below: `debug/train_smoke_20261016_005103.csv` / `debug/train_metrics_20261016_005103.csv`  
Cost model: auto_correct **+20**, abstain **−40**, auto_wrong **−800** (brief §1 / `DESIGN.md`).

---

## 1. Harness

```bash
cd submission
python scripts/run_train_smoke.py
```

One command on `../data/order_lines_train.csv` (`n=420`). Prints overall / per-tenant / per-noise-class metrics and writes a timestamped pair under `debug/` (`train_smoke_<stamp>.csv`, `train_metrics_<stamp>.csv`). Numbers in this section are from `20261016_005103`.

### Noise-class segmentation

Nine classes in `matcher/input_class.py`, assigned from **line shape** (text / barcode / buyer SKU / UOM + catalogue), not from matcher `reason_code`. `reason_code` is a pipeline output and would move with thresholds; noise class must stay fixed so we can see *which input populations* break.

Axes: **non-item / wrong-world** (`non_item`, `foreign_brand`) · **structured ID** (`id_barcode`, `id_alias`) · **text difficulty** (`conversational_prefix`, `typo_or_abbrev`, `brandless_clean`, `clean_named`) · **pack/twin underspec** (`pack_uom_underspec`). Priority (first match): `non_item` → ID → `foreign_brand` → `conversational_prefix` → `typo_or_abbrev` → `pack_uom_underspec` → `brandless_clean` → `clean_named`.

### Breakdown (`20261016_005103`)

**Overall**


| n   | auto_ok | auto_bad | abstain | P     | cov   | accuracy | net     | recall@3 (abstain_miss) | cross-tenant | p95 ms |
| --- | ------- | -------- | ------- | ----- | ----- | -------- | ------- | ----------------------- | ------------ | ------ |
| 420 | 221     | 18       | 181     | 0.925 | 0.569 | 0.526    | −17,220 | 0.865                   | 0            | 93.0   |


**Per tenant**


| tenant | n   | auto_ok | auto_bad | abstain | P     | cov   | net     |
| ------ | --- | ------- | -------- | ------- | ----- | ----- | ------- |
| acme   | 260 | 127     | 18       | 115     | 0.876 | 0.558 | −16,460 |
| nordic | 160 | 94      | 0        | 66      | 1.000 | 0.588 | −760    |


**Per noise class**


| noise_class           | n   | auto_ok | auto_bad | abstain | P     | cov   | net    |
| --------------------- | --- | ------- | -------- | ------- | ----- | ----- | ------ |
| non_item              | 22  | 0       | 0        | 22      | —     | 0.000 | −880   |
| id_barcode            | 13  | 12      | 0        | 1       | 1.000 | 0.923 | +200   |
| id_alias              | 64  | 58      | 0        | 6       | 1.000 | 0.906 | +920   |
| foreign_brand         | 38  | 1       | 0        | 37      | 1.000 | 0.026 | −1,460 |
| conversational_prefix | 78  | 46      | 2        | 30      | 0.958 | 0.615 | −1,880 |
| typo_or_abbrev        | 10  | 7       | 0        | 3       | 1.000 | 0.700 | +20    |
| pack_uom_underspec    | 88  | 35      | 5        | 48      | 0.875 | 0.455 | −5,220 |
| brandless_clean       | 9   | 3       | 1        | 5       | 0.750 | 0.444 | −940   |
| clean_named           | 98  | 59      | 10       | 29      | 0.855 | 0.704 | −7,980 |


All 18 FPs are **acme**. ID slices are the only positive net; 15/18 FPs sit in `clean_named` + `pack_uom_underspec`.

---



## 2. Metric defence — why accuracy misleads; precision–coverage curve



### Definitions (as implemented in `scripts/run_train_smoke.py`)


| Metric                    | Formula                                      | Question it answers                                         |
| ------------------------- | -------------------------------------------- | ----------------------------------------------------------- |
| **Precision on** `auto`   | `auto_correct / (auto_correct + auto_wrong)` | When we commit, how often are we right?                     |
| **Coverage**              | `(auto_correct + auto_wrong) / n`            | How often do we auto?                                       |
| **Accuracy (misleading)** | `auto_correct / n`                           | How often did we auto-match the right SKU over *all* lines? |
| **Net value**             | `ac·(+20) + aw·(−800) + abstain·(−40)`       | Expected business value under the cost model                |


`abstain_ok`, although considered to be the correct categorization, does not count in accuracy and precision — only enlarges `n`, so good caution **lowers** the accuracy number.

### Looking at accuracy

On train (as-shipped matcher):


| Metrics   | Numbers                                                                  |
| --------- | ------------------------------------------------------------------------ |
| Outcomes  | `auto_correct=221`, `auto_wrong=18`, `abstain_ok=107`, `abstain_miss=74` |
| Precision | **92.47%** (221/239)                                                     |
| Coverage  | **56.90%**                                                               |
| Accuracy  | **52.62%** (221/420)                                                     |
| Net value | **−17,220**                                                              |


Accuracy ≈ 53% looks mediocre. Most of the gap vs precision is intentional abstention: **107** lines are `abstain_ok` (no correct item; refusing is the right action). Accuracy treats those the same as failures. Maximising accuracy would push toward answering more blank-GT lines, which become `auto_wrong` at **−800** each — the opposite of the objective in §1.

### Precision–coverage sweeps

```bash
python scripts/sweep_operating_point.py
# writes debug/operating_point_sweep_<stamp>.csv
```

Matcher **scoring** is held fixed (candidates already in the smoke CSV). Two post-hoc axes:

1. **confidence τ** — demote existing `auto` when `confidence < τ` (text floors fixed at shipped 0.90 / 0.03).
2. `AUTO_FLOOR` **×** `MARGIN` — re-apply the text decide rule on parsed `candidates`. ID-lane autos (`barcode_hit` / `alias_`*) stay; `ambiguous_twins` / rejects never promote. (`REVIEW_FLOOR` omitted: it does not gate `auto`.)

Full grid: `debug/operating_point_sweep_20261016_005103.csv` (51 rows).

#### A. Confidence τ


| τ    | coverage | precision | accuracy | net_value   | ac  | aw  | ab_ok | ab_miss |
| ---- | -------- | --------- | -------- | ----------- | --- | --- | ----- | ------- |
| 0.00 | 0.569    | 0.925     | 0.526    | **−17,220** | 221 | 18  | 107   | 74      |
| 0.72 | 0.548    | 0.922     | 0.505    | −17,760     | 212 | 18  | 107   | 83      |
| 0.90 | 0.543    | 0.921     | 0.500    | −17,880     | 210 | 18  | 107   | 85      |
| 0.95 | 0.536    | 0.920     | 0.493    | −18,060     | 207 | 18  | 107   | 88      |
| 0.98 | 0.348    | 0.884     | 0.307    | −21,980     | 129 | 17  | 108   | 166     |
| 1.00 | 0.340    | 0.881     | 0.300    | −22,160     | 126 | 17  | 108   | 169     |




#### B. `AUTO_FLOOR` × `MARGIN`


| AUTO_FLOOR | MARGIN   | coverage | precision | net_value   | ac  | aw  |
| ---------- | -------- | -------- | --------- | ----------- | --- | --- |
| 0.85       | 0.03     | 0.619    | 0.923     | −17,600     | 240 | 18  |
| 0.88       | 0.03     | 0.593    | 0.928     | **−16,620** | 231 | 18  |
| **0.90**   | **0.03** | 0.574    | 0.925     | −17,100     | 223 | 18  |
| 0.92       | 0.03     | 0.569    | 0.925     | −17,220     | 221 | 18  |
| 0.95       | 0.03     | 0.567    | 0.924     | −17,280     | 220 | 18  |
| 0.90       | 0.00     | 0.605    | 0.890     | −24,520     | 226 | 28  |
| 0.90       | 0.05     | 0.514    | 0.921     | −17,780     | 199 | 17  |
| 0.90       | 0.10     | 0.455    | 0.916     | −18,460     | 175 | 16  |
| 1.00       | 0.03     | 0.367    | 0.890     | −21,500     | 137 | 17  |




### Residual FPs are not movable by these knobs

The **18** train `auto_wrong` rows are almost all `lexical_unique` at **confidence = 1.0** with **blank GT**. They already clear every reasonable `AUTO_FLOOR` / `MARGIN` / confidence τ. Across both sweeps:

- `aw` stays **18** for all non-extreme settings (including best-net cell `0.88 / 0.03`).
- Only at harsh settings (`MARGIN ≥ 0.08` or floors → 1.0) does `aw` drop to 15–17 — while burning dozens of true positives and worsening net value.

So the residual FP mass is a **policy / capability** problem (confident auto on unmatchable or label-noisy lines), not an operating-point dial. Threshold sweeps still matter for TP/coverage trade-offs; they are the wrong tool for those 18.

### Reading the curves

1. **Confidence τ:** best net at τ = 0.0 (as-shipped smoke). Raising τ demotes correct low-conf autos (e.g. nine `alias_exact` at 0.55) and barely touches FPs.
2. `AUTO_FLOOR` **×** `MARGIN`**:** best post-hoc net at **0.88 / 0.03** (−16,620) with still `aw=18` — extra TPs from mid-band reviews, zero FP reduction. Loosening `MARGIN` to 0 adds FPs fast (net collapses). Tightening margin past 0.03 costs TPs for ~1 FP.
3. Accuracy tracks coverage downward; it never credits `abstain_ok`.



### Chosen operating point

Keep the matcher’s internal decision rule as shipped:

- Text: `AUTO_FLOOR = 0.90`, `MARGIN = 0.03`, `REVIEW_FLOOR = 0.72`
- Alias: unique in-date active → auto (`ALIAS_AUTO_FLOOR = 0.0`, D-01)
- No post-hoc confidence gate on top

**Why:** live smoke net −17,220 at ≈92.5% precision / ≈57% coverage. The post-hoc 0.88 floor looks slightly better on net but does **not** fix residual FPs; changing the shipped floor needs a real matcher re-run + decision-log entry, not a CSV re-label. `REVIEW_FLOOR` stays a review-path knob only.

**Who moves the knob:** Product owns the 20× FP cost assumption. If that ratio falls (e.g. 20× → 3×), re-run `sweep_operating_point.py` and reconsider floors. Ops may impose a hard precision floor if wrong shipments dominate.

**Honest limit:** post-hoc sweeps do not re-score or re-open twin/attr logic. Killing the blank-GT lexical FPs requires §3-style fixes, not a higher τ.

---



## 3. Error analysis (20 failures)

Source: `debug/train_smoke_20261016_005103.csv`. Train has **18** `auto_wrong` (−800 each) and **74** `abstain_miss` (−40 each). Below: **20 named lines**, grouped by root cause. Fix type is what I would change — not what shipped in this submission.

Cost classes: **AW** = `auto_wrong`, **AM** = `abstain_miss`.

### ++Group A  (AUTO WRONG)++



### blank GT ∩ exact catalogue name → confident lexical auto (data / policy)

All **18** train AWs are acme, blank `gt_item_code`, `lexical_unique` (almost all conf = 1.0). Attr filtering made near-siblings drop out, so an exact `item_name` hit looks unique and autos. Threshold sweeps (§2) cannot move this mass.


| line_id    | outcome | reason           | root cause                                                       | fix                                                                                     |
| ---------- | ------- | ---------------- | ---------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| ACM-T-0022 | AW      | `lexical_unique` | Exact name appears in acme catalogue, active, but gt shows blank | Business / label: audit blank∩exact-name; do not invent a code gate that kills true TPs |
| ACM-T-0028 | AW      | `lexical_unique` | Exact name appears in acme catalogue, active, but gt shows blank | same                                                                                    |
| ACM-T-0050 | AW      | `lexical_unique` | Exact name appears in acme catalogue, active, but gt shows blank | same                                                                                    |
| ACM-T-0055 | AW      | `lexical_unique` | Exact name appears in acme catalogue, active, but gt shows blank | same                                                                                    |
| ACM-T-0064 | AW      | `lexical_unique` | Exact name appears in acme catalogue, active, but gt shows blank | same                                                                                    |
| ACM-T-0082 | AW      | `lexical_unique` | Exact name appears in acme catalogue, active, but gt shows blank | same                                                                                    |




### ++Group A′++

### brandless false unique (capability)


| line_id    | outcome | reason                  | root cause                                                                                                                                          | fix                                                    |
| ---------- | ------- | ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| ACM-T-0147 | AW      | `lexical_unique` @ 0.95 | `Cable Tie 200mm White` — no brand; many brand twins in catalogue; twin policy does not disagree on **brand**, shortlist collapses to one Hitex hit | Abstain when brandless and ≥2 brands share leaf+attrs. |




### ++Group B — list / chat prefix noise (capability)++

`normalize` already strips `-`, `need`, `please send`, `item:`. It does **not** strip `1)` / `2)`.


| line_id    | outcome | reason            | root cause                                                                                        | fix                                                         |
| ---------- | ------- | ----------------- | ------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| ACM-T-0057 | AM      | `ambiguous_twins` | `1) Hietx Cable Tie 300m Natural` — list prefix + typo + `300m`≠`300mm`; GT already top @ 0.915   | Strip `^\d+\)` before brand/attr; also Group C (`natural`)  |
| ACM-T-0125 | AM      | `ambiguous_twins` | `- Knato Masking Taep…` — leading `-` already stripped; residual is typo (`Knato`/`Taep`) + twins | Typo tolerance / grade twin; **not** primarily a prefix bug |




### Group C — missing attr vocabulary → twins with GT on top (capability)

`natural` is catalogue colour; `brass` is catalogue material. Neither is in `attrs.py` (`_COLOURS` / `_FINISH_PATTERNS`). 

Query leaves colour/finish unspecified → `unspecified_attr_disagreement` → review even when top candidate is GT @ 1.0. 


| line_id      | outcome | reason            | root cause                                                              | fix                                                                       |
| ------------ | ------- | ----------------- | ----------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| ACM-T-0168   | AM      | `ambiguous_twins` | `Natural` not extracted                                                 | Add `natural` as colour                                                   |
| `ACM-T-0018` | AM      | `ambiguous_twins` | `normalize` turns `/`→space, so `3/4"` size extract degrades on valves. | don't strip "/" but might hurt other positive cases                       |
| ACM-T-0085   | AM      | `ambiguous_twins` | `brass` not extracted (+ inch size noise)                               | Add `brass` as finish/material; fix fractional-inch after slash normalize |
| ACM-T-0222   | AM      | `ambiguous_twins` | same                                                                    | same                                                                      |




### Group D — OLD alias + weak text → successor confirm never fires (policy / capability)

Alias maps to `*-OLD`; live sibling exists; `alias_old_successor` only autos if live code ∈ **text** candidates. Underspec text never surfaces it → fall through to junk lexical review. 


| line_id    | outcome | reason             | root cause                                                      | fix                                                                                                 |
| ---------- | ------- | ------------------ | --------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| NRD-T-0010 | AM      | `ambiguous_margin` | `006703262` → `NRD-PRAW0055-OLD`; text `Bay 16/20 2kg` too weak | Inject live successor into candidates, or auto unique OLD→live without text confirm (business call) |
| ACM-T-0132 | AM      | `ambiguous_margin` | `006495314` → `ACM-GIWI0811-OLD`; text `GI Wire`                | same                                                                                                |
| NRD-T-0038 | AM      | `ambiguous_margin` | `003449087` → `NRD-CHIC0486-OLD`; text `Breast 1kg`             | same                                                                                                |


Train scale: ~29 buyer_sku `abstain_miss` were OLD-only fallthrough in an earlier probe; these three are exemplars.

### Group E — multi-word brand typo (capability)


| line_id    | outcome | reason                     | root cause                                                                                                                         | fix                                           |
| ---------- | ------- | -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| NRD-T-0002 | AM      | `no_candidate_above_floor` | `Cape ay…` — brand is `Cape Bay`; multi-word brands are exact-substring only; fuzzy is single-word only → brandless → wrong family | Fuzzy / partial multi-word brand (or synonym) |




### Group F — other AM modes (sampled to round out the 20)


| line_id    | outcome | reason              | root cause                                             | fix                                                                               |
| ---------- | ------- | ------------------- | ------------------------------------------------------ | --------------------------------------------------------------------------------- |
| NRD-T-0009 | AM      | `ambiguous_barcode` | Same barcode on active twin `NRD-FULL0174` / `0174B`   | Pack/UOM disambiguation on barcode collisions; else forced review (correct today) |
| ACM-T-0195 | AM      | `ambiguous_twins`   | `putih` (Malay white) not in colour / synonym table    | Map `putih`→`white` in normalize                                                  |
| ACM-T-0061 | AM      | `ambiguous_twins`   | Pack cue `x12 case` but bulk twin `…B` still disagrees | Stronger pack→non-bulk preference, or keep abstain when bulk twin present         |




### Fix-type summary


| type                                | groups            | action                                                                              |
| ----------------------------------- | ----------------- | ----------------------------------------------------------------------------------- |
| **Data / policy**                   | A                 | Label audit; Product owns whether blank and exact-name auto is acceptable           |
| **One capability, many lines**      | C, and A′ / B / E | Attr vocab; brandless brand-disagreement; list-prefix strip; multi-word brand fuzzy |
| **Policy knob already in pipeline** | D                 | Relax or seed OLD→live confirm                                                      |
| **Acceptable abstain / niche**      | F (`0009`)        | Barcode twins should not silent-pick                                                |


---



## 4. Label / under-specification issues

The train key is not a perfect oracle. Three cases (pattern + exemplars):

### 4.1 Blank GT on an exact catalogue `item_name` (label trap)

**Example:** `ACM-T-0064`, `ACM-T-0082`, `ACM-T-0028` (same as Group A).

**Analyse:** The line text matches an active catalogue row, thats why seeing`lexical_unique` @ 1.0, but `gt_item_code` is blank. Scoring calls that `auto_wrong`. 

Depends what the absent label inclined towards: must abstain in these cases (out of system ability to detect the hidden rule) or business side to clarify with client 

**Production:** periodic audit of blank GT ∩ exact/near-exact `item_name`; ensure operator confirms into `customer_sku_map`. 

### 4.2 Brandless underspec with many catalogue twins

**Example:** `ACM-T-0147` — `Cable Tie 200mm White`, blank GT.

**Analyse:** Even if GT were filled, the line does not name a brand among Hitex / Vermont / Stallion / … white 200mm ties. Auto-picking one brand is under-specified for the buyer. 

**Production:** force review when brandless and brand twins remain after attrs

### 4.3 Matching catalogue x available stock

**Example:** `ACM-T-0022` — exact `Kanto Nitrile Glove M Blue` (and siblings differ by size/colour in candidates). Blank GT again. Ops may also care about stock / pack (line UOM `box`) without that being in GT.

**Analyse:**There are other auto_correct matches of out of stock catalogue hence this system does not consider the availability when it comes to decision.

**Production:** separate “match identity” from “promise ship” — matcher returns code + evidence; availability is a downstream gate

---

## 5. Regression safety

Gates below are what I would enforce in CI against the stamped smoke metrics — not yet wired as an exit-code gate in this repo.


| gate                   | break the build if                             | why                                                                   |
| ---------------------- | ---------------------------------------------- | --------------------------------------------------------------------- |
| **Cross-tenant**       | `cross_tenant_violations > 0`                  | Hard correctness; any acme→`NRD-`* or reverse fails the task          |
| **Precision on auto**  | `P < 0.90` on train smoke                      | Below ~90% the −800 AW economics dominate; current baseline ≈0.925    |
| **Auto-wrong ceiling** | `auto_wrong > 18` on this train file           | Allows the known blank-GT Group A mass; forbids new FP modes          |
| **Net value floor**    | `net_value < −20,000`                          | Catches “answer more, precision dies” regressions (~baseline −17,220) |
| **Coverage**           | `coverage < 0.45` **or** `> 0.70` &&`P < 0.92` | Low cov = silent capability loss; high cov + soft P = aggressive auto |
| **p95 latency**        | `p95_ms > 200` on this laptop-class smoke      | Matcher must stay interactive; baseline p95 ≈93 ms                    |
| **Twin regressions**   | any fail in `tests/test_attrs.py`              | Underspec finish/bulk must stay review (Stallion flap, HDG bulk, …)   |


**How the benchmark avoids silent rot**

1. **Noise classes are input-shaped**, not `reason_code`-shaped — so threshold churn cannot redefine the breakdown.
2. **Holdout is unlabelled** — CI does not invent holdout precision; only shape checks (reason mix, coverage band, cross-tenant=0, latency).
3. **Known AW allow-list** — Group A `line_id`s are contested labels; a new AW outside that set is a real regression even if total `aw` stays ≤18.

Reversal triggers already logged in `MINDLOG.md`: restore alias conf floor if low-conf alias FPs appear; tighten OLD→live if successor autos go wrong.