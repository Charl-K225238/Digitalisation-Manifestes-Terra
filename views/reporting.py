"""
Page Reporting — construction de la liste prévisionnelle définitive à partir
des manifestes déjà structurés, et rapprochements avec la 1ère liste
provisoire (service Reporting) et le Discharging Container Summary.

Voir claude/ANALYSE_ONGLET_REPORTING_2026-09-03.md (projet Claude) pour
l'analyse complète ayant guidé ce design.
"""
import io
import pathlib
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import tracking
import reporting_builder as rbld
from ui_helpers import help_expander, current_identity

tracking.clear_demo_data()


@st.cache_data(ttl=120, show_spinner=False)
def _cached_list_voyages() -> pd.DataFrame:
    """Cache 2 min — list_voyages_disponibles() relit un export Excel archivé
    par voyage pour connaître ses ports, coûteux à refaire à chaque rerun
    Streamlit (chaque clic sur la page). Le bouton "🔄 Actualiser" ci-dessous
    vide ce cache pour voir immédiatement un manifeste tout juste traité."""
    return rbld.list_voyages_disponibles()


st.title("Reporting")
st.caption(
    "Construit la liste prévisionnelle définitive à partir des manifestes déjà "
    "structurés (onglet Pré-Masque), et la rapproche de la 1ère liste provisoire "
    "reçue et du Discharging Container Summary — pour accélérer sa création "
    "et faciliter la vérification avec les autres sources."
)

with help_expander("ℹ️ Comment utiliser cette page"):
    st.markdown(
        "1. **Choisissez un Navire/Voyage** déjà traité dans l'onglet Pré-Masque, "
        "puis générez la liste prévisionnelle définitive (3 onglets RORO / "
        "CONTENEUR / BB, agrégée depuis tous les manifestes déjà structurés "
        "pour ce voyage). C'est le manifeste qui fait foi.\n"
        "2. **Rapprochez-la avec la 1ère liste provisoire** reçue (souvent "
        "incomplète) : les B/L présents dans les manifestes mais absents de "
        "cette liste sont à ajouter, ceux présents dans la liste mais absents "
        "des manifestes déjà traités sont à vérifier (port pas encore "
        "traité, ou booking modifié).\n"
        "3. **Rapprochez avec le Discharging Container Summary** (souvent "
        "incomplet lui aussi) : ce fichier ne contient aucun numéro de B/L, "
        "le rapprochement se fait uniquement par numéro de conteneur, et "
        "uniquement pour l'onglet CONTENEUR.\n\n"
        "Colonnes de booking (Agent, STATUTS, REMARQUES, ARRIVAL, CLIENT "
        "distinct du destinataire...) n'existent pas dans le manifeste PDF "
        "brut : elles restent vides dans la liste générée, à compléter par "
        "le service Reporting — c'est voulu, pas un oubli."
    )

# ---------------------------------------------------------------------------
# Sélection du Navire / Voyage
# ---------------------------------------------------------------------------
col_h1, col_h2 = st.columns([5, 1])
with col_h1:
    st.subheader("1. Liste prévisionnelle définitive")
with col_h2:
    if st.button("🔄 Actualiser", help="Voir immédiatement un manifeste tout juste traité depuis Pré-Masque (sinon repris automatiquement sous 2 min)."):
        _cached_list_voyages.clear()
        st.rerun()

voyages = _cached_list_voyages()
if voyages.empty:
    st.info("Aucun manifeste structuré pour l'instant — traitez d'abord des manifestes depuis la page Pré-Masque.")
    st.stop()

voyages["label"] = voyages["navire"] + " — " + voyages["voyage"] + " (ports : " + voyages["ports"] + ")"
choix = st.selectbox("Navire / Voyage", voyages["label"], key="rep_voyage_choice")
sel = voyages[voyages["label"] == choix].iloc[0]
navire, voyage = sel["navire"], sel["voyage"]

col_a, col_b = st.columns([1, 2])
with col_a:
    generer = st.button("🔄 Générer / actualiser la liste prévisionnelle définitive", type="primary", use_container_width=True)
with col_b:
    ports_attendus_raw = st.text_input(
        "Ports de chargement attendus pour ce voyage (optionnel, séparés par des virgules)",
        key="rep_ports_attendus",
        help="Si renseigné, un avertissement liste les ports qui manquent encore parmi les manifestes traités.",
    )

