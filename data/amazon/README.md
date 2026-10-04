# Amazon extraction (generated – do not edit by hand)

Regenerate with `python3 scripts/extract_amazon.py`.

- `lines/YYYY-MM.json` – every row of the Amazon Monthly Unified Transaction CSVs (288,065 rows, none dropped or de-duplicated). Each row carries `src` (CSV file) and `line` (line number in that file) so it can be traced back to the original.
- `summary.json` – month → day totals (orders, units, product sales, shipping credits, fees, refunds, payouts to bank, net).
- `checks.json` – integrity checks (row counts per file, component columns = total, identical rows kept).

Notes: dates are Amazon's Pacific time as printed; "units" = quantity on `Order` rows; refunds carry no quantity, so they are shown in dollars; `payouts` = Amazon "Transfer" rows (money sent to bank, with last digits in `acct`).
