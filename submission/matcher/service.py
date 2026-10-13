"""Public matcher API for one order line."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Mapping

from .alias_index import AliasIndex, load_alias_index
from .arbitrate import arbitrate_id
from .catalogue import CatalogueIndex, load_default_catalogues
from .lanes.alias import run_alias
from .lanes.barcode import run_barcode
from .lanes.text import decide_text, retrieve_text
from .types import MatchResult


def _parse_order_date(value: str) -> date:
    value = (value or "").strip()
    if not value:
        return date(2099, 1, 1)
    return datetime.strptime(value, "%Y-%m-%d").date()


@dataclass
class OrderLine:
    line_id: str
    tenant: str
    customer_id: str
    order_date: str
    raw_text: str = ""
    buyer_sku: str = ""
    raw_barcode: str = ""

    @classmethod
    def from_mapping(cls, row: Mapping[str, str]) -> "OrderLine":
        return cls(
            line_id=(row.get("line_id") or "").strip(),
            tenant=(row.get("tenant") or "").strip(),
            customer_id=(row.get("customer_id") or "").strip(),
            order_date=(row.get("order_date") or "").strip(),
            raw_text=(row.get("raw_text") or "").strip(),
            buyer_sku=(row.get("buyer_sku") or "").strip(),
            raw_barcode=(row.get("raw_barcode") or "").strip(),
        )


class MatchService:
    """
    Tenant-scoped matcher.

    Slice 2: barcode → alias → (text retrieve for soft oppose) → ID arb → text decide.
    Attr / twin filters still deferred to slice 3.
    """

    def __init__(self, catalogue: CatalogueIndex, aliases: AliasIndex) -> None:
        self.catalogue = catalogue
        self.aliases = aliases

    @classmethod
    def from_data_dir(cls, data_dir: Path | str) -> "MatchService":
        data_dir = Path(data_dir)
        catalogue = load_default_catalogues(data_dir)
        aliases = load_alias_index(data_dir / "customer_sku_map.csv")
        return cls(catalogue, aliases)

    def match(self, line: OrderLine | Mapping[str, str]) -> MatchResult:
        if not isinstance(line, OrderLine):
            line = OrderLine.from_mapping(line)

        tenant = line.tenant
        if tenant not in {"acme", "nordic"}:
            return MatchResult(
                decision="reject",
                reason_code="unknown_tenant",
                confidence=0.0,
            )

        # (1) barcode
        bc = run_barcode(tenant, line.raw_barcode, self.catalogue)
        if bc.stopped:
            return bc.result  # type: ignore[return-value]

        # (2) alias
        order_date = _parse_order_date(line.order_date)
        al = run_alias(
            tenant,
            line.customer_id,
            line.buyer_sku,
            order_date,
            self.aliases,
            self.catalogue,
        )
        if al.stopped:
            return al.result  # type: ignore[return-value]

        # Text retrieve once: soft oppose for ID, or full decide if no ID.
        retrieval = retrieve_text(tenant, line.raw_text, self.catalogue)

        # (3) ID arbitration (+ soft text oppose)
        if bc.tentative or al.tentative:
            id_result = arbitrate_id(bc.tentative, al.tentative, retrieval)
            if id_result is not None:
                return id_result

        # (4) text lane
        return decide_text(retrieval)
