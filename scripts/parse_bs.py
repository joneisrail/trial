"""Parser for B&S FRAGRANCES AND COSMETICS INC. invoices / orders (text-layer PDFs)."""
import re, subprocess, os, datetime
M = r"\$([\d,]+\.\d\d)"
ROW = re.compile(rf"^\s*(\d+)\s+(.+?)\s{{2,}}(.*?)\s+{M}\s+(\S+)\s+(?:(\d+(?:\.\d+)?)%\s+)?{M}\s*(\w)?\s*$")
PEND = re.compile(r"^\s*(\d+)\s+(\S+)\s*$")
DESC = re.compile(rf"^\s+(.*?)\s+{M}\s+(\S+)\s+(?:(\d+(?:\.\d+)?)%\s+)?{M}\s*(\w)?\s*$")
def f(s): return round(float(s.replace(",", "")), 2)
def parse_bs(path, rel):
    txt = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True).stdout
    pages = txt.split("\f")
    if pages and not pages[-1].strip(): pages = pages[:-1]
    inv = {"supplier": "B&S FRAGRANCES AND COSMETICS INC.", "file": rel, "pages": len(pages), "lines": [], "notes": [],
           "total": None, "date": None, "number": None, "bill_to": None, "problems": [], "doc_type": "invoice"}
    sums = {}
    for pi, pg in enumerate(pages, 1):
        L = pg.splitlines(); inrows = False; pend = None
        if any(re.fullmatch(r"\s*Order\s*", l) or re.search(r"\s{20,}Order\s*$", l) for l in L[:8]): inv["doc_type"] = "order"
        for i, l in enumerate(L):
            m = re.search(r"INV(?:OICE)?\s*#:?\s*(\d+)", l, re.I)
            if m and not inv["number"]: inv["number"] = m[1]
            if "Bill To" in l and not inv["bill_to"]:
                inv["bill_to"] = next((re.split(r"\s{2,}", x.strip())[0] for x in L[i+1:i+4] if x.strip()), None)
            if re.search(r"SALESPERSON\s+YOUR NO", l) and i + 2 < len(L):
                parts = re.split(r"\s{2,}", L[i+2].strip())
                d = re.findall(r"\d{1,2}/\d{1,2}/\d{4}", L[i+2])
                if d and not inv["date"]: inv["date"] = d[-1]; inv["salesperson"] = parts[0]; inv["your_no"] = parts[1] if len(parts) > 1 else None
            if re.search(r"QTY\.\s+ITEM NO", l): inrows = True; continue
            for key, pat in (("sale", r"SALE AMOUNT|Sale Amt\.:"), ("freight", r"FREIGHT|Freight:"), ("tax", r"SALES TAX|Sales Tax:"),
                             ("total", r"TOTAL|Total Amt\.:"), ("paid", r"PAID TODAY|Paid Today:"), ("balance", r"BALANCE DUE|Balance Due:")):
                m = re.search(rf"(?:{pat})\s+{M}\s*$", l)
                if m: sums[key] = f(m[1]); inrows = False
            if not inrows or not l.strip(): continue
            if "THANK YOU" in l: inrows = False; continue
            m = ROW.match(l)
            if pend and not m:
                d = DESC.match(l)
                if d:
                    inv["lines"].append({"qty": float(pend[0]), "code": pend[1], "desc": d[1].strip(), "price": f(d[2]),
                                         "unit": d[3], "disc": float(d[4]) if d[4] else 0.0, "amount": f(d[5]), "page": pi})
                    pend = None; continue
            pend = None
            if not m and PEND.match(l): pend = PEND.match(l).groups(); continue
            if m:
                inv["lines"].append({"qty": float(m[1]), "code": m[2].strip(), "desc": m[3].strip(), "price": f(m[4]),
                                     "unit": m[5], "disc": float(m[6]) if m[6] else 0.0, "amount": f(m[7]), "page": pi})
            elif inv["lines"] and l.startswith(" " * 12):
                inv["lines"][-1]["desc"] += " " + l.strip()
            else:
                inv["notes"].append({"page": pi, "text": l.strip()})
    inv["sums"] = sums; inv["total"] = sums.get("total", sums.get("sale"))
    if not inv["number"]:
        m = re.search(r"(\d{4,8})", os.path.basename(rel)); inv["number"] = m[1].zfill(8) if m else None
        inv["problems"].append("invoice number taken from file name")
    s = round(sum(x["amount"] for x in inv["lines"]), 2); inv["lines_sum"] = s
    if inv["total"] is None: inv["problems"].append("no total found")
    elif "sale" in sums and abs(s - sums["sale"]) > 0.011: inv["problems"].append(f"lines sum {s} != sale amount {sums['sale']}")
    for x in inv["lines"]:
        exp = round(x["qty"] * x["price"] * (1 - x["disc"] / 100), 2)
        if abs(exp - x["amount"]) > 0.011: inv["problems"].append(f"qty*price != amount: {x['code']} {x['qty']}*{x['price']}!={x['amount']}")
    inv["pdf_created"] = None
    info = subprocess.run(["pdfinfo", "-isodates", path], capture_output=True, text=True).stdout
    m = re.search(r"CreationDate:\s+(\S+)", info); inv["pdf_created"] = m[1] if m else None
    if inv["date"]: inv["iso_date"] = datetime.datetime.strptime(inv["date"], "%m/%d/%Y").strftime("%Y-%m-%d")
    return inv
