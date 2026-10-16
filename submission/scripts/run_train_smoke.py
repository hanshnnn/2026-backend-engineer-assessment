"""Task 3 train eval harness — one command, reproducible metrics.

From submission/:

    python scripts/run_train_smoke.py

Runs against ../data/order_lines_train.csv and prints:
  - overall metrics (precision on auto, coverage, net value, abstention quality, …)
  - per-tenant breakdown
  - per-noise-class breakdown (input_class; defined in matcher/input_class.py)

Also writes one pair of CSVs per run under submission/debug/:
  train_smoke_<YYYYMMDD_HHMMSS>.csv    — row-level detail
  train_metrics_<YYYYMMDD_HHMMSS>.csv  — overall / tenant / noise-class slices

"""

from __future__ import annotations

import csv
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUBMISSION = Path(__file__).resolve().parents[1]
if str(SUBMISSION) not in sys.path:
    sys.path.insert(0, str(SUBMISSION))

from matcher import MatchService  # noqa: E402
from matcher.input_class import INPUT_CLASSES, classify_input  # noqa: E402

DATA = ROOT / "data"
TRAIN = DATA / "order_lines_train.csv"
OUT_DIR = SUBMISSION / "debug"

METRICS_FIELDS = [
    "id",
    "slice_type",
    "slice_name",
    "n",
    "auto_correct",
    "auto_wrong",
    "abstain_ok",
    "abstain_miss",
    "abstain",
    "precision",
    "coverage",
    "accuracy",
    "net_value",
    "recall_at_3_on_abstain_miss",
    "cross_tenant_violations",
    "latency_p50_ms",
    "latency_p95_ms",
    "latency_max_ms",
]

# Cost model from DESIGN / brief §1 (relative units).
V_CORRECT = 20
V_ABSTAIN = -40
V_WRONG = -800


def _outcome(decision: str, pred: str, gt: str) -> str:
    if decision == "auto":
        if gt and pred == gt:
            return "auto_correct"
        return "auto_wrong"
    if gt:
        return "abstain_miss"
    return "abstain_ok"


def _in_candidates(gt: str, candidates_csv: str) -> bool:
    if not gt or not candidates_csv:
        return False
    for part in candidates_csv.split("|"):
        code = part.split(":", 1)[0].strip()
        if code == gt:
            return True
    return False


def _cross_tenant(tenant: str, item_code: str) -> bool:
    if not item_code:
        return False
    t = (tenant or "").strip().lower()
    code = item_code.upper()
    if t == "acme" and code.startswith("NRD-"):
        return True
    if t == "nordic" and code.startswith("ACM-"):
        return True
    return False


def _slice_stats(rows: list[dict]) -> dict:
    ac = sum(1 for r in rows if r["outcome"] == "auto_correct")
    aw = sum(1 for r in rows if r["outcome"] == "auto_wrong")
    ab_ok = sum(1 for r in rows if r["outcome"] == "abstain_ok")
    ab_miss = sum(1 for r in rows if r["outcome"] == "abstain_miss")
    abstain = ab_ok + ab_miss
    n = len(rows)
    n_auto = ac + aw
    precision = ac / n_auto if n_auto else 0.0
    coverage = n_auto / n if n else 0.0
    accuracy = ac / n if n else 0.0
    net = ac * V_CORRECT + aw * V_WRONG + abstain * V_ABSTAIN
    cand_hits = sum(
        1
        for r in rows
        if r["outcome"] == "abstain_miss" and r["gt_in_candidates"] == "1"
    )
    recall_at_3_on_abstain_miss = cand_hits / ab_miss if ab_miss else 0.0
    return {
        "n": n,
        "auto_correct": ac,
        "auto_wrong": aw,
        "abstain_ok": ab_ok,
        "abstain_miss": ab_miss,
        "abstain": abstain,
        "precision": precision,
        "coverage": coverage,
        "accuracy": accuracy,
        "net": net,
        "recall_at_3_on_abstain_miss": recall_at_3_on_abstain_miss,
    }


