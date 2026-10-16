# SYNC.md — Task 5

Work so far is in `starter/sync/sync_adapter.py` (do not change `fake_erp.py`).  
Isolating tests: `submission/tests/test_sync_defects.py` (one test per defect below).

---

## Defects

### 1. MAIA-812 — missing rows on pull (INV1)

**Symptoms:** First `pull` already missing a record (`EXT-0050`). Local count < remote count.

**What was going wrong:**  
ERP `list_changes` only returns rows with `updated_at > since` (strict `>`), and many rows share the same second. After each page we set `cursor = page[-1].updated_at`. The **last row on the page is kept**, but other rows with that **same** timestamp that sort *after* the page cut never come back on the next page. They only show up later if someone edits them (new timestamp) — that matches the ticket.

**Fix:** On a full page, do not park the cursor on the last row’s timestamp if that bucket is incomplete. Set cursor to the last row with an *earlier* timestamp so the next page re-reads the tied rows. Short final page → then park on the last timestamp.

**Invariant this restores:** After a full pull, every remote record should exist locally at the remote version.

---



### 2. MAIA-830 — one edit, two ERP writes (INV2)

**Symptoms:** `EXT-0042` appeared twice in the write log with the same `price=999`.

**What was going wrong (sequence):**

1. `write` can **commit**, then raise **504** (`ErpTimeout`).
2. Our idempotency key included `attempt` and `time.time()`, so the retry used a **different** key.
3. ERP idempotency only matches the **exact** key string → treated as a new write.
4. Retry still had old `base_version` → **409** → old conflict code wrote again → second version.

**Fix:**

- Idempotency key = hash of `(external_id, payload)` only — same edit, same key on every retry.
- On 409, if remote payload is **already the same** as what we are pushing → just adopt that version (our write already landed). Do not write again.

**Invariant this restores:** One local dirty edit should create at most one new ERP version.

---



### 3. MAIA-844 — ERP edit overwritten (INV3)

**Symptoms:** ERP set `EXT-0011` to `uom=Box`; after our push it was gone (`uom=Nos` again).

**What 409 means (as I understand it):**  
We push with `base_version` = the version we last knew. If remote already moved to a **higher** version, ERP returns **409** (conflict). Happy-path local push (versions still match) does **not** hit 409 — so this fix does not change normal “just push my edit” when nobody else touched the row.

**What was going wrong:**

```text
pull       local/remote v1  {price:21, uom:Nos}
UI edit    local dirty      {price:999, uom:Nos}  still base_version=1
ERP edit   remote becomes   v2 {price:55.5, uom:Box}
push       write(base=1) → 409
old code   force-write our local at v2 → wipes Box
```

**Fix:** On 409, if remote payload is **different** → do **not** force-write. Copy remote into local and clear dirty (keep the ERP edit). Tradeoff I accept for now: our unpushed local edit on that row is dropped; better than silently destroying the remote one. I have not built a real merge / conflict UI.

**Invariant this restores:** A remote edit that happened after our base version must not be silently lost.

---



## Latent defects (no ticket yet — not fixed)

These are still in the code. `run_sync` / the three tickets did not force them to show. I have not fixed them; listing what I understand and when they would surface.

### L-A — dirty local can be wiped on pull

UI edit sets `dirty` but does **not** bump `updated_at_utc`. Pull only keeps dirty local if `local.updated_at_utc > remote.updated_at`. That check usually fails (stale local clock; field is also server `+08`, not real UTC).

**Surfaces when:** local is dirty, that row comes back in a pull (e.g. ERP also changed it) → pull overwrites local with remote and clears dirty. INV3 was fixed on the **push/409** path; this is the pull-side version of “local edit lost.”

### L-B — idempotency key forgotten after 60s

ERP only remembers an idempotency key for 60 seconds (exact string). After that it is **forgotten**. A later retry with the same key string is treated as a **new** write, not a replay.

**Surfaces when:** process dies after a commit (or is slow to retry) and comes back after the window. We then rely on version/409 handling instead of idempotency. My INV2 fix (stable key + adopt if payload already matches) helps inside the window; this is about depending on short vendor memory.

### L-C — whole page shares one second

My INV1 fix needs an *earlier* timestamp on the page to park the cursor. If a **full** page is all the same second, there is no earlier stamp → cursor still moves to that second → next page is `> that second` → other rows still at that second are skipped (same family as MAIA-812, rarer shape).

**Surfaces when:** bulk write / import puts more than `page_size` rows in the same second.

---



## Vendor contract (what I would ask)

I have not negotiated a real ERP API; this is what I would ask for, tied to bugs I hit, and what I do if they say no.

1. **Cursor that includes id (or an opaque token)** — not only `updated_at` at second resolution — so same-second ties cannot skip rows (INV1 / L-C).
  *If no:* keep draining incomplete timestamp buckets (my INV1 fix).
2. **Idempotency that survives 504-after-commit** — stable client key, remembered longer than 60s (INV2 / L-B).
  *If no:* stable key + always retry the same key; on 409 if payload already matches → adopt, don’t write again.
3. **Timestamps with timezone / UTC clearly marked** — so we don’t compare misleading local strings (L-A).
  *If no:* don’t use those strings for dirty LWW; trust version / 409 instead.

These are about **correct sync under more load** (fewer skips, fewer duplicate writes, fewer lost edits) — not a promise that processes won’t crash.

---



## Scale (500 tenants / 5 min)

I have not run this at 500 tenants. Based on the defects above:

**Falls over first:** sync lasting too long / retry pile-up — more pages when timestamps tie, more **504** retries under load

---



## How I check

```bash
cd starter/sync && python run_sync.py
python -m unittest submission.tests.test_sync_defects -v
```

Expect: symptom reporter green; three defect tests pass.