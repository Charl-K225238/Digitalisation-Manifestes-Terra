"""
Parseur « CARGO MANIFEST » scanné (formulaire agent : breakbulk Inde -> Abidjan)
-> DataFrame au format pré-masque IPAKI (mêmes colonnes que mol_manifest_parser,
pour réutiliser l'écran de vérification et generate_premasque_excel()).

Référence : M.V. UNION LUCK V3 (10/2026), 6 pages, 6 lots, Ennore -> Abidjan.

Structure source : scan (CamScanner) sans couche texte, pages tournées à 90°.
Un tableau par page, une colonne par rubrique :
  SL.No | Shipper | Consignee(s) party | Quantity | Description of Goods | Gross Weight
En-tête de page : « M.V. <navire> <voyage> », Port of Loading, Port of Discharging.

Variante « MR.NO » (réf. INDEV INFRA, MV PAC SEGINUS V583X, 11/2026) : plusieurs lots par page,
  rubriques MR.NO/DATE | SHIPPERS | CONSIGNEES | MARKS AND NOS | DESCRIPTION | NO.OF PKGS |
  GROSS WEIGHT KGS | REMARK, une ligne du tableau par lot, puis « TOTAL PKGS ». Le n° MR
  sert de n° de B/L (lu par OCR : à vérifier). En-tête : « SHIPPED ON MV <navire> V<voyage> »,
  « ROUTE: <port de chargement> PORT (…) - ABIDJAN ».

Particularités :
  - AUCUN N° de B/L ni volume : colonnes laissées vides, à compléter (rien n'est
    inventé). Le lot est identifié par la colonne LOT (SL.No).
  - Quantity compte des colis, pas des véhicules : la source de vérité des
    unités est la liste de châssis de la description. Écart = colis (caisses,
    skids...), signalé. Pour Caterpillar, le PIN (17 car.) sert de châssis.
  - Poids brut par lot : réparti à parts égales entre ses unités.
  - Colis sans châssis : une ligne CATEGORIE = « Colis » par colis, sans poids
    (déjà compté dans le poids du lot) sauf lot composé uniquement de colis.
"""
from __future__ import annotations

import datetime
import re

import pandas as pd

from mol_manifest_parser import ManifestReadError, ManifestFormatError, OUTPUT_COLUMNS
import vehicle_models as vm

SEUIL_SOMBRE = 170           # pixel plus sombre = encre / trait
FENETRE_TRAIT = 16           # px : absorbe l'inclinaison du scan
COUVERTURE_TRAIT = 0.9       # part des rangées traversées par un vrai trait

ID_RE = re.compile(r'^(?=.*\d)[A-Z0-9][A-Z0-9\-]{5,24}$')
CHASSIS_INLINE_RE = re.compile(r'CHAS+I*S+I*S*\s*(?:NO|NUMBER)\b\.?\s*[:;.]*\s*([A-Z0-9]{6,})', re.I)
ENGINE_RE = re.compile(r'ENGINE\s*(?:SERIAL\s*)?(?:NO|NUMBER)\b\.?\s*[:;.]*\s*([A-Z0-9]{5,})?', re.I)
LIST_LABEL_RE = re.compile(r'^(PIN|UNIT\s+SERIAL|CHASSIS|ENGINE\s+SERIAL)\s+NUMBER\s*:?\s*$', re.I)
QTY_RE = re.compile(r'(\d+)\s*(?:PACK|PKG|UNIT|PCS|NOS)', re.I)
WEIGHT_RE = re.compile(r'(\d[\d,]*(?:\.\d+)?)KGS?', re.I)
HEAD_QTY_RE = re.compile(r'^(\d+)\s*X\s*(.+?)(?:\s*\+.*)?$', re.I)
YEAR_RE = re.compile(r'(?:YEAR\s+OF\s+MANUFACTURE|YOM)\s*[:.]?\s*(\d{4})', re.I)
STARRED_MODEL_RE = re.compile(r'M\w{0,2}ODEL\s*[:;]\s*\W*(SMRS[^*/]+?)\W*(?:/|SERIAL|$)', re.I)
USED_RE = re.compile(r'\b(?:USED|RE-?CONDITIONED|REFUR\w*|REBUR\w*)\b|USED(?=RIG|VE[HIC])', re.I)
# « … VEHICLE WITH NEW AIR COMPRESSOR », « HAVE ALONGWITH NEW ELGI AC » : NEW vise l'équipement fourni
# avec le véhicule, pas le véhicule.
AVEC_NEUF_RE = re.compile(r'WITH\s*NEW\b[^.;]*', re.I)
# Accessoires / équipements livrés avec le véhicule (OCR parfois collé : DRILLACCESS, STDACCRS)
ACCESSOIRES_RE = re.compile(r'ACCESS|ACCRS|SPARE|COMPRESS|COMPRS', re.I)
# Véhicule écrit collé ou mal orthographié par l'OCR (« USEDRIGVEICLE », « RIGVECHICLE »)
VEHICULE_COLLE_RE = re.compile(r'VE[HCI]{1,3}CLE')
TOTAL_RE = re.compile(r'\bTOTAL\b', re.I)
ROUTE_RE = re.compile(r'ROUTE\s*[:;.]?\s*([A-Z][A-Z ]+?)\s+(?:SEA\s+)?PORT\b.*?-\s*([A-Z]{4,})', re.I)
COMPRESSOR_RE = re.compile(r'\bNEW\s+(?:-\s*)?(?:ELGI\s+|CHICAGO\s+)?(?:PNEUMATIC\s+)?AIR\s+COMPRESSOR', re.I)
NEW_RE = vm.NEW_ETAT_RE   # mot NEW écrit, hors noms propres (NEW HOLLAND, NEW YORK…)
VEHICLE_WORD_RE = re.compile(r'CHAS+I|VEHICLE|TRUCK|LORRY|EXCAVATOR|LOADER', re.I)
VESSEL_RE = re.compile(r'M\s*\.?\s*V\s*\.?\s+([A-Z][A-Z ]+?)\s+(V[\s.]*\d\S*)', re.I)
POL_RE = re.compile(r'P\w{2,3}\s+\w{1,2}\s+L\w{2,3}din\w*\s*[:;.\-]*\s*(.+?)(?=\s+P\w{2,3}\s+\w{1,2}\s+Disch|$)', re.I)
POD_RE = re.compile(r'P\w{2,3}\s+\w{1,2}\s+Disch\w*\s*[:;.]?\s*(\S+)', re.I)

