#!/usr/bin/env python3
"""Two-way sync between our local item store and the ERP in fake_erp.py.

This code is in production. It mostly works. Ops have raised three tickets:

  MAIA-812  "some items never appear on our side until someone edits them"
  MAIA-830  "price history shows two updates a second apart, we only made one"
  MAIA-844  "an edit made in the ERP was overwritten by our older value"

Task 5 is about this file. Read the tickets as symptoms, not diagnoses.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field

from fake_erp import ErpConflict, ErpTimeout, FakeErp


@dataclass
class LocalRecord:
    external_id: str
    payload: dict
    remote_version: int
    updated_at_utc: str          # "YYYY-MM-DD HH:MM:SS", UTC
    dirty: bool = False


@dataclass
class LocalStore:
    """Stands in for our Postgres tables. Committed writes only."""
    records: dict = field(default_factory=dict)
    cursor: str | None = None
    applied_log: list = field(default_factory=list)

    def upsert(self, rec: LocalRecord) -> None:
        self.records[rec.external_id] = rec
        self.applied_log.append((rec.external_id, rec.remote_version))

    def set_cursor(self, cursor: str) -> None:
        self.cursor = cursor


def now_utc() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())


def idempotency_key(external_id: str, payload: dict) -> str:
    # Stable per logical edit so a 504-after-commit retry reuses the ERP cache
    # instead of creating a second write.
    blob = json.dumps({"id": external_id, "payload": payload}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


def pull(erp: FakeErp, store: LocalStore, page_size: int = 50) -> int:
    """Pull remote changes since the stored cursor into the local store."""
    pulled = 0
    while True:
        page = erp.list_changes(since=store.cursor, limit=page_size)
        if not page:
            break
        for rec in page:
            local = store.records.get(rec.external_id)
            if local and local.dirty and local.updated_at_utc > rec.updated_at:
                # our unsent local edit is newer - keep it, drop the remote one
                continue
            store.upsert(LocalRecord(
                external_id=rec.external_id,
                payload=dict(rec.payload),
                remote_version=rec.version,
                updated_at_utc=rec.updated_at,
                dirty=False,
            ))
            pulled += 1
        # ERP filters updated_at > since at second resolution; ties are common.
        # Never park the cursor on a timestamp we have not fully drained, or
        # siblings after the page boundary are skipped forever.
        if len(page) < page_size:
            store.set_cursor(page[-1].updated_at)
            break
        last_ts = page[-1].updated_at
        earlier = [r for r in page if r.updated_at < last_ts]
        if earlier:
            store.set_cursor(earlier[-1].updated_at)
        else:
            store.set_cursor(last_ts)
    return pulled


def push(erp: FakeErp, store: LocalStore, max_attempts: int = 3) -> int:
    """Push locally-dirty records to the ERP."""
    pushed = 0
    for rec in list(store.records.values()):
        if not rec.dirty:
            continue
        key = idempotency_key(rec.external_id, rec.payload)
        for _attempt in range(max_attempts):
            try:
                remote = erp.write(rec.external_id, rec.payload,
                                   base_version=rec.remote_version,
                                   idempotency_key=key)
            except ErpTimeout:
                continue                      # may already be committed - retry same key
            except ErpConflict:
                current = erp.get(rec.external_id)
                if current and current.payload == rec.payload:
                    # Our write landed (e.g. 504 after commit); don't write again.
                    remote = current
                else:
                    # Concurrent remote edit — do not clobber it.
                    remote = current
                    rec.payload = dict(remote.payload)
            rec.remote_version = remote.version
            rec.updated_at_utc = remote.updated_at
            rec.dirty = False
            store.upsert(rec)
            pushed += 1
            break
    return pushed


def sync(erp: FakeErp, store: LocalStore) -> dict:
    return {"pulled": pull(erp, store), "pushed": push(erp, store)}
