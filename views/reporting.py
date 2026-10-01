"""
Page Reporting — construction de la liste prévisionnelle définitive à partir
des manifestes déjà structurés, rapprochements avec la 1ère liste provisoire
(service Reporting) et le Discharging Container Summary, et classification
des conteneurs par POL/volume — regroupés en sous-onglets sur cette même page
(même principe que Pré-Masque pour Grimaldi / navire à grue).

Voir claude/ANALYSE_ONGLET_REPORTING_2026-09-03.md et
claude/ANALYSE_TABLEAU_CLASSIFICATION_VEHICULES_2026-09-03.md (projet
Claude) pour l'analyse complète ayant guidé ce design.
"""
import pathlib
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import tracking
import reporting_builder as rbld
import classification_vehicules as clsveh
from ui_classification import render_classification
from ui_helpers import help_expander, current_identity, current_access_role

tracking.clear_demo_data()


@st.cache_data(ttl=120, show_spinner=False)
def _cached_list_voyages() -> pd.DataFrame:
    """Cache 2 min, partagé entre les 2 sous-onglets — list_voyages_disponibles()
    relit un export Excel archivé par voyage pour connaître ses ports, coûteux
    à refaire à chaque rerun Streamlit (chaque clic sur la page). Le bouton
    "🔄 Actualiser" de chaque sous-onglet vide ce cache pour voir immédiatement
    un manifeste tout juste traité."""
    return rbld.list_voyages_disponibles()


st.title("Reporting")
st.caption(
    "Construit la liste prévisionnelle définitive à partir des manifestes déjà "
    "structurés (onglet Pré-Masque), la rapproche des autres sources reçues, "
    "et calcule la classification des véhicules par port de chargement."
)

# =============================================================================
# Sous-onglet 1 — Liste prévisionnelle définitive + rapprochements
# =============================================================================
def _render_liste_definitive():
    with help_expander("ℹ️ Comment utiliser cet onglet"):
        st.markdown(
            "1. **Choisissez un Navire/Voyage** déjà traité dans l'onglet Pré-Masque, "
            "puis générez la liste prévisionnelle définitive "
            "(onglet CONTENEUR, agrégé depuis tous les manifestes déjà structurés "
            "pour ce voyage). C'est le manifeste qui fait foi.\n\n"
            "Colonnes de booking (Agent, STATUTS, REMARQUES, ARRIVAL, CLIENT "
            "distinct du destinataire...) n'existent pas dans le manifeste PDF "
            "brut : elles restent vides dans la liste générée, à compléter par "
            "le service Reporting — c'est voulu, pas un oubli."
        )

    # -------------------------------------------------------------------
    # Sélection du Navire / Voyage
    # -------------------------------------------------------------------
    col_h1, col_h2 = st.columns([5, 1])
    with col_h1:
        st.subheader("1. Liste prévisionnelle définitive")
    with col_h2:
        if st.button("🔄 Actualiser", help="Voir immédiatement un manifeste tout juste traité depuis Pré-Masque (sinon repris automatiquement sous 2 min).", key="rep_refresh"):
            _cached_list_voyages.clear()
            st.rerun()

    voyages = _cached_list_voyages()
    if voyages.empty:
        st.info("Aucun manifeste structuré pour l'instant — traitez d'abord des manifestes depuis la page Pré-Masque.")
        return

    voyages["label"] = voyages["navire"] + " — " + voyages["voyage"]
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

        m1, m2 = st.columns(2)
        m1.metric("CONTENEUR — lignes", len(previs['CONTENEUR']))
        m2.metric("B/L distincts", previs['CONTENEUR']['_BL_norm'].nunique())

        if not used_df.empty:
            with st.expander(f"📄 {len(used_df)} traitement(s) source utilisé(s)"):
                st.dataframe(used_df[["horodatage", "agent", "fichier", "nb_bl"]], use_container_width=True, hide_index=True)

        df_show = previs["CONTENEUR"].drop(
            columns=[c for c in previs["CONTENEUR"].columns if c.startswith("_")], errors="ignore"
        )
        st.dataframe(df_show, use_container_width=True, hide_index=True)

        wb_buf = rbld.build_previsionnelle_workbook_bytes(previs, navire, voyage)
        st.download_button(
            "⬇️ Télécharger la liste prévisionnelle définitive (.xlsx)",
            data=wb_buf.getvalue(),
            file_name=f"Liste_Previsionnelle_{navire}_{voyage}.xlsx".replace(" ", "_"),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

# =============================================================================
# Sous-onglet 2 — Classification conteneurs (tâche 11, 03/09, repositionné 04/09)
# =============================================================================
def _render_classification():
    render_classification("cls_veh")


# -----------------------------------------------------------------------
# "direction" (03/09) : accès à cette page limité à la Classification
# véhicules EN LECTURE SEULE (voir _render_classification) — pas au
# de saisie/traitement au quotidien hors périmètre Direction. Pas de sous-
# onglets dans ce cas : un seul contenu affiché directement.
# -----------------------------------------------------------------------
if current_access_role() == "direction":
    _render_classification()
else:
    tab_rappro, tab_classif = st.tabs(["📋 Liste définitive", "🚗 Classification véhicules"])
    with tab_rappro:
        _render_liste_definitive()
    with tab_classif:
        _render_classification()
