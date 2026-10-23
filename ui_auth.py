"""
Écrans de connexion du mode comptes (CONNEXION_PAR_COMPTE = true) :
1. Première configuration : tant qu'aucun administrateur n'existe, création du
   premier compte protégée par le code BOOTSTRAP_ADMIN_PASSWORD ;
2. Connexion : e-mail + mot de passe (limitation d'essais par adresse) ;
3. Première connexion : changement obligatoire du mot de passe provisoire.
gate() arrête la page tant que la personne n'est pas pleinement connectée.
"""
import streamlit as st

import comptes as C
import permissions as P
from security_utils import guarded_check, lock_message, secrets_match, log_error
from ui_helpers import current_account, icon, login_account, logout


def _header(sous_titre: str) -> None:
    st.markdown(
        "<div style='display:flex;flex-direction:column;align-items:center;gap:6px;margin:3rem 0 1.5rem'>"
        "<h2 style='margin:0;display:flex;align-items:center;gap:10px'>"
        + icon("lock", 24, "#0B7A2E") + "Manifestes Terra</h2>"
        f"<p style='color:#5E5B57;margin:0'>{sous_titre}</p></div>",
        unsafe_allow_html=True,
    )


def _bootstrap_secret() -> str:
    try:
        return st.secrets.get("BOOTSTRAP_ADMIN_PASSWORD", "") or ""
    except Exception:
        return ""


def _premiere_configuration() -> None:
    _header("Première configuration · création du compte administrateur")
    _, col, _ = st.columns([1, 2, 1])
    with col:
        if not _bootstrap_secret():
            st.error("Le secret BOOTSTRAP_ADMIN_PASSWORD est requis pour créer le premier administrateur. "
                     "Ajoutez-le dans les secrets puis redémarrez l'application.")
            st.stop()
        groupes = [g for g in C.list_groupes() if P.ADMIN_PERM in g["permissions"]]
        st.info("Aucun administrateur n'existe encore. Ce formulaire n'apparaît qu'une fois : "
                "il disparaît dès que le premier compte administrateur est créé.")
        with st.form("bootstrap_admin"):
            code = st.text_input("Code d'amorçage (BOOTSTRAP_ADMIN_PASSWORD)", type="password")
            c1, c2 = st.columns(2)
            nom = c1.text_input("Nom")
            prenom = c2.text_input("Prénom")
            email = st.text_input("E-mail professionnel")
            gid = st.selectbox("Groupe", [g["id"] for g in groupes],
                               format_func=lambda i: next(g["nom"] for g in groupes if g["id"] == i))
            p1 = st.text_input(f"Mot de passe (≥ {C.PWD_MIN} caractères, lettres et chiffres)", type="password")
            p2 = st.text_input("Confirmer le mot de passe", type="password")
            ok = st.form_submit_button("Créer le compte administrateur", type="primary", width="stretch")
        if ok:
            good, msg = guarded_check("bootstrap", lambda: secrets_match(code, _bootstrap_secret()))
            if not good:
                st.error(msg)
                return
            if p1 != p2:
                st.error("Les deux mots de passe ne correspondent pas.")
                return
            try:
                C.create_utilisateur(nom, prenom, email, "", gid, auteur="amorçage", password=p1)
            except C.CompteError as e:
                st.error(str(e))
                return
            st.success("Compte administrateur créé. Connectez-vous avec votre e-mail et votre mot de passe.")
            st.rerun()


def _connexion() -> None:
    _header("Application interne · Terminal Roulier d'Abidjan")
    _, col, _ = st.columns([1, 2, 1])
    with col:
        with st.form("login"):
            email = st.text_input("E-mail professionnel", placeholder="prenom.nom@terra.ci")
            pwd = st.text_input("Mot de passe", type="password")
            ok = st.form_submit_button("Se connecter", type="primary", width="stretch")
        st.caption("Mot de passe oublié ou compte bloqué : contactez l'IT.")
        if not ok:
            return
        key = f"login:{C.normalize_email(email)}"
        if lock_message(key):
            st.error(lock_message(key))
            return
        holder = {}

        def _check():
            holder["acc"] = C.authenticate(email, pwd)
            return holder["acc"] is not None
        good, msg = guarded_check(key, _check)
        if not good:
            st.error(msg.replace("Identifiants incorrects.", "E-mail ou mot de passe incorrect (ou compte désactivé)."))
            return
        login_account(holder["acc"])
        try:  # le nom rejoint la liste des agents connus (archives, tableau de bord)
            from tracking import register_known_agent
            acc = holder["acc"]
            register_known_agent(acc["nom_affiche"], acc["service"] or acc["groupe"], acc["groupe"])
        except Exception:
            pass
        st.rerun()


def _changement_obligatoire(acc: dict) -> None:
    _header(f"Bienvenue {acc['prenom']} · choisissez votre mot de passe personnel")
    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.info("Vous vous êtes connecté avec un mot de passe provisoire. "
                "Choisissez maintenant votre propre mot de passe : il ne sera connu que de vous.")
        with st.form("first_pwd"):
            p1 = st.text_input(f"Nouveau mot de passe (≥ {C.PWD_MIN} caractères, lettres et chiffres)", type="password")
            p2 = st.text_input("Confirmer", type="password")
            ok = st.form_submit_button("Enregistrer et continuer", type="primary", width="stretch")
        if st.button("Annuler et se déconnecter"):
            logout()
            st.rerun()
        if ok:
            if p1 != p2:
                st.error("Les deux mots de passe ne correspondent pas.")
                return
            try:
                C.change_password(acc["id"], None, p1)
            except C.CompteError as e:
                st.error(str(e))
                return
            acc = dict(acc, doit_changer_mdp=False)
            login_account(acc)
            st.rerun()


def gate() -> None:
    """Arrête l'exécution tant que la personne n'est pas connectée avec un mot de passe définitif."""
    acc = current_account()
    if acc:
        if acc.get("doit_changer_mdp"):
            _changement_obligatoire(acc)
            st.stop()
        return
    try:
        C.ensure_initial_groups()
        has_admin = C.admin_exists()
    except Exception as exc:
        log_error("comptes.gate", exc)
        st.error("La base des comptes est inaccessible ou incomplète. Administrateur : vérifiez DATABASE_URL "
                 "et exécutez le script de schéma (02_schema_manifestes.sql), qui crée les tables des comptes.")
        st.stop()
    if not has_admin:
        _premiere_configuration()
    else:
        _connexion()
    st.stop()
