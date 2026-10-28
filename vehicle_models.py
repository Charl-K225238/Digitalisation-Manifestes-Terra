"""
Marques / modèles véhicules — module commun aux parseurs MOL / NYK / EUKOR.

Ordre de détection de la marque (le premier qui répond gagne) :
  1. Label explicite « BRAND: X » de la description.
  2. Marque connue (liste élargie BRANDS) citée dans la description.
  3. Mot commun au chargeur et à la description (ex. chargeur
     « KAIFENG JETOUR AUTOMOBILE » + description « JETOUR X70 ») : couvre une
     marque absente de la liste mais bien mentionnée.
  4. Chargeur connu (SHIPPER_BRANDS), puis préfixe constructeur du VIN (WMI).

Modèles : un B/L peut déclarer plusieurs modèles (« 30 UNITS OF JETOUR X70PLUS,
19 UNITS OF JETOUR G700 »). Sans tableau VIN -> modèle, on rapproche les
quantités déclarées des groupes de VIN de même préfixe (8 premiers caractères :
même constructeur + même code véhicule). Rapprochement uniquement s'il est sans
ambiguïté ; sinon le modèle reste à vérifier (observation), jamais deviné.
"""
from __future__ import annotations

import re
from collections import Counter

# Nom canonique affiché ; alias éventuels à droite.
_BRAND_ALIASES = {
    "Mercedes": ["MERCEDES-BENZ", "MERCEDES BENZ", "MERCEDES"],
    "MAN": ["MAN", "M.A.N."],
    "Land Rover": ["LAND ROVER", "RANGE ROVER"],
    "Volkswagen": ["VOLKSWAGEN", "VW"],
    "Great Wall": ["GREAT WALL", "GWM"],
    "Maruti Suzuki": ["MARUTI SUZUKI", "MARUTI"],
    "Ashok Leyland": ["ASHOK LEYLAND"],
    "John Deere": ["JOHN DEERE"],
    "New Holland": ["NEW HOLLAND"],
    "King Long": ["KING LONG", "KINGLONG"],
    "Golden Dragon": ["GOLDEN DRAGON"],
    "Lynk & Co": ["LYNK & CO", "LYNK&CO"],
    "Sinotruk": ["SINOTRUK", "SINO TRUK", "CNHTC"],
    "Howo": ["HOWO"],
    "Dongfeng": ["DONGFENG", "DONG FENG", "DFAC"],
    "DFSK": ["DFSK"],
    "Develon": ["DEVELON"],
    "Doosan": ["DOOSAN"],
    "Hyundai": ["HYUNDAI"],
    "Kia": ["KIA"],
    "MG": ["MG"],
}
_SIMPLE = """
TOYOTA NISSAN SUZUKI MAZDA MITSUBISHI HONDA ISUZU HINO SUBARU LEXUS DAIHATSU
KIA FORD CHEVROLET JEEP DODGE RAM GMC CADILLAC TESLA
PEUGEOT RENAULT CITROEN DACIA OPEL FIAT SKODA AUDI BMW PORSCHE VOLVO
IVECO MAN DAF SCANIA
CHANGAN JAC JETOUR CHERY GEELY BYD HAVAL EXEED OMODA JAECOO SOUEAST
FOTON SHACMAN FAW JMC BAIC BAW MAXUS WULING BAOJUN DAYUN KAIYI KARRY SWM ZOTYE
LIFAN HAIMA BRILLIANCE JINBEI HONGQI BESTUNE FORTHING LEAPMOTOR ZEEKR AVATR
XPENG DEEPAL JETTA GAC TRUMPCHI HIGER YUTONG ZHONGTONG ANKAI
SANY XCMG LIUGONG LONKING SDLG SHANTUI ZOOMLION SINOMACH SUNWARD
CATERPILLAR KOMATSU JCB BOBCAT KUBOTA LIEBHERR HITACHI KOBELCO TEREX
MANITOU HYSTER YALE TCM HELI HANGCHA
TATA MAHINDRA EICHER BAJAJ TVS
YAMAHA KAWASAKI HAOJUE HAOJIN DAYANG LONCIN ZONGSHEN APSONIC SANYA
PROTON PERODUA
ACURA INFINITI GENESIS LINCOLN BUICK CHRYSLER SSANGYONG KGM MINI SMART
BELL LOVOL CIMC KAMAZ
"""
BRANDS: dict[str, str] = {}
for canon, aliases in _BRAND_ALIASES.items():
    for a in aliases:
        BRANDS[a] = canon
