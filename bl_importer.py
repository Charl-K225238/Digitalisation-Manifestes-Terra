"""
Génération du fichier d'import IPAKI « BL Importer » (70 colonnes) à partir d'un
manifeste brut — 4 formats : Chinese RoRo (XLSX/XLS), MOL ALIS (PDF),
Grimaldi (PDF), Hyundai Glovis (PDF scanné, OCR).

Principe : 1 ligne par véhicule (châssis), les informations du B/L étant
répétées sur chaque ligne (même structure que le modèle réel IPAKI).

Remplissage :
  - AUTOMATIQUE (déduit du manifeste, jamais deviné) : N° B/L, nature,
    pays de destination finale, POL (UNLOCODE si connu), nombre d'unités,
    volume/poids du B/L et de chaque véhicule, châssis, modèle, code
    véhicule (< / > 15 m³), commodity (neuf/occasion), mode de transport RR.
  - À COMPLÉTER PAR LES AGENTS (données de booking/référentiel IPAKI absentes
    du manifeste) : Call Number, SlotFile, Consignee (code client), Shipper,
    Forwarder... Ces colonnes restent vides ; `check_required()` liste ce qu'il
    reste à saisir.

Module sans dépendance Streamlit (testable seul).
"""
from __future__ import annotations

import io
import json
import os
import re
import tempfile
from collections import OrderedDict
from datetime import datetime

import pandas as pd

import classification_vehicules as clsveh

_TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "assets", "bl_importer_template.json")
with open(_TEMPLATE_PATH, encoding="utf-8") as _f:
    _TEMPLATE = json.load(_f)

#: Les 70 colonnes du modèle IPAKI, dans l'ordre exact.
BL_IMPORTER_COLUMNS: list = list(_TEMPLATE["columns"])
#: Contenu de l'onglet « Description » du modèle (lignes brutes).
DESCRIPTION_ROWS: list = _TEMPLATE["description"]

COMMODITY_NEUF = "VEHICULES NEUFS, VOITURES NEUVES, CAMION"
COMMODITY_USAGE = "VEHICULES USAGES,VOITURES OCCASIONS"

# Champs obligatoires (colonne « Required » de l'onglet Description du modèle)
# qui ne peuvent PAS être déduits d'un manifeste → à saisir par les agents.
REQUIRED_BOOKING_FIELDS = [
    "Call Number", "SlotFile",
]
# Champs obligatoires qui doivent être remplis automatiquement : si vides, c'est
# une donnée manquante dans le manifeste (signalée à l'agent).
REQUIRED_AUTO_FIELDS = [
    "BL Number", "ImportExport", "Final Destination Country", "TransportMode",
    "BLItem YardItemType", "BLItem YardItemNumber", "BLItem YardItemCode",
    "BLItem Commodity", "BLItem Commodity Volume", "BLItem Commodity Weight",
    "BLItem ImportExport", "BLItem Commodity HazardousClass",
]

# ---------------------------------------------------------------------------
# Référentiel ports → UNLOCODE (uniquement des codes certains ; un port
# inconnu reste vide et est signalé, jamais inventé).
# ---------------------------------------------------------------------------
_PORT_UNLOCODE = [
    ("ANTWERP", "BEANR"), ("ANVERS", "BEANR"), ("ZEEBRUGGE", "BEZEE"),
    ("HAMBURG", "DEHAM"), ("BREMERHAVEN", "DEBRV"),
    ("TILBURY", "GBTIL"), ("SOUTHAMPTON", "GBSOU"),
    ("ROTTERDAM", "NLRTM"), ("AMSTERDAM", "NLAMS"),
    ("LE HAVRE", "FRLEH"), ("MARSEILLE", "FRMRS"), ("SETE", "FRSET"), ("SÈTE", "FRSET"),
    ("BARCELONA", "ESBCN"), ("VALENCIA", "ESVLC"), ("VIGO", "ESVIG"),
    ("GENOA", "ITGOA"), ("GENOVA", "ITGOA"), ("LIVORNO", "ITLIV"),
    ("SALERNO", "ITSAL"), ("CIVITAVECCHIA", "ITCVV"),
    ("DUBAI", "AEDXB"), ("JEBEL ALI", "AEJEA"),
    ("ENNORE", "INENR"), ("PIPAVAV", "INPAV"), ("CHENNAI", "INMAA"),
    ("MUNDRA", "INMUN"), ("NHAVA SHEVA", "INNSA"), ("MUMBAI", "INBOM"),
    ("DURBAN", "ZADUR"),
    ("TIANJIN", "CNTSN"), ("XINGANG", "CNTXG"), ("YANTAI", "CNYTN"),
    ("SHANGHAI", "CNSHA"), ("NINGBO", "CNNGB"), ("QINGDAO", "CNTAO"),
    ("DALIAN", "CNDLC"),
    ("MOKPO", "KRMOK"), ("PYEONGTAEK", "KRPTK"), ("ULSAN", "KRUSN"),
    ("INCHEON", "KRINC"),
    ("YOKOHAMA", "JPYOK"), ("NAGOYA", "JPNGO"), ("KOBE", "JPUKB"),
    ("ABIDJAN", "CIABJ"), ("DAKAR", "SNDKR"), ("COTONOU", "BJCOO"),
    ("LAGOS", "NGLOS"), ("TEMA", "GHTEM"),
]

