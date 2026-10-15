"""Input-class segmentation (eval harness)."""

from __future__ import annotations

import unittest
from pathlib import Path

from matcher.catalogue import load_default_catalogues
from matcher.input_class import classify_input

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


class TestInputClass(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cat = load_default_catalogues(DATA)

    def _cls(self, **fields: str) -> str:
        row = {
            "tenant": "acme",
            "raw_text": "",
            "buyer_sku": "",
            "raw_barcode": "",
            "uom_text": "",
            "gt_item_code": "ACM-X",
            **fields,
        }
        return classify_input(row, self.cat)

    def test_non_item(self) -> None:
        self.assertEqual(self._cls(raw_text="same as last month order"), "non_item")

    def test_id_barcode_beats_text(self) -> None:
        self.assertEqual(
            self._cls(raw_text="whatever", raw_barcode="1234567890123"),
            "id_barcode",
        )

    def test_id_alias(self) -> None:
        self.assertEqual(
            self._cls(raw_text="Tolsen Wall Plug", buyer_sku="CUST-SKU-1"),
            "id_alias",
        )

    def test_foreign_brand(self) -> None:
        self.assertEqual(
            self._cls(raw_text="Cadbury Dairy Milk 165g"),
            "foreign_brand",
        )

    def test_conversational_prefix(self) -> None:
        self.assertEqual(
            self._cls(raw_text="please send Tolsen Wall Plug 12mm Red"),
            "conversational_prefix",
        )

    def test_typo_abbrev(self) -> None:
        self.assertEqual(
            self._cls(raw_text="Vermmont PVC Pipe 20mm Class E"),
            "typo_or_abbrev",
        )

    def test_brandless_vs_clean(self) -> None:
        # Cable Tie lines are brandless product words, not foreign brands.
        self.assertEqual(
            self._cls(raw_text="Cable Tie 450mm Black"),
            "brandless_clean",
        )
        self.assertEqual(
            self._cls(raw_text="Tolsen Wall Plug 12mm Red"),
            "clean_named",
        )

    def test_chat_crumbs_are_non_item(self) -> None:
        for text in ("subtotal", "thanks bro", "pls confirm stock first", "PO attached"):
            self.assertEqual(self._cls(raw_text=text), "non_item", text)

    def test_normal_class_token_is_not_typo(self) -> None:
        self.assertEqual(self._cls(raw_text="Hitex PVC Pipe 25mm Class C"), "clean_named")

    def test_colour_fuzzy_brand_is_not_typo(self) -> None:
        # "white" fuzzes to Hitex inside detect_brand; that is not a brand typo.
        self.assertNotEqual(self._cls(raw_text="Cable White"), "typo_or_abbrev")

    def test_leading_brand_typo(self) -> None:
        self.assertEqual(self._cls(raw_text="Hitexx Wall Plugg 8mm Red"), "typo_or_abbrev")

    def test_pls_prefix(self) -> None:
        self.assertEqual(
            self._cls(raw_text="pls send Kanto Masking Tape 24mm General"),
            "conversational_prefix",
        )

if __name__ == "__main__":
    unittest.main()
