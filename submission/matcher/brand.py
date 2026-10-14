"""Catalogue-derived brand detection (exact + light fuzzy). Soft restrict only."""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

from .normalize import tokenize

# Fuzzy floor for typo brands (Vermmont→Vermont, Kato→Kanto). Train-probed ~0.78.
BRAND_FUZZY_FLOOR = 78.0


@dataclass(frozen=True)
class BrandHit:
    brand: str | None
    how: str  # "exact" | "fuzzy" | "prefix" | "none"
    leading_token: str | None


def _brand_keys(brands: set[str]) -> dict[str, str]:
    """normalized brand string → canonical catalogue brand."""
    out: dict[str, str] = {}
    for b in brands:
        key = " ".join(tokenize(b.lower()))
        if key:
            out[key] = b
    return out


def detect_brand(normalized_text: str, brands: set[str]) -> BrandHit:
    """
    Find a tenant catalogue brand in the line.

    Order: multi-word exact → unigram exact → glued prefix (HitexNitrile) → fuzzy typo.
    Miss → brand=None (caller keeps full catalogue pool — brandless path).
    """
    tokens = tokenize(normalized_text)
    leading = next((t for t in tokens if t.isalpha() and len(t) >= 2), None)
    if not brands or not tokens:
        return BrandHit(None, "none", leading)

    key_map = _brand_keys(brands)
    joined = " ".join(tokens)

    # Multi-word brands first (golden pantry, cape bay).
    for key in sorted((k for k in key_map if " " in k), key=len, reverse=True):
        if key in joined:
            return BrandHit(key_map[key], "exact", leading)

    singles = {k: v for k, v in key_map.items() if " " not in k}

    for tok in tokens:
        if tok in singles:
            return BrandHit(singles[tok], "exact", leading)

    # Glued brand+product: HitexNitrile → Hitex
    for tok in tokens[:3]:
        for key, canon in singles.items():
            if len(key) >= 4 and tok.startswith(key) and len(tok) > len(key) + 1:
                return BrandHit(canon, "prefix", leading)

    # Fuzzy typo on early alphabetic tokens vs single-word brands.
    for tok in tokens[:5]:
        if not tok.isalpha() or len(tok) < 4:
            continue
        best_key = None
        best_score = 0.0
        for key in singles:
            score = float(fuzz.ratio(tok, key))
            if score > best_score:
                best_score = score
                best_key = key
        if best_key is not None and best_score >= BRAND_FUZZY_FLOOR:
            return BrandHit(singles[best_key], "fuzzy", leading)

    return BrandHit(None, "none", leading)


def looks_brand_shaped(token: str | None) -> bool:
    """Leading token that might be a brand name (not a short code / number)."""
    if not token:
        return False
    return token.isalpha() and len(token) >= 4