_NATURE_MAP = {"IMPORT": "Import", "EXPORT": "Export",
               "TRANSBO": "Transbo", "TRANSSHIPMENT": "Transbo"}

_VIN_RE = re.compile(r"\b(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{17}\b")
# « WITH CHASSIS NO.011203T2158 » (numéros de châssis courts, engins)
_CHASSIS_NO_RE = re.compile(r"CHASSIS\s*(?:NO|N°|NUMBER)\.?\s*[:\-]?\s*([A-Z0-9]{6,20})")


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------
def port_unlocode(pol: str) -> str:
    """UNLOCODE du port de chargement, "" si inconnu."""
    txt = re.sub(r"\s+", " ", str(pol or "")).upper()
    for key, code in _PORT_UNLOCODE:
        if key in txt:
            return code
    return ""


def clean_port_name(pol: str) -> str:
    """Nettoie un libellé de port (parasites « DISCHARGE PORT … » du manifeste)."""
    txt = re.sub(r"\s+", " ", str(pol or "")).strip()
    txt = re.split(r"DISCHARGE", txt, flags=re.I)[0].strip(" ,:：")
    return txt


def final_destination_country(dest: str) -> str:
    """Pays de destination finale au format du modèle IPAKI.
    Vide / Abidjan / Côte d'Ivoire → « COTE D'IVOIRE »."""
    d = re.sub(r"\s+", " ", str(dest or "")).strip().upper()
    d = re.sub(r"[`´’]", "'", d)
    if not d or any(k in d for k in ("ABIDJAN", "COTE D", "CÔTE D", "IVOIRE", "IVORY")):
        return "COTE D'IVOIRE"
    return d


