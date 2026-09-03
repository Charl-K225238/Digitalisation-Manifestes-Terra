"""
classification_builder.py — Tableau de classification des véhicules par
POL (port de chargement) et tranche de volume (<15m³ / 15-50m³ / >50m³).

Contexte (voir claude/ANALYSE_TABLEAU_CLASSIFICATION_VEHICULES_2026-09-03.md
dans le projet Claude) : remplace le fichier manuel à ~150 onglets (un par
escale) par un calcul automatique depuis les manifestes déjà structurés.
Décisions validées avec l'utilisateur (03/09) :
  - MVP limité aux manifestes "Import" (Nature_BL) — Export/Transbo jamais
    testés en pratique (aucun échantillon réel), donc exclus du calcul et
    remontés séparément dans le diagnostic plutôt que devinés.
  - Calcul à la volée depuis les exports déjà archivés (même principe que
    reporting_builder.fetch_voyage_detail), pas de nouvelle table de
    données brutes.

Prérequis (voir manifest_parser.py, 03/09 v9 suite) : la colonne "Volume_CBM"
de l'onglet "Détail Cargaison" est désormais bien renseignée par-véhicule
(clé unifiée avec Conteneur/Colis — corrige un bug où le volume unitaire
véhicule, déjà calculé, était silencieusement perdu à l'export sous l'ancien
nom "Volume_Unitaire_CBM", absent de MERGED_DETAIL_COLUMNS). Un manifeste
Véhicule archivé AVANT ce correctif (ou sous l'un des anciens formats
d'onglets, voir LEGACY_DETAIL_SHEETS et les formats encore plus anciens
"Detail_Cargaison_Vehicule" non couverts) n'aura pas cette colonne — ses
véhicules remontent en "volume manquant" (diag) plutôt que classifiés au
hasard. Un ré-traitement du manifeste (bouton Pré-Masque, doublon = mise à
jour automatique) suffit à le rendre classifiable.
"""
import io

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import reporting_builder as rbld
from manifest_parser import _volume_tranche, HEADER_FILL

TRANCHES = ["C", "V", "T"]  # _volume_tranche : C=<15m3, V=15-50m3, T=>50m3
TRANCHE_LABELS = {"C": "VEHICULE < 15M3", "V": "VEHICULE 15-50m3", "T": "VEHICULE > 50m3"}


def classify_vehicules(navire: str, voyage: str):
    """Retourne (df_classifie, diag) pour un Navire/Voyage donné.

    df_classifie : 1 ligne par châssis Import, colonnes POL (Port_Chargement),
    Tranche (<15m3/15-50m3/>50m3, vide si volume inconnu), Poids_Unitaire_Kg,
    Volume_CBM, Neuf (bool). Vide si aucun véhicule Import classifiable.

    diag : {total_vehicules, hors_import (Export/Transb. exclus du MVP),
    sans_volume (Import mais volume manquant — ré-traitement nécessaire)}
    — en plus du diagnostic de fetch_voyage_detail (accessible séparément
    via reporting_builder.fetch_voyage_detail si besoin d'un détail plus fin
    sur les échecs de lecture d'export)."""
    result, _used_df, _ports, _fetch_diag = rbld.fetch_voyage_detail(navire, voyage)
    df_veh = result.get("Vehicule", pd.DataFrame())
    diag = {"total_vehicules": len(df_veh), "hors_import": 0, "sans_volume": 0}
    if df_veh.empty:
        return pd.DataFrame(columns=["POL", "Tranche", "Poids_Unitaire_Kg", "Volume_CBM", "Neuf"]), diag

    # rbld._col(df, name) : renvoie df[name] si présente, sinon une Série de
    # valeurs par défaut de la bonne longueur/index — contrairement à
    # df.get(name) (ou df.get(name, default) avec un default scalaire), qui
    # renvoie None/le scalaire brut (PAS une Série) quand la colonne est
    # absente. Bug réel constaté en production (03/09, données réelles) : un
    # manifeste Véhicule archivé sans colonne "Volume_CBM" (ancien format,
    # voir docstring du module) faisait planter toute la page avec un
    # AttributeError ('float' object has no attribute 'map') au lieu d'être
    # traité comme "volume manquant" par véhicule — corrigé ici pour TOUTES
    # les colonnes potentiellement absentes de cette fonction, pas seulement
    # celle qui avait été prise en défaut.
    nature = rbld._col(df_veh, "Nature_BL").astype(str).str.strip().str.lower()
    is_import = nature.isin(["import", ""])  # "" = ancien export sans Nature_BL renseignée, traité comme Import
    diag["hors_import"] = int((~is_import).sum())
    df_i = df_veh[is_import].copy()
    if df_i.empty:
        return pd.DataFrame(columns=["POL", "Tranche", "Poids_Unitaire_Kg", "Volume_CBM", "Neuf"]), diag

    volume = pd.to_numeric(rbld._col(df_i, "Volume_CBM"), errors="coerce")
    tranche = volume.map(_volume_tranche)
    diag["sans_volume"] = int((tranche == "").sum())
    poids = pd.to_numeric(rbld._col(df_i, "Poids_Unitaire_Kg"), errors="coerce")
    neuf = rbld._col(df_i, "Etat").astype(str).str.strip().str.lower() == "neuf"

    df_out = pd.DataFrame({
        "POL": rbld._col(df_i, "Port_Chargement").astype(str).str.strip(),
        "Tranche": tranche,
        "Poids_Unitaire_Kg": poids,
        "Volume_CBM": volume,
        "Neuf": neuf,
    })
    return df_out, diag


