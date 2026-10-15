# Decision log

One entry per choice that could reasonably have gone another way.

## D-01 — Alias auto on uniqueness + in-date active check (no confidence floor)
**Context:** `customer_sku_map.csv` mixes `confirmed_order`, `inferred_match`, and `manual_import` rows with confidence in `{0.55, 0.72, 1.0}`, expired windows, and duplicate buyer SKUs pointing to different items.
**Options:** (a) require `source == confirmed_order` and `conf >= 0.72`, (b) require `conf >= 0.72` regardless of source, (c) require only in-date + active catalogue item + unique target code (`ALIAS_AUTO_FLOOR = 0.0`).
**Chose:** (b) initially in design, then revised to (c) after train evaluation.
**Evidence:** On `order_lines_train.csv` ($n=420$), all 9 unique active aliases at confidence `0.55` matched `gt_item_code` (`ACM-T-0008, 0035, 0063, 0076, 0158, 0185`; `NRD-T-0035, 0103, 0157`). Gating at `0.72` cost 9 abstentions ($9 \times -60 = -540$ net value vs correct auto) and prevented 0 false positives.
**Reversal trigger:** Any false positive from an `inferred_match` alias on holdout or production audit → raise `ALIAS_AUTO_FLOOR` back to `0.72` (re-enabling `alias_low_trust`).

## D-02 — Ambiguous active alias stops immediately as `review` (`ambiguous_alias`)
**Context:** Some buyer SKUs map to $\ge 2$ distinct active catalogue items on the order date (e.g. `acme/CUST-002/002469423` before expiry).
**Options:** (a) pick highest-confidence row, (b) fall through and let text decide silently, (c) hard stop with `decision=review`, `reason_code=ambiguous_alias`, and emit top codes in `candidates`.
**Chose:** (c).
**Evidence:** Picking argmax risks a $-800$ wrong shipment when two mappings share confidence or represent genuine buyer SKU reuse; stopping surfaces both codes in `candidates` for recall@3.
**Reversal trigger:** If text disambiguates polluted multi-target SKUs at $>98\%$ precision in shadow mode, allow text tie-break when one alias target also has a unique lexical match $\ge 0.90$.

## D-03 — Superseded alias (`*-OLD`) strips suffix only when text candidates confirm
**Context:** Catalogue contains `*-OLD` / `disabled=1` items; many buyer aliases still point at `FOO-OLD` while active `FOO` exists.
**Options:** (a) hard review on any inactive alias, (b) ignore alias and fall through to text only, (c) blindly strip `-OLD` and auto active `FOO`, (d) strip `-OLD` to unique active `FOO` and auto (`alias_old_successor`) only if `FOO` appears in text retrieval candidates.
**Chose:** (d) (upgraded from (b)).
**Evidence:** On train, 29 `abstain_miss` lines with `buyer_sku` were `*-OLD` fallthroughs where text alone abstained on twins/margins. Option (d) recovered **35** `alias_old_successor` autos on train with **0 false positives**, while preventing blind auto when line text describes a completely different item.
**Reversal trigger:** If a tenant reuses base codes for incompatible replacements (where `FOO` is not the true successor of `FOO-OLD`), require explicit successor metadata or fall back to (b).

## D-04 — ID arbitration + soft text oppose (`id_id_conflict` / `id_text_conflict`)
**Context:** A line can carry both `raw_barcode` and `buyer_sku`, or carry an ID while `raw_text` clearly names a different product.
**Options:** (a) ID always wins without checking text, (b) barcode vs alias mismatch → `id_id_conflict`, and single ID tentative is vetoed (`id_text_conflict`) only when text has a strong unique match (`SOFT_OPPOSE_FLOOR = 0.90`, `MARGIN = 0.03`) to a different code, (c) require text agreement on every ID hit.
**Chose:** (b).
**Evidence:** Requiring text agreement on every ID hit (c) breaks noisy/abbreviated lines where barcode or alias is the only reliable signal; never checking (a) fails when a buyer pastes a stale SKU on a different line description. Soft oppose runs on the already-computed text retrieval with negligible latency cost.
**Reversal trigger:** If `id_text_conflict` causes false abstentions on valid rebrands/renames, raise `SOFT_OPPOSE_FLOOR` above `0.95`.

## D-05 — Required-attribute & twin abstention (`ambiguous_twins`); ignore `xN` pack multipliers
**Context:** Catalogues contain active twins differing only by dimension (`M8x40` vs `M8x50`), thickness, grit, class (`A`/`B`/`C`), finish (`ZP`/`HDG`/`SS304`), colour, or `(Bulk)` vs retail pack. Order lines also contain `x24 ctn` / `x48` outer quantity tokens.
**Options:** (a) take top RapidFuzz score, (b) enforce extracted attribute compatibility on shortlist and return `review` / `ambiguous_twins` whenever remaining candidates still vary on an omitted attribute or collapse to identical base names, (c) treat `xN` in order text as catalogue pack SKU selector.
**Chose:** (b), and explicitly ignore `xN` for SKU identity except explicit `(Bulk)` / bulk tokens.
**Evidence:** On train, `ambiguous_twins` caught **73** underspecified lines (e.g. `ACM-T-0006` "Stallion Flap Disc" with no size/grit, Nordic bulk vs retail twins) that would otherwise auto at $\ge 0.85$ lexical similarity and incur $-800$ each.
**Reversal trigger:** If structured UOM + `unit_price` vs `list_price` ratio cleanly separates retail vs bulk twins without hurting recall, add a price-ratio tie-breaker in v2.

