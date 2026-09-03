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
import pandas as pd

import reporting_builder as rbld
from manifest_parser import _volume_tranche

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

    nature = df_veh.get("Nature_BL", pd.Series([""] * len(df_veh))).astype(str).str.strip().str.lower()
    is_import = nature.isin(["import", ""])  # "" = ancien export sans Nature_BL renseignée, traité comme Import
    diag["hors_import"] = int((~is_import).sum())
    df_i = df_veh[is_import].copy()
    if df_i.empty:
        return pd.DataFrame(columns=["POL", "Tranche", "Poids_Unitaire_Kg", "Volume_CBM", "Neuf"]), diag

    volume = pd.to_numeric(df_i.get("Volume_CBM"), errors="coerce")
    tranche = volume.map(_volume_tranche)
    diag["sans_volume"] = int((tranche == "").sum())
    poids = pd.to_numeric(df_i.get("Poids_Unitaire_Kg"), errors="coerce")
    neuf = df_i.get("Etat", pd.Series([""] * len(df_i))).astype(str).str.strip().str.lower() == "neuf"

    df_out = pd.DataFrame({
        "POL": df_i.get("Port_Chargement", "").astype(str).str.strip(),
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
