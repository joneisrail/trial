"""Parser for PERFUME CENTER OF AMERICA invoices (text-layer PDFs)."""
import re, subprocess, os, datetime
NUM = r"-?[\d,]*\.?\d+"
ROW = re.compile(rf"^\s*(\S+)\s+(\S+)\s+({NUM})\s+({NUM})\s+({NUM})\s+({NUM})\s*$")
def f(s): return round(float(s.replace(",", "")), 2)
def parse_pc(path, rel):
    txt = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True).stdout
    pages = txt.split("\f")
    if pages and not pages[-1].strip(): pages = pages[:-1]
    inv = {"supplier": "PERFUME CENTER OF AMERICA", "file": rel, "pages": len(pages), "lines": [], "notes": [], "total": None,
           "date": None, "number": None, "bill_to": None, "problems": [], "doc_type": "invoice"}
    sums = {}; stated = {}
    for pi, pg in enumerate(pages, 1):
        L = pg.splitlines(); inrows = False
        for i, l in enumerate(L):
            m = re.search(r"Invoice Number:\s*(\S+)", l)
            if m and not inv["number"]: inv["number"] = m[1]
            m = re.search(r"Invoice Date:\s*(\d+/\d+/\d{4})", l)
            if m and not inv["date"]: inv["date"] = m[1]
            m = re.search(r"Total Lines:\s*(\d+)\s+Total Units:\s*(\d+)", l)
            if m: stated = {"lines": int(m[1]), "units": int(m[2])}
            m = re.search(r"(?:Sold To|Bill To):", l)
            if m and not inv["bill_to"]:
                inv["bill_to"] = next((re.split(r"\s{2,}", x.strip())[0] for x in L[i+1:i+3] if x.strip()), None)
            m = re.search(r"Order Number:\s*(\S+)|SO Number:\s*(\S+)", l)
            if m and not inv.get("order_no"): inv["order_no"] = m[1] or m[2]
            if re.match(r"\s*Item Number\s+Unit\s+Quantity", l): inrows = True; continue
            for key, pat in (("net", r"Net Order:"), ("discount", r"Less Discount:"), ("freight", r"Freight:"),
                             ("tax", r"Sales Tax:"), ("total", r"Order Total:")):
                m = re.search(rf"{pat}\s+({NUM})\s*$", l)
                if m: sums[key] = f(m[1]); inrows = False
            if re.match(r"\s*All sales are final", l): inrows = False
            if not inrows or not l.strip(): continue
            m = ROW.match(l)
            if m:
                inv["lines"].append({"qty": f(m[3]), "code": m[1], "unit": m[2], "backorder": f(m[4]), "desc": "", "price": f(m[5]),
                                     "amount": f(m[6]), "page": pi})
            elif inv["lines"] and not inv["lines"][-1]["desc"]:
                inv["lines"][-1]["desc"] = l.strip()
            elif inv["lines"] and l.strip() and not re.match(r"\s*(Continued|Page:)", l) and l.startswith("    "):
                inv["lines"][-1]["desc"] += " " + l.strip()
            elif l.strip() and not re.match(r"\s*(Continued|Page:)", l):
                inv["notes"].append({"page": pi, "text": l.strip()})
    inv["sums"] = sums; inv["stated"] = stated; inv["total"] = sums.get("total", sums.get("net"))
    s = round(sum(x["amount"] for x in inv["lines"]), 2); inv["lines_sum"] = s
    if inv["total"] is None: inv["problems"].append("no total found")
    elif "net" in sums and abs(s - sums["net"]) > 0.011: inv["problems"].append(f"lines sum {s} != net order {sums['net']}")
    if "net" in sums and abs(sums["net"] - sums.get("discount", 0) + sums.get("freight", 0) + sums.get("tax", 0) - inv["total"]) > 0.011:
        inv["problems"].append("net - discount + freight + tax != total")
    if stated:
        if stated["lines"] != len(inv["lines"]): inv["problems"].append(f"stated lines {stated['lines']} != parsed {len(inv['lines'])}")
        u = sum(x["qty"] for x in inv["lines"])
        if abs(stated["units"] - u) > 0.01: inv["problems"].append(f"stated units {stated['units']} != parsed {u}")
    for x in inv["lines"]:
        if abs(round(x["qty"] * x["price"], 2) - x["amount"]) > 0.011:
            inv["problems"].append(f"qty*price != amount: {x['code']} {x['qty']}*{x['price']}!={x['amount']}")
    info = subprocess.run(["pdfinfo", "-isodates", path], capture_output=True, text=True).stdout
    m = re.search(r"CreationDate:\s+(\S+)", info); inv["pdf_created"] = m[1] if m else None
    if inv["date"]: inv["iso_date"] = datetime.datetime.strptime(inv["date"], "%m/%d/%Y").strftime("%Y-%m-%d")
    return inv
