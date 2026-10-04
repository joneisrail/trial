#!/usr/bin/env python3
"""Product matching: Amazon titles <-> supplier invoice descriptions.

Method (deterministic, explainable):
 1. normalise every description (size in oz, set flag, gender, concentration, name tokens)
 2. fuzzy-canonicalise name tokens (typos / plurals, edit distance 1)
 3. cluster supplier descriptions into purchase products (same size + set flag, compatible gender,
    high weighted-token overlap)
 4. match each Amazon title to the best purchase product; confidence high / medium / low or none
 5. write data/products/*.json (+ per-product drill-down files)
Nothing is merged silently: low-confidence matches go to a review queue and are NOT counted as matched.
"""
import glob, json, math, os, re, sys, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from normalize import parse, VARIANTS
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def scope():
    return json.load(open(os.path.join(ROOT, "data", "scope.json")))

def load():
    sc = scope()
    am = collections.defaultdict(lambda: {"units": 0, "sales": 0.0, "skus": set(), "rows": 0, "refund_rows": 0, "refund_amt": 0.0, "first": "9", "last": "0"})
    for f in sorted(glob.glob(os.path.join(ROOT, "data/amazon/lines/*.json"))):
        for r in json.load(open(f)):
            if not (sc["sales_from"] <= r["d"] <= sc["sales_to"]): continue
            if r["type"] == "Order":
                a = am[r["desc"]]; a["units"] += r["qty"]; a["sales"] += r["sales"]; a["rows"] += 1
                if r["sku"]: a["skus"].add(r["sku"])
                a["first"] = min(a["first"], r["d"]); a["last"] = max(a["last"], r["d"])
            elif r["type"] == "Refund" and r["desc"]:
                a = am[r["desc"]]; a["refund_rows"] += 1; a["refund_amt"] += r["total"]
    inv = json.load(open(os.path.join(ROOT, "data/invoices/invoices.json")))
    pu = collections.defaultdict(lambda: {"units": 0.0, "amount": 0.0, "lines": 0, "suppliers": collections.Counter()})
    for i in inv:
        if not (i["final"] and i["category"] == "nasima_purchase"): continue
        if not (sc["purchases_from"] <= i["iso_date"] <= sc["purchases_to"]): continue
        for x in i["lines"]:
            if x.get("non_merch") or not x["desc"].strip(): continue
            p = pu[x["desc"]]; p["units"] += x["qty"]; p["amount"] += x["amount"]; p["lines"] += 1; p["suppliers"][i["supplier"]] += x["qty"]
    return am, pu

# ---- fuzzy token canonicalisation (optimal-string-alignment distance <= 1)
def osa1(a, b):
    if a == b: return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1: return False
    if la == lb:
        d = [i for i in range(la) if a[i] != b[i]]
        if len(d) == 1: return True
        return len(d) == 2 and d[1] == d[0] + 1 and a[d[0]] == b[d[1]] and a[d[1]] == b[d[0]]
    if la > lb: a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]: i += 1
    return a[i:] == b[i + 1:]

def canon_map(counter):
    toks = sorted(counter, key=lambda t: -counter[t])
    by = collections.defaultdict(list)
    for t in toks: by[(t[0], len(t))].append(t)
    m = {}
    for t in toks:
        if t in m: continue
        m[t] = t
        if len(t) < 4: continue
        for L in (len(t) - 1, len(t), len(t) + 1):
            for u in by.get((t[0], L), []):
                if u not in m and len(u) >= 4 and osa1(t, u): m[u] = t
    return m

