"""
Page Profil — identification de l'agent.
L'identité est mémorisée dans st.session_state["identity"] pour toute la session
ET dans st.query_params (URL du navigateur) pour survivre au rechargement de page.

Chaque utilisateur conserve sa propre identité dans son URL de navigateur —
aucun fichier partagé côté serveur n'est lu pour la suggestion par défaut.
"""
import pathlib
import sys

import streamlit as st

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tracking import (
    get_known_agents,
    get_known_services,
    get_known_roles,
    save_user_identity,
    normalize_name,
)
from ui_helpers import combo_with_custom

# ---------------------------------------------------------------------------
# Constantes métier
# ---------------------------------------------------------------------------
SERVICES = ["Reporting", "Opérations", "Planification", "Data"]
ROLES    = ["Agent", "Chef de service", "Chef de la planification", "Analyste Data"]

# ---------------------------------------------------------------------------
# Auto-restauration depuis l'URL (persistance navigateur, isolée par onglet)
# ---------------------------------------------------------------------------
_qp = st.query_params
_qp_name    = _qp.get("id_name", "").strip()
_qp_service = _qp.get("id_service", "").strip()
_qp_role    = _qp.get("id_role", "").strip()

if _qp_name and _qp_service and _qp_role and not st.session_state.get("identity"):
    st.session_state["identity"] = {
        "name":    normalize_name(_qp_name),
        "service": _qp_service,
        "role":    _qp_role,
    }
    st.rerun()

# ---------------------------------------------------------------------------
# En-tête
# ---------------------------------------------------------------------------
st.title("Profil — Identification")
st.caption("Renseignez votre identité une fois. Elle est mémorisée pour toute la session et restaurée automatiquement au rechargement.")

# ---------------------------------------------------------------------------
# Affichage selon l'état de la session
# ---------------------------------------------------------------------------
identity = st.session_state.get("identity")

if identity and not st.session_state.get("changing_identity"):
    # ── Identité déjà confirmée — bannière compacte ──
    st.success(
        f"✅ Connecté : **{identity['name']}** — {identity['service']} / {identity['role']}"
    )
    if st.button("✏️ Modifier"):
        st.session_state["changing_identity"] = True
        st.rerun()
    st.info("📦 Vous pouvez maintenant naviguer vers les autres onglets.")

else:
    # ── Formulaire d'identification ──
    # Suggestion : uniquement depuis les query_params propres au navigateur
    # (pas de load_user_identity() qui lirait un fichier partagé côté serveur)
    _suggested = identity or {}
    _suggested_name = normalize_name(_suggested.get("name", ""))

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
    _ok = bool(agent_normalized) and bool(service_input) and bool(role_input)

    if st.button("✅ Valider mon identité", type="primary", disabled=not _ok):
        # Persistance côté navigateur (URL) — propre à chaque onglet/utilisateur
        st.query_params["id_name"]    = agent_normalized
        st.query_params["id_service"] = service_input
        st.query_params["id_role"]    = role_input
        # Persistance locale (optionnelle, utile en installation locale)
        try:
            save_user_identity(agent_normalized, service_input, role_input)
        except Exception:
            pass
        st.session_state["identity"]          = {
            "name":    agent_normalized,
            "service": service_input,
            "role":    role_input,
        }
        st.session_state["changing_identity"] = False
        st.rerun()

    if not _ok:
        st.info("Complétez votre profil pour accéder aux autres onglets.")
