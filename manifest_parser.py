"""
Prototype - Parseur de manifestes cargo Grimaldi (format PBREPORT)
Approche: parsing deterministe base sur les positions de colonnes (pipes)
plutot que LLM, car le rapport est genere par machine avec un gabarit fixe.
"""
import re
import pdfplumber
import pandas as pd

BL_RE = re.compile(r'^\[?([A-Z]?\d{6,})\]?(\[T\])?$')
CONTAINER_RE = re.compile(r'^CN\s*:\s*(\S+)$')
SEAL_RE = re.compile(r'^SN\s*:\s*(\S+)$')
WEIGHT_RE = re.compile(r'^([\d,]+\.\d{2})$')
CBM_RE = re.compile(r'^([\d,]+\.\d{3})\s*CBM$')
LM_RE = re.compile(r'^([\d,]+\.\d{2})\s*LM$')
DATE_RE = re.compile(r'DATED\s+([\d/\-]+)')
ORIG_BL_RE = re.compile(r'ORIGINAL BILL OF LADING\s+(\S+)')
FREIGHT_RE = re.compile(r'Freight payable at\s*:\s*(.+)')
HS_CODE_RE = re.compile(r'H\.?S\.?\s*CODE\s*:\s*(\S+)', re.I)
MODEL_YEAR_RE = re.compile(r'Model\s*Year\s*:?\s*(\d{4})|MODEL\s*:\s*(\d{4})', re.I)
TRANSIT_TO_RE = re.compile(r'TRANSIT TO\s*:?\s*([A-Z][A-Za-z]+)', re.I)
LOCAL_AREA_RE = re.compile(
    r'ABIDJAN|IVORY COAST|COTE D|CÔTE D|C\u2019?OTE D|TREICHVILLE|COCODY|YOPOUGON|MARCORY|'
    r'PLATEAU|ADJAME|KOUMASSI|PORT[- ]?BOUET|BINGERVILLE|ANYAMA|RIVIERA|ANGRE|ATTECOUBE|ABOBO',
    re.I)
FT_SIZE_RE = re.compile(r'(\d{2})\s*ft', re.I)
COLOR_RE = re.compile(r'COLOR\s*:\s*([A-Za-z /]+?)(?:\s{2,}|$|\||H\.?S)', re.I)
VEHICLE_TYPE_RE = re.compile(r"Van\(s\)|Car\(s\)|RoRo|Tractor", re.I)
FOOTER_MARKERS = ("Totals For", "Grand Totals", "Summary Totals", "End Of Report")
# En-têtes de tableau répétés en haut de chaque page -> à ignorer entièrement
HEADER_ROW_MARKERS = (
    "B/L No.", "SHIPPER(SH), CONSIGNEE(CN), NOTIFY(NO", "Marks And Nos.;",
    "Numbers And Kind Of Packages;", "Name Of Ship And Voyage No.",
    "Nationality Of Ship", "Name Of Master", "Place Of Receipt",
    "CARGO MANIFEST", "Grimaldi Deep Sea S.p.A.", "Move Type", "Origin Port",
    "Port Where & When Report is made", "Weight(Kgs)", "Charge Information",
)


def extract_rows(pdf_path):
    """Extrait toutes les lignes de toutes les pages, splittees par colonnes (pipe)."""
    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for pno, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            for line in text.split("\n"):
                cols = [c.strip() for c in line.split("|")]
                # retire la 1ere colonne vide (avant le premier pipe) et la derniere si vide
                if cols and cols[0] == "":
                    cols = cols[1:]
                if cols and cols[-1] == "":
                    cols = cols[:-1]
                rows.append((pno, cols))
    return rows


def is_separator(cols):
    if not cols:
        return True
    joined = "".join(cols).strip()
    return joined == "" or set(joined) <= {"-"}


def is_footer(cols):
    joined = " ".join(cols)
    return any(m in joined for m in FOOTER_MARKERS)


def get(cols, i):
    return cols[i].strip() if i < len(cols) else ""


