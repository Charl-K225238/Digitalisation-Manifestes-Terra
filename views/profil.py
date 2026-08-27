"""
Page Profil — identification de l'agent.
L'identité est mémorisée dans st.session_state["identity"] pour toute la session,
dans st.query_params (URL du navigateur) pour survivre à un rechargement (F5),
ET dans le localStorage du navigateur pour survivre à une réouverture de l'app
dans un nouvel onglet ou depuis un favori (l'URL, elle, ne conserve rien dans
ce cas — d'où le recours au localStorage en complément).

Chaque utilisateur conserve sa propre identité dans SON navigateur — aucun
fichier partagé côté serveur n'est lu pour la suggestion par défaut.

Sécurité à deux niveaux :
1. Mot de passe commun (APP_PASSWORD, app.py) — protège l'accès à l'application.
2. Mot de passe personnel (optionnel, défini ici) — empêche un collègue qui
   connaît le mot de passe commun de choisir votre nom dans la liste et
   d'agir sous votre identité. Chaque agent peut l'activer volontairement.
   Un agent protégé n'est JAMAIS mémorisé dans l'URL ni le localStorage : le
   mot de passe personnel doit être ressaisi à chaque nouvelle visite.
"""
import json
import pathlib
import sys

import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tracking import (
    get_known_agents,
    get_known_services,
    get_known_roles,
    save_user_identity,
    normalize_name,
    has_password,
    set_user_password,
    verify_user_password,
    remove_user_password,
    add_known_value,
)
from ui_helpers import combo_with_custom

# ---------------------------------------------------------------------------
# Constantes métier
# ---------------------------------------------------------------------------
SERVICES = ["Reporting", "Opérations", "Planification", "Data"]
ROLES    = ["Agent", "Chef de service", "Chef de la planification", "Analyste Data"]

_LS_KEY = "manifestes_identity"

# ---------------------------------------------------------------------------
# Auto-restauration depuis l'URL (persistance navigateur, isolée par onglet)
# Les agents protégés par un mot de passe personnel ne sont PAS restaurés
# automatiquement : le mot de passe doit être ressaisi à chaque rechargement,
# sinon la protection perdrait tout son sens (URL/localStorage copiés).
# ---------------------------------------------------------------------------
_qp = st.query_params
_qp_name    = _qp.get("id_name", "").strip()
_qp_service = _qp.get("id_service", "").strip()
_qp_role    = _qp.get("id_role", "").strip()
_qp_name_normalized = normalize_name(_qp_name) if _qp_name else ""

if (
    _qp_name and _qp_service and _qp_role
    and not st.session_state.get("identity")
    and not has_password(_qp_name_normalized)
):
    st.session_state["identity"] = {
        "name":    _qp_name_normalized,
        "service": _qp_service,
        "role":    _qp_role,
    }
    st.rerun()

# ---------------------------------------------------------------------------
# Auto-restauration depuis le localStorage — couvre le cas où l'URL n'a plus
# les paramètres (nouvel onglet, favori, app rouverte le lendemain) : sans
# ça, il faudrait se réidentifier à chaque nouvelle visite. Ne se déclenche
# qu'une fois par session pour éviter toute boucle de rechargement, et
# seulement si l'identité n'est pas déjà connue par un autre moyen.
# ---------------------------------------------------------------------------
if (
    not st.session_state.get("identity")
    and not (_qp_name and _qp_service and _qp_role)
    and not st.session_state.get("_ls_restore_attempted")
):
    st.session_state["_ls_restore_attempted"] = True
    components.html(
        f"""
        <script>
        try {{
            const saved = window.parent.localStorage.getItem("{_LS_KEY}");
            if (saved) {{
                const obj = JSON.parse(saved);
                if (obj && obj.name && obj.service && obj.role) {{
                    const url = new URL(window.parent.location.href);
                    url.searchParams.set("id_name", obj.name);
                    url.searchParams.set("id_service", obj.service);
                    url.searchParams.set("id_role", obj.role);
                    window.parent.location.replace(url.toString());
                }}
            }}
        }} catch (e) {{}}
        </script>
        """,
        height=0,
    )

