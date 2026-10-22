"""
Page Administration — groupes de droits et utilisateurs (mode comptes).

Groupes : un nom + les fonctionnalités cochées, classées par catégorie
(catalogue : permissions.py). Utilisateurs : nom, prénom, e-mail, service,
groupe ; mot de passe provisoire généré et affiché UNE fois, à changer par
la personne à sa première connexion. Toutes les actions sont journalisées.
"""
import pathlib
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import comptes as C
import permissions as P
from ui_helpers import accounts_mode, current_account, require_perm

if not accounts_mode():
    st.info("L'administration des comptes est disponible quand la connexion par compte est activée "
            "(secret CONNEXION_PAR_COMPTE = true).")
    st.stop()
require_perm(P.ADMIN_PERM)
moi = current_account()
auteur = moi["email"]

st.title("Utilisateurs et droits")
st.caption("Créez des groupes en cochant les fonctionnalités autorisées, puis affectez chaque utilisateur à un groupe. "
           "Les changements s'appliquent aux personnes connectées en moins d'une minute.")

# Message affiché une seule fois après une action (ex. mot de passe provisoire)
_flash = st.session_state.pop("_admin_flash", None)
if _flash:
    kind, texte, pwd = _flash
    getattr(st, kind)(texte)
    if pwd:
        st.code(pwd, language=None)
        st.caption("Ce mot de passe provisoire ne sera plus affiché. Remettez-le à la personne de vive voix ou en "
                   "main propre (jamais par e-mail). Elle devra le changer à sa première connexion.")


def _flash_rerun(kind: str, texte: str, pwd: str = "") -> None:
    st.session_state["_admin_flash"] = (kind, texte, pwd)
    st.rerun()


try:
    groupes = C.list_groupes()
    users = C.list_utilisateurs()
except Exception:
    st.error("Lecture des comptes impossible pour le moment. Réessayez dans un instant.")
    st.stop()
g_by_id = {g["id"]: g for g in groupes}

tab_g, tab_u, tab_j = st.tabs([":material/group: Groupes", ":material/person_add: Utilisateurs",
                               ":material/history: Journal"])

# ---------------------------------------------------------------------------
# Groupes
# ---------------------------------------------------------------------------
with tab_g:
    st.dataframe(
        pd.DataFrame([{"Groupe": g["nom"], "Description": g["description"],
                       "Utilisateurs actifs": g["nb_actifs"], "Fonctionnalités": len(g["permissions"])}
                      for g in groupes]),
        hide_index=True, use_container_width=True,
    )
    choix = st.selectbox("Groupe à créer ou modifier", [None] + [g["id"] for g in groupes],
                         format_func=lambda i: "＋ Nouveau groupe" if i is None else g_by_id[i]["nom"],
                         key="adm_groupe_sel")
    g = g_by_id.get(choix)
    k = f"g{choix or 'new'}"
    actuelles = set(g["permissions"]) if g else set()

    with st.form(f"form_groupe_{k}"):
        c1, c2 = st.columns([1, 2])
        nom = c1.text_input("Nom du groupe", value=g["nom"] if g else "", key=f"{k}_nom")
        desc = c2.text_input("Description (facultatif)", value=g["description"] if g else "", key=f"{k}_desc")
        st.markdown("**Fonctionnalités autorisées**")
        st.caption("Toujours accessibles à tous : Vue d'ensemble, Profil, Avis & retours.")
        coches = []
        cats = P.CATALOGUE
        for i in range(0, len(cats), 3):
            cols = st.columns(3)
            for col, (cat, items) in zip(cols, cats[i:i + 3]):
                with col.container(border=True):
                    st.markdown(f"**{cat}**")
                    for code, label in items:
                        if st.checkbox(label, value=code in actuelles, key=f"{k}_{code}"):
                            coches.append(code)
        valider = st.form_submit_button("Valider le groupe", type="primary")
    if valider:
        try:
            C.save_groupe(choix, nom, desc, coches, auteur)
        except C.CompteError as e:
            st.error(str(e))
        else:
            _flash_rerun("success", f"Groupe « {nom.strip()} » enregistré ({len(coches)} fonctionnalité(s)).")

    if g:
        if g["nb_total"]:
            st.caption(f"Suppression impossible : {g['nb_total']} utilisateur(s) dans ce groupe.")
        elif st.button(f"Supprimer le groupe « {g['nom']} »", key=f"{k}_del"):
            C.delete_groupe(g["id"], auteur)
            st.session_state.pop("adm_groupe_sel", None)
            _flash_rerun("success", f"Groupe « {g['nom']} » supprimé.")

