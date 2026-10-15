"""Smoke-run matcher + export text-lane parse debug CSV.

Same outcomes as run_train_smoke.py, plus columns for brand / phrase / attrs
so you can see how the system split each line.
"""

from __future__ import annotations

import csv
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUBMISSION = Path(__file__).resolve().parents[1]
if str(SUBMISSION) not in sys.path:
    sys.path.insert(0, str(SUBMISSION))

from matcher import MatchService  # noqa: E402
from matcher.attrs import Attrs, extract_item_attrs  # noqa: E402
from matcher.lanes.text import retrieve_text  # noqa: E402
from matcher.phrases import item_phrase, query_for_phrase  # noqa: E402

DATA = ROOT / "data"
TRAIN = DATA / "order_lines_train.csv"
OUT_DIR = SUBMISSION / "debug"
OUT_DEFAULT = OUT_DIR / "train_smoke_debug.csv"

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


def _fmt_sizes(attrs: Attrs | None) -> str:
    if attrs is None or not attrs.sizes:
        return ""
    return "|".join(sorted(attrs.sizes))


def _fmt_bulk(attrs: Attrs | None) -> str:
    if attrs is None or attrs.bulk is None:
        return ""
    return "1" if attrs.bulk else "0"


def _item_debug(svc: MatchService, tenant: str, item_code: str) -> dict[str, str]:
    """Catalogue name / phrase / attrs for one code (empty if missing)."""
    empty = {
        "item_name": "",
        "phrase": "",
        "attr_sizes": "",
        "attr_finish": "",
        "attr_colour": "",
        "attr_grade": "",
        "attr_bulk": "",
    }
    if not item_code:
        return empty
    item = svc.catalogue.get(tenant, item_code)
    if item is None:
        return empty
    ia = extract_item_attrs(item.item_name)
    return {
        "item_name": item.item_name,
        "phrase": item_phrase(item),
        "attr_sizes": _fmt_sizes(ia),
        "attr_finish": ia.finish or "",
        "attr_colour": ia.colour or "",
        "attr_grade": ia.grade or "",
        "attr_bulk": _fmt_bulk(ia),
    }


def main() -> None:
    svc = MatchService.from_data_dir(DATA)
    reasons: Counter[str] = Counter()
    decisions: Counter[str] = Counter()
    outcomes: Counter[str] = Counter()
    auto_correct = auto_wrong = abstain = 0
    n = 0
    latencies_ms: list[float] = []

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DEFAULT
    try:
        fh_out = out_path.open("w", newline="", encoding="utf-8")
    except PermissionError:
        out_path = OUT_DIR / f"train_smoke_debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
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
        # text-lane parse
        "norm_text",
        "brand",
        "brand_how",
        "phrase_query",
        "attr_sizes",
        "attr_finish",
        "attr_colour",
        "attr_grade",
        "attr_bulk",
        "pool_size",
        "text_refuse",
        # predicted catalogue view
        "pred_item_name",
        "pred_phrase",
        "pred_attr_sizes",
        "pred_attr_finish",
        "pred_attr_colour",
        "pred_attr_grade",
        "pred_attr_bulk",
        # ground-truth catalogue view
        "gt_item_name",
        "gt_phrase",
        "gt_attr_sizes",
        "gt_attr_finish",
        "gt_attr_colour",
        "gt_attr_grade",
        "gt_attr_bulk",
    ]

    with TRAIN.open(newline="", encoding="utf-8") as fh_in, fh_out:
        writer = csv.DictWriter(fh_out, fieldnames=fieldnames)
        writer.writeheader()
        for row in csv.DictReader(fh_in):
            n += 1
            t0 = time.perf_counter()
            result = svc.match(row)
            latencies_ms.append((time.perf_counter() - t0) * 1000.0)
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

            tenant = (row.get("tenant") or "").strip()
            raw_text = row.get("raw_text") or ""
            retrieval = retrieve_text(tenant, raw_text, svc.catalogue)
            qattrs = retrieval.query_attrs
            phrase_q = (
                query_for_phrase(retrieval.normalized, retrieval.brand)
                if retrieval.normalized
                else ""
            )
            pred_dbg = _item_debug(svc, tenant, pred)
            gt_dbg = _item_debug(svc, tenant, gt)

            writer.writerow(
                {
                    "line_id": row.get("line_id", ""),
                    "tenant": tenant,
                    "customer_id": row.get("customer_id", ""),
                    "order_date": row.get("order_date", ""),
                    "raw_text": raw_text,
                    "buyer_sku": row.get("buyer_sku", ""),
                    "raw_barcode": row.get("raw_barcode", ""),
                    "gt_item_code": gt,
                    "decision": result.decision,
                    "item_code": pred,
                    "confidence": f"{result.confidence:.4f}",
                    "reason_code": result.reason_code,
                    "candidates": result.candidates_csv(),
                    "outcome": outcome,
                    "norm_text": retrieval.normalized,
                    "brand": retrieval.brand or "",
                    "brand_how": retrieval.brand_how,
                    "phrase_query": phrase_q,
                    "attr_sizes": _fmt_sizes(qattrs),
                    "attr_finish": (qattrs.finish if qattrs else None) or "",
                    "attr_colour": (qattrs.colour if qattrs else None) or "",
                    "attr_grade": (qattrs.grade if qattrs else None) or "",
                    "attr_bulk": _fmt_bulk(qattrs),
                    "pool_size": retrieval.pool_size,
                    "text_refuse": retrieval.refuse_reason or "",
                    "pred_item_name": pred_dbg["item_name"],
                    "pred_phrase": pred_dbg["phrase"],
                    "pred_attr_sizes": pred_dbg["attr_sizes"],
                    "pred_attr_finish": pred_dbg["attr_finish"],
                    "pred_attr_colour": pred_dbg["attr_colour"],
                    "pred_attr_grade": pred_dbg["attr_grade"],
                    "pred_attr_bulk": pred_dbg["attr_bulk"],
                    "gt_item_name": gt_dbg["item_name"],
                    "gt_phrase": gt_dbg["phrase"],
                    "gt_attr_sizes": gt_dbg["attr_sizes"],
                    "gt_attr_finish": gt_dbg["attr_finish"],
                    "gt_attr_colour": gt_dbg["attr_colour"],
                    "gt_attr_grade": gt_dbg["attr_grade"],
                    "gt_attr_bulk": gt_dbg["attr_bulk"],
                }
            )

    coverage = (auto_correct + auto_wrong) / n if n else 0.0
    precision = (
        auto_correct / (auto_correct + auto_wrong) if (auto_correct + auto_wrong) else 0.0
    )
    net = auto_correct * V_CORRECT + auto_wrong * V_WRONG + abstain * V_ABSTAIN

    latencies_ms.sort()
    if latencies_ms:
        p50 = latencies_ms[len(latencies_ms) // 2]
        p95 = latencies_ms[max(0, int(len(latencies_ms) * 0.95) - 1)]
        pmax = latencies_ms[-1]
    else:
        p50 = p95 = pmax = 0.0

    print(f"lines={n}")
    print(f"decisions={dict(decisions)}")
    print(f"reasons={dict(reasons)}")
    print(f"outcomes={dict(outcomes)}")
    print(f"auto_correct={auto_correct} auto_wrong={auto_wrong} abstain={abstain}")
    print(f"precision_on_auto={precision:.4f} coverage={coverage:.4f} net_value={net}")
    print(f"latency_ms p50={p50:.2f} p95={p95:.2f} max={pmax:.2f}")
    print(f"wrote={out_path}")


if __name__ == "__main__":
    main()
