"""Item-phrase shortlist tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SUBMISSION = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[2]
if str(SUBMISSION) not in sys.path:
    sys.path.insert(0, str(SUBMISSION))

from matcher.catalogue import load_default_catalogues  # noqa: E402
from matcher.normalize import normalize_text  # noqa: E402
from matcher.phrases import brand_stripped_name, item_phrase, shortlist_by_phrase  # noqa: E402
from matcher.service import MatchService, OrderLine  # noqa: E402


class PhraseUnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cat = load_default_catalogues(ROOT / "data")

    def test_brand_stripped(self) -> None:
        item = self.cat.get("acme", "ACM-WALL0029")
        assert item is not None
        tail = brand_stripped_name(item)
        self.assertNotIn("tolsen", tail)
        self.assertIn("wall plug", tail)

    def test_cable_tie_shortlist_without_brand(self) -> None:
        pool = [it for it in self.cat.items_for_tenant("acme") if it.active]
        ranked = shortlist_by_phrase(
            normalize_text("Cable Tie 450mm Black"), pool, brand=None
        )
        self.assertTrue(ranked)
        top_codes = [it.item_code for it, _ in ranked[:5]]
        self.assertTrue(any(c.startswith("ACM-CABL") for c in top_codes))


class PhraseIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.svc = MatchService.from_data_dir(ROOT / "data")

    def test_brandless_cable_tie_text_only(self) -> None:
        r = self.svc.match(
            OrderLine(
                "X",
                "acme",
                "CUST-001",
                "2026-06-01",
                raw_text="Cable Tie 450mm Black",
            )
        )
        self.assertNotEqual(r.reason_code, "brand_not_in_tenant")
        self.assertNotEqual(r.decision, "reject")

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

    def test_twins_still_abstain(self) -> None:
        r = self.svc.match(
            OrderLine(
                "ACM-T-0066",
                "acme",
                "CUST-001",
                "2026-06-01",
                raw_text="Tolsen Bolt M8x50",
            )
        )
        self.assertNotEqual(r.decision, "auto")
        self.assertEqual(r.reason_code, "ambiguous_twins")


if __name__ == "__main__":
    unittest.main()