def parse_manifest(pdf_path, source_label):
    rows = extract_rows(pdf_path)

    context = {
        "vessel_voyage": "", "move_type": "", "origin_port": "",
        "port_of_loading": "", "port_of_discharge": "",
    }

    records = []
    current = None  # dict pour le B/L en cours
    state = None  # "SH" | "CN" | "NO"

    def flush():
        nonlocal current
        if current:
            records.append(current)
        current = None

    for idx, (pno, cols) in enumerate(rows):
        if not cols or is_separator(cols):
            continue
        if is_footer(cols):
            continue
        if any(marker in cols for marker in HEADER_ROW_MARKERS):
            continue

        # --- Detection / mise a jour du contexte de section ---
        # Ligne "Nom navire / Lieu rapport / Sens / Port origine / Date depart POL".
        # Reperee par structure (colonne "Sens" = "H : H" / "P : P" + colonne 0
        # au format "NAVIRE : VOYAGE"), PAS par le nom d'un navire particulier
        # (un manifeste peut concerner n'importe quel navire de la flotte).
        if (get(cols, 0) and ":" in get(cols, 0) and len(cols) >= 3
                and get(cols, 2) in ("H : H", "P : P")):
            context["vessel_voyage"] = get(cols, 0)
            context["move_type"] = get(cols, 2)
            context["origin_port"] = get(cols, 3) if len(cols) > 3 else ""
            continue
        if get(cols, 0) == "Italy" and len(cols) >= 4:
            context["port_of_loading"] = get(cols, 3)
            context["port_of_discharge"] = get(cols, 4) if len(cols) > 4 else ""
            continue

        col0 = get(cols, 0)
        m = BL_RE.match(col0)
        if m:
            # nouveau B/L -> on cloture le precedent
            flush()
            current = {
                "source_file": source_label,
                "vessel_voyage": context["vessel_voyage"],
                "move_type": context["move_type"],
                "origin_port": context["origin_port"],
                "port_of_loading": context["port_of_loading"],
                "port_of_discharge": context["port_of_discharge"],
                "bl_number": m.group(1),
                "transshipment": bool(m.group(2)),
                "shipper_name": "", "shipper": [], "consignee_name": [], "consignee_address": [],
                "notify_name": [], "notify_address": [],
                "items": [],  # liste d'items {qty, type_raw, weight, tare, cbm, lm, chassis, container_no, seal_no}
                "freight_payable_at": "", "original_bl_ref": "", "original_bl_date": "",
                "raw_desc_lines": [],
            }
            state = "SH"

        if current is None:
            continue  # lignes hors-B/L (avant le 1er record) -> ignorees

        c1 = get(cols, 1)  # colonne SHIPPER/CONSIGNEE/NOTIFY
        c2 = get(cols, 2)  # colonne Unit No.
        c3 = get(cols, 3)  # colonne Description
        c4 = get(cols, 4)  # colonne Weight
        c5 = get(cols, 5)  # colonne Measurement

        def active_item():
            if not current["items"]:
                current["items"].append({"qty": 1, "type_raw": "", "weight": None, "tare": None,
                                          "cbm": None, "lm": None, "chassis": [],
                                          "container_no": [], "seal_no": []})
            return current["items"][-1]

        # --- colonne 1 : shipper / consignee / notify ---
        if c1:
            if c1.startswith("SH:"):
                state = "SH"
                name = c1[3:].strip()
                current["shipper_name"] = name
                current["shipper"].append(name)
            elif c1.startswith("CN:"):
                state = "CN"
                current["consignee_name"].append(c1[3:].strip())
            elif re.match(r'^NO\[\d+\]:', c1):
                state = "NO"
                current["notify_name"].append(re.sub(r'^NO\[\d+\]:', '', c1).strip())
            else:
                if state == "SH":
                    current["shipper"].append(c1)
                elif state == "CN":
                    current["consignee_address"].append(c1)
                elif state == "NO":
                    current["notify_address"].append(c1)

        # --- colonne 2 : conteneur / scellé / chassis (rattachés à l'item actif) ---
        if c2:
            mc = CONTAINER_RE.match(c2)
            ms = SEAL_RE.match(c2)
            if mc:
                active_item()["container_no"].append(mc.group(1))
            elif ms:
                active_item()["seal_no"].append(ms.group(1))
            elif c2 == "CHASSIS NOS :":
                pass
            elif re.match(r'^[A-Z0-9]{10,}$', c2):
                active_item()["chassis"].append(c2)

        # --- colonne 3 : description / type de colis (créé un nouvel item) / infos service ---
        if c3:
            fm = FREIGHT_RE.search(c3)
            om = ORIG_BL_RE.search(c3)
            dm = DATE_RE.search(c3)
            qty_m = re.match(r'^(\d+)[\s\-]+(.*(?:Van|Cargo|Cube|Car|LM RoRo|PIECE|CRATE|Tractor|PACKAGE).*)$', c3, re.I)
            if fm:
                current["freight_payable_at"] = fm.group(1).strip()
            elif om:
                current["original_bl_ref"] = om.group(1)
            elif dm:
                current["original_bl_date"] = dm.group(1)
            elif qty_m:
                current["items"].append({
                    "qty": int(qty_m.group(1)), "type_raw": qty_m.group(2).strip(),
                    "weight": None, "tare": None, "cbm": None, "lm": None,
                    "chassis": [], "container_no": [], "seal_no": [],
                })
            elif c3 == "TARE":
                pass  # le tare est en colonne weight, gere plus bas
            elif c3 == "Service B/L":
                pass  # marqueur de type de B/L, pas un type de colis
            else:
                current["raw_desc_lines"].append(c3)

        # --- colonne 4 : poids (gross ou tare selon description), rattaché à l'item actif ---
        if c4:
            wm = WEIGHT_RE.match(c4.replace(",", ""))
            if wm:
                val = float(wm.group(1))
                if c3 == "TARE":
                    active_item()["tare"] = val
                else:
                    active_item()["weight"] = val

        # --- colonne 5 : CBM ou LM, rattaché à l'item actif ---
        if c5:
            cm = CBM_RE.match(c5)
            lmm = LM_RE.match(c5)
            if cm:
                active_item()["cbm"] = float(cm.group(1).replace(",", ""))
            elif lmm:
                active_item()["lm"] = float(lmm.group(1).replace(",", ""))

    flush()
    return records


