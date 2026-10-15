"""Input-class segmentation for eval (Task 3).

Nine mutually exclusive primary classes, assigned by priority on the *line*
(not on matcher ``reason_code``).
"""

from __future__ import annotations

import re
from typing import Mapping

from rapidfuzz import fuzz, process

from .attrs import extract_attrs, extract_item_attrs, unspecified_attr_disagreement
from .brand import BRAND_FUZZY_FLOOR, BrandHit, detect_brand, looks_brand_shaped
from .catalogue import CatalogueIndex, CatalogueItem
from .normalize import normalize_text, tokenize
from .phrases import shortlist_by_phrase

# Priority order (first match wins).
INPUT_CLASSES = (
    "non_item",
    "id_barcode",
    "id_alias",
    "foreign_brand",
    "conversational_prefix",
    "typo_or_abbrev",
    "pack_uom_underspec",
    "brandless_clean",
    "clean_named",
)

_NON_ITEM_PHRASES = (
    "same as last",
    "same as before",
    "as per last order",
    "opening balance",
    "delivery fee",
    "delivery charge",
    "misc charge",
    "subtotal",
    "thanks",
    "deliver by",
    "kindly quote",
    "po attached",
    "confirm stock",
    "attn",
)

# Checked on raw (pre-synonym) text — abbrev / Malay / known train typos.
_TYPO_ABBREV = re.compile(
    r"(?:"
    r"\bvermmont\b"
    r"|\bzp\b"
    r"|\bs/s\b"
    r"|\bskru\b"
    r"|\bayam\b"
    r"|\bsusu\b"
    r"|\bsds\b"
    r")",
    re.I,
)

_CONVERSATIONAL = re.compile(
    r"^\s*(?:"
    r"please\b|pls\b|urgent\b|need\b|req(?:uest)?\b|item\s*:|\d+\)|-+\s*"
    r")",
    re.I,
)

_PACK_QTY = re.compile(r"\bx\s*\d+\b", re.I)
_PACK_UOM = frozenset(
    {"case", "ctn", "carton", "outer", "box", "bag", "tin", "tray", "pallet", "packet"}
)

_PHRASE_FLOOR = 0.65
_PHRASE_LIMIT = 15


def _active_pool(tenant: str, catalogue: CatalogueIndex) -> list[CatalogueItem]:
    return [
        it
        for it in catalogue.items_for_tenant(tenant)
        if it.active
        and "MISC" not in it.item_code.upper()
        and not any(
            tok in it.item_name.upper()
            for tok in ("DELIVERY FEE", "OPENING BALANCE", "MISC CHARGE", "DO NOT SELL")
        )
    ]


def _leading_appears_in_catalogue(leading: str, pool: list[CatalogueItem]) -> bool:
    """True if leading token shows up in any active item name (product word, not foreign)."""
    for it in pool:
        tokens = set(tokenize(normalize_text(it.item_name)))
        if leading in tokens:
            return True
    return False


def _leading_is_brand_typo(hit: BrandHit) -> bool:
    """Fuzzy brand hit counts as a typo only if the leading token is what matched.

    detect_brand also fuzzes later tokens, so colour words like ``white`` can hit ``Hitex``.
    """
    if hit.how != "fuzzy" or not hit.brand or not hit.leading_token:
        return False
    brand_key = " ".join(tokenize(hit.brand.lower()))
    return fuzz.ratio(hit.leading_token, brand_key) >= BRAND_FUZZY_FLOOR


def _is_typo_or_abbrev(raw: str, brand_typo: bool) -> bool:
    if brand_typo:
        return True
    if _TYPO_ABBREV.search(raw or ""):
        return True
    # Broken class token seen in train: "20mmC  lass E" (not a normal "20mm Class E").
    if re.search(r"\d+\s*mm\s*c\s+lass\b|\d+mmclass", raw or "", re.I):
        return True
    return False


def _is_pack_uom_underspec(
    raw: str,
    uom_text: str,
    norm: str,
    brand: str | None,
    pool: list[CatalogueItem],
) -> bool:
    if _PACK_QTY.search(raw or "") or _PACK_QTY.search(norm):
        return True
    uom = (uom_text or "").strip().lower()
    if uom in _PACK_UOM:
        return True
    if re.search(r"\bbulk\b", norm):
        return True

    # Twin / bulk underspec: phrase shortlist disagrees on an attr the line omitted.
    if not pool:
        return False
    ranked = shortlist_by_phrase(
        norm, pool, brand, limit=_PHRASE_LIMIT, floor=_PHRASE_FLOOR
    )
    if len(ranked) < 2:
        return False
    qattrs = extract_attrs(norm)
    item_attrs = [extract_item_attrs(it.item_name) for it, _score in ranked]
    return unspecified_attr_disagreement(qattrs, item_attrs)


def classify_input(
    row: Mapping[str, str],
    catalogue: CatalogueIndex,
) -> str:
    """Assign one of ``INPUT_CLASSES``. Does not read matcher outputs."""
    tenant = (row.get("tenant") or "").strip()
    raw = (row.get("raw_text") or "").strip()

    barcode = (row.get("raw_barcode") or "").strip()
    buyer_sku = (row.get("buyer_sku") or "").strip()
    uom_text = (row.get("uom_text") or "").strip()

    norm = normalize_text(raw)
    if not norm or any(p in norm for p in _NON_ITEM_PHRASES):
        return "non_item"

    if barcode:
        return "id_barcode"
    if buyer_sku:
        return "id_alias"

    pool = _active_pool(tenant, catalogue) if tenant else []
    brands = {it.brand for it in pool if it.brand}
    hit = detect_brand(norm, brands)
    brand_typo = _leading_is_brand_typo(hit)
    # A fuzzy hit on a non-leading token (white→Hitex) is not a real brand signal.
    brand = None if hit.how == "fuzzy" and not brand_typo else hit.brand

    if brand is None and looks_brand_shaped(hit.leading_token):
        leading = hit.leading_token or ""
        if leading and not _leading_appears_in_catalogue(leading, pool):
            # Extra guard: leading also far from every catalogue brand token.
            brand_keys = [" ".join(tokenize(b.lower())) for b in brands if b]
            if brand_keys:
                _best, score, _ = process.extractOne(
                    leading, brand_keys, scorer=fuzz.ratio
                )
                if float(score) < BRAND_FUZZY_FLOOR:
                    return "foreign_brand"
            else:
                return "foreign_brand"

    if _CONVERSATIONAL.search(raw):
        return "conversational_prefix"

    if _is_typo_or_abbrev(raw, brand_typo):
        return "typo_or_abbrev"

    if _is_pack_uom_underspec(raw, uom_text, norm, brand, pool):
        return "pack_uom_underspec"

    if brand is None:
        return "brandless_clean"

    return "clean_named"
