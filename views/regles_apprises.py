"""
Règles apprises — règles enregistrées depuis les comparaisons au pré-masque agent.
Tous les agents voient, désactivent et réactivent les règles ; rien n'est supprimé.
Les écarts de structure (niveau 4) sont la liste des corrections de parser à faire.
"""
import pathlib
import sys

import streamlit as st

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import regles_store                                     # noqa: E402
from security_utils import safe_error                   # noqa: E402
from ui_helpers import current_identity, require_perm   # noqa: E402

require_perm("saisie.premasque")
st.title("Règles apprises")
st.caption("Corrections validées par les agents lors des comparaisons au pré-masque agent. "
           "Elles s'appliquent à tous les prochains pré-masques ; chaque ligne modifiée est "
           "signalée dans l'onglet « À VÉRIFIER » du fichier de vérification.")

try:
    df = regles_store.lister_regles()
    ecarts = regles_store.lister_ecarts_structure()
except Exception as e:
    safe_error("regles_apprises: lecture", e,
               "Tables des règles apprises introuvables : exécuter la fin de supabase_schema.sql "
               "dans l'éditeur SQL Supabase.")
    st.stop()

auteur = (current_identity() or {}).get("nom") or "agent inconnu"
t1, t2 = st.tabs([f"Règles ({int(df['active'].sum()) if len(df) else 0} actives)",
                  f"Corrections de parser à faire ({int((ecarts['statut'] == 'ouvert').sum()) if len(ecarts) else 0})"])

with t1:
    if df.empty:
        st.info("Aucune règle pour l'instant : elles se créent depuis Pré-Masque › Comparer au pré-masque de l'agent.")
    else:
        c1, c2 = st.columns(2)
        etat = c1.segmented_control("État", ["Actives", "Désactivées", "Toutes"], default="Actives", key="ra_etat")
        cols = c2.multiselect("Colonnes", sorted(df["colonne"].unique()), key="ra_cols")
        vue = df
        if etat == "Actives":
            vue = vue[vue["active"]]
        elif etat == "Désactivées":
            vue = vue[~vue["active"]]
        if cols:
            vue = vue[vue["colonne"].isin(cols)]
        st.dataframe(vue.drop(columns=["journal"]), hide_index=True)
        sel = st.selectbox("Règle à modifier", vue["id"].tolist(), index=None, key="ra_sel",
                           format_func=lambda i: f"n° {i} — " + " · ".join(
                               str(x) for x in df.loc[df["id"] == i, ["colonne", "valeur_app", "chassis", "valeur"]]
                               .iloc[0].tolist() if x))
        if sel is not None:
            ligne = df[df["id"] == sel].iloc[0]
            st.text(ligne["journal"])
            libelle = "Désactiver" if ligne["active"] else "Réactiver"
            if st.button(f":material/toggle_on: {libelle} la règle n° {sel}", key="ra_toggle"):
                try:
                    regles_store.changer_etat(sel, not bool(ligne["active"]), auteur)
                    st.success(f"Règle n° {sel} {'désactivée' if ligne['active'] else 'réactivée'}.")
                    st.rerun()
                except Exception as e:
                    safe_error("regles_apprises: état", e, "Modification impossible pour l'instant.")

with t2:
    st.caption("Ouvert automatiquement quand une même colonne cumule au moins "
               f"{regles_store.SEUIL_STRUCTURE} surcharges ponctuelles : le parser lit mal cette "
               "colonne et doit être corrigé par une PR.")
    if ecarts.empty:
        st.info("Aucune correction de parser en attente.")
    else:
        st.dataframe(ecarts, hide_index=True)
        e_sel = st.selectbox("Écart", ecarts["id"].tolist(), index=None, key="es_sel")
        if e_sel is not None:
            statut = st.segmented_control("Statut", ["ouvert", "en PR", "fermé"], key="es_statut",
                                          default=ecarts.loc[ecarts["id"] == e_sel, "statut"].iloc[0])
            if st.button("Enregistrer le statut", key="es_save"):
                try:
                    regles_store.changer_statut_ecart(e_sel, statut)
                    st.rerun()
                except Exception as e:
                    safe_error("regles_apprises: statut", e, "Modification impossible pour l'instant.")