if generer:
    _was_definitive = tracking.get_liste_definitive(navire, voyage)
    with st.spinner("Agrégation des manifestes déjà structurés…"):
        dfs, used_df, ports, diag = rbld.fetch_voyage_detail(navire, voyage)
        previs = rbld.build_liste_previsionnelle(dfs)
    if _was_definitive:
        tracking.clear_liste_definitive(navire, voyage)
        st.session_state["rep_definitive_cleared"] = True
    st.session_state["rep_previs"] = previs
    st.session_state["rep_ports"] = ports
    st.session_state["rep_used"] = used_df
    st.session_state["rep_diag"] = diag
    st.session_state["rep_navire"] = navire
    st.session_state["rep_voyage"] = voyage

previs = st.session_state.get("rep_previs")
if previs is not None and st.session_state.get("rep_navire") == navire and st.session_state.get("rep_voyage") == voyage:
    ports = st.session_state.get("rep_ports", [])
    used_df = st.session_state.get("rep_used", pd.DataFrame())

    # ── Statut "liste définitive" — badge informatif, pas de verrouillage :
    # à re-marquer par un agent après chaque régénération si besoin. ──
    if st.session_state.pop("rep_definitive_cleared", False):
        st.warning("⚠️ La liste a été régénérée — le statut « définitive » a été retiré. Marquez-la à nouveau une fois vérifiée.")
    _definitive = tracking.get_liste_definitive(navire, voyage)
    if _definitive:
        st.success(
            f"✅ Liste définitive — marquée par **{_definitive['agent']}** "
            f"le {_definitive['horodatage']:%d/%m/%Y à %H:%M}."
        )
    else:
        if st.button("✅ Marquer cette liste comme définitive", key="rep_mark_definitive"):
            _identity = current_identity()
            if not _identity or not _identity.get("name"):
                st.error("Identifiez-vous d'abord sur la page Profil.")
            else:
                tracking.mark_liste_definitive(navire, voyage, _identity["name"])
                st.rerun()

    diag = st.session_state.get("rep_diag", {})
    if not ports:
        if diag.get("echec_telechargement") or diag.get("illisible"):
            st.error(
                f"{diag.get('total', 0)} traitement(s) archivé(s) trouvé(s) pour ce Navire/Voyage, "
                f"mais aucun exploitable : {diag.get('echec_telechargement', 0)} export(s) introuvable(s) "
                f"au téléchargement, {diag.get('illisible', 0)} export(s) illisible(s) ou sans données "
                "reconnues. Contactez le support si le problème persiste (fichier archivé corrompu ?)."
            )
        elif diag.get("sans_export"):
            st.warning(
                f"{diag.get('sans_export', 0)} traitement(s) trouvé(s) pour ce Navire/Voyage mais sans "
                "export archivé — retraitez le(s) manifeste(s) depuis Pré-Masque."
            )
        else:
            st.warning("Aucun manifeste traité pour ce Navire/Voyage — traitez-le d'abord depuis la page Pré-Masque.")
    else:
        st.success(f"Ports de chargement couverts par les manifestes déjà traités : {', '.join(ports)}")
        if ports_attendus_raw.strip():
            attendus = {p.strip().upper() for p in ports_attendus_raw.split(",") if p.strip()}
            couverts_norm = {p.upper() for p in ports}
            manquants_ports = sorted(p for p in attendus if not any(p in c or c in p for c in couverts_norm))
            if manquants_ports:
                st.warning(f"⚠️ Ports attendus non encore couverts : {', '.join(manquants_ports)} — la liste ci-dessous est générée quand même, à réactualiser une fois ces manifestes disponibles.")
            else:
                st.success("Tous les ports attendus sont couverts.")

    m1, m2, m3 = st.columns(3)
    m1.metric("RORO — lignes / B/L", f"{len(previs['RORO'])} / {previs['RORO']['_BL_norm'].nunique()}")
    m2.metric("CONTENEUR — lignes / B/L", f"{len(previs['CONTENEUR'])} / {previs['CONTENEUR']['_BL_norm'].nunique()}")
    m3.metric("BB — lignes / B/L", f"{len(previs['BB'])} / {previs['BB']['_BL_norm'].nunique()}")

    if not used_df.empty:
        with st.expander(f"📄 {len(used_df)} traitement(s) source utilisé(s)"):
            st.dataframe(used_df[["horodatage", "agent", "fichier", "nb_bl"]], use_container_width=True, hide_index=True)

    tab_roro, tab_cont, tab_bb = st.tabs(["RORO", "CONTENEUR", "BB"])
    for tab, key in ((tab_roro, "RORO"), (tab_cont, "CONTENEUR"), (tab_bb, "BB")):
        with tab:
            df_show = previs[key].drop(columns=[c for c in previs[key].columns if c.startswith("_")], errors="ignore")
            st.dataframe(df_show, use_container_width=True, hide_index=True)

    wb_buf = rbld.build_previsionnelle_workbook_bytes(previs, navire, voyage)
    st.download_button(
        "⬇️ Télécharger la liste prévisionnelle définitive (.xlsx)",
        data=wb_buf.getvalue(),
        file_name=f"Liste_Previsionnelle_{navire}_{voyage}.xlsx".replace(" ", "_"),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

st.divider()

# ---------------------------------------------------------------------------
# Étape 2 — Rapprochement avec la 1ère liste provisoire
# ---------------------------------------------------------------------------
st.subheader("2. Rapprochement avec la 1ère liste provisoire")
if previs is None:
    st.info("Générez d'abord la liste prévisionnelle définitive ci-dessus.")
else:
    prov_file = st.file_uploader("Liste prévisionnelle provisoire reçue (.xls / .xlsx)", type=["xls", "xlsx"], key="rep_prov_file")
    if prov_file is not None and st.button("🔎 Rapprocher avec la liste provisoire", key="rep_prov_btn"):
        try:
            prov, prov_warnings = rbld.parse_liste_provisoire(prov_file.getvalue(), prov_file.name)
        except Exception as e:
            st.error(f"Impossible de lire ce fichier : {e}")
            prov, prov_warnings = None, {}
        if prov is not None:
            resultats = {}
            for sheet in ("RORO", "CONTENEUR", "BB"):
                manquants, en_trop, n_communs = rbld.reconcile_bl(previs[sheet], prov.get(sheet, pd.DataFrame()))
                resultats[sheet] = (manquants, en_trop, n_communs)
            st.session_state["rep_bl_resultats"] = resultats
            st.session_state["rep_prov_data"] = prov
            st.session_state["rep_prov_warnings"] = prov_warnings

    resultats = st.session_state.get("rep_bl_resultats")
    prov_warnings = st.session_state.get("rep_prov_warnings", {})
    if prov_warnings:
        st.error(
            "⚠️ Rapprochement non fiable pour " + ", ".join(prov_warnings.keys()) + " — "
            "colonne B/L non reconnue dans ce fichier. Détail :\n\n"
            + "\n".join(f"- **{s}** : {msg}" for s, msg in prov_warnings.items())
        )
    if resultats:
        # ── Filtre par port(s) de chargement — le rapprochement complet peut
        # couvrir plusieurs ports d'un même voyage ; permet de se concentrer
        # sur un port à la fois sans perdre les autres (export toujours
        # complet, non filtré). ──
        _ports_dispo = sorted({
            str(p).strip() for sheet in ("RORO", "CONTENEUR", "BB")
            for df_side in resultats[sheet][:2] if not df_side.empty and "POL" in df_side.columns
            for p in df_side["POL"].dropna().unique() if str(p).strip()
        })
        ports_filtre = st.multiselect(
            "Filtrer par port(s) de chargement (POL)",
            _ports_dispo, key="rep_prov_ports_filtre",
            help="Aucune sélection = tous les ports affichés. Le rapport téléchargé reste complet quel que soit ce filtre.",
        )

        def _filtre_port(df):
            if not ports_filtre or df.empty or "POL" not in df.columns:
                return df
            return df[df["POL"].astype(str).str.strip().isin(ports_filtre)]

        tabs_rapproch = st.tabs(["RORO", "CONTENEUR", "BB"])
        for tab, sheet in zip(tabs_rapproch, ("RORO", "CONTENEUR", "BB")):
            manquants, en_trop, n_communs = resultats[sheet]
            manquants_f, en_trop_f = _filtre_port(manquants), _filtre_port(en_trop)
            with tab:
                st.caption(f"{n_communs} B/L en commun avec la liste provisoire.")
                st.markdown(f"🟡 **À ajouter** — {manquants_f['_BL_norm'].nunique() if not manquants_f.empty else 0} B/L des manifestes absents de la liste provisoire")
                if not manquants_f.empty:
                    st.dataframe(manquants_f.drop(columns=[c for c in manquants_f.columns if c.startswith("_")], errors="ignore"), use_container_width=True, hide_index=True)
                else:
                    st.caption("Aucun.")
                st.markdown(f"🔵 **À vérifier** — {en_trop_f['_BL_norm'].nunique() if not en_trop_f.empty else 0} B/L de la liste provisoire absents des manifestes déjà traités")
                if not en_trop_f.empty:
                    st.dataframe(en_trop_f.drop(columns=[c for c in en_trop_f.columns if c.startswith("_")], errors="ignore"), use_container_width=True, hide_index=True)
                else:
                    st.caption("Aucun.")

        report_buf = rbld.build_report_workbook_bytes(
            {f"{s} - A ajouter": resultats[s][0] for s in ("RORO", "CONTENEUR", "BB")}
            | {f"{s} - A verifier": resultats[s][1] for s in ("RORO", "CONTENEUR", "BB")},
            title_lines=[f"Navire : {navire}", f"Voyage : {voyage}", "Rapprochement avec la 1ère liste provisoire"],
        )
        st.download_button(
            "⬇️ Télécharger le rapport d'écarts (.xlsx)",
            data=report_buf.getvalue(),
            file_name=f"Rapprochement_Liste_Provisoire_{navire}_{voyage}.xlsx".replace(" ", "_"),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="rep_prov_dl",
        )

        # ── Validation des écarts → un seul fichier corrigé (retour
        # utilisateur 03/09) : au lieu de croiser 3 fichiers à la main,
        # produit la liste provisoire reçue mise à jour directement — B/L du
        # manifeste absents ajoutés en fin d'onglet (🟠), B/L de la liste
        # provisoire non retrouvés dans les manifestes signalés en place
        # (🔴, jamais supprimés — le port correspondant n'est peut-être
        # simplement pas encore traité). Ne couvre que ce rapprochement
        # (étape 2) — le Discharging Summary (étape 3) compare des écarts de
        # poids, pas une liste de B/L à compléter, nature différente. ──
        st.markdown("**✅ Valider les écarts → produire une liste corrigée et à jour**")

        _n_ajouts_par_onglet = {s: (resultats[s][0]["_BL_norm"].nunique() if not resultats[s][0].empty else 0) for s in ("RORO", "CONTENEUR", "BB")}
        _n_signales_par_onglet = {s: (resultats[s][1]["_BL_norm"].nunique() if not resultats[s][1].empty else 0) for s in ("RORO", "CONTENEUR", "BB")}
        _n_ajouts_total = sum(_n_ajouts_par_onglet.values())
        _n_signales_total = sum(_n_signales_par_onglet.values())
        _detail_ajouts = ", ".join(f"{s} : {n}" for s, n in _n_ajouts_par_onglet.items() if n)
        _detail_signales = ", ".join(f"{s} : {n}" for s, n in _n_signales_par_onglet.items() if n)
        st.caption(
            "Ce fichier reprend la liste provisoire reçue telle quelle (POL, quantités, poids… "
            "inchangés) et lui applique 2 ajustements — rien d'autre n'est modifié, aucune ligne "
            "n'est supprimée :\n\n"
            f"🟠 **{_n_ajouts_total} B/L ajouté(s)** en fin d'onglet — présents dans le manifeste déjà "
            f"traité mais absents de la liste provisoire reçue" + (f" ({_detail_ajouts})" if _detail_ajouts else "") + ".\n\n"
            f"🔴 **{_n_signales_total} B/L signalé(s)** en place, en rouge — présents dans la liste "
            "provisoire reçue mais non retrouvés dans les manifestes déjà traités (à vérifier avant "
            "confirmation : peut-être un port pas encore traité, pas forcément une erreur)"
            + (f" ({_detail_signales})" if _detail_signales else "") + "."
        )
        if prov_warnings:
            st.caption("⚠️ Le(s) onglet(s) signalé(s) plus haut en erreur (colonne B/L non reconnue) seront quand même inclus tels quels dans le fichier corrigé, sans ajustement fiable — à ne pas utiliser pour ces onglets tant que la colonne B/L n'est pas identifiée.")
        if st.button("✅ Valider les écarts et produire la liste corrigée", key="rep_prov_valider", type="primary"):
            prov_data = st.session_state.get("rep_prov_data", {})
            corrige_buf = rbld.build_liste_corrigee_workbook_bytes(prov_data, previs, resultats, navire, voyage)
            st.session_state["rep_corrige_buf"] = corrige_buf.getvalue()
            st.session_state["rep_corrige_recap"] = (_n_ajouts_total, _n_signales_total)
        corrige_bytes = st.session_state.get("rep_corrige_buf")
        if corrige_bytes:
            _recap = st.session_state.get("rep_corrige_recap")
            if _recap:
                st.success(f"Fichier généré : {_recap[0]} B/L ajouté(s) en orange, {_recap[1]} B/L signalé(s) en rouge à vérifier.")
            st.download_button(
                "⬇️ Télécharger la liste corrigée (.xlsx)",
                data=corrige_bytes,
                file_name=f"Liste_Provisoire_Corrigee_{navire}_{voyage}.xlsx".replace(" ", "_"),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="rep_prov_corrige_dl",
                use_container_width=True,
            )

st.divider()

# ---------------------------------------------------------------------------
# Étape 3 — Rapprochement avec le Discharging Container Summary
# ---------------------------------------------------------------------------
st.subheader("3. Rapprochement avec le Discharging Container Summary")
if previs is None:
    st.info("Générez d'abord la liste prévisionnelle définitive ci-dessus.")
else:
    st.caption(
        "Rapprochement par numéro de conteneur uniquement (ce fichier ne contient "
        "pas de B/L) — limité à l'onglet CONTENEUR. Ce fichier étant souvent "
        "préliminaire/incomplet, un conteneur manquant d'un côté n'est pas "
        "automatiquement une anomalie — à confirmer avec le bord."
    )
    disch_file = st.file_uploader("Discharging Container Summary (.pdf)", type=["pdf"], key="rep_disch_file")
    if disch_file is not None and st.button("🔎 Rapprocher avec le Discharging Summary", key="rep_disch_btn"):
        try:
            df_disch = rbld.parse_discharging_summary_pdf(disch_file.getvalue())
        except Exception as e:
            st.error(f"Impossible de lire ce fichier : {e}")
            df_disch = pd.DataFrame()
        if df_disch.empty:
            st.warning("Aucune ligne conteneur reconnue dans ce PDF.")
        else:
            manq_disch, manq_manif, merged, dup_warning = rbld.reconcile_containers(previs["CONTENEUR"], df_disch)
            st.session_state["rep_cont_resultats"] = (df_disch, manq_disch, manq_manif, merged, dup_warning)

    cont_resultats = st.session_state.get("rep_cont_resultats")
    if cont_resultats is not None and len(cont_resultats) != 5:
        # Format d'un ancien déploiement encore en mémoire de session (le
        # code de l'app peut être mis à jour sans réinitialiser les sessions
        # déjà ouvertes côté Streamlit Cloud) — on l'ignore plutôt que de
        # planter, l'agent n'a qu'à relancer le rapprochement.
        cont_resultats = None
        st.session_state["rep_cont_resultats"] = None
        st.info("Résultat précédent obsolète (mise à jour de l'application) — relancez le rapprochement ci-dessus.")
    if cont_resultats:
        df_disch, manq_disch, manq_manif, merged, dup_warning = cont_resultats
        if dup_warning:
            st.warning(dup_warning)
        m1, m2, m3 = st.columns(3)
        m1.metric("Conteneurs discharging summary", len(df_disch))
        m2.metric("Conteneurs communs rapprochés", len(merged))
        m3.metric("Écarts non-nuls", int((merged["Ecart_kg"] != 0).sum()) if not merged.empty else 0)

        st.markdown(f"🟡 **{len(manq_disch)}** conteneur(s) du manifeste absent(s) du Discharging Summary")
        if not manq_disch.empty:
            st.dataframe(manq_disch.drop(columns=[c for c in manq_disch.columns if c.startswith("_")], errors="ignore"), use_container_width=True, hide_index=True)

        st.markdown(f"🔵 **{len(manq_manif)}** conteneur(s) du Discharging Summary absent(s) du manifeste")
        if not manq_manif.empty:
            st.dataframe(manq_manif, use_container_width=True, hide_index=True)

        st.markdown("⚖️ **Écarts de poids** (conteneurs présents dans les deux — triés par écart absolu décroissant ; le poids manifeste est une moyenne quand plusieurs conteneurs partagent un même B/L, des écarts sont donc attendus dans ce cas)")
        if not merged.empty:
            cols_ecart = [c for c in ("No_Conteneur", "Shipment#", "Poids_manifeste_kg", "Poids_discharge_kg", "Ecart_kg", "Ecart_pct") if c in merged.columns]
            st.dataframe(merged[cols_ecart], use_container_width=True, hide_index=True)

        report_buf = rbld.build_report_workbook_bytes(
            {
                "Conteneurs absents discharging": manq_disch,
                "Conteneurs absents manifeste": manq_manif,
                "Ecarts de poids": merged,
            },
            title_lines=[f"Navire : {navire}", f"Voyage : {voyage}", "Rapprochement Discharging Container Summary"],
        )
        st.download_button(
            "⬇️ Télécharger le rapport d'écarts (.xlsx)",
            data=report_buf.getvalue(),
            file_name=f"Rapprochement_Discharging_Summary_{navire}_{voyage}.xlsx".replace(" ", "_"),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="rep_disch_dl",
        )
