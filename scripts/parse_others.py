"""Parsers for the 'Others' folder: Perfume Network, Fragrance Unlimited II, Premier Fragrance, Niche Brands,
plus B&S invoices billed to SCENTCITY. Each doc gets category = 'nasima_purchase' (billed to Nasima) or
'upstream_scentcity' (billed to Scentcity: Scentcity's own purchases, NOT Nasima's)."""
import re, subprocess, os, datetime
from parse_bs import parse_bs
NUM = r"-?[\d,]*\.?\d+"
def f(s): return round(float(s.replace(",", "")), 2)
def text(path):
    t = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True).stdout
    pages = t.split("\f")
    return pages[:-1] if pages and not pages[-1].strip() else pages
def created(path):
    m = re.search(r"CreationDate:\s+(\S+)", subprocess.run(["pdfinfo", "-isodates", path], capture_output=True, text=True).stdout)
    return m[1] if m else None
def base(supplier, rel, pages):
    return {"supplier": supplier, "file": rel, "pages": len(pages), "lines": [], "notes": [], "total": None, "date": None,
            "number": None, "bill_to": None, "problems": [], "doc_type": "invoice"}
def finish(inv, path, datefmt, lines_total=None):
    s = round(sum(x["amount"] for x in inv["lines"]), 2); inv["lines_sum"] = s
    if inv["total"] is None: inv["problems"].append("no total found")
    else:
        expect = lines_total if lines_total is not None else inv["total"]
        if abs(s - expect) > 0.011: inv["problems"].append(f"lines sum {s} != {expect}")
    for x in inv["lines"]:
        if abs(round(x["qty"] * x["price"], 2) - x["amount"]) > 0.011:
            inv["problems"].append(f"qty*price != amount: {x['code']} {x['qty']}*{x['price']}!={x['amount']}")
    inv["pdf_created"] = created(path)
    if inv["date"]: inv["iso_date"] = datetime.datetime.strptime(inv["date"], datefmt).strftime("%Y-%m-%d")
    inv["category"] = "nasima_purchase" if "NASIMA" in (inv["bill_to"] or "").upper() else "upstream_scentcity"
    return inv

def parse_pni(path, rel):
    pages = text(path); inv = base("PERFUME NETWORK INC", rel, pages)
    for pi, pg in enumerate(pages, 1):
        L = pg.splitlines(); inrows = False
        for i, l in enumerate(L):
            m = re.search(r"Invoice Number:\s*(\S+)", l)
            if m and not inv["number"]: inv["number"] = m[1]
            m = re.search(r"Invoice Date:\s*(\w+ \d+, \d{4})", l)
            if m and not inv["date"]: inv["date"] = m[1]
            if "Bill To" in l and not inv["bill_to"]:
                inv["bill_to"] = next((re.split(r"\s{2,}", x.strip())[0] for x in L[i+1:i+3] if x.strip()), None)
            if re.match(r"\s*Quantity\s+Item Description", l): inrows = True; continue
            m = re.search(rf"\bTOTAL\s+({NUM})\s*$", l)
            if m: inv["total"] = f(m[1]); inrows = False
            m = re.search(rf"SUBTOTAL\s+({NUM})\s*$", l)
            if m: inv["subtotal"] = f(m[1]); inrows = False
            if not inrows or not l.strip(): continue
            m = re.match(rf"^\s*({NUM})\s+(.*?)\s+({NUM})\s+({NUM})\s*$", l)
            if m:
                fr = "FREIGHT" in m[2].upper()
                inv["lines"].append({"qty": f(m[1]), "code": "", "desc": m[2].strip(), "price": f(m[3]), "amount": f(m[4]), "page": pi,
                                     **({"non_merch": True} if fr else {})})
            elif l.strip(): inv["notes"].append({"page": pi, "text": l.strip()})
    return finish(inv, path, "%b %d, %Y", inv.get("subtotal"))

