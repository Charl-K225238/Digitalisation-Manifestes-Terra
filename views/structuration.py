"""
Page de structuration des manifestes cargo Grimaldi.
Upload PDF -> extraction automatique -> aperçu -> export Excel par navire.
"""
import io
import pathlib
import sys
import time
import zipfile
from datetime import datetime

import pandas as pd
import streamlit as st

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from manifest_parser import (
    parse_manifest,
    records_to_dataframe,
    build_workbook_bytes,
    classify_cargo_type,
    SHEET_COLUMNS,
    CAT_CODE_TO_SHEET,
)
from tracking import log_traitement, find_similar, save_export_excel, save_source_pdf
from ui_helpers import help_expander

st.title("📦 Structuration des manifestes cargo")
st.caption(
    "Upload un ou plusieurs manifestes PDF (Grimaldi) → extraction automatique "
    "→ vérification → export Excel structuré par navire, avec un onglet par "
    "type de marchandise (Véhicule / Conteneur / Colis)."
)

with help_expander("ℹ️ Comment utiliser cette page ?"):
    st.markdown(
        """
1. Indiquez votre **nom** — il permet de retrouver qui a traité quoi dans le
   tableau de bord et l'archive.
2. Chargez un ou plusieurs manifestes PDF puis cliquez sur **▶ Lancer le traitement**.
3. Vérifiez les indicateurs et l'aperçu par catégorie. Les colonnes issues d'une
   reconnaissance heuristique (adresse, statut neuf/usager, type de colis)
   méritent une relecture ponctuelle avant export.
4. Décochez les colonnes non nécessaires dans chaque onglet si besoin.
5. Téléchargez le fichier Excel — un classeur par navire/voyage détecté,
   regroupés en `.zip` s'il y en a plusieurs.

Chaque manifeste traité est automatiquement conservé (PDF source + Excel
structuré) dans **🗂️ Archives**, où vous pouvez le retrouver, le rechercher
et le re-télécharger à tout moment. 📊 Le **Tableau de bord** suit de son
côté les volumes traités et le temps de structuration, semaine par semaine.
        """
    )

if "records" not in st.session_state:
    st.session_state["records"] = None
if "df" not in st.session_state:
    st.session_state["df"] = None

# ---------------------------------------------------------------------------
# 1. Identification + upload
# ---------------------------------------------------------------------------
agent = st.text_input(
    "🧑‍💻 Nom et prénom",
    placeholder="ex : KOUADIO Charles",
    help="Traçabilité : qui a traité ce manifeste. Visible dans le tableau de bord et l'archive.",
)

uploaded_files = st.file_uploader(
    "Manifestes PDF à traiter",
    type="pdf",
    accept_multiple_files=True,
    help="Format accepté : manifestes Grimaldi (rapport PBREPORT). Plusieurs fichiers à la fois possible.",
)

col_a, col_b = st.columns([1, 4])
with col_a:
    can_launch = bool(uploaded_files) and bool(agent.strip())
    launch = st.button("▶ Lancer le traitement", type="primary", disabled=not can_launch)
if uploaded_files and not agent.strip():
    st.warning("Merci de renseigner votre nom avant de lancer le traitement.")

