"""
Page de structuration des manifestes cargo Grimaldi.
Upload PDF → extraction automatique → aperçu → export Excel par navire.
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
# (Streamlit hot-reload keeps old modules in sys.modules)
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

# "Autre" n'est plus une entrée figée de la liste — combo_with_custom() offre
# désormais une saisie libre ("✏️ Autre (préciser)…") plus explicite, qui
# évite qu'un agent choisisse un simple "Autre" sans préciser son service réel.
SERVICES = ["Reporting", "Opérations", "Planification", "Data"]
ROLES    = ["Agent", "Chef de service", "Chef de la planification", "Analyste Data"]

# Profils de colonnes par service (None = toutes les colonnes disponibles).
# Les noms doivent correspondre exactement aux clés de SHEET_COLUMNS.
_PROFILE_COLS: dict = {
    "Reporting": {
        # Objectif : alimenter la Liste prévisionnelle
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
        # Objectif : alimenter le Pré-masque IPAKI / TETRAX
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


# Libellés d'affichage français pour les colonnes (utilisés uniquement dans
# l'aperçu st.dataframe — les noms Python sont conservés pour l'export Excel).
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
    """Colonnes pré-cochées pour ce profil/feuille, intersectées avec available."""
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
if "changing_identity"     not in st.session_state:
    st.session_state["changing_identity"] = False
# Compteur incrémenté par le bouton « Réinitialiser les colonnes » — force
# Streamlit à recréer le widget multiselect avec les valeurs par défaut du profil.
if "cols_reset_counter" not in st.session_state:
    st.session_state["cols_reset_counter"] = 0

# ---------------------------------------------------------------------------
# En-tête
# ---------------------------------------------------------------------------
st.title("📦 Structuration des manifestes cargo")
st.caption(
    "Upload un ou plusieurs manifestes PDF (Grimaldi) → extraction automatique "
    "→ vérification → export Excel structuré par navire."
)

with help_expander("ℹ️ Comment utiliser cette page ?"):
    st.markdown(
        """
1. **Identifiez-vous une seule fois** — votre nom, service et rôle sont mémorisés
   pour toutes les sessions suivantes. Cliquez sur *Modifier* pour changer.
2. **Chargez un ou plusieurs PDF** puis cliquez sur **▶ Lancer le traitement**.
3. **Choisissez votre profil** (*Reporting* ou *Opérations*) pour afficher
   uniquement les colonnes utiles à votre service.
