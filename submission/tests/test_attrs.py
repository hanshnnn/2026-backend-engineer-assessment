"""Attribute extract + twin policy tests (slice 3)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SUBMISSION = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[2]
if str(SUBMISSION) not in sys.path:
    sys.path.insert(0, str(SUBMISSION))

from matcher.attrs import (  # noqa: E402
    extract_attrs,
    extract_item_attrs,
    unspecified_attr_disagreement,
)
from matcher.normalize import normalize_text  # noqa: E402
from matcher.service import MatchService, OrderLine  # noqa: E402


class AttrExtractTests(unittest.TestCase):
    def test_size_and_finish(self) -> None:
        a = extract_attrs(normalize_text("Tolsen Hex Bolt M8x50 HDG"))
        self.assertIn("m8x50", a.sizes)
        self.assertEqual(a.finish, "hdg")
        self.assertIsNone(a.bulk)

    def test_bulk_on_item(self) -> None:
        a = extract_item_attrs('Tolsen Hex Bolt M8x50 HDG (Bulk)')
        self.assertTrue(a.bulk)
        self.assertEqual(a.finish, "hdg")

    def test_pack_qty_ignored(self) -> None:
        a = extract_attrs(normalize_text('Kanto Screw #8 x 3/4" Zinc Plated x6'))
        self.assertNotIn("x6", "".join(a.sizes))

    def test_bulk_twin_disagreement(self) -> None:
        q = extract_attrs("halberg chicken breast strips 5kg")
        items = [
            extract_item_attrs("Halberg Chicken Breast Strips 5kg"),
            extract_item_attrs("Halberg Chicken Breast Strips 5kg (Bulk)"),
        ]
        self.assertTrue(unspecified_attr_disagreement(q, items))


class TwinFpRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.svc = MatchService.from_data_dir(ROOT / "data")

    def _match(self, line_id: str, tenant: str, customer: str, date: str, text: str):
        return self.svc.match(
            OrderLine(line_id, tenant, customer, date, raw_text=text)
        )

    def test_underspec_finish_no_auto(self) -> None:
        r = self._match("ACM-T-0066", "acme", "CUST-001", "2026-06-01", "Tolsen Bolt M8x50")
        self.assertNotEqual(r.decision, "auto")
        self.assertEqual(r.reason_code, "ambiguous_twins")

    def test_hdg_bulk_twin_no_auto(self) -> None:
        r = self._match(
            "ACM-T-0134", "acme", "CUST-001", "2026-06-01", "Tolsen Hex Bolt M8x50 HDG"
        )
        self.assertNotEqual(r.decision, "auto")
        self.assertEqual(r.reason_code, "ambiguous_twins")

    def test_nordic_bulk_twin_no_auto(self) -> None:
        r = self._match(
            "NRD-T-0052", "nordic", "CUST-001", "2026-06-01", "Halberg Breast Strips 5kg"
        )
        self.assertNotEqual(r.decision, "auto")
        self.assertEqual(r.reason_code, "ambiguous_twins")

    def test_stallion_flap_twins(self) -> None:
        r = self._match(
            "ACM-T-0006",
            "acme",
            "CUST-006",
            "2026-05-06",
            "- Stallion Angle Grinder Disc Flap",
        )
        self.assertNotEqual(r.decision, "auto")
        self.assertEqual(r.reason_code, "ambiguous_twins")

    def test_coloured_plug_still_autos(self) -> None:
        r = self._match(
            "ACM-T-0001", "acme", "CUST-004", "2026-06-26", "Tolsen Wall Plug 12mm Red"
        )
        self.assertEqual(r.decision, "auto")
        self.assertEqual(r.item_code, "ACM-WALL0029")


if __name__ == "__main__":
    unittest.main()
