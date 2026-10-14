"""Buyer-SKU alias lane — dirty memory with uniqueness gate."""

from __future__ import annotations

from datetime import date

from ..alias_index import AliasIndex, AliasRow
from ..catalogue import CatalogueIndex
from ..types import Candidate, LaneOutcome, MatchResult, TentativeHit

# Unique in-date active alias → auto regardless of confidence band (0.55 / 0.72 / 1.0).
# Floor kept as a knob for reversal; 0.0 = no conf gate (train evidence 2026-10-14).
ALIAS_AUTO_FLOOR = 0.0


def _collapse_best(rows: list[AliasRow]) -> dict[str, float]:
    best: dict[str, float] = {}
    for row in rows:
        prev = best.get(row.item_code)
        if prev is None or row.confidence > prev:
            best[row.item_code] = row.confidence
    return best


def _old_successor_hint(
    tenant: str,
    rows: list[AliasRow],
    catalogue: CatalogueIndex,
) -> TentativeHit | None:
    """
    Unique *-OLD map → strip suffix to one active live code.

    Caller must confirm that code appears in text candidates before auto.
    """
    best: dict[str, float] = {}
    for row in rows:
        code = row.item_code
        if not code.endswith("-OLD"):
            continue
        live = code[: -len("-OLD")]
        if not catalogue.is_active(tenant, live):
            continue
        prev = best.get(live)
        if prev is None or row.confidence > prev:
            best[live] = row.confidence
    if len(best) != 1:
        return None
    code, conf = next(iter(best.items()))
    return TentativeHit(
        item_code=code,
        confidence=conf,
        reason_code="alias_old_successor",
        candidates=(Candidate(code, conf),),
    )


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
        # Empty / expired / only superseded → optional OLD→live soft hint.
        inactive = aliases.lookup_in_force(tenant, customer_id, sku, order_date)
        hint = _old_successor_hint(tenant, inactive, catalogue) if inactive else None
        return LaneOutcome(pending_text_confirm=hint)

    best = _collapse_best(rows)
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