# Acronymes en majuscules ; noms de marque en casse titre (« Kia », « Toyota »).
_ACRONYMS = {"BMW", "DAF", "MAN", "GMC", "JAC", "BYD", "MG", "FAW", "BAW", "JMC", "BAIC", "GAC",
             "SWM", "XCMG", "SDLG", "JCB", "TCM", "TVS", "KGM", "CIMC", "DFSK", "GWM", "VW"}
for w in _SIMPLE.split():
    BRANDS.setdefault(w, w if w in _ACRONYMS else w.title())
# Les plus longs d'abord (« MARUTI SUZUKI » avant « SUZUKI »).
_BRAND_KEYS = sorted(BRANDS, key=len, reverse=True)


def canon(brand: str) -> str:
    """Nom canonique d'une marque (même casse partout : liste, VIN, chargeur)."""
    return BRANDS.get((brand or "").upper(), brand or "")
_BRAND_RE = re.compile(r"(?<![A-Z0-9])(" + "|".join(re.escape(k) for k in _BRAND_KEYS) + r")(?![A-Z0-9])")

SHIPPER_BRANDS = [
    ("HYUNDAI GLOVIS", "Hyundai"), ("HYUNDAI MOTOR", "Hyundai"),
    ("HD CONSTRUCTION EQUIPMENT", "Develon"), ("JOHN DEERE", "John Deere"),
    ("ANHUI JIANGHUAI", "JAC"), ("SAIC MOTOR", "MG"), ("CHONGQING CHANGAN", "Changan"),
    ("GREAT WALL", "Great Wall"), ("BEIQI FOTON", "Foton"), ("CHINA NATIONAL HEAVY DUTY", "Sinotruk"),
    ("SHAANXI AUTOMOBILE", "Shacman"), ("ZHENGZHOU YUTONG", "Yutong"), ("XIAMEN KING LONG", "King Long"),
    ("MARUTI SUZUKI", "Maruti Suzuki"), ("TOYOTA TSUSHO", "Toyota"),
]
# Préfixes constructeur (WMI) — filet de sécurité quand rien n'est écrit.
WMI_BRANDS = {
    "LS4": "Changan", "LS5": "Changan", "LS7": "Changan", "LJ1": "JAC", "LJ8": "JAC",
    "LSJ": "MG", "LVT": "Soueast", "LVV": "Chery", "LVM": "Chery", "LGX": "BYD", "LC0": "BYD",
    "LGW": "Great Wall", "LB3": "Geely", "LVA": "Foton", "LVB": "Foton", "LZZ": "Sinotruk",
    "LZG": "Shacman", "LZY": "Yutong", "LFV": "Volkswagen", "LGB": "Dongfeng",
    "LDY": "Zhongtong", "LGW": "Great Wall", "LVA": "Foton",
    # Véhicules d'origine américaine / japonaise / coréenne (fréquents en Grimaldi)
    "KM8": "Hyundai", "5NM": "Hyundai", "5NP": "Hyundai", "KMH": "Hyundai",
    "KND": "Kia", "5XY": "Kia", "5XX": "Kia", "3KP": "Kia",
    "5J6": "Honda", "1HG": "Honda", "2HG": "Honda", "2HK": "Honda", "SHH": "Honda",
    "5J8": "Acura", "19U": "Acura", "2T3": "Toyota", "4T1": "Toyota", "4T3": "Toyota",
    "5TD": "Toyota", "5TF": "Toyota", "JTN": "Toyota", "JTJ": "Lexus", "2T2": "Lexus",
    "JA4": "Mitsubishi", "JA3": "Mitsubishi", "JM1": "Mazda", "JM3": "Mazda",
    "1N4": "Nissan", "5N1": "Nissan", "3N1": "Nissan", "JN1": "Nissan",
    "1C6": "Ram", "3C6": "Ram", "1C4": "Jeep", "1FM": "Ford", "1FT": "Ford", "3FA": "Ford",
    "1GN": "Chevrolet", "1G1": "Chevrolet", "3GN": "Chevrolet", "KL7": "Chevrolet",
    "5UX": "BMW", "WBA": "BMW", "WBS": "BMW", "W1K": "Mercedes", "W1N": "Mercedes",
    "4JG": "Mercedes", "WDC": "Mercedes", "WVW": "Volkswagen", "WVG": "Volkswagen",
    "3VW": "Volkswagen", "JF2": "Subaru", "4S4": "Subaru", "VF6": "Renault",
    "YV1": "Volvo", "YV4": "Volvo", "1T0": "John Deere", "1DW": "John Deere",
    "1T8": "John Deere", "CAT": "Caterpillar", "KMT": "Komatsu", "AEB": "Bell",
    "TYB": "Mitsubishi", "JL6": "Mitsubishi", "JN8": "Nissan", "L5E": "Zoomlion",
    "KMH": "Hyundai", "KMJ": "Hyundai", "KMF": "Hyundai", "KNA": "Kia", "KNC": "Kia",
    "JTD": "Toyota", "JTE": "Toyota", "JTF": "Toyota", "JTM": "Toyota", "AHT": "Toyota",
    "MR0": "Toyota", "MHF": "Toyota", "JN1": "Nissan", "JN8": "Nissan", "MA3": "Maruti Suzuki",
    "JS2": "Suzuki", "JS3": "Suzuki", "JAA": "Isuzu", "MPA": "Isuzu", "JMB": "Mitsubishi",
    "MMB": "Mitsubishi", "WDB": "Mercedes-Benz", "WDD": "Mercedes-Benz", "WMA": "MAN",
    "XLR": "DAF", "YS2": "Scania", "YV2": "Volvo", "ZCF": "Iveco", "VF1": "Renault",
    "VF3": "Peugeot", "MAT": "Tata", "MA1": "Mahindra", "MB1": "Ashok Leyland",
}
_GENERIC_WORDS = {
    "CO", "LTD", "LIMITED", "INC", "CORP", "CORPORATION", "COMPANY", "GROUP", "HOLDINGS",
    "AUTOMOBILE", "AUTOMOBILES", "AUTOMOTIVE", "MOTOR", "MOTORS", "AUTO", "SALES", "TRADE",
    "TRADING", "INTERNATIONAL", "IMPORT", "EXPORT", "INDUSTRY", "INDUSTRIAL", "MACHINERY",
    "EQUIPMENT", "VEHICLE", "VEHICLES", "TECHNOLOGY", "SUPPLY", "CHAIN", "LOGISTICS",
    "CHINA", "HONG", "KONG", "SHANGHAI", "BEIJING", "TIANJIN", "ANHUI", "FUJIAN", "HENAN",
    "SHANDONG", "JIANGSU", "ZHEJIANG", "CHONGQING", "GUANGZHOU", "SHENZHEN", "XIAMEN",
    "THE", "AND", "OF", "NEW", "USED", "UNITS", "UNIT",
}