def _print_header(title: str) -> None:
    print()
    print(f"=== {title} ===")


def _print_slice(label: str, rows: list[dict]) -> None:
    if not rows:
        return
    s = _slice_stats(rows)
    print(
        f"  {label:28s}  n={s['n']:3d}  "
        f"auto_ok={s['auto_correct']:3d}  auto_bad={s['auto_wrong']:3d}  "
        f"abstain={s['abstain']:3d}  "
        f"P={s['precision']:.3f}  cov={s['coverage']:.3f}  "
        f"net={s['net']:7d}"
    )


def _metrics_row(
    run_id: int,
    slice_type: str,
    slice_name: str,
    rows: list[dict],
    *,
    cross_tenant: int | None = None,
    p50: float | None = None,
    p95: float | None = None,
    pmax: float | None = None,
) -> dict[str, str]:
    s = _slice_stats(rows)
    return {
        "id": str(run_id),
        "slice_type": slice_type,
        "slice_name": slice_name,
        "n": str(s["n"]),
        "auto_correct": str(s["auto_correct"]),
        "auto_wrong": str(s["auto_wrong"]),
        "abstain_ok": str(s["abstain_ok"]),
        "abstain_miss": str(s["abstain_miss"]),
        "abstain": str(s["abstain"]),
        "precision": f"{s['precision']:.4f}",
        "coverage": f"{s['coverage']:.4f}",
        "accuracy": f"{s['accuracy']:.4f}",
        "net_value": str(s["net"]),
        "recall_at_3_on_abstain_miss": f"{s['recall_at_3_on_abstain_miss']:.4f}",
        "cross_tenant_violations": "" if cross_tenant is None else str(cross_tenant),
        "latency_p50_ms": "" if p50 is None else f"{p50:.2f}",
        "latency_p95_ms": "" if p95 is None else f"{p95:.2f}",
        "latency_max_ms": "" if pmax is None else f"{pmax:.2f}",
    }


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run_id = 1
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    svc = MatchService.from_data_dir(DATA)
    reasons: Counter[str] = Counter()
    decisions: Counter[str] = Counter()
    outcomes: Counter[str] = Counter()
    noise_counts: Counter[str] = Counter()
    cross_tenant = 0
    latencies_ms: list[float] = []
    records: list[dict] = []

    row_fields = [
        "id",
        "line_id",
        "tenant",
        "customer_id",
        "order_date",
        "raw_text",
        "buyer_sku",
        "raw_barcode",
        "gt_item_code",
        "noise_class",
        "decision",
        "item_code",
        "confidence",
        "reason_code",
        "candidates",
        "outcome",
        "gt_in_candidates",
    ]

    with TRAIN.open(newline="", encoding="utf-8") as fh_in:
        for row in csv.DictReader(fh_in):
            noise_class = classify_input(row, svc.catalogue)
            noise_counts[noise_class] += 1

            t0 = time.perf_counter()
            result = svc.match(row)
            latencies_ms.append((time.perf_counter() - t0) * 1000.0)

            decisions[result.decision] += 1
            reasons[result.reason_code] += 1
            gt = (row.get("gt_item_code") or "").strip()
            pred = result.item_code or ""
            outcome = _outcome(result.decision, pred, gt)
            outcomes[outcome] += 1
            cands = result.candidates_csv()
            gt_in = "1" if _in_candidates(gt, cands) else "0"
            if _cross_tenant(row.get("tenant", ""), pred):
                cross_tenant += 1

            records.append(
                {
                    "id": str(run_id),
                    "line_id": row.get("line_id", ""),
                    "tenant": row.get("tenant", ""),
                    "customer_id": row.get("customer_id", ""),
                    "order_date": row.get("order_date", ""),
                    "raw_text": row.get("raw_text", ""),
                    "buyer_sku": row.get("buyer_sku", ""),
                    "raw_barcode": row.get("raw_barcode", ""),
                    "gt_item_code": gt,
                    "noise_class": noise_class,
                    "decision": result.decision,
                    "item_code": pred,
                    "confidence": f"{result.confidence:.4f}",
                    "reason_code": result.reason_code,
                    "candidates": cands,
                    "outcome": outcome,
                    "gt_in_candidates": gt_in,
                }
            )
            run_id += 1

    overall = _slice_stats(records)
    latencies_ms.sort()
    p50 = latencies_ms[len(latencies_ms) // 2] if latencies_ms else 0.0
    p95 = (
        latencies_ms[max(0, int(len(latencies_ms) * 0.95) - 1)] if latencies_ms else 0.0
    )
    pmax = latencies_ms[-1] if latencies_ms else 0.0

    by_tenant: dict[str, list[dict]] = defaultdict(list)
    by_noise: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_tenant[r["tenant"]].append(r)
        by_noise[r["noise_class"]].append(r)
    run_id = 1
    metric_rows: list[dict[str, str]] = [
        _metrics_row(
            run_id,
            "overall",
            "all",
            records,
            cross_tenant=cross_tenant,
            p50=p50,
            p95=p95,
            pmax=pmax,
        )
    ]
    run_id += 1
    for tenant in sorted(by_tenant):
        metric_rows.append(
            _metrics_row(run_id, "tenant", tenant, by_tenant[tenant])
        )
        run_id += 1
    for name in INPUT_CLASSES:
        if name in by_noise:
            metric_rows.append(
                _metrics_row(run_id, "noise_class", name, by_noise[name])
            )
            run_id += 1
    for name in sorted(set(by_noise) - set(INPUT_CLASSES)):
        metric_rows.append(
            _metrics_row(run_id, "noise_class", name, by_noise[name])
        )
        run_id += 1

    # One smoke + one metrics file per run (timestamped names; sequential id inside).
    smoke_path = OUT_DIR / f"train_smoke_{stamp}.csv"
    metrics_path = OUT_DIR / f"train_metrics_{stamp}.csv"
    _write_csv(smoke_path, row_fields, records)
    _write_csv(metrics_path, METRICS_FIELDS, metric_rows)

    print(f"Task 3 harness — order_lines_train.csv  id={run_id}")
    print(f"cost model: auto_correct={V_CORRECT:+d}  abstain={V_ABSTAIN:+d}  auto_wrong={V_WRONG:+d}")

    _print_header("overall")
    print(f"  lines                 {overall['n']}")
    print(f"  decisions             {dict(decisions)}")
    print(f"  outcomes              {dict(outcomes)}")
    print(
        f"  precision_on_auto     {overall['precision']:.4f}  "
        f"({overall['auto_correct']}/{overall['auto_correct'] + overall['auto_wrong']})"
    )
    print(f"  coverage              {overall['coverage']:.4f}")
    print(
        f"  accuracy (misleading) {overall['accuracy']:.4f}  "
        f"(correct-auto / all lines — ignores abstain quality)"
    )
    print(f"  net_value             {overall['net']}")
    print(
        f"  recall@3_abstain_miss {overall['recall_at_3_on_abstain_miss']:.4f}  "
        f"(GT in candidates when we abstained but GT existed)"
    )
    print(f"  cross_tenant_violations {cross_tenant}")
    print(f"  latency_ms            p50={p50:.2f}  p95={p95:.2f}  max={pmax:.2f}")
    print(f"  noise_class_counts    {dict(noise_counts)}")
    print(f"  reason_code_counts    {dict(reasons)}  (matcher path — not noise class)")

    _print_header("per tenant")
    for tenant in sorted(by_tenant):
        _print_slice(tenant, by_tenant[tenant])

    _print_header("per noise class (input_class)")
    print("  taxonomy: matcher/input_class.py — line shape, not reason_code")
    for name in INPUT_CLASSES:
        _print_slice(name, by_noise.get(name, []))
    for name in sorted(set(by_noise) - set(INPUT_CLASSES)):
        _print_slice(name, by_noise[name])

    print()
    print(f"wrote_rows={smoke_path}")
    print(f"wrote_metrics={metrics_path}")


if __name__ == "__main__":
    main()
