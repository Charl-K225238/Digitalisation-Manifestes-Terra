"""
Page Reporting — construction de la liste prévisionnelle définitive à partir
des manifestes déjà structurés, rapprochements avec la 1ère liste provisoire
(service Reporting) et le Discharging Container Summary, et classification
des véhicules par POL/volume — regroupés en sous-onglets sur cette même page
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
from classification_builder import classify_vehicules, pivot_pol_tranche, build_classification_workbook_bytes
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
def _render_rapprochement():
    with help_expander("ℹ️ Comment utiliser cet onglet"):
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

    # -------------------------------------------------------------------
    # Étape 2 — Rapprochement avec la 1ère liste provisoire
    # -------------------------------------------------------------------
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

    # -------------------------------------------------------------------
    # Étape 3 — Rapprochement avec le Discharging Container Summary
    # -------------------------------------------------------------------
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

# =============================================================================
# Sous-onglet 2 — Classification véhicules (tâche 11, 03/09)
# =============================================================================
def _render_classification():
    st.caption(
        "Tableau de classification des véhicules par port de chargement (POL) et "
        "tranche de volume — recalculé automatiquement depuis les manifestes déjà "
        "structurés, à la place du fichier manuel à ~150 onglets."
    )

    with help_expander("ℹ️ Comment utiliser cet onglet"):
        st.markdown(
            "1. **Choisissez un Navire/Voyage** déjà traité dans l'onglet Pré-Masque.\n"
            "2. Le tableau croisé (POL en lignes, tranches de volume en colonnes) "
            "s'affiche automatiquement — 100% recalculé, rien à ressaisir.\n"
            "3. **Complétez la fiche de suivi** de l'escale (date ETA/ATA — seul "
            "champ obligatoire ; statut et remarques restent facultatifs, en "
            "édition libre).\n\n"
            "**Limite MVP** : seuls les manifestes **Import** sont classifiés pour "
            "l'instant (Export/Transbo pas encore couverts, faute d'exemples réels "
            "pour valider le calcul) — la fiche de suivi, elle, fonctionne pour les "
            "3 sens dès maintenant."
        )

    # -------------------------------------------------------------------
    # Parcourir par période — s'appuie sur les fiches de suivi déjà
    # saisies (tâche 11b) pour retrouver rapidement une escale sans
    # connaître son nom exact de voyage. Une escale jamais renseignée
    # n'apparaît pas ici (aucune date fiable à défaut de saisie manuelle)
    # — pas un bug, juste "pas encore suivi". Défensif : une erreur ici ne
    # doit jamais bloquer le reste de l'onglet (voir try/except ci-dessous
    # — diagnostique aussi une éventuelle table pas encore migrée côté
    # Supabase, au lieu d'un crash generique).
    # -------------------------------------------------------------------
    with st.expander("🗓️ Parcourir par période (escales déjà renseignées)"):
        try:
            escales = tracking.list_suivi_escales()
        except Exception as e:
            escales = pd.DataFrame()
            st.error(
                f"Impossible de lire les fiches de suivi ({type(e).__name__} : {e}). "
                "Vérifiez que la migration SQL manifestes_suivi_escale a bien été exécutée dans Supabase."
            )
        if escales.empty:
            st.caption("Aucune fiche de suivi saisie pour l'instant — renseignez une date d'escale ci-dessous pour qu'elle apparaisse ici.")
        else:
            c1, c2 = st.columns(2)
            d_min = c1.date_input("Du", value=None, key="cls_periode_debut")
            d_max = c2.date_input("Au", value=None, key="cls_periode_fin")
            esc_f = escales.copy()
            esc_f["date_escale"] = pd.to_datetime(esc_f["date_escale"]).dt.date
            if d_min:
                esc_f = esc_f[esc_f["date_escale"] >= d_min]
            if d_max:
                esc_f = esc_f[esc_f["date_escale"] <= d_max]
            st.dataframe(
                esc_f[["navire", "voyage", "sens", "date_escale", "statut", "remarques"]]
                    .rename(columns={"navire": "Navire", "voyage": "Voyage", "sens": "Sens",
                                      "date_escale": "Date escale", "statut": "Statut", "remarques": "Remarques"}),
                use_container_width=True, hide_index=True,
            )

    st.divider()

    # -------------------------------------------------------------------
    # Sélection Navire / Voyage / Sens
    # -------------------------------------------------------------------
    col_h1, col_h2 = st.columns([5, 1])
    with col_h1:
        st.subheader("1. Sélection de l'escale")
    with col_h2:
        if st.button("🔄 Actualiser", help="Voir immédiatement un manifeste tout juste traité depuis Pré-Masque.", key="cls_refresh"):
            _cached_list_voyages.clear()
            st.rerun()

    voyages_cls = _cached_list_voyages()
    if voyages_cls.empty:
        st.info("Aucun manifeste structuré pour l'instant — traitez d'abord des manifestes depuis la page Pré-Masque.")
    else:
        navires = sorted(voyages_cls["navire"].unique())
        navire_c = st.selectbox("Navire", navires, key="cls_navire")
        voyages_du_navire = voyages_cls[voyages_cls["navire"] == navire_c]
        voyage_c = st.selectbox("Voyage", sorted(voyages_du_navire["voyage"].unique()), key="cls_voyage")
        sens_c = st.selectbox("Sens", tracking.SENS_ESCALE, index=0, key="cls_sens",
                               help="Seul « Import » est classifié pour l'instant (voir limite MVP ci-dessus).")

        try:
            _existant = tracking.get_suivi_escale(navire_c, voyage_c, sens_c)
        except Exception as e:
            _existant = None
            st.error(f"Impossible de lire la fiche de suivi ({type(e).__name__} : {e}).")

        # Direction : accès LECTURE SEULE à cette page (voir décision
        # d'accès du 03/09) — tableau croisé et export restent visibles
        # (consultation), mais pas la saisie/modification de la fiche de
        # suivi (section 3 ci-dessous).
        _lecture_seule = current_access_role() == "direction"

        st.divider()

        # -----------------------------------------------------------
        # Tableau de classification (Import uniquement, MVP)
        # -----------------------------------------------------------
        st.subheader("2. Tableau de classification (POL × tranche de volume)")
        if sens_c != "Import":
            st.info(
                f"Classification « {sens_c} » pas encore disponible dans ce MVP (voir limite ci-dessus) — "
                "seule la fiche de suivi ci-dessous est utilisable pour ce sens."
            )
        else:
            with st.spinner("Calcul depuis les manifestes déjà structurés…"):
                df_classifie, diag = classify_vehicules(navire_c, voyage_c)

            if diag["total_vehicules"] == 0:
                st.warning("Aucun véhicule trouvé pour ce Navire/Voyage — vérifiez qu'un manifeste Véhicule a bien été traité dans Pré-Masque.")
            else:
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Véhicules (total manifeste)", diag["total_vehicules"])
                m2.metric("Hors périmètre (Export/Transbo)", diag["hors_import"])
                m3.metric("Classifiables (Import)", diag["total_vehicules"] - diag["hors_import"])
                m4.metric("Sans volume (à ré-traiter)", diag["sans_volume"])

                if diag["sans_volume"]:
                    st.warning(
                        f"{diag['sans_volume']} véhicule(s) Import sans volume exploitable — exclu(s) du "
                        "tableau plutôt que classé(s) au hasard. Un ré-traitement du manifeste concerné "
                        "dans Pré-Masque (le doublon met à jour automatiquement) suffit à les rendre "
                        "classifiables si le manifeste source a été traité avant le correctif du 03/09."
                    )

                pols_dispo = sorted(p for p in df_classifie["POL"].unique() if p)
                pol_filtre = st.multiselect("Filtrer par port de chargement (POL)", pols_dispo, key="cls_pol_filtre",
                                             help="Aucune sélection = tous les ports. L'export reste complet quel que soit ce filtre.")
                df_f = df_classifie[df_classifie["POL"].isin(pol_filtre)] if pol_filtre else df_classifie

                pivot = pivot_pol_tranche(df_f)
                if pivot.empty:
                    st.caption("Aucune ligne classifiable pour cette sélection.")
                else:
                    st.dataframe(pivot, use_container_width=True, hide_index=True)

                    report_buf = build_classification_workbook_bytes(df_classifie, navire_c, voyage_c, _existant)
                    st.download_button(
                        "⬇️ Télécharger (Excel — mise en page fidèle au fichier de référence)",
                        data=report_buf.getvalue(),
                        file_name=f"Classification_{navire_c}_{voyage_c}.xlsx".replace(" ", "_"),
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="cls_dl",
                        help="Export toujours complet (tous les POL), quel que soit le filtre ci-dessus.",
                    )

        st.divider()

        # -----------------------------------------------------------
        # Fiche de suivi de l'escale (tâche 11b) — date obligatoire,
        # reste optionnel pour statut/remarques
        # -----------------------------------------------------------
        st.subheader("3. Fiche de suivi de l'escale")

        if _lecture_seule:
            st.caption("Accès en lecture seule (rôle Direction) — consultation uniquement, pas de saisie.")
            if _existant:
                c1, c2 = st.columns([1, 3])
                c1.metric("Date d'escale (ETA/ATA)", f"{_existant['date_escale']:%d/%m/%Y}")
                c2.markdown(f"**Statut** : {_existant['statut'] or '—'}")
                st.markdown(f"**Remarques** : {_existant['remarques'] or '—'}")
                st.caption(f"Dernière saisie par **{_existant['agent']}** le {_existant['horodatage']:%d/%m/%Y à %H:%M}.")
            else:
                st.caption("Aucune fiche de suivi renseignée pour cette escale.")
        else:
            st.caption("Seule la date d'escale réelle (ETA/ATA) est obligatoire — statut et remarques restent facultatifs.")

            c1, c2 = st.columns([1, 3])
            with c1:
                _date_defaut = _existant["date_escale"] if _existant else None
                date_escale = st.date_input("Date d'escale réelle (ETA/ATA) *", value=_date_defaut, key="cls_date_escale")
            with c2:
                statut = st.text_input("Statut (optionnel)", value=(_existant["statut"] if _existant else ""), key="cls_statut")
            remarques = st.text_area("Remarques (optionnel)", value=(_existant["remarques"] if _existant else ""), key="cls_remarques")

            if _existant:
                st.caption(f"Dernière saisie par **{_existant['agent']}** le {_existant['horodatage']:%d/%m/%Y à %H:%M}.")

            if st.button("💾 Enregistrer la fiche de suivi", type="primary", key="cls_save_suivi"):
                _identity = current_identity()
                if not _identity or not _identity.get("name"):
                    st.error("Identifiez-vous d'abord sur la page Profil.")
                elif not date_escale:
                    st.error("La date d'escale réelle (ETA/ATA) est obligatoire.")
                else:
                    try:
                        tracking.save_suivi_escale(navire_c, voyage_c, sens_c, date_escale, _identity["name"],
                                                    statut=statut, remarques=remarques)
                    except Exception as e:
                        st.error(f"Échec de l'enregistrement ({type(e).__name__} : {e}).")
                    else:
                        st.success("Fiche de suivi enregistrée.")
                        st.rerun()


# -----------------------------------------------------------------------
# "direction" (03/09) : accès à cette page limité à la Classification
# véhicules EN LECTURE SEULE (voir _render_classification) — pas au
# rapprochement liste provisoire/Discharging Summary, qui reste une page
# de saisie/traitement au quotidien hors périmètre Direction. Pas de sous-
# onglets dans ce cas : un seul contenu affiché directement.
# -----------------------------------------------------------------------
if current_access_role() == "direction":
    _render_classification()
else:
    tab_rappro, tab_classif = st.tabs(["🧮 Rapprochement liste provisoire", "🚗 Classification véhicules"])
    with tab_rappro:
        _render_rapprochement()
    with tab_classif:
        _render_classification()
