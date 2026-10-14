"""Catalogue-derived item phrases (group leaf + brand-stripped name)."""

from __future__ import annotations

import re

from rapidfuzz import fuzz, process

from .catalogue import CatalogueItem
from .normalize import normalize_text, tokenize


def group_leaf(item: CatalogueItem) -> str:
    leaf = (item.item_group.split(">")[-1] if item.item_group else "").strip()
    return normalize_text(leaf)


def brand_stripped_name(item: CatalogueItem) -> str:
    """item_name with leading catalogue brand removed — the portable item phrase."""
    name = normalize_text(item.item_name)
    brand = normalize_text(item.brand)
    if brand and name.startswith(brand + " "):
        return name[len(brand) + 1 :].strip()
    if brand and name.startswith(brand):
        return name[len(brand) :].strip()
    return name


def item_phrase(item: CatalogueItem) -> str:
    """
    Retrieval key for one catalogue row.
    Prefer brand-stripped name; prepend group leaf when it adds tokens not already present.
    """
    tail = brand_stripped_name(item)
    leaf = group_leaf(item)
    if leaf and leaf not in tail:
        return f"{leaf} {tail}".strip()
    return tail or leaf


def query_for_phrase(normalized_query: str, brand: str | None) -> str:
    """Drop known brand tokens from the query so we match item phrases, not brand noise."""
    q = normalized_query
    if brand:
        b = normalize_text(brand)
        if b:
            q = re.sub(rf"\b{re.escape(b)}\b", " ", q)
            q = re.sub(r"\s+", " ", q).strip()
    return q or normalized_query


def shortlist_by_phrase(
    normalized_query: str,
    pool: list[CatalogueItem],
    brand: str | None,
    *,
    limit: int = 15,
    floor: float = 0.65,
) -> list[tuple[CatalogueItem, float]]:
    """
    Rank pool by catalogue-derived phrase similarity.
    Returns (item, phrase_score) best first; empty if nothing clears the floor.
    """
    if not pool:
        return []

    q = query_for_phrase(normalized_query, brand)
    # Leaf containment boost: if a group leaf appears in the query, prefer that family
    # without requiring a hardcoded product list.
    leaf_hits: set[str] = set()
    for it in pool:
        leaf = group_leaf(it)
        if leaf and leaf in q:
            leaf_hits.add(leaf)

    narrowed = pool
    if leaf_hits:
        preferred = [it for it in pool if group_leaf(it) in leaf_hits]
        if preferred:
            narrowed = preferred

    choices = {it.item_code: item_phrase(it) for it in narrowed}
    # Map code → item for reconstruction
    by_code = {it.item_code: it for it in narrowed}

    extracted = process.extract(
        q,
        choices,
        scorer=fuzz.WRatio,
        limit=min(limit, len(choices)),
        score_cutoff=floor * 100,
    )
    out: list[tuple[CatalogueItem, float]] = []
    for _value, score, key in extracted:
        item = by_code.get(str(key))
        if item is not None:
            out.append((item, round(float(score) / 100.0, 4)))
    return out


def has_any_leaf_token(normalized_query: str, pool: list[CatalogueItem]) -> bool:
    """True if any catalogue group leaf appears in the query (foothold check)."""
    q_tokens = set(tokenize(normalized_query))
    for it in pool:
        leaf = group_leaf(it)
        if not leaf:
            continue
        leaf_toks = set(tokenize(leaf))
        if leaf_toks and leaf_toks.issubset(q_tokens):
            return True
        if leaf in normalized_query:
            return True
    return False
