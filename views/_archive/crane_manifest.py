"""
Page Pré-Masque Navire à Grue — Manifest Excel chinois → Pré-masque IPAKI.

L'agent charge un manifest Excel (format navire cargo général / grue),
le parser éclate automatiquement la colonne DESCRIPTION en colonnes séparées
(MODELE, CHÂSSIS/VIN, ANNEE, ETAT, DESTINATION...) à raison d'une ligne par
VIN/châssis, puis génère un fichier Excel pré-masque prêt à vérifier/compléter.
"""
import io
import pathlib
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from crane_manifest_parser import (
    parse_crane_manifest,
    generate_premasque_excel,
)
from ui_helpers import help_expander

# Guard identité
_identity = st.session_state.get("identity")
if not _identity:
    st.warning(
        "👤 **Identifiez-vous d'abord** depuis la page **Profil**.",
        icon="👤",
    )
    st.stop()

# ---------------------------------------------------------------------------
# En-tête
# ---------------------------------------------------------------------------
st.title("🏗️ Pré-Masque Navire à Grue")
st.caption(
    "Chargez un manifest Excel (navire cargo général / grue) → "
    "extraction automatique des VINs, modèles, années, destinations → "
    "export Pré-Masque IPAKI prêt à vérifier."
)

with help_expander("ℹ️ Comment utiliser cette page ?"):
    st.markdown(
        """
- **1 · Chargez** le fichier manifest Excel du navire à grue (*.xlsx* ou *.xls*).
- **2 · Vérifiez** l'aperçu : le parser a automatiquement éclaté la colonne
  DESCRIPTION en colonnes séparées (1 ligne = 1 VIN/châssis). Les colonnes en
  orange clair sont à compléter manuellement (MARQUE, ETAT si non détecté…).
- **3 · Corrigez** directement dans le tableau éditable si besoin.
- **4 · Téléchargez** le fichier Excel Pré-Masque IPAKI, prêt à importer.
- **Onglet « Données brutes »** dans l'Excel : conserve le texte brut source
  (type véhicule, N° moteur, expéditeur) pour référence ou vérification.
        """
    )

st.divider()

# ---------------------------------------------------------------------------
# 1 · Upload
# ---------------------------------------------------------------------------
st.subheader("1 · Charger le manifest")
uploaded = st.file_uploader(
    "📂 Manifest navire à grue (.xlsx / .xls)",
    type=["xlsx", "xls"],
    accept_multiple_files=False,
    help="Manifest Excel au format chinois (Cargo Manifest / Destination Manifest).",
)

if not uploaded:
    st.info("⬆ Chargez le fichier manifest pour commencer.")
    st.stop()

# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
try:
    df = parse_crane_manifest(uploaded.getvalue(), uploaded.name)
except ValueError as e:
    st.error(str(e), icon="🚫")
    st.stop()
except Exception as e:
    st.error(f"Erreur inattendue lors du parsing : {e}", icon="🚫")
    st.stop()

if df.empty:
    st.warning("Aucune donnée extraite du fichier.", icon="⚠️")
    st.stop()

# Statistiques rapides
n_total = len(df)
n_vin = int((df["CHÂSSIS"] != "").sum())
n_sans_vin = n_total - n_vin
n_bl = df["BL"].nunique()
n_transbo = int((df["NATURE BL"] == "Transbo").sum())

col1, col2, col3, col4 = st.columns(4)
col1.metric("Véhicules", n_total)
col2.metric("VINs extraits", n_vin)
col3.metric("Sans VIN", n_sans_vin,
            help="Lignes sans N° châssis dans le manifest source — à compléter manuellement.")
col4.metric("B/L distincts", n_bl)

if n_sans_vin > 0:
    st.warning(
        f"⚠️ {n_sans_vin} ligne(s) sans N° châssis (VIN absent du manifest source) — "
        "à compléter manuellement dans le tableau ou dans l'Excel exporté.",
        icon="⚠️",
    )
if n_transbo > 0:
    st.info(
        f"ℹ️ {n_transbo} véhicule(s) en transit (Transbo) — "
        "Destination finale extraite automatiquement.",
        icon="ℹ️",
    )

st.success(f"✅ Manifest parsé : {n_total} lignes extraites depuis {n_bl} B/L.", icon="✅")

st.divider()

# ---------------------------------------------------------------------------
# 2 · Aperçu et édition
# ---------------------------------------------------------------------------
st.subheader("2 · Vérifier et ajuster les données")
st.caption(
    "Colonnes éditables directement — l'export utilisera vos modifications. "
    "Colonnes grisées : calculées automatiquement."
)

# Colonnes à afficher/éditer (sans les colonnes _ internes)
edit_cols = [c for c in df.columns if not c.startswith("_")]

