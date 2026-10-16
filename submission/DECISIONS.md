# Decision log

One entry per choice that could reasonably have gone another way.

## D-01 — Alias auto on uniqueness + in-date active check (no confidence floor)

**Context:** `customer_sku_map.csv` mixes `confirmed_order`, `inferred_match`, and `manual_import` rows. Confidence sits in `{0.55, 0.72, 1.0}`. Some windows are expired; some buyer SKUs point at more than one item.

**Options:**
(a) require `source == confirmed_order` and `conf >= 0.72`
(b) require `conf >= 0.72` regardless of source
(c) require only in-date + active catalogue item + unique target code (`ALIAS_AUTO_FLOOR = 0.0`)

**Chose:** (b) in the first design, then (c) after looking at train.

**Why:** On `order_lines_train.csv` (n=420), all 9 unique active aliases at confidence `0.55` matched `gt_item_code` (`ACM-T-0008, 0035, 0063, 0076, 0158, 0185`; `NRD-T-0035, 0103, 0157`). Gating at `0.72` only bought 9 abstentions and caught 0 false positives.

**Reversal:** Any false positive from an alias record → raise `ALIAS_AUTO_FLOOR` higher depending on the alias accuracy.

## D-02 — Ambiguous active alias stops as `review` (`ambiguous_alias`)

**Context:** Some buyer SKUs map to ≥2 distinct active catalogue items on the order date (e.g. `acme/CUST-002/002469423` before expiry). Train barely exercises this path — most multi-target rows are already expired or leave one active — but the map can still look like that on a live date.

**Options:**
(a) pick highest-confidence row
(b) fall through and let text decide silently
(c) hard stop with `decision=review`, `reason_code=ambiguous_alias`, and put the top codes in `candidates`

**Chose:** (c).

**Why:** Two mappings with the same confidence, or real buyer SKU reuse, are not something I want to guess. Wrong auto is −800. Stopping keeps both codes visible for the human and for recall@3. This is more defensive policy than train evidence — I’d rather fail open to review than silent-pick.

**Reversal:** Unsure.

## D-03 — Superseded alias (`*-OLD`) strips suffix only when text candidates confirm

**Context:** Catalogue has `*-OLD` / `disabled=1` items. Many buyer aliases still point at `FOO-OLD` while active record exists.

**Options:**
(a) hard review on any inactive alias
(b) ignore alias and fall through to text only
(c) blindly strip `-OLD` and auto active 
(d) strip `-OLD` to unique active and auto (`alias_old_successor`) only if `active` in text retrieval candidates

**Chose:** (d) (upgraded from (b)).

**Why:** On train, 29 `abstain_miss` lines with `buyer_sku` were `*-OLD` fallthroughs where text alone abstained on twins/margins. Option (d) recovered 35 `alias_old_successor` autos with 0 false positives, and still blocks blind auto when the line text is a different product.

**Reversal:** Unless alias will be totally different from OLD to active catalogue

## D-04 — Required-attribute & twin abstention (`ambiguous_twins`); ignore `xN` pack multipliers

**Context:** Catalogues have active twins that differ only by dimension (`M8x40` vs `M8x50`), thickness, grit, class (`A`/`B`/`C`), finish (`ZP`/`HDG`/`SS304`), colour, or `(Bulk)` vs retail. Order lines also have `x24 ctn` / `x48` outer quantity tokens.

**Options:**
(a) take top RapidFuzz score
(b) enforce extracted attribute compatibility on the shortlist; return `review` / `ambiguous_twins` when remaining candidates still vary on an omitted attribute or collapse to identical base names
(c) treat `xN` in order text as a catalogue pack SKU selector

**Chose:** (b), and ignore `xN` for SKU identity except explicit `(Bulk)` / bulk tokens.

**Why:** On train, `ambiguous_twins` caught 73 underspecified lines (e.g. `ACM-T-0006` "Stallion Flap Disc" with no size/grit; Nordic bulk vs retail twins) that would otherwise auto at ≥ 0.85 lexical similarity and cost −800 each.

**Reversal:** If structured UOM + `unit_price` vs `list_price` cleanly separates retail vs bulk without hurting recall, add a price-ratio tie-breaker in v2.

## D-05 — Catalogue-derived brand soft-filter instead of hardcoded brand denylist

**Context:** Lines like `ACM-T-0013` ("Cadbury Dairy Milk 165g" on Acme) must reject as `brand_not_in_tenant`. Generic lines with no brand ("Cable Tie 4.8x300mm Black") must still match.

