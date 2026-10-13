"""ID arbitration + soft text oppose (stub in slice 0+1)."""

from __future__ import annotations

from typing import Optional

from .types import Candidate, MatchResult, TentativeHit


def soft_text_oppose(tentative: TentativeHit) -> Optional[str]:
    """
    Slice 0+1 stub: always treat text as weak → never oppose.

    Later: return opposing item_code if text has a unique strong candidate ≠ ID.
    """
    return None


def arbitrate_id(
    barcode: Optional[TentativeHit],
    alias: Optional[TentativeHit],
) -> Optional[MatchResult]:
    """
    Resolve barcode/alias tentatives.

    Returns a MatchResult when an ID decision is ready, else None → text lane.
    """
    if barcode and alias:
        if barcode.item_code != alias.item_code:
            cands = [
                Candidate(barcode.item_code, barcode.confidence),
                Candidate(alias.item_code, alias.confidence),
            ]
            return MatchResult(
                decision="review",
                reason_code="id_id_conflict",
                confidence=0.0,
                candidates=cands,
            )
        # Same code from both — prefer barcode reason, keep alias conf if lower? Use max.
        hit = TentativeHit(
            item_code=barcode.item_code,
            confidence=max(barcode.confidence, alias.confidence),
            reason_code="barcode_hit",
            candidates=barcode.candidates or alias.candidates,
        )
        return _finalize_id_auto(hit)

    single = barcode or alias
    if single is None:
        return None
    return _finalize_id_auto(single)


def _finalize_id_auto(hit: TentativeHit) -> MatchResult:
    opposed = soft_text_oppose(hit)
    if opposed is not None and opposed != hit.item_code:
        return MatchResult(
            decision="review",
            reason_code="id_text_conflict",
            confidence=0.0,
            candidates=[
                Candidate(hit.item_code, hit.confidence),
                Candidate(opposed, 1.0),
            ],
        )
    return MatchResult(
        decision="auto",
        reason_code=hit.reason_code,
        item_code=hit.item_code,
        confidence=hit.confidence,
        candidates=list(hit.candidates) if hit.candidates else [Candidate(hit.item_code, hit.confidence)],
    )
