"""Tenant-scoped catalogue indexes."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


def is_active_item(item_code: str, disabled: str | int | bool) -> bool:
    """Active = not disabled and not a superseded *-OLD code."""
    if str(disabled).strip() in {"1", "true", "True"}:
        return False
    if item_code.endswith("-OLD"):
        return False
    return True


@dataclass(frozen=True)
class CatalogueItem:
    tenant: str
    item_code: str
    item_name: str
    brand: str
    item_group: str
    barcode: str
    disabled: bool
    active: bool


class CatalogueIndex:
    """In-memory per-tenant catalogue + barcode lookup."""

    def __init__(self) -> None:
        self._by_code: dict[tuple[str, str], CatalogueItem] = {}
        # (tenant, barcode) -> active item codes (stable order)
        self._by_barcode: dict[tuple[str, str], list[str]] = {}

    def add(self, item: CatalogueItem) -> None:
        self._by_code[(item.tenant, item.item_code)] = item
        if item.active and item.barcode:
            key = (item.tenant, item.barcode)
            bucket = self._by_barcode.setdefault(key, [])
            if item.item_code not in bucket:
                bucket.append(item.item_code)

    def get(self, tenant: str, item_code: str) -> CatalogueItem | None:
        return self._by_code.get((tenant, item_code))

    def is_active(self, tenant: str, item_code: str) -> bool:
        item = self.get(tenant, item_code)
        if item is None:
            # Unknown code: treat as inactive so alias cannot auto it.
            return False
        return item.active

    def lookup_barcode(self, tenant: str, barcode: str) -> list[str]:
        if not barcode:
            return []
        return list(self._by_barcode.get((tenant, barcode), []))

    def items_for_tenant(self, tenant: str) -> Iterable[CatalogueItem]:
        for (t, _), item in self._by_code.items():
            if t == tenant:
                yield item


def load_catalogue(path: Path, tenant: str, index: CatalogueIndex | None = None) -> CatalogueIndex:
    index = index or CatalogueIndex()
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            code = (row.get("item_code") or "").strip()
            if not code:
                continue
            disabled_raw = (row.get("disabled") or "0").strip()
            active = is_active_item(code, disabled_raw)
            item = CatalogueItem(
                tenant=tenant,
                item_code=code,
                item_name=(row.get("item_name") or "").strip(),
                brand=(row.get("brand") or "").strip(),
                item_group=(row.get("item_group") or "").strip(),
                barcode=(row.get("barcode") or "").strip(),
                disabled=disabled_raw in {"1", "true", "True"},
                active=active,
            )
            index.add(item)
    return index


def load_default_catalogues(data_dir: Path) -> CatalogueIndex:
    index = CatalogueIndex()
    load_catalogue(data_dir / "catalogue_acme.csv", "acme", index)
    load_catalogue(data_dir / "catalogue_nordic.csv", "nordic", index)
    return index
