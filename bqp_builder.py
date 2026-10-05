"""
BQP — Base de Quantités Physiques (ISPS) pré-remplie depuis les manifestes
déjà structurés d'un Navire/Voyage (sous-onglet "BQP" de la page Reporting).

Gabarit reproduit fidèlement depuis les modèles METSOVO V.26251 et
EUPHONY ACE V.0165A (1 feuille, formules F/G/H/I/17 conservées).

Règles validées avec l'utilisateur (05/10) :
- VEHICULES NOMBRE / TONNAGE = totaux de la classification véhicules
  (1 ligne "Véhicule" = 1 châssis ; tonnage = somme des poids en kg / 1000).
- Dates (début / fin d'opérations, sortie du navire) : laissées vides, saisies
  par l'agent.
- Armateur coque et libellé de la ligne B/L : proposés puis éditables avant
  export (le transporteur n'est pas stocké dans les exports structurés).
- Conteneurs PLEINS débarqués uniquement (Statut_VP != "V") ; les EMBARQUÉS ne
  figurent pas dans un manifeste d'import : colonnes laissées à 0 pour l'agent.
- Le comptage physique peut différer du manifeste (écarts constatés de 1 à 2
  véhicules sur les BQP historiques) : le fichier est un pré-remplissage à
  vérifier, pas une valeur définitive.
"""
import io

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

import reporting_builder as rbld

BL_LABEL_MULTI = "B/L DIVERS ARMATEURS"


def default_bl_label(carrier: str) -> str:
    """Un seul transporteur connu -> 'BL <TRANSPORTEUR>', sinon libellé
    multi-armateurs (modèles METSOVO / EUPHONY ACE)."""
    carrier = (carrier or "").strip()
    return f"BL  {carrier.upper()}" if carrier else BL_LABEL_MULTI


def quantities_from_detail(dfs: dict) -> dict:
    """dfs = premier retour de rbld.fetch_voyage_detail(). Retourne
    {veh_nombre, veh_tonnage_t, c20, c40, nb_conteneurs_lignes}."""
    df_v = dfs.get("Vehicule", pd.DataFrame())
    poids = pd.to_numeric(
        rbld._col(df_v, "Poids_Unitaire_Kg").astype(str).str.replace(",", ".", regex=False),
        errors="coerce",
    ).fillna(0)
    veh_n = int(len(df_v))
    veh_t = round(float(poids.sum()) / 1000.0, 3)

    df_c = dfs.get("Conteneur", pd.DataFrame())
    c20 = c40 = 0
    if not df_c.empty:
        statut = rbld._col(df_c, "Statut_VP").astype(str).str.strip().str.upper()
        pleins = df_c[statut != "V"]
        size = rbld._col(pleins, "Type_Colis").astype(str).str.strip().str.upper()
        c20 = int((size == "20").sum())
        # 40/45 pieds et MAFI (2 TEU, cf. règle TEU de reporting_builder) -> colonne 40'
        c40 = int(((size != "20") & (size != "")).sum())
    return {"veh_nombre": veh_n, "veh_tonnage_t": veh_t, "c20": c20, "c40": c40}