# Fin de nom de modèle (le modèle s'arrête avant ces mots).
_MODEL_STOP = {
    "SEATS", "SEAT", "UNITS", "UNIT", "VERSION", "FUEL", "PASSENGER", "CAR", "CARS", "SUV",
    "VEHICLE", "VEHICLES", "VEHICULES", "HS", "MODEL", "NEW", "USED", "COLOUR", "COLOR",
    "VIN", "CHASSIS", "YEAR", "BRAND", "SECOND", "GENERATION", "AND", "WITH", "LHD", "RHD",
}
_SEG_RE = re.compile(r"(?:^|\s)(\d+)\s+(?:UNITS?\s+OF\s+)?", re.I)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").upper()).strip()


def find_brand(desc: str, shipper: str = "", vins: list[str] | None = None) -> str:
    d = _norm(desc)
    lab = re.search(r"\bBRAND\s*:\s*([A-Z][A-Z0-9&\- ]{1,25}?)(?:\s*$|\s*[,/;]|\s+(?:COLOU?R|HS|VIN|MODEL)\b)", d)
    if lab:
        b = lab.group(1).strip()
        return BRANDS.get(b, b.title() if len(b) > 3 else b)
    m = _BRAND_RE.search(d)
    if m:
        return BRANDS[m.group(1)]
    s = _norm(shipper)
    for w in re.findall(r"[A-Z]{3,}", s):
        if w not in _GENERIC_WORDS and re.search(rf"(?<![A-Z]){w}(?![A-Z])", d):
            return w.title()
    for key, brand in SHIPPER_BRANDS:
        if key in s:
            return canon(brand)
    for v in vins or []:
        if len(v) == 17 and v[:3] in WMI_BRANDS:
            return canon(WMI_BRANDS[v[:3]])
    return ""


