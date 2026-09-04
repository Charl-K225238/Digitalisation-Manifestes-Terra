"""
classification_builder.py — Tableau de classification des conteneurs par
POL (port de chargement) et tranche de volume (<15m³ / 15-50m³ / >50m³).

Contexte (voir claude/ANALYSE_TABLEAU_CLASSIFICATION_VEHICULES_2026-09-03.md
dans le projet Claude) : remplace le fichier manuel à ~150 onglets (un par
escale) par un calcul automatique depuis les manifestes déjà structurés.

Repositionné le 04/09 (retour utilisateur, sur échantillon réel de 13
manifestes) : la quasi-totalité des manifestes Grimaldi traités par TERRA
sont des manifestes conteneurs/groupage, pas des manifestes RORO châssis —
la classification porte donc sur l'onglet "Cargaison groupée - Conteneurs"
(1 ligne = 1 conteneur physique), pas sur les véhicules. Le principe reste
inchangé : POL en lignes, tranche de volume en colonnes (NOMBRE/TONNAGE/
VOLUME par tranche), classée d'après Volume_CBM (déjà renseigné par
conteneur, capacité standard 20/40 pieds) — même seuils <15/15-50/>50m3 que
la version précédente. Le tableau reste agrégé (une somme par POL, pas une
ligne par conteneur) : voir pivot_pol_tranche.

Décisions MVP (03/09, toujours valables) :
  - Limité aux manifestes "Import" (Nature_BL) — Export/Transbo exclus du
    calcul et remontés séparément dans le diagnostic plutôt que devinés.
  - Calcul à la volée depuis les exports déjà archivés (même principe que
    reporting_builder.fetch_voyage_detail), pas de nouvelle table de
    données brutes.
"""
import io

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import reporting_builder as rbld
from manifest_parser import _volume_tranche, HEADER_FILL

TRANCHES = ["C", "V", "T"]  # _volume_tranche : C=<15m3, V=15-50m3, T=>50m3
TRANCHE_LABELS = {"C": "CONTENEUR < 15M3", "V": "CONTENEUR 15-50m3", "T": "CONTENEUR > 50m3"}

_EMPTY_COLS = ["POL", "Tranche", "Poids_Unitaire_Kg", "Volume_CBM"]


def classify_conteneurs(navire: str, voyage: str):
    """Retourne (df_classifie, diag) pour un Navire/Voyage donné.

    df_classifie : 1 ligne par conteneur physique Import, colonnes POL
    (Port_Chargement), Tranche (<15m3/15-50m3/>50m3, vide si volume inconnu),
    Poids_Unitaire_Kg, Volume_CBM. Vide si aucun conteneur Import classifiable.

    diag : {total_conteneurs, hors_import (Export/Transb. exclus du MVP),
    sans_volume (Import mais volume manquant — ré-traitement nécessaire)} —
    en plus du diagnostic de fetch_voyage_detail (accessible séparément via
    reporting_builder.fetch_voyage_detail si besoin d'un détail plus fin sur
    les échecs de lecture d'export)."""
    result, _used_df, _ports, _fetch_diag = rbld.fetch_voyage_detail(navire, voyage)
    df_cont = result.get("Conteneur", pd.DataFrame())
    diag = {"total_conteneurs": len(df_cont), "hors_import": 0, "sans_volume": 0}
    if df_cont.empty:
        return pd.DataFrame(columns=_EMPTY_COLS), diag

    # rbld._col(df, name) : renvoie df[name] si présente, sinon une Série de
    # valeurs par défaut de la bonne longueur/index — contrairement à
    # df.get(name) (ou df.get(name, default) avec un default scalaire), qui
    # renvoie None/le scalaire brut (PAS une Série) quand la colonne est
    # absente (bug réel constaté en production, 03/09).
    nature = rbld._col(df_cont, "Nature_BL").astype(str).str.strip().str.lower()
    is_import = nature.isin(["import", ""])  # "" = ancien export sans Nature_BL renseignée, traité comme Import
    diag["hors_import"] = int((~is_import).sum())
    df_i = df_cont[is_import].copy()
    if df_i.empty:
        return pd.DataFrame(columns=_EMPTY_COLS), diag

    volume = pd.to_numeric(rbld._col(df_i, "Volume_CBM"), errors="coerce")
    tranche = volume.map(_volume_tranche)
    diag["sans_volume"] = int((tranche == "").sum())
    poids = pd.to_numeric(rbld._col(df_i, "Poids_Unitaire_Kg"), errors="coerce")

    df_out = pd.DataFrame({
        "POL": rbld._col(df_i, "Port_Chargement").astype(str).str.strip(),
        "Tranche": tranche,
        "Poids_Unitaire_Kg": poids,
        "Volume_CBM": volume,
    })
    return df_out, diag


