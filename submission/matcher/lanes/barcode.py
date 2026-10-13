"""Barcode lane — exact tenant catalogue lookup on active rows only."""

from __future__ import annotations

from ..catalogue import CatalogueIndex
from ..types import Candidate, LaneOutcome, MatchResult, TentativeHit


def run_barcode(tenant: str, raw_barcode: str, catalogue: CatalogueIndex) -> LaneOutcome:
    barcode = (raw_barcode or "").strip()
    if not barcode:
        return LaneOutcome()

    hits = catalogue.lookup_barcode(tenant, barcode)
    if not hits:
        return LaneOutcome()

    cands = tuple(Candidate(code, 1.0) for code in hits[:3])
    if len(hits) >= 2:
        return LaneOutcome(
            result=MatchResult(
                decision="review",
                reason_code="ambiguous_barcode",
                confidence=0.0,
                candidates=list(cands),
            )
        )

    code = hits[0]
    return LaneOutcome(
        tentative=TentativeHit(
            item_code=code,
            confidence=1.0,
            reason_code="barcode_hit",
            candidates=(Candidate(code, 1.0),),
        )
    )
