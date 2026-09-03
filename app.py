"""
Point d'entrée de l'application — navigation entre les pages.

Lancement inchangé :
    streamlit run app.py
"""
import streamlit as st

from ui_helpers import inject_css, APP_VERSION, current_access_role

st.set_page_config(page_title="Manifestes Grimaldi", page_icon="📦", layout="wide")
inject_css()
st.sidebar.caption(f"Manifestes Grimaldi · v{APP_VERSION}")

# ── Authentification par mot de passe (optionnelle) ───────────────────────
try:
    _pwd_secret = st.secrets["APP_PASSWORD"]
except Exception:
    _pwd_secret = ""
if _pwd_secret and not st.session_state.get("_auth_ok"):
    st.markdown(
        "<h2 style='text-align:center;margin-top:3rem'>🔐 Accès sécurisé</h2>"
        "<p style='text-align:center;color:#666'>Application interne — Terra Grimaldi</p>",
        unsafe_allow_html=True,
    )
    col_c, col_form, col_d = st.columns([1, 2, 1])
    with col_form:
        _pwd_input = st.text_input("Mot de passe", type="password", label_visibility="collapsed",
                                   placeholder="Entrez le mot de passe…")
        if st.button("Accéder", type="primary", use_container_width=True):
            if _pwd_input == _pwd_secret:
                st.session_state["_auth_ok"] = True
                st.rerun()
            else:
                st.error("Mot de passe incorrect.")
    st.stop()

profil_page = st.Page(
    "views/profil.py",
    title="Profil",
    icon="👤",
    default=True,
)
structuration_page = st.Page(
    "views/structuration.py",
    title="Pré-Masque",
    icon="📦",
)
loading_report_page = st.Page(
    "views/loading_report.py",
    title="MASQUE / TYPE ISO",
    icon="📋",
)
reporting_page = st.Page(
    "views/reporting.py",
    title="Reporting",
    icon="🧮",
)
dashboard_page = st.Page(
    "views/dashboard.py",
    title="Tableau de bord",
    icon="📊",
)
archive_page = st.Page(
    "views/archive.py",
    title="Archives",
    icon="🗂️",
)
avis_page = st.Page(
    "views/avis.py",
    title="Avis & Retours",
    icon="💬",
)

# ── Navigation filtrée par rôle d'accès ────────────────────────────────────
# "agent" (défaut, aucun mot de passe personnel) : pages de saisie uniquement.
# "analyste" : accès complet (dont Reporting — traitement de masse, jugé hors
#              périmètre "direction").
# "direction" (chef de service planification, DEX, DG) : tableau de bord +
#              archives, sans les pages de saisie/traitement au quotidien.
# Un rôle "analyste"/"direction" nécessite un compte protégé par mot de passe
# personnel (page Profil) — voir tracking.get_access_role.
_role = current_access_role()

_pages_by_role = {
    "agent": [profil_page, structuration_page, loading_report_page, avis_page],
    "analyste": [
        profil_page, structuration_page, loading_report_page,
        reporting_page, dashboard_page, archive_page, avis_page,
    ],
    "direction": [profil_page, dashboard_page, archive_page, avis_page],
}
pages = _pages_by_role.get(_role, _pages_by_role["agent"])

pg = st.navigation(pages)
pg.run()
