"""
Page Pré-Masque cargo — manifeste PDF (Grimaldi) ou manifest Excel (navire à grue).

Deux onglets, même objectif : générer un pré-masque IPAKI/TETRAX depuis des
fichiers d'entrée différents.
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

# Force reload to ensure the latest version of tracking is used after a deploy
import importlib as _importlib
import tracking as _tracking_mod
_importlib.reload(_tracking_mod)
del _importlib, _tracking_mod

from manifest_parser import (
    parse_manifest,
    records_to_dataframe,
    build_workbook_bytes,
    classify_cargo_type,
    SHEET_COLUMNS,
    CAT_CODE_TO_SHEET,
)
from crane_manifest_parser import (
    parse_crane_manifest,
    generate_premasque_excel,
)
from tracking import (
    log_traitement,
    find_duplicate_bl,
    get_known_agents,
    get_known_services,
    get_known_roles,
    load_user_identity,
    save_user_identity,
    save_export_excel,
    save_source_pdf,
    set_verifie,
    normalize_name,
)
from ui_helpers import help_expander, combo_with_custom

# ---------------------------------------------------------------------------
# Constantes métier
# ---------------------------------------------------------------------------
SERVICES = ["Reporting", "Opérations", "Planification", "Data"]
ROLES    = ["Agent", "Chef de service", "Chef de la planification", "Analyste Data"]

_PROFILE_COLS: dict = {
    "Reporting": {
        "Vehicule":  ["BL_Numero", "Nature_BL", "Navire", "Voyage",
                      "Port_Chargement", "Port_Dechargement", "Pays_Transit",
                      "Marque", "Modele", "Nb_Unites", "Poids_Kg", "Etat",
                      "Chargeur_Nom", "Destinataire_Nom"],
        "Conteneur": ["BL_Numero", "Nature_BL", "Navire", "Voyage",
                      "Port_Chargement", "Port_Dechargement", "Pays_Transit",
                      "No_Conteneur", "No_Scelle", "Type_Colis",
                      "Nb_Unites", "Poids_Kg",
                      "Chargeur_Nom", "Destinataire_Nom"],
        "Colis":     ["BL_Numero", "Nature_BL", "Navire", "Voyage",
                      "Port_Chargement", "Port_Dechargement", "Pays_Transit",
                      "Type_Colis", "Nb_Unites", "Poids_Kg",
                      "Chargeur_Nom", "Destinataire_Nom"],
    },
    "Opérations": {
        "Vehicule":  ["BL_Numero", "Nature_BL",
                      "Port_Chargement", "Port_Dechargement", "Pays_Transit",
                      "Marque", "Modele", "Annee_Fabrication", "Couleur",
                      "Numeros_Chassis", "No_Moteur", "Code_HS", "Etat",
                      "Nb_Unites", "Poids_Kg", "LM",
                      "Chargeur_Nom", "Destinataire_Nom"],
        "Conteneur": ["BL_Numero", "Nature_BL",
                      "Port_Chargement", "Port_Dechargement", "Pays_Transit",
                      "No_Conteneur", "No_Scelle", "Type_Colis",
                      "Nb_Unites", "Poids_Kg", "Tare_Kg", "Volume_CBM"],
        "Colis":     ["BL_Numero", "Nature_BL",
                      "Port_Chargement", "Port_Dechargement", "Pays_Transit",
                      "Type_Colis", "Nb_Unites", "Poids_Kg"],
    },
}

COLUMN_LABELS: dict[str, str] = {
    "BL_Numero":             "N° BL",
    "Nature_BL":             "Nature BL",
    "Navire":                "Navire",
    "Voyage":                "Voyage",
    "Port_Chargement":       "Port charg.",
    "Port_Dechargement":     "Port déch.",
    "Pays_Transit":          "Pays transit",
    "Marque":                "Marque",
    "Modele":                "Modèle",
    "Annee_Fabrication":     "Année",
    "Couleur":               "Couleur",
    "Numeros_Chassis":       "N° Châssis",
    "No_Moteur":             "N° Moteur",
    "Code_HS":               "Code HS",
    "Etat":                  "État",
    "Nb_Unites":             "Qté",
    "Poids_Kg":              "Poids (kg)",
    "Tare_Kg":               "Tare (kg)",
    "Volume_CBM":            "Volume (m³)",
    "LM":                    "LM (m)",
    "No_Conteneur":          "N° Conteneur",
    "No_Scelle":             "N° Scellé",
    "Type_Colis":            "Type colis",
    "Chargeur_Nom":          "Chargeur",
    "Destinataire_Nom":      "Destinataire",
    "Destinataire_Adresse":  "Adresse dest.",
}


def _profile_default_cols(profile: str, sheet_name: str, available: list) -> list:
    desired = _PROFILE_COLS.get(profile, {}).get(sheet_name)
    if desired is None:
        return available
    return [c for c in desired if c in available]


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
if "records"               not in st.session_state:
    st.session_state["records"] = None
if "df"                    not in st.session_state:
    st.session_state["df"] = None
if "vessel_traitement_ids" not in st.session_state:
    st.session_state["vessel_traitement_ids"] = {}
if "cols_reset_counter"    not in st.session_state:
    st.session_state["cols_reset_counter"] = 0

# ---------------------------------------------------------------------------
# Identité — guard
# ---------------------------------------------------------------------------
identity = st.session_state.get("identity")
if not identity:
    st.warning(
        "**Identifiez-vous d'abord** depuis la page **Profil** "
        "pour pouvoir traiter des manifestes.",
        icon="👤",
    )
    st.stop()

agent   = identity["name"]
service = identity["service"]
role    = identity["role"]

# ---------------------------------------------------------------------------
# En-tête
# ---------------------------------------------------------------------------
st.title("Pré-Masque cargo")
st.caption(
    "Générez le pré-masque IPAKI/TETRAX depuis un manifeste PDF Grimaldi "
    "ou un manifest Excel navire à grue."
)

tab_pdf, tab_excel = st.tabs(
    ["📄 Manifeste PDF — Grimaldi", "📊 Manifest Excel — Navire à Grue"]
)

# ===========================================================================
# ONGLET 1 · Manifeste PDF (Grimaldi)
# ===========================================================================
with tab_pdf:

    with help_expander("ℹ️ Comment utiliser cet onglet ?"):
        st.markdown(
            """
