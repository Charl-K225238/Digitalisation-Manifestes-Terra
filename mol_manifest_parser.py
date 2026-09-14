"""
Parseur manifest MOL / MITSUI OSK LINES (format "ALIS ABIDJAN PROD CARGO
MANIFESTE") -> DataFrame au format pré-masque IPAKI (mêmes colonnes que
crane_manifest_parser.py, pour réutiliser generate_premasque_excel() tel quel).

Structure source : texte à colonnes pipe ("!"), comme PBREPORT Grimaldi mais
avec une sémantique de colonnes différente :
  col0 = N° B/L | col1 = SH/CO/NO (shipper/consignee/notify)
  col2 = Marks and Numbers (quasi toujours vide)
  col3 = Description of Goods | col4 = Gr Weight (Kg) | col5 = Measurement (m3)

4 sous-formats d'identification des unités observés dans un même manifeste
réel (voyage 0165A, EUPHONY ACE, 09/2026) :
  1. Label "CHASSIS NO:" / "CHASSIS NUMBER:" / "TRUCK CHASSIS NUMBER:" puis
     liste de VIN, une par ligne (majorité des B/L véhicules standards)
  2. Header "CHASSIS# ENGINE/MOTOR#" sans ":" puis paires VIN/moteur en
     alternance stricte, sans label par unité (Suzuki/Maruti)
  3. Tableau numéroté "S.NO. MACHINE NO. PIN NO." / "ENGINE NO." — ligne
     "<n> <machine_no> <pin_no>" puis ligne "<engine_no>" (Komatsu, engins)
  4. Listes séparées par label (PIN NUMBER: / UNIT SERIAL NUMBER /
     CHASSIS NUMBER: / ENGINE SERIAL NUMBER) — se ramène au cas 1 en ne
     retenant que le bloc CHASSIS NUMBER:, les autres identifiants
     (PIN/serial/engine) sont redondants pour notre usage (traçabilité
     châssis) et volontairement ignorés.
"""
from __future__ import annotations

import io
import re
import pdfplumber
import pandas as pd


def _as_stream(pdf_bytes_or_path):
    """Accepte indifféremment un chemin (str), des bytes bruts (ex.
    uploaded_file.getvalue() côté Streamlit) ou un objet déjà file-like —
    même souplesse d'appel que parse_crane_manifest(file_bytes, filename)."""
    if isinstance(pdf_bytes_or_path, (bytes, bytearray)):
        return io.BytesIO(pdf_bytes_or_path)
    return pdf_bytes_or_path

# ---------------------------------------------------------------------------
FORMAT_MARKERS = ("MITSUI OSK LINES", "MOL (CAR CARRIER)")

# Préfixe 3-6 lettres (constaté "MOLU" sur ce voyage, mais le préfixe B/L
# interne à un armateur peut varier d'un service/voyage à l'autre) + 6+
# chiffres — pas figé sur "MOLU" pour rester flexible, sans risque de faux
# positif : ce module n'est appelé qu'après confirmation is_mol_format().
BL_RE = re.compile(r'^([A-Z]{3,6}\d{6,})$')
QTY_TYPE_RE = re.compile(r'^(\d+)\s+(VEHICULES?|PACKAGE)S?$', re.I)
TOTAL_BL_RE = re.compile(r'^Total\s+B/L\s*:\s*(\S+)\s*/\s*$', re.I)
TOTAL_QTY_RE = re.compile(r'^(\d+)\s+GW', re.I)
POL_RE = re.compile(r'Port of loading \.\.:\s*(.+)$', re.I)
POD_RE = re.compile(r'Port of discharge\s*:\s*(.+)$', re.I)
VESSEL_RE = re.compile(r'^Vessel\s*:\s*\S+\s+(.+?)\s+Call date', re.I)
VOYAGE_RE = re.compile(r'Voyage\s*\.\.\.\s*:\s*(\S+)', re.I)