ROW5 = re.compile(rf"^\s*({NUM})\s+(\S+)\s+(.*?)\s+({NUM})\s+({NUM})\s*$")
def parse_qcode(path, rel, supplier, billre, datere, numre, totre):
    """Scentcity-style layout: qty, item code, description, price, amount (FU2, Premier)."""
    pages = text(path); inv = base(supplier, rel, pages)
    for pi, pg in enumerate(pages, 1):
        L = pg.splitlines(); inrows = False
        for i, l in enumerate(L):
            m = re.search(r"(\d{1,2}/\d{1,2}/\d{4})\s+(\d+)\s*$", l)
            if m and not inv["date"] and i < 14: inv["date"], inv["number"] = m[1], m[2]
            if re.search(r"BILL TO|Bill To", l) and not inv["bill_to"]:
                inv["bill_to"] = next((re.split(r"\s{2,}", x.strip())[0] for x in L[i+1:i+3] if x.strip()), None)
            if re.match(r"\s*(QUANTITY|Quantity)\s+(ITEM CODE|Item Code)", l): inrows = True; continue
            m = re.search(rf"Total(?: USD)?\s+\$?({NUM})\s*$", l)
            if m: inv["total"] = f(m[1]); inrows = False; continue
            if not inrows or not l.strip(): continue
            m = ROW5.match(l)
            if m: inv["lines"].append({"qty": f(m[1]), "code": m[2], "desc": m[3].strip(), "price": f(m[4]), "amount": f(m[5]), "page": pi})
            elif inv["lines"] and l.startswith(" " * 20): inv["lines"][-1]["desc"] += " " + l.strip()
            elif re.match(r"\s*(Overdue|etc\.|to our|This merch|This mer|ALL GOODS|UNTIL)", l): inrows = False
            else: inv["notes"].append({"page": pi, "text": l.strip()})
    return finish(inv, path, "%m/%d/%Y")

NROW = re.compile(rf"^\s*(\S+)\s+(.*?)\s+(?:(\d+|N/A)\s+)?(\d+)\s+({NUM})\s+({NUM})\s*(\d{{9,14}})?\s*$")
def parse_niche(path, rel):
    pages = text(path); inv = base("NICHE BRANDS INTERNATIONAL", rel, pages)
    for pi, pg in enumerate(pages, 1):
        L = pg.splitlines(); inrows = False
        for i, l in enumerate(L):
            m = re.search(r"(\d{1,2}/\d{1,2}/\d{4})\s+(SR\d+)\s*$", l)
            if m and not inv["date"]: inv["date"], inv["number"] = m[1], m[2]
            if "Invoice To" in l and not inv["bill_to"]:
                inv["bill_to"] = next((re.split(r"\s{2,}", x.strip())[0] for x in L[i+1:i+3] if x.strip()), None)
                inv["bill_to"] = " / ".join(re.split(r"\s{2,}", x.strip())[0] for x in L[i+1:i+3] if x.strip())
            m = re.search(r"Total Qty.*", l)
            if m and i + 2 < len(L):
                n = re.findall(r"(\d+)\s+([\d.]+)\s*$", L[i+2]); 
                if n: inv["stated_qty"] = int(n[0][0])
            if re.match(r"\s*Item Na", l): inrows = True; continue
            m = re.search(rf"\bTotal\s+({NUM})\s*$", l)
            if m and "Subtotal" not in l: inv["total"] = f(m[1])
            m = re.search(rf"Subtotal\s+({NUM})\s*$", l)
            if m: inv["subtotal"] = f(m[1])
            if re.search(r"Minimum advertised", l): inrows = False
            if not inrows or not l.strip(): continue
            m = NROW.match(l)
            if m: inv["lines"].append({"qty": float(m[4]), "code": m[1], "desc": m[2].strip(), "price": f(m[5]), "amount": f(m[6]),
                                       "case_pack": m[3] or "", "upc": m[7] or "", "page": pi})
    return finish(inv, path, "%m/%d/%Y", inv.get("subtotal"))

def parse_other(path, rel):
    t = "\n".join(text(path))
    if "PERFUME NETWORK" in t: inv = parse_pni(path, rel)
    elif "FRAGRANCE UNLIMITED" in t: inv = parse_qcode(path, rel, "FRAGRANCE UNLIMITED II, INC.", None, None, None, None)
    elif "PREMIER FRAGRANCE" in t: inv = parse_qcode(path, rel, "PREMIER FRAGRANCE LLC", None, None, None, None)
    elif "nichebrandsintl" in t or "Niche Brands" in t: inv = parse_niche(path, rel)
    elif "B&S FRAGRANCES" in t:
        inv = parse_bs(path, rel); inv["category"] = "nasima_purchase" if "NASIMA" in (inv["bill_to"] or "").upper() else "upstream_scentcity"
    else: return None
    return inv
