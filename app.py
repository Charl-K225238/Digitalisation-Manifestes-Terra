"""
Point d'entrée de l'application — navigation entre les pages.

Lancement inchangé :
    streamlit run app.py
"""
import streamlit as st

from ui_helpers import inject_css, APP_VERSION, current_access_role, icon
from security_utils import guarded_check, lock_message, secrets_match

LOGO = "assets/logo_terra.png"
st.set_page_config(page_title="Manifestes Terra", page_icon=LOGO, layout="wide")
inject_css()
st.logo(LOGO, size="large")
st.sidebar.caption(f"Manifestes Terra · v{APP_VERSION}")

# ── Authentification par mot de passe (OBLIGATOIRE) ───────────────────────
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
    title="Reporting",
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

activite_page = st.Page(
    "views/activite.py",
    title="Activité du terminal",
    icon=":material/directions_boat:",
)

# ── Navigation par sections, filtrée par rôle d'accès ─────────────────────
# L'app couvre désormais trois usages : la saisie (pré-masque, masque ISO,
# fiche, BL), la production de rapports aux règles connues, et la
# constitution de données propres pour l'analyse. Les pages sont donc
# regroupées par usage :
#   Saisie   : production quotidienne des agents
#   Rapports : rapports calculés depuis les données (Reporting, Stats Flash)
#   Données  : archives et historique
#   Pilotage : tableau de bord (analyste / direction)
#   Compte   : profil et avis
# Rôles (voir tracking.get_access_role) :
# "agent"     : tout sauf Pilotage (Saisie, Rapports dont Stats Flash, Archives, Compte).
# "analyste"  : tout.
# "direction" : tout, comme l'analyste (DG, directeur d'exploitation, chefs de service).
#               Les fonctions d'administration (gestion des accès, chargement/
#               correction Stats Flash) restent réservées à l'analyste dans les pages.
_role = current_access_role()

_saisie = [structuration_page, fiche_page, loading_report_page, bl_importer_page]
_compte = [profil_page, avis_page]
_pages_by_role = {
    "agent": {
        "Accueil": [accueil_page],
        "Saisie": _saisie,
        "Rapports": [reporting_page, stats_flash_page],
        "Données": [archive_page],
        "Compte": _compte,
    },
    "analyste": {
        "Accueil": [accueil_page],
        "Saisie": _saisie,
        "Rapports": [reporting_page, stats_flash_page],
        "Données": [archive_page],
        "Pilotage": [activite_page, dashboard_page],
        "Compte": _compte,
    },
    "direction": {
        "Accueil": [accueil_page],
        "Saisie": _saisie,
        "Rapports": [reporting_page, stats_flash_page],
        "Données": [archive_page],
        "Pilotage": [activite_page, dashboard_page],
        "Compte": _compte,
    },
}
pages = _pages_by_role.get(_role, _pages_by_role["agent"])

pg = st.navigation(pages)
pg.run()