_LEAD_SKIP = {"LHD", "RHD", "PASSENGER", "CAR", "PICK", "UP", "PICKUP", "FUEL", "SUV", "NEW", "BRAND"}


def _model_after(tokens: list[str], brand_keys: set[str]) -> str:
    out = []
    for t in tokens:
        tc = t.strip(".,;:()")
        if not out and tc in _LEAD_SKIP:
            continue
        if not tc or tc == "/" or tc in _MODEL_STOP or tc in brand_keys or re.fullmatch(r"\d+", tc):
            break
        out.append(tc)
        if len(out) == 3 or t.endswith((",", ";", ")")):
            break
    return " ".join(out)


def model_groups(desc: str, brand: str) -> list[tuple[int | None, str]]:
    """[(quantité|None, modèle)] cités après la marque. Quantité = nombre qui
    précède (« 30 UNITS OF JETOUR X70PLUS ») ; None si la marque est citée sans
    quantité (« SOUEAST S05 SOUEAST S07 »). Doublons fusionnés."""
    if not brand:
        return []
    keys = {k for k, v in BRANDS.items() if v == brand} | {brand.upper()}
    d = _norm(desc.replace("/", " / "))
    toks = d.split()
    out: list[tuple[int | None, str]] = []
    for i, t in enumerate(toks):
        if t.strip(".,;:") not in keys:
            # marques en 2 mots (« JOHN DEERE »)
            if not any(" ".join(toks[i:i + 2]).strip(".,;:") == k for k in keys if " " in k):
                continue
            j = i + 2
        else:
            j = i + 1
        # « MODEL:CHANGAN X5PLUS » / « BRAND:CHANGAN » : labels traités à part
        if i and toks[i - 1].endswith("BRAND:"):
            continue
        model = _model_after(toks[j:], keys)
        if not model:
            continue
        qty = None
        back = toks[max(0, i - 3):i]
        if len(back) >= 2 and back[-2:] in (["UNITS", "OF"], ["UNIT", "OF"]) and len(back) == 3 and back[0].isdigit():
            qty = int(back[0])
        elif back and back[-1].isdigit():
            qty = int(back[-1])
        out.append((qty, model))
    # explicite « MODEL: X » prioritaire quand il est seul
    lab = re.search(r"\bMODEL\s*:\s*(?:" + "|".join(re.escape(k) for k in keys) + r")\s+([A-Z0-9][A-Z0-9\-]*)", d)
    if lab:
        return [(None, lab.group(1))]
    seen, uniq = set(), []
    for q, m in out:
        if (q, m) not in seen:
            seen.add((q, m))
            uniq.append((q, m))
    # Même modèle cité sans puis avec quantité -> garder la version quantifiée
    quantified = {m for q, m in uniq if q is not None}
    return [(q, m) for q, m in uniq if q is not None or m not in quantified]


def assign_models(chassis: list[str], groups: list[tuple[int | None, str]]):
    """-> (modele_par_chassis: dict, observation: str).
    1 modèle : tous les châssis. Plusieurs : rapprochement quantité déclarée
    <-> groupe de VIN (8 premiers caractères) s'il est unique, sinon
    observation « à vérifier »."""
    if not groups:
        return {}, ""
    names = [m for _, m in groups]
    if len(set(names)) == 1:
        return {c: names[0] for c in chassis}, ""
    listing = ", ".join(f"{q} {m}" if q else m for q, m in groups)
    obs = f"plusieurs modeles sur le B/L ({listing}) - verifier le modele"
    qtys = [q for q, _ in groups]
    vin_groups = Counter(c[:8] for c in chassis if len(c) == 17)
    if all(q for q in qtys) and len(set(qtys)) == len(qtys) and sum(qtys) == len(chassis) \
            and sorted(vin_groups.values()) == sorted(qtys) and len(set(vin_groups.values())) == len(vin_groups):
        by_qty = {q: m for q, m in groups}
        pref_model = {p: by_qty[n] for p, n in vin_groups.items()}
        return {c: pref_model[c[:8]] for c in chassis}, ""
    return {c: "" for c in chassis}, obs



# ---------------------------------------------------------------------------
# Résolution véhicule par véhicule (manifestes à description libre, Grimaldi)
# ---------------------------------------------------------------------------
_BOILER_RE = re.compile(
    r"TRANSSHIPMENT|SERVICE BILL|VOYAGE\s|GOODS ONLY|SHIPPER|ON BEHALF|INVOICE|TEL\b|TELEPHONE|@|"
    r"FREIGHT|NOTIFY|CONSIGNEE|CARRIER|LIABILITY|RESPONSIBILITY|CONTINUE ON NEXT", re.I)
_GENERIC_MODEL = {"TRUCK", "TRUCKS", "BUS", "BUSES", "TRACTOR", "TRAILER", "EXCAVATOR", "LOADER",
                  "VAN", "PICKUP", "SUV"}
_DROP_WORDS = {"CARS", "CAR", "VEHICLES", "VEHICLE", "VEHICLE(S)", "UNITS", "UNIT", "NEW", "USED",
               "BRAND", "MARKED", "OF", "(S)", "UNPACKED", "BRANDNEW"}
_CUT_RE = re.compile(r"\b(VIN|HS\s*CODE|AES|MODEL\s*(?:NO\.?)?\s*:|ENGINE|IN TRANSIT|S/N|SERIAL|REG\s*:|TITLE|"
                     r"YEAR|COLOU?R|PIN|MSO|AS PER|SALE|PRODUCT)\b.*$", re.I)
_MODEL_LABEL_RE = re.compile(r"\bMODEL(?:\s*NO\.?)?\s*[:.]?\s*([A-Z0-9][A-Z0-9\-\.]*\d[A-Z0-9\-\.]*)", re.I)
_UNBRANDED_HEAD_RE = re.compile(r"^([A-Z][A-Z0-9\-]{2,})\s+(?:CARS|VEHICLES|SUVS?)$")
_UNIT_MODEL_RE = re.compile(r"^\d+\s+UNITS?\s+MODEL\s*:?\s*([A-Z0-9][A-Z0-9\-\.]*\d[A-Z0-9\-\.]*)$")
_CODE_TOKEN_RE = re.compile(r"(?=.*\d)(?=.*[A-Z])[A-Z0-9][A-Z0-9\-\.]{1,11}")
_CODE_LINE_RE = re.compile(r"^(?=.*\d)[A-Z0-9][A-Z0-9\-\.]{2,}(?:\s+[A-Z0-9]{1,3})?$")


def _is_vin(tok: str) -> bool:
    return bool(re.fullmatch(r"(?=.*[A-HJ-NPR-Z])(?=.*\d)[A-HJ-NPR-Z0-9]{17}", tok or ""))


def _model_from_line(line: str, key_end: int, first_brand: str = "") -> str:
    rest = _CUT_RE.sub("", line[key_end:])
    rest = re.split(r"[,;]| / ", rest)[0]
    toks = []
    for t in rest.split():
        tc = t.strip(".:()")
        if not tc or tc.upper() in _DROP_WORDS or _is_vin(tc) or re.fullmatch(r"(19|20)\d\d", tc):
            continue
        if _BRAND_RE.fullmatch(tc.upper()):        # seconde marque sur la ligne
            if first_brand and canon(tc) in _group(first_brand):
                toks.append(tc)                       # gamme du même constructeur (HOWO)
                continue
            break
        if tc.upper() in ("SEATS", "SEATER", "SEAT", "PLACES"):
            # « BUS 25 SEATS » : le nombre de places n'est pas le modèle
            while toks and re.fullmatch(r"\d+", toks[-1]):
                toks.pop()
            break
        toks.append(tc)
    return " ".join(toks[:5]).upper()


def _headings(lines: list[str]):
    """Repère les lignes « marque + modèle » -> [(index, marque, modèle)]."""
    out = []
    for i, raw in enumerate(lines):
        line = _norm(raw)
        if not line or _BOILER_RE.search(line):
            continue
        m = _BRAND_RE.search(line)
        if not m:
            um = _UNBRANDED_HEAD_RE.match(line)
            if um and um.group(1) not in _DROP_WORDS:
                out.append((i, None, um.group(1)))      # marque déduite du VIN
            elif _UNIT_MODEL_RE.match(line):
                out.append((i, None, _UNIT_MODEL_RE.match(line).group(1)))   # « 1 UNIT MODEL ZTC600V-1 »
            continue
        brand = BRANDS[m.group(1)]
        model = _model_from_line(line, m.end(), brand)
        # Modèle générique (« BUS », « TRUCK ») ou vide : code modèle explicite
        # juste après (« MODEL NO.: ZK6729D2 », ligne « LCK6125EV »).
        for k, nxt in enumerate(lines[i + 1:i + 4]):
            n = _norm(nxt)
            if _BRAND_RE.search(n) or _UNIT_MODEL_RE.match(n):
                break
            lm = _MODEL_LABEL_RE.search(n)
            if lm and re.fullmatch(r"(19|20)\d\d", lm.group(1)):
                lm = None                               # « MODEL 2023 » = année, pas un modèle
            if lm and "/" not in lm.group(1):
                code = lm.group(1).rstrip(".,")
                if code not in model:
                    model = f"{code} {model}".strip()   # « SQR6460T1KTBD DASHING »
                break
            if model and model not in _GENERIC_MODEL:
                continue
            first = n.split()[0].rstrip(".,") if n.split() else ""
            if k == 0 and (_CODE_LINE_RE.match(n) or (_CODE_TOKEN_RE.fullmatch(first) and len(n.split()) <= 3)) \
                    and not _is_vin(first) and not re.fullmatch(r"[\d\s]+", first):
                code = n if _CODE_LINE_RE.match(n) else first
                model = f"{code} {model}".strip()
                break
        out.append((i, brand, model))
    return out


def _wmi(c: str):
    return canon(WMI_BRANDS[c[:3]]) if _is_vin(c) and c[:3] in WMI_BRANDS else None


def _same_maker(wmi_brand, brand) -> bool:
    if not wmi_brand or not brand:
        return True                       # pas d'information contraire
    return brand in _group(wmi_brand)


def _pick_model(models: set, n_chassis: int) -> str:
    """Un seul modèle -> lui. Plusieurs : « ACCENT » / « ACCENT SE » (l'un
    préfixe de l'autre) -> le plus complet ; un seul spécifique à côté d'un
    générique (« TRUCK ») et un seul véhicule -> le spécifique. Sinon vide."""
    ms = sorted(models, key=len)
    if not ms:
        return ""
    if len(ms) == 1:
        return ms[0]
    if all(ms[-1].startswith(x) for x in ms[:-1]):
        return ms[-1]
    spec = [x for x in ms if x not in _GENERIC_MODEL]
    if len(spec) == 1 and n_chassis == 1:
        return spec[0]
    return ""


