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
    "Mercedes-Benz": ["MERCEDES-BENZ", "MERCEDES BENZ", "MERCEDES"],
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
    "MG": ["MG"],
}
_SIMPLE = """
TOYOTA NISSAN SUZUKI MAZDA MITSUBISHI HONDA ISUZU HINO SUBARU LEXUS DAIHATSU
KIA FORD CHEVROLET JEEP DODGE RAM GMC CADILLAC TESLA
PEUGEOT RENAULT CITROEN DACIA OPEL FIAT SKODA SEAT AUDI BMW PORSCHE VOLVO
IVECO MAN DAF SCANIA
CHANGAN JAC JETOUR CHERY GEELY BYD HAVAL TANK EXEED OMODA JAECOO SOUEAST
FOTON SHACMAN FAW JMC BAIC BAW MAXUS WULING BAOJUN DAYUN KAIYI KARRY SWM ZOTYE
LIFAN HAIMA BRILLIANCE JINBEI HONGQI BESTUNE FORTHING LEAPMOTOR ZEEKR AVATR
NETA XPENG NIO DEEPAL ROX JETTA GAC TRUMPCHI HIGER YUTONG ZHONGTONG ANKAI
SANY XCMG LIUGONG LONKING SDLG SHANTUI ZOOMLION SINOMACH SUNWARD
CATERPILLAR KOMATSU JCB CASE BOBCAT KUBOTA LIEBHERR HITACHI KOBELCO TEREX
MANITOU HYSTER YALE TCM HELI HANGCHA
TATA MAHINDRA EICHER BAJAJ TVS HERO FORCE
YAMAHA KAWASAKI HAOJUE HAOJIN DAYANG LONCIN ZONGSHEN APSONIC SANYA
PROTON PERODUA
"""
BRANDS: dict[str, str] = {}
for canon, aliases in _BRAND_ALIASES.items():
    for a in aliases:
        BRANDS[a] = canon
for w in _SIMPLE.split():
    BRANDS.setdefault(w, w.title() if len(w) > 3 else w)
# Les plus longs d'abord (« MARUTI SUZUKI » avant « SUZUKI »).
_BRAND_KEYS = sorted(BRANDS, key=len, reverse=True)
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
            return brand
    for v in vins or []:
        if len(v) == 17 and v[:3] in WMI_BRANDS:
            return WMI_BRANDS[v[:3]]
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