def simplify_type_colis(type_raw):
    """Réduit le type de colis à l'information essentielle.
    Conteneur -> taille en ft ('20'/'40'). Véhicule -> catégorie courte.
    Divers -> 'Colis'/'Caisse'. Retourne (libelle, code C/V/D)."""
    ft = FT_SIZE_RE.search(type_raw)
    if ft:
        return ft.group(1), "C"
    if re.search(r'Small Van', type_raw, re.I):
        return "Van léger", "V"
    if re.search(r'Big Van', type_raw, re.I):
        return "Van lourd", "V"
    if re.search(r'Car\(s\)', type_raw, re.I):
        return "Voiture", "V"
    if re.search(r'RoRo', type_raw, re.I):
        return "RoRo", "V"
    if re.search(r'Tractor|Construction Equip', type_raw, re.I):
        return "Engin lourd", "V"
    if re.search(r'CRATE|PIECE|PACKAGE', type_raw, re.I):
        return "Colis", "D"
    return (type_raw[:20] if type_raw else ""), "D"


def detect_transit(full_desc, consignee_addr, notify_addr):
    """Detecte si la marchandise transite au-dela d'Abidjan (regime transit
    vers pays enclave : Mali, Burkina Faso, Niger...), PAS le transbordement
    navire-a-navire (deja capture par Port_Origine_Transbordement).
    Retourne (bool_transit, pays_detecte_ou_vide, niveau_confiance)."""
    m = TRANSIT_TO_RE.search(full_desc)
    if m:
        return True, m.group(1).strip().title(), "haute"
    addr = " ".join(consignee_addr + notify_addr)
    if addr.strip() and not LOCAL_AREA_RE.search(addr):
        # aucune reference locale (Abidjan/quartier/Cote d'Ivoire) dans l'adresse
        return True, "", "faible"
    return False, "", "haute"


COMMUNES_ABIDJAN = [
    "TREICHVILLE", "COCODY", "YOPOUGON", "MARCORY", "PLATEAU", "ADJAME",
    "KOUMASSI", "PORT-BOUET", "PORT BOUET", "BINGERVILLE", "ANYAMA",
    "ATTECOUBE", "ABOBO", "RIVIERA", "ANGRE", "AKOUEDO", "SONGON", "TREICHIVLLE",
]
COUNTRY_PATTERNS = [
    (re.compile(r"IVORY COAST|COTE D.?IVOIRE|C.TE D.IVOIRE", re.I), "Côte d'Ivoire"),
    (re.compile(r"\bMALI\b", re.I), "Mali"),
    (re.compile(r"BURKINA", re.I), "Burkina Faso"),
    (re.compile(r"\bNIGER\b", re.I), "Niger"),
    (re.compile(r"SENEGAL", re.I), "Sénégal"),
    (re.compile(r"U\.?S\.?A\.?\b|UNITED STATES", re.I), "États-Unis"),
    (re.compile(r"\bITALY\b", re.I), "Italie"),
    (re.compile(r"PORTUGAL", re.I), "Portugal"),
    (re.compile(r"SAUDI ARAB", re.I), "Arabie Saoudite"),
    (re.compile(r"SOUTH AFRICA", re.I), "Afrique du Sud"),
]