**Options:**
(a) hardcoded foreign-brand denylist + product-noun allowlist
(b) derive brand vocabulary per tenant from `catalogue_<tenant>.csv` (exact multi-word/unigram, glued prefix like `HitexNitrile`, fuzzy typo ≥ 78); soft-restrict when matched, keep the full pool when brandless, and reject as `brand_not_in_tenant` only when a leading brand-shaped token misses the tenant’s brands and top item score < 0.72

**Chose:** (b).

**Why:** Dropping the hardcoded lists raised train `auto_correct` from 176 → 182, cut over-aggressive `brand_not_in_tenant` rejects from 63 → 46, and works on unseen tenants without editing a denylist.

**Reversal:** If a new tenant’s catalogue leaves `brand` blank on most items.

## D-06 — Item-phrase shortlist (`leaf + brand-stripped name`) before attribute filtering

**Context:** Running attribute extraction and twin checks across a whole brand pool (~150 items) mixed unrelated product families with similar numbers and weakened twin detection.

**Options:**
(a) keyword family bucketing, then attrs on the whole family
(b) build a phrase key per item (`item_group` leaf + brand-stripped `item_name`), shortlist top 15 with phrase score ≥ 0.65 (prefer items whose catalogue leaf appears in the query), then run attribute/twin filters only on that shortlist

**Chose:** (b).

**Why:** On train (n=420), the phrase shortlist before attrs lifted `auto_correct` from 182 → 189 at the same `auto_wrong` (18), cut false `ambiguous_twins` abstentions from 127 → 88, and improved net value by +420.

**Reversal:** If heavy Malay/abbreviation lines miss the `0.65` phrase floor before synonym expansion, expand synonyms before phrase scoring (already shared via `normalize_text`).

## D-07 — Keep exact-name `lexical_unique` autos despite 17 blank-GT train lines

**Context:** After all filters, train has 18 `auto_wrong` lines. 17 of those 18 have blank `gt_item_code`, but `raw_text` is an exact unique match (`score = 1.0`) to one active catalogue `item_name` (e.g. `PVCP`, `ANGL`, `SELF`, `NITR`, `BALL`), with no `buyer_sku` or `raw_barcode`.

**Options:**
(a) abstain on all no-ID exact lexical matches in those product families
(b) add a UOM or `unit_price` veto
(c) keep `lexical_unique` auto (`AUTO_FLOOR = 0.90`, `MARGIN = 0.03`) and treat the 17 as label noise in `EVAL.md`

**Chose:** (c).

**Why:** Of 68 no-ID exact-name train matches, 51 were correct autos and 17 were blank-GT. Same feature shape either way: vague UOMs (`unit`/`ea`/`pcs`) on both sides; where `unit_price` exists on the 17, 10/10 sit within $15 of catalogue `list_price`. No clean rule splits the 17 from the 51 without overfitting.

**Reversal:** If ops gives the real reason those lines were unfulfillable (credit hold, restricted group, min order pack), encode that rule explicitly.

## D-08 — Skip local embeddings / dense retrieval in v1

**Context:** §5.2 allows `sentence-transformers` if it earns its place in net value over the lexical baseline.

**Options:**
(a) add MiniLM embedding lane over `item_name`
(b) lexical normalization + synonym table + catalogue brand/phrase shortlist + attribute/twin gates only

**Chose:** (b).

**Why:** Catalogues are small (524 and 1,148 items). Remaining train misses are mostly twin underspecification (`ambiguous_twins = 73`), foreign brands (~45), and low-similarity noise (~40). Dense similarity makes twin collisions worse (`M8x40` vs `M8x50`), and one wrong auto is −800. Lexical path runs ~20–25 ms/line with no model load.

**Reversal:** If a new tenant has >20k items with long free-text descriptions and synonym tables leave too much recall on the table, add an offline-indexed embedding lane before the attribute/twin gate — never bypassing it.

## D-09 — Cold-start tenant discovery via `catalogue_<tenant>.csv`

**Context:** A brand-new tenant has a catalogue CSV and zero rows in `customer_sku_map.csv`.

**Options:**
(a) hardcode `tenant in {"acme", "nordic"}`
(b) auto-discover every `catalogue_<tenant>.csv` in `data_dir`; reject only when `not catalogue.has_tenant(tenant)`; empty alias lookups fall through to text

**Chose:** (b).

**Why:** Synthetic `catalogue_newco.csv` + empty `AliasIndex()`: barcode still autos (`barcode_hit`), unknown `buyer_sku` falls through and resolves via text (`lexical_unique`), unknown tenants without a catalogue reject as `unknown_tenant`.

**Reversal:** In production multi-tenant (Task 6), replace file globbing with a tenant catalogue registry / DB partition lookup.