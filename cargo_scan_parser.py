"""
Parseur « CARGO MANIFEST » scanné (formulaire agent : breakbulk Inde -> Abidjan)
-> DataFrame au format pré-masque IPAKI (mêmes colonnes que mol_manifest_parser,
pour réutiliser l'écran de vérification et generate_premasque_excel()).

Référence : M.V. UNION LUCK V3 (10/2026), 6 pages, 6 lots, Ennore -> Abidjan.

Structure source : scan (CamScanner) sans couche texte, pages tournées à 90°.
Un tableau par page, une colonne par rubrique :
  SL.No | Shipper | Consignee(s) party | Quantity | Description of Goods | Gross Weight
En-tête de page : « M.V. <navire> <voyage> », Port of Loading, Port of Discharging.

Particularités :
  - AUCUN N° de B/L ni volume : colonnes laissées vides, à compléter (rien n'est
    inventé). Le lot est identifié par la colonne LOT (SL.No).
  - Quantity compte des colis, pas des véhicules : la source de vérité des
    unités est la liste de châssis de la description. Écart = colis (caisses,
    skids...), signalé. Pour Caterpillar, le PIN (17 car.) sert de châssis.
  - Poids brut par lot : réparti à parts égales entre ses unités.
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
USED_RE = re.compile(r'\b(?:USED|RE-?CONDITIONED|REFUR\w*|REBUR\w*)\b', re.I)
COMPRESSOR_RE = re.compile(r'\bNEW\s+(?:-\s*)?(?:ELGI\s+|CHICAGO\s+)?(?:PNEUMATIC\s+)?AIR\s+COMPRESSOR', re.I)
NEW_RE = re.compile(r'\bNEW\b', re.I)
VESSEL_RE = re.compile(r'M\s*\.?\s*V\s*\.?\s+([A-Z][A-Z ]+?)\s+(V[\s.]*\d\S*)', re.I)
POL_RE = re.compile(r'P\w{2,3}\s+\w{1,2}\s+L\w{2,3}din\w*\s*[:;.\-]*\s*(.+?)(?=\s+P\w{2,3}\s+\w{1,2}\s+Disch|$)', re.I)
POD_RE = re.compile(r'P\w{2,3}\s+\w{1,2}\s+Disch\w*\s*[:;.]?\s*(\S+)', re.I)

# Année-modèle ISO 3779 (10e caractère du VIN), cycle 2010-2039.
_VIN_YEAR = {c: 2010 + i for i, c in enumerate("ABCDEFGHJKLMNPRSTVWXY123456789")}

# Marques d'engins absentes du référentiel voitures (ordre = priorité).
_ENGIN_BRANDS = [("JCB", "JCB"), ("ASHOK LEYLAND", "Ashok Leyland"),
                 ("AMW MOTORS", "AMW"), ("CATERPILLAR", "Caterpillar")]
_MODEL_KEYWORDS = ["DTH DRILL", "RIG SUPPORT VEHICLE", "RIG VEHICLE"]


def is_scan_pdf(data: bytes) -> bool:
    """Vrai si la 1re page n'a pas de texte exploitable (CamScanner y laisse
    seulement un filigrane de quelques caractères)."""
    import fitz
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
    import fitz
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
            "description": "DESCRIPTION", "gross": "GROSS"}
    found = {}
    for txt, x, y, w, h in zip(d["text"], d["left"], d["top"], d["width"], d["height"]):
        low = (txt or "").lower()
        for k, v in keys.items():
            if k in low and (v not in found or y * 2 < found[v][2] - 40):   # le plus haut
                found[v] = (x * 2, (x + w) * 2, (y + h) * 2)
    return found


def _find_table(img):
    """Cherche l'orientation où les 5 rubriques sont lues.
    -> (image N&B, ancres) ou (None, {}). L'OSD se trompe sur les pages creuses."""
    gray = img.convert("L")
    for angle in (0, 180, 90, 270):
        candidate = gray.rotate(angle, expand=True) if angle else gray
        anchors = _header_anchors(candidate)
        if len(anchors) == 5:
            return candidate, anchors
    return None, {}


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
    up = seg.upper()
    for key, brand in _ENGIN_BRANDS:
        if key in up:
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
    up = seg.upper()
    return next((k for k in _MODEL_KEYWORDS if k in up), "")


