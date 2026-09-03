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
from ui_helpers import help_expander

tracking.clear_demo_data()

st.title("Reporting")
st.caption(
    "Construit la liste prévisionnelle définitive à partir des manifestes déjà "
    "structurés (Structuration), et la rapproche de la 1ère liste provisoire "
    "reçue et du Discharging Container Summary — pour accélérer sa création "
    "et faciliter la vérification avec les autres sources."
)

with help_expander("ℹ️ Comment utiliser cette page"):
    st.markdown(
        "1. **Choisissez un Navire/Voyage** déjà traité dans Structuration, "
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
st.subheader("1. Liste prévisionnelle définitive")

voyages = rbld.list_voyages_disponibles()
if voyages.empty:
    st.info("Aucun manifeste structuré pour l'instant — traitez d'abord des manifestes depuis la page Pré-Masque.")
    st.stop()

voyages["label"] = voyages["navire"] + " — " + voyages["voyage"] + " (" + voyages["nb_traitements"].astype(str) + " traitement(s))"
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
    with st.spinner("Agrégation des manifestes déjà structurés…"):
        dfs, used_df, ports = rbld.fetch_voyage_detail(navire, voyage)
        previs = rbld.build_liste_previsionnelle(dfs)
    st.session_state["rep_previs"] = previs
    st.session_state["rep_ports"] = ports
    st.session_state["rep_used"] = used_df
    st.session_state["rep_navire"] = navire
    st.session_state["rep_voyage"] = voyage

previs = st.session_state.get("rep_previs")
if previs is not None and st.session_state.get("rep_navire") == navire and st.session_state.get("rep_voyage") == voyage:
    ports = st.session_state.get("rep_ports", [])
    used_df = st.session_state.get("rep_used", pd.DataFrame())

    if not ports:
        st.warning("Aucune donnée détail trouvée pour ce Navire/Voyage — vérifiez que les manifestes ont bien été traités avec export archivé.")
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
            prov = rbld.parse_liste_provisoire(prov_file.getvalue(), prov_file.name)
        except Exception as e:
            st.error(f"Impossible de lire ce fichier : {e}")
            prov = None
        if prov is not None:
            resultats = {}
            for sheet in ("RORO", "CONTENEUR", "BB"):
                manquants, en_trop, n_communs = rbld.reconcile_bl(previs[sheet], prov.get(sheet, pd.DataFrame()))
                resultats[sheet] = (manquants, en_trop, n_communs)
            st.session_state["rep_bl_resultats"] = resultats

    resultats = st.session_state.get("rep_bl_resultats")
    if resultats:
        for sheet in ("RORO", "CONTENEUR", "BB"):
            manquants, en_trop, n_communs = resultats[sheet]
            st.markdown(f"**{sheet}** — {n_communs} B/L en commun")
            c1, c2 = st.columns(2)
            with c1:
                st.caption(f"🟡 À ajouter — {manquants['_BL_norm'].nunique() if not manquants.empty else 0} B/L des manifestes absents de la liste provisoire")
                if not manquants.empty:
                    st.dataframe(manquants.drop(columns=[c for c in manquants.columns if c.startswith("_")], errors="ignore"), use_container_width=True, hide_index=True)
            with c2:
                st.caption(f"🔵 À vérifier — {en_trop['_BL_norm'].nunique() if not en_trop.empty else 0} B/L de la liste provisoire absents des manifestes déjà traités")
                if not en_trop.empty:
                    st.dataframe(en_trop.drop(columns=[c for c in en_trop.columns if c.startswith("_")], errors="ignore"), use_container_width=True, hide_index=True)

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
            manq_disch, manq_manif, merged = rbld.reconcile_containers(previs["CONTENEUR"], df_disch)
            st.session_state["rep_cont_resultats"] = (df_disch, manq_disch, manq_manif, merged)

    cont_resultats = st.session_state.get("rep_cont_resultats")
    if cont_resultats:
        df_disch, manq_disch, manq_manif, merged = cont_resultats
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
