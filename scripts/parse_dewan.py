"""Parser for DEWAN FRAGRANCES INC invoices (text-layer PDFs)."""
import re, subprocess, os, datetime
NUM = r"-?[\d,]*\.?\d+"
ROW = re.compile(rf"^\s*({NUM})\s+(\S+)\s+(.*?)\s+({NUM})\s+({NUM})\s*$")
PEND = re.compile(rf"^\s*({NUM})\s+(\S+)\s*$")
DESC = re.compile(rf"^\s+(.*?)\s+({NUM})\s+({NUM})\s*$")
def f(s): return round(float(s.replace(",", "")), 2)
def parse_dewan(path, rel):
    txt = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True).stdout
    pages = txt.split("\f")
    if pages and not pages[-1].strip(): pages = pages[:-1]
    inv = {"supplier": "DEWAN FRAGRANCES INC", "file": rel, "pages": len(pages), "lines": [], "notes": [], "total": None,
           "date": None, "number": None, "bill_to": None, "problems": [], "doc_type": "invoice"}
    sums = {}
    for pi, pg in enumerate(pages, 1):
        L = pg.splitlines(); inrows = False; pend = None
        for i, l in enumerate(L):
            m = re.search(r"Invoice Number:\s*(\S+)", l)
            if m and not inv["number"]: inv["number"] = m[1]
            m = re.search(r"Invoice Date:\s*(\w+ \d+, \d{4})", l)
            if m and not inv["date"]: inv["date"] = m[1]
            if "Bill To" in l and not inv["bill_to"]:
                inv["bill_to"] = next((re.split(r"\s{2,}", x.strip())[0] for x in L[i+1:i+4] if x.strip()), None)
            if re.match(r"\s*Quantity\s+Item\s+Description", l): inrows = True; continue
            for key, pat in (("subtotal", r"Subtotal"), ("freight", r"Freight"), ("total", r"Total Invoice Amount"),
                             ("paid", r"Payment/Credit Applied"), ("balance", r"TOTAL BALANCE DUE")):
                m = re.search(rf"{pat}\s+\(?({NUM})\)?\s*$", l)
                if m: sums[key] = f(m[1]); inrows = False
            if re.search(r"TOTAL PI?E?CES", l): inrows = False; continue
            if not inrows or not l.strip(): continue
            m = ROW.match(l)
            if pend and not m:
                d = DESC.match(l)
                if d:
                    inv["lines"].append({"qty": f(pend[0]), "code": pend[1], "desc": d[1].strip(), "price": f(d[2]), "amount": f(d[3]), "page": pi})
                    pend = None; continue
            pend = None
            if not m and PEND.match(l): pend = PEND.match(l).groups(); continue
            if m:
                inv["lines"].append({"qty": f(m[1]), "code": m[2], "desc": m[3].strip(), "price": f(m[4]), "amount": f(m[5]), "page": pi})
            elif inv["lines"] and l.startswith(" " * 12) and not re.search(r"\d\.\d\d\s*$", l):
                inv["lines"][-1]["desc"] += " " + l.strip()
            else:
                inv["notes"].append({"page": pi, "text": l.strip()})
    inv["sums"] = sums; inv["total"] = sums.get("total", sums.get("subtotal"))
    s = round(sum(x["amount"] for x in inv["lines"]), 2); inv["lines_sum"] = s
    if inv["total"] is None: inv["problems"].append("no total found")
    elif abs(s - sums.get("subtotal", inv["total"])) > 0.011: inv["problems"].append(f"lines sum {s} != subtotal {sums.get('subtotal', inv['total'])}")
    for x in inv["lines"]:
        if abs(round(x["qty"] * x["price"], 2) - x["amount"]) > 0.011:
            inv["problems"].append(f"qty*price != amount: {x['code']} {x['qty']}*{x['price']}!={x['amount']}")
    info = subprocess.run(["pdfinfo", "-isodates", path], capture_output=True, text=True).stdout
    m = re.search(r"CreationDate:\s+(\S+)", info); inv["pdf_created"] = m[1] if m else None
    if inv["date"]: inv["iso_date"] = datetime.datetime.strptime(inv["date"], "%b %d, %Y").strftime("%Y-%m-%d")
    return inv
