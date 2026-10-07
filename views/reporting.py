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
import manifest_totals
from ui_helpers import help_expander, current_identity, current_access_role
from security_utils import filter_uploads

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
    st.caption(
        "Tableau de classification des véhicules par port de chargement (POL) et "
        "tranche de volume — recalculé depuis le(s) manifeste(s) bruts uploadés, à la "
        "place du fichier manuel à ~150 onglets."
    )

    with help_expander("ℹ️ Comment utiliser cet onglet"):
        st.markdown(
            "1. **Uploadez le(s) manifeste(s) bruts** (PDF ou XLSX), puis cliquez sur "
            "« Générer la classification ». Le format est détecté automatiquement par "
            "fichier, et le navire, le voyage, ainsi que le port de chargement (POL) de "
            "chaque véhicule sont repris directement du manifeste — aucune sélection "
            "préalable n'est nécessaire. Un résumé (POL en lignes, tranches de volume en "
            "colonnes, nombre + poids cumulés en kg + colonne NEW VEH) s'affiche.\n"
            "2. Le fichier Excel téléchargé va plus loin : détail par POL avec "
            "sous-total puis total général — même mise en page que le fichier de "
            "référence."
        )

    # -------------------------------------------------------------------
    # Le navire/voyage affichés dans le tableau et le nom du fichier
    # Excel sont ceux détectés automatiquement dans le(s) manifeste(s)
    # uploadé(s) ci-dessous — aucune sélection préalable n'est requise.
    # Bug UX corrigé (28/09) : l'upload était auparavant bloqué tant
    # qu'aucun Navire/Voyage n'avait déjà été traité côté Pré-Masque
    # (uploader caché dans le "else" du if voyages_cls.empty), ce qui
    # rendait l'onglet inutilisable au premier lancement et obligeait à
    # traiter un manifeste ailleurs avant de pouvoir s'en servir ici.
    # -------------------------------------------------------------------
    st.subheader("1. Manifeste(s) bruts")
    st.caption(
        "Formats reconnus automatiquement : Chinese RoRo (XLSX), MOL ALIS, Grimaldi et "
        "Hyundai Glovis (PDF, y compris scanné). Les manifestes scannés (Hyundai Glovis) "
        "prennent plus de temps à traiter — une barre de progression s'affiche."
    )

    # Compteur pour forcer le reset du file_uploader (changer la key le vide)
    if "cls_veh_uploader_seq" not in st.session_state:
        st.session_state["cls_veh_uploader_seq"] = 0
    uploader_key = f"cls_veh_upload_{st.session_state['cls_veh_uploader_seq']}"

    cls_files = st.file_uploader(
        "Manifeste(s) bruts pour la classification (PDF ou XLSX)",
        type=["pdf", "xlsx", "xls"],
        accept_multiple_files=True,
        key=uploader_key,
        help="Un ou plusieurs manifestes du même Navire/Voyage (un par port de chargement si besoin). "
             "Format détecté automatiquement (Chinese RoRo / MOL ALIS / Grimaldi / Hyundai Glovis scanné).",
    )
    cls_files = filter_uploads(cls_files)

    # Boutons Générer / Réinitialiser côte à côte
    col_gen, col_reset = st.columns([3, 1])
    do_generate = cls_files and col_gen.button(
        "🔄 Générer la classification", type="primary", key="cls_veh_generate"
    )
    has_results = st.session_state.get("cls_veh_entries") is not None
    if (cls_files or has_results) and col_reset.button(
        "🗑️ Réinitialiser", key="cls_veh_reset"
    ):
        for k in ("cls_veh_entries", "cls_veh_ship", "cls_veh_voy",
                   "cls_veh_unreadable", "cls_veh_novehicle", "cls_veh_declared", "cls_veh_stacked"):
            st.session_state.pop(k, None)
        st.session_state["cls_veh_uploader_seq"] += 1
        st.rerun()

    if do_generate:
        all_entries = []
        ship_name_detected, voyage_detected = "", ""
        unreadable = []
        no_vehicle = []
        declared = {}
        stacked_parts = []
        progress_bar = st.progress(0.0)
        status = st.empty()
        n_files = len(cls_files)
        for fi, f in enumerate(cls_files):
            status.caption(f"Traitement de « {f.name} » ({fi + 1}/{n_files})…")

            def _cb(page_cur, page_total, _fi=fi, _fname=f.name):
                frac = (_fi + page_cur / max(page_total, 1)) / n_files
                progress_bar.progress(min(frac, 1.0))
                status.caption(f"Traitement de « {_fname} » — page {page_cur}/{page_total}…")

            entries, meta, fmt = clsveh.parse_manifest_bytes(f.name, f.getvalue(), progress_cb=_cb)
            progress_bar.progress((fi + 1) / n_files)
            if f.name.lower().endswith(".pdf") and fmt != "unknown":
                _d = manifest_totals.declared_vehicle_total(f.getvalue()).get("vehicules")
                if _d is not None:
                    declared[f.name] = _d
            if fmt == "unknown":
                unreadable.append(f.name)
                continue
            if fmt == "grimaldi":
                try:
                    import io as _io
                    from manifest_parser import parse_manifest as _pm, records_to_dataframe as _r2d
                    _df = _r2d(_pm(_io.BytesIO(f.getvalue()), f.name))
                    stacked_parts.append(manifest_totals.stacked_detail_df(_df))
                except Exception:
                    pass   # détail facultatif : ne bloque jamais la classification
            if not entries:
                # Format reconnu mais aucun véhicule (ex. manifeste 100 % conteneurs) :
                # ce n'est pas une erreur de lecture.
                no_vehicle.append(f.name)
                continue
            all_entries.extend(entries)
            if not ship_name_detected and meta.get("ship_name"):
                ship_name_detected = meta["ship_name"]
            if not voyage_detected and meta.get("voyage"):
                voyage_detected = meta["voyage"]
        status.empty()
        progress_bar.empty()
        st.session_state["cls_veh_entries"] = all_entries
        st.session_state["cls_veh_ship"] = ship_name_detected or "NAVIRE"
        st.session_state["cls_veh_voy"] = voyage_detected or "VOYAGE"
        st.session_state["cls_veh_unreadable"] = unreadable
        st.session_state["cls_veh_novehicle"] = no_vehicle
        st.session_state["cls_veh_declared"] = declared
        st.session_state["cls_veh_stacked"] = (
            pd.concat(stacked_parts, ignore_index=True) if stacked_parts else None)

    cls_entries = st.session_state.get("cls_veh_entries")
    if cls_entries is not None:
        if st.session_state.get("cls_veh_unreadable"):
            st.warning(
                "Format non reconnu, fichier(s) ignoré(s) : "
                + ", ".join(st.session_state["cls_veh_unreadable"])
            )
        if st.session_state.get("cls_veh_novehicle"):
            st.info(
                "Aucun véhicule dans (conteneurs / colis uniquement) : "
                + ", ".join(st.session_state["cls_veh_novehicle"])
            )

        diag = clsveh.classification_diag(cls_entries)
        if diag["total_vehicules"] == 0:
            st.warning("Aucun véhicule extrait des manifestes uploadés.")
        else:
            st.divider()
            st.subheader("2. Tableau de classification (POL x tranche de volume)")
            ship_lbl = st.session_state.get("cls_veh_ship", "NAVIRE")
            voy_lbl = st.session_state.get("cls_veh_voy", "VOYAGE")
            st.caption(f"Navire/Voyage détecté(s) automatiquement : **{ship_lbl} / {voy_lbl}**")

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Véhicules (total)", diag["total_vehicules"])
            m2.metric("Dont neufs (NEW VEH)", diag["neufs"])
            m3.metric("B/L / entrées retenues", diag["nb_bl"])
            m4.metric("Sans tranche exploitable", diag["sans_tranche"],
                      help="Ni volume ni poids exploitable dans le manifeste — exclus du "
                           "tableau ci-dessous mais toujours comptés ici, jamais supprimés "
                           "silencieusement.")

            _decl = st.session_state.get("cls_veh_declared") or {}
            if _decl:
                _d_tot = sum(_decl.values())
                if _d_tot == diag["total_vehicules"]:
                    st.success(
                        f"✅ Total cohérent avec le manifeste : {_d_tot} véhicules annoncés "
                        f"= {diag['total_vehicules']} extraits.")
                else:
                    st.warning(
                        f"⚠️ Le manifeste annonce **{_d_tot}** véhicules (récapitulatif « Summary "
                        f"Totals ») ; **{diag['total_vehicules']}** extraits "
                        f"(écart {diag['total_vehicules'] - _d_tot:+d}). Vérifier les B/L des "
                        f"lignes « sans tranche » et les services B/L [T].")
            if diag["sans_tranche"]:
                st.caption(
                    f"ℹ️ {diag['sans_tranche']} véhicule(s) sans poids/volume propre sont comptés "
                    "dans le total mais absents du tableau (à classer manuellement). Les véhicules "
                    "empilés (« bébé au dos ») et remorques attelées ne figurent jamais dans le "
                    "tableau : ils n'ont pas de volume propre.")

            with st.expander("ℹ️ Comment vérifier les totaux (à lire)"):
                for _l in manifest_totals.agent_message(
                        None, sum(_decl.values()) if _decl else None, diag["sans_tranche"]):
                    st.markdown(_l)
                st.caption("Ce message figure aussi dans l'onglet « A LIRE - Totaux » du fichier Excel généré.")

            pivot_df = clsveh.entries_to_pivot_df(cls_entries)
            if pivot_df.empty:
                st.caption("Aucune ligne classifiable.")
            else:
                display_df = pivot_df.set_index("POL")

                def _hl_total(row):
                    is_total = row.name == "TOTAL"
                    return ["background-color: #1F4E78; color: white; font-weight: bold;" if is_total else ""] * len(row)

                fmt_map = {}
                for c in display_df.columns:
                    if "VOLUME" in c:
                        fmt_map[c] = "{:,.2f}"
                    else:
                        fmt_map[c] = "{:,.0f}"

                styled = display_df.style.format(fmt_map, na_rep="—").apply(_hl_total, axis=1)
                st.markdown("**Résumé par port de chargement (POL)**")
                st.dataframe(styled, use_container_width=True)

            _dd = st.session_state.get("cls_veh_declared") or {}
            xbytes = clsveh.build_classification_excel_bytes(
                cls_entries, ship_lbl, voy_lbl, declared_total=(sum(_dd.values()) if _dd else None),
                stacked_df=st.session_state.get("cls_veh_stacked"))
            st.download_button(
                "⬇️ Télécharger la classification (Excel — mise en page fidèle au fichier de référence)",
                data=xbytes,
                file_name=f"Classification_VEHICULE_{ship_lbl}_{voy_lbl}.xlsx".replace(" ", "_"),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="cls_veh_dl",
            )
    else:
        st.info("Uploadez un ou plusieurs manifestes bruts puis cliquez sur « Générer la classification ».")


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