def build_bqp_workbook_bytes(navire: str, voyage: str, armateur: str, bl_label: str,
                             q: dict) -> io.BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = "BQP"
    ws.sheet_view.showGridLines = True
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True

    def font(sz, bold=False):
        return Font(name="Times New Roman", size=sz, bold=bold)

    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left = Alignment(horizontal="left", vertical="center")
    blue = PatternFill("solid", start_color="CCFFFF")
    yellow = PatternFill("solid", start_color="FFFF00")
    pale_y = PatternFill("solid", start_color="FFFF99")
    tot_fill = PatternFill("solid", start_color="99CCFF")

    for col, w in {"A": 44, "B": 32, "C": 19.85, "D": 30, "E": 19.85, "F": 18, "G": 18,
                   "H": 18, "I": 18, "J": 16.7, "K": 30.85}.items():
        ws.column_dimensions[col].width = w
    for r, h in {1: 45.6, 2: 45.6, 3: 45.6, 4: 20.25, 7: 72.6, 10: 90.6, 11: 68.45,
                 12: 52.15, 13: 52.15, 14: 52.15, 15: 52.15, 16: 52.15, 17: 85.9}.items():
        ws.row_dimensions[r].height = h

    # --- En-tête navire (dates volontairement vides : saisies par l'agent) ---
    head = [
        ("B1", "NAVIRE: "), ("C1", navire), ("G1", "DEBUT DES OPERATIONS: "),
        ("B2", "N° VOYAGE:"), ("C2", voyage), ("G2", "FIN DES OPERATIONS: "),
        ("B3", "ARMATEUR COQUE : "), ("C3", armateur), ("G3", "SORTIE DU NAVIRE: "),
    ]
    for ref, val in head:
        c = ws[ref]
        c.value = val
        is_val = ref.startswith("C")
        c.font = font(18 if is_val else 20, True)
        c.alignment = center if ref == "B3" else left
    for rng in ("C1:D1", "C2:D2", "G1:I1", "G2:I2", "G3:I3", "B3:B4", "C3:D4"):
        ws.merge_cells(rng)
    for ref in ("J1", "J2", "J3"):
        ws[ref].font = font(20, True)  # à compléter par l'agent

    ws["A7"] = "ESCALES : ABIDJAN - TERRA"
    ws["A7"].font = font(36, True)
    ws["A7"].alignment = center
    ws["A7"].fill = pale_y
    ws.merge_cells("A7:K7")

    # --- Tableau marchandises ---
    heads = {
        "A10": ("MARCHANDISES", 20, False), "B10": ("CONTENEURS PLEINS DEBARQUÉS ", 16, True),
        "D10": ("CONTENEURS PLEINS EMBARQUÉS ", 16, True),
        "F10": ("TOTAL CONTENEURS     \n( EMBARQUÉS + \nDEBARQUÉS )", 16, True),
        "H10": ("TOTAL CONTENEURS\n ( TEU)\n( EMBARQUÉS + DEBARQUÉS )", 16, True),
        "J10": ("VEHICULES \n ( DEBARQUÉS + EMBARQUÉS)", 16, True),
    }
    for ref, (val, sz, b) in heads.items():
        ws[ref] = val
        ws[ref].font = font(sz, b)
        ws[ref].alignment = center
    for col in "ABCDEFGHIJK":
        ws[f"{col}10"].fill = blue
    for rng in ("B10:C10", "D10:E10", "F10:G10", "H10:I10", "J10:K10"):
        ws.merge_cells(rng)

    ws["A11"] = "TYPE ISO CONTENEURS"
    ws["A11"].font = font(18)
    ws["A11"].alignment = Alignment(wrap_text=True, vertical="center")
    for col, lab in zip("BCDEFGHI", ["20'", "40'"] * 4):
        ws[f"{col}11"] = lab
        ws[f"{col}11"].font = font(24)
        ws[f"{col}11"].alignment = center
    ws["J11"], ws["K11"] = "NOMBRE", "TONNAGE"
    for ref in ("J11", "K11"):
        ws[ref].font = font(18)
        ws[ref].alignment = center
    ws["K11"].fill = yellow

    # --- Ligne de données (12) + lignes de formules vides (13-16) comme le modèle ---
    ws["A12"] = bl_label
    ws["A12"].font = font(18)
    ws["A12"].alignment = Alignment(wrap_text=True, vertical="center")
    vals = {"B12": q["c20"], "C12": q["c40"], "D12": 0, "E12": 0}
    for ref, v in vals.items():
        ws[ref] = v
    ws["J12"], ws["K12"] = q["veh_nombre"], q["veh_tonnage_t"]
    for r in range(12, 17):
        ws[f"F{r}"] = f"=SUM(B{r}+D{r})"
        ws[f"G{r}"] = f"=SUM(C{r}+E{r})"
        ws[f"H{r}"] = f"=F{r}*1"
        ws[f"I{r}"] = f"=G{r}*2"
        for col in "BCDEFGHIJK":
            c = ws[f"{col}{r}"]
            c.alignment = center
            c.number_format = "#,##0"
            c.font = font(28, col in "HI") if col not in "JK" else font(24, col == "K")
    ws["K12"].number_format = "#,##0.000"
    ws["K12"].fill = yellow

    ws["A17"] = "NB TOTAL CONTENEURS"
    ws["A17"].font = font(20)
    ws["A17"].alignment = center
    totals = {"B17": "=SUM(B12:B16,C12:C16)", "D17": "=SUM(D12:D16,E12:E16)",
              "F17": "=F12+G12", "H17": "=SUM(H12:H16,I12:I16)",
              "J17": "=SUM(J12:J16)", "K17": "=SUM(K12:K16)"}
    for ref, f in totals.items():
        ws[ref] = f
        ws[ref].font = font(36 if ref[0] in "BDFH" else 28, True)
        ws[ref].alignment = center
    ws["K17"].number_format = "#,##0.000"
    for ref in ("J17", "K17"):
        ws[ref].fill = tot_fill
    for rng in ("B17:C17", "D17:E17", "F17:G17", "H17:I17"):
        ws.merge_cells(rng)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
