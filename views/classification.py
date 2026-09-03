"""
Page Classification véhicules — tableau croisé POL × tranche de volume,
calculé à la volée depuis les manifestes déjà structurés (voir
classification_builder.py), plus une fiche de suivi manuelle par escale
(date d'escale réelle ETA/ATA, statut, remarques — voir tracking.py,
table manifestes_suivi_escale, tâche 11b).

Remplace le fichier manuel à ~150 onglets — voir
claude/ANALYSE_TABLEAU_CLASSIFICATION_VEHICULES_2026-09-03.md (projet
Claude) pour l'analyse complète ayant guidé ce design.

MVP (décision validée 03/09) : classification calculée pour le Sens
"Import" uniquement (Export/Transbo jamais testés en pratique, aucun
échantillon réel disponible pour calibrer) — les manifestes Export/Transbo
remontent dans le diagnostic plutôt que d'être classés au hasard. La fiche
de suivi (date/statut/remarques), elle, est disponible pour les 3 sens dès
maintenant : c'est une saisie manuelle, indépendante du calcul.
"""
import pathlib
import sys
from datetime import date

import pandas as pd
import streamlit as st

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import tracking
import reporting_builder as rbld
from classification_builder import classify_vehicules, pivot_pol_tranche, build_classification_workbook_bytes
from ui_helpers import help_expander, current_identity

tracking.clear_demo_data()


@st.cache_data(ttl=120, show_spinner=False)
def _cached_list_voyages() -> pd.DataFrame:
    """Même cache que la page Reporting (2 min) — voir son commentaire :
    list_voyages_disponibles() relit un export archivé par voyage."""
    return rbld.list_voyages_disponibles()


st.title("Classification véhicules")
st.caption(
    "Tableau de classification des véhicules par port de chargement (POL) et "
    "tranche de volume — recalculé automatiquement depuis les manifestes déjà "
    "structurés (onglet Pré-Masque), à la place du fichier manuel à ~150 "
    "onglets. Complétez la date d'escale réelle pour situer chaque escale "
    "dans le temps (aucune date fiable dans le manifeste lui-même)."
)

with help_expander("ℹ️ Comment utiliser cette page"):
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

# ---------------------------------------------------------------------------
# Parcourir par période — s'appuie sur les fiches de suivi déjà saisies
# (tâche 11b) pour retrouver rapidement une escale sans connaître son nom
# exact de voyage. Une escale jamais renseignée n'apparaît pas ici (aucune
# date fiable à défaut de saisie manuelle) — pas un bug, juste "pas encore
# suivi".
# ---------------------------------------------------------------------------
with st.expander("🗓️ Parcourir par période (escales déjà renseignées)"):
    escales = tracking.list_suivi_escales()
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

# ---------------------------------------------------------------------------
# Sélection Navire / Voyage / Sens
# ---------------------------------------------------------------------------
col_h1, col_h2 = st.columns([5, 1])
with col_h1:
    st.subheader("1. Sélection de l'escale")
with col_h2:
    if st.button("🔄 Actualiser", help="Voir immédiatement un manifeste tout juste traité depuis Pré-Masque."):
        _cached_list_voyages.clear()
        st.rerun()

voyages = _cached_list_voyages()
if voyages.empty:
    st.info("Aucun manifeste structuré pour l'instant — traitez d'abord des manifestes depuis la page Pré-Masque.")
    st.stop()

navires = sorted(voyages["navire"].unique())
navire = st.selectbox("Navire", navires, key="cls_navire")
voyages_du_navire = voyages[voyages["navire"] == navire]
voyage = st.selectbox("Voyage", sorted(voyages_du_navire["voyage"].unique()), key="cls_voyage")
sens = st.selectbox("Sens", tracking.SENS_ESCALE, index=0, key="cls_sens",
                     help="Seul « Import » est classifié pour l'instant (voir limite MVP ci-dessus).")

_existant = tracking.get_suivi_escale(navire, voyage, sens)

st.divider()

# ---------------------------------------------------------------------------
# Tableau de classification (Import uniquement, MVP)
# ---------------------------------------------------------------------------
st.subheader("2. Tableau de classification (POL × tranche de volume)")
if sens != "Import":
    st.info(
        f"Classification « {sens} » pas encore disponible dans ce MVP (voir limite ci-dessus) — "
        "seule la fiche de suivi ci-dessous est utilisable pour ce sens."
    )
else:
    with st.spinner("Calcul depuis les manifestes déjà structurés…"):
        df_classifie, diag = classify_vehicules(navire, voyage)

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

            report_buf = build_classification_workbook_bytes(df_classifie, navire, voyage, _existant)
            st.download_button(
                "⬇️ Télécharger (Excel — mise en page fidèle au fichier de référence)",
                data=report_buf.getvalue(),
                file_name=f"Classification_{navire}_{voyage}.xlsx".replace(" ", "_"),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="cls_dl",
                help="Export toujours complet (tous les POL), quel que soit le filtre ci-dessus.",
            )

st.divider()

# ---------------------------------------------------------------------------
# Fiche de suivi de l'escale (tâche 11b) — date obligatoire, reste optionnel
# ---------------------------------------------------------------------------
st.subheader("3. Fiche de suivi de l'escale")
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
        tracking.save_suivi_escale(navire, voyage, sens, date_escale, _identity["name"],
                                    statut=statut, remarques=remarques)
        st.success("Fiche de suivi enregistrée.")
        st.rerun()