# Déclencheurs de sous-formats (col3). Tolère la coquille "CHASIS" (1 seul S)
# vue sur au moins 1 B/L réel (typo source, pas une variante à deviner : les
# deux graphies existent bel et bien dans ce manifeste).
_CHAS = r'CHAS{1,2}IS'
ALT_HEADER_RE = re.compile(
    rf'^{_CHAS}\s*(?:NO\.?|#)?\s*:?\s*/?\s*ENGINE\s*(?:NO\.?|#|/\s*MOTOR#?)?\s*:?$', re.I)
NUM_TABLE_HEADER_RE = re.compile(r'^S\.?\s*NO\.?\s+MACHINE\s+NO\.?\s+PIN\s+NO\.?$', re.I)
NUM_TABLE_ROW_RE = re.compile(r'^\d+\s+(\S+)\s+([A-Z0-9]{8,})$')
CHASSIS_LABEL_RE = re.compile(
    rf'^(?:TRUCK\s+)?{_CHAS}(?:\s+NO\.?|\s+NUMBER)\s*:?$|^{_CHAS}\s*NO\s*:?$', re.I)
# Non ancré en fin de ligne (pas de "$") : couvre aussi bien un label seul sur
# sa ligne ("ENGINE SERIAL NUMBER:") qu'un label suivi de sa valeur sur la
# même ligne ("ENGINE NO: JDEZ701298") — les deux cas existent dans ce
# manifeste. re.match() ancre déjà en début de ligne, donc pas de "^" requis
# en plus des motifs eux-mêmes.
STOP_LABEL_RE = re.compile(
    r'^(ENGINE\s+(NO\.?|NUMBER|SERIAL\s+NUMBER)\s*:?|HSN?\s*CODE|'
    r'MODEL\s*:|MODEL\s*/\s*AGE\s*:|YEAR\s+OF\s+MANUFACTUR\w*|'
    r'PIN\s+NUMBER\s*:?|UNIT\s+SERIAL\s+NUMBER\s*:?|S\.?\s*NO\.?\s+MACHINE)',
    re.I)
# Un vrai numéro de châssis/série contient toujours au moins un chiffre —
# exclut les mots de description purement alphabétiques ("VEHICLE-REFURNISHED")
# qui matchaient à tort le format "token" avant ce garde-fou.
TOKEN_RE = re.compile(r'^(?=.*\d)[A-Z0-9][A-Z0-9\-]{7,20}$')
# VIN standard ISO 3779 (17 car., sans I/O/Q) — utilisé en filet de sécurité
# quand aucun mode/label n'a permis de capter de châssis pour un B/L : capte
# aussi bien une liste de VIN sans label du tout (ex. Toyota) que des lignes
# "machine_no VIN" collées (ex. Komatsu) sans dépendre du bon déclenchement
# d'un mode. Ne remplace PAS le mode "labeled" (nécessaire quand le vrai
# identifiant n'est PAS un VIN 17 car., ex. n° châssis Caterpillar à 10 car.
# alors qu'un PIN NUMBER 17 car. non désiré coexiste dans le même B/L).
VIN_STRICT_RE = re.compile(r'\b([A-HJ-NPR-Z0-9]{17})\b')

YEAR_RE = re.compile(
    r'(?:YEAR\s+OF\s+MANUFACTUR\w*|MODEL\s*/\s*AGE|MODEL)\s*:?\s*(\d{4})', re.I)
HS_CODE_RE = re.compile(r'HSN?\s*CODE\.?\s*(?:NO)?\s*:\s*([\d\s]{4,12})', re.I)
ENGINE_NO_RE = re.compile(r'ENGINE\s+(?:NO\.?|NUMBER)\s*:\s*([A-Z0-9]{4,})', re.I)
NEW_RE = re.compile(r'\bNEW\b', re.I)
USED_RE = re.compile(r'\bUSED\b|\bREFURBISHED\b', re.I)

