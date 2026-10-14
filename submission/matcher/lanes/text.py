"""Lexical text lane: brand (soft) → family → attr filter → twin check → RapidFuzz."""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz, process

from ..attrs import (
    Attrs,
    extract_attrs,
    extract_item_attrs,
    item_matches_query,
    unspecified_attr_disagreement,
)
from ..brand import BrandHit, detect_brand, looks_brand_shaped
from ..catalogue import CatalogueIndex, CatalogueItem
from ..normalize import normalize_text
from ..types import Candidate, MatchResult

AUTO_FLOOR = 0.90
MARGIN = 0.03
REVIEW_FLOOR = 0.72
SOFT_OPPOSE_FLOOR = 0.90
FUZZ_LIMIT = 8
# Below this, a brand-shaped leading token that matched no tenant brand → foreign refuse.
FOREIGN_ITEM_WEAK = 0.72

_NON_ITEM_PHRASES = (
    "same as last",
    "same as before",
    "as per last order",
    "opening balance",
    "delivery fee",
    "misc charge",
)


@dataclass
class TextRetrieval:
    normalized: str
    brand: str | None
    pool_size: int
    candidates: list[Candidate]
    refuse_reason: str | None = None
    query_attrs: Attrs | None = None
    brand_how: str = "none"


def _is_misc(item: CatalogueItem) -> bool:
    code = item.item_code.upper()
    name = item.item_name.upper()
    if "MISC" in code:
        return True
    if any(tok in name for tok in ("DELIVERY FEE", "OPENING BALANCE", "MISC CHARGE", "DO NOT SELL")):
        return True
    return False


def _family_narrow(text: str, items: list[CatalogueItem]) -> list[CatalogueItem]:
    by_leaf: dict[str, list[CatalogueItem]] = {}
    for it in items:
        leaf = (it.item_group.split(">")[-1] if it.item_group else "").strip().lower()
        if leaf:
            by_leaf.setdefault(leaf, []).append(it)
    leaves = sorted(by_leaf.keys(), key=len, reverse=True)
    for leaf in leaves:
        if leaf and leaf in text:
            return by_leaf[leaf]
    return items


def _score_candidates(norm: str, pool: list[CatalogueItem]) -> list[Candidate]:
    if not pool:
        return []
    choices = {it.item_code: normalize_text(it.item_name) for it in pool}
    extracted = process.extract(
        norm,
        choices,
        scorer=fuzz.WRatio,
        limit=min(FUZZ_LIMIT, len(choices)),
        score_cutoff=REVIEW_FLOOR * 100,
    )
    return [
        Candidate(item_code=str(key), score=round(float(score) / 100.0, 4))
        for _value, score, key in extracted
    ]


def _maybe_foreign_refuse(
    hit: BrandHit,
    cands: list[Candidate],
) -> str | None:
    """
    No hardcoded foreign list: brand-shaped leading token, matched no tenant brand,
    and item retrieval is weak → brand_not_in_tenant.
    """
    if hit.brand is not None:
        return None
    if not looks_brand_shaped(hit.leading_token):
        return None
    top = cands[0].score if cands else 0.0
    if top < FOREIGN_ITEM_WEAK:
        return "brand_not_in_tenant"
    return None