if launch and uploaded_files:
    progress = st.progress(0, text="Démarrage…")
    all_records = []
    n = len(uploaded_files)
    file_record_map = {}
    file_durations = {}
    for i, f in enumerate(uploaded_files):
        progress.progress(i / n, text=f"Analyse de {f.name}…")
        t0 = time.time()
        try:
            recs = parse_manifest(f, f.name)
            all_records.extend(recs)
            file_record_map[f.name] = recs
        except Exception as e:
            st.error(f"Erreur sur {f.name} : {e}")
        file_durations[f.name] = time.time() - t0
        progress.progress((i + 1) / n, text=f"{f.name} traité")

    progress.progress(1.0, text="Structuration des données…")
    df = records_to_dataframe(all_records)
    st.session_state["records"] = all_records
    st.session_state["df"] = df
    progress.empty()
    st.success(f"{len(all_records)} connaissements (B/L) extraits → {len(df)} lignes structurées.")
    st.session_state["last_agent"] = agent.strip()

    # --- Journalisation + archivage (alimente le tableau de bord et l'archive) ---
    doublons_detectes = []
    for fname, recs in file_record_map.items():
        df_f = records_to_dataframe(recs)
        duree = round(file_durations.get(fname, 0), 2)

        # Le PDF source est toujours archivé, même si l'extraction n'a rien donné
        # (traçabilité + permet de rejouer/diagnostiquer plus tard).
        src_file = next((uf for uf in uploaded_files if uf.name == fname), None)
        pdf_path = save_source_pdf(src_file.getvalue()) if src_file is not None else None

        if df_f.empty:
            log_traitement(agent.strip(), fname, "", "", 0, 0, 0, 0, 0,
                            duree_sec=duree, pdf_path=pdf_path)
            continue

        navire = df_f["Navire"].iloc[0]
        voyage = df_f["Voyage"].iloc[0]
        nb_bl_actuel = int(df_f["BL_Numero"].nunique())

        # Détection de doublon : CE navire ET ce voyage ont-ils déjà été
        # traités ensemble ? (un même code voyage réutilisé par un autre
        # navire est normal et n'est pas un doublon — voir find_similar)
        anterieurs = find_similar(navire, voyage)
        if not anterieurs.empty:
            doublons_detectes.append((navire, voyage, fname, nb_bl_actuel, anterieurs))

        # Archive : Excel structuré (toutes colonnes, indépendant du choix
        # d'export ci-dessous) + lien vers le PDF déjà sauvegardé.
        export_buf = build_workbook_bytes(df_f, navire, voyage, sheet_columns=SHEET_COLUMNS)
        export_path = save_export_excel(export_buf.getvalue())

        log_traitement(
            agent.strip(), fname, navire, voyage,
            nb_bl=int(df_f["BL_Numero"].nunique()),
            nb_vehicules=int(df_f.loc[df_f["_cat_code"] == "V", "Nb_Unites"].sum()),
            nb_conteneurs=int(df_f.loc[df_f["_cat_code"] == "C", "Nb_Unites"].sum()),
            nb_colis=int(df_f.loc[df_f["_cat_code"] == "D", "Nb_Unites"].sum()),
            nb_transit=int((df_f["Pays_Transit"] != "").sum()),
            duree_sec=duree, export_path=export_path, pdf_path=pdf_path,
            type_cargo=classify_cargo_type(df_f),
        )

    for navire, voyage, fname, nb_bl_actuel, anterieurs in doublons_detectes:
        dernier = anterieurs.iloc[0]
        try:
            date_txt = datetime.fromisoformat(dernier["horodatage"]).strftime("%d/%m/%Y")
        except ValueError:
            date_txt = dernier["horodatage"]
        nb_bl_avant = dernier.get("nb_bl")
        if pd.notna(nb_bl_avant) and int(nb_bl_avant) == nb_bl_actuel:
            nuance = (
                f"même nombre de B/L ({nb_bl_actuel}) — vérifiez qu'il ne s'agit pas "
                "d'un envoi en double du même fichier."
            )
        elif pd.notna(nb_bl_avant):
            nuance = (
                f"mais avec un nombre de B/L différent ({int(nb_bl_avant)} avant, "
                f"{nb_bl_actuel} maintenant) — probablement une mise à jour, pas un doublon."
            )
        else:
            nuance = "vérifiez qu'il ne s'agit pas d'un doublon."
        st.warning(
            f"⚠️ **{navire} / {voyage}** (`{fname}`) semble déjà avoir été traité "
            f"{len(anterieurs)} fois — la dernière le {date_txt} par **{dernier['agent']}** "
            f"(`{dernier['fichier']}`), {nuance}"
        )

# ---------------------------------------------------------------------------
# 2. Résultats
# ---------------------------------------------------------------------------
df = st.session_state["df"]

