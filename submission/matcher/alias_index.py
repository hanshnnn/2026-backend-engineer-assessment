"""Buyer-SKU alias index with date + active filters."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from .catalogue import CatalogueIndex


def _parse_date(value: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


@dataclass(frozen=True)
class AliasRow:
    tenant: str
    customer_id: str
    buyer_sku: str
    item_code: str
    valid_from: date | None
    valid_to: date | None
    source: str
    confidence: float

    def in_force(self, order_date: date) -> bool:
        if self.valid_from is not None and order_date < self.valid_from:
            return False
        if self.valid_to is not None and order_date > self.valid_to:
            return False
        return True


class AliasIndex:
    def __init__(self) -> None:
        self._rows: dict[tuple[str, str, str], list[AliasRow]] = {}

    def add(self, row: AliasRow) -> None:
        key = (row.tenant, row.customer_id, row.buyer_sku)
        self._rows.setdefault(key, []).append(row)

    def lookup_in_force(
        self,
        tenant: str,
        customer_id: str,
        buyer_sku: str,
        order_date: date,
    ) -> list[AliasRow]:
        """Return in-date alias rows (active or not)."""
        if not buyer_sku:
            return []
        raw = self._rows.get((tenant, customer_id, buyer_sku), [])
        return [row for row in raw if row.in_force(order_date)]

    def lookup(
        self,
        tenant: str,
        customer_id: str,
        buyer_sku: str,
        order_date: date,
        catalogue: CatalogueIndex,
    ) -> list[AliasRow]:
        """Return in-date alias rows that point at active catalogue items."""
        out: list[AliasRow] = []
        for row in self.lookup_in_force(tenant, customer_id, buyer_sku, order_date):
            if not catalogue.is_active(tenant, row.item_code):
                continue
            out.append(row)
        return out


def load_alias_index(path: Path) -> AliasIndex:
    index = AliasIndex()
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            sku = (row.get("customer_sku") or "").strip()
            code = (row.get("item_code") or "").strip()
            if not sku or not code:
                continue
            conf_raw = (row.get("confidence") or "0").strip() or "0"
            index.add(
                AliasRow(
                    tenant=(row.get("tenant") or "").strip(),
                    customer_id=(row.get("customer_id") or "").strip(),
                    buyer_sku=sku,
                    item_code=code,
                    valid_from=_parse_date(row.get("valid_from") or ""),
                    valid_to=_parse_date(row.get("valid_to") or ""),
                    source=(row.get("source") or "").strip(),
                    confidence=float(conf_raw),
                )
            )
    return index
