# Submission — Mindhive 2026 Backend Engineer Assessment

## Timebox

Most of the window went into Task 2–3 (matcher + eval). Task 5 (sync) is done with
fixes and isolating tests. Task 4 (PERF) and Task 6 (SCALE) are intentionally stubbed —
I chose matcher precision under the −800 cost model over finishing every section shallowly.

## Deliverables status


| File / Path                                    | Task                                                   | Status               |
| ---------------------------------------------- | ------------------------------------------------------ | -------------------- |
| `[DESIGN.md](DESIGN.md)`                       | Task 1 — Problem framing & pipeline design             | Complete             |
| `[DECISIONS.md](DECISIONS.md)`                 | §9 — Decision log (`D-01` … `D-09`)                    | Complete             |
| `[predictions.csv](predictions.csv)`           | Task 2 — Holdout predictions (300 rows)                | Complete             |
| `matcher/` + `tests/` + `scripts/`             | Task 2 — Matcher service, unit tests, runners          | Complete             |
| `[EVAL.md](EVAL.md)`                           | Task 3 — Evaluation harness, curves, 20-error analysis | Complete             |
| `[SYNC.md](SYNC.md)` + `starter/sync/` + tests | Task 5 — ERP sync adapter diagnosis & fixes            | Complete             |
| `[PERF.md](PERF.md)`                           | Task 4 — SQLite report diagnosis & optimization        | Stub — not attempted |
| `[SCALE.md](SCALE.md)`                         | Task 6 — Scaling to 500 tenants / 4M items             | Stub — not attempted |


---



## Clean-machine setup

Requires **Python 3.10+** and `rapidfuzz` (allowed in §5.2; no network calls at inference time).

```bash
pip install rapidfuzz
```

All commands below assume your working directory is `submission/` (with dataset files in `../data/`):

```bash
cd submission
```

---



## How to run

### 1. Run unit & integration tests (barcode, alias, brand, phrases, attrs, cold-start)

```bash
python -m unittest discover -s tests -v
```



### 2. Generate holdout `predictions.csv` (Task 2 deliverable)

```bash
python scripts/run_holdout.py
```

Writes `submission/predictions.csv` with exact schema:
`line_id,item_code,confidence,decision,reason_code,candidates` (`300` rows; `item_code` is blank whenever `decision != "auto"`).

### 3. Run train evaluation harness (Task 3)

```bash
python scripts/run_train_smoke.py
```

One-command, reproducible eval on `../data/order_lines_train.csv` (`420` rows). Prints:

- overall: precision on `auto`, coverage, net value (`+20` / `-40` / `-800`), recall@3 on abstain-miss, cross-tenant violations, latency
- per-**tenant** breakdown
- per-**noise-class** breakdown (9 classes in `matcher/input_class.py`)
- `reason_code` counts (matcher path — separate from noise class)

Writes one pair of CSVs per run under `submission/debug/`:

- `train_smoke_<YYYYMMDD_HHMMSS>.csv` — row-level detail
- `train_metrics_<YYYYMMDD_HHMMSS>.csv` — overall / tenant / noise-class slices

Both include a sequential integer column `id` (`1`, `2`, …) shared for that run.

### 4. Operating-point sweeps (Task 3.2)

```bash
python scripts/sweep_operating_point.py
# optional: --csv debug/train_smoke_<stamp>.csv
```

Post-hoc sweeps over the latest (or given) `train_smoke_*.csv`:

- confidence τ gate
- `AUTO_FLOOR` × `MARGIN` grid (text decide on stored `candidates`; ID autos fixed)

Prints both tables and writes `debug/operating_point_sweep_<stamp>.csv`. See `EVAL.md` §2.

---



## Current matcher snapshot (Task 2)


| Dataset                   | Lines | `auto` | `review` | `reject` | Coverage | Precision on `auto` | Net value      |
| ------------------------- | ----- | ------ | -------- | -------- | -------- | ------------------- | -------------- |
| `order_lines_train.csv`   | 420   | 239    | 132      | 49       | 56.9%    | 92.47% (221 / 239)  | −17,220        |
| `order_lines_holdout.csv` | 300   | 160    | 103      | 37       | 53.3%    | *(unlabelled)*      | *(unlabelled)* |


