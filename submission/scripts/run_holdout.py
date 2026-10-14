"""Run matcher on order_lines_holdout.csv → predictions.csv (Task 2 deliverable)."""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUBMISSION = Path(__file__).resolve().parents[1]
if str(SUBMISSION) not in sys.path:
    sys.path.insert(0, str(SUBMISSION))

from matcher import MatchService  # noqa: E402

DATA = ROOT / "data"
HOLDOUT = DATA / "order_lines_holdout.csv"
OUT = SUBMISSION / "predictions.csv"

FIELDS = ["line_id", "item_code", "confidence", "decision", "reason_code", "candidates"]


def main() -> None:
    svc = MatchService.from_data_dir(DATA)
    decisions: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    n = 0

    with HOLDOUT.open(newline="", encoding="utf-8") as fh_in, OUT.open(
        "w", newline="", encoding="utf-8"
    ) as fh_out:
        writer = csv.DictWriter(fh_out, fieldnames=FIELDS)
        writer.writeheader()
        for row in csv.DictReader(fh_in):
            n += 1
            result = svc.match(row)
            decisions[result.decision] += 1
            reasons[result.reason_code] += 1
            # README: item_code blank when abstaining (review/reject).
            item_code = result.item_code if result.decision == "auto" else ""
            writer.writerow(
                {
                    "line_id": (row.get("line_id") or "").strip(),
                    "item_code": item_code,
                    "confidence": f"{result.confidence:.4f}",
                    "decision": result.decision,
                    "reason_code": result.reason_code,
                    "candidates": result.candidates_csv(),
                }
            )

    print(f"lines={n}")
    print(f"decisions={dict(decisions)}")
    print(f"reasons={dict(reasons)}")
    print(f"wrote={OUT}")


if __name__ == "__main__":
    main()
