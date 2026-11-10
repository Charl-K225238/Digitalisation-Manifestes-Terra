"""
premasque_ipaki.py — Pré-masque véhicules au format exact des agents (import Ipaki)
et fichier de vérification qui l'accompagne.

Deux fichiers, jamais mélangés :
  - pré-masque Ipaki : UN onglet « MASQUE IPAKI TETRAX », en-tête en ligne 1, les
    26 colonnes du masque agent (mêmes libellés, espaces compris), valeurs seules
    (ni formule, ni couleur, ni commentaire, ni lien) : rien qui puisse gêner l'import ;
  - vérification : onglets « À VÉRIFIER » (points + totaux), « Masque annoté »
    (même contenu, couleurs + commentaires + liens), « GUIDE » ; ajoutés au classeur
    d'export habituel (qui garde « Détail Cargaison », relu par le Reporting).

Règles reprises du masque agent (navire GSL0526 Anvers, 320 unités, cohérentes à 100 %) :
  - BLItem : volume ≤ 15 → VEH < 15m3 ; ≤ 50 → VEH > 15m3 ; > 50 → VEH > 50m3 ;
  - TYPE D'ACTION : Côte d'Ivoire → IMPORT, Togo → TRANSBO, Burkina/Mali/Niger → TRANSIT ;
  - FINAL DESTINATION IPAKI = pays ; POL/POD IPAKI = UN/LOCODE ;
  - unités portées : porteur « RLT », remorque attelée « AT <châssis du porteur> »,
    unité empilée « DS <châssis de la remorque, sinon du porteur> », poids et volume 0.
Pas de dépendance Streamlit : testable seul.
"""
import datetime
import io
import re

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

SHEET = "MASQUE IPAKI TETRAX"
# Libellés exacts du masque agent (espaces doubles et finaux compris ; colonne S sans titre).
COLUMNS = [
    "NBRE", "MODE DE TRANSPORT", "ESCALE TETRAX", "NATURE BL", "POL  TETRAX", "POD TETRAX",
    "FINAL DESTINATION TETRAX", "POIDS TETRAX (KG)", "BL", "ESCALE IPAKI", "POL IPAKI",
    "POD IPAKI", "FINAL DESTINATION IPAKI", "MARQUE ", "MODELE", "MARQUE & MODELE", "ETAT",
    "ANNEE DE FABRICATION ", "", "CHÂSSIS", "TYPE D'ACTION", "POIDS IPAKI (TON)", "VOLUME",
    "BLItem YardItemCode", "CLIENT ", "OBSERVATION",
]
ETAT_NEUF = "VEHICULES NEUFS, VOITURES NEUVES, CAMION"
ETAT_USAGE = "VEHICULES USAGES,VOITURES OCCASIONS"

LOCODE = {
    "ABIDJAN": "CIABJ", "SAN PEDRO": "CISPY", "ANTWERP": "BEANR", "ANVERS": "BEANR",
    "HAMBURG": "DEHAM", "BREMERHAVEN": "DEBRV", "AMSTERDAM": "NLAMS", "ROTTERDAM": "NLRTM",
    "TILBURY": "GBTIL", "LIVERPOOL": "GBLIV", "SOUTHAMPTON": "GBSOU", "PORTBURY": "GBPRU",
    "LE HAVRE": "FRLEH", "VALENCIA": "ESVLC", "SAVONA": "ITSVN", "NAPLES": "ITNAP",
    "SALERNO": "ITSAL", "BALTIMORE": "USBAL", "DAVISVILLE": "USDVV", "HALIFAX": "CAHAL",
    "DURBAN": "ZADUR", "LAGOS": "NGLOS", "TIN CAN": "NGTIN", "COTONOU": "BJCOO",
    "LOME": "TGLFW", "TEMA": "GHTEM", "DAKAR": "SNDKR", "CONAKRY": "GNCKY",
}
# Pays de destination finale -> (libellé Ipaki, type d'action, ville par défaut).
PAYS = {
    "COTE D'IVOIRE": ("COTE D'IVOIRE", "IMPORT", "ABIDJAN"),
    "BURKINA FASO": ("BURKINA FASO", "TRANSIT", "OUAGADOUGOU"),
    "MALI": ("MALI", "TRANSIT", "BAMAKO"),
    "NIGER": ("NIGER", "TRANSIT", "NIAMEY"),
    "TOGO": ("TOGO", "TRANSBO", "LOME"),
}

