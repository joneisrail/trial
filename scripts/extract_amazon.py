#!/usr/bin/env python3
"""Extract Amazon Monthly Unified Transaction CSVs into report-ready JSON.

Input : "Nasima report Amazon/*MonthlyUnifiedTransaction.csv"
Output: data/amazon/lines/YYYY-MM.json  (every source row, with file + line ref)
        data/amazon/summary.json        (month -> day totals, payouts)
        data/amazon/checks.json         (integrity checks)
Dates are kept exactly as Amazon prints them (Pacific time, PST/PDT).
Nothing is de-duplicated or dropped: every source row is written once.
"""
import csv, glob, json, os, re, datetime, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "Nasima report Amazon")
OUT = os.path.join(ROOT, "data", "amazon")
MONEY = ["product sales", "product sales tax", "shipping credits", "shipping credits tax",
         "gift wrap credits", "giftwrap credits tax", "Regulatory Fee", "Tax On Regulatory Fee",
         "promotional rebates", "promotional rebates tax", "marketplace withheld tax",
         "selling fees", "fba fees", "other transaction fees", "other"]

def num(s):
    s = (s or "").replace(",", "").strip()
    return round(float(s), 2) if s else 0.0

def parse_date(s):
    m = re.match(r"(\w+) (\d+), (\d+) (\d+:\d+:\d+ [AP]M)", s)
    d = datetime.datetime.strptime(f"{m[1]} {m[2]} {m[3]} {m[4]}", "%b %d %Y %I:%M:%S %p")
    return d.strftime("%Y-%m-%d"), d.strftime("%H:%M:%S")

lines = collections.defaultdict(list)
files = []
for path in sorted(glob.glob(os.path.join(SRC, "*MonthlyUnifiedTransaction.csv"))):
    fname = os.path.basename(path)
    n_rows = 0; sum_total = 0.0; header = None
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rd = csv.reader(fh)
        for row in rd:
            if header is None:
                if row and row[0] == "date/time":
                    header = row
                continue
            if not row: continue
            r = dict(zip(header, row))
            day, tm = parse_date(r["date/time"])
            rec = {
                "d": day, "t": tm, "type": r["type"], "order": r["order id"], "sku": r["sku"],
                "desc": r["description"], "qty": int(num(r["quantity"])),
                "sales": num(r["product sales"]), "stax": num(r["product sales tax"]),
                "ship": num(r["shipping credits"]), "promo": num(r["promotional rebates"]),
                "sellfee": num(r["selling fees"]), "fbafee": num(r["fba fees"]),
                "otherfee": num(r["other transaction fees"]), "other": num(r["other"]),
                "total": num(r["total"]), "settle": r["settlement id"],
                "src": fname, "line": rd.line_num,
            }
            comp = round(sum(num(r.get(c)) for c in MONEY), 2)
            ok = abs(comp - rec["total"]) < 0.011
            if not ok: rec["mismatch"] = 1
            m = re.search(r"ending (?:in|with):? ?(\d+)", r["description"])
            if r["type"] == "Transfer" and m: rec["acct"] = m[1]
            lines[day[:7]].append(rec)
            n_rows += 1; sum_total += rec["total"]
    files.append({"file": fname, "rows": n_rows, "sum_total": round(sum_total, 2)})

os.makedirs(os.path.join(OUT, "lines"), exist_ok=True)
for f in glob.glob(os.path.join(OUT, "lines", "*.json")): os.remove(f)
summary = {}
for mon in sorted(lines):
    rows = sorted(lines[mon], key=lambda x: (x["d"], x["t"]))
    with open(os.path.join(OUT, "lines", mon + ".json"), "w") as fh:
        json.dump(rows, fh, separators=(",", ":"))
    days = collections.OrderedDict()
    for x in rows:
        d = days.setdefault(x["d"], dict(orders=0, units=0, sales=0.0, shipcr=0.0, promo=0.0, fees=0.0,
                                         refunds=0, refund_amt=0.0, payouts=0.0, net=0.0))
        t = x["type"]
        if t == "Order":
            d["orders"] += 1; d["units"] += x["qty"]; d["sales"] += x["sales"]
            d["shipcr"] += x["ship"]; d["promo"] += x["promo"]
        if t == "Refund": d["refunds"] += 1; d["refund_amt"] += x["total"]
        if t == "Transfer": d["payouts"] += -x["total"]
        d["fees"] += x["sellfee"] + x["fbafee"] + x["otherfee"]
        d["net"] += x["total"]
    for d in days.values():
        for k in d: d[k] = round(d[k], 2) if isinstance(d[k], float) else d[k]
    mt = collections.Counter()
    for d in days.values():
        for k, v in d.items(): mt[k] += v
    summary[mon] = {"totals": {k: round(v, 2) for k, v in mt.items()}, "days": days}

# checks
dup = collections.Counter((x["d"], x["t"], x["type"], x["order"], x["sku"], x["qty"], x["total"], x["src"])
                          for mon in lines for x in lines[mon])
all_rows = [x for mon in lines for x in lines[mon]]
checks = {
    "files": files,
    "total_rows_in_files": sum(f["rows"] for f in files),
    "total_rows_written": len(all_rows),
    "rows_where_components_ne_total": sum(1 for x in all_rows if x.get("mismatch")),
    "identical_row_groups_kept": sum(1 for v in dup.values() if v > 1),
    "types": dict(collections.Counter(x["type"] for x in all_rows)),
    "payout_accounts": dict(collections.Counter(x.get("acct") for x in all_rows if x["type"] == "Transfer")),
    "first_date": min(x["d"] for x in all_rows), "last_date": max(x["d"] for x in all_rows),
}
with open(os.path.join(OUT, "summary.json"), "w") as fh: json.dump(summary, fh, separators=(",", ":"))
with open(os.path.join(OUT, "checks.json"), "w") as fh: json.dump(checks, fh, indent=1)
print(json.dumps({k: v for k, v in checks.items() if k != "files"}, indent=1))