# Année-modèle ISO 3779 (10e caractère du VIN), cycle 2010-2039.
_VIN_YEAR = {c: 2010 + i for i, c in enumerate("ABCDEFGHJKLMNPRSTVWXY123456789")}

# Marques d'engins absentes du référentiel voitures (ordre = priorité).
_ENGIN_BRANDS = [("JCB", "JCB"), ("ASHOK LEYLAND", "Ashok Leyland"),
                 ("AMW MOTORS", "AMW"), ("CATERPILLAR", "Caterpillar")]
# Comparés au texte sans espaces : l'OCR colle les mots (« ASHOKLEYLANDLTD », « DTHDRILLMDL »).
_MODEL_KEYWORDS = [("DTHDRILL", "DTH DRILL"), ("RIGSUPPORTVEHICLE", "RIG SUPPORT VEHICLE"),
                   ("MOBILEDRILLING", "MOBILE DRILLING RIG VEHICLE"), ("RIGVEHICLE", "RIG VEHICLE"),
                   ("RIGVECHICLE", "RIG VEHICLE"), ("RIGVEICLE", "RIG VEHICLE")]


def _compact(t: str) -> str:
    return re.sub(r'[^A-Z0-9]', '', (t or '').upper())


def _pymupdf():
    """PyMuPDF sous son nom actuel ; « fitz » (nom historique, annoncé comme retiré)
    seulement en repli pour une ancienne installation."""
    try:
        import pymupdf
        return pymupdf
    except ImportError:
        import fitz
        return fitz


def is_scan_pdf(data: bytes) -> bool:
    """Vrai si la 1re page n'a pas de texte exploitable (CamScanner y laisse
    seulement un filigrane de quelques caractères)."""
    fitz = _pymupdf()
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            return bool(len(doc)) and len(doc[0].get_text().strip()) < 40
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Lecture de l'image : en-têtes, traits du tableau, OCR par colonne
# ---------------------------------------------------------------------------
def _pages(data: bytes):
    """Itère (page n°, total, image) ; lève ManifestReadError si illisible."""
    fitz = _pymupdf()
    from classification_vehicules import _render_page_rotated
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as e:
        raise ManifestReadError(
            "Impossible d'ouvrir ce PDF (fichier corrompu, protégé ou incomplet). "
            "Rechargez le manifeste d'origine.") from e
    with doc:
        if not len(doc):
            raise ManifestReadError("Le PDF ne contient aucune page. Rechargez le fichier d'origine.")
        for i in range(len(doc)):
            yield i + 1, len(doc), _render_page_rotated(doc, i)


