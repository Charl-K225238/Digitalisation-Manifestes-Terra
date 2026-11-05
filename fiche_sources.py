"""
Fiche de dépouillement : lecture de tous les types de manifestes.

Reconnaît le format d'un fichier, le lit avec le parser Pré-Masque existant et
le ramène aux unités de la fiche (une ligne par unité, voir fiche_depouillement).

  Grimaldi PDF                 -> libellés de catégorie du manifeste (inchangé)
  EUKOR, MOL / NYK / K LINE    -> colonnes Pré-Masque
  Navire à grue (.xls, .xlsx)  -> colonnes Pré-Masque
  Cargo Manifest scanné        -> colonnes Pré-Masque (OCR)
  Hyundai Glovis scanné        -> B/L (OCR), pas de châssis individuels

Hors Grimaldi, le manifeste ne donne pas de catégorie USED / NEW / >50m3 :
volume unitaire strictement > 50 m3 -> >50m3 ; sans volume, un mot d'engin
(camion, foreuse...) -> >50m3 à vérifier ; sinon l'état Neuf / Usager décide.
Sans état écrit : année de fabrication ÉCRITE au manifeste et récente -> NEW, sinon
USED, en fiabilité LOW. Rien n'est déduit du VIN.
"""
import datetime
import io
import pathlib
import re

import fiche_depouillement as fd

SEUIL_50M3 = 50.0
ANS_RECENTS = 1     # sans état écrit : année du manifeste >= année en cours - 1 -> NEW
_ENGIN_RE = re.compile(
    r"TRUCK|TRACTOR|TRAILER|\bRIG\b|DRILL|EXCAVATOR|BULLDOZER|DOZER|LOADER|FORKLIFT|CRANE|"
    r"\bBUS\b|GRADER|ROLLER|COMPRESSOR|GENERATOR", re.I)


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None        # NaN -> None


def _etat(v) -> str:
    s = str(v or "").upper()
    if "NEUF" in s or "NEUVE" in s:
        return "Neuf"
    return "Usager" if "USAG" in s or "OCCASION" in s else ""


def classify_unit(libelle, etat, volume, colis=False, annee=None):
    """-> (sous_type, fiabilité) pour une ligne hors Grimaldi."""
    if colis:
        return "COLIS", "HIGH"
    if volume is not None and volume > SEUIL_50M3:
        return "MAFI", "HIGH"
    if volume is None and _ENGIN_RE.search(libelle or ""):
        return "MAFI", "MEDIUM"
    if etat == "Neuf":
        return "VEH_NEW", "HIGH"
    if etat == "Usager":
        return "VEH_USED", "HIGH"
    if annee and annee >= datetime.date.today().year - ANS_RECENTS:
        return "VEH_NEW", "LOW"
    return "VEH_USED", "LOW"


def units_from_premasque(df, navire, voyage):
    """Une unité par ligne du DataFrame Pré-Masque (tous parsers sauf Grimaldi)."""
    units = []
    for r in df.to_dict("records"):
        libelle = str(r.get("MARQUE & MODELE") or r.get("MODELE") or "").strip()
        volume = _num(r.get("VOLUME"))
        volume = volume if volume is not None else _num(r.get("VOLUME TETRAX"))
        chassis = str(r.get("CHÂSSIS") or "")
        # EUKOR et Cargo Manifest complètent l'année depuis le VIN pour le Pré-Masque :
        # ici, seule l'année écrite au manifeste compte.
        annee = _num(r["_ANNEE_MANIFESTE"] if "_ANNEE_MANIFESTE" in r else r.get("ANNEE DE FABRICATION"))
        sub, conf = classify_unit(libelle, _etat(r.get("ETAT")), volume or None,
                                  r.get("CATEGORIE") == "Colis", annee)
        units.append({
            "Navire": navire or "(navire non détecté)", "Voyage": voyage or "",
            "BL": r.get("BL") or (f"Lot {r['LOT']}" if r.get("LOT") else ""),
            "Catégorie": fd.SUBTYPE_CAT[sub], "Sous-type": fd.SUBTYPE_LABELS[sub],
            "Identification manifeste": libelle, "Marque/Modèle": libelle,
            "N° conteneur": "", "Châssis/VIN": chassis,
            "Année": int(annee) if annee else "",
            "Poids (kg)": _num(r.get("POIDS TETRAX (KG)")), "CBM": volume,
            "Fiabilité": conf,
        })
    return units


