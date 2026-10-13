"""ID arbitration + soft text oppose."""

from __future__ import annotations

from typing import Optional

from .lanes.text import TextRetrieval, strong_unique_text_code
from .types import Candidate, MatchResult, TentativeHit


def soft_text_oppose(tentative: TentativeHit, retrieval: TextRetrieval | None) -> Optional[str]:
    """
    If text has a unique strong candidate ≠ ID → oppose.
    Weak / refused / agreeing text → no oppose (ID may auto).
    """
    if retrieval is None:
        return None
    code = strong_unique_text_code(retrieval)
    if code is None:
        return None
    if code == tentative.item_code:
        return None
    return code


def arbitrate_id(
    barcode: Optional[TentativeHit],
    alias: Optional[TentativeHit],
    text_retrieval: TextRetrieval | None = None,
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
        hit = TentativeHit(
            item_code=barcode.item_code,
            confidence=max(barcode.confidence, alias.confidence),
            reason_code="barcode_hit",
            candidates=barcode.candidates or alias.candidates,
        )
        return _finalize_id_auto(hit, text_retrieval)

    single = barcode or alias
    if single is None:
        return None
    return _finalize_id_auto(single, text_retrieval)


def _finalize_id_auto(hit: TentativeHit, text_retrieval: TextRetrieval | None) -> MatchResult:
    opposed = soft_text_oppose(hit, text_retrieval)
    if opposed is not None:
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
        candidates=list(hit.candidates)
        if hit.candidates
        else [Candidate(hit.item_code, hit.confidence)],
    )
