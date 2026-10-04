#!/bin/sh
# Rebuild every data file the report page reads. Run after adding documents.
set -e
cd "$(dirname "$0")/.."
python3 scripts/extract_amazon.py   >/dev/null
python3 scripts/extract_invoices.py
python3 scripts/match_products.py   >/dev/null
python3 scripts/build_meta.py       >/dev/null
rm -rf scripts/__pycache__
echo "done - commit and push to update the site"