def run():
    am, pu = load()
    A = {k: parse(k) for k in am}; P = {k: parse(k) for k in pu}
    cnt = collections.Counter(t.partition("#")[0] for d in list(A.values()) + list(P.values()) for t in d["tokens"])
    cm = canon_map(cnt)
    def cmap(t):
        base, _, n = t.partition("#"); b = cm.get(base, base)
        return b + ("#" + n if n else "")
    for d in list(A.values()) + list(P.values()): d["tk"] = frozenset(cmap(t) for t in d["tokens"])
    df = collections.Counter(t for d in list(A.values()) + list(P.values()) for t in d["tk"])
    N = len(A) + len(P)
    idf = {t: math.log((N + 1) / (c + 1)) + 0.5 for t, c in df.items()}
    W = lambda s: sum(idf[t] for t in s)
    for d in list(A.values()) + list(P.values()):
        for t in d['tk']: idf.setdefault(t, idf.get(t.partition('#')[0], 1.0))

    def compat(a, b):
        """return (ok, size_state) ; size_state: 'eq' | 'unk'"""
        if a["set"] != b["set"]: return False, None
        if a["kind"] != b["kind"]: return False, None
        if a["gender"] and b["gender"] and a["gender"] != b["gender"] and "U" not in (a["gender"], b["gender"]): return False, None
        if a["size"] is not None and b["size"] is not None:
            d = abs(a["size"] - b["size"])
            if d <= 0.15: return True, "eq"
            if d <= 0.45: return True, "near"
            return False, None
        return True, "unk"

    def score(a, b):
        ok, ss = compat(a, b)
        if not ok or not a["tk"] or not b["tk"]: return None
        inter = a["tk"] & b["tk"]
        if not inter: return None
        wi = W(inter); ws = min(W(a["tk"]), W(b["tk"])); wl = max(W(a["tk"]), W(b["tk"]))
        return {"small": wi / ws, "large": wi / wl, "size": ss, "inter": len(inter)}

    # ---- 3. cluster supplier descriptions
    inv_idx = collections.defaultdict(set)
    clusters = []   # list of {"members":[desc], "seed": parsed}
    for k in sorted(P, key=lambda k: -pu[k]["units"]):
        d = P[k]; best = None; bs = 0
        cands = set()
        for t in d["tk"]: cands |= inv_idx[t]
        for ci in cands:
            c = clusters[ci]
            if d["size"] is None or c["seed"]["size"] is None: continue   # never merge supplier lines on unknown size
            s = score(d, c["seed"])
            if (d["tk"] ^ c["seed"]["tk"]) & VARIANTS: continue          # 'intense' vs plain etc. are different products
            if s and s["size"] == "eq" and s["small"] >= 0.99 and s["large"] >= 0.5 and (s["small"] + s["large"]) > bs:
                best, bs = ci, s["small"] + s["large"]
        if best is None:
            clusters.append({"members": [k], "seed": d}); best = len(clusters) - 1
            for t in d["tk"]: inv_idx[t].add(best)
        else:
            clusters[best]["members"].append(k)
    return am, pu, A, P, clusters, inv_idx, idf, score, W

def classify(a, ci, s, clusters):
    """tier for Amazon title a vs cluster ci given score s (size state in s['size'])"""
    b = clusters[ci]["seed"]
    conc_hard = a["conc"] in ("edt", "edp") and b["conc"] in ("edt", "edp") and a["conc"] != b["conc"]
    sm, lg, sz = s["small"], s["large"], s["size"]
    if sz == "eq" and sm >= 0.99 and lg >= 0.6: t = "high"
    elif sz == "eq" and ((sm >= 0.99 and lg >= 0.3) or (sm >= 0.85 and lg >= 0.5)): t = "medium"
    elif sz == "near" and sm >= 0.99 and lg >= 0.4: t = "medium"
    elif sz == "unk" and sm >= 0.99 and lg >= 0.5: t = "unk"       # decided later (needs uniqueness)
    else: t = "low" if sm >= 0.7 else "none"
    extra_b = b["tk"] - a["tk"]                     # supplier words absent from the (usually wordier) Amazon title
    if extra_b and t in ("high", "medium"): t = "low" if t == "medium" else "medium"
    vdiff = (a["tk"] ^ b["tk"]) & VARIANTS
    if vdiff and t in ("high", "medium"): t = "low" if t == "medium" else "medium"   # variant word on one side only
    if conc_hard and t == "high": t = "medium"
    elif conc_hard and t == "medium": t = "low"
    return t