def resolve_per_chassis(desc_lines: list[str], chassis: list[str]) -> dict:
    """{châssis: (marque, modèle)} pour les châssis résolus sans ambiguïté.
    1. VIN écrit dans la description -> titre marque/modèle qui le précède,
       sauf si le préfixe constructeur du VIN le contredit.
    2. Sinon marque par préfixe VIN (WMI) parmi les marques citées, avec son
       modèle s'il est unique pour cette marque dans le B/L.
    3. Sinon, une seule marque citée (non contredite par le VIN) -> elle.
    Un châssis non résolu est absent du résultat (jamais deviné)."""
    lines = [l for l in desc_lines if l is not None]
    heads = _headings(lines)
    res = {}
    named = {b for _, b, _ in heads if b}
    for idx, raw in enumerate(lines):
        up = _norm(raw)
        hs = [h for h in heads if h[0] <= idx]
        if not hs:
            continue
        _, b, mdl = hs[-1]
        for c in chassis:
            if c in res or c not in up:
                continue
            w = _wmi(c)
            if b is None:                             # titre sans marque (« POER CARS »)
                if len(named) == 1:
                    bb = next(iter(named))
                    if len(named) > 1 and not _same_maker(w, bb):
                        bb = None
                else:
                    cand = [x for x in named if _same_maker(w, x)] if w else []
                    bb = cand[0] if len(cand) == 1 else w
                if bb:
                    res[c] = (bb, mdl)
            elif len(named) <= 1 or _same_maker(w, b):
                res[c] = (b, mdl)
    by_brand: dict[str, set] = {}
    for _, b, mdl in heads:
        if b:
            by_brand.setdefault(b, set())
            if mdl:
                by_brand[b].add(mdl)
    pending = {}
    for c in chassis:
        if c in res:
            continue
        w = _wmi(c)
        b = None
        if len(by_brand) == 1:
            b = next(iter(by_brand))              # une seule marque citée : le texte prime
        elif w:
            exact = [x for x in by_brand if x == w]
            cands = exact or [x for x in by_brand if _same_maker(w, x)]
            b = cands[0] if len(cands) == 1 else None
        if b:
            pending[c] = b
        elif w and not by_brand:
            res[c] = (w, "")
    per_brand = Counter(pending.values())
    for c, b in pending.items():
        res[c] = (b, _pick_model(by_brand.get(b, set()), per_brand[b]))
    # Modèle encore vide : label « MODEL: X » unique dans un B/L mono-marque
    # (« 17UNITSFOTONMINI-TRUCK / MODEL:BJ1030V4JV2-BH »).
    labels = {m.group(1).upper() for l in lines for m in _MODEL_LABEL_RE.finditer(_norm(l))
              if "/" not in m.group(1) and not re.fullmatch(r"(19|20)\d\d", m.group(1))}
    brands_res = {b for b, _ in res.values()}
    if len(labels) == 1 and len(brands_res) == 1 and len(named) <= 1:
        lab = next(iter(labels))
        for c, (b, mdl) in list(res.items()):
            if not mdl:
                res[c] = (b, lab)
    return res


# Constructeur (WMI) -> marque commerciale citée dans les manifestes
_BRAND_FAMILY = {"Great Wall": "Haval", "Chery": "Jetour", "Lexus": "Toyota", "Acura": "Honda"}
# Groupes constructeurs : un VIN d'une marque du groupe ne contredit pas une
# autre marque du même groupe (Accent assemblée par Kia, Infiniti sur VIN
# Nissan, Jetour sur VIN Soueast/Chery, gamme HOWO de Sinotruk…).
_MAKER_GROUPS = [
    {"Great Wall", "Haval"}, {"Chery", "Jetour", "Soueast", "Exeed", "Omoda", "Jaecoo"},
    {"Toyota", "Lexus"}, {"Honda", "Acura"}, {"Nissan", "Infiniti"},
    {"Hyundai", "Kia", "Genesis"}, {"Sinotruk", "Howo"}, {"Volkswagen", "Audi", "Skoda", "Jetta"},
    {"Mercedes", "Smart"}, {"BMW", "Mini"}, {"Ram", "Jeep", "Dodge", "Chrysler"},
    {"Chevrolet", "GMC", "Cadillac", "Buick"}, {"MG", "Maxus"},
]


def _group(b):
    for g in _MAKER_GROUPS:
        if b in g:
            return g
    return {b}