# ---------------------------------------------------------------------------
# Utilisateurs
# ---------------------------------------------------------------------------
with tab_u:
    with st.expander("＋ Nouvel utilisateur", expanded=not users or len(users) < 2):
        with st.form("form_new_user", clear_on_submit=False):
            c1, c2 = st.columns(2)
            n_nom = c1.text_input("Nom")
            n_prenom = c2.text_input("Prénom")
            c3, c4 = st.columns(2)
            n_mail = c3.text_input("E-mail professionnel", placeholder="prenom.nom@terra.ci")
            n_service = c4.text_input("Service (facultatif)", placeholder="Reporting, Opérations…",
                                      help="Sert aux statistiques par service du tableau de bord.")
            n_groupe = st.selectbox("Groupe", [g["id"] for g in groupes], format_func=lambda i: g_by_id[i]["nom"])
            creer = st.form_submit_button("Créer l'utilisateur", type="primary")
        if creer:
            try:
                pwd = C.create_utilisateur(n_nom, n_prenom, n_mail, n_service, n_groupe, auteur)
            except C.CompteError as e:
                st.error(str(e))
            else:
                _flash_rerun("success", f"Compte créé pour {C.display_name(n_nom, n_prenom)} "
                                        f"({C.normalize_email(n_mail)}). Mot de passe provisoire :", pwd)

    if not users:
        st.caption("Aucun utilisateur pour l'instant.")
    else:
        st.dataframe(
            pd.DataFrame([{
                "Nom": u["nom"], "Prénom": u["prenom"], "E-mail": u["email"], "Groupe": u["groupe"],
                "Service": u["service"], "Statut": "Actif" if u["actif"] else "Désactivé",
                "1re connexion faite": "Non" if u["doit_changer_mdp"] else "Oui",
                "Dernière connexion": (pd.Timestamp(u["derniere_connexion"]).tz_convert("Africa/Abidjan")
                                       .strftime("%d/%m/%Y %H:%M") if u["derniere_connexion"] else "—"),
            } for u in users]),
            hide_index=True, use_container_width=True,
        )

        st.markdown("**Modifier un utilisateur**")
        u_by_id = {u["id"]: u for u in users}
        uid = st.selectbox("Utilisateur", list(u_by_id), key="adm_user_sel",
                           format_func=lambda i: f"{u_by_id[i]['nom_affiche']} — {u_by_id[i]['email']}")
        u = u_by_id[uid]
        with st.form(f"form_edit_user_{uid}"):
            c1, c2, c3 = st.columns([2, 2, 1])
            e_groupe = c1.selectbox("Groupe", [g["id"] for g in groupes], format_func=lambda i: g_by_id[i]["nom"],
                                    index=[g["id"] for g in groupes].index(u["groupe_id"]))
            e_service = c2.text_input("Service", value=u["service"])
            e_actif = c3.toggle("Compte actif", value=u["actif"])
            enreg = st.form_submit_button("Enregistrer", type="primary")
        if enreg:
            try:
                C.update_utilisateur(uid, e_groupe, e_service, e_actif, auteur)
            except C.CompteError as e:
                st.error(str(e))
            else:
                _flash_rerun("success", f"{u['nom_affiche']} : modifications enregistrées.")
        if st.button("Réinitialiser le mot de passe", key=f"reset_{uid}",
                     help="Génère un nouveau mot de passe provisoire et débloque le compte après trop d'essais."):
            pwd = C.reset_password(uid, auteur)
            _flash_rerun("warning", f"Nouveau mot de passe provisoire pour {u['nom_affiche']} :", pwd)

# ---------------------------------------------------------------------------
# Journal
# ---------------------------------------------------------------------------
with tab_j:
    st.caption("200 dernières actions d'administration (création, modification, réinitialisation…).")
    try:
        j = C.list_journal()
    except Exception:
        j = pd.DataFrame()
    if j.empty:
        st.caption("Aucune action enregistrée.")
    else:
        j["horodatage"] = pd.to_datetime(j["horodatage"], utc=True).dt.tz_convert("Africa/Abidjan").dt.strftime("%d/%m/%Y %H:%M")
        st.dataframe(j.rename(columns={"horodatage": "Date", "auteur": "Par", "action": "Action", "detail": "Détail"}),
                     hide_index=True, use_container_width=True)