RANK = {"high": 3, "medium": 2, "low": 1, "none": 0}
def match_all(am, A, clusters, inv_idx, score):
    out = {}
    for k, a in A.items():
        cands = set()
        for t in a["tk"]: cands |= inv_idx[t]
        L = []
        for ci in cands:
            s = score(a, clusters[ci]["seed"])
            if not s: continue
            t = classify(a, ci, s, clusters)
            if t == "none": continue
            L.append({"ci": ci, "tier": t, "score": round(s["small"] * 0.7 + s["large"] * 0.3, 3), "size": s["size"],
                      "small": round(s["small"], 2), "large": round(s["large"], 2)})
        known = [c for c in L if c["tier"] in ("high", "medium", "low") and c["size"] != "unk"]
        unk = [c for c in L if c["tier"] == "unk"]
        known.sort(key=lambda c: (-RANK[c["tier"]], -c["score"]))
        note = ""
        if known and known[0]["tier"] in ("high", "medium"):
            best = known[0]; best_t = best["tier"]
        elif unk:
            # size unstated on one side: accept only if the candidates agree (a single product, or same size everywhere)
            sizes = {clusters[c["ci"]]["seed"]["size"] for c in unk}
            other_sizes = {clusters[c["ci"]]["seed"]["size"] for c in L if c["size"] in ("eq", "near")}
            if len(unk) == 1 or (len(sizes) == 1 and not other_sizes):
                unk.sort(key=lambda c: -c["score"]); best = unk[0]; best_t = "medium"
                note = "size not stated on " + ("the Amazon title" if a["size"] is None else "the invoice")
            else:
                unk.sort(key=lambda c: -c["score"]); best = unk[0]; best_t = "low"; note = "size not stated; several candidate products"
        elif known:
            best = known[0]; best_t = "low"
        else:
            best = None; best_t = "none"
        out[k] = {"tier": best_t, "best": best, "note": note, "alts": [c for c in sorted(L, key=lambda c: -c["score"]) if c is not best][:3]}
    return out

def grams(tk):
    st = "".join(sorted(tk)); return {st[i:i + 3] for i in range(max(1, len(st) - 2))}

def second_pass(M, A, clusters):
    """Relaxed pass for leftovers: Amazon titles still unmatched vs supplier products nobody matched.
    Character-trigram similarity catches abbreviations/spelling variants; only accepted with a clear margin."""
    attached = {m["best"]["ci"] for m in M.values() if m["tier"] in ("high", "medium")}
    orph = [ci for ci in range(len(clusters)) if ci not in attached and clusters[ci]["members"]]
    og = {ci: grams(clusters[ci]["seed"]["tk"]) for ci in orph}
    gi = collections.defaultdict(set)
    for ci, g in og.items():
        for x in g: gi[x].add(ci)
    n2 = 0
    for k, m in M.items():
        if m["tier"] in ("high", "medium"): continue
        a = A[k]; ga = grams(a["tk"]); cands = collections.Counter()
        for x in ga:
            for ci in gi.get(x, ()): cands[ci] += 1
        sc = []
        for ci, _ in cands.most_common(40):
            b = clusters[ci]["seed"]
            if a["set"] != b["set"] or a["kind"] != b["kind"]: continue
            if a["gender"] and b["gender"] and a["gender"] != b["gender"] and "U" not in (a["gender"], b["gender"]): continue
            if a["size"] is not None and b["size"] is not None:
                d = abs(a["size"] - b["size"])
                if d > 0.45: continue
                unk = False
            else: unk = True
            inter = len(ga & og[ci]); cont = inter / min(len(ga), len(og[ci])); dice = 2 * inter / (len(ga) + len(og[ci]))
            sc.append((0.5 * cont + 0.5 * dice, ci, unk))
        sc.sort(reverse=True)
        if not sc: continue
        top, ci, unk = sc[0]
        second = sc[1][0] if len(sc) > 1 else 0
        if top >= (0.8 if unk else 0.7) and top - second >= 0.05:
            M[k] = {"tier": "medium", "best": {"ci": ci, "tier": "medium", "score": round(top, 3), "size": "unk" if unk else "eq", "small": round(top, 2), "large": round(top, 2)},
                    "note": "approximate name match (spelling/abbreviation), similarity %.2f" % top, "alts": []}
            n2 += 1
    return n2