def simplify_address(addr):
    """Reduit une adresse brute a l'essentiel : Commune, Ville, Pays.
    Best-effort (liste de communes/pays connus) ; a completer si de
    nouvelles zones apparaissent dans de futurs manifestes."""
    if not addr:
        return ""
    commune = next((c for c in COMMUNES_ABIDJAN if re.search(re.escape(c), addr, re.I)), None)
    ville = "Abidjan" if (commune or re.search(r'\bABIDJAN\b', addr, re.I)) else ""
    pays = ""
    for pat, name in COUNTRY_PATTERNS:
        if pat.search(addr):
            pays = name
            break
    parts = [p for p in [commune.title() if commune else None, ville, pays] if p]
    return ", ".join(parts)


def item_status(type_raw, desc_context):
    """Neuf si 'NEW' mentionné pour cet item (dans son libellé ou le contexte
    descriptif proche), Occasion si 'USED', vide sinon."""
    text = type_raw + " " + desc_context
    if re.search(r'\bNEW\b', text, re.I):
        return "Neuf"
    if re.search(r'\bUSED\b', text, re.I):
        return "Usager"
    return ""


def records_to_dataframe(records):
    """Vue groupee : 1 ligne = 1 (B/L, Type de colis simplifie).
    Les items de meme type au sein d'un meme B/L sont additionnes (quantite,
    poids, volume)."""
    rows = []
    for r in records:
        full_desc = " | ".join(dict.fromkeys(r["raw_desc_lines"]))
        is_transit, transit_pays, transit_conf = detect_transit(
            full_desc, r["consignee_address"], r["notify_address"])
        nav_m = re.match(r'^(.*?)\s*:\s*(\S+)$', r["vessel_voyage"])
        if nav_m:
            navire = nav_m.group(1).strip()
            voyage = nav_m.group(2).strip()
        else:
            # Format de ligne inattendu (variante de gabarit non encore vue) :
            # on ne laisse jamais le nom de navire silencieusement vide, pour
            # que l'agent le remarque et le complète manuellement.
            navire = r["vessel_voyage"].strip() or "(navire non détecté)"
            voyage = ""
        addr_simple = simplify_address(", ".join(r["consignee_address"]))

        for it in r["items"]:
            type_simple, type_code = simplify_type_colis(it["type_raw"])
            statut = item_status(it["type_raw"], full_desc)
            rows.append({
                "Fichier": r["source_file"],
                "Navire": navire,
                "Voyage": voyage,
                "Port_Chargement": r["port_of_loading"],
                "BL_Numero": r["bl_number"],
                "Chargeur_Nom": r["shipper_name"],
                "Destinataire_Nom": " ".join(r["consignee_name"]).strip(),
                "Destinataire_Adresse": addr_simple,
                "No_Conteneur": "; ".join(it["container_no"]),
                "No_Scelle": "; ".join(it["seal_no"]),
                "Numeros_Chassis": "; ".join(it["chassis"]),
                "Type_Colis": type_simple,
                "_cat_code": type_code,
                "Etat": statut,
                "Nb_Unites": it["qty"],
                "Poids_Kg": it["weight"] or 0.0,
                "Tare_Kg": it["tare"] or 0.0,
                "Volume_CBM": it["cbm"] or 0.0,
                "Pays_Transit": transit_pays,
                "_transit_confiance": transit_conf,
            })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # Regroupement : meme B/L + meme type de colis simplifie -> on additionne
    group_keys = ["Fichier", "Navire", "Voyage", "Port_Chargement", "BL_Numero",
                  "Chargeur_Nom", "Destinataire_Nom", "Destinataire_Adresse",
                  "Type_Colis", "_cat_code", "Etat", "Pays_Transit", "_transit_confiance"]
    agg = df.groupby(group_keys, dropna=False, sort=False).agg(
        No_Conteneur=("No_Conteneur", lambda s: "; ".join(dict.fromkeys(x for x in s if x))),
        No_Scelle=("No_Scelle", lambda s: "; ".join(dict.fromkeys(x for x in s if x))),
        Numeros_Chassis=("Numeros_Chassis", lambda s: "; ".join(dict.fromkeys(x for x in s if x))),
        Nb_Unites=("Nb_Unites", "sum"),
        Poids_Kg=("Poids_Kg", "sum"),
        Tare_Kg=("Tare_Kg", "sum"),
        Volume_CBM=("Volume_CBM", "sum"),
    ).reset_index()
    return agg