_BRANDS = [
    "ASHOK LEYLAND", "MARUTI SUZUKI", "MERCEDES-BENZ", "LAND ROVER",
    "RANGE ROVER", "TOYOTA", "NISSAN", "SUZUKI", "MAZDA", "KOMATSU",
    "CATERPILLAR", "MITSUBISHI", "HONDA", "FORD", "HYUNDAI", "KIA",
    "ISUZU", "VOLVO", "SCANIA", "DAF", "IVECO", "MAN", "RENAULT",
    "PEUGEOT", "CHEVROLET", "JETOUR", "SINOTRUK", "FOTON",
]
_NON_MODEL = frozenset({"NEW", "USED", "UNITS", "UNIT", "OF", "VEHICLES",
                         "VEHICLE", "SUZUKI"})


def _split_row(line: str):
    cols = [c.strip() for c in line.split("!")]
    if cols and cols[0] == "":
        cols = cols[1:]
    if cols and cols[-1] == "":
        cols = cols[:-1]
    return cols


def _is_separator(cols):
    if not cols:
        return True
    joined = "".join(cols).strip()
    return joined == "" or set(joined) <= {"-", "="}


def is_mol_format(pdf_bytes_or_path) -> bool:
    try:
        with pdfplumber.open(_as_stream(pdf_bytes_or_path)) as pdf:
            if not pdf.pages:
                return False
            text = (pdf.pages[0].extract_text() or "")
    except Exception:
        # PDF illisible/corrompu : pas une erreur de format MOL à signaler
        # spécifiquement, laisse l'appelant gérer (comme un PDF non reconnu).
        return False
    return all(m in text for m in FORMAT_MARKERS)


def _extract_brand_model(desc_text: str):
    up = desc_text.upper()
    for brand in _BRANDS:
        if brand in up:
            idx = up.find(brand)
            after = desc_text[idx + len(brand):].strip()
            modele = ""
            for tok in after.replace("/", " ").split():
                t = tok.upper().strip(".,")
                if t and t[0].isalpha() and t not in _NON_MODEL:
                    modele = tok.strip(".,")
                    break
            return brand.title(), modele
    return "", ""


# Colonnes garanties en sortie, même si aucun B/L n'a été extrait (évite un
# KeyError côté UI, ex. df["BL"].nunique() sur un DataFrame sans colonnes).
OUTPUT_COLUMNS = [
    "NBRE", "NATURE BL", "POL TETRAX", "POD TETRAX", "FINAL DESTINATION TETRAX",
    "POIDS TETRAX (KG)", "TYPE / TAILLE", "VOLUME TETRAX", "BL", "MARQUE",
    "MODELE", "MARQUE & MODELE", "ETAT", "ANNEE DE FABRICATION",
    "TYPE D'ACTION", "OBSERVATION", "CHÂSSIS",
    "_qty_declaree", "_type_declare", "_ctrl_qty", "_ctrl_weight",
]