def pivot_pol_tranche(df_classifie: pd.DataFrame) -> pd.DataFrame:
    """Construit le tableau croisé POL (lignes, avec ligne TOTAL finale) ×
    tranche de volume (groupes de colonnes NOMBRE/TONNAGE/VOLUME) + NEW VEH,
    même structure que le fichier de référence (colonnes multi-niveaux
    aplaties en "<groupe> - <sous-colonne>" pour rester un DataFrame simple ;
    l'export Excel — tâche 11d — reconstruira l'en-tête à 2 niveaux visuel).
    Lignes sans Tranche (volume manquant) exclues du croisé mais comptées
    dans le diagnostic de classify_vehicules — jamais classées au hasard."""
    cols = ["POL"] + [f"{TRANCHE_LABELS[t]} - {sub}" for t in TRANCHES for sub in ("NOMBRE", "TONNAGE", "VOLUME")] + ["NEW VEH"]
    if df_classifie.empty:
        return pd.DataFrame(columns=cols)

    df = df_classifie[df_classifie["Tranche"] != ""].copy()
    if df.empty:
        return pd.DataFrame(columns=cols)

    rows = []
    for pol, g in df.groupby("POL", sort=True):
        row = {"POL": pol}
        for t in TRANCHES:
            gt = g[g["Tranche"] == t]
            row[f"{TRANCHE_LABELS[t]} - NOMBRE"] = len(gt)
            row[f"{TRANCHE_LABELS[t]} - TONNAGE"] = round(gt["Poids_Unitaire_Kg"].sum() / 1000.0, 3) if len(gt) else 0
            row[f"{TRANCHE_LABELS[t]} - VOLUME"] = round(gt["Volume_CBM"].sum(), 2) if len(gt) else 0
        row["NEW VEH"] = int(g["Neuf"].sum())
        rows.append(row)

    total = {"POL": "TOTAL"}
    for t in TRANCHES:
        total[f"{TRANCHE_LABELS[t]} - NOMBRE"] = sum(r[f"{TRANCHE_LABELS[t]} - NOMBRE"] for r in rows)
        total[f"{TRANCHE_LABELS[t]} - TONNAGE"] = round(sum(r[f"{TRANCHE_LABELS[t]} - TONNAGE"] for r in rows), 3)
        total[f"{TRANCHE_LABELS[t]} - VOLUME"] = round(sum(r[f"{TRANCHE_LABELS[t]} - VOLUME"] for r in rows), 2)
    total["NEW VEH"] = sum(r["NEW VEH"] for r in rows)
    rows.append(total)

    return pd.DataFrame(rows, columns=cols)