def _fmt_num(x, nd: int = 3) -> str:
    """Nombre au format texte du modèle IPAKI : virgule décimale, zéros finaux
    retirés (« 115,005 », « 10,75 »). "" si absent."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return ""
    if v != v or v <= 0:
        return ""
    s = f"{v:.{nd}f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _first_line(text, maxlen: int = 80) -> str:
    for ln in str(text or "").replace("\r", "").split("\n"):
        ln = re.sub(r"\s+", " ", ln).strip(" ,;:")
        if ln:
            return ln[:maxlen]
    return ""


def _etat_to_new(etat) -> "bool | None":
    e = str(etat or "").upper()
    if not e.strip():
        return None
    if "NEUF" in e or "NEW" in e or "NEUV" in e:
        return True
    if "USAG" in e or "OCCAS" in e or "USED" in e:
        return False
    return None


def _new_unit(bl, nature, pol, dest, modele, is_new, chassis, kg, vol,
              consignee="", shipper="", bl_kg=None, bl_vol=None, source=""):
    """Un véhicule normalisé (kg/vol unitaires ; bl_kg/bl_vol = totaux B/L)."""
    def _s(x):  # NaN / None / nombre → texte propre
        if x is None or (isinstance(x, float) and x != x):
            return ""
        return re.sub(r"\s+", " ", str(x)).strip()
    return {
        "bl": _s(bl), "nature": nature or "Import",
        "pol": clean_port_name(_s(pol)), "dest": _s(dest), "modele": _s(modele),
        "is_new": is_new, "chassis": _s(chassis),
        "kg": _num(kg) or None, "vol": _num(vol) or None,
        "consignee": _s(consignee), "shipper": _s(shipper),
        "bl_kg": bl_kg, "bl_vol": bl_vol, "source": source,
    }


# ---------------------------------------------------------------------------
# Extracteurs par format → liste de véhicules normalisés
# ---------------------------------------------------------------------------
def _units_from_entries_expanded(entries, source, chassis_by_bl=None,
                                 model_by_bl=None, meta_by_bl=None):
    """Étend des entrées B/L (nombre, tonnage, volume totaux) en 1 ligne par
    véhicule. chassis_by_bl : {bl: [châssis...]} (complété par des lignes sans
    châssis si moins que `nombre`)."""
    chassis_by_bl = chassis_by_bl or {}
    model_by_bl = model_by_bl or {}
    meta_by_bl = meta_by_bl or {}
    units, warnings = [], []
    for e in entries:
        if getattr(e, "excluded", False) or e.nombre <= 0:
            continue
        n = int(e.nombre)
        kg = e.tonnage / n if e.tonnage else None
        vol = e.volume / n if e.volume else None
        meta = meta_by_bl.get(e.bl_number, {})
        chs = list(chassis_by_bl.get(e.bl_number, []))
        if len(chs) > n:
            warnings.append(f"B/L {e.bl_number} : {len(chs)} châssis détectés pour "
                            f"{n} unités déclarées — seuls les {n} premiers sont repris.")
            chs = chs[:n]
        chs += [""] * (n - len(chs))
        modele = model_by_bl.get(e.bl_number) or _first_line(e.description, 90)
        for ch in chs:
            units.append(_new_unit(
                e.bl_number, meta.get("nature", "Import"), e.pol,
                meta.get("dest", ""), modele, bool(e.is_new), ch, kg, vol,
                consignee=meta.get("consignee", ""), shipper=meta.get("shipper", ""),
                bl_kg=e.tonnage or None, bl_vol=e.volume or None, source=source))
    return units, warnings


def _read_chinese_raw(data: bytes, filename: str):
    """Texte brut par B/L du manifeste Chinese RoRo : description, expéditeur,
    destinataire (pour extraire VIN, modèle, noms)."""
    engine = "openpyxl" if filename.lower().endswith(".xlsx") else "xlrd"
    raw = pd.read_excel(io.BytesIO(data), header=None, engine=engine)
    hdr = None
    for i in range(min(15, len(raw))):
        row = " ".join(str(v).upper() for v in raw.iloc[i] if pd.notna(v))
        if "B/L NO" in row and "DESCRIPTION" in row:
            hdr = i
            break
    out = {}
    if hdr is None:
        return out

    def _col(key):
        for j, v in enumerate(raw.iloc[hdr]):
            if key in str(v).upper():
                return j
        return None
    c_bl, c_desc = _col("B/L NO"), _col("DESCRIPTION")
    c_sh, c_co = _col("SHIPPER"), _col("CONSIGNEE")
    for i in range(hdr + 1, len(raw)):
        bl = str(raw.iat[i, c_bl]).strip() if pd.notna(raw.iat[i, c_bl]) else ""
        if not bl or bl.upper() in ("NAN", "TOTAL"):
            continue
        g = lambda c: str(raw.iat[i, c]) if c is not None and pd.notna(raw.iat[i, c]) else ""
        out[bl] = {"desc": g(c_desc), "shipper": g(c_sh), "consignee": g(c_co)}
    return out


def _clean_party(text: str) -> str:
    t = re.sub(r"(?i)consign\s*name\s*:", "", str(text or ""))
    return _first_line(t, 90)


def units_chinese(data: bytes, filename: str, entries, meta):
    """Chinese RoRo : totaux/nombre fiables = parser classification (344/344
    validé sur Metsovo) ; châssis = VIN (17 car.) lus dans la description ;
    destination/nature/marque = parser Pré-Masque (grue)."""
    from crane_manifest_parser import parse_crane_manifest
    warnings = []
    raw_by_bl = {}
    try:
        raw_by_bl = _read_chinese_raw(data, filename)
    except Exception as exc:  # lecture brute non bloquante
        warnings.append(f"{filename} : lecture détaillée impossible ({exc}) — châssis non extraits.")
    crane = pd.DataFrame()
    try:
        crane = parse_crane_manifest(data, filename)
    except Exception as exc:
        warnings.append(f"{filename} : infos nature/destination non lues ({exc}).")

    meta_by_bl, chassis_by_bl, model_by_bl = {}, {}, {}
    for bl, d in raw_by_bl.items():
        seen = OrderedDict()
        up = d["desc"].upper()
        for m in _VIN_RE.findall(up):
            seen[m] = None
        for m in _CHASSIS_NO_RE.findall(up):
            seen[m] = None
        chassis_by_bl[bl] = list(seen)
        meta_by_bl[bl] = {"shipper": _clean_party(d["shipper"]),
                          "consignee": _clean_party(d["consignee"])}
    if not crane.empty:
        for bl, g in crane.groupby("BL", sort=False):
            r = g.iloc[0]
            m = meta_by_bl.setdefault(bl, {})
            m["nature"] = _NATURE_MAP.get(str(r.get("NATURE BL", "")).upper(), "Import")
            m["dest"] = str(r.get("FINAL DESTINATION TETRAX", "") or "")
            # Châssis du parser grue en complément (VIN en 16 car., etc.)
            extra = [c for c in g["CHÂSSIS"].astype(str) if c and c != "nan"]
            have = chassis_by_bl.setdefault(bl, [])
            for c in extra:
                if c not in have:
                    have.append(c)
            marque = str(g["MARQUE"].iloc[0] or "").strip()
            mm = str(g["MARQUE & MODELE"].iloc[0] or "").strip()
            if mm:
                model_by_bl[bl] = mm
            elif marque:
                model_by_bl[bl] = marque
    units, w2 = _units_from_entries_expanded(
        entries, "Chinese RoRo", chassis_by_bl, model_by_bl, meta_by_bl)
    return units, warnings + w2


def units_hyundai(entries):
    """Hyundai Glovis (scanné) : pas de châssis individuels dans l'OCR →
    N lignes sans châssis par B/L (à compléter par les agents)."""
    meta = {e.bl_number: {"dest": "COTE D'IVOIRE"} for e in entries}
    units, w = _units_from_entries_expanded(entries, "Hyundai Glovis", None, None, meta)
    w.append("Hyundai Glovis (scanné) : numéros de châssis non extraits — "
             "colonnes YardItemNumber / BarCode / ChassisNumber à compléter.")
    return units, w


def units_mol(data: bytes, filename: str):
    """MOL ALIS : le parser Pré-Masque donne 1 ligne par châssis ; poids et
    volume sont ceux du B/L (répétés) → répartis par véhicule."""
    from mol_manifest_parser import parse_mol_manifest
    df, warns, _meta = parse_mol_manifest(data, filename)
    warnings = [f"{filename} : {w}" for w in (warns or [])]
    units = []
    if df is None or df.empty:
        return units, warnings
    counts = df.groupby("BL")["BL"].transform("count")
    for (_, r), n in zip(df.iterrows(), counts):
        kg = _num(r.get("POIDS TETRAX (KG)"))
        vol = _num(r.get("VOLUME TETRAX"))
        units.append(_new_unit(
            r.get("BL"), _NATURE_MAP.get(str(r.get("NATURE BL", "")).upper(), "Import"),
            r.get("POL TETRAX"), str(r.get("FINAL DESTINATION TETRAX", "") or ""),
            r.get("MARQUE & MODELE") or r.get("MODELE") or "",
            _etat_to_new(r.get("ETAT")), r.get("CHÂSSIS"),
            kg / n if kg else None, vol / n if vol else None,
            bl_kg=kg, bl_vol=vol, source="MOL ALIS"))
    # bl_kg/bl_vol : le parser répète le total du B/L sur chaque ligne
    return units, warnings


def units_grimaldi(data: bytes, filename: str, progress_cb=None):
    """Grimaldi : on réutilise le parser Pré-Masque (lignes catégorie Véhicule),
    étendu à Nb_Unites lignes même quand tous les châssis ne sont pas listés."""
    import manifest_parser as mp
    recs = mp.parse_manifest(io.BytesIO(data), filename, progress_cb=progress_cb)
    df = mp.records_to_dataframe(recs)
    units, warnings = [], []
    if df is None or df.empty:
        return units, warnings
    veh = df[df["_cat_code"] == "V"]
    for _, r in veh.iterrows():
        nb = max(int(r.get("Nb_Unites") or 1), 1)
        chs = [c.strip() for c in str(r.get("Numeros_Chassis") or "").split(";") if c.strip()]
        n = max(nb, len(chs))
        chs += [""] * (n - len(chs))
        kg_tot, vol_tot = _num(r.get("Poids_Kg")) or 0, _num(r.get("Volume_CBM")) or 0
        marque, modele = str(r.get("Marque") or "").strip(), str(r.get("Modele") or "").strip()
        mm = f"{marque} {modele}".strip()
        dest = r.get("Pays_Transit") or ""
        for ch in chs:
            units.append(_new_unit(
                r.get("BL_Numero"), _NATURE_MAP.get(str(r.get("Nature_BL", "")).upper(), "Import"),
                r.get("Port_Chargement"), dest, mm, _etat_to_new(r.get("Etat")), ch,
                kg_tot / n if kg_tot else None, vol_tot / n if vol_tot else None,
                consignee=str(r.get("Destinataire_Nom") or ""),
                shipper=str(r.get("Chargeur_Nom") or ""),
                bl_kg=kg_tot, bl_vol=vol_tot, source="Grimaldi"))
    _fill_zero_weight_units(units)
    return units, warnings


def _fill_zero_weight_units(units):
    """Grimaldi : un enregistrement à poids/volume 0 (véhicule empilé / « bébé
    au dos ») appartient à un B/L dont le total est porté par un autre
    enregistrement. Si TOUS les véhicules du B/L sont du même modèle, le total
    B/L est réparti à parts égales (somme conservée) ; sinon on laisse vide
    (jamais de valeur inventée pour des types différents)."""
    by_bl = OrderedDict()
    for u in units:
        by_bl.setdefault(u["bl"], []).append(u)
    for bl, grp in by_bl.items():
        if not any(not u["kg"] or not u["vol"] for u in grp):
            continue
        if len({u["modele"] for u in grp}) != 1:
            continue
        tot_kg = sum(u["kg"] or 0 for u in grp)
        tot_vol = sum(u["vol"] or 0 for u in grp)
        n = len(grp)
        for u in grp:
            u["kg"] = (tot_kg / n) if tot_kg else None
            u["vol"] = (tot_vol / n) if tot_vol else None


def build_units(files, progress_cb=None):
    """files : [(nom, bytes)]. Retourne (units, warnings, erreurs, formats)."""
    units, warnings, errors, formats = [], [], [], {}
    for fi, (name, data) in enumerate(files):
        suffix = os.path.splitext(name)[1].lower() or ".pdf"
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as t:
                t.write(data)
                tmp = t.name
            fmt = clsveh.detect_format(tmp)
            formats[name] = fmt

            def _cb(p, tot, _fi=fi, _n=len(files), _name=name):
                if progress_cb:
                    progress_cb(_fi, _n, _name, p, tot)

            if fmt == "chinese_roro":
                entries, meta = clsveh.parse_chinese_roro(tmp)
                u, w = units_chinese(data, name, entries, meta)
            elif fmt == "mol_alis":
                u, w = units_mol(data, name)
            elif fmt == "grimaldi":
                u, w = units_grimaldi(data, name, progress_cb=_cb)
            elif fmt == "hyundai_glovis":
                entries, meta = clsveh.parse_hyundai_glovis(tmp, progress_cb=_cb)
                u, w = units_hyundai(entries)
            else:
                errors.append(f"{name} : format non reconnu.")
                continue
            if not u:
                errors.append(f"{name} : aucun véhicule trouvé (format {fmt}).")
            for unit in u:
                unit["file"] = name
            units.extend(u)
            warnings.extend(w)
        except Exception as exc:
            errors.append(f"{name} : erreur de traitement ({exc}).")
        finally:
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
    return units, warnings, errors, formats


# ---------------------------------------------------------------------------
# Construction du tableau 70 colonnes
# ---------------------------------------------------------------------------
def units_to_dataframe(units) -> pd.DataFrame:
    """Normalise les véhicules → DataFrame aux 70 colonnes (valeurs). Reproduit
    le classeur « IMPORTER VEHICULE » des agents : colonnes de saisie remplies
    depuis le manifeste, colonnes calculées = résultat des formules (voir
    FORMULA_TEMPLATES)."""
    rows = []
    year = datetime.now().year
    by_bl = OrderedDict()
    for u in units:
        by_bl.setdefault((u["source"], u["bl"]), []).append(u)

    for (_src, bl), group in by_bl.items():
        n = len(group)
        vols = [round(g["vol"], 3) if g["vol"] else None for g in group]
        kgs = [round(g["kg"] / 1000, 3) if g["kg"] else None for g in group]
        bl_vol = round(sum(v or 0 for v in vols), 3) or ""
        bl_wt = round(sum(k or 0 for k in kgs), 3) or ""
        if any(g["is_new"] is None for g in group):
            bl_commodity = ""
        else:
            bl_commodity = COMMODITY_NEUF if all(g["is_new"] for g in group) else COMMODITY_USAGE
        first = group[0]
        consignee_txt = next((g["consignee"] for g in group if g["consignee"]), "")
        shipper_txt = next((g["shipper"] for g in group if g["shipper"]), "")
        ie = first["nature"]
        pol_code = port_unlocode(first["pol"])

        for g, vol_u, wt_u in zip(group, vols, kgs):
            r = dict.fromkeys(BL_IMPORTER_COLUMNS, "")
            # --- colonnes de saisie (remplies depuis le manifeste) ---
            r["BL Number"] = bl
            r["ImportExport"] = ie
            r["Final Destination Country"] = final_destination_country(g["dest"] or first["dest"])
            r["Port Of Loading City UNLOCODE"] = pol_code
            r["Commodity"] = bl_commodity
            r["Comment"] = consignee_txt
            r["BLItem Commodity Volume"] = vol_u if vol_u else ""
            r["BLItem Commodity Weight"] = wt_u if wt_u else ""
            r["BLItem CustomNumber"] = year
            r["BLItem VehicleModel"] = g["modele"]
            r["BLItem ChassisNumber"] = g["chassis"]
            r["Shipper Name"] = shipper_txt
            # --- colonnes calculées (résultat des formules du classeur agents) ---
            r["Related Customer"] = "IMPORTER"
            r["Number of Yard Items"] = n
            r["TransportMode"] = "RR"
            r["Consignee"] = "IMPORTER"
            r["BLVolume"] = bl_vol
            r["BLWeight"] = bl_wt
            r["Reception Location UNLOCODE"] = "CIABJ"
            r["UnitOfMeasure"] = "Tonnes"
            r["BLItem YardItemType"] = "Véhicule"
            r["BLItem YardItemNumber"] = g["chassis"]
            r["BLItem AllowInvalidYardItemNumber"] = True
            if vol_u:
                r["BLItem YardItemCode"] = "VEH > 15m3" if vol_u > 15 else "VEH < 15m3"
            r["BLItem Commodity"] = bl_commodity
            r["BLItem ImportExport"] = ie
            r["BLItem BarCode"] = g["chassis"]
            r["Is Lifter"] = "FALSE"
            r["Freight Prepaid / Collect"] = "Collect"
            r["Is Transfer"] = "FALSE"
            r["BLItem HazardousClass"] = "0"
            r["Attach to BL"] = "FALSE"
            rows.append(r)
    return pd.DataFrame(rows, columns=BL_IMPORTER_COLUMNS)


# ---------------------------------------------------------------------------
# Contrôles
# ---------------------------------------------------------------------------
def check_required(df: pd.DataFrame, units=None) -> dict:
    """Résumé de ce qui reste à compléter / contrôler.
    Retourne {"a_completer": DataFrame, "manquants_manifeste": DataFrame,
              "alertes": [str]}."""
    n = len(df)

    def _empty(col):
        return int((df[col].astype(str).str.strip() == "").sum())

    a_comp = pd.DataFrame(
        [{"Colonne": c, "Lignes à saisir": _empty(c), "Total lignes": n}
         for c in REQUIRED_BOOKING_FIELDS])
    manq = pd.DataFrame(
        [{"Colonne": c, "Lignes vides": _empty(c), "Total lignes": n}
         for c in REQUIRED_AUTO_FIELDS if _empty(c) > 0])
    alertes = []
    unk = sorted({u["pol"] for u in (units or []) if u["pol"] and not port_unlocode(u["pol"])})
    if unk:
        alertes.append("Port de chargement sans UNLOCODE connu (à saisir) : " + ", ".join(unk))
    dup = df[df["BLItem YardItemNumber"].astype(str).str.strip() != ""]
    dups = dup["BLItem YardItemNumber"][dup["BLItem YardItemNumber"].duplicated()].unique()
    if len(dups):
        alertes.append(f"{len(dups)} numéro(s) de châssis en double : " + ", ".join(map(str, dups[:5])))
    if units:
        bl_src = {}
        for u in units:
            bl_src.setdefault(u["bl"], set()).add(u.get("file") or u["source"])
        multi = [b for b, srcs in bl_src.items() if len(srcs) > 1]
        if multi:
            alertes.append(f"{len(multi)} B/L présent(s) dans plusieurs manifestes (totaux cumulés) : "
                           + ", ".join(multi[:3]))
        n_inc = sum(1 for u in units if u["is_new"] is None)
        if n_inc:
            alertes.append(f"{n_inc} véhicule(s) dont l'état (neuf/occasion) n'est pas précisé dans le "
                           "manifeste : colonne « BLItem Commodity » laissée vide — à saisir (neuf / occasion).")
        n_nochassis = sum(1 for u in units if not u["chassis"])
        if n_nochassis:
            alertes.append(f"{n_nochassis} véhicule(s) sans numéro de châssis dans le manifeste "
                           "(YardItemNumber / BarCode / ChassisNumber à saisir).")
        n_novol = sum(1 for u in units if not u["vol"] or not u["kg"])
        if n_novol:
            alertes.append(f"{n_novol} véhicule(s) sans poids ou volume exploitable : le code véhicule "
                           "(formule du classeur) retombe sur « VEH < 15m3 » — à corriger après saisie du volume.")
    longs = df.loc[df["BLItem YardItemNumber"].astype(str).str.len() > 17, "BLItem YardItemNumber"].unique()
    if len(longs):
        alertes.append(f"{len(longs)} numéro(s) de châssis de plus de 17 caractères (extraction suspecte) : "
                       + ", ".join(map(str, longs[:3])))
    return {"a_completer": a_comp, "manquants_manifeste": manq, "alertes": alertes}


# ---------------------------------------------------------------------------
# Export Excel
# ---------------------------------------------------------------------------
# Code couleur des en-têtes du classeur des agents « IMPORTER VEHICULE » :
#   vert  = à remplir avec attention · rouge = B/L & CHÂSSIS (à remplir avec soin)
#   noir  = calculé par formule ou laissé vide
HEADER_RED = {"BL Number", "BLItem ChassisNumber"}
HEADER_GREEN = {
    "ImportExport", "Call Number", "Final Destination Country", "SlotFile",
    "Port Of Loading City UNLOCODE", "Reception Location UNLOCODE", "Commodity",
    "Comment", "BLItem Comment", "BLItem Commodity Volume", "BLItem Commodity Weight",
    "BLItem CustomNumber", "BLItem VehicleModel", "Shipper Name",
}
# Colonnes de saisie renseignées depuis le manifeste (le reste des colonnes
# vertes — Call Number, SlotFile, BLItem Comment — est à saisir par les agents).
INPUT_COLUMNS = [
    "BL Number", "ImportExport", "Final Destination Country",
    "Port Of Loading City UNLOCODE", "Commodity", "Comment",
    "BLItem Commodity Volume", "BLItem Commodity Weight", "BLItem CustomNumber",
    "BLItem VehicleModel", "BLItem ChassisNumber", "Shipper Name",
]


def _col_letter(idx: int) -> str:
    """Index 0-based → lettre(s) de colonne Excel (0→A, 26→AA)."""
    s = ""
    idx += 1
    while idx:
        idx, rem = divmod(idx - 1, 26)
        s = chr(65 + rem) + s
    return s


def _L(name: str) -> str:
    return _col_letter(BL_IMPORTER_COLUMNS.index(name))


# Formules des colonnes noires — identiques à celles du classeur des agents.
# {r} = n° de ligne Excel, {N} = dernière ligne de données.
def _formula_templates() -> dict:
    A, B, F, O = _L("BL Number"), _L("ImportExport"), _L("Call Number"), _L("SlotFile")
    AD, VOL, WT, CH = (_L("Commodity"), _L("BLItem Commodity Volume"),
                       _L("BLItem Commodity Weight"), _L("BLItem ChassisNumber"))
    blank = f'IF(ISBLANK({A}{{r}}),"",%s)'
    return {
        "Related Customer": blank % '"IMPORTER"',
        "Number of Yard Items": blank % f"COUNTIF(${A}$2:${A}${{N}},{A}{{r}})",
        "TransportMode": blank % '"RR"',
        "Consignee": blank % '"IMPORTER"',
        "BLVolume": blank % f"SUMIF(${A}$2:${A}${{N}},{A}{{r}},${VOL}$2:${VOL}${{N}})",
        "BLWeight": blank % f"SUMIF(${A}$2:${A}${{N}},{A}{{r}},${WT}$2:${WT}${{N}})",
        "Reception Location UNLOCODE": blank % '"CIABJ"',
        "YardItemType": blank % '""',
        "UnitOfMeasure": blank % '"Tonnes"',
        "BLItem YardItemType": blank % '"Véhicule"',
        "BLItem YardItemNumber": blank % f'IF(ISBLANK({CH}{{r}}),"",TRIM({CH}{{r}}))',
        "BLItem AllowInvalidYardItemNumber": "TRUE",
        "BLItem YardItemCode": blank % f'IF({VOL}{{r}}>15,"VEH > 15m3","VEH < 15m3")',
        "BLItem Commodity": blank % f"{AD}{{r}}",
        "BLItem ImportExport": blank % f'IF(ISBLANK({B}{{r}}),"",{B}{{r}})',
        "BLItem BarCode": blank % f'IF(ISBLANK({CH}{{r}}),"",TRIM({CH}{{r}}))',
        "OutGoingCallNumber": f'IF({B}{{r}}="Transbo",{F}{{r}},"")',
        "OutGoingSlotFile": f'IF({B}{{r}}="Transbo",{O}{{r}},"")',
        "Is Lifter": blank % '"FALSE"',
        "Freight Prepaid / Collect": blank % '"Collect"',
        "Is Transfer": blank % '"FALSE"',
        "BLItem HazardousClass": blank % '"0"',
        "Attach to BL": blank % '"FALSE"',
    }


FORMULA_TEMPLATES = _formula_templates()
_NUMERIC_INPUTS = {"BLItem Commodity Volume", "BLItem Commodity Weight", "BLItem CustomNumber"}


class _CachedFormulaCell:
    """Cellule formule .xls AVEC valeur calculée enregistrée (xlwt écrit par
    défaut un résultat « vide » : les colonnes calculées resteraient vides tant
    que le fichier n'est pas ouvert/recalculé dans Excel). Écrit l'enregistrement
    FORMULA (BIFF8) avec son résultat + l'enregistrement STRING pour les textes."""

    def __init__(self, rowx, colx, xf_idx, formula, value):
        self.rowx, self.colx, self.xf_idx = rowx, colx, xf_idx
        self.formula, self.value = formula, value

    def get_biff_data(self):
        import struct
        from xlwt import BIFFRecords
        rec = bytearray(BIFFRecords.FormulaRecord(
            self.rowx, self.colx, self.xf_idx, self.formula.rpn(), 0).get())
        v, tail = self.value, b""
        if isinstance(v, bool):
            res = struct.pack("<BBBBBBH", 1, 0, int(v), 0, 0, 0, 0xFFFF)
        elif isinstance(v, (int, float)):
            res = struct.pack("<d", float(v))
        else:
            txt = str(v)
            res = struct.pack("<BBBBBBH", 0, 0, 0, 0, 0, 0, 0xFFFF)
            body = struct.pack("<HB", len(txt), 1) + txt.encode("utf-16-le")
            tail = struct.pack("<HH", 0x0207, len(body)) + body
        rec[10:18] = res          # 4 (en-tête) + 6 (ligne, col, XF) = offset du résultat
        return bytes(rec) + tail


def _cached_value(col: str, row) -> "str | float | bool":
    """Valeur que la formule de `col` donne dans Excel pour la ligne `row`
    (mêmes règles : cellule vide = 0 dans une comparaison / une référence)."""
    chassis = str(row["BLItem ChassisNumber"]).strip()
    vol = row["BLItem Commodity Volume"]
    vol = float(vol) if vol not in ("", None) else 0.0
    transbo = row["ImportExport"] == "Transbo"
    if col in ("Number of Yard Items", "BLVolume", "BLWeight"):
        v = row[col]
        return float(v) if v not in ("", None) else 0.0
    if col in ("BLItem YardItemNumber", "BLItem BarCode"):
        return chassis
    if col == "BLItem AllowInvalidYardItemNumber":
        return True
    if col == "BLItem YardItemCode":
        return "VEH > 15m3" if vol > 15 else "VEH < 15m3"
    if col == "BLItem Commodity":
        return row["Commodity"] if row["Commodity"] != "" else 0.0
    if col == "BLItem ImportExport":
        return row["ImportExport"]
    if col in ("OutGoingCallNumber", "OutGoingSlotFile"):
        return 0.0 if transbo else ""
    return {  # colonnes à valeur constante
        "Related Customer": "IMPORTER", "Consignee": "IMPORTER", "TransportMode": "RR",
        "Reception Location UNLOCODE": "CIABJ", "YardItemType": "",
        "UnitOfMeasure": "Tonnes", "BLItem YardItemType": "Véhicule",
        "Is Lifter": "FALSE", "Freight Prepaid / Collect": "Collect",
        "Is Transfer": "FALSE", "BLItem HazardousClass": "0", "Attach to BL": "FALSE",
    }[col]


def _legend_rows():
    return [("green", "À remplir avec attention"), ("black", "Laisser vide"),
            ("red", "BL & CHASSIS (À REMPLIR AVEC SOIN)")]


def build_agents_xls_bytes(df: pd.DataFrame) -> bytes:
    """Classeur « IMPORTER VEHICULE » pour les agents (.xls) : colonnes de saisie
    pré-remplies depuis le manifeste, colonnes noires = formules identiques à
    leur classeur (valeurs déjà calculées), en-têtes colorés
    (vert / rouge / noir). Onglet « Description » = légende des couleurs +
    description officielle des champs IPAKI. Les formules sont enregistrées avec
    leur valeur calculée : les colonnes noires sont directement renseignées, sans
    ouverture ni recalcul préalable dans Excel."""
    import xlwt
    if len(df) > 65534:
        raise ValueError(f"{len(df)} lignes : dépasse la limite du format .xls (65 535). "
                         "Traitez les manifestes en plusieurs fois.")
    wb = xlwt.Workbook(encoding="utf-8")
    for idx, rgb in ((0x30, (0, 128, 0)), (0x31, (255, 0, 0)), (0x32, (0, 0, 0))):
        wb.set_colour_RGB(idx, *rgb)

    def _hdr(colour_idx, font_idx):
        st = xlwt.easyxf("font: name Arial, height 200, bold on; align: wrap on, vert top;")
        st.pattern = xlwt.Pattern()
        st.pattern.pattern = xlwt.Pattern.SOLID_PATTERN
        st.pattern.pattern_fore_colour = colour_idx
        st.font.colour_index = font_idx
        return st
    st_green, st_red, st_black = _hdr(0x30, 1), _hdr(0x31, 1), _hdr(0x32, 1)
    st_body = xlwt.easyxf("font: name Arial, height 200;")

    ws = wb.add_sheet("BL Importer")
    n = len(df)
    last = n + 1
    for j, col in enumerate(BL_IMPORTER_COLUMNS):
        st = st_red if col in HEADER_RED else st_green if col in HEADER_GREEN else st_black
        ws.write(0, j, col, st)
        ws.col(j).width = 256 * max(13, min(38, len(col) + 3))
    ws.row(0).height_mismatch = True
    ws.row(0).height = 255
    ws.set_panes_frozen(True)
    ws.set_horz_split_pos(1)

    for i in range(n):
        r = i + 2  # n° de ligne Excel
        rowvals = df.iloc[i]
        for j, col in enumerate(BL_IMPORTER_COLUMNS):
            if col in FORMULA_TEMPLATES:
                frm = xlwt.Formula(FORMULA_TEMPLATES[col].format(r=r, N=last))
                ws.write(i + 1, j, frm, st_body)          # enregistre la formule (styles, refs)
                xf = ws.row(i + 1)._Row__cells[j].xf_idx
                ws.row(i + 1)._Row__cells[j] = _CachedFormulaCell(
                    i + 1, j, xf, frm, _cached_value(col, rowvals))
            elif col in INPUT_COLUMNS:
                val = rowvals[col]
                if val == "" or val is None or (isinstance(val, float) and val != val):
                    continue
                if col in _NUMERIC_INPUTS:
                    ws.write(i + 1, j, float(val), st_body)
                else:
                    ws.write(i + 1, j, str(val), st_body)

    wd = wb.add_sheet("Description")
    fills = {"green": 0x30, "red": 0x31, "black": 0x32}
    for k, (colour, text) in enumerate(_legend_rows()):
        st = xlwt.easyxf("font: name Arial, height 200;")
        st.pattern = xlwt.Pattern()
        st.pattern.pattern = xlwt.Pattern.SOLID_PATTERN
        st.pattern.pattern_fore_colour = fills[colour]
        wd.write(k, 0, "", st)
        wd.write(k, 1, text)
    wd.col(1).width = 256 * 40
    for i, row in enumerate(DESCRIPTION_ROWS, start=5):
        for j, val in enumerate(row):
            if val != "":
                wd.write(i, j, str(val))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def default_filename(ext: str = "xls", prefix: str = "IMPORTER_VEHICULE") -> str:
    return f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}.{ext}"
