"""Lexical text lane: brand/family → attr filter → twin check → RapidFuzz → decide."""

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
from ..catalogue import CatalogueIndex, CatalogueItem
from ..normalize import normalize_text, tokenize
from ..types import Candidate, MatchResult

# Retuned with attrs (slice 3). Still train-only; may sweep again in EVAL.
AUTO_FLOOR = 0.90
MARGIN = 0.03
REVIEW_FLOOR = 0.72
SOFT_OPPOSE_FLOOR = 0.90
FUZZ_LIMIT = 8

_FOREIGN_BRAND_TOKENS = {
    "cadbury",
    "nestle",
    "nestlé",
    "coca",
    "pepsi",
    "heineken",
}

_NON_ITEM_PHRASES = (
    "same as last",
    "same as before",
    "as per last order",
    "opening balance",
    "delivery fee",
    "misc charge",
)

_PRODUCT_START = {
    "cable",
    "hose",
    "pvc",
    "gi",
    "ball",
    "hex",
    "self",
    "angle",
    "wall",
    "nitrile",
    "masking",
    "safety",
    "grinding",
    "flap",
    "screw",
    "bolt",
    "valve",
    "pipe",
    "wire",
    "plug",
    "clip",
    "glove",
    "helmet",
    "tape",
    "tie",
    "chicken",
    "salmon",
    "beef",
    "prawn",
    "potato",
    "milk",
    "butter",
    "puff",
    "squid",
    "mozzarella",
    "vanilla",
    "whipping",
    "fries",
    "patty",
}


@dataclass
class TextRetrieval:
    normalized: str
    brand: str | None
    pool_size: int
    candidates: list[Candidate]
    refuse_reason: str | None = None
    query_attrs: Attrs | None = None


def _is_misc(item: CatalogueItem) -> bool:
    code = item.item_code.upper()
    name = item.item_name.upper()
    if "MISC" in code:
        return True
    if any(tok in name for tok in ("DELIVERY FEE", "OPENING BALANCE", "MISC CHARGE", "DO NOT SELL")):
        return True
    return False


def _brand_aliases(brands: set[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for b in brands:
        key = normalize_text(b)
        if key:
            out[key] = b
    typos = {"vermmont": "vermont"}
    lower_map = {normalize_text(b): b for b in brands}
    for typo, canon_norm in typos.items():
        if canon_norm in lower_map:
            out[typo] = lower_map[canon_norm]
    return out


def _detect_brand(tokens: list[str], brand_map: dict[str, str]) -> str | None:
    if not tokens:
        return None
    multi = sorted((k for k in brand_map if " " in k), key=len, reverse=True)
    joined = " ".join(tokens)
    for key in multi:
        if key in joined:
            return brand_map[key]
    for tok in tokens:
        if tok in brand_map:
            return brand_map[tok]
    return None


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


def retrieve_text(tenant: str, raw_text: str, catalogue: CatalogueIndex) -> TextRetrieval:
    norm = normalize_text(raw_text)
    if not norm:
        return TextRetrieval("", None, 0, [], refuse_reason="not_an_item")

    for phrase in _NON_ITEM_PHRASES:
        if phrase in norm:
            return TextRetrieval(norm, None, 0, [], refuse_reason="not_an_item")

    tokens = tokenize(norm)
    brands = {it.brand for it in catalogue.items_for_tenant(tenant) if it.brand}
    brand_map = _brand_aliases(brands)
    brand = _detect_brand(tokens, brand_map)
    qattrs = extract_attrs(norm)

    if brand is None and tokens:
        first = tokens[0]
        if first in _FOREIGN_BRAND_TOKENS:
            return TextRetrieval(norm, None, 0, [], refuse_reason="brand_not_in_tenant", query_attrs=qattrs)
        if (
            first.isalpha()
            and len(first) >= 4
            and first not in _PRODUCT_START
            and first not in brand_map
        ):
            return TextRetrieval(norm, None, 0, [], refuse_reason="brand_not_in_tenant", query_attrs=qattrs)

    pool = [
        it
        for it in catalogue.items_for_tenant(tenant)
        if it.active and not _is_misc(it)
    ]
    if brand:
        branded = [it for it in pool if it.brand == brand]
        if branded:
            pool = branded

    pool = _family_narrow(norm, pool)

    # Attrs from raw item_name (keeps "(Bulk)" which normalize would strip).
    item_attrs_map = {it.item_code: extract_item_attrs(it.item_name) for it in pool}

    filtered = [it for it in pool if item_matches_query(qattrs, item_attrs_map[it.item_code])]
    if not filtered:
        return TextRetrieval(
            norm,
            brand,
            0,
            [],
            refuse_reason="no_candidate_above_floor",
            query_attrs=qattrs,
        )

    pool = filtered
    pool_attrs = [item_attrs_map[it.item_code] for it in pool]

    # Required-attr / bulk twin abstain before trusting fuzz uniqueness.
    if unspecified_attr_disagreement(qattrs, pool_attrs):
        cands = _score_candidates(norm, pool)
        return TextRetrieval(
            norm,
            brand,
            len(pool),
            cands,
            refuse_reason="ambiguous_twins",
            query_attrs=qattrs,
        )

    cands = _score_candidates(norm, pool)
    return TextRetrieval(norm, brand, len(pool), cands, query_attrs=qattrs)


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
    """Soft oppose only when text would itself auto (no twin refuse)."""
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
