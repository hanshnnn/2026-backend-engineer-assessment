"""Unit tests for barcode / alias / ID arbitration (slice 0+1)."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

SUBMISSION = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[2]
if str(SUBMISSION) not in sys.path:
    sys.path.insert(0, str(SUBMISSION))

from matcher.alias_index import AliasIndex, AliasRow  # noqa: E402
from matcher.arbitrate import arbitrate_id  # noqa: E402
from matcher.catalogue import CatalogueIndex, CatalogueItem  # noqa: E402
from matcher.lanes.alias import run_alias  # noqa: E402
from matcher.lanes.barcode import run_barcode  # noqa: E402
from matcher.service import MatchService, OrderLine  # noqa: E402
from matcher.types import TentativeHit  # noqa: E402


def _item(tenant: str, code: str, barcode: str = "", active: bool = True) -> CatalogueItem:
    return CatalogueItem(
        tenant=tenant,
        item_code=code,
        item_name=code,
        brand="",
        item_group="",
        barcode=barcode,
        disabled=not active,
        active=active,
    )


class BarcodeLaneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cat = CatalogueIndex()
        self.cat.add(_item("acme", "ACM-A", barcode="111"))
        self.cat.add(_item("acme", "ACM-B", barcode="222"))
        self.cat.add(_item("acme", "ACM-C", barcode="222"))  # ambiguous
        self.cat.add(_item("acme", "ACM-OLD", barcode="333", active=False))
        self.cat.add(_item("nordic", "NRD-A", barcode="111"))

    def test_unique_barcode_tentative(self) -> None:
        out = run_barcode("acme", "111", self.cat)
        self.assertFalse(out.stopped)
        assert out.tentative is not None
        self.assertEqual(out.tentative.item_code, "ACM-A")
        self.assertEqual(out.tentative.reason_code, "barcode_hit")

    def test_ambiguous_barcode_review(self) -> None:
        out = run_barcode("acme", "222", self.cat)
        self.assertTrue(out.stopped)
        assert out.result is not None
        self.assertEqual(out.result.reason_code, "ambiguous_barcode")
        self.assertEqual(out.result.decision, "review")

    def test_tenant_isolation(self) -> None:
        # Nordic barcode 111 must not resolve on acme line.
        out = run_barcode("acme", "111", self.cat)
        assert out.tentative is not None
        self.assertEqual(out.tentative.item_code, "ACM-A")
        out_n = run_barcode("nordic", "111", self.cat)
        assert out_n.tentative is not None
        self.assertEqual(out_n.tentative.item_code, "NRD-A")

    def test_inactive_barcode_ignored(self) -> None:
        out = run_barcode("acme", "333", self.cat)
        self.assertFalse(out.stopped)
        self.assertIsNone(out.tentative)


class AliasLaneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cat = CatalogueIndex()
        self.cat.add(_item("acme", "ACM-LIVE"))
        self.cat.add(_item("acme", "ACM-OTHER"))
        self.cat.add(_item("acme", "ACM-DEAD-OLD", active=False))
        self.aliases = AliasIndex()

    def _add(self, sku: str, code: str, conf: float, valid_to: date | None = None) -> None:
        self.aliases.add(
            AliasRow(
                tenant="acme",
                customer_id="CUST-1",
                buyer_sku=sku,
                item_code=code,
                valid_from=date(2026, 1, 1),
                valid_to=valid_to,
                source="confirmed_order",
                confidence=conf,
            )
        )

    def test_trusted_unique_alias(self) -> None:
        self._add("SKU1", "ACM-LIVE", 0.72)
        out = run_alias("acme", "CUST-1", "SKU1", date(2026, 6, 1), self.aliases, self.cat)
        self.assertFalse(out.stopped)
        assert out.tentative is not None
        self.assertEqual(out.tentative.reason_code, "alias_exact")
        self.assertEqual(out.tentative.item_code, "ACM-LIVE")

    def test_low_conf_unique_still_autos(self) -> None:
        # Train: all alias@0.55 unique hits matched GT — conf floor removed (see MINDLOG).
        self._add("SKU1", "ACM-LIVE", 0.55)
        out = run_alias("acme", "CUST-1", "SKU1", date(2026, 6, 1), self.aliases, self.cat)
        self.assertFalse(out.stopped)
        assert out.tentative is not None
        self.assertEqual(out.tentative.reason_code, "alias_exact")
        self.assertEqual(out.tentative.item_code, "ACM-LIVE")
        self.assertEqual(out.tentative.confidence, 0.55)

    def test_ambiguous_alias(self) -> None:
        self._add("SKU1", "ACM-LIVE", 1.0)
        self._add("SKU1", "ACM-OTHER", 1.0)
        out = run_alias("acme", "CUST-1", "SKU1", date(2026, 6, 1), self.aliases, self.cat)
        self.assertTrue(out.stopped)
        assert out.result is not None
        self.assertEqual(out.result.reason_code, "ambiguous_alias")

    def test_old_only_no_live_sibling_falls_through(self) -> None:
        self._add("SKU1", "ACM-DEAD-OLD", 1.0)
        out = run_alias("acme", "CUST-1", "SKU1", date(2026, 6, 1), self.aliases, self.cat)
        self.assertFalse(out.stopped)
        self.assertIsNone(out.tentative)
        self.assertIsNone(out.pending_text_confirm)

    def test_old_only_emits_live_sibling_hint(self) -> None:
        self.cat.add(_item("acme", "ACM-LIVE-OLD", active=False))
        self._add("SKU1", "ACM-LIVE-OLD", 0.55)
        out = run_alias("acme", "CUST-1", "SKU1", date(2026, 6, 1), self.aliases, self.cat)
        self.assertFalse(out.stopped)
        self.assertIsNone(out.tentative)
        assert out.pending_text_confirm is not None
        self.assertEqual(out.pending_text_confirm.item_code, "ACM-LIVE")
        self.assertEqual(out.pending_text_confirm.reason_code, "alias_old_successor")
        self.assertEqual(out.pending_text_confirm.confidence, 0.55)

    def test_expired_falls_through(self) -> None:
        self._add("SKU1", "ACM-LIVE", 1.0, valid_to=date(2026, 3, 31))
        out = run_alias("acme", "CUST-1", "SKU1", date(2026, 6, 1), self.aliases, self.cat)
        self.assertFalse(out.stopped)
        self.assertIsNone(out.tentative)


class IdArbitrationTests(unittest.TestCase):
    def test_conflict(self) -> None:
        a = TentativeHit("ACM-A", 1.0, "barcode_hit")
        b = TentativeHit("ACM-B", 1.0, "alias_exact")
        result = arbitrate_id(a, b)
        assert result is not None
        self.assertEqual(result.reason_code, "id_id_conflict")
        self.assertEqual(result.decision, "review")

    def test_agree(self) -> None:
        a = TentativeHit("ACM-A", 1.0, "barcode_hit")
        b = TentativeHit("ACM-A", 0.72, "alias_exact")
        result = arbitrate_id(a, b)
        assert result is not None
        self.assertEqual(result.decision, "auto")
        self.assertEqual(result.item_code, "ACM-A")
        self.assertEqual(result.reason_code, "barcode_hit")

    def test_barcode_only(self) -> None:
        a = TentativeHit("ACM-A", 1.0, "barcode_hit")
        result = arbitrate_id(a, None)
        assert result is not None
        self.assertEqual(result.reason_code, "barcode_hit")
        self.assertEqual(result.decision, "auto")


class ServiceIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.svc = MatchService.from_data_dir(ROOT / "data")

    def test_real_barcode_auto(self) -> None:
        # ACM-T-0023 from train exploration
        line = OrderLine(
            line_id="ACM-T-0023",
            tenant="acme",
            customer_id="CUST-001",
            order_date="2026-06-01",
            raw_barcode="910597372782",
        )
        result = self.svc.match(line)
        self.assertEqual(result.decision, "auto")
        self.assertEqual(result.reason_code, "barcode_hit")
        self.assertEqual(result.item_code, "ACM-CABL0816")

    def test_ambiguous_barcode_on_train_like(self) -> None:
        # NRD-T-0009 barcode hits two actives
        line = OrderLine(
            line_id="NRD-T-0009",
            tenant="nordic",
            customer_id="CUST-001",
            order_date="2026-06-01",
            raw_barcode="973863540740",
        )
        result = self.svc.match(line)
        self.assertEqual(result.decision, "review")
        self.assertEqual(result.reason_code, "ambiguous_barcode")

    def test_cadbury_via_text_lane(self) -> None:
        line = OrderLine(
            line_id="ACM-T-0013",
            tenant="acme",
            customer_id="CUST-003",
            order_date="2026-08-23",
            raw_text="Cadbury Dairy Milk 165g",
        )
        result = self.svc.match(line)
        self.assertEqual(result.decision, "reject")
        self.assertEqual(result.reason_code, "brand_not_in_tenant")

    def test_old_alias_confirmed_by_text_candidates(self) -> None:
        # ACM-T-0011: sku → ACM-ANGL0886-OLD; text surfaces live ACM-ANGL0886.
        line = OrderLine(
            line_id="ACM-T-0011",
            tenant="acme",
            customer_id="CUST-001",
            order_date="2026-08-13",
            raw_text="need Kanto Grinder Disc Grinding",
            buyer_sku="001959523",
        )
        result = self.svc.match(line)
        self.assertEqual(result.decision, "auto")
        self.assertEqual(result.reason_code, "alias_old_successor")
        self.assertEqual(result.item_code, "ACM-ANGL0886")


if __name__ == "__main__":
    unittest.main()
