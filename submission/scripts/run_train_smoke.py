"""Smoke-run matcher on order_lines_train.csv + export debug CSV."""

from __future__ import annotations

import csv
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUBMISSION = Path(__file__).resolve().parents[1]
if str(SUBMISSION) not in sys.path:
    sys.path.insert(0, str(SUBMISSION))

from matcher import MatchService  # noqa: E402

DATA = ROOT / "data"
TRAIN = DATA / "order_lines_train.csv"
OUT_DIR = SUBMISSION / "debug"
OUT_DEFAULT = OUT_DIR / "train_smoke.csv"

# Relative costs from DESIGN
V_CORRECT = 20
V_ABSTAIN = -40
V_WRONG = -800


def _outcome(decision: str, pred: str, gt: str) -> str:
    if decision == "auto":
        if gt and pred == gt:
            return "auto_correct"
        return "auto_wrong"
    if gt:
        return "abstain_miss"  # had a label, we refused
    return "abstain_ok"  # blank gt, correctly refused


def main() -> None:
    svc = MatchService.from_data_dir(DATA)
    reasons: Counter[str] = Counter()
    decisions: Counter[str] = Counter()
    outcomes: Counter[str] = Counter()
    auto_correct = auto_wrong = abstain = 0
    n = 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DEFAULT
    try:
        fh_out = out_path.open("w", newline="", encoding="utf-8")
    except PermissionError:
        out_path = OUT_DIR / f"train_smoke_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        fh_out = out_path.open("w", newline="", encoding="utf-8")

    fieldnames = [
        "line_id",
        "tenant",
        "customer_id",
        "order_date",
        "raw_text",
        "buyer_sku",
        "raw_barcode",
        "gt_item_code",
        "decision",
        "item_code",
        "confidence",
        "reason_code",
        "candidates",
        "outcome",
    ]

    with TRAIN.open(newline="", encoding="utf-8") as fh_in, fh_out:
        writer = csv.DictWriter(fh_out, fieldnames=fieldnames)
        writer.writeheader()
        for row in csv.DictReader(fh_in):
            n += 1
            result = svc.match(row)
            decisions[result.decision] += 1
            reasons[result.reason_code] += 1
            gt = (row.get("gt_item_code") or "").strip()
            pred = result.item_code or ""
            outcome = _outcome(result.decision, pred, gt)
            outcomes[outcome] += 1

            if result.decision == "auto":
                if pred == gt and gt:
                    auto_correct += 1
                else:
                    auto_wrong += 1
            else:
                abstain += 1

            writer.writerow(
                {
                    "line_id": row.get("line_id", ""),
                    "tenant": row.get("tenant", ""),
                    "customer_id": row.get("customer_id", ""),
                    "order_date": row.get("order_date", ""),
                    "raw_text": row.get("raw_text", ""),
                    "buyer_sku": row.get("buyer_sku", ""),
                    "raw_barcode": row.get("raw_barcode", ""),
                    "gt_item_code": gt,
                    "decision": result.decision,
                    "item_code": pred,
                    "confidence": f"{result.confidence:.4f}",
                    "reason_code": result.reason_code,
                    "candidates": result.candidates_csv(),
                    "outcome": outcome,
                }
            )

    coverage = (auto_correct + auto_wrong) / n if n else 0.0
    precision = (
        auto_correct / (auto_correct + auto_wrong) if (auto_correct + auto_wrong) else 0.0
    )
    net = auto_correct * V_CORRECT + auto_wrong * V_WRONG + abstain * V_ABSTAIN

    print(f"lines={n}")
    print(f"decisions={dict(decisions)}")
    print(f"reasons={dict(reasons)}")
    print(f"outcomes={dict(outcomes)}")
    print(f"auto_correct={auto_correct} auto_wrong={auto_wrong} abstain={abstain}")
    print(f"precision_on_auto={precision:.4f} coverage={coverage:.4f} net_value={net}")
    print(f"wrote={out_path}")


if __name__ == "__main__":
    main()
