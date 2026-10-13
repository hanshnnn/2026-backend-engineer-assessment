"""Smoke-run matcher on order_lines_train.csv (slice 0+1 diagnostics)."""

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
TRAIN = DATA / "order_lines_train.csv"

# Relative costs from DESIGN
V_CORRECT = 20
V_ABSTAIN = -40
V_WRONG = -800


def main() -> None:
    svc = MatchService.from_data_dir(DATA)
    reasons: Counter[str] = Counter()
    decisions: Counter[str] = Counter()
    auto_correct = auto_wrong = abstain = 0
    n = 0

    with TRAIN.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            n += 1
            result = svc.match(row)
            decisions[result.decision] += 1
            reasons[result.reason_code] += 1
            gt = (row.get("gt_item_code") or "").strip()

            if result.decision == "auto":
                if result.item_code == gt and gt:
                    auto_correct += 1
                else:
                    auto_wrong += 1
            else:
                abstain += 1

    coverage = (auto_correct + auto_wrong) / n if n else 0.0
    precision = auto_correct / (auto_correct + auto_wrong) if (auto_correct + auto_wrong) else 0.0
    net = auto_correct * V_CORRECT + auto_wrong * V_WRONG + abstain * V_ABSTAIN

    print(f"lines={n}")
    print(f"decisions={dict(decisions)}")
    print(f"reasons={dict(reasons)}")
    print(f"auto_correct={auto_correct} auto_wrong={auto_wrong} abstain={abstain}")
    print(f"precision_on_auto={precision:.4f} coverage={coverage:.4f} net_value={net}")
    print("note: text lane is stubbed — most lines abstain with no_candidate_above_floor")


if __name__ == "__main__":
    main()
