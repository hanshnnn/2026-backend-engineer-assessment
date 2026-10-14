"""Attribute extract + twin disagreement checks (size / finish / colour / grade / bulk)."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Pack qty like x6 / x48 is NOT a SKU discriminator in v1 (DESIGN).
_PACK_QTY = re.compile(r"\bx\s*\d+\b")

_SIZE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bm\d+x\d+\b"),
    re.compile(r"#\d+\s*x\s*\d+(?:/\d+)?(?:\s*\")?"),
    re.compile(r"\d+\s*-\s*\d+\s*mm\b"),
    re.compile(r"\d+(?:\.\d+)?\s*mm\b"),
    re.compile(r"\d+\s*-\s*\d+\s*/\s*\d+\s*\"?"),  # 1-1/4"
    re.compile(r"\d+\s*/\s*\d+\s*\"?"),  # 1/2"
    re.compile(r"\d+(?:\.\d+)?\s*\""),
    re.compile(r"\d+(?:\.\d+)?\s*kg\b"),
    re.compile(r"\b\d+\s*g\b"),
]

_FINISH_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bzinc\s+plated\b"), "zinc_plated"),
    (re.compile(r"\bhdg\b"), "hdg"),
    (re.compile(r"\bstainless\s+304\b"), "ss304"),
    (re.compile(r"\bstainless\s+316\b"), "ss316"),
    (re.compile(r"\bstainless\s+410\b"), "ss410"),
    (re.compile(r"\bpvc\b"), "pvc"),
    (re.compile(r"\bss304\b"), "ss304"),
]

_COLOURS = ("red", "blue", "white", "black", "brown", "yellow", "green", "grey", "gray")

_GRADE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bclass\s*([cde])\b"), "class"),  # special: group 1
    (re.compile(r"\bflap\b"), "flap"),
    (re.compile(r"\bgrinding\b"), "grinding"),
    (re.compile(r"\bcutting\b"), "cutting"),
    (re.compile(r"\bsoft\b"), "soft"),
    (re.compile(r"\bstandard\b"), "standard"),
]


def _norm_size(raw: str) -> str:
    s = raw.lower().strip()
    s = s.replace(" ", "").replace('"', "")
    return s


@dataclass(frozen=True)
class Attrs:
    sizes: frozenset[str]
    finish: str | None
    colour: str | None
    grade: str | None
    bulk: bool | None  # True=bulk, None=unspecified (items: False=non-bulk)


def extract_attrs(text: str) -> Attrs:
    """Extract attrs from normalized order text or item_name."""
    t = (text or "").lower()
    # Strip pack qty so x6 does not look like a size key.
    t_no_pack = _PACK_QTY.sub(" ", t)

    sizes: set[str] = set()
    for pat in _SIZE_PATTERNS:
        for m in pat.finditer(t_no_pack):
            sizes.add(_norm_size(m.group(0)))

    finish: str | None = None
    for pat, label in _FINISH_PATTERNS:
        if pat.search(t):
            finish = label
            break

    colour: str | None = None
    for c in _COLOURS:
        if re.search(rf"\b{c}\b", t):
            colour = "grey" if c == "gray" else c
            break

    grade: str | None = None
    for pat, label in _GRADE_PATTERNS:
        m = pat.search(t)
        if not m:
            continue
        if label == "class":
            grade = f"class_{m.group(1)}"
        else:
            grade = label
        break

    bulk: bool | None = None
    if re.search(r"\bbulk\b", t):
        bulk = True

    return Attrs(
        sizes=frozenset(sizes),
        finish=finish,
        colour=colour,
        grade=grade,
        bulk=bulk,
    )


def extract_item_attrs(item_name: str) -> Attrs:
    """Item names encode bulk explicitly; absence ⇒ non-bulk."""
    base = extract_attrs(item_name)
    is_bulk = bool(re.search(r"\(\s*bulk\s*\)", (item_name or "").lower())) or bool(
        re.search(r"\bbulk\b", (item_name or "").lower())
    )
    return Attrs(
        sizes=base.sizes,
        finish=base.finish,
        colour=base.colour,
        grade=base.grade,
        bulk=True if is_bulk else False,
    )


def item_matches_query(query: Attrs, item: Attrs) -> bool:
    """Hard filter: every attr the query stated must match the item."""
    if query.sizes and not query.sizes.issubset(item.sizes):
        # Allow match if any query size token equals any item size (subset strict
        # fails when item has M8x50 and query has m8x50 — both normalized same).
        # Also allow intersection for multi-token sizes.
        if not (query.sizes & item.sizes):
            return False
        # If query has multiple size tokens, require all present.
        if len(query.sizes) > 1 and not query.sizes.issubset(item.sizes):
            return False
    if query.finish is not None and item.finish != query.finish:
        return False
    if query.colour is not None and item.colour != query.colour:
        return False
    if query.grade is not None and item.grade != query.grade:
        return False
    if query.bulk is True and item.bulk is not True:
        return False
    return True


def unspecified_attr_disagreement(query: Attrs, items: list[Attrs]) -> bool:
    """
    True if ≥2 items disagree on an attr the query did not specify.
    → caller should abstain with ambiguous_twins.
    """
    if len(items) < 2:
        return False

    if query.finish is None:
        vals = {a.finish for a in items if a.finish is not None}
        if len(vals) > 1:
            return True

    if query.colour is None:
        vals = {a.colour for a in items if a.colour is not None}
        if len(vals) > 1:
            return True

    if query.grade is None:
        vals = {a.grade for a in items if a.grade is not None}
        if len(vals) > 1:
            return True

    if not query.sizes:
        vals = {a.sizes for a in items if a.sizes}
        if len(vals) > 1:
            return True

    if query.bulk is None:
        vals = {a.bulk for a in items}
        if len(vals) > 1:
            return True

    return False