# ---------------------------------------------------------------------------
# En-tête
# ---------------------------------------------------------------------------
st.title("Profil — Identification")
st.caption("Renseignez votre identité une fois. Elle est mémorisée sur cet appareil et restaurée automatiquement à chaque visite.")

# ---------------------------------------------------------------------------
# Affichage selon l'état de la session
# ---------------------------------------------------------------------------
identity = st.session_state.get("identity")

if identity and not st.session_state.get("changing_identity"):
    # ── Identité déjà confirmée — bannière compacte ──
    st.success(
        f"✅ Connecté : **{identity['name']}** — {identity['service']} / {identity['role']}"
    )
    col_mod, col_sec, col_out = st.columns(3)
    with col_mod:
        if st.button("✏️ Modifier"):
            st.session_state["changing_identity"] = True
            st.rerun()
    with col_sec:
        _sec_open = st.toggle("🔒 Sécurité du profil", key="profil_sec_toggle")
    with col_out:
        if st.button("🚪 Oublier ce poste"):
            st.query_params.pop("id_name", None)
            st.query_params.pop("id_service", None)
            st.query_params.pop("id_role", None)
            components.html(
                f"""<script>
                try {{ window.parent.localStorage.removeItem("{_LS_KEY}"); }} catch (e) {{}}
                </script>""",
                height=0,
            )
            st.session_state.pop("identity", None)
            st.session_state["changing_identity"] = False
            st.rerun()

    if _sec_open:
        _agent_norm = identity["name"]
        with st.container(border=True):
            if has_password(_agent_norm):
                st.caption("Un mot de passe personnel protège déjà votre identité.")
                with st.form("profil_change_pwd"):
                    _cur = st.text_input("Mot de passe actuel", type="password")
                    _new = st.text_input("Nouveau mot de passe", type="password")
                    _new2 = st.text_input("Confirmer le nouveau mot de passe", type="password")
                    col_a, col_b = st.columns(2)
                    with col_a:
                        _submit_change = st.form_submit_button("Changer le mot de passe", type="primary")
                    with col_b:
                        _submit_remove = st.form_submit_button("Retirer la protection")

                    if _submit_change:
                        if not verify_user_password(_agent_norm, _cur):
                            st.error("Mot de passe actuel incorrect.")
                        elif not _new or _new != _new2:
                            st.error("Le nouveau mot de passe et sa confirmation ne correspondent pas.")
                        else:
                            set_user_password(_agent_norm, _new)
                            st.success("Mot de passe mis à jour.")
                    if _submit_remove:
                        if not verify_user_password(_agent_norm, _cur):
                            st.error("Mot de passe actuel incorrect.")
                        else:
                            remove_user_password(_agent_norm)
                            st.success("Protection retirée — votre identité n'est plus protégée par un mot de passe personnel.")
                            st.rerun()
            else:
                st.caption(
                    "Optionnel : définissez un mot de passe personnel pour empêcher un "
                    "collègue de sélectionner votre nom et d'agir sous votre identité."
                )
                with st.form("profil_set_pwd"):
                    _new = st.text_input("Nouveau mot de passe", type="password")
                    _new2 = st.text_input("Confirmer le mot de passe", type="password")
                    if st.form_submit_button("🔒 Activer la protection", type="primary"):
                        if not _new or len(_new) < 4:
                            st.error("Le mot de passe doit contenir au moins 4 caractères.")
                        elif _new != _new2:
                            st.error("Les deux mots de passe ne correspondent pas.")
                        else:
                            set_user_password(_agent_norm, _new)
                            st.success("Mot de passe personnel activé.")
                            st.rerun()

    st.info("📦 Vous pouvez maintenant naviguer vers les autres onglets.")