def merge_clusters(M, A, clusters, score):
    """(a) bridge: one Amazon title that fully contains the names of several supplier products of the same size
    shows they are the same product under different invoice wording -> merge them.
    (b) adopt: a supplier product with no size stated and the same name as exactly one sized product -> merge."""
    par = list(range(len(clusters)))
    def find(x):
        while par[x] != x: par[x] = par[par[x]]; x = par[x]
        return x
    def union(x, y):
        x, y = find(x), find(y)
        if x != y: par[y] = x
    nb = 0
    def can_merge(x, y):
        a, b = clusters[find(x)]["seed"], clusters[find(y)]["seed"]
        if a["set"] != b["set"] or a["kind"] != b["kind"]: return False
        if a["gender"] and b["gender"] and a["gender"] != b["gender"]: return False
        if a["size"] is None or b["size"] is None or abs(a["size"] - b["size"]) > 0.15: return False
        if (a["tk"] ^ b["tk"]) & VARIANTS: return False
        s_ = score(a, b)
        return bool(s_) and s_["small"] >= 0.99 and s_["large"] >= 0.35
    for k, m in M.items():
        if m["tier"] not in ("high", "medium") or not m["best"]: continue
        grp = [m["best"]["ci"]]
        for c in m["alts"]:
            if c["tier"] in ("high", "medium") and c["size"] in ("eq", "near") and c["small"] >= 0.99 and not (clusters[c["ci"]]["seed"]["tk"] - A[k]["tk"]):
                grp.append(c["ci"])
        grp = [g for g in grp if not (clusters[g]["seed"]["tk"] - A[k]["tk"])]
        for g in grp[1:]:
            if find(g) != find(grp[0]) and can_merge(grp[0], g): union(grp[0], g); nb += 1
    attached = {find(m["best"]["ci"]) for m in M.values() if m["tier"] in ("high", "medium")}
    na = 0
    byname = collections.defaultdict(list)
    for ci, c in enumerate(clusters):
        if c["seed"]["size"] is not None: byname[(c["seed"]["tk"], c["seed"]["set"], c["seed"]["kind"])].append(ci)
    for ci, c in enumerate(clusters):
        sd = c["seed"]
        if sd["size"] is None and find(ci) not in attached:
            cand = {find(x) for x in byname.get((sd["tk"], sd["set"], sd["kind"]), [])}
            if len(cand) == 1:
                union(next(iter(cand)), ci); na += 1
    for m in M.values():
        if m["best"]: m["best"]["ci"] = find(m["best"]["ci"])
        for c in m["alts"]: c["ci"] = find(c["ci"])
    members = collections.defaultdict(list)
    for ci, c in enumerate(clusters): members[find(ci)].extend(c["members"])
    merged = []
    for r in range(len(clusters)):
        if find(r) == r:
            members[r].sort(key=lambda d: 0)  # keep order
            merged.append(None)
    # rebuild cluster list with stable root indices
    new = [None] * len(clusters)
    for ci, c in enumerate(clusters):
        r = find(ci)
        if new[r] is None: new[r] = {"members": [], "seed": clusters[r]["seed"]}
        new[r]["members"].extend(c["members"])
    for i in range(len(new)):
        if new[i] is None: new[i] = {"members": [], "seed": clusters[i]["seed"]}
    print("merged supplier products: bridge", nb, "adopt-no-size", na)
    return new

def build():
    am, pu, A, P, clusters, inv_idx, idf, score, W = run()
    M = match_all(am, A, clusters, inv_idx, score)
    clusters = merge_clusters(M, A, clusters, score)
    print("second pass matched", second_pass(M, A, clusters), "more titles")
    OUT = os.path.join(ROOT, "data", "products"); os.makedirs(os.path.join(OUT, "detail"), exist_ok=True)
    for f in glob.glob(os.path.join(OUT, "detail", "*.json")): os.remove(f)
    # supplier-side aggregates per cluster
    sup_by_desc = {}
    inv = json.load(open(os.path.join(ROOT, "data/invoices/invoices.json")))
    sc = scope()
    for i in inv:
        if not (i["final"] and i["category"] == "nasima_purchase"): continue
        if not (sc["purchases_from"] <= i["iso_date"] <= sc["purchases_to"]): continue
        for x in i["lines"]:
            if x.get("non_merch") or not x["desc"].strip(): continue
            d = sup_by_desc.setdefault((x["desc"], i["supplier"]), {"units": 0.0, "amount": 0.0})
            d["units"] += x["qty"]; d["amount"] += x["amount"]
    cl_of_desc = {m: ci for ci, c in enumerate(clusters) for m in c["members"]}
    # products: one per purchase cluster (anchor); Amazon titles join at high/medium
    prods = {}
    def newp(key, name, a):
        prods[key] = {"key": key, "name": name, "size": a["size"], "gender": a["gender"], "set": a["set"], "kind": a["kind"],
                      "amazon": [], "supplier": [], "candidates": []}
        return prods[key]
    for ci, c in enumerate(clusters):
        if not c["members"]: continue
        top = c["members"][0]
        p = newp(("c", ci), top, c["seed"])
        for m in c["members"]:
            for (desc, sup), v in sup_by_desc.items():
                pass
    sd_by_desc = collections.defaultdict(list)
    for (desc, sup), v in sup_by_desc.items(): sd_by_desc[desc].append((sup, v))
    for ci, c in enumerate(clusters):
        if not c["members"]: continue
        p = prods[("c", ci)]
        for m in c["members"]:
            for sup, v in sd_by_desc[m]:
                p["supplier"].append({"desc": m, "supplier": sup, "units": v["units"], "amount": round(v["amount"], 2)})
    for k, m in M.items():
        a = am[k]; rec = {"title": k, "skus": sorted(a["skus"]), "units": a["units"], "sales": round(a["sales"], 2), "tier": m["tier"],
                          "note": m["note"], "refund_rows": a["refund_rows"], "refund_amt": round(a["refund_amt"], 2), "first": a["first"], "last": a["last"]}
        if m["tier"] in ("high", "medium"):
            prods[("c", m["best"]["ci"])]["amazon"].append(rec)
        else:
            p = newp(("a", k), k, A[k]); p["amazon"].append(rec)
            if m["best"]:
                c = clusters[m["best"]["ci"]]
                p["candidates"].append({"supplier_desc": c["members"][0], "why": m["note"] or "partial name match", "small": m["best"]["small"], "size_match": m["best"]["size"]})
    plist = []
    for key, p in prods.items():
        p["sold_units"] = sum(x["units"] for x in p["amazon"]); p["sold_sales"] = round(sum(x["sales"] for x in p["amazon"]), 2)
        p["sourced_units"] = sum(x["units"] for x in p["supplier"]); p["sourced_amount"] = round(sum(x["amount"] for x in p["supplier"]), 2)
        p["refund_rows"] = sum(x["refund_rows"] for x in p["amazon"]); p["refund_amt"] = round(sum(x["refund_amt"] for x in p["amazon"]), 2)
        tiers = {x["tier"] for x in p["amazon"]}
        if p["supplier"] and p["amazon"] and tiers <= {"high", "medium"}:
            p["status"] = "matched_high" if tiers == {"high"} else "matched_probable"
        elif p["supplier"] and not p["amazon"]: p["status"] = "sourced_not_sold"
        elif p["amazon"] and "low" in tiers: p["status"] = "review"
        else: p["status"] = "sold_no_invoice"
        plist.append(p)
    plist.sort(key=lambda p: (-p["sold_units"], -p["sourced_units"], p["name"]))
    for n, p in enumerate(plist, 1): p["id"] = "P%04d" % n
    # drill-down rows ------------------------------------------------------
    title_pid = {x["title"]: p["id"] for p in plist for x in p["amazon"]}
    desc_pid = {}
    for p in plist:
        for x in p["supplier"]: desc_pid[x["desc"]] = p["id"]
    sold = collections.defaultdict(list); refs = collections.defaultdict(list); buys = collections.defaultdict(list)
    for f in sorted(glob.glob(os.path.join(ROOT, "data/amazon/lines/*.json"))):
        for r in json.load(open(f)):
            if not (sc["sales_from"] <= r["d"] <= sc["sales_to"]): continue
            pid = title_pid.get(r["desc"])
            if not pid: continue
            if r["type"] == "Order": sold[pid].append([r["d"], r["order"], r["qty"], r["sales"], r["src"], r["line"]])
            elif r["type"] == "Refund": refs[pid].append([r["d"], r["order"], r["total"], r["src"], r["line"]])
    for i in inv:
        if not (i["final"] and i["category"] == "nasima_purchase"): continue
        if not (sc["purchases_from"] <= i["iso_date"] <= sc["purchases_to"]): continue
        for x in i["lines"]:
            pid = desc_pid.get(x["desc"])
            if pid and not x.get("non_merch"):
                buys[pid].append([i["iso_date"], i["supplier"], i["number"], x["qty"], x["price"], x["amount"], i["file"], x["page"], x["desc"]])
    SH = 40
    for si in range(0, len(plist), SH):
        shard = {}
        for p in plist[si:si + SH]:
            shard[p["id"]] = {"sold": sorted(sold[p["id"]]), "refunds": sorted(refs[p["id"]]), "bought": sorted(buys[p["id"]])}
        json.dump(shard, open(os.path.join(OUT, "detail", "%03d.json" % (si // SH)), "w"), separators=(",", ":"))
    slim = []
    for p in plist:
        slim.append({k: p[k] for k in ("id", "name", "size", "gender", "set", "kind", "status", "sold_units", "sold_sales", "sourced_units",
                                       "sourced_amount", "refund_rows", "refund_amt", "amazon", "supplier", "candidates")})
    json.dump(slim, open(os.path.join(OUT, "products.json"), "w"), separators=(",", ":"))
    # summary
    st = collections.Counter(); su = collections.Counter(); ss = collections.Counter()
    for p in plist:
        st[p["status"]] += 1; su[p["status"]] += p["sold_units"]; ss[p["status"]] += p["sourced_units"]
    tot_sold = sum(p["sold_units"] for p in plist); tot_src = sum(p["sourced_units"] for p in plist)
    summ = {"products": len(plist), "shard_size": SH, "status_counts": dict(st), "sold_units_by_status": {k: int(v) for k, v in su.items()},
            "sourced_units_by_status": {k: int(v) for k, v in ss.items()}, "total_sold_units": int(tot_sold), "total_sourced_units": int(tot_src),
            "amazon_titles": len(A), "supplier_descriptions": len(P)}
    json.dump(summ, open(os.path.join(OUT, "summary.json"), "w"), indent=1)
    return summ

if __name__ == "__main__":
    print(json.dumps(build(), indent=1))