# Colonnes retenues par onglet (dans l'ordre d'affichage)
SHEET_COLUMNS = {
    "Vehicule": ["Navire", "Voyage", "Port_Chargement", "BL_Numero", "Numeros_Chassis",
                 "Nb_Unites", "Poids_Kg", "Volume_CBM", "Etat", "Pays_Transit"],
    "Conteneur": ["Navire", "Voyage", "Port_Chargement", "BL_Numero", "No_Conteneur", "No_Scelle",
                  "Type_Colis", "Nb_Unites", "Poids_Kg", "Tare_Kg", "Volume_CBM",
                  "Chargeur_Nom", "Destinataire_Nom", "Destinataire_Adresse", "Pays_Transit"],
    "Colis": ["Navire", "Voyage", "Port_Chargement", "BL_Numero", "Type_Colis", "Nb_Unites",
              "Poids_Kg", "Volume_CBM", "Chargeur_Nom", "Destinataire_Nom",
              "Destinataire_Adresse", "Pays_Transit"],
}
CAT_CODE_TO_SHEET = {"V": "Vehicule", "C": "Conteneur", "D": "Colis"}

CARGO_TYPE_LABELS = {
    frozenset({"V"}): "🚗 Véhicules uniquement",
    frozenset({"C"}): "📦 Conteneurs uniquement",
    frozenset({"D"}): "📋 Colis uniquement",
    frozenset({"V", "C"}): "🔀 Mixte (Véhicules + Conteneurs)",
    frozenset({"V", "D"}): "🔀 Mixte (Véhicules + Colis)",
    frozenset({"C", "D"}): "🔀 Mixte (Conteneurs + Colis)",
    frozenset({"V", "C", "D"}): "🔀 Mixte (Véhicules + Conteneurs + Colis)",
}


def classify_cargo_type(df_subset):
    """Détermine le type de cargaison d'un navire/voyage à partir des
    catégories réellement présentes dans ses lignes ("Véhicules uniquement",
    "Mixte", ...). Certains manifestes ne listent que des véhicules, d'autres
    combinent plusieurs types — utile pour organiser l'aperçu, l'archive et
    la recherche sans que l'agent ait à ouvrir chaque fichier pour le savoir."""
    if df_subset.empty or "_cat_code" not in df_subset.columns:
        return "—"
    present = frozenset(df_subset["_cat_code"].dropna().unique())
    return CARGO_TYPE_LABELS.get(present, "—")


def records_to_item_dataframe(records):
    """Vue détaillée : 1 ligne = 1 item (type/quantité/poids/volume déjà
    correctement apparié), pour classification par tranche de volume
    (reproduit la logique du Tableau de classification des véhicules)."""
    rows = []
    for r in records:
        full_desc = " | ".join(dict.fromkeys(r["raw_desc_lines"]))
        for it in r["items"]:
            type_simple, type_code = simplify_type_colis(it["type_raw"])
            statut = item_status(it["type_raw"], full_desc)
            is_vehicle = type_code == "V"
            qty = it["qty"] or 1
            cbm = it["cbm"]
            avg_cbm = (cbm / qty) if (cbm is not None and qty) else None
            bucket = ""
            if is_vehicle and avg_cbm is not None:
                bucket = "<15m3" if avg_cbm < 15 else ("15-50m3" if avg_cbm <= 50 else ">50m3")
            rows.append({
                "Fichier": r["source_file"],
                "Navire_Voyage": r["vessel_voyage"],
                "Port_Chargement": r["port_of_loading"],
                "Origine_Cargaison": r["origin_port"] if r["origin_port"] != r["port_of_loading"] else "",
                "BL_Numero": r["bl_number"],
                "Type_Colis": type_simple,
                "Statut_Vehicule": statut,
                "Nb_Unites": qty,
                "Type_Colis_Texte": f'{it["qty"]}-{it["type_raw"]}',
                "Chassis": "; ".join(it["chassis"]),
                "Poids_Kg": it["weight"],
                "Volume_CBM": it["cbm"],
                "Tranche_Volume": bucket,
            })
    return pd.DataFrame(rows)


HEADER_FILL = "1F4E78"


