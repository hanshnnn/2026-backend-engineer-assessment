"""Buyer-SKU alias lane — dirty memory with uniqueness gate."""

from __future__ import annotations

from datetime import date

from ..alias_index import AliasIndex
from ..catalogue import CatalogueIndex
from ..types import Candidate, LaneOutcome, MatchResult, TentativeHit

# Unique in-date active alias → auto regardless of confidence band (0.55 / 0.72 / 1.0).
# Floor kept as a knob for reversal; 0.0 = no conf gate (train evidence 2026-10-14).
ALIAS_AUTO_FLOOR = 0.0


def run_alias(
    tenant: str,
    customer_id: str,
    buyer_sku: str,
    order_date: date,
    aliases: AliasIndex,
    catalogue: CatalogueIndex,
    auto_floor: float = ALIAS_AUTO_FLOOR,
) -> LaneOutcome:
    sku = (buyer_sku or "").strip()
    if not sku:
        return LaneOutcome()

    rows = aliases.lookup(tenant, customer_id, sku, order_date, catalogue)
    if not rows:
        # Empty, expired, or only superseded/disabled → fall through to text.
        return LaneOutcome()

    # Collapse to distinct codes; keep max confidence per code.
    best: dict[str, float] = {}
    for row in rows:
        prev = best.get(row.item_code)
        if prev is None or row.confidence > prev:
            best[row.item_code] = row.confidence

    codes = sorted(best.keys())  # stable order for candidates
    cands = [Candidate(code, best[code]) for code in codes[:3]]

    if len(codes) >= 2:
        return LaneOutcome(
            result=MatchResult(
                decision="review",
                reason_code="ambiguous_alias",
                confidence=0.0,
                candidates=cands,
            )
        )

    code = codes[0]
    conf = best[code]
    if conf < auto_floor:
        # Reversal path only — unused while ALIAS_AUTO_FLOOR == 0.0.
        return LaneOutcome(
            result=MatchResult(
                decision="review",
                reason_code="alias_low_trust",
                item_code="",
                confidence=conf,
                candidates=[Candidate(code, conf)],
            )
        )

    return LaneOutcome(
        tentative=TentativeHit(
            item_code=code,
            confidence=conf,
            reason_code="alias_exact",
            candidates=(Candidate(code, conf),),
        )
    )
