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


(Post-hoc cell at shipped 0.90/0.03 can differ by a couple of lines from live smoke totals — re-decide on stored top-3 candidates, not a full matcher re-run.)

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

*Stub — pick 20* `line_id`*s from* `auto_wrong` *+ costly* `abstain_miss`*; root cause, cost class, fix grouping.*

---



## 4. Label / under-specification issues

*Stub — ≥3 lines where GT is wrong or the task is underspecified.*

---



## 5. Regression safety

*Stub — concrete gates on precision / net / cross-tenant / p95 latency that break the build.*