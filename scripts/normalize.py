"""Description normaliser for perfume titles (Amazon titles and supplier invoice lines).
Extracts size (oz), set size, gender, concentration and the remaining 'name tokens'."""
import re, html, unicodedata

ML_TO_OZ = {5:0.2, 7:0.25, 7.5:0.25, 10:0.3, 15:0.5, 20:0.7, 25:0.8, 30:1.0, 40:1.4, 45:1.5, 50:1.7, 60:2.0, 75:2.5, 80:2.7,
            90:3.0, 100:3.4, 120:4.0, 125:4.2, 150:5.0, 175:6.0, 200:6.7, 250:8.4, 300:10.1, 236:8.0, 240:8.1, 118:4.0}
def ml_to_oz(ml):
    best = min(ML_TO_OZ, key=lambda k: abs(k - ml))
    return ML_TO_OZ[best] if abs(best - ml) <= max(2, best * 0.04) else round(ml / 29.57, 1)

CONC = [("edt", r"\b(edt|eau\s*d[eiu]\s*toil+e?tte?|eau de toilete|eau de toilet|toilette)\b"),
        ("edp", r"\b(edp|eau\s*d[eiu]\s*(parfum|perfume|parfun)|parfum|perfume spray)\b"),
        ("edc", r"\b(edc|eau\s*d[eiu]\s*cologne|cologne|col|splash)\b"),
        ("deo", r"\b(deo|deodorant|antiperspirant|anti-perspirant|a/p|dsp)\b"),
        ("ash", r"\b(after\s*shave|a/s|ash|aftershave)\b"),
        ("bodymist", r"\b(body\s*mist|body\s*spray|body\s*lotion|shower\s*gel|body\s*wash|lotion|powder|body\s*cream|dusting)\b")]
MALE = r"\b(masculin|masculine|men|mens|men's|man|male|homme|masculine|for him|boy|boys|\(m\)|m|him|pour lui|gents)\b"
FEMALE = r"\b(women|womens|women's|woman|female|femme|ladies|lady|feminine|for her|girl|girls|\(w\)|\(l\)|w|l|her|she)\b"
UNI = r"\b(unisex|u|both)\b"
STOP = set("""by for the and of de di du la le les el new in box boxed brand authentic authentique genuine sealed original
perfume perfumes fragrance fragrances cologne eau toilette parfum spray spr sp splash fluid fl ounce ounces oz ml
pour with w tester unboxed unbox without packaging packing item sample mini travel size pack a an to set gift pcs pc piece
pieces 100 percent impression edition ph pc2 pcs3 us usa ship usps ups fedex edt edp edc col deo scent women men mens womens
man woman deodorant antiperspirant homme masculin femme masculine feminine ladies unisex him her h wm g s c m l u sold sealed""".split())

VARIANTS = {"zero", "vip", "chill", "crush", "kicks", "he", "she", "wave", "soul", "intense", "extreme", "sport", "noir", "elixir", "absolute", "dark", "wild", "pure", "ii", "iii", "plus", "sexy", "light",
            "summer", "black", "blue", "red", "white", "gold", "silver", "night", "sunset", "sweet", "fresh", "ultra", "royal", "classic",
            "original", "legend", "spirit", "rouge", "bleu", "bleue", "eau", "love", "rose", "pink"}
PLAUSIBLE = {0.5, 1.0, 1.7, 2.0, 2.5, 3.0, 3.3, 3.4, 3.6, 4.0, 4.2, 5.0, 6.7, 8.0, 10.1}

def clean(t):
    t = html.unescape(t or "")
    t = unicodedata.normalize("NFKD", t); t = "".join(c for c in t if not unicodedata.combining(c))
    return t.lower()