1. **Chargez un ou plusieurs PDF** puis cliquez sur **▶ Lancer le traitement**.
2. **Choisissez votre profil** (*Reporting* ou *Opérations*) pour n'afficher
   que les colonnes utiles à votre service.
3. **Cochez ✅ Vérifié** après relecture pour valider la structuration.
4. **Téléchargez** le fichier Excel — un classeur par navire/voyage.
            """
        )

    # ── 1 · Upload + lancement ──
    uploaded_files = st.file_uploader(
        "Manifestes PDF à traiter",
        type="pdf",
        accept_multiple_files=True,
        help="Format : manifestes Grimaldi (rapport PBREPORT). Plusieurs fichiers acceptés.",
        key="pdf_uploader",
    )

    can_launch = bool(uploaded_files) and bool(agent)
    launch = st.button("▶ Lancer le traitement", type="primary", disabled=not can_launch)

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
        progress.empty()

        # ── Détection de doublon ──
        fichiers_refuses = {}
        for fname, recs in file_record_map.items():
            df_f = records_to_dataframe(recs)
            if df_f.empty:
                continue
            navire = df_f["Navire"].iloc[0]
            voyage = df_f["Voyage"].iloc[0]
            bl_numeros = df_f["BL_Numero"].dropna().unique().tolist()
            doublon = find_duplicate_bl(navire, voyage, bl_numeros)
            if not doublon.empty:
                fichiers_refuses[fname] = (navire, voyage, doublon)

        for fname, (navire, voyage, doublon) in fichiers_refuses.items():
            dernier = doublon.iloc[0]
            try:
                date_txt = datetime.fromisoformat(dernier["horodatage"]).strftime("%d/%m/%Y à %Hh%M")
            except (ValueError, TypeError):
                date_txt = str(dernier["horodatage"])
            bl_communs = dernier["bl_communs"]
            bl_apercu  = ", ".join(bl_communs[:5]) + (f" (+{len(bl_communs)-5} autres)" if len(bl_communs) > 5 else "")
            st.error(
                f"🚫 **Import refusé — `{fname}` déjà traité.**\n\n"
                f"**{navire} / {voyage}** — {len(bl_communs)} connaissement(s) structuré(s) "
                f"le {date_txt} par **{dernier['agent']}** (`{dernier['fichier']}`) : {bl_apercu}.\n\n"
                "Si ce manifeste concerne un **nouveau port de chargement** pour ce même navire/voyage, "
                "vérifiez que les numéros de B/L sont bien différents — consultez 🗂️ Archives pour l'historique."
            )

        file_record_map = {f: r for f, r in file_record_map.items() if f not in fichiers_refuses}
        all_records     = [r for recs in file_record_map.values() for r in recs]
        df_result       = records_to_dataframe(all_records)
        st.session_state["records"] = all_records
        st.session_state["df"]      = df_result
        n_refuses = len(fichiers_refuses)
        if all_records:
            msg = f"{len(all_records)} connaissements (B/L) extraits → {len(df_result)} lignes structurées."
            if n_refuses:
                msg += f" ({n_refuses} fichier(s) refusé(s) pour doublon.)"
            st.success(msg)
        elif n_refuses:
            st.info("Tous les fichiers chargés ont été refusés (doublons).")

        # ── Journalisation + archivage ──
        vessel_ids: dict = {}
        for fname, recs in file_record_map.items():
            df_f  = records_to_dataframe(recs)
            duree = round(file_durations.get(fname, 0), 2)
            src_file = next((uf for uf in uploaded_files if uf.name == fname), None)
            pdf_path = save_source_pdf(src_file.getvalue()) if src_file else None

            if df_f.empty:
                log_traitement(agent, fname, "", "", 0, 0, 0, 0, 0,
                               duree_sec=duree, pdf_path=pdf_path, service=service, role=role)
                continue

            navire = df_f["Navire"].iloc[0]
            voyage = df_f["Voyage"].iloc[0]
            export_buf  = build_workbook_bytes(df_f, navire, voyage, sheet_columns=SHEET_COLUMNS)
            export_path = save_export_excel(export_buf.getvalue())

            tid = log_traitement(
                agent, fname, navire, voyage,
                nb_bl=int(df_f["BL_Numero"].nunique()),
                nb_vehicules=int(df_f.loc[df_f["_cat_code"] == "V", "Nb_Unites"].sum()),
                nb_conteneurs=int(df_f.loc[df_f["_cat_code"] == "C", "Nb_Unites"].sum()),
                nb_colis=int(df_f.loc[df_f["_cat_code"] == "D", "Nb_Unites"].sum()),
                nb_transit=int((df_f["Pays_Transit"] != "").sum()),
                duree_sec=duree, export_path=export_path, pdf_path=pdf_path,
                type_cargo=classify_cargo_type(df_f),
                bl_numeros=df_f["BL_Numero"].dropna().unique().tolist(),
                service=service, role=role,
            )
            vessel_ids[(navire, voyage)] = tid

        st.session_state["vessel_traitement_ids"] = vessel_ids

    # ── 2 · Résultats ──
    df = st.session_state["df"]

    if df is not None and len(df):
        st.divider()

        n_navires = df[["Navire", "Voyage"]].drop_duplicates().shape[0]
        n_bl      = df["BL_Numero"].nunique()
        n_veh     = int(df.loc[df["_cat_code"] == "V", "Nb_Unites"].sum())
        n_cont    = int(df.loc[df["_cat_code"] == "C", "Nb_Unites"].sum())
        n_colis   = int(df.loc[df["_cat_code"] == "D", "Nb_Unites"].sum())

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Navires/voyages", n_navires)
        m2.metric("B/L", n_bl)
        m3.metric("Véhicules", n_veh)
        m4.metric("Conteneurs", n_cont)
        m5.metric("Colis", n_colis)

        st.caption(f"Traité par **{agent}** — {service} / {role}.")
        st.divider()

        vessels_all = df[["Navire", "Voyage"]].drop_duplicates().values.tolist()
        recap = (
            df.groupby(["Navire", "Voyage"])
              .agg(BL=("BL_Numero", "nunique"), Unites=("Nb_Unites", "sum"))
              .reset_index()
              .rename(columns={"BL": "B/L", "Unites": "Unités"})
        )
        recap["Fichier Excel"] = recap.apply(
            lambda r: f"Manifeste_{r['Navire']}_{r['Voyage']}".replace(" ", "_") + ".xlsx", axis=1
        )
        _grp_cols = ["Navire", "Voyage"]
        types_par_navire = (
            df.groupby(_grp_cols, group_keys=False)
              .apply(lambda sub: classify_cargo_type(sub.drop(columns=_grp_cols, errors="ignore")))
              .reset_index(name="Type de cargaison")
        )
        recap = recap.merge(types_par_navire, on=["Navire", "Voyage"], how="left")

        st.subheader("Récapitulatif par navire / voyage")
        st.dataframe(
            recap[["Navire", "Voyage", "Type de cargaison", "B/L", "Unités", "Fichier Excel"]],
            width='stretch', hide_index=True,
        )

        # ── Bandeau qualité ──
        veh_q = df[df["_cat_code"] == "V"]
        _quality_issues: list[str] = []
        _quality_ok:     list[str] = []

        def _pct_empty(series) -> int:
            if series.empty:
                return 100
            empty = series.isna() | (series.astype(str).str.strip().isin(["", "0", "0.0"]))
            return int(100 * empty.sum() / len(series))

        if not veh_q.empty:
            for col, label, seuil in [
                ("Poids_Kg",         "Poids (kg)",  60),
                ("Numeros_Chassis",  "N° Châssis",  10),
                ("Marque",           "Marque",       30),
                ("Annee_Fabrication","Année fab.",   70),
                ("Code_HS",          "Code HS",      80),
                ("Etat",             "État",         20),
            ]:
                if col in veh_q.columns:
                    p = _pct_empty(veh_q[col])
                    if p >= seuil:
                        _quality_issues.append(f"**{label}** ({100-p}% remplis)")
                    else:
                        _quality_ok.append(f"{label} ({100-p}%)")

        if _quality_issues:
            st.warning(
                "**Vérification recommandée — champs partiellement extraits depuis le PDF source :**\n\n"
                + "  ".join(f"· {f}" for f in _quality_issues)
                + "\n\nCes informations sont parfois absentes ou mal structurées dans le PDF Grimaldi. "
                "Complétez-les manuellement dans l'Excel exporté avant de les importer dans IPAKI/TETRAX.",
                icon="⚠️",
            )
        elif not veh_q.empty:
            st.success(
                "✅ Extraction complète — champs clés bien remplis : " + ", ".join(_quality_ok),
                icon="✅",
            )

        st.divider()

        # ── Aperçu + sélection des colonnes ──
        st.subheader("Aperçu et sélection des colonnes")

        if len(vessels_all) > 1:
            vessel_options = ["🔎 Tous les navires"] + [f"{nav} / {voy}" for nav, voy in vessels_all]
            vessel_choice  = st.selectbox("Filtrer par navire/voyage", vessel_options)
            if vessel_choice.startswith("🔎"):
                df_preview = df
            else:
                nav_sel, voy_sel = [s.strip() for s in vessel_choice.split(" / ", 1)]
                df_preview = df[(df["Navire"] == nav_sel) & (df["Voyage"] == voy_sel)]
        else:
            df_preview = df

        _profile_opts    = ["Tous", "Reporting", "Opérations", "Personnalisé"]
        _profile_default = service if service in _profile_opts else "Tous"
        _col_prof, _col_reset = st.columns([4, 1])
        with _col_prof:
            profile = st.selectbox(
                "🎛️ Profil d'affichage",
                _profile_opts,
                index=_profile_opts.index(_profile_default),
                key="profile_display",
            )
        with _col_reset:
            st.markdown("&nbsp;", unsafe_allow_html=True)
            if st.button("🔄 Réinitialiser les colonnes", use_container_width=True):
                st.session_state["cols_reset_counter"] += 1
                st.rerun()

        tab_labels   = {"Vehicule": "🚗 Véhicule", "Conteneur": "📦 Conteneur", "Colis": "📋 Colis"}
        cats_present = [c for c in CAT_CODE_TO_SHEET if c in set(df["_cat_code"].unique())]
        if not cats_present:
            cats_present = list(CAT_CODE_TO_SHEET)
        inner_tabs = st.tabs([tab_labels[CAT_CODE_TO_SHEET[c]] for c in cats_present])

        selected_columns = {}
        for cat_code, inner_tab in zip(cats_present, inner_tabs):
            sheet_name = CAT_CODE_TO_SHEET[cat_code]
            with inner_tab:
                sub      = df_preview[df_preview["_cat_code"] == cat_code].copy()
                all_cols = [c for c in SHEET_COLUMNS[sheet_name] if c in sub.columns]

                if sub.empty:
                    st.info("Aucune ligne dans cette catégorie pour la sélection en cours.")
                    selected_columns[sheet_name] = all_cols
                    continue

                prof_src = profile if profile != "Personnalisé" else "Tous"
                prof_def = _profile_default_cols(prof_src, sheet_name, all_cols)
                _reset_n = st.session_state["cols_reset_counter"]
                chosen = st.multiselect(
                    f"Colonnes à inclure dans l'export — {sheet_name}",
                    options=all_cols,
                    default=prof_def,
                    key=f"cols_{sheet_name}_{profile}_{_reset_n}",
                )
                selected_columns[sheet_name] = chosen or all_cols

                _preview = sub[selected_columns[sheet_name]].rename(columns=COLUMN_LABELS)
                st.dataframe(_preview, width='stretch', height=380)
                _lm_sum  = sub["LM"].sum() if "LM" in sub.columns and sub["LM"].notna().any() else None
                _caption = f"{len(sub)} lignes — {int(sub['Nb_Unites'].sum())} unités au total"
                if _lm_sum:
                    _caption += f" — {_lm_sum:.2f} m linéaires"
                st.caption(_caption)

        for cat_code, sheet_name in CAT_CODE_TO_SHEET.items():
            selected_columns.setdefault(sheet_name, SHEET_COLUMNS[sheet_name])

        # ── Validation ──
        vessel_ids = st.session_state.get("vessel_traitement_ids", {})
        if vessel_ids:
            st.divider()
            st.subheader("Validation après relecture")
            st.caption(
                "Cochez après avoir vérifié les données — visible dans le tableau de bord et les archives."
            )
            _vcols = st.columns(min(len(vessels_all), 3))
            for i, (nav, voy) in enumerate(vessels_all):
                tid = vessel_ids.get((nav, voy))
                if tid is None:
                    continue
                _vkey = f"verifie_check_{tid}"

                def _on_verifie_change(tid=tid, key=_vkey):
                    set_verifie(tid, st.session_state[key])

                with _vcols[i % 3]:
                    st.checkbox(
                        f"Vérifié — {nav} / {voy}",
                        key=_vkey,
                        on_change=_on_verifie_change,
                    )

        st.divider()

        # ── Export ──
        st.subheader("Export")
        vessels = df[["Navire", "Voyage"]].drop_duplicates().values.tolist()

        if len(vessels) == 1:
            navire, voyage = vessels[0]
            g_bl = df[(df["Navire"] == navire) & (df["Voyage"] == voyage)]
            buf  = build_workbook_bytes(g_bl, navire, voyage, sheet_columns=selected_columns)
            st.download_button(
                f"⬇ Télécharger Manifeste_{navire}_{voyage}.xlsx",
                data=buf,
                file_name=f"Manifeste_{navire}_{voyage}".replace(" ", "_") + ".xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
            )
        else:
            st.write(f"{len(vessels)} navires/voyages détectés — un classeur distinct par navire.")
            zip_buf = io.BytesIO()
            vessel_buffers = {}
            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for navire, voyage in vessels:
                    g_bl  = df[(df["Navire"] == navire) & (df["Voyage"] == voyage)]
                    buf   = build_workbook_bytes(g_bl, navire, voyage, sheet_columns=selected_columns)
                    fname = f"Manifeste_{navire}_{voyage}".replace(" ", "_") + ".xlsx"
                    zf.writestr(fname, buf.getvalue())
                    vessel_buffers[(navire, voyage)] = (fname, buf.getvalue())
            zip_buf.seek(0)
            st.download_button(
                "⬇ Télécharger tous les classeurs (.zip)",
                data=zip_buf, file_name="Manifestes_structures.zip", mime="application/zip",
                type="primary",
            )
            with st.expander("⬇ Télécharger individuellement"):
                for (navire, voyage), (fname, data) in vessel_buffers.items():
                    nb_bl_v = int(df[(df["Navire"] == navire) & (df["Voyage"] == voyage)]["BL_Numero"].nunique())
                    c1, c2  = st.columns([3, 2])
                    c1.write(f"**{navire}** / {voyage} — {nb_bl_v} B/L")
                    c2.download_button(
                        "⬇ Excel", data=data, file_name=fname,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"dl_{navire}_{voyage}", use_container_width=True,
                    )

    elif df is not None:
        st.warning("Aucune donnée extraite des fichiers fournis.")
    else:
        st.info("⬆ Chargez un ou plusieurs manifestes PDF puis cliquez sur *Lancer le traitement*.")


# ===========================================================================
# ONGLET 2 · Manifest Excel — Navire à Grue
# ===========================================================================
with tab_excel:

    with help_expander("ℹ️ Comment utiliser cet onglet ?"):
        st.markdown(
            """
