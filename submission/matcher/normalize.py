"""Text normalization + small synonym table (v1)."""

from __future__ import annotations

import re

# Applied after lowercasing / slash→space. Order matters for multi-word targets.
_SYNONYMS: list[tuple[str, str]] = [
    (r"\bvermmont\b", "vermont"),
    (r"\bzp\b", "zinc plated"),
    (r"\bs/s\b", "stainless"),
    (r"\bss304\b", "stainless 304"),
    (r"\bss316\b", "stainless 316"),
    (r"\bss410\b", "stainless 410"),
    (r"\bskru\b", "screw"),
    (r"\bayam\b", "chicken"),
    (r"\bsusu\b", "milk"),
]

_NOISE_PREFIX = re.compile(
    r"^(?:item\s*:|-+\s*|please\s+send\s+|need\s+|req(?:uest)?\s*:?\s*)+",
    re.I,
)
_NON_ALNUM = re.compile(r"[^a-z0-9.#%\-\s\"]+")
_SPACE = re.compile(r"\s+")


def normalize_text(raw: str) -> str:
    text = (raw or "").strip().lower()
    if not text:
        return ""
    text = text.replace("/", " ").replace("\\", " ")
    text = _NOISE_PREFIX.sub("", text)
    text = text.replace("''", '"').replace("″", '"').replace("'", '"')
    text = _NON_ALNUM.sub(" ", text)
    for pattern, repl in _SYNONYMS:
        text = re.sub(pattern, repl, text)
    # Fix glued class tokens seen in train: "20mmc lass e" / "20mmclass e"
    text = re.sub(r"(\d+)\s*mm\s*c\s*lass\s*", r"\1mm class ", text)
    text = re.sub(r"(\d+)mmclass\s*", r"\1mm class ", text)
    text = _SPACE.sub(" ", text).strip()
    return text


def tokenize(normalized: str) -> list[str]:
    if not normalized:
        return []
    return [t for t in normalized.split() if t]
