# Nasima Perfume – Amazon sales & supplier purchases report

Static report (`index.html` + `data/`) built from the source documents in this repository.

## Folders
| Folder | Contents |
|---|---|
| `Nasima report Amazon/` | Amazon Monthly Unified Transaction CSVs (orders, refunds, fees, payouts) |
| `Amazon Payment Received/` | Bank statements and a payment cheque (PDF) – not yet reconciled in the report |
| `All Invoice/` | SCENTCITY INC invoices; sub-folders `BS Fragrance`, `Dewan`, `Perfume Center`, `Others` |
| `data/` | Generated JSON read by the page (never edit by hand) |
| `scripts/` | Extraction and matching code |

## Adding more invoices
1. Put the files in the matching supplier folder (new supplier → new sub-folder of `All Invoice/`).
2. Text PDFs are read directly. **Scanned/paper invoices** need OCR (`tesseract` is installable in the build environment); each scanned invoice is checked by comparing the sum of its lines to its printed total, and anything that does not tie is flagged.
3. Run `scripts/rebuild.sh`, then commit and push. The page updates.

## Hosting
The site is plain static files: publish the repository root on GitHub Pages or Cloudflare Pages (no build step). The repository contains bank statements, customer order details and invoices – keep it **private** and protect the site (for example Cloudflare Access).

## Report period (`data/scope.json`)
The report is limited to the dates in `data/scope.json`: **sales and payouts 25 Jul 2018 – 31 Mar 2020**, **sourcing (supplier invoices) 1 Jul 2018 – 31 Mar 2020**. Sourcing starts earlier because goods sold were bought at least a month before. Change the dates there and run `scripts/rebuild.sh` (the page reads the same file). Documents outside the dates stay in the repository but are not counted.

## Rules the report follows
* Every invoice number is counted once, using its final version (an invoice rather than a draft order, then the latest PDF creation time).
* Documents billed to SCENTCITY (its own purchases) are shown for provenance and are not counted as Nasima purchases.
* Product matching is automatic and tiered (high / probable / needs review); weak matches are never counted as matched.
* Dates are Amazon's Pacific time. Units are order quantities; refunds are shown in dollars.