def pivot_pol_tranche(df_classifie: pd.DataFrame) -> pd.DataFrame:
    """Construit le tableau croisé POL (lignes, avec ligne TOTAL finale) ×
    tranche de volume (groupes de colonnes NOMBRE/TONNAGE/VOLUME), même
    structure que le fichier de référence (colonnes multi-niveaux aplaties en
    "<groupe> - <sous-colonne>" pour rester un DataFrame simple ; l'export
    Excel reconstruira l'en-tête à 2 niveaux visuel). Un ensemble agrégé —
    une somme par POL (nombre de conteneurs + tonnage + volume), pas une
    ligne par conteneur (voir demande utilisateur 04/09). Lignes sans Tranche
    (volume manquant) exclues du croisé mais comptées dans le diagnostic de
    classify_conteneurs — jamais classées au hasard."""
    cols = ["POL"] + [f"{TRANCHE_LABELS[t]} - {sub}" for t in TRANCHES for sub in ("NOMBRE", "TONNAGE", "VOLUME")]
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
        rows.append(row)

    total = {"POL": "TOTAL"}
    for t in TRANCHES:
        total[f"{TRANCHE_LABELS[t]} - NOMBRE"] = sum(r[f"{TRANCHE_LABELS[t]} - NOMBRE"] for r in rows)
        total[f"{TRANCHE_LABELS[t]} - TONNAGE"] = round(sum(r[f"{TRANCHE_LABELS[t]} - TONNAGE"] for r in rows), 3)
        total[f"{TRANCHE_LABELS[t]} - VOLUME"] = round(sum(r[f"{TRANCHE_LABELS[t]} - VOLUME"] for r in rows), 2)
    rows.append(total)

    return pd.DataFrame(rows, columns=cols)


# ---------------------------------------------------------------------------
# Export Excel — mise en page fidèle au fichier de référence x150 onglets
# (tâche 11d, voir claude/ANALYSE_TABLEAU_CLASSIFICATION_VEHICULES_2026-09-03.md
# section 1) : titre, en-tête à 2 niveaux (3 groupes de tranche × 3
# sous-colonnes NOMBRE/TONNAGE/VOLUME), une ligne PAR POL — un ensemble
# agrégé (nombre de conteneurs + tonnage + volume cumulés), pas une ligne par
# conteneur (demande utilisateur 04/09) — puis une ligne TOTAL en bas.
# Repose directement sur pivot_pol_tranche (même chiffres que l'affichage
# écran).
# ---------------------------------------------------------------------------
TOTAL_FILL = "1F4E78"  # même bleu que l'en-tête — ligne TOTAL générale


def build_classification_workbook_bytes(df_classifie: pd.DataFrame, navire: str, voyage: str,
                                          escale_info: dict | None = None) -> io.BytesIO:
    """escale_info optionnel : {"date_escale"} (voir tracking.get_suivi_escale)
    — affiché en bandeau titre si fourni, purement informatif, n'affecte pas
    le calcul."""
    header_font = Font(name="Arial", bold=True, color="FFFFFF", size=10)
    header_fill = PatternFill(start_color=HEADER_FILL, end_color=HEADER_FILL, fill_type="solid")
    title_font = Font(name="Arial", bold=True, size=11)
    body_font = Font(name="Arial", size=10)
    total_font = Font(name="Arial", bold=True, color="FFFFFF", size=10)
    total_fill = PatternFill(start_color=TOTAL_FILL, end_color=TOTAL_FILL, fill_type="solid")
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "Classification"

    # ── Bandeau titre ──
    title_lines = [
        "TABLEAU DE CLASSIFICATION DES CONTENEURS PAR POL ET VOLUME",
        f"Navire : {navire}    Voyage : {voyage}",
    ]
    if escale_info and escale_info.get("date_escale"):
        title_lines.append(f"Date d'escale (ETA/ATA) : {escale_info['date_escale']:%d/%m/%Y}")
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
    n_cols = col - 1
    for r in (header_row1, header_row2):
        for c in range(1, n_cols + 1):
            cell = ws.cell(row=r, column=c)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = center

    def _tranche_cols(t):
        i = TRANCHES.index(t)
        return 2 + i * 3, 3 + i * 3, 4 + i * 3  # NOMBRE, TONNAGE, VOLUME

    # ── Une ligne agrégée par POL (+ ligne TOTAL) — mêmes chiffres que
    # pivot_pol_tranche, pas de détail conteneur par conteneur ──
    pivot = pivot_pol_tranche(df_classifie)
    row = header_row2
    total_conteneurs = 0
    for _, pr in pivot.iterrows():
        row += 1
        is_total = pr["POL"] == "TOTAL"
        ws.cell(row=row, column=1, value=pr["POL"])
        for t in TRANCHES:
            c_nb, c_tn, c_vol = _tranche_cols(t)
            n = pr[f"{TRANCHE_LABELS[t]} - NOMBRE"]
            if n:
                ws.cell(row=row, column=c_nb, value=n)
                ws.cell(row=row, column=c_tn, value=pr[f"{TRANCHE_LABELS[t]} - TONNAGE"])
                ws.cell(row=row, column=c_vol, value=pr[f"{TRANCHE_LABELS[t]} - VOLUME"])
            if is_total:
                total_conteneurs += n
        for c in range(1, n_cols + 1):
            cell = ws.cell(row=row, column=c)
            if is_total:
                cell.font = total_font
                cell.fill = total_fill
            else:
                cell.font = body_font

    if pivot.empty or total_conteneurs == 0:
        ws.cell(row=row + 1, column=1, value="Aucun conteneur classifiable pour cette sélection.")

    for c in range(1, n_cols + 1):
        ws.column_dimensions[get_column_letter(c)].width = 14 if c > 1 else 20
    ws.freeze_panes = f"A{header_row2 + 1}"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