# Configuration des colonnes pour l'éditeur
col_config = {
    "NBRE": st.column_config.NumberColumn("N°", width="small"),
    "NATURE BL": st.column_config.SelectboxColumn(
        "Nature BL", options=["Import", "Transbo", "Export"], width="small"
    ),
    "POL TETRAX": st.column_config.TextColumn("POL", width="medium"),
    "POD TETRAX": st.column_config.TextColumn("POD", width="medium"),
    "FINAL DESTINATION TETRAX": st.column_config.TextColumn("Dest. Finale", width="medium"),
    "POIDS TETRAX (KG)": st.column_config.NumberColumn("Poids (kg)", format="%d", width="small"),
    "TYPE / TAILLE": st.column_config.SelectboxColumn(
        "Type", options=["C", "V", "T"], width="small",
        help="C : < 15m³  |  V : 15–50m³  |  T : > 50m³"
    ),
    "VOLUME TETRAX": st.column_config.NumberColumn("Volume (m³)", format="%.3f", width="small"),
    "BL": st.column_config.TextColumn("N° BL", width="medium"),
    "MARQUE": st.column_config.TextColumn("Marque", width="medium"),
    "MODELE": st.column_config.TextColumn("Modèle", width="medium"),
    "MARQUE & MODELE": st.column_config.TextColumn("Marque & Modèle", width="medium"),
    "ETAT": st.column_config.SelectboxColumn(
        "État",
        options=[
            "VEHICULES NEUFS, VOITURES NEUVES, CAMION",
            "VEHICULES USAGES,VOITURES OCCASIONS",
        ],
        width="large",
    ),
    "ANNEE DE FABRICATION": st.column_config.TextColumn("Année", width="small"),
    "CHÂSSIS": st.column_config.TextColumn("Châssis / VIN", width="large"),
    "TYPE D'ACTION": st.column_config.SelectboxColumn(
        "Action", options=["IMPORT", "EXPORT", "TRANSBO"], width="small"
    ),
    "POIDS IPAKI (TON)": st.column_config.NumberColumn("Poids (t)", format="%.3f", width="small"),
    "VOLUME": st.column_config.NumberColumn("Vol. (m³)", format="%.3f", width="small"),
    "CLIENT": st.column_config.TextColumn("Client", width="large"),
    "OBSERVATION": st.column_config.TextColumn("Observation", width="large"),
    # Colonnes IPAKI (à compléter manuellement)
    "MODE DE TRANSPORT": st.column_config.TextColumn("Mode Transport", width="medium"),
    "ESCALE TETRAX": st.column_config.TextColumn("Escale TETRAX", width="medium"),
    "ESCALE IPAKI": st.column_config.TextColumn("Escale IPAKI", width="medium"),
    "POL IPAKI": st.column_config.TextColumn("POL IPAKI", width="medium"),
    "POD IPAKI": st.column_config.TextColumn("POD IPAKI", width="medium"),
    "FINAL DESTINATION IPAKI": st.column_config.TextColumn("Dest. IPAKI", width="medium"),
    "BLItem YardItemCode": st.column_config.TextColumn("BLItem", width="medium"),
}

edited_df = st.data_editor(
    df[edit_cols],
    column_config=col_config,
    hide_index=True,
    use_container_width=True,
    num_rows="fixed",
    key="crane_editor",
    height=min(38 * (len(df) + 1) + 3, 600),
)

# Recombiner les colonnes éditées avec les colonnes internes (_)
df_final = edited_df.copy()
for col in df.columns:
    if col.startswith("_"):
        df_final[col] = df[col].values

# Recalculer MARQUE & MODELE si l'une des deux a été modifiée
df_final["MARQUE & MODELE"] = df_final.apply(
    lambda r: f"{r['MARQUE']} {r['MODELE']}".strip() if r["MARQUE"] else r["MODELE"],
    axis=1,
)

st.divider()

# ---------------------------------------------------------------------------
# 3 · Génération et téléchargement
# ---------------------------------------------------------------------------
st.subheader("3 · Générer le Pré-Masque IPAKI")

# Nom de fichier basé sur le fichier source
stem = pathlib.Path(uploaded.name).stem
out_name = f"PREMASQUE_IPAKI_{stem}.xlsx"

try:
    xls_bytes = generate_premasque_excel(df_final)
    st.download_button(
        "⬇ Télécharger le Pré-Masque IPAKI (.xlsx)",
        data=xls_bytes,
        file_name=out_name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        use_container_width=False,
        help=f"{n_total} lignes · format pré-masque IPAKI · onglet 'Données brutes' inclus",
    )
    st.caption(
        f"✅ {n_total} véhicule(s) · {n_vin} VINs extraits automatiquement · "
        f"{n_sans_vin} à compléter manuellement"
    )
except Exception as e:
    st.error(f"Erreur lors de la génération : {e}", icon="🚫")

# ---------------------------------------------------------------------------
# Aperçu des données brutes (expandable)
# ---------------------------------------------------------------------------
with help_expander("🔍 Données brutes extraites (type véhicule, N° moteur, expéditeur)"):
    raw_cols = {
        "_BL_SOURCE": "BL",
        "_VEHICLE_TYPE": "Type véhicule",
        "_ENGINE_NO": "N° Moteur",
        "_SHIPPER": "Expéditeur",
    }
    avail = {k: v for k, v in raw_cols.items() if k in df_final.columns}
    if avail:
        df_raw_view = df_final[list(avail.keys())].rename(columns=avail)
        st.dataframe(df_raw_view, hide_index=True, use_container_width=True)