def retrieve_text(tenant: str, raw_text: str, catalogue: CatalogueIndex) -> TextRetrieval:
    norm = normalize_text(raw_text)
    if not norm:
        return TextRetrieval("", None, 0, [], refuse_reason="not_an_item")

    for phrase in _NON_ITEM_PHRASES:
        if phrase in norm:
            return TextRetrieval(norm, None, 0, [], refuse_reason="not_an_item")

    brands = {it.brand for it in catalogue.items_for_tenant(tenant) if it.brand}
    hit = detect_brand(norm, brands)
    qattrs = extract_attrs(norm)

    pool = [
        it
        for it in catalogue.items_for_tenant(tenant)
        if it.active and not _is_misc(it)
    ]
    # Soft restrict: brand hit narrows pool; miss keeps full active catalogue.
    if hit.brand:
        branded = [it for it in pool if it.brand == hit.brand]
        if branded:
            pool = branded

    pool = _family_narrow(norm, pool)

    item_attrs_map = {it.item_code: extract_item_attrs(it.item_name) for it in pool}
    filtered = [it for it in pool if item_matches_query(qattrs, item_attrs_map[it.item_code])]
    if not filtered:
        # Still allow foreign refuse when pool empty after attrs (e.g. Cadbury).
        foreign = _maybe_foreign_refuse(hit, [])
        return TextRetrieval(
            norm,
            hit.brand,
            0,
            [],
            refuse_reason=foreign or "no_candidate_above_floor",
            query_attrs=qattrs,
            brand_how=hit.how,
        )

    pool = filtered
    pool_attrs = [item_attrs_map[it.item_code] for it in pool]

    if unspecified_attr_disagreement(qattrs, pool_attrs):
        cands = _score_candidates(norm, pool)
        foreign = _maybe_foreign_refuse(hit, cands)
        if foreign:
            return TextRetrieval(
                norm,
                hit.brand,
                len(pool),
                cands,
                refuse_reason=foreign,
                query_attrs=qattrs,
                brand_how=hit.how,
            )
        return TextRetrieval(
            norm,
            hit.brand,
            len(pool),
            cands,
            refuse_reason="ambiguous_twins",
            query_attrs=qattrs,
            brand_how=hit.how,
        )

    cands = _score_candidates(norm, pool)
    foreign = _maybe_foreign_refuse(hit, cands)
    if foreign:
        return TextRetrieval(
            norm,
            hit.brand,
            len(pool),
            cands,
            refuse_reason=foreign,
            query_attrs=qattrs,
            brand_how=hit.how,
        )

    return TextRetrieval(
        norm,
        hit.brand,
        len(pool),
        cands,
        query_attrs=qattrs,
        brand_how=hit.how,
    )


def decide_text(retrieval: TextRetrieval) -> MatchResult:
    if retrieval.refuse_reason:
        decision = (
            "reject"
            if retrieval.refuse_reason in {"not_an_item", "brand_not_in_tenant"}
            else "review"
        )
        return MatchResult(
            decision=decision,  # type: ignore[arg-type]
            reason_code=retrieval.refuse_reason,
            confidence=retrieval.candidates[0].score if retrieval.candidates else 0.0,
            candidates=retrieval.candidates[:3],
        )

    cands = retrieval.candidates
    if not cands:
        return MatchResult(
            decision="review",
            reason_code="no_candidate_above_floor",
            confidence=0.0,
        )

    top = cands[0]
    second = cands[1].score if len(cands) > 1 else 0.0
    margin = top.score - second

    if top.score >= AUTO_FLOOR and margin >= MARGIN:
        return MatchResult(
            decision="auto",
            reason_code="lexical_unique",
            item_code=top.item_code,
            confidence=top.score,
            candidates=cands[:3],
        )

    if top.score >= REVIEW_FLOOR and margin < MARGIN:
        return MatchResult(
            decision="review",
            reason_code="ambiguous_margin",
            confidence=top.score,
            candidates=cands[:3],
        )

    return MatchResult(
        decision="review",
        reason_code="no_candidate_above_floor",
        confidence=top.score if top.score >= REVIEW_FLOOR else 0.0,
        candidates=cands[:3],
    )


def strong_unique_text_code(retrieval: TextRetrieval) -> str | None:
    if retrieval.refuse_reason:
        return None
    cands = retrieval.candidates
    if not cands:
        return None
    top = cands[0]
    second = cands[1].score if len(cands) > 1 else 0.0
    if top.score >= SOFT_OPPOSE_FLOOR and (top.score - second) >= MARGIN:
        return top.item_code
    return None
