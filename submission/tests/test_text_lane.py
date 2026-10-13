"""Text lane tests (slice 2)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SUBMISSION = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[2]
if str(SUBMISSION) not in sys.path:
    sys.path.insert(0, str(SUBMISSION))

from matcher.normalize import normalize_text  # noqa: E402
from matcher.service import MatchService, OrderLine  # noqa: E402


class NormalizeTests(unittest.TestCase):
    def test_vermmont_and_class_glue(self) -> None:
        n = normalize_text("Vermmont  PVC  Pipe  20mmC  lass  E")
        self.assertIn("vermont", n)
        self.assertIn("class", n)
        self.assertIn("20mm", n)

    def test_zp_synonym(self) -> None:
        n = normalize_text("bolt M8 ZP")
        self.assertIn("zinc plated", n)


class TextLaneIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.svc = MatchService.from_data_dir(ROOT / "data")

    def test_cadbury_reject(self) -> None:
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

    def test_easy_tolsen_wall_plug(self) -> None:
        line = OrderLine(
            line_id="ACM-T-0001",
            tenant="acme",
            customer_id="CUST-004",
            order_date="2026-06-26",
            raw_text="Tolsen Wall Plug 12mm Red",
        )
        result = self.svc.match(line)
        self.assertEqual(result.decision, "auto")
        self.assertEqual(result.reason_code, "lexical_unique")
        self.assertEqual(result.item_code, "ACM-WALL0029")

    def test_stallion_flap_does_not_auto(self) -> None:
        # Underspecified twins — must not confidently auto in slice 2.
        line = OrderLine(
            line_id="ACM-T-0006",
            tenant="acme",
            customer_id="CUST-006",
            order_date="2026-05-06",
            raw_text="- Stallion Angle Grinder Disc Flap",
        )
        result = self.svc.match(line)
        self.assertNotEqual(result.decision, "auto")

    def test_same_as_last_month(self) -> None:
        line = OrderLine(
            line_id="ACM-T-0014",
            tenant="acme",
            customer_id="CUST-006",
            order_date="2026-05-14",
            raw_text="same as last month order",
        )
        result = self.svc.match(line)
        self.assertEqual(result.decision, "reject")
        self.assertEqual(result.reason_code, "not_an_item")


if __name__ == "__main__":
    unittest.main()