def parse_mol_manifest(pdf_bytes_or_path, source_label: str = "") -> pd.DataFrame:
    """Lève ValueError si le PDF ne correspond pas au format MOL/MITSUI
    (cohérent avec parse_crane_manifest — l'appelant UI peut attraper cette
    exception précisément plutôt qu'un DataFrame vide silencieux)."""
    if not is_mol_format(pdf_bytes_or_path):
        raise ValueError(
            "Ce PDF ne correspond pas au format MOL / MITSUI OSK LINES "
            "attendu (marqueurs \"MITSUI OSK LINES\" / \"MOL (CAR CARRIER)\" "
            "absents de la première page)."
        )
    with pdfplumber.open(_as_stream(pdf_bytes_or_path)) as pdf:
        lines = []
        for page in pdf.pages:
            text = page.extract_text() or ""
            lines.extend(text.split("\n"))
            page.flush_cache()

    navire, voyage, pol, pod = "", "", "", ""
    records = []
    current = None
    state = None  # "SH" | "CO" | "NO"
    mode = None   # None | "alt" | "numtable" | "labeled"
    alt_toggle = 0
    warnings = []

    def flush():
        nonlocal current
        if current:
            records.append(current)
        current = None

    for raw in lines:
        vm = VESSEL_RE.search(raw)
        if vm:
            navire = vm.group(1).strip()
        vym = VOYAGE_RE.search(raw)
        if vym:
            voyage = vym.group(1).strip()
        pm = POL_RE.search(raw)
        if pm:
            pol = pm.group(1).strip()
        pdm = POD_RE.search(raw)
        if pdm:
            pod = pdm.group(1).strip()

        cols = _split_row(raw)
        if _is_separator(cols):
            continue
        if not raw.strip().startswith("!"):
            continue  # ligne hors tableau (en-tête page, adresses transporteur...)

        c0, c1, c2, c3 = (cols[i] if i < len(cols) else "" for i in range(4))
        c4 = cols[4] if len(cols) > 4 else ""
        c5 = cols[5] if len(cols) > 5 else ""

        m = BL_RE.match(c0)
        if m and current is not None and m.group(1) == current["bl"]:
            # Répétition du n° de B/L en tête de page après "To be continued
            # ... / Continued ..." (pagination PDF) : PAS un nouveau B/L,
            # on poursuit l'accumulation du bloc déjà ouvert.
            m = None
        if m:
            flush()
            current = {
                "bl": m.group(1), "pol": pol, "pod": pod,
                "qty_declared": None, "type_declared": "",
                "weight": None, "volume": None,
                "chassis": [], "desc_lines": [],
            }
            state = "SH"
            mode = None
            alt_toggle = 0

        if current is None:
            continue

        if c1:
            if c1.startswith("SH "):
                state = "SH"
            elif c1.startswith("CO "):
                state = "CO"
            elif c1.startswith("NO "):
                state = "NO"

        if c4:
            wv = c4.replace(",", "")
            try:
                if current["weight"] is None:
                    current["weight"] = float(wv)
            except ValueError:
                pass
        if c5:
            mv = c5.replace(",", "")
            try:
                if current["volume"] is None:
                    current["volume"] = float(mv)
            except ValueError:
                pass

        if c3:
            qm = QTY_TYPE_RE.match(c3)
            tbm = TOTAL_BL_RE.match(c0) if c0 else None
            if qm and current["qty_declared"] is None:
                current["qty_declared"] = int(qm.group(1))
                current["type_declared"] = qm.group(2).upper()
            elif ALT_HEADER_RE.match(c3):
                mode = "alt"
                alt_toggle = 0
            elif NUM_TABLE_HEADER_RE.match(c3):
                mode = "numtable"
            elif CHASSIS_LABEL_RE.match(c3):
                mode = "labeled"
            elif STOP_LABEL_RE.match(c3):
                if mode == "labeled":
                    mode = None
            elif mode == "numtable":
                ntm = NUM_TABLE_ROW_RE.match(c3)
                if ntm:
                    current["chassis"].append(ntm.group(2))
            elif mode == "alt":
                if TOKEN_RE.match(c3):
                    if alt_toggle == 0:
                        current["chassis"].append(c3)
                    alt_toggle = 1 - alt_toggle
            elif mode == "labeled":
                if TOKEN_RE.match(c3):
                    current["chassis"].append(c3)
            current["desc_lines"].append(c3)

        # ligne "Total B/L : BREAKBULK /" -> qty/poids/volume de contrôle
        if c0 and TOTAL_BL_RE.match(c0):
            tqm = TOTAL_QTY_RE.match(c1) if c1 else None
            if tqm:
                current["_ctrl_qty"] = int(tqm.group(1))
            try:
                current["_ctrl_weight"] = float(c2.replace(",", "")) if c2 else None
                current["_ctrl_volume"] = float(c3.replace(",", "")) if c3 else None
            except (ValueError, AttributeError):
                pass

    flush()

    rows = []
    for r in records:
        if not r["chassis"]:
            # Filet de sécurité : aucun mode n'a capté de châssis (label non
            # reconnu, variante d'en-tête non prévue...) — recherche directe
            # de VIN 17 car. dans tout le texte descriptif du B/L. Ne
            # s'applique que si la liste est vide, pour ne jamais court-
            # circuiter une capture "labeled" déjà correcte (ex. Caterpillar,
            # où le vrai n° châssis fait 10 car. et coexiste avec un PIN
            # NUMBER de 17 car. qu'il ne faut pas confondre avec le châssis).
            found = VIN_STRICT_RE.findall(" ".join(r["desc_lines"]))
            r["chassis"] = list(dict.fromkeys(found))
        full_desc = " ".join(dict.fromkeys(r["desc_lines"]))
        marque, modele = _extract_brand_model(full_desc)
        ym = YEAR_RE.search(full_desc)
        annee = int(ym.group(1)) if ym else None
        etat = "Neuf" if NEW_RE.search(full_desc) else ("Usager" if USED_RE.search(full_desc) else "")
        n_chassis = len(r["chassis"])
        n_declared = r["qty_declared"] or 0
        flag = ""
        if n_chassis == 0:
            flag = "AUCUN CHASSIS EXTRAIT - a completer manuellement"
        elif r["type_declared"].startswith("VEHIC") and n_chassis != n_declared:
            flag = f"ecart quantite : {n_declared} declares vs {n_chassis} chassis extraits"

        # "Import" par défaut (POD = Abidjan, cas de ce manifeste) ; sinon
        # "Export"/"Transbo" possible sur un futur manifeste MOL — détecté
        # depuis le POD plutôt que figé, sans données pour calibrer plus
        # finement Export vs Transbo à ce stade (à affiner si un exemple réel
        # se présente, jamais deviné).
        nature = "Import" if re.search(r'ABIDJAN', r["pod"], re.I) else "Export/Transbo"
        base = {
            "NATURE BL": nature, "POL TETRAX": r["pol"], "POD TETRAX": r["pod"],
            "FINAL DESTINATION TETRAX": r["pod"],
            "POIDS TETRAX (KG)": r["weight"], "TYPE / TAILLE": "",
            "VOLUME TETRAX": r["volume"], "BL": r["bl"],
            "MARQUE": marque, "MODELE": modele,
            "MARQUE & MODELE": f"{marque} {modele}".strip(),
            "ETAT": etat, "ANNEE DE FABRICATION": annee,
            "TYPE D'ACTION": "", "OBSERVATION": flag,
            "_qty_declaree": n_declared, "_type_declare": r["type_declared"],
            "_ctrl_qty": r.get("_ctrl_qty"), "_ctrl_weight": r.get("_ctrl_weight"),
        }
        if r["chassis"]:
            for ch in r["chassis"]:
                row = dict(base)
                row["CHÂSSIS"] = ch
                rows.append(row)
        else:
            row = dict(base)
            row["CHÂSSIS"] = ""
            rows.append(row)

    if rows:
        df = pd.DataFrame(rows)
        df.insert(0, "NBRE", range(1, len(df) + 1))
    else:
        # Aucun B/L extrait (PDF vide, format inattendu au-delà des
        # marqueurs de détection...) : DataFrame vide mais avec les
        # colonnes attendues, pour que le code appelant (df["BL"].nunique(),
        # etc.) ne plante pas sur un KeyError.
        df = pd.DataFrame(columns=OUTPUT_COLUMNS)
        warnings.append(
            "Aucun B/L extrait de ce PDF — vérifier qu'il s'agit bien d'un "
            "manifeste MOL/MITSUI complet (pages non tronquées)."
        )
    meta = {"navire": navire, "voyage": voyage}
    return df, warnings, meta