def _etat(seg: str) -> str:
    if USED_RE.search(seg):
        return "Usager"
    return "Neuf" if NEW_RE.search(COMPRESSOR_RE.sub(" ", seg)) else ""


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
    obs_lot = []
    hq = next((HEAD_QTY_RE.match(l) for l in lines if HEAD_QTY_RE.match(l)), None)
    if hq and units and int(hq.group(1)) != len(units):
        obs_lot.append(f"{hq.group(1)} unites annoncees vs {len(units)} identifiants lus")
    if lists["PIN"] and lists["UNIT"]:
        bad = [c for c in lists["PIN"] if c[-8:] not in lists["UNIT"]]
        if bad:
            warnings.append(f"Lot {sl} : PIN sans numéro de série correspondant ({', '.join(bad)}) "
                            "— erreur OCR probable, vérifier sur le scan.")
    if not units:
        units = [{"chassis": "", "engine": "", "start": 0, "end": len(lines) - 1}
                 for _ in range(colis or 1)]
        obs_lot.append("AUCUN CHASSIS EXTRAIT - a completer manuellement")
    elif colis and colis != len(units):
        ecart = colis - len(units)
        obs_lot.append(f"{colis} colis declares vs {len(units)} chassis")
        if ecart > 0:
            warnings.append(f"Lot {sl} : {colis} colis déclarés pour {len(units)} châssis "
                            f"— {ecart} colis sans châssis, à traiter en colis si besoin.")
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
        rows.append({
            "NATURE BL": "Import" if "ABIDJAN" in pod else "Export/Transbo",
            "POL TETRAX": pol, "POD TETRAX": pod, "FINAL DESTINATION TETRAX": pod,
            "POIDS TETRAX (KG)": poids, "TYPE / TAILLE": "", "VOLUME TETRAX": None, "BL": "",
            "MARQUE": marque, "MODELE": modele, "MARQUE & MODELE": f"{marque} {modele}".strip(),
            "ETAT": _etat(seg), "ANNEE DE FABRICATION": _year(seg, u["chassis"]),
            "TYPE D'ACTION": "IMPORT" if "ABIDJAN" in pod else "",
            "CLIENT": _first_line(lot["consignee"]), "LOT": sl,
            "OBSERVATION": " ; ".join(obs), "CHÂSSIS": u["chassis"],
            "_qty_declaree": colis, "_type_declare": "PACKAGE", "_ctrl_qty": colis,
            "_ctrl_weight": w_tot, "_ENGINE_NO": u["engine"], "_SHIPPER": _first_line(lot["shipper"]),
        })
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
    for pno, total, img in _pages(data):
        gray, anchors = _find_table(img)
        if gray is None:
            if pno == 1:
                raise ManifestFormatError(
                    "Ce PDF n'est pas un « CARGO MANIFEST » scanné (colonnes SL.No / Shipper / "
                    "Consignee / Quantity / Description / Gross Weight non trouvées). "
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
        sls = [int(l["sl"]) for l in lots if l["sl"]]
        warnings.insert(0, "Ce manifeste ne porte ni N° de B/L ni volume : colonnes à compléter "
                           "avant import (chaque ligne garde son N° de lot, colonne LOT).")
        if sls and sls != list(range(sls[0], sls[-1] + 1)):
            warnings.insert(1, f"Numérotation des lots non continue ({', '.join(map(str, sls))}) : "
                               "vérifier qu'il ne manque pas de page pour Abidjan.")
    else:
        df = pd.DataFrame(columns=OUTPUT_COLUMNS + ["CLIENT", "LOT", "_ENGINE_NO", "_SHIPPER"])
        warnings.append("Aucun lot extrait de ce PDF — vérifier qu'il s'agit bien d'un CARGO MANIFEST complet.")
    meta = {"navire": navire, "voyage": voyage, "nb_lots": len(lots), "total_declare": None}
    return df, warnings, meta