def parse(desc):
    t = clean(desc)
    t = t.replace("&", " and ").replace("’", "'").replace("`", "'")
    t = re.sub(r"anti[\s-]*perspirant", "antiperspirant", t)
    t = re.sub(r"cool\s+water", "coolwater", t)
    t = re.sub(r"\b(stk|stick)\b", "stick", t)
    t = re.sub(r"\bd'?or\b", "dor", t)
    t = re.sub(r"\bevery\s+one\b", "everyone", t)
    for a_, b_ in (("blk", "black"), ("blck", "black"), ("krystal", "crystal"), ("kl", "karen low"), ("pnk", "pink"), ("wht", "white"),
                   ("mdnt", "midnight"), ("intens", "intense"), ("extrm", "extreme"), ("sung", "sung"), ("bleu", "blue")):
        t = re.sub(r"\b%s\b" % a_, b_, t)
    t = re.sub(r"\bsubtotal\b.*$", "", t)
    t = re.sub(r"(\d)(oz|ml)([a-z])", r"\1\2 \3", t)       # 3.0ozedt -> 3.0oz edt
    out = {"raw": desc}
    # size
    sizes = []
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*[- ]?\s*(fl\.?\s*oz|fluid\s*ounces?|ounces?|oz\.?|ml|milliliters?)\b", t):
        v = float(m[1]); unit = m[2]
        sizes.append(ml_to_oz(v) if unit.startswith(("ml", "milli")) else round(v, 1))
    # 'x.x spr' / 'x.x sp' / 'x.x edp' style without unit
    if not sizes:
        for m in re.finditer(r"(?<![\d.])(\d{1,2}\.\d)(?![\d.])\s*(?:spr|sp\b|edp|edt|edc|col|spl|deo|splash|spray)", t):
            sizes.append(round(float(m[1]), 1))
    if not sizes:
        m = re.search(r"(?<![\d.#])(\d{1,2}\.\d{1,2})\s*$", t.strip())
        if m: sizes.append(round(float(m[1]), 1))
    if not sizes:   # bare plausible fragrance size anywhere in the text (e.g. 'tres nuit 3.4 eau de toilette')
        for m in re.finditer(r"(?<![\d.#])(\d{1,2}\.\d)(?![\d.])", t):
            if round(float(m[1]), 1) in PLAUSIBLE: sizes.append(round(float(m[1]), 1)); break
    out["size"] = sizes[0] if sizes else None
    out["sizes"] = sizes
    # set
    setn = None
    m = re.search(r"(\d)\s*[- ]?\s*(?:pcs?|piece|pc)\b", t) or re.search(r"\b(\d)pcs?\b", t) or re.search(r"\b(\d)\s*pc\b", t)
    if m: setn = int(m[1])
    is_set = bool(setn) and setn > 1 or bool(re.search(r"\bset\b|gift set|w/\s*\d|\bw/\b|\bwith\b.*\b(lotion|gel|bag|body)\b|\bcoffret\b", t))
    out["set"] = is_set; out["setn"] = setn
    out["tester"] = bool(re.search(r"\btester\b|\bunboxed\b|without box|no box|w/o box|plain box|white box", t))
    # concentration (first match in text order)
    conc = None; best = 999
    for name, pat in CONC:
        m = re.search(pat, t)
        if m and m.start() < best: conc, best = name, m.start()
    out["conc"] = conc
    out["kind"] = "deo" if conc == "deo" else "ash" if conc == "ash" else "body" if conc == "bodymist" else "frag"
    if re.search(r"\bpowder\b|\blotion\b|\bgel\b|shower|body (wash|cream|mist|spray)", t) and not is_set: out["kind"] = "body"
    if re.search(r"\bstick\b|antiperspirant|deodorant", t) and not is_set: out["kind"] = "deo"
    # gender
    g = None
    tt = " " + t + " "
    mm, ff, uu = re.search(MALE, tt), re.search(FEMALE, tt), re.search(UNI, tt)
    if re.search(r"\bunisex\b", t): g = "U"
    elif mm and not ff: g = "M"
    elif ff and not mm: g = "W"
    elif mm and ff: g = "M" if mm.start() < ff.start() else "W"
    out["gender"] = g
    # name tokens
    n = re.split(r"\b(?:impression of|inspired by|version of|compare to|type of|similar to|alternative to|smells like)\b", t)[0]
    n = re.sub(r"(\d+(?:\.\d+)?)\s*[- ]?\s*(fl\.?\s*oz|fluid\s*ounces?|ounces?|oz\.?|ml|milliliters?)\b", " ", n)
    n = re.sub(r"[^a-z0-9' ]", " ", n)
    n = n.replace("'s", "").replace("'", "")
    drop_nums = {str(int(x)) for x in sizes if x == int(x)} | ({str(setn)} if setn else set())
    toks = [w for w in n.split() if w not in STOP and not re.fullmatch(r"\d+pcs?", w)
            and not (re.fullmatch(r"\d+(\.\d+)?", w) and (len(w) <= 2 or "." in w or w in drop_nums))]
    seen = []; [seen.append(w) for w in toks if w not in seen]
    out["tokens"] = seen
    return out