PIGGY_ATTELEE, PIGGY_EMPILEE = "Attelée", "Empilée"
EPM_RE = re.compile(r"\bDISMOUNTED\b|\bD[EÉ]MONT[EÉ]", re.I)
CHASSIS_SALE_RE = re.compile(r"[^A-Z0-9]")

# Niveaux des points à vérifier (couleur du masque annoté).
ROUGE, ORANGE, JAUNE = "Incohérence", "État à confirmer", "À vérifier"
_COULEUR = {ROUGE: "F8CBAD", ORANGE: "FCE4D6", JAUNE: "FFF2CC"}
_ORDRE = {ROUGE: 0, ORANGE: 1, JAUNE: 2}


_VIN_ANNEES = "ABCDEFGHJKLMNPRSTVWXY123456789"   # 10e caractère du VIN (ISO 3779), cycle de 30 ans


def annee_vin(ch: str):
    """Année-modèle lue au 10e caractère d'un VIN de 17 caractères, ramenée au cycle
    le plus récent qui ne dépasse pas l'an prochain ; None si illisible."""
    ch = str(ch or "").upper()
    if len(ch) != 17 or ch[9] not in _VIN_ANNEES:
        return None
    y = 2010 + _VIN_ANNEES.index(ch[9])
    while y > datetime.date.today().year + 1:
        y -= 30
    return y


def locode(port: str) -> str:
    p = str(port or "").upper()
    for nom, code in LOCODE.items():
        if nom in p:
            return code
    return ""


def yard_code(volume) -> str:
    try:
        v = float(volume or 0)
    except (TypeError, ValueError):
        v = 0.0
    if v != v or v <= 15:          # NaN ou ≤ 15 (unités portées à 0 comprises)
        return "VEH < 15m3"
    return "VEH > 15m3" if v <= 50 else "VEH > 50m3"


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _piggy_map(g_bl) -> dict:
    """châssis -> (type de portage ou "", texte descriptif) depuis le DataFrame structuré."""
    out = {}
    if g_bl is None or len(g_bl) == 0:
        return out
    for _, r in g_bl.iterrows():
        tc = str(r.get("Type_Colis") or "")
        kind = PIGGY_ATTELEE if tc.startswith("Attelée") else (PIGGY_EMPILEE if tc.startswith("Empilée") else "")
        texte = " ".join(str(r.get(k) or "") for k in ("Commodity", "Modele", "Type_Colis"))
        for ch in str(r.get("Numeros_Chassis") or "").split(";"):
            if ch.strip():
                out.setdefault(ch.strip(), (kind, texte))
    return out


