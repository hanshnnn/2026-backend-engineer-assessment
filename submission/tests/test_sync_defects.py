"""One isolating test per Task 5 sync defect (MAIA-812 / 830 / 844).

Each test sets up only that failure mode and asserts only that invariant.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SYNC = Path(__file__).resolve().parents[2] / "starter" / "sync"
if str(SYNC) not in sys.path:
    sys.path.insert(0, str(SYNC))

from fake_erp import FakeErp  # noqa: E402
from sync_adapter import LocalStore, pull, push  # noqa: E402


class SyncDefectTests(unittest.TestCase):
    def test_inv1_pull_keeps_same_second_siblings(self) -> None:
        """MAIA-812: page boundary inside a tied timestamp must not drop siblings."""
        erp = FakeErp(seed=11, timeout_rate=0.0)
        erp.seed_records(60)
        store = LocalStore()

        pull(erp, store)

        missing = [eid for eid in erp.records if eid not in store.records]
        self.assertEqual(
            missing,
            [],
            f"pull skipped same-second siblings after page cut: {missing}",
        )

    def test_inv2_timeout_does_not_double_write(self) -> None:
        """MAIA-830: 504-after-commit retry must not create a second ERP version."""
        erp = FakeErp(seed=0, timeout_rate=1.0)  # every fresh write 504s after commit
        erp.seed_records(5)
        store = LocalStore()
        pull(erp, store)

        rec = store.records["EXT-0001"]
        rec.payload = dict(rec.payload, price=999.0)
        rec.dirty = True
        log_before = len(erp.write_log)

        push(erp, store)

        priced = [
            (eid, ver, payload)
            for eid, ver, payload in erp.write_log[log_before:]
            if eid == "EXT-0001" and payload.get("price") == 999.0
        ]
        self.assertEqual(
            len(priced),
            1,
            f"one local edit produced {len(priced)} remote writes: {priced}",
        )
        self.assertFalse(store.records["EXT-0001"].dirty)

    def test_inv3_conflict_does_not_clobber_remote(self) -> None:
        """MAIA-844: 409 with a different remote payload must not force-write local."""
        erp = FakeErp(seed=0, timeout_rate=0.0)  # no timeouts — isolate conflict only
        erp.seed_records(5)
        store = LocalStore()
        pull(erp, store)

        rec = store.records["EXT-0001"]
        rec.payload = dict(rec.payload, price=999.0)
        rec.dirty = True

        erp.tick(60)
        erp.write(
            "EXT-0001",
            {"name": "item 1", "price": 55.5, "uom": "Box"},
            base_version=1,
        )

        push(erp, store)

        self.assertEqual(
            erp.records["EXT-0001"].payload.get("uom"),
            "Box",
            f"remote concurrent edit was clobbered: {erp.records['EXT-0001'].payload}",
        )


if __name__ == "__main__":
    unittest.main()
