# Product matching (generated – do not edit by hand)

Regenerate: `python3 scripts/extract_invoices.py && python3 scripts/match_products.py`

**Method** (scripts/normalize.py, scripts/match_products.py)
1. Every Amazon title and supplier invoice description is normalised: size in oz (ml converted), set vs single, gender, product type (fragrance / deodorant / body), concentration, and the remaining name tokens (typos and plurals merged, edit distance 1).
2. Supplier descriptions of the same product are grouped (same size, same set flag, compatible gender, no differing variant word such as *intense*/*pure*/*dark*).
3. Each Amazon title is matched to the best supplier product. Tiers: **high** (same name + size), **probable** (near size, abbreviation/spelling difference, or size not printed on one side), **review** (weak evidence – *not counted as matched*), or none.
4. A second pass compares leftovers by character similarity (abbreviations such as BLK/black, KRYSTAL/crystal) and accepts only clear winners.

**Files**: `products.json` (one record per product: aliases, units, amounts), `summary.json`, `detail/NNN.json` (source rows per product: Amazon CSV file + line, invoice PDF + page).

**Known limits**: matching is automatic and name-based (Amazon has no barcodes); pack multipliers in titles ("Pack of 2") are not applied to units; products listed on Amazon under a different brand name than the supplier uses may stay unmatched or in review. Items the owner confirms or rejects should be recorded as overrides in a future `overrides.json`.