def build_rows(veh_rows, g_bl=None, escale_ipaki="", mode_transport=""):
    """Lignes du masque (dicts sur COLUMNS) et points à vérifier.

    veh_rows : sortie de manifest_parser._rows_vehicule_detail (1 ligne par châssis, dans
    l'ordre du manifeste) ; g_bl : DataFrame structuré (type de portage par châssis)."""
    piggy = _piggy_map(g_bl)
    rows, points = [], []
    vus = {}
    porteur = remorque = None          # châssis courants de la chaîne, par B/L
    bl_courant = None

    def point(i, niveau, colonne, texte):
        points.append({"ligne": i, "niveau": niveau, "colonne": colonne, "texte": texte})

    for i, r in enumerate(veh_rows, start=1):
        ch = str(r.get("Chassis") or "").strip()
        bl = str(r.get("BL_Numero") or "")
        kind, texte = piggy.get(ch, ("", ""))
        if bl != bl_courant:
            porteur = remorque = None
            bl_courant = bl

        pays_t = str(r.get("Pays_Transit") or "").strip().upper()
        if pays_t in PAYS:
            pays, action, ville_def = PAYS[pays_t]
        elif pays_t:
            pays, action, ville_def = pays_t, "TRANSIT", ""
        else:
            pays, action, ville_def = PAYS["COTE D'IVOIRE"]
        nature = r.get("Nature_BL") or "Import"
        if nature == "Export":
            action = "EXPORT"
        elif nature in ("Transbo", "Transb.") and action == "IMPORT":
            action = "TRANSBO"
        ville = str(r.get("Destination_Brute") or "").strip().upper() or (
            str(r.get("Port_Dechargement") or "").upper() if action == "IMPORT" else ville_def)
        if action in ("TRANSIT", "TRANSBO") and not str(r.get("Destination_Brute") or "").strip():
            point(i, JAUNE, "FINAL DESTINATION TETRAX",
                  f"Ville non écrite au manifeste : {ville or '?'} proposée pour {pays}.")

        # Chaîne porteur / attelée / empilée
        obs = ""
        if kind == PIGGY_ATTELEE:
            obs = f"AT {porteur}" if porteur else "AT"
            remorque = ch
        elif kind == PIGGY_EMPILEE:
            ref = remorque or porteur
            obs = f"DS {ref}" if ref else "DS"
        else:
            porteur, remorque = ch, None
        if kind and obs in ("AT", "DS"):
            point(i, ROUGE, "OBSERVATION", "Unité portée sans unité porteuse identifiée sur ce B/L.")
        if not obs and EPM_RE.search(texte):
            obs = "EPM"
            point(i, JAUNE, "OBSERVATION", "Engin démonté (EPM proposé) : confirmer.")

        poids = _num(r.get("Poids_Unitaire_Kg"))
        volume = _num(r.get("Volume_CBM"))
        if kind:
            poids, volume = 0.0, 0.0
        elif poids is None:
            point(i, ROUGE, "POIDS TETRAX (KG)", "Poids absent du manifeste pour cette unité.")
        if not kind and volume is None:
            point(i, JAUNE, "VOLUME", "Volume absent : classe BLItem à confirmer.")

        etat = r.get("Etat") or ""
        if etat == "Neuf":
            etat_lib = ETAT_NEUF
        else:
            etat_lib = ETAT_USAGE
            if etat != "Usager":
                point(i, ORANGE, "ETAT", "Aucun état écrit au manifeste : USAGÉ par défaut, NEUF si l'agent le confirme.")

        client = str(r.get("Destinataire_Nom") or "").strip()
        if not client or client.upper().startswith("TO THE ORDER") or client.upper().startswith("TO ORDER"):
            point(i, JAUNE, "CLIENT ", "Destinataire « à ordre » ou absent : prendre le notify du B/L.")

        if CHASSIS_SALE_RE.search(ch.upper()):
            point(i, ROUGE, "CHÂSSIS", "Caractère inattendu dans le châssis.")
        elif len(ch) != 17:
            point(i, JAUNE, "CHÂSSIS", f"Châssis de {len(ch)} caractères (17 attendus pour un VIN ; normal pour un engin).")
        if ch in vus:
            point(i, ROUGE, "CHÂSSIS", f"Châssis en double (déjà ligne {vus[ch]}).")
        vus.setdefault(ch, i)

        marque = str(r.get("Marque") or "").strip().upper()
        modele = str(r.get("Modele") or "").strip().upper()
        if not marque:
            point(i, JAUNE, "MARQUE ", "Marque non reconnue.")
        # Année : écrite au manifeste, sinon convention des agents (vérifiée sur GSL0526,
        # 314/321) : véhicule neuf -> année en cours ; usagé -> année du VIN, sinon 2000.
        annee = int(_num(r.get("Annee_Fabrication"))) if _num(r.get("Annee_Fabrication")) else ""
        if not annee:
            if etat == "Neuf":
                annee = datetime.date.today().year
            elif annee_vin(ch):
                annee = annee_vin(ch)
                point(i, JAUNE, "ANNEE DE FABRICATION ", f"Année non écrite : {annee} lue dans le VIN.")
            else:
                annee = 2000
                point(i, JAUNE, "ANNEE DE FABRICATION ", "Année non écrite ni lisible dans le châssis : 2000 par défaut.")

        rows.append({
            "NBRE": i, "MODE DE TRANSPORT": mode_transport or "", "ESCALE TETRAX": "",
            "NATURE BL": nature, "POL  TETRAX": str(r.get("Port_Chargement") or "").upper(),
            "POD TETRAX": str(r.get("Port_Dechargement") or "").upper(),
            "FINAL DESTINATION TETRAX": ville,
            "POIDS TETRAX (KG)": round(poids) if poids is not None else "",
            "BL": bl, "ESCALE IPAKI": escale_ipaki or "",
            "POL IPAKI": locode(r.get("Port_Chargement")), "POD IPAKI": locode(r.get("Port_Dechargement")),
            "FINAL DESTINATION IPAKI": pays,
            "MARQUE ": marque, "MODELE": modele, "MARQUE & MODELE": f"{marque} {modele}".strip(),
            "ETAT": etat_lib, "ANNEE DE FABRICATION ": annee, "": len(ch), "CHÂSSIS": ch,
            "TYPE D'ACTION": action,
            "POIDS IPAKI (TON)": round(poids / 1000, 3) if poids is not None else "",
            "VOLUME": round(volume, 3) if volume is not None else "",
            "BLItem YardItemCode": yard_code(volume), "CLIENT ": client, "OBSERVATION": obs,
        })
        if not rows[-1]["POL IPAKI"]:
            point(i, JAUNE, "POL IPAKI", "Port de chargement sans code UN/LOCODE connu.")

    # Porteur = toute unité suivie d'au moins une unité portée sur le même B/L.
    for k, row in enumerate(rows):
        if row["OBSERVATION"].startswith(("AT ", "DS ")):
            ref = row["OBSERVATION"][3:]
            for j in range(k - 1, -1, -1):
                if rows[j]["CHÂSSIS"] == ref and rows[j]["BL"] == row["BL"]:
                    if not rows[j]["OBSERVATION"]:
                        rows[j]["OBSERVATION"] = "RLT"
                    break
    if not escale_ipaki:
        points.insert(0, {"ligne": None, "niveau": JAUNE, "colonne": "ESCALE IPAKI",
                          "texte": "Code escale Ipaki non saisi : à saisir dans l'app avant l'export."})
    if not mode_transport:
        points.insert(0, {"ligne": None, "niveau": JAUNE, "colonne": "MODE DE TRANSPORT",
                          "texte": "Mode de transport (n° Tetrax) non saisi : à saisir dans l'app avant l'export."})
    return rows, points