def write_sheet(ws, data, title_lines=None):
    """Ecrit un DataFrame dans une feuille openpyxl, avec bandeau titre et
    en-tetes stylees."""
    from openpyxl.utils.dataframe import dataframe_to_rows
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    header_fill = PatternFill(start_color=HEADER_FILL, end_color=HEADER_FILL, fill_type="solid")
    header_font = Font(name="Arial", bold=True, color="FFFFFF", size=10)
    body_font = Font(name="Arial", size=10)
    title_font = Font(name="Arial", bold=True, size=11)

    if title_lines:
        for line in title_lines:
            ws.append([line])
            ws.cell(row=ws.max_row, column=1).font = title_font
        ws.append([])

    for row in dataframe_to_rows(data, index=False, header=True):
        ws.append(row)
    # openpyxl peut laisser une "ligne fantome" apres un append([]) vide ;
    # on deduit la position reelle de l'en-tete a partir du nombre de
    # lignes de donnees effectivement ecrites (fiable), pas d'un compteur
    # de lignes calcule avant l'ecriture.
    header_row_idx = ws.max_row - len(data)
    for j, col in enumerate(data.columns, start=1):
        cell = ws.cell(row=header_row_idx, column=j)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for row in ws.iter_rows(min_row=header_row_idx + 1):
        for cell in row:
            cell.font = body_font
    ws.freeze_panes = f"A{header_row_idx + 1}"
    for i, col in enumerate(data.columns, start=1):
        col_lens = data[col].map(lambda v: len(str(v)) if pd.notna(v) else 0)
        maxlen = max(len(str(col)), col_lens.max() if len(data) else 0)
        ws.column_dimensions[get_column_letter(i)].width = min(max(maxlen + 2, 10), 45)


def build_workbook_bytes(g_bl, navire, voyage, sheet_columns=None):
    """Construit un classeur (3 onglets Vehicule/Conteneur/Colis) pour UN
    navire/voyage deja filtre, et le retourne en memoire (BytesIO).
    sheet_columns permet de surcharger les colonnes visibles par onglet
    (ex: choix de l'agent dans l'interface)."""
    from openpyxl import Workbook
    import io

    cols_map = sheet_columns if sheet_columns is not None else SHEET_COLUMNS
    title = [f"Navire : {navire}", f"Voyage : {voyage}", "Port de déchargement : ABIDJAN"]

    wb = Workbook()
    first = True
    for cat_code, sheet_name in CAT_CODE_TO_SHEET.items():
        g_cat = g_bl[g_bl["_cat_code"] == cat_code]
        cols = [c for c in cols_map.get(sheet_name, []) if c in g_cat.columns]
        ws = wb.active if first else wb.create_sheet()
        ws.title = f"Detail_Cargaison_{sheet_name}"
        first = False
        write_sheet(ws, g_cat[cols].reset_index(drop=True), title_lines=title)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def build_excel_per_vessel(df_bl, output_dir):
    """Génère un classeur Excel par Navire/Voyage sur disque (usage CLI/local)."""
    import os
    os.makedirs(output_dir, exist_ok=True)
    written = []
    for (navire, voyage), g_bl in df_bl.groupby(["Navire", "Voyage"]):
        safe_name = re.sub(r'[^A-Za-z0-9]+', '_', f"{navire}_{voyage}").strip('_')
        buf = build_workbook_bytes(g_bl, navire, voyage)
        path = os.path.join(output_dir, f"Manifeste_{safe_name}.xlsx")
        with open(path, "wb") as f:
            f.write(buf.getbuffer())
        written.append(path)
    return written


if __name__ == "__main__":
    files = [
        ("/mnt/user-data/uploads/GSE0426_-_DAKAR_FINAL.pdf", "GSE0426_-_DAKAR_FINAL.pdf"),
        ("/mnt/user-data/uploads/GSE0426_-_GIOIA_TAURO.pdf", "GSE0426_-_GIOIA_TAURO.pdf"),
    ]
    all_records = []
    for path, label in files:
        recs = parse_manifest(path, label)
        print(f"{label}: {len(recs)} B/L extraits")
        all_records.extend(recs)

    df_bl = records_to_dataframe(all_records)

    outputs = build_excel_per_vessel(df_bl, "/home/claude/work/out")
    print("\nFichiers générés:")
    for p in outputs:
        print(" -", p)
    print(f"\nTotal lignes groupées (BL x Type): {len(df_bl)}")
    print("\nRépartition par catégorie:")
    print(df_bl["_cat_code"].value_counts())
    print("\nRépartition Etat:")
    print(df_bl["Etat"].value_counts(dropna=False))
