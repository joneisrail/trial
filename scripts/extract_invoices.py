#!/usr/bin/env python3
"""Extract SCENTCITY INC supplier invoices (text-layer PDFs) -> data/invoices/*.json
Every invoice records its source PDF, page of each line, and validation results."""
import sys, glob, json, os, re, subprocess, collections, datetime
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parse_bs import parse_bs
from parse_dewan import parse_dewan
SRC = os.path.join(ROOT, "All Invoice"); BS = os.path.join(SRC, "BS Fragrance"); DEWAN = os.path.join(SRC, "Dewan"); OUT = os.path.join(ROOT, "data", "invoices")
NUM = r"-?[\d,]*\.?\d+"
LINE = re.compile(rf"^\s*({NUM})\s+(\S+)\s+(.*?)\s+({NUM})\s+({NUM})\s*$")
PEND = re.compile(rf"^\s*({NUM})\s+(\S+)\s*$")           # qty + code, description/price on next line
DESC = re.compile(rf"^\s+(.*?)\s+({NUM})\s+({NUM})\s*$")   # description + price + amount only
def f(s): return round(float(s.replace(",", "")), 2)
def parse(path):
    txt = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True).stdout
    pages = txt.split("\f")
    if pages and not pages[-1].strip(): pages = pages[:-1]
    inv = {"file": os.path.basename(path), "pages": len(pages), "lines": [], "notes": [], "total": None,
           "date": None, "number": None, "bill_to": None, "terms": None, "rep": None, "via": None, "problems": []}
    for pi, pg in enumerate(pages, 1):
        L = pg.splitlines(); inrows = False; pend = None
        for i, l in enumerate(L):
            m = re.search(r"(\d{1,2}/\d{1,2}/\d{4})\s+(\d+)\s*$", l) if i < 12 else None
            if m and not inv["date"]: inv["date"], inv["number"] = m[1], m[2]
            if "Bill To" in l and not inv["bill_to"]:
                inv["bill_to"] = next((re.split(r"\s{2,}", x.strip())[0] for x in L[i+1:i+4] if x.strip()), None)
            if "Terms" in l and "Rep" in l and i + 2 < len(L):
                parts = re.split(r"\s{2,}", L[i+2].strip())
                if len(parts) >= 3: inv["terms"], inv["rep"] = parts[0], parts[1]
                if len(parts) >= 4: inv["ship_date"] = parts[2]; inv["via"] = parts[3] if len(parts) > 3 else None
            if re.match(r"\s*Quantity\s+Item Code", l): inrows = True; continue
            m = re.search(r"Total\s+\$([\d,]+\.\d\d)\s*$", l)
            if m: inv["total"] = f(m[1]); inrows = False; continue
            if re.search(r"Phone #\s+Fax #", l): inrows = False; continue
            if not inrows or not l.strip(): continue
            m = LINE.match(l)
            if pend and not m:
                d = DESC.match(l)
                if d:
                    inv["lines"].append({"qty": f(pend[0]), "code": pend[1], "desc": d[1].strip(), "price": f(d[2]),
                                         "amount": f(d[3]), "page": pi}); pend = None; continue
            pend = None
            if not m and PEND.match(l) and "." in l or (not m and PEND.match(l) and l.strip().split()[1].endswith("...")):
                pend = PEND.match(l).groups(); continue
            if m:
                inv["lines"].append({"qty": f(m[1]), "code": m[2], "desc": m[3].strip(), "price": f(m[4]),
                                     "amount": f(m[5]), "page": pi})
            elif re.match(rf"^\s+(DELIVERY)\s+(.*?)\s+({NUM})\s+({NUM})\s*$", l):
                d = re.match(rf"^\s+(DELIVERY)\s+(.*?)\s+({NUM})\s+({NUM})\s*$", l)
                inv["lines"].append({"qty": 1.0, "code": "DELIVERY", "desc": d[2].strip(), "price": f(d[3]),
                                     "amount": f(d[4]), "page": pi, "non_merch": True})
            elif inv["lines"] and l.startswith(" " * 20) and not re.match(r"\s*\d", l):
                inv["lines"][-1]["desc"] += " " + l.strip()
            else:
                inv["notes"].append({"page": pi, "text": l.strip()})
    s = round(sum(x["amount"] for x in inv["lines"]), 2); inv["lines_sum"] = s
    if inv["total"] is None: inv["problems"].append("no total found")
    elif abs(s - inv["total"]) > 0.011: inv["problems"].append(f"lines sum {s} != total {inv['total']}")
    for x in inv["lines"]:
        if abs(round(x["qty"] * x["price"], 2) - x["amount"]) > 0.011:
            inv["problems"].append(f"qty*price != amount: {x['code']} {x['qty']}*{x['price']}!={x['amount']}")
    info = subprocess.run(["pdfinfo", "-isodates", path], capture_output=True, text=True).stdout
    m = re.search(r"CreationDate:\s+(\S+)", info); inv["pdf_created"] = m[1] if m else None
    if inv["date"]:
        inv["iso_date"] = datetime.datetime.strptime(inv["date"], "%m/%d/%Y").strftime("%Y-%m-%d")
    return inv
if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    invs = []
    for p in sorted(glob.glob(os.path.join(SRC, "*.pdf"))):
        i = parse(p); i["supplier"] = "SCENTCITY INC"; i["doc_type"] = "invoice"
        i["file"] = "All Invoice/" + i["file"]; invs.append(i)
    for p in sorted(glob.glob(os.path.join(BS, "*.pdf"))):
        invs.append(parse_bs(p, os.path.relpath(p, ROOT)))
    for p in sorted(glob.glob(os.path.join(DEWAN, "*.PDF")) + glob.glob(os.path.join(DEWAN, "*.pdf"))):
        invs.append(parse_dewan(p, os.path.relpath(p, ROOT)))
    # Same invoice number in several files = versions / copies of one invoice. Final version =
    # an invoice rather than a draft order, then latest PDF creation time, then larger total.
    groups = collections.defaultdict(list)
    for i in invs: groups[(i["supplier"], i["number"])].append(i)
    for n, v in groups.items():
        v.sort(key=lambda x: (x["doc_type"] == "invoice", x["pdf_created"] or "", x["total"] or 0))
        for k, x in enumerate(v):
            x["version"] = k + 1; x["versions_of_number"] = len(v); x["final"] = (k == len(v) - 1)
            if x["final"] and any((y["total"] or 0) > (x["total"] or 0) for y in v[:-1]):
                x["problems"].append("final version has LOWER total than an earlier version - confirm")
    json.dump(invs, open(os.path.join(OUT, "invoices.json"), "w"), separators=(",", ":"))
    print(len(invs), "files;", sum(1 for i in invs if i["final"]), "invoices;", sum(len(i["lines"]) for i in invs), "lines;",
          sum(1 for i in invs if i["problems"]), "with problems")