# ── Fichier 1 : pré-masque pour Ipaki (données seules) ─────────────────────────
def ipaki_xlsx_bytes(rows) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET
    ws.append(COLUMNS)
    for r in rows:
        ws.append([r[c] for c in COLUMNS])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── Fichier 2 : onglets de vérification (ajoutés au classeur d'export) ──────────
_NAVY = "1F3864"
_GUIDE_ETAPES = [
    "1. Saisir dans l'app le mode de transport et le code escale Ipaki avant de télécharger.",
    "2. Onglet À VÉRIFIER : contrôler les totaux (✓ attendu partout).",
    "3. Traiter les points du haut vers le bas (rouge, puis orange, puis jaune) : Ctrl+clic sur « Aller » ouvre la ligne.",
    "4. Corriger dans l'app quand c'est possible (puis re-télécharger), sinon dans le pré-masque Ipaki.",
    "5. Cocher « Vérifié » (x) en colonne A ; le compteur en haut indique ce qui reste.",
    "   Année non écrite au manifeste : neuf = année en cours ; usagé = année du VIN, sinon 2000 (signalé).",
    "6. Intégrer dans Ipaki le fichier PREMASQUE_IPAKI (jamais ce fichier de vérification).",
]
_RACCOURCIS = [
    ("Ctrl+Maj+L", "Activer ou retirer les filtres"), ("Alt+↓", "Ouvrir la liste d'un filtre"),
    ("Ctrl+F / Ctrl+H", "Rechercher / remplacer"), ("Ctrl+flèche", "Aller au bout des données"),
    ("Ctrl+Début", "Revenir en haut"), ("F2", "Modifier la cellule"), ("Ctrl+D", "Recopier vers le bas"),
    ("Ctrl+clic", "Suivre un lien (Aller / ↩)"), ("Ctrl+Z", "Annuler"), ("Ctrl+S", "Enregistrer"),
]


def _entete(ws, row, valeurs):
    for j, v in enumerate(valeurs, 1):
        c = ws.cell(row=row, column=j, value=v)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", start_color=_NAVY, end_color=_NAVY)


def add_verification_sheets(wb, rows, points, navire="", voyage="", totaux=None, index=0):
    """Ajoute « À VÉRIFIER », « Masque annoté » et « GUIDE » à un classeur openpyxl.
    totaux : lignes de texte du contrôle des totaux (manifest_totals.agent_message)."""
    points = sorted(points, key=lambda p: (_ORDRE[p["niveau"]], p["ligne"] or 0))
    wv = wb.create_sheet("À VÉRIFIER", index)
    wm = wb.create_sheet("Masque annoté", index + 1)

    # Masque annoté : mêmes colonnes, + lien retour.
    _entete(wm, 1, COLUMNS + ["↩"])
    for r in rows:
        wm.append([r[c] for c in COLUMNS])
    col_idx = {c: j for j, c in enumerate(COLUMNS, 1)}
    for p in points:
        if not p["ligne"]:
            continue
        cell = wm.cell(row=p["ligne"] + 1, column=col_idx.get(p["colonne"], 1))
        cell.fill = PatternFill("solid", start_color=_COULEUR[p["niveau"]], end_color=_COULEUR[p["niveau"]])
        old = cell.comment.text + "\n" if cell.comment else ""
        cell.comment = Comment(old + f"{p['niveau']} : {p['texte']}", "Manifestes Terra")
    wm.freeze_panes = "A2"
    wm.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}{len(rows) + 1}"

    # À VÉRIFIER
    wv["A1"] = f"À VÉRIFIER — {navire} / {voyage}".strip(" —/")
    wv["A1"].font = Font(bold=True, size=13)
    wv["A2"] = ("Aide : traiter du rouge au jaune · Ctrl+clic sur « Aller » ouvre la ligne · "
                "mettre x en colonne A une fois vérifié · voir l'onglet GUIDE.")
    n = len(points)
    wv["A5"] = "Contrôle des totaux"
    wv["A5"].font = Font(bold=True)
    r0 = 6
    lignes_tot = [f"Unités dans le masque : {len(rows)}"] + list(totaux or [])
    for k, t in enumerate(lignes_tot):
        wv.cell(row=r0 + k, column=1, value=t).alignment = Alignment(wrap_text=True)
    h = r0 + len(lignes_tot) + 1
    _entete(wv, h, ["Vérifié (x)", "Niveau", "Ligne", "B/L", "Châssis", "Colonne", "Point", "Aller"])
    for k, p in enumerate(points, h + 1):
        r = rows[p["ligne"] - 1] if p["ligne"] else {}
        vals = ["", p["niveau"], p["ligne"] or "", r.get("BL", ""), r.get("CHÂSSIS", ""), p["colonne"], p["texte"]]
        for j, v in enumerate(vals, 1):
            c = wv.cell(row=k, column=j, value=v)
            if j == 2:
                c.fill = PatternFill("solid", start_color=_COULEUR[p["niveau"]], end_color=_COULEUR[p["niveau"]])
        if p["ligne"]:
            go = wv.cell(row=k, column=8, value="Aller")
            col = get_column_letter(col_idx.get(p["colonne"], 1))
            go.hyperlink = f"#'Masque annoté'!{col}{p['ligne'] + 1}"
            go.font = Font(color="0563C1", underline="single")
            back = wm.cell(row=p["ligne"] + 1, column=len(COLUMNS) + 1, value="↩ À VÉRIFIER")
            back.hyperlink = f"#'À VÉRIFIER'!A{k}"
            back.font = Font(color="0563C1", underline="single")
    wv["A3"] = f'=COUNTIF(A{h + 1}:A{h + max(n, 1)},"x")&" / {n} points vérifiés"'
    wv["A3"].font = Font(bold=True)
    for j, w in enumerate([11, 16, 7, 14, 21, 24, 70, 8], 1):
        wv.column_dimensions[get_column_letter(j)].width = w
    wv.freeze_panes = f"A{h + 1}"

    # GUIDE
    wg = wb.create_sheet("GUIDE", index + 2)
    wg["A1"] = "Guide de vérification du pré-masque"
    wg["A1"].font = Font(bold=True, size=13)
    for k, t in enumerate(_GUIDE_ETAPES, 3):
        wg.cell(row=k, column=1, value=t)
    k0 = 4 + len(_GUIDE_ETAPES)
    wg.cell(row=k0, column=1, value="Légende : rouge = incohérence · orange = état à confirmer · jaune = à vérifier.")
    _entete(wg, k0 + 2, ["Raccourci Excel", "Action"])
    for k, (a, b) in enumerate(_RACCOURCIS, k0 + 3):
        wg.cell(row=k, column=1, value=a)
        wg.cell(row=k, column=2, value=b)
    wg.cell(row=k0 + 4 + len(_RACCOURCIS), column=1,
            value="Excel n'a pas de bouton « retour » : utiliser le lien « ↩ À VÉRIFIER » en fin de ligne du masque annoté.")
    wg.column_dimensions["A"].width = 22
    wg.column_dimensions["B"].width = 60
    return wv, wm, wg