# ---------------------------------------------------------------------------
# Export Excel — mise en page fidèle au fichier de référence x150 onglets
# (tâche 11d, voir claude/ANALYSE_TABLEAU_CLASSIFICATION_VEHICULES_2026-09-03.md
# section 1) : titre, en-tête à 2 niveaux (3 groupes de tranche × 3
# sous-colonnes NOMBRE/TONNAGE/VOLUME + NEW VEH), un bloc par POL — une ligne
# par véhicule physique, quantité/poids/volume placés uniquement dans le
# triplet de colonnes de sa tranche (les autres restent vides, comme dans le
# fichier reçu — pas de 0 trompeur), ligne de sous-total par bloc, ligne
# TOTAL en bas. Contrairement à pivot_pol_tranche (croisé déjà agrégé, pour
# l'affichage écran), reconstruit le détail ligne-à-ligne à partir de
# df_classifie (sortie de classify_vehicules, 1 ligne = 1 véhicule).
# ---------------------------------------------------------------------------
SUBTOTAL_FILL = "D9E1F2"  # bleu pastel — ligne de sous-total par POL
TOTAL_FILL = "1F4E78"     # même bleu que l'en-tête — ligne TOTAL générale


def build_classification_workbook_bytes(df_classifie: pd.DataFrame, navire: str, voyage: str,
                                          escale_info: dict | None = None) -> io.BytesIO:
    """escale_info optionnel : {"date_escale", "statut", "remarques"} (voir
    tracking.get_suivi_escale) — affiché en bandeau titre si fourni, purement
    informatif, n'affecte pas le calcul."""
    header_font = Font(name="Arial", bold=True, color="FFFFFF", size=10)
    header_fill = PatternFill(start_color=HEADER_FILL, end_color=HEADER_FILL, fill_type="solid")
    title_font = Font(name="Arial", bold=True, size=11)
    body_font = Font(name="Arial", size=10)
    subtotal_font = Font(name="Arial", bold=True, size=10)
    subtotal_fill = PatternFill(start_color=SUBTOTAL_FILL, end_color=SUBTOTAL_FILL, fill_type="solid")
    total_font = Font(name="Arial", bold=True, color="FFFFFF", size=10)
    total_fill = PatternFill(start_color=TOTAL_FILL, end_color=TOTAL_FILL, fill_type="solid")
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "Classification"

    # ── Bandeau titre ──
    title_lines = [
        "TABLEAU DE CLASSIFICATION DES VEHICULES PAR POL ET VOLUME",
        f"Navire : {navire}    Voyage : {voyage}",
    ]
    if escale_info and escale_info.get("date_escale"):
        line = f"Date d'escale (ETA/ATA) : {escale_info['date_escale']:%d/%m/%Y}"
        if escale_info.get("statut"):
            line += f"    Statut : {escale_info['statut']}"
        title_lines.append(line)
        if escale_info.get("remarques"):
            title_lines.append(f"Remarques : {escale_info['remarques']}")
    for line in title_lines:
        ws.append([line])
        ws.cell(row=ws.max_row, column=1).font = title_font
    ws.append([])

    # ── En-tête à 2 niveaux ──
    header_row1 = ws.max_row + 1
    header_row2 = header_row1 + 1
    ws.cell(row=header_row1, column=1, value="POL")
    ws.merge_cells(start_row=header_row1, start_column=1, end_row=header_row2, end_column=1)
    col = 2
    for t in TRANCHES:
        ws.cell(row=header_row1, column=col, value=TRANCHE_LABELS[t])
        ws.merge_cells(start_row=header_row1, start_column=col, end_row=header_row1, end_column=col + 2)
        for j, sub in enumerate(("NOMBRE", "TONNAGE", "VOLUME")):
            ws.cell(row=header_row2, column=col + j, value=sub)
        col += 3
    ws.cell(row=header_row1, column=col, value="NEW VEH")
    ws.merge_cells(start_row=header_row1, start_column=col, end_row=header_row2, end_column=col)
    n_cols = col
    for r in (header_row1, header_row2):
        for c in range(1, n_cols + 1):
            cell = ws.cell(row=r, column=c)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = center

    def _tranche_cols(t):
        i = TRANCHES.index(t)
        return 2 + i * 3, 3 + i * 3, 4 + i * 3  # NOMBRE, TONNAGE, VOLUME

    # ── Blocs par POL (1 ligne = 1 véhicule, valeurs dans le triplet de sa
    # tranche uniquement) ──
    row = header_row2
    total_veh = 0
    total_par_tranche = {t: {"NOMBRE": 0, "TONNAGE": 0.0, "VOLUME": 0.0} for t in TRANCHES}
    total_new = 0
    df = df_classifie[df_classifie["Tranche"] != ""] if not df_classifie.empty else df_classifie
    for pol, g in (df.groupby("POL", sort=True) if not df.empty else []):
        first = True
        n_new_bloc = 0
        for _, vr in g.iterrows():
            row += 1
            ws.cell(row=row, column=1, value=pol if first else None)
            first = False
            t = vr["Tranche"]
            c_nb, c_tn, c_vol = _tranche_cols(t)
            ws.cell(row=row, column=c_nb, value=1)
            ws.cell(row=row, column=c_tn, value=round(vr["Poids_Unitaire_Kg"] / 1000.0, 3) if pd.notna(vr["Poids_Unitaire_Kg"]) else None)
            ws.cell(row=row, column=c_vol, value=round(vr["Volume_CBM"], 2) if pd.notna(vr["Volume_CBM"]) else None)
            if vr["Neuf"]:
                ws.cell(row=row, column=n_cols, value=1)
                n_new_bloc += 1
            for c in range(1, n_cols + 1):
                ws.cell(row=row, column=c).font = body_font

        row += 1
        ws.cell(row=row, column=1, value=f"{len(g)} VEHICULES")
        for t in TRANCHES:
            gt = g[g["Tranche"] == t]
            c_nb, c_tn, c_vol = _tranche_cols(t)
            n, tn, vol = len(gt), round(gt["Poids_Unitaire_Kg"].sum() / 1000.0, 3), round(gt["Volume_CBM"].sum(), 2)
            if n:
                ws.cell(row=row, column=c_nb, value=n)
                ws.cell(row=row, column=c_tn, value=tn)
                ws.cell(row=row, column=c_vol, value=vol)
            total_par_tranche[t]["NOMBRE"] += n
            total_par_tranche[t]["TONNAGE"] += tn
            total_par_tranche[t]["VOLUME"] += vol
        ws.cell(row=row, column=n_cols, value=n_new_bloc or None)
        for c in range(1, n_cols + 1):
            cell = ws.cell(row=row, column=c)
            cell.font = subtotal_font
            cell.fill = subtotal_fill
        total_veh += len(g)
        total_new += n_new_bloc

    row += 1
    ws.cell(row=row, column=1, value=f"TOTAL = {total_veh} VEHICULES")
    for t in TRANCHES:
        c_nb, c_tn, c_vol = _tranche_cols(t)
        ws.cell(row=row, column=c_nb, value=total_par_tranche[t]["NOMBRE"] or None)
        ws.cell(row=row, column=c_tn, value=round(total_par_tranche[t]["TONNAGE"], 3) or None)
        ws.cell(row=row, column=c_vol, value=round(total_par_tranche[t]["VOLUME"], 2) or None)
    ws.cell(row=row, column=n_cols, value=total_new or None)
    for c in range(1, n_cols + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = total_font
        cell.fill = total_fill

    if total_veh == 0:
        ws.cell(row=row + 1, column=1, value="Aucun véhicule classifiable pour cette sélection.")

    for c in range(1, n_cols + 1):
        ws.column_dimensions[get_column_letter(c)].width = 14 if c > 1 else 20
    ws.freeze_panes = f"A{header_row2 + 1}"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