def units_from_entries(entries, meta):
    """Hyundai Glovis : B/L sans châssis individuels, nombre d'unités par B/L."""
    units = []
    for e in entries:
        if e.excluded:
            continue
        n = max(int(e.nombre or 1), 1)
        volume = round(e.volume / n, 3) if e.volume else None
        sub, conf = classify_unit(e.description, "Neuf" if e.is_new else "", volume)
        for _ in range(n):
            units.append({
                "Navire": meta.get("ship_name") or "(navire non détecté)", "Voyage": meta.get("voyage") or "",
                "BL": e.bl_number, "Catégorie": fd.SUBTYPE_CAT[sub], "Sous-type": fd.SUBTYPE_LABELS[sub],
                "Identification manifeste": e.description, "Marque/Modèle": "", "N° conteneur": "",
                "Châssis/VIN": "", "Année": "",
                "Poids (kg)": round(e.tonnage / n, 1) if e.tonnage else None, "CBM": volume,
                "Fiabilité": conf,
            })
    return units


def _controle_total(df, meta) -> list:
    """Total annoncé par le manifeste comparé aux lignes lues."""
    annonce = meta.get("total_declare")
    if annonce and annonce != len(df):
        return [f"Le manifeste annonce {annonce} unités, {len(df)} lues : vérifier avant usage."]
    return []


def controles_lot(fichiers) -> list:
    """Contrôles sur l'ensemble chargé. fichiers : [(nom, unités)]."""
    vu, doublons = {}, {}
    for nom, units in fichiers:
        for u in units:
            ch = u.get("Châssis/VIN")
            if ch and ch in vu and vu[ch] != nom:
                doublons[ch] = (vu[ch], nom)
            vu.setdefault(ch, nom)
    if not doublons:
        return []
    ex, (a, b) = next(iter(doublons.items()))
    return [f"{len(doublons)} châssis présents dans deux fichiers (ex. {ex} dans {a} et {b}) : "
            "ils sont comptés deux fois, vérifier les fichiers chargés."]


def read_manifest(name: str, data: bytes, progress_cb=None):
    """-> (libellé du format, unités, avertissements).
    Lève une exception au message clair si le fichier n'est pas reconnu."""
    if name.lower().endswith((".xls", ".xlsx")):
        from bl_importer import is_grimaldi_xlsx
        from crane_manifest_parser import parse_crane_manifest
        if data[:2] == b"PK" and is_grimaldi_xlsx(data):
            raise ValueError("Ce fichier est un export de l'application, pas un manifeste : "
                             "chargez le manifeste d'origine.")
        df = parse_crane_manifest(data, name)
        navire = df.attrs.get("navire") or pathlib.Path(name).stem   # à défaut, nom du fichier
        return "Navire à grue", units_from_premasque(df, navire, df.attrs.get("voyage")), []

    from cargo_scan_parser import is_scan_pdf, parse_cargo_scan_manifest
    from eukor_manifest_parser import is_eukor_format, parse_eukor_manifest
    from mol_manifest_parser import is_mol_format, parse_mol_manifest

    if is_scan_pdf(data):
        import classification_vehicules as cv
        entries, meta, fmt = cv.parse_manifest_bytes(name, data, progress_cb=progress_cb)
        if fmt == "hyundai_glovis" and entries:
            return ("Hyundai Glovis scanné", units_from_entries(entries, meta),
                    ["Châssis individuels non disponibles sur ce format scanné."])
        df, warns, m = parse_cargo_scan_manifest(data, name, progress_cb)
        return "Cargo Manifest scanné", units_from_premasque(df, m.get("navire"), m.get("voyage")), warns
    if is_eukor_format(data):
        df, warns, m = parse_eukor_manifest(data, name, progress_cb)
        return "EUKOR", units_from_premasque(df, m.get("navire"), m.get("voyage")), warns + _controle_total(df, m)
    if is_mol_format(data):
        df, warns, m = parse_mol_manifest(data, name)
        return "MOL / NYK / K LINE", units_from_premasque(df, m.get("navire"), m.get("voyage")), warns

    from manifest_parser import parse_manifest
    records = parse_manifest(io.BytesIO(data), name, progress_cb=progress_cb)
    units = fd.build_units(records)
    if units:
        return "Grimaldi", units, []
    parse_mol_manifest(data, name)      # lève le message d'erreur explicite
    raise ValueError("format de manifeste non reconnu")
