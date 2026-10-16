"""Post-hoc operating-point sweeps over a train_smoke CSV (Task 3.2).

Two axes (matcher scoring held fixed; candidates already in the smoke file):

1. **confidence τ** — demote ``decision=auto`` when ``confidence < τ``.
2. **AUTO_FLOOR × MARGIN** — re-apply the text decide rule on parsed
   ``candidates`` scores. ID-lane autos (barcode / alias) are unchanged;
   ``ambiguous_twins`` / ``reject`` never promote to auto.

Writes ``debug/operating_point_sweep_<stamp>.csv`` (or ``--out``).

Usage (from submission/):
  python scripts/sweep_operating_point.py
  python scripts/sweep_operating_point.py --csv debug/train_smoke_YYYYMMDD_HHMMSS.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEBUG = ROOT / "debug"

V_CORRECT = 20
V_ABSTAIN = -40
V_WRONG = -800

# As-shipped text knobs (matcher/lanes/text.py).
SHIPPED_AUTO_FLOOR = 0.90
SHIPPED_MARGIN = 0.03

DEFAULT_TAUS = (0.0, 0.72, 0.80, 0.85, 0.90, 0.92, 0.95, 0.98, 1.0)
DEFAULT_AUTO_FLOORS = (0.85, 0.88, 0.90, 0.92, 0.95, 0.98, 1.0)
DEFAULT_MARGINS = (0.00, 0.02, 0.03, 0.05, 0.08, 0.10)

# ID-lane autos are not gated by text AUTO_FLOOR / MARGIN.
_ID_AUTO_REASONS = frozenset(
    {"barcode_hit", "alias_exact", "alias_old_successor"}
)
# Hard abstains — never promote via floor/margin post-hoc.
_NO_PROMOTE_REASONS = frozenset(
    {
        "ambiguous_twins",
        "not_an_item",
        "brand_not_in_tenant",
        "ambiguous_alias",
        "ambiguous_barcode",
        "id_id_conflict",
        "id_text_conflict",
    }
)

_OUT_FIELDS = [
    "sweep",
    "tau",
    "auto_floor",
    "margin",
    "n",
    "auto_correct",
    "auto_wrong",
    "abstain_ok",
    "abstain_miss",
    "precision",
    "coverage",
    "accuracy",
    "net_value",
]


def _latest_smoke() -> Path:
    stamped = sorted(DEBUG.glob("train_smoke_20*.csv"))
    if not stamped:
        raise SystemExit(
            f"No train_smoke_20*.csv under {DEBUG}; run run_train_smoke.py first."
        )
    return stamped[-1]


def _parse_candidates(raw: str) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for part in (raw or "").split("|"):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            continue
        code, score_s = part.split(":", 1)
        try:
            out.append((code.strip(), float(score_s)))
        except ValueError:
            continue
    return out


def _outcome_from_auto(pred: str, gt: str) -> str:
    if gt and pred == gt:
        return "auto_correct"
    return "auto_wrong"


def _outcome_abstain(gt: str) -> str:
    return "abstain_miss" if gt else "abstain_ok"


def _text_passes(cands: list[tuple[str, float]], auto_floor: float, margin: float) -> bool:
    if not cands:
        return False
    top = cands[0][1]
    second = cands[1][1] if len(cands) > 1 else 0.0
    return top >= auto_floor and (top - second) >= margin


def _row_outcome_conf(row: dict, tau: float) -> str:
    decision = row.get("decision", "")
    conf = float(row.get("confidence") or 0.0)
    pred = (row.get("item_code") or "").strip()
    gt = (row.get("gt_item_code") or "").strip()
    if decision == "auto" and conf >= tau:
        return _outcome_from_auto(pred, gt)
    return _outcome_abstain(gt)


def _row_outcome_floor_margin(
    row: dict, auto_floor: float, margin: float
) -> str:
    """Re-decide auto vs abstain under text floors; ID autos kept."""
    decision = row.get("decision", "")
    reason = row.get("reason_code", "")
    pred = (row.get("item_code") or "").strip()
    gt = (row.get("gt_item_code") or "").strip()
    cands = _parse_candidates(row.get("candidates") or "")

    if decision == "auto" and reason in _ID_AUTO_REASONS:
        return _outcome_from_auto(pred, gt)

    if decision == "reject" or reason in _NO_PROMOTE_REASONS:
        return _outcome_abstain(gt)

    # Text-shaped path: lexical auto, or review that might promote.
    if _text_passes(cands, auto_floor, margin):
        top_code = cands[0][0]
        return _outcome_from_auto(top_code, gt)
    return _outcome_abstain(gt)


def _aggregate(outcomes: list[str]) -> dict:
    ac = sum(1 for o in outcomes if o == "auto_correct")
    aw = sum(1 for o in outcomes if o == "auto_wrong")
    ab_ok = sum(1 for o in outcomes if o == "abstain_ok")
    ab_miss = sum(1 for o in outcomes if o == "abstain_miss")
    n = len(outcomes)
    n_auto = ac + aw
    abstain = ab_ok + ab_miss
    return {
        "n": n,
        "auto_correct": ac,
        "auto_wrong": aw,
        "abstain_ok": ab_ok,
        "abstain_miss": ab_miss,
        "precision": (ac / n_auto) if n_auto else 0.0,
        "coverage": (n_auto / n) if n else 0.0,
        "accuracy": (ac / n) if n else 0.0,
        "net_value": ac * V_CORRECT + aw * V_WRONG + abstain * V_ABSTAIN,
    }


def _stats_conf(rows: list[dict], tau: float) -> dict:
    s = _aggregate([_row_outcome_conf(r, tau) for r in rows])
    s.update(
        {
            "sweep": "confidence_tau",
            "tau": tau,
            "auto_floor": SHIPPED_AUTO_FLOOR,
            "margin": SHIPPED_MARGIN,
        }
    )
    return s


def _stats_floor_margin(
    rows: list[dict], auto_floor: float, margin: float
) -> dict:
    s = _aggregate(
        [_row_outcome_floor_margin(r, auto_floor, margin) for r in rows]
    )
    s.update(
        {
            "sweep": "auto_floor_margin",
            "tau": "",
            "auto_floor": auto_floor,
            "margin": margin,
        }
    )
    return s


def _print_table(title: str, rows_out: list[dict], cols: list[str]) -> None:
    print()
    print(f"=== {title} ===")
    # Header widths from col names + sample.
    widths = {c: max(len(c), 6) for c in cols}
    for r in rows_out:
        for c in cols:
            widths[c] = max(widths[c], len(str(_fmt(r, c))))
    hdr = "  ".join(f"{c:>{widths[c]}}" for c in cols)
    print(hdr)
    print("-" * len(hdr))
    for r in rows_out:
        print("  ".join(f"{_fmt(r, c):>{widths[c]}}" for c in cols))


def _fmt(r: dict, c: str) -> str:
    v = r[c]
    if c in {"precision", "coverage", "accuracy"} and isinstance(v, float):
        return f"{v:.3f}"
    if c in {"tau", "auto_floor", "margin"} and v != "" and isinstance(v, float):
        return f"{v:.2f}"
    if c == "tau" and v == "":
        return "-"
    return str(v)


def _write_csv(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=_OUT_FIELDS)
        w.writeheader()
        for r in records:
            w.writerow(
                {
                    "sweep": r["sweep"],
                    "tau": "" if r["tau"] == "" else f"{float(r['tau']):.4f}",
                    "auto_floor": f"{float(r['auto_floor']):.4f}",
                    "margin": f"{float(r['margin']):.4f}",
                    "n": r["n"],
                    "auto_correct": r["auto_correct"],
                    "auto_wrong": r["auto_wrong"],
                    "abstain_ok": r["abstain_ok"],
                    "abstain_miss": r["abstain_miss"],
                    "precision": f"{r['precision']:.6f}",
                    "coverage": f"{r['coverage']:.6f}",
                    "accuracy": f"{r['accuracy']:.6f}",
                    "net_value": r["net_value"],
                }
            )


def _parse_floats(s: str) -> list[float]:
    return [float(x.strip()) for x in s.split(",") if x.strip()]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", type=Path, default=None, help="train_smoke CSV")
    ap.add_argument(
        "--taus",
        default=",".join(str(t) for t in DEFAULT_TAUS),
        help="confidence floors",
    )
    ap.add_argument(
        "--auto-floors",
        default=",".join(str(t) for t in DEFAULT_AUTO_FLOORS),
        help="AUTO_FLOOR grid",
    )
    ap.add_argument(
        "--margins",
        default=",".join(str(t) for t in DEFAULT_MARGINS),
        help="MARGIN grid",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output CSV (default: debug/operating_point_sweep_<smoke_stamp>.csv)",
    )
    args = ap.parse_args()

    path = args.csv or _latest_smoke()
    if not path.is_file():
        raise SystemExit(f"CSV not found: {path}")

    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise SystemExit(f"Empty CSV: {path}")

    taus = _parse_floats(args.taus)
    floors = _parse_floats(args.auto_floors)
    margins = _parse_floats(args.margins)

    rel = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    print(f"source={rel}")
    print(f"n={len(rows)}  cost=+{V_CORRECT}/{V_ABSTAIN}/{V_WRONG}")
    print(
        f"shipped text knobs: AUTO_FLOOR={SHIPPED_AUTO_FLOOR}  "
        f"MARGIN={SHIPPED_MARGIN}"
    )

    conf_rows = [_stats_conf(rows, tau) for tau in taus]
    _print_table(
        "confidence τ (AUTO_FLOOR/MARGIN fixed at shipped)",
        conf_rows,
        [
            "tau",
            "coverage",
            "precision",
            "accuracy",
            "net_value",
            "auto_correct",
            "auto_wrong",
            "abstain_ok",
            "abstain_miss",
        ],
    )

    fm_rows = [
        _stats_floor_margin(rows, af, mg)
        for af in floors
        for mg in margins
    ]
    _print_table(
        "AUTO_FLOOR × MARGIN (ID autos fixed; no conf gate)",
        fm_rows,
        [
            "auto_floor",
            "margin",
            "coverage",
            "precision",
            "accuracy",
            "net_value",
            "auto_correct",
            "auto_wrong",
            "abstain_ok",
            "abstain_miss",
        ],
    )

    # Highlight shipped cell + best net on floor×margin grid.
    shipped = next(
        (
            r
            for r in fm_rows
            if abs(r["auto_floor"] - SHIPPED_AUTO_FLOOR) < 1e-9
            and abs(r["margin"] - SHIPPED_MARGIN) < 1e-9
        ),
        None,
    )
    best = max(fm_rows, key=lambda r: r["net_value"])
    print()
    if shipped:
        print(
            f"shipped cell (0.90 / 0.03): "
            f"P={shipped['precision']:.4f}  cov={shipped['coverage']:.4f}  "
            f"net={shipped['net_value']}  aw={shipped['auto_wrong']}"
        )
    print(
        f"best net on AUTO_FLOOR×MARGIN grid: "
        f"floor={best['auto_floor']:.2f}  margin={best['margin']:.2f}  "
        f"P={best['precision']:.4f}  cov={best['coverage']:.4f}  "
        f"net={best['net_value']}  aw={best['auto_wrong']}"
    )
    print(
        "Note: residual blank-GT lexical_unique FPs at conf=1.0 clear every "
        "reasonable floor/margin; knobs mostly trade TPs, not those FPs."
    )

    stamp_m = re.search(r"train_smoke_(\d{8}_\d{6})", path.name)
    stamp = stamp_m.group(1) if stamp_m else "manual"
    out = args.out or (DEBUG / f"operating_point_sweep_{stamp}.csv")
    all_rows = conf_rows + fm_rows
    _write_csv(out, all_rows)
    out_rel = out.relative_to(ROOT) if out.is_relative_to(ROOT) else out
    print(f"\nwrote={out_rel}  rows={len(all_rows)}")


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(0)