else:
    # ── Formulaire d'identification ──
    # Suggestion : uniquement depuis les query_params propres au navigateur
    # (pas de load_user_identity() qui lirait un fichier partagé côté serveur)
    _suggested = identity or {}
    _suggested_name = normalize_name(_suggested.get("name", "")) or _qp_name_normalized

    known = get_known_agents()
    known_names = [a["agent"] for a in known]

    if known_names:
        _opts = ["— Choisir —"] + known_names + ["✏️ Nouveau nom…"]
        _default_idx = _opts.index(_suggested_name) if _suggested_name in known_names else 0
        _sel = st.selectbox("Nom et prénom", _opts, index=_default_idx, key="profil_name_select")
        if _sel == "✏️ Nouveau nom…":
            agent_input = st.text_input(
                "Saisir votre nom",
                value=_suggested_name if _suggested_name not in known_names else "",
                placeholder="ex : Kouadio Charles",
                key="profil_name_new",
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
            "Nom et prénom",
            value=_suggested_name,
            placeholder="ex : Kouadio Charles",
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
            key=f"profil_svc_{agent_input}",
            help="Choisissez un service existant ou saisissez le vôtre librement.",
        )
    with col_role:
        role_input = combo_with_custom(
            "Rôle", get_known_roles(ROLES), default_value=_role_default,
            key=f"profil_role_{agent_input}",
            help="Choisissez un rôle existant ou saisissez le vôtre librement.",
        )

    agent_normalized = normalize_name(agent_input)
    _protected = bool(agent_normalized) and has_password(agent_normalized)

    if _protected:
        st.warning(
            f"🔒 **{agent_normalized}** est protégé par un mot de passe personnel. "
            "Saisissez-le pour continuer sous cette identité.",
            icon="🔒",
        )
        _personal_pwd = st.text_input("Mot de passe personnel", type="password", key="profil_personal_pwd")
    else:
        _personal_pwd = None

    _ok = bool(agent_normalized) and bool(service_input) and bool(role_input)
    if _protected:
        _ok = _ok and bool(_personal_pwd) and verify_user_password(agent_normalized, _personal_pwd)

    _btn_disabled = not _ok
    if st.button("✅ Valider mon identité", type="primary", disabled=_btn_disabled):
        # Persistance côté navigateur (URL + localStorage) — propre à chaque
        # poste/navigateur. Un agent protégé n'est volontairement mémorisé NI
        # dans l'URL NI dans le localStorage : le mot de passe personnel doit
        # être ressaisi à chaque nouvelle visite.
        if _protected:
            st.query_params.pop("id_name", None)
            st.query_params.pop("id_service", None)
            st.query_params.pop("id_role", None)
        else:
            st.query_params["id_name"]    = agent_normalized
            st.query_params["id_service"] = service_input
            st.query_params["id_role"]    = role_input
            _payload = json.dumps({
                "name": agent_normalized, "service": service_input, "role": role_input,
            })
            components.html(
                f"""<script>
                try {{ window.parent.localStorage.setItem("{_LS_KEY}", JSON.stringify({_payload})); }} catch (e) {{}}
                </script>""",
                height=0,
            )
        # Persistance locale (optionnelle, utile en installation locale)
        try:
            save_user_identity(agent_normalized, service_input, role_input)
        except Exception:
            pass
        # Partage immédiat d'un service/rôle personnalisé avec les autres
        # agents, sans attendre qu'un traitement ou un avis l'utilise.
        try:
            add_known_value("service", service_input)
            add_known_value("role", role_input)
        except Exception:
            pass
        st.session_state["identity"]          = {
            "name":    agent_normalized,
            "service": service_input,
            "role":    role_input,
        }
        st.session_state["changing_identity"] = False
        st.rerun()

    if _protected and agent_normalized and _personal_pwd and not verify_user_password(agent_normalized, _personal_pwd):
        st.error("Mot de passe personnel incorrect.")
    elif not _ok:
        st.info("Complétez votre profil pour accéder aux autres onglets.")