def _header_anchors(gray):
    """-> {rubrique: (x0, x1, y1)} depuis l'OCR rapide de la page (échelle 1/2)."""
    import pytesseract
    small = gray.resize((gray.width // 2, gray.height // 2))
    d = pytesseract.image_to_data(small, output_type=pytesseract.Output.DICT, config="--psm 11")
    keys = {"shipper": "SHIPPER", "consign": "CONSIGNEE", "quantity": "QUANTITY",
            "description": "DESCRIPTION", "gross": "GROSS", "remark": "REMARK"}
    found = {}
    for txt, x, y, w, h in zip(d["text"], d["left"], d["top"], d["width"], d["height"]):
        low = (txt or "").lower()
        for k, v in keys.items():
            if k in low and (v not in found or y * 2 < found[v][2] - 40):   # le plus haut
                found[v] = (x * 2, (x + w) * 2, (y + h) * 2)
    return found


_RUBRIQUES = {"SHIPPER", "CONSIGNEE", "QUANTITY", "DESCRIPTION", "GROSS"}
_RUBRIQUES_MR = {"SHIPPER", "CONSIGNEE", "DESCRIPTION", "GROSS", "REMARK"}


def _find_table(img):
    """Cherche l'orientation où les rubriques sont lues.
    -> (image N&B, ancres, format « sl » ou « mr ») ou (None, {}, "").
    L'OSD se trompe sur les pages creuses."""
    gray = img.convert("L")
    for angle in (0, 180, 90, 270):
        candidate = gray.rotate(angle, expand=True) if angle else gray
        anchors = _header_anchors(candidate)
        if _RUBRIQUES <= set(anchors):
            # format historique : ancres inchangées (un « REMARK » ailleurs ne décale pas le tableau)
            return candidate, {k: anchors[k] for k in _RUBRIQUES}, "sl"
        if _RUBRIQUES_MR <= set(anchors):
            return candidate, anchors, "mr"
    return None, {}, ""


def _line_peaks(dark):
    """Traits perpendiculaires à l'axe 1 de `dark` : positions où presque toutes
    les rangées ont un pixel sombre dans une fenêtre étroite. Contrairement à
    une somme de pixels, le texte (coupé par les interlignes) n'y passe pas."""
    import numpy as np
    cum = np.cumsum(dark, axis=1, dtype=np.int32)
    w = FENETRE_TRAIT
    covered = ((cum[:, w:] - cum[:, :-w]) > 0).mean(0)
    idx = np.where(covered >= COUVERTURE_TRAIT)[0]
    groups = []
    for i in idx:
        if groups and i - groups[-1][-1] <= 2:
            groups[-1].append(int(i))
        else:
            groups.append([int(i)])
    return [(g[0] + g[-1]) // 2 + w // 2 for g in groups]


def _table_box(gray, anchors):
    """Traits du tableau -> (y_haut_corps, y_bas, bornes x des 6 colonnes)."""
    import numpy as np
    arr = np.asarray(gray) < SEUIL_SOMBRE
    x_min = max(0, anchors["SHIPPER"][0] - 400)
    x_max = min(arr.shape[1], anchors["GROSS"][1] + 150)
    head_y = max(a[2] for a in anchors.values())

    # Traits horizontaux, mesurés sur la seule largeur de la colonne Description
    # (la plus sûre d'être entière dans le scan).
    ys = [y for y in _line_peaks(arr[:, anchors["DESCRIPTION"][0]:anchors["GROSS"][0] - 100].T)
          if y >= head_y]
    top = ys[0] if ys else head_y + 30
    bottom = ys[-1] if len(ys) > 1 else arr.shape[0] - 40

    peaks = _line_peaks(arr[top + 15:bottom - 15, :])

    def between(a, b, last=False):
        c = [p for p in peaks if a <= p <= b]
        return (c[-1] if last else c[0]) if c else (a + b) // 2

    a = anchors
    x1 = between(a["SHIPPER"][0] - 400, a["SHIPPER"][0], last=True)
    x2 = between(a["SHIPPER"][1], a["CONSIGNEE"][0], last=True)
    x3 = between(a["CONSIGNEE"][1], a["QUANTITY"][0], last=True)
    x4 = between(a["QUANTITY"][1], a["DESCRIPTION"][0])
    x5 = between(a["DESCRIPTION"][1] + 200, a["GROSS"][0])
    x6 = between(a["DESCRIPTION"][1] + 200, a["GROSS"][0], last=True)
    left = between(x_min, x1 - 40) if [p for p in peaks if x_min <= p <= x1 - 40] else x1 - 130
    return top, bottom, {"sl": (left, x1), "shipper": (x1, x2), "consignee": (x2, x3),
                         "qty": (x3, x4), "desc": (x4, x5), "gross": (x6, min(x6 + 330, gray.width))}


def _ocr_cells(gray, top, bottom, cols):
    import pytesseract
    out = {}
    for name, (a, b) in cols.items():
        crop = gray.crop((a + 8, top + 8, b - 8, bottom - 8))
        cfg = "--psm 6 -c tessedit_char_whitelist=0123456789" if name == "sl" else "--psm 6"
        out[name] = pytesseract.image_to_string(crop, config=cfg)
    return out


def _page_head(gray, anchors):
    """Ligne « M.V. ... Port of Loading ... Port of Discharging », juste au-dessus
    du tableau : recadrée et agrandie (petite police, marges de scan bruitées)."""
    import pytesseract
    y = min(a[2] for a in anchors.values())
    crop = gray.crop((max(0, anchors["SHIPPER"][0] - 350), max(0, y - 160),
                      min(gray.width, anchors["GROSS"][1] + 200), y - 70))
    return pytesseract.image_to_string(crop.resize((crop.width * 2, crop.height * 2)), config="--psm 6")


# ---------------------------------------------------------------------------
# Variante « MR.NO » : une ligne du tableau par lot
# ---------------------------------------------------------------------------
_COLS_MR = ["mr", "shipper", "consignee", "marks", "desc", "pkgs", "gross", "remark"]
_OCR_CONFUS = {"5": "[5S]", "S": "[5S]", "8": "[8B]", "B": "[8B]", "0": "[0O]", "O": "[0O]",
               "1": "[1I]", "I": "[1I]", "2": "[2Z]", "Z": "[2Z]"}


def _mr_bl(cell: str, voyage: str) -> str:
    """N° MR (1re ligne) ; le n° de voyage qu'il contient est recalé sur celui de l'en-tête
    (OCR : « PLPES83XMAA001 » pour PLPE583XMAA001, voyage 583X)."""
    mr = _clean_id(_first_line(cell).split()[0]) if _first_line(cell) else ""
    core = re.sub(r"^V", "", voyage or "")
    if mr and len(core) >= 3:
        motif = "".join(_OCR_CONFUS.get(c, re.escape(c)) for c in core)
        mr = re.sub(motif, core, mr, count=1)
    return mr


def _mr_lots(gray, anchors) -> tuple[list[dict], dict, str]:
    """-> (lots, totaux annoncés {pkgs, gross}, en-tête OCR) d'une page au format MR."""
    import numpy as np
    import pytesseract
    arr = np.asarray(gray) < SEUIL_SOMBRE
    y_tete = min(a[2] for a in anchors.values())
    hs = _line_peaks(arr[:, anchors["DESCRIPTION"][0]:anchors["GROSS"][0] - 100].T)
    haut = max([y for y in hs if y < y_tete - 15] or [max(0, y_tete - 60)])
    crop = gray.crop((0, max(0, haut - 260), gray.width, max(1, haut - 5)))
    tete = pytesseract.image_to_string(crop.resize((crop.width * 2, crop.height * 2)), config="--psm 6")
    bandes = [(a, b) for a, b in zip(hs, hs[1:]) if a >= y_tete - 15 and b - a > 100]
    verticaux = [_line_peaks(arr[a + 10:b - 10, :]) for a, b in bandes]
    ref = next((v for v in verticaux if len(v) == len(_COLS_MR) + 1), None)
    lots, totaux = [], {}
    if ref is None:
        return lots, totaux, tete
    for (a, b), v in zip(bandes, verticaux):
        v = v if len(v) == len(ref) else ref        # trait coupé : colonnes de la ligne voisine
        cell = {}
        for nom, (x0, x1) in zip(_COLS_MR, zip(v, v[1:])):
            cell[nom] = pytesseract.image_to_string(gray.crop((x0 + 8, a + 6, x1 - 8, b - 6)), config="--psm 6")
        n = re.findall(r"\d+", cell["pkgs"])
        g = re.search(r"\d[\d,]*(?:\.\d+)?", re.sub(r"\s", "", cell["gross"]))
        qty = int(n[0]) if n else None
        gross = float(g.group(0).replace(",", "")) if g else None
        if TOTAL_RE.search(cell["desc"] + " " + cell["mr"]):
            totaux = {"pkgs": qty, "gross": gross}
            break
        if not (cell["desc"].strip() or qty or gross):
            continue
        lots.append({"mr": cell["mr"], "shipper": cell["shipper"], "consignee": cell["consignee"],
                     "desc": cell["desc"], "qty": qty, "gross": gross, "marks": cell["marks"]})
    return lots, totaux, tete


# ---------------------------------------------------------------------------
# Interprétation d'un lot
# ---------------------------------------------------------------------------
def _clean_id(tok: str) -> str:
    return re.sub(r'[^A-Z0-9\-]', '', tok.upper().replace("}", "J").replace("{", "J"))


def _fix_vin(c: str) -> str:
    """I et O n'existent pas dans un VIN (ISO 3779) : toujours une confusion OCR."""
    return c.replace("I", "1").replace("O", "0") if len(c) == 17 else c


def _vin_check_ok(c: str) -> bool:
    """Clé de contrôle ISO 3779 (9e car.). Vrai si non applicable (autre format)."""
    if len(c) != 17 or not (c[8].isdigit() or c[8] == "X"):
        return True
    vals = dict(zip("ABCDEFGHJKLMNPRSTUVWXYZ", [1, 2, 3, 4, 5, 6, 7, 8, 1, 2, 3, 4, 5, 7, 9, 2, 3, 4, 5, 6, 7, 8, 9]))
    poids = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]
    r = sum((int(ch) if ch.isdigit() else vals.get(ch, 0)) * p for ch, p in zip(c, poids)) % 11
    return ("X" if r == 10 else str(r)) == c[8]


def _first_line(cell: str) -> str:
    lines = [l.strip(" ,.;") for l in cell.split("\n") if l.strip(" ,.;'‘|")]
    return lines[0] if lines else ""


def _extract_units(desc: str):
    """-> ([{chassis, engine, start, end}], listes PIN/SERIAL) depuis la description."""
    lines = [l.strip() for l in desc.split("\n") if l.strip()]
    lists = {"PIN": [], "UNIT": [], "CHASSIS": [], "ENGINE": []}
    units, mode, held_engine, pending_engine, seg = [], None, "", False, 0
    for i, line in enumerate(lines):
        label = LIST_LABEL_RE.match(line)
        if label:
            mode = label.group(1).split()[0].upper()
            continue
        if mode:
            toks = [_clean_id(t) for t in re.split(r'[,\s]+', line) if t.strip(" .")]
            if toks and all(ID_RE.match(t) for t in toks):
                lists[mode].extend(toks)
                continue
            mode = None
        if pending_engine:
            pending_engine = False
            m = re.match(r'^([A-Z0-9]{5,})\b', line)
            if m and units:
                units[-1]["engine"] = m.group(1)
                continue
        cm = CHASSIS_INLINE_RE.search(line)
        if cm:
            units.append({"chassis": _fix_vin(_clean_id(cm.group(1))), "engine": held_engine,
                          "start": seg, "end": i})
            held_engine, seg = "", i + 1
        em = ENGINE_RE.search(line)
        if em:
            if not em.group(1):
                pending_engine = True
            elif units and not units[-1]["engine"]:
                units[-1]["engine"] = em.group(1)
            else:
                held_engine = em.group(1)
    if lists["PIN"]:                 # liste Caterpillar : le PIN identifie la machine
        units = [{"chassis": c, "engine": "", "start": 0, "end": len(lines) - 1} for c in lists["PIN"]]
    elif not units and lists["CHASSIS"]:
        units = [{"chassis": c, "engine": "", "start": 0, "end": len(lines) - 1} for c in lists["CHASSIS"]]
    if len(units) == 1:              # unité seule : toute la description la concerne
        units[0].update(start=0, end=len(lines) - 1)
    return units, lists, lines


def _brand(seg: str, shipper: str, chassis: str) -> str:
    up, cp = seg.upper(), _compact(seg)
    for key, brand in _ENGIN_BRANDS:
        if key in up or _compact(key) in cp:
            return brand
    if chassis.startswith("CAT") or "CATERPILLAR" in shipper.upper():
        return "Caterpillar"
    return vm.find_brand(seg, shipper, [chassis] if chassis else None) or ""


def _model(seg_lines: list[str]) -> str:
    seg = " ".join(seg_lines)
    for line in seg_lines:
        m = re.match(r'^JCB\s+(.+)$', line, re.I)
        if m:
            return m.group(1).strip()
    m = STARRED_MODEL_RE.search(seg)
    if m:
        return m.group(1)
    for line in seg_lines:
        m = HEAD_QTY_RE.match(line)
        if m:
            return m.group(2).strip()
    cp = _compact(seg)
    return next((lib for k, lib in _MODEL_KEYWORDS if k in cp), "")


def _etat(seg: str) -> str:
    if USED_RE.search(seg):
        return "Usager"
    return "Neuf" if NEW_RE.search(AVEC_NEUF_RE.sub(" ", COMPRESSOR_RE.sub(" ", seg))) else ""


def _year(seg: str, chassis: str) -> int | None:
    m = YEAR_RE.search(seg)
    if m:
        return int(m.group(1))
    if len(chassis) == 17:
        y = _VIN_YEAR.get(chassis[9])
        if y and y <= datetime.date.today().year + 1:
            return y
    return None


def _lot_rows(lot: dict, pol: str, pod: str, warnings: list[str]) -> list[dict]:
    sl = lot["sl"] or "?"
    units, lists, lines = _extract_units(lot["desc"])
    full = " ".join(lines)
    colis = lot["qty"]
    colis_sup = 0
    obs_lot = []
    hq = next((HEAD_QTY_RE.match(l) for l in lines if HEAD_QTY_RE.match(l)), None)
    if hq and units and int(hq.group(1)) != len(units):
        obs_lot.append(f"{hq.group(1)} unites annoncees vs {len(units)} identifiants lus")
    if lists["PIN"] and lists["UNIT"]:
        bad = [c for c in lists["PIN"] if c[-8:] not in lists["UNIT"]]
        if bad:
            warnings.append(f"Lot {sl} : PIN sans numéro de série correspondant ({', '.join(bad)}) "
                            "— erreur OCR probable, vérifier sur le scan.")
    base = {"NATURE BL": "Import" if "ABIDJAN" in pod else "Export/Transbo",
            "POL TETRAX": pol, "POD TETRAX": pod, "FINAL DESTINATION TETRAX": pod,
            "TYPE / TAILLE": "", "VOLUME TETRAX": None, "BL": lot.get("bl", ""),
            "ANNEE DE FABRICATION": None, "CHÂSSIS": "",
            "TYPE D'ACTION": "IMPORT" if "ABIDJAN" in pod else "",
            "CLIENT": _first_line(lot["consignee"]), "LOT": sl,
            "_qty_declaree": colis, "_type_declare": "PACKAGE", "_ctrl_qty": colis,
            "_ctrl_weight": lot["gross"], "_SHIPPER": _first_line(lot["shipper"]),
            # « AS PER INVOICE & PACKING LIST » : détails (châssis, dimensions) dans les pièces du B/L
            "_PIECES_JOINTES": bool(re.search(r"INVOICE|PACKING", f"{lot.get('marks', '')} {full}", re.I))}

    def colis_rows(n: int, poids_total: float | None, note: str, libelle: str = "") -> list[dict]:
        """Lignes « Colis » : description reprise de « 7 X SKID... » si elle
        correspond au nombre de colis, sinon le libellé donné, sinon à identifier par l'agent."""
        desc = next((m.group(2).strip() for m in map(HEAD_QTY_RE.match, lines)
                     if m and int(m.group(1)) == n), "") or libelle or "Colis a identifier"
        out = []
        for k in range(n):
            p = None
            if poids_total is not None:         # reste d'arrondi sur le dernier colis
                p = round(poids_total / n)
                p = p if k < n - 1 else round(poids_total) - p * (n - 1)
            out.append({**base, "CATEGORIE": "Colis", "POIDS TETRAX (KG)": p, "MARQUE": "",
                        "MODELE": desc, "MARQUE & MODELE": desc, "ETAT": "",
                        "OBSERVATION": note, "_ENGINE_NO": ""})
        return out

    if not units and not VEHICLE_WORD_RE.search(full) and not VEHICULE_COLLE_RE.search(_compact(full)):
        n = colis or 1
        warnings.append(f"Lot {sl} : {n} colis sans châssis ni véhicule décrit, ajoutés en lignes Colis.")
        return colis_rows(n, lot["gross"], "colis sans chassis")
    accessoires = bool(ACCESSOIRES_RE.search(_compact(full)))
    if not units:                    # véhicule décrit mais châssis non lu : à compléter
        n_veh = colis or 1
        if colis and colis > 1 and not hq and accessoires:
            # « RIG VEHICLE WITH NEW AIR COMPRESSOR AND STANDARD ACCESSORIES », 3 PKGS :
            # 1 véhicule, les autres colis sont ses équipements (décision du 23/11).
            n_veh, colis_sup = 1, colis - 1
            warnings.append(f"Lot {sl} : {colis} colis pour un véhicule décrit avec ses équipements "
                            f"— 1 véhicule et {colis_sup} colis EPM, à confirmer.")
        units = [{"chassis": "", "engine": "", "start": 0, "end": len(lines) - 1}
                 for _ in range(n_veh)]
        obs_lot.append("AUCUN CHASSIS EXTRAIT - a completer manuellement")
    elif colis and colis != len(units):
        ecart = colis - len(units)
        obs_lot.append(f"{colis} colis declares vs {len(units)} chassis")
        if ecart > 0:
            colis_sup = ecart
            warnings.append(f"Lot {sl} : {colis} colis déclarés pour {len(units)} châssis "
                            f"— {ecart} ajoutés en lignes Colis, poids à compléter.")
    n = len(units)
    w_tot = lot["gross"]
    u_w = round(w_tot / n) if w_tot else None
    if w_tot is None:
        obs_lot.append("POIDS NON LU - a completer")
    elif n > 1:
        obs_lot.append("poids du lot reparti a parts egales")
    if re.search(r'CARGO\s+IN\s+TRANSIT\s+TO', full, re.I):
        m = re.search(r'RESPONSIBILITY\s+CEASES\s+AT\s+([A-Z, ]+)', full, re.I)
        obs_lot.append("transit vers Abidjan" + (f", fin de responsabilite a {m.group(1).strip(' ,.')}" if m else ""))

    rows = []
    for k, u in enumerate(units):
        seg_lines = lines[u["start"]:u["end"] + 1]
        seg = " ".join(seg_lines)
        marque = _brand(seg, lot["shipper"], u["chassis"])
        modele = _model(seg_lines)
        obs = list(obs_lot)
        if not _vin_check_ok(u["chassis"]):
            obs.append("cle VIN non conforme : verifier le chassis sur le scan")
        poids = u_w
        if u_w is not None and k == n - 1:      # reste d'arrondi : somme = poids du lot
            poids = round(w_tot) - u_w * (n - 1)
        rows.append({**base, "CATEGORIE": "Vehicule", "POIDS TETRAX (KG)": poids, "MARQUE": marque,
                     "MODELE": modele, "MARQUE & MODELE": f"{marque} {modele}".strip(),
                     "ETAT": _etat(seg), "ANNEE DE FABRICATION": _year(seg, u["chassis"]),
                     "_ANNEE_MANIFESTE": _year(seg, ""),
                     "OBSERVATION": " ; ".join(obs), "CHÂSSIS": u["chassis"],
                     "_ENGINE_NO": u["engine"],
                     # équipements cités sans colis à part -> EPM/ACCESSORIES au pré-masque
                     "_COLIS_BL": "ACCESSORIES" if accessoires and not colis_sup else None})
    if colis_sup:
        rows.extend(colis_rows(colis_sup, None, "colis sans chassis - poids compris dans le lot, a detailler",
                               "ACCESSORIES" if accessoires else ""))
    return rows


def _clean_port(p: str) -> str:
    """« ENNORE SEA PORT, INDIA » -> « ENNORE » ; OCR « ABIDIAN » -> « ABIDJAN »."""
    p = re.split(r",|\s+(?:SEA\s+)?(?:PORT|PT)\b", (p or "").strip().upper())[0].strip()
    return "ABIDJAN" if re.match(r"ABID\w{1,3}N", p) else p


def parse_cargo_scan_manifest(src, source_label: str = "", progress_cb=None):
    """-> (DataFrame, warnings, meta). Lève ManifestReadError / ManifestFormatError."""
    data = src if isinstance(src, (bytes, bytearray)) else src.read()
    data = bytes(data)
    navire = voyage = pol = pod = ""
    lots: list[dict] = []
    warnings: list[str] = []
    format_mr, totaux_mr = False, []
    for pno, total, img in _pages(data):
        gray, anchors, fmt = _find_table(img)
        if fmt == "mr":
            format_mr = True
            lots_p, tot, tete = _mr_lots(gray, anchors)
            tete = " ".join(tete.split())
            m = VESSEL_RE.search(tete)
            if m:
                navire = navire or m.group(1).strip().upper()
                voyage = voyage or re.sub(r'[\s.]', '', m.group(2)).upper()
            m = ROUTE_RE.search(tete)
            if m:
                pol = pol or _clean_port(m.group(1))
                pod = pod or _clean_port(m.group(2))
            if not lots_p:
                warnings.append(f"Page {pno} : aucun lot lu dans le tableau — page à saisir manuellement.")
            for lot in lots_p:
                lots.append({**lot, "page": pno, "sl": str(len(lots) + 1), "bl": _mr_bl(lot["mr"], voyage)})
            if tot:
                totaux_mr.append(tot)
            if progress_cb:
                progress_cb(pno, total)
            continue
        if gray is None:
            if pno == 1:
                raise ManifestFormatError(
                    "Ce PDF n'est pas un « CARGO MANIFEST » scanné (colonnes SL.No / Shipper / "
                    "Consignee / Quantity / Description / Gross Weight, ou MR.NO / Shippers / Consignees / "
                    "Description / No.of Pkgs / Gross Weight / Remark non trouvées). "
                    "Utilisez l'onglet du bon type de manifeste.")
            warnings.append(f"Page {pno} : tableau non reconnu, page ignorée — à saisir manuellement.")
            if progress_cb:
                progress_cb(pno, total)
            continue
        top, bottom, cols = _table_box(gray, anchors)
        head = " ".join(_page_head(gray, anchors).split())
        m = VESSEL_RE.search(head)
        if m:
            navire = navire or m.group(1).strip().upper()
            voyage = voyage or re.sub(r'[\s.]', '', m.group(2)).upper()
        m = POL_RE.search(head)
        pol = pol or (_clean_port(m.group(1)) if m else "")
        m = POD_RE.search(head)
        pod = pod or (_clean_port(m.group(1)) if m else "")

        c = _ocr_cells(gray, top, bottom, cols)
        sl = re.findall(r'\d+', c["sl"])
        qty = QTY_RE.search(" ".join(c["qty"].split()))
        gross = WEIGHT_RE.search(re.sub(r'\s', '', c["gross"]))
        if len(sl) > 1:
            warnings.append(f"Page {pno} : plusieurs lots sur la page ({', '.join(sl)}), lus comme un "
                            "seul — format non testé, vérifier cette page.")
        if sl or qty or gross:
            lots.append({"page": pno, "sl": sl[0] if sl else "", "shipper": c["shipper"],
                         "consignee": c["consignee"], "desc": c["desc"],
                         "qty": int(qty.group(1)) if qty else None,
                         "gross": float(gross.group(1).replace(",", "")) if gross else None})
        elif lots:                       # page de suite : prolonge le lot en cours
            lots[-1]["desc"] += "\n" + c["desc"]
        if progress_cb:
            progress_cb(pno, total)

    pod = pod or "ABIDJAN"
    rows: list[dict] = []
    for lot in lots:
        rows.extend(_lot_rows(lot, pol, pod, warnings))
    if rows:
        df = pd.DataFrame(rows)
        df.insert(0, "NBRE", range(1, len(df) + 1))
        # Ordre fixe du Pré-Masque : mêmes colonnes et même ordre que les autres manifestes.
        visibles = [c for c in OUTPUT_COLUMNS if not c.startswith("_") and c not in ("OBSERVATION", "CHÂSSIS")]
        df = df[visibles + ["CATEGORIE", "CLIENT", "LOT", "OBSERVATION", "CHÂSSIS"]
                + [c for c in df.columns if c.startswith("_")]]
        sls = [int(l["sl"]) for l in lots if l["sl"]]
        if format_mr:
            warnings.insert(0, "N° de B/L = n° MR du manifeste, lu par OCR : à vérifier sur le scan. "
                               "Aucun volume ni châssis au manifeste : colonnes à compléter avant import.")
            lus_p = sum(l["qty"] or 0 for l in lots)
            lus_g = sum(l["gross"] or 0 for l in lots)
            for t in totaux_mr:
                if t.get("pkgs") is not None and t["pkgs"] != lus_p:
                    warnings.insert(1, f"Total colis annoncé {t['pkgs']}, {lus_p} lus : lot manquant ou mal lu.")
                if t.get("gross") is not None and abs(t["gross"] - lus_g) > 1:
                    warnings.insert(1, f"Poids total annoncé {t['gross']:,.0f} kg, {lus_g:,.0f} kg lus : vérifier les poids.")
        else:
            warnings.insert(0, "Ce manifeste ne porte ni N° de B/L ni volume : colonnes à compléter "
                               "avant import (chaque ligne garde son N° de lot, colonne LOT).")
        if sls and sls != list(range(sls[0], sls[-1] + 1)):
            warnings.insert(1, f"Numérotation des lots non continue ({', '.join(map(str, sls))}) : "
                               "vérifier qu'il ne manque pas de page pour Abidjan.")
    else:
        df = pd.DataFrame(columns=OUTPUT_COLUMNS + ["CATEGORIE", "CLIENT", "LOT", "_ENGINE_NO", "_SHIPPER"])
        warnings.append("Aucun lot extrait de ce PDF — vérifier qu'il s'agit bien d'un CARGO MANIFEST complet.")
    meta = {"navire": navire, "voyage": voyage, "nb_lots": len(lots), "total_declare": None}
    return df, warnings, meta