4. **Cochez ✅ Vérifié** après relecture pour valider la structuration.
5. **Téléchargez** le fichier Excel — un classeur par navire/voyage.
        """
    )

# ---------------------------------------------------------------------------
# 1. Identification — affichée UNE SEULE FOIS par session, puis réduite en
#    bannière. L'identité n'est considérée CONFIRMÉE que si CETTE session de
#    navigateur l'a explicitement validée (st.session_state) — le fichier
#    d'identité mémorisé sur le serveur (load_user_identity) sert seulement à
#    PRÉ-REMPLIR le formulaire, jamais à confirmer silencieusement une
#    identité. Avant ce correctif, un fichier partagé côté serveur faisait
#    qu'un nouvel onglet affichait directement le nom de la DERNIÈRE personne
#    à s'être identifiée sur l'app (sans risque sur un poste local à un seul
#    agent, mais source de mauvaise attribution sur l'app partagée en ligne).
# ---------------------------------------------------------------------------
identity = st.session_state.get("identity")
_suggested = identity or load_user_identity()

if identity and not st.session_state.get("changing_identity"):
    # ── Bannière compacte si CETTE session a déjà validé son identité ──
    col_id, col_btn = st.columns([5, 1])
    with col_id:
        st.info(
            f"🧑‍💻 **{identity['name']}** — {identity['service']} / {identity['role']}"
        )
    with col_btn:
        if st.button("✏️ Modifier", use_container_width=True):
            st.session_state["changing_identity"] = True
            st.rerun()
    agent   = identity["name"]
    service = identity["service"]
    role    = identity["role"]
else:
    # ── Formulaire complet (premier lancement de CETTE session, ou modification) ──
    st.subheader("Votre identité")
    st.caption(
        "Confirmez votre nom pour cette session — mémorisé ensuite pour "
        "toutes les pages tant que cet onglet reste ouvert."
    )

    known = get_known_agents()
    known_names = [a["agent"] for a in known]
    _suggested_name = normalize_name(_suggested.get("name", "")) if _suggested else ""

    if known_names:
        _opts = ["— Choisir —"] + known_names + ["✏️ Nouveau nom…"]
        _default_idx = _opts.index(_suggested_name) if _suggested_name in known_names else 0
        _sel = st.selectbox("Nom et prénom", _opts, index=_default_idx, key="id_name_select")
        if _sel == "✏️ Nouveau nom…":
            agent_input = st.text_input(
                "Saisir votre nom", value=_suggested_name if _suggested_name not in known_names else "",
                placeholder="ex : Kouadio Charles", key="id_name_new",
            )
            _prev = {}
        elif _sel == "— Choisir —":
            agent_input = ""
            _prev = {}
        else:
            agent_input = _sel
            _prev = next((a for a in known if a["agent"] == _sel), {})
    else:
        agent_input = st.text_input(
            "Nom et prénom", value=_suggested_name, placeholder="ex : Kouadio Charles",
            help="Visible dans le tableau de bord et les archives. Insensible à la "
                 "casse — 'KOUADIO Charles' et 'kouadio charles' sont reconnus comme "
                 "la même personne.",
        )
        _prev = {}

    _svc_default  = _prev.get("service") or (_suggested.get("service", "") if _suggested else "")
    _role_default = _prev.get("role")    or (_suggested.get("role", "")    if _suggested else "")
    col_svc, col_role = st.columns(2)
    with col_svc:
        service_input = combo_with_custom(
            "Service", get_known_services(SERVICES), default_value=_svc_default,
            key=f"id_svc_{agent_input}",
            help="Choisissez un service existant ou saisissez le vôtre librement.",
        )
    with col_role:
        role_input = combo_with_custom(
            "Rôle", get_known_roles(ROLES), default_value=_role_default,
            key=f"id_role_{agent_input}",
            help="Choisissez un rôle existant ou saisissez le vôtre librement.",
        )

    agent_normalized = normalize_name(agent_input)
    _ok = bool(agent_normalized) and bool(service_input) and bool(role_input)
    if st.button("✅ Valider mon identité", type="primary", disabled=not _ok):
        save_user_identity(agent_normalized, service_input, role_input)
        st.session_state["identity"]          = {"name": agent_normalized,
                                                  "service": service_input,
                                                  "role": role_input}
        st.session_state["changing_identity"] = False
        st.rerun()

    if not _ok:
        st.warning("Renseignez votre nom, votre service et votre rôle pour continuer.")
        st.stop()

    agent, service, role = agent_normalized, service_input, role_input

# ---------------------------------------------------------------------------
# 2. Upload + lancement
# ---------------------------------------------------------------------------
uploaded_files = st.file_uploader(
    "Manifestes PDF à traiter",
    type="pdf",
    accept_multiple_files=True,
    help="Format : manifestes Grimaldi (rapport PBREPORT). Plusieurs fichiers acceptés.",
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
    # ── Détection de doublon (avant toute journalisation) ──
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
        bl_communs  = dernier["bl_communs"]
        bl_apercu   = ", ".join(bl_communs[:5]) + (f" (+{len(bl_communs)-5} autres)" if len(bl_communs) > 5 else "")
        st.error(
            f"🚫 **Import refusé — `{fname}` déjà traité.**\n\n"
            f"**{navire} / {voyage}** — {len(bl_communs)} connaissement(s) structuré(s) "
            f"le {date_txt} par **{dernier['agent']}** (`{dernier['fichier']}`) : {bl_apercu}.\n\n"
            "Si ce manifeste concerne un **nouveau port de chargement** pour ce même navire/voyage, "
            "vérifiez que les numéros de B/L sont bien différents — consultez 🗂️ Archives pour l'historique."
        )

    file_record_map = {f: r for f, r in file_record_map.items() if f not in fichiers_refuses}
    all_records     = [r for recs in file_record_map.values() for r in recs]
    df              = records_to_dataframe(all_records)
    st.session_state["records"] = all_records
    st.session_state["df"]      = df
    n_refuses = len(fichiers_refuses)
    if all_records:
        msg = f"{len(all_records)} connaissements (B/L) extraits → {len(df)} lignes structurées."
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

# ---------------------------------------------------------------------------
# 3. Résultats
# ---------------------------------------------------------------------------
df = st.session_state["df"]

if df is not None and len(df):
    st.divider()

    # Indicateurs rapides
    n_navires = df[["Navire", "Voyage"]].drop_duplicates().shape[0]
    n_bl      = df["BL_Numero"].nunique()
    n_veh     = int(df.loc[df["_cat_code"] == "V", "Nb_Unites"].sum())
    n_cont    = int(df.loc[df["_cat_code"] == "C", "Nb_Unites"].sum())
    n_colis   = int(df.loc[df["_cat_code"] == "D", "Nb_Unites"].sum())
    n_transit = int((df["Pays_Transit"] != "").sum())

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Navires/voyages", n_navires)
    m2.metric("B/L", n_bl)
    m3.metric("Véhicules", n_veh)
    m4.metric("Conteneurs", n_cont)
    m5.metric("Lots en transit", n_transit)

    st.caption(
        f"Traité par **{agent}** — {service} / {role}."
    )
    st.divider()

    # Récapitulatif navire/voyage
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
    # include_groups n'existe que depuis pandas 2.2 — on exclut manuellement
    # les colonnes de regroupement pour rester compatible avec pandas < 2.2.
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

    # Profil d'affichage — pré-sélectionné sur le service de l'agent
    _profile_opts    = ["Tous", "Reporting", "Opérations", "Personnalisé"]
    _profile_default = service if service in _profile_opts else "Tous"
    _col_prof, _col_reset = st.columns([4, 1])
    with _col_prof:
        profile = st.selectbox(
            "🎛️ Profil d'affichage",
            _profile_opts,
            index=_profile_opts.index(_profile_default),
            key="profile_display",
            help=(
                "**Reporting** → colonnes pour la Liste prévisionnelle.  \n"
                "**Opérations** → colonnes pour le Pré-masque IPAKI/TETRAX.  \n"
                "**Personnalisé** → ajustez manuellement ci-dessous."
            ),
        )
    with _col_reset:
        st.markdown("&nbsp;", unsafe_allow_html=True)   # alignement vertical
        if st.button(
            "🔄 Réinitialiser les colonnes",
            help="Remet les colonnes affichées aux valeurs par défaut du profil sélectionné.",
            use_container_width=True,
        ):
            st.session_state["cols_reset_counter"] += 1
            st.rerun()

    tab_labels   = {"Vehicule": "🚗 Véhicule", "Conteneur": "📦 Conteneur", "Colis": "📋 Colis"}
    cats_present = [c for c in CAT_CODE_TO_SHEET if c in set(df["_cat_code"].unique())]
    if not cats_present:
        cats_present = list(CAT_CODE_TO_SHEET)
    tabs = st.tabs([tab_labels[CAT_CODE_TO_SHEET[c]] for c in cats_present])

    selected_columns = {}
    for cat_code, tab in zip(cats_present, tabs):
        sheet_name = CAT_CODE_TO_SHEET[cat_code]
        with tab:
            sub       = df_preview[df_preview["_cat_code"] == cat_code].copy()
            all_cols  = [c for c in SHEET_COLUMNS[sheet_name] if c in sub.columns]

            if sub.empty:
                st.info("Aucune ligne dans cette catégorie pour la sélection en cours.")
                selected_columns[sheet_name] = all_cols
                continue

            prof_src  = profile if profile != "Personnalisé" else "Tous"
            prof_def  = _profile_default_cols(prof_src, sheet_name, all_cols)

            _reset_n = st.session_state["cols_reset_counter"]
            chosen = st.multiselect(
                f"Colonnes à inclure dans l'export — {sheet_name}",
                options=all_cols,
                default=prof_def,
                # Clé incluant profil ET compteur : changer l'un ou l'autre
                # réinitialise la sélection et recharge les valeurs par défaut.
                key=f"cols_{sheet_name}_{profile}_{_reset_n}",
                help="Les colonnes décochées sont exclues du fichier Excel téléchargé. "
                     "Utilisez **Réinitialiser les colonnes** pour revenir aux colonnes du profil.",
            )
            selected_columns[sheet_name] = chosen or all_cols

            _preview = (
                sub[selected_columns[sheet_name]]
                .rename(columns=COLUMN_LABELS)
            )
            st.dataframe(_preview, width='stretch', height=380)
            _lm_sum = sub["LM"].sum() if "LM" in sub.columns and sub["LM"].notna().any() else None
            _caption = f"{len(sub)} lignes — {int(sub['Nb_Unites'].sum())} unités au total"
            if _lm_sum:
                _caption += f" — {_lm_sum:.2f} m linéaires"
            st.caption(_caption)

    for cat_code, sheet_name in CAT_CODE_TO_SHEET.items():
        selected_columns.setdefault(sheet_name, SHEET_COLUMNS[sheet_name])

    # ── Validation (vérification inline) ──
    vessel_ids = st.session_state.get("vessel_traitement_ids", {})
    if vessel_ids:
        st.divider()
        st.subheader("✅ Validation après relecture")
        st.caption(
            "Cochez après avoir vérifié les données — cette information est visible "
            "dans le tableau de bord et les archives."
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
        st.caption("💡 Ces fichiers restent aussi accessibles depuis **🗂️ Archives** avec le PDF source.")

elif df is not None:
    st.warning("Aucune donnée extraite des fichiers fournis.")
else:
    st.info("⬆ Chargez un ou plusieurs manifestes PDF puis cliquez sur *Lancer le traitement*.")