if df is not None and len(df):
    st.divider()

    # --- Indicateurs rapides ---
    n_navires = df[["Navire", "Voyage"]].drop_duplicates().shape[0]
    n_bl = df["BL_Numero"].nunique()
    n_veh = int(df.loc[df["_cat_code"] == "V", "Nb_Unites"].sum())
    n_cont = int(df.loc[df["_cat_code"] == "C", "Nb_Unites"].sum())
    n_colis = int(df.loc[df["_cat_code"] == "D", "Nb_Unites"].sum())
    n_transit = int((df["Pays_Transit"] != "").sum())

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Navires/voyages", n_navires)
    m2.metric("B/L", n_bl)
    m3.metric("Véhicules", n_veh)
    m4.metric("Conteneurs", n_cont)
    m5.metric("Lots en transit", n_transit)

    st.caption(
        f"Traitement effectué par **{agent.strip() if agent else st.session_state.get('last_agent', '—')}**."
    )

    st.divider()

    # --- Récapitulatif par navire/voyage : un classeur Excel = une ligne ici ---
    vessels_all = df[["Navire", "Voyage"]].drop_duplicates().values.tolist()
    recap = (
        df.groupby(["Navire", "Voyage"])
          .agg(
              BL=("BL_Numero", "nunique"),
              Unites=("Nb_Unites", "sum"),
          )
          .reset_index()
          .rename(columns={"Navire": "Navire", "Voyage": "Voyage", "BL": "B/L", "Unites": "Unités"})
    )
    recap["Fichier Excel"] = recap.apply(
        lambda r: f"Manifeste_{r['Navire']}_{r['Voyage']}".replace(" ", "_") + ".xlsx", axis=1
    )
    # Type de cargaison (véhicules uniquement / mixte / ...) détecté à partir
    # des catégories réellement présentes pour ce navire/voyage — certains
    # manifestes ne listent que des véhicules, d'autres combinent plusieurs
    # types de marchandise.
    types_par_navire = (
        df.groupby(["Navire", "Voyage"], group_keys=False)
          .apply(classify_cargo_type, include_groups=False)
          .reset_index(name="Type de cargaison")
    )
    recap = recap.merge(types_par_navire, on=["Navire", "Voyage"], how="left")

    st.subheader("Récapitulatif par navire/voyage")
    st.caption(
        "Chaque ligne ci-dessous correspondra à **un fichier Excel distinct** à "
        "l'export — les données ne sont regroupées ensemble que si le navire "
        "*et* le voyage sont identiques. Le **type de cargaison** aide à "
        "repérer d'un coup d'œil les manifestes ne listant que des véhicules."
    )
    st.dataframe(
        recap[["Navire", "Voyage", "Type de cargaison", "B/L", "Unités", "Fichier Excel"]],
        width='stretch', hide_index=True,
    )

    st.divider()

    # --- Aperçu + sélection de colonnes par catégorie ---
    st.subheader("Aperçu et sélection des colonnes")

    if len(vessels_all) > 1:
        vessel_options = ["🔎 Tous les navires (vue combinée)"] + [
            f"{nav} / {voy}" for nav, voy in vessels_all
        ]
        vessel_choice = st.selectbox(
            "Filtrer l'aperçu par navire/voyage",
            vessel_options,
            help=(
                "Plusieurs navires/voyages ont été détectés dans les fichiers "
                "chargés — chacun produira son propre fichier Excel. Choisissez "
                "un navire pour n'afficher que les lignes de son futur fichier, "
                "ou gardez la vue combinée pour tout voir d'un coup."
            ),
        )
        if vessel_choice.startswith("🔎"):
            df_preview = df
        else:
            nav_sel, voy_sel = [s.strip() for s in vessel_choice.split(" / ", 1)]
            df_preview = df[(df["Navire"] == nav_sel) & (df["Voyage"] == voy_sel)]
    else:
        df_preview = df

    tab_labels = {"Vehicule": "🚗 Véhicule", "Conteneur": "📦 Conteneur", "Colis": "📋 Colis"}
    # Onglets limités aux catégories réellement présentes dans l'ensemble des
    # fichiers chargés (pas seulement la sélection courante) : un manifeste
    # "véhicules uniquement" n'affiche alors ni onglet Conteneur ni Colis
    # vides, plutôt que de forcer un clic pour découvrir qu'ils sont vides.
    cats_presentes = [c for c in CAT_CODE_TO_SHEET if c in set(df["_cat_code"].unique())]
    if not cats_presentes:
        cats_presentes = list(CAT_CODE_TO_SHEET)
    tabs = st.tabs([tab_labels[CAT_CODE_TO_SHEET[c]] for c in cats_presentes])

    selected_columns = {}
    for cat_code, tab in zip(cats_presentes, tabs):
        sheet_name = CAT_CODE_TO_SHEET[cat_code]
        with tab:
            sub = df_preview[df_preview["_cat_code"] == cat_code].copy()
            default_cols = [c for c in SHEET_COLUMNS[sheet_name] if c in sub.columns]

            if sub.empty:
                st.info("Aucune ligne dans cette catégorie pour le navire sélectionné.")
                selected_columns[sheet_name] = default_cols
                continue

            chosen = st.multiselect(
                f"Colonnes à conserver — {sheet_name}",
                options=default_cols,
                default=default_cols,
                key=f"cols_{sheet_name}",
                help="Décochez une colonne pour l'exclure du fichier Excel exporté (s'applique à tous les navires).",
            )
            selected_columns[sheet_name] = chosen or default_cols

            display_cols = selected_columns[sheet_name]
            st.dataframe(sub[display_cols], width='stretch', height=400)
            st.caption(f"{len(sub)} lignes — {int(sub['Nb_Unites'].sum())} unités au total")

    # Catégories totalement absentes des fichiers chargés : colonnes par
    # défaut conservées pour l'export (l'onglet Excel correspondant restera
    # simplement vide, ce qui est normal pour un manifeste véhicules uniquement).
    for cat_code, sheet_name in CAT_CODE_TO_SHEET.items():
        selected_columns.setdefault(sheet_name, SHEET_COLUMNS[sheet_name])

    st.divider()

    # --- Export ---
    st.subheader("Export")
    vessels = df[["Navire", "Voyage"]].drop_duplicates().values.tolist()

    if len(vessels) == 1:
        navire, voyage = vessels[0]
        g_bl = df[(df["Navire"] == navire) & (df["Voyage"] == voyage)]
        buf = build_workbook_bytes(g_bl, navire, voyage, sheet_columns=selected_columns)
        st.download_button(
            f"⬇ Télécharger Manifeste_{navire}_{voyage}.xlsx",
            data=buf,
            file_name=f"Manifeste_{navire}_{voyage}".replace(" ", "_") + ".xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )
    else:
        st.write(
            f"{len(vessels)} navires/voyages détectés — un classeur Excel distinct "
            "par navire, téléchargeables individuellement ci-dessous ou en une fois via le .zip."
        )
        zip_buf = io.BytesIO()
        vessel_buffers = {}
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for navire, voyage in vessels:
                g_bl = df[(df["Navire"] == navire) & (df["Voyage"] == voyage)]
                buf = build_workbook_bytes(g_bl, navire, voyage, sheet_columns=selected_columns)
                fname = f"Manifeste_{navire}_{voyage}".replace(" ", "_") + ".xlsx"
                zf.writestr(fname, buf.getvalue())
                vessel_buffers[(navire, voyage)] = (fname, buf.getvalue())
        zip_buf.seek(0)

        st.download_button(
            "⬇ Télécharger tous les classeurs (.zip)",
            data=zip_buf,
            file_name="Manifestes_structures.zip",
            mime="application/zip",
            type="primary",
            help="Un seul fichier .zip contenant un classeur Excel par navire/voyage.",
        )

        with st.expander("⬇ Télécharger les classeurs individuellement"):
            for (navire, voyage), (fname, data) in vessel_buffers.items():
                nb_bl_v = int(df[(df["Navire"] == navire) & (df["Voyage"] == voyage)]["BL_Numero"].nunique())
                c1, c2 = st.columns([3, 2])
                c1.write(f"**{navire}** / {voyage} — {nb_bl_v} B/L")
                c2.download_button(
                    "⬇ Excel",
                    data=data,
                    file_name=fname,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"dl_{navire}_{voyage}",
                    width='stretch',
                )
            st.caption(
                "💡 Ces mêmes fichiers restent aussi accessibles à tout moment "
                "depuis l'onglet **🗂️ Archives**, avec le PDF source associé."
            )

elif df is not None:
    st.warning("Aucune donnée n'a pu être extraite des fichiers fournis.")
else:
    st.info("⬆ Chargez un ou plusieurs manifestes PDF puis cliquez sur *Lancer le traitement*.")