- **1 · Chargez** le fichier manifest Excel du navire à grue (*.xlsx* ou *.xls*).
- **2 · Vérifiez** l'aperçu : le parser a automatiquement éclaté la colonne
  DESCRIPTION en colonnes séparées (1 ligne = 1 VIN/châssis).
- **3 · Corrigez** directement dans le tableau éditable si besoin.
- **4 · Téléchargez** le fichier Excel Pré-Masque IPAKI, prêt à importer.
- **Onglet « Données brutes »** dans l'Excel : conserve le texte brut source
  (type véhicule, N° moteur, expéditeur) pour référence ou vérification.
            """
        )

    st.divider()

    # ── 1 · Upload ──
    st.subheader("1 · Charger le manifest")
    uploaded_crane = st.file_uploader(
        "Manifest navire à grue (.xlsx / .xls)",
        type=["xlsx", "xls"],
        accept_multiple_files=False,
        help="Manifest Excel au format chinois (Cargo Manifest / Destination Manifest).",
        key="crane_uploader",
    )

    if not uploaded_crane:
        st.info("⬆ Chargez le fichier manifest pour commencer.")
    else:
        # ── Parsing ──
        df_crane = None
        parse_ok  = True
        try:
            df_crane = parse_crane_manifest(uploaded_crane.getvalue(), uploaded_crane.name)
        except ValueError as e:
            st.error(str(e), icon="🚫")
            parse_ok = False
        except Exception as e:
            st.error(f"Erreur inattendue lors du parsing : {e}", icon="🚫")
            parse_ok = False

        if parse_ok and (df_crane is None or df_crane.empty):
            st.warning("Aucune donnée extraite du fichier.", icon="⚠️")
            parse_ok = False

        if parse_ok and df_crane is not None:
            n_total   = len(df_crane)
            n_vin     = int((df_crane["CHÂSSIS"] != "").sum())
            n_sans_vin = n_total - n_vin
            n_bl      = df_crane["BL"].nunique()
            n_transbo = int((df_crane["NATURE BL"] == "Transbo").sum())

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Véhicules", n_total)
            col2.metric("VINs extraits", n_vin)
            col3.metric("Sans VIN", n_sans_vin,
                        help="Lignes sans N° châssis dans le manifest source — à compléter manuellement.")
            col4.metric("B/L distincts", n_bl)

            if n_sans_vin > 0:
                st.warning(
                    f"{n_sans_vin} ligne(s) sans N° châssis — "
                    "à compléter manuellement dans le tableau ou dans l'Excel exporté.",
                    icon="⚠️",
                )
            if n_transbo > 0:
                st.info(
                    f"{n_transbo} véhicule(s) en transit (Transbo) — "
                    "Destination finale extraite automatiquement.",
                    icon="ℹ️",
                )

            st.success(f"Manifest parsé : {n_total} lignes extraites depuis {n_bl} B/L.", icon="✅")
            st.divider()

            # ── 2 · Aperçu et édition ──
            st.subheader("2 · Vérifier et ajuster les données")
            st.caption(
                "Colonnes éditables directement — l'export utilisera vos modifications."
            )

            edit_cols = [c for c in df_crane.columns if not c.startswith("_")]
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
                "MODE DE TRANSPORT": st.column_config.TextColumn("Mode Transport", width="medium"),
                "ESCALE TETRAX": st.column_config.TextColumn("Escale TETRAX", width="medium"),
                "ESCALE IPAKI": st.column_config.TextColumn("Escale IPAKI", width="medium"),
                "POL IPAKI": st.column_config.TextColumn("POL IPAKI", width="medium"),
                "POD IPAKI": st.column_config.TextColumn("POD IPAKI", width="medium"),
                "FINAL DESTINATION IPAKI": st.column_config.TextColumn("Dest. IPAKI", width="medium"),
                "BLItem YardItemCode": st.column_config.TextColumn("BLItem", width="medium"),
            }

            edited_df = st.data_editor(
                df_crane[edit_cols],
                column_config=col_config,
                hide_index=True,
                use_container_width=True,
                num_rows="fixed",
                key="crane_editor",
                height=min(38 * (len(df_crane) + 1) + 3, 600),
            )

            df_final = edited_df.copy()
            for col in df_crane.columns:
                if col.startswith("_"):
                    df_final[col] = df_crane[col].values
            df_final["MARQUE & MODELE"] = df_final.apply(
                lambda r: f"{r['MARQUE']} {r['MODELE']}".strip() if r["MARQUE"] else r["MODELE"],
                axis=1,
            )

            st.divider()

            # ── 3 · Génération + archivage automatique ──
            st.subheader("3 · Générer le Pré-Masque IPAKI")
            stem     = pathlib.Path(uploaded_crane.name).stem
            out_name = f"PREMASQUE_IPAKI_{stem}.xlsx"
            try:
                xls_bytes = generate_premasque_excel(df_final)

                # Archivage automatique à la génération
                _crane_archive_key = f"_crane_archived_{stem}"
                if not st.session_state.get(_crane_archive_key):
                    try:
                        _export_path = save_export_excel(xls_bytes)
                        # Navire/voyage depuis le nom du fichier à défaut
                        _navire = df_final["BL"].iloc[0].split("/")[0].strip() if len(df_final) else stem
                        log_traitement(
                            agent, uploaded_crane.name,
                            navire=_navire, voyage="",
                            nb_bl=int(df_final["BL"].nunique()) if "BL" in df_final.columns else 0,
                            nb_vehicules=n_total,
                            nb_conteneurs=0, nb_colis=0,
                            nb_transit=n_transbo,
                            export_path=_export_path,
                            type_cargo="Vehicule",
                            bl_numeros=df_final["BL"].dropna().unique().tolist() if "BL" in df_final.columns else [],
                            service=service, role=role,
                        )
                        st.session_state[_crane_archive_key] = True
                    except Exception as _ae:
                        pass  # archivage non bloquant

                st.download_button(
                    "⬇ Télécharger le Pré-Masque IPAKI (.xlsx)",
                    data=xls_bytes,
                    file_name=out_name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary",
                    help=f"{n_total} lignes · format pré-masque IPAKI · onglet 'Données brutes' inclus",
                )
                st.caption(
                    f"{n_total} véhicule(s) · {n_vin} VINs extraits automatiquement · "
                    f"{n_sans_vin} à compléter manuellement · archivé ✅"
                )
            except Exception as e:
                st.error(f"Erreur lors de la génération : {e}", icon="🚫")

            # ── Données brutes ──
            with help_expander("🔍 Données brutes extraites (type véhicule, N° moteur, expéditeur)"):
                raw_cols = {
                    "_BL_SOURCE":    "BL",
                    "_VEHICLE_TYPE": "Type véhicule",
                    "_ENGINE_NO":    "N° Moteur",
                    "_SHIPPER":      "Expéditeur",
                }
                avail = {k: v for k, v in raw_cols.items() if k in df_final.columns}
                if avail:
                    df_raw_view = df_final[list(avail.keys())].rename(columns=avail)
                    st.dataframe(df_raw_view, hide_index=True, use_container_width=True)