## D-06 — Catalogue-derived brand soft-filter instead of hardcoded brand denylist
**Context:** Lines like `ACM-T-0013` ("Cadbury Dairy Milk 165g" on Acme) must be rejected (`brand_not_in_tenant`), while generic lines without a brand ("Cable Tie 4.8x300mm Black") must still match.
**Options:** (a) hardcoded foreign-brand denylist + product-noun allowlist, (b) derive brand vocabulary per tenant from `catalogue_<tenant>.csv` (exact multi-word/unigram, glued prefix like `HitexNitrile`, fuzzy typo $\ge 78$); soft-restrict when matched, keep full pool when brandless, and reject as `brand_not_in_tenant` only when a leading brand-shaped token misses the tenant's brands and top item score $< 0.72$.
**Chose:** (b).
**Evidence:** Replacing the hardcoded lists with catalogue-derived brand matching increased train `auto_correct` from 176 → 182, cut over-aggressive `brand_not_in_tenant` rejects from 63 → 46, and works automatically on unseen tenants (`cold-start safe`).
**Reversal trigger:** If a new tenant's catalogue leaves `brand` blank on most items, mine leading capitalised tokens from `item_name` only when frequency $\ge 3$.

## D-07 — Item-phrase shortlist (`leaf + brand-stripped name`) before attribute filtering
**Context:** Running attribute extraction and twin checks across an entire brand pool (~150 items) caused unrelated product families with similar numbers to collide or dilute twin detection.
**Options:** (a) keyword family bucketing → attrs on whole family, (b) build a phrase key per item (`item_group` leaf + brand-stripped `item_name`), shortlist top 15 items with phrase score $\ge 0.65` (preferring items whose catalogue leaf appears in the query), then run attribute/twin filters only on that shortlist.
**Chose:** (b).
**Evidence:** On train ($n=420$), adding the phrase shortlist before attrs lifted `auto_correct` from 182 → 189 at the same `auto_wrong` (18), reduced false `ambiguous_twins` abstentions from 127 → 88, and improved net value by $+420$.
**Reversal trigger:** If heavy Malay/abbreviation lines miss the `0.65` phrase floor before synonym expansion, expand synonyms prior to phrase scoring (already shared via `normalize_text`).

## D-08 — Keep exact-name `lexical_unique` autos despite 17 blank-GT train lines
**Context:** After all filters, train has 18 `auto_wrong` lines; **17 of 18** have blank `gt_item_code` yet their `raw_text` is an exact, unique match (`score = 1.0`) to a single active catalogue `item_name` (e.g. `PVCP`, `ANGL`, `SELF`, `NITR`, `BALL`), with no `buyer_sku` or `raw_barcode`.
**Options:** (a) abstain on all no-ID exact lexical matches in those product families, (b) add a UOM or `unit_price` veto, (c) keep `lexical_unique` auto (`AUTO_FLOOR = 0.90`, `MARGIN = 0.03`) and document the 17 as an inseparable label-noise floor in `EVAL.md`.
**Chose:** (c).
**Evidence:** Auditing all 68 no-ID exact-name train matches showed **51 correct autos and 17 blank-GT lines** with identical feature distributions: vague UOMs (`unit`/`ea`/`pcs`) appear on both, and where `unit_price` is present on the 17 blank-GT lines, **10/10** sit within $15\%$ of catalogue `list_price`. No non-overfit rule separates the 17 from the 51.
**Reversal trigger:** If production/ops provides the upstream rule that made those lines unfulfillable (e.g. customer credit hold, restricted item group, or minimum order pack), encode that explicit business rule.

## D-09 — Skip local embeddings / dense retrieval in v1
**Context:** §5.2 allows `sentence-transformers` if it earns its place in net value over the lexical baseline.
**Options:** (a) add MiniLM embedding lane over `item_name`, (b) lexical normalization + synonym table + catalogue brand/phrase shortlist + attribute/twin gates only.
**Chose:** (b).
**Evidence:** Active catalogues are small (524 and 1,148 items). Train error analysis shows remaining misses are dominated by twin underspecification (`ambiguous_twins = 73`), foreign brands (`45`), and low-similarity noise (`40`) — dense similarity increases twin collisions (higher cosine similarity between `M8x40` and `M8x50`) where a single false auto costs $-800$. Lexical pipeline runs in ~20–25 ms/line without model load overhead.
**Reversal trigger:** If a new tenant has $>20\text{k}$ items with verbose free-text descriptions where synonym tables leave $>10\%$ recall on the table, add an offline-indexed embedding lane strictly **before** the attribute/twin gate (never bypassing it).

## D-10 — Cold-start tenant discovery via `catalogue_<tenant>.csv`
**Context:** A brand-new tenant has a catalogue CSV and zero rows in `customer_sku_map.csv`.
**Options:** (a) hardcode `tenant in {"acme", "nordic"}`, (b) auto-discover every `catalogue_<tenant>.csv` in `data_dir`, reject only when `not catalogue.has_tenant(tenant)`, and let empty alias lookups continue cleanly to text.
**Chose:** (b).
**Evidence:** Tested with a synthetic `catalogue_newco.csv` and empty `AliasIndex()`: barcode hits auto (`barcode_hit`), unknown `buyer_sku` falls through without stopping and resolves via text (`lexical_unique`), and unknown tenants without a catalogue reject as `unknown_tenant`.
**Reversal trigger:** In production multi-tenant deployment (Task 6), replace file globbing with tenant catalogue registry / DB partition lookup.
