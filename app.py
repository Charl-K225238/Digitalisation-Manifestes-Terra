"""
Point d'entrée de l'application — navigation entre les pages.

Lancement inchangé :
    streamlit run app.py
"""
import streamlit as st

from ui_helpers import (inject_css, APP_VERSION, icon, accounts_mode, current_account, logout,
                        has_perm)
from security_utils import guarded_check, lock_message, secrets_match

LOGO = "assets/logo_terra.png"
st.set_page_config(page_title="Manifestes Terra", page_icon=LOGO, layout="wide")
inject_css()
st.logo(LOGO, size="large")
st.sidebar.caption(f"Manifestes Terra · v{APP_VERSION}")

# ── Authentification ─────────────────────────────────────────────────────
# Deux modes (secret CONNEXION_PAR_COMPTE) :
#   - comptes (true)  : e-mail + mot de passe personnel, comptes et groupes de
#                       droits gérés par l'IT (page Administration) ;
#   - historique      : mot de passe commun APP_PASSWORD puis choix du nom (Profil).
if accounts_mode():
    import ui_auth
    ui_auth.gate()
    _acc = current_account()
    st.sidebar.caption(f"{_acc['prenom']} {_acc['nom'].title()} · {_acc['groupe']}")
    if st.sidebar.button("Se déconnecter", icon=":material/logout:"):
        logout()
        st.rerun()
else:
    # Refus de démarrer si APP_PASSWORD n'est pas défini : plus aucun mode « ouvert ».
    try:
        _pwd_secret = st.secrets["APP_PASSWORD"]
    except Exception:
        _pwd_secret = ""
    if not _pwd_secret:
        st.error(
            "Configuration incomplète : l'application ne peut pas démarrer sans mot de passe d'accès. "
            "Contactez l'administrateur."
        )
        st.stop()
    if not st.session_state.get("_auth_ok"):
        st.markdown(
            "<div style='display:flex;flex-direction:column;align-items:center;gap:6px;margin:3rem 0 1.5rem'>"
            "<h2 style='margin:0;display:flex;align-items:center;gap:10px'>"
            + icon("lock", 24, "#0B7A2E") + "Manifestes Terra</h2>"
            "<p style='color:#5E5B57;margin:0'>Application interne · Terminal Roulier d'Abidjan</p></div>",
            unsafe_allow_html=True,
        )
        col_c, col_form, col_d = st.columns([1, 2, 1])
        with col_form:
            _pwd_input = st.text_input("Mot de passe", type="password", label_visibility="collapsed",
                                       placeholder="Entrez le mot de passe…")
            _lock_msg = lock_message("app")
            if _lock_msg:
                st.error(_lock_msg)
            if st.button("Accéder", type="primary", use_container_width=True):
                _ok, _msg = guarded_check("app", lambda: secrets_match(_pwd_input, _pwd_secret))
                if _ok:
                    st.session_state["_auth_ok"] = True
                    st.rerun()
                else:
                    st.error(_msg)
        st.stop()

profil_page = st.Page(
    "views/profil.py",
    title="Profil",
    icon=":material/person:",
)
accueil_page = st.Page(
    "views/accueil.py",
    title="Vue d'ensemble",
    icon=":material/home:",
    default=True,
)
structuration_page = st.Page(
    "views/structuration.py",
    title="Pré-Masque",
    icon=":material/note_add:",
)
loading_report_page = st.Page(
    "views/loading_report.py",
    title="MASQUE / TYPE ISO",
    icon=":material/grid_on:",
)
fiche_page = st.Page(
    "views/fiche_depouillement.py",
    title="Fiche de dépouillement",
    icon=":material/fact_check:",
)
bl_importer_page = st.Page(
    "views/bl_importer.py",
    title="BL Importer",
    icon=":material/layers:",
)
reporting_page = st.Page(
    "views/reporting.py",
    title="Liste prévisionnelle / Tableau de classification",
    icon=":material/table_chart:",
)
dashboard_page = st.Page(
    "views/dashboard.py",
    title="Tableau de bord",
    icon=":material/dashboard:",
)
archive_page = st.Page(
    "views/archive.py",
    title="Archives",
    icon=":material/inventory_2:",
)
avis_page = st.Page(
    "views/avis.py",
    title="Avis & Retours",
    icon=":material/chat_bubble:",
)

stats_flash_page = st.Page(
    "views/stats_flash.py",
    title="Stats Flash & Reporting",
    icon=":material/trending_up:",
)

note_volumes_page = st.Page(
    "views/note_volumes.py",
    title="Note volumes mensuels",
    icon=":material/summarize:",
)

activite_page = st.Page(
    "views/activite.py",
    title="Activité du terminal",
    icon=":material/directions_boat:",
)

admin_page = st.Page(
    "views/admin.py",
    title="Utilisateurs et droits",
    icon=":material/admin_panel_settings:",
)

# ── Navigation par sections, filtrée par fonctionnalités accordées ────────
# Une page n'apparaît que si la fonctionnalité correspondante est accordée
# (permissions.py) : groupe de l'utilisateur en mode comptes, ou traduction
# des rôles agent / analyste / direction en mode historique. Les pages
# vérifient aussi elles-mêmes leur droit (require_perm), au cas où.
# Toujours visibles : Vue d'ensemble, Profil, Avis & Retours.
_sections = {
    "Accueil": [(None, accueil_page)],
    "Saisie": [("saisie.premasque", structuration_page), ("saisie.fiche", fiche_page),
               ("saisie.masque_iso", loading_report_page), ("saisie.bl_importer", bl_importer_page),
               ("saisie.reporting", reporting_page)],
    "Rapports": [("rapports.stats_flash", stats_flash_page), ("rapports.note_volumes", note_volumes_page)],
    "Données": [("donnees.archives", archive_page)],
    "Pilotage": [("pilotage.activite", activite_page), ("pilotage.dashboard", dashboard_page)],
    "Compte": [(None, profil_page), (None, avis_page)],
}
if accounts_mode():
    _sections["Administration"] = [("admin.comptes", admin_page)]

pages = {}
for _titre, _items in _sections.items():
    _visibles = [pg_ for code, pg_ in _items if code is None or has_perm(code)]
    if _visibles:
        pages[_titre] = _visibles

pg = st.navigation(pages)
pg.run()
