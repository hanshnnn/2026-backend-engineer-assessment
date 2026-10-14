"""Catalogue brand detection tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SUBMISSION = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[2]
if str(SUBMISSION) not in sys.path:
    sys.path.insert(0, str(SUBMISSION))

from matcher.brand import detect_brand  # noqa: E402
from matcher.normalize import normalize_text  # noqa: E402
from matcher.service import MatchService, OrderLine  # noqa: E402

ACME = {"Bosco", "Hitex", "Kanto", "Remax", "Stallion", "Tolsen", "Vermont"}


class BrandDetectTests(unittest.TestCase):
    def test_exact(self) -> None:
        h = detect_brand(normalize_text("Tolsen Wall Plug 12mm Red"), ACME)
        self.assertEqual(h.brand, "Tolsen")
        self.assertEqual(h.how, "exact")

    def test_fuzzy_typo(self) -> None:
        # Even without normalize synonym, fuzzy should catch Vermmont.
        h = detect_brand("vermmont pvc pipe 20mm class e", ACME)
        self.assertEqual(h.brand, "Vermont")
        self.assertEqual(h.how, "fuzzy")

    def test_multiword_nordic(self) -> None:
        brands = {"Cape Bay", "Golden Pantry", "Halberg", "Sisu"}
        h = detect_brand(normalize_text("Cape Bay Prawn 1kg"), brands)
        self.assertEqual(h.brand, "Cape Bay")
        self.assertEqual(h.how, "exact")

    def test_miss_brandless(self) -> None:
        h = detect_brand(normalize_text("Cable Tie 450mm Black"), ACME)
        self.assertIsNone(h.brand)
        self.assertEqual(h.how, "none")


class BrandPathIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.svc = MatchService.from_data_dir(ROOT / "data")

    def test_cadbury_still_rejects(self) -> None:
        r = self.svc.match(
            OrderLine(
                "ACM-T-0013",
                "acme",
                "CUST-003",
                "2026-08-23",
                raw_text="Cadbury Dairy Milk 165g",
            )
        )
        self.assertEqual(r.decision, "reject")
        self.assertEqual(r.reason_code, "brand_not_in_tenant")

    def test_brandless_cable_tie_can_match(self) -> None:
        # ACM-T-0023 style — no brand on line, still matchable via text.
        r = self.svc.match(
            OrderLine(
                "ACM-T-0023",
                "acme",
                "CUST-001",
                "2026-06-01",
                raw_text="Cable Tie 450mm Black",
                raw_barcode="910597372782",  # this line also has barcode in train
            )
        )
        # Barcode may auto; also try pure text brandless:
        r2 = self.svc.match(
            OrderLine(
                "X",
                "acme",
                "CUST-001",
                "2026-06-01",
                raw_text="Cable Tie 450mm Black",
            )
        )
        self.assertNotEqual(r2.reason_code, "brand_not_in_tenant")
        # Should not hard-reject brandless product lines.
        self.assertNotEqual(r2.decision, "reject")


if __name__ == "__main__":
    unittest.main()
