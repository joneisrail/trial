#!/usr/bin/env python3
"""Write data/report_meta.json: generation time and document counts shown on the report's Summary tab."""
import glob, json, os, datetime
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def n(pat): return len(glob.glob(os.path.join(ROOT, pat)))
meta = {
    "generated_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    "documents": {
        "Amazon transaction reports (CSV)": n("Nasima report Amazon/*MonthlyUnifiedTransaction.csv"),
        "Bank statements and payment cheque (PDF)": n("Amazon Payment Received/*.pdf"),
        "Supplier invoices – SCENTCITY INC": n("All Invoice/*.pdf"),
        "Supplier invoices – B&S Fragrance": n("All Invoice/BS Fragrance/*.pdf"),
        "Supplier invoices – Dewan Fragrances": n("All Invoice/Dewan/*.PDF") + n("All Invoice/Dewan/*.pdf"),
        "Supplier invoices – Perfume Center of America": n("All Invoice/Perfume Center/*.pdf"),
        "Other documents (Perfume Network invoices, Scentcity supply-chain documents, BOL)": n("All Invoice/Others/*.pdf"),
    },
}
json.dump(meta, open(os.path.join(ROOT, "data", "report_meta.json"), "w"), indent=1)
print(json.dumps(meta, indent=1))
