"""
Point d'entrée de l'application — navigation entre les pages.

Lancement inchangé :
    streamlit run app.py
"""
import streamlit as st

from ui_helpers import inject_css, APP_VERSION, current_access_role
from security_utils import guarded_check, lock_message, secrets_match

st.set_page_config(page_title="Manifestes Grimaldi", page_icon="📦", layout="wide")
inject_css()
st.sidebar.caption(f"Manifestes Grimaldi · v{APP_VERSION}")

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
        "<h2 style='text-align:center;margin-top:3rem'>🔐 Accès sécurisé</h2>"
        "<p style='text-align:center;color:#666'>Application interne — Terra Grimaldi</p>",
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
fiche_page = st.Page(
    "views/fiche_depouillement.py",
    title="Fiche de dépouillement",
    icon="🧾",
)
bl_importer_page = st.Page(
    "views/bl_importer.py",
    title="BL Importer",
    icon="📑",
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

stats_flash_page = st.Page(
    "views/stats_flash.py",
    title="Stats Flash & Reporting",
    icon="📈",
)

activite_page = st.Page(
    "views/activite.py",
    title="Activité du terminal",
    icon="🚢",
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
# "agent"     : Saisie + Reporting + Archives (inchangé depuis le 03/09).
# "analyste"  : tout.
# "direction" : Rapports (Reporting en lecture seule sur la classification,
#               Stats Flash en lecture seule), Archives, Tableau de bord.
_role = current_access_role()

_saisie = [structuration_page, fiche_page, loading_report_page, bl_importer_page]
_compte = [profil_page, avis_page]
_pages_by_role = {
    "agent": {
        "Saisie": _saisie,
        "Rapports": [reporting_page],
        "Données": [archive_page],
        "Compte": _compte,
    },
    "analyste": {
        "Saisie": _saisie,
        "Rapports": [reporting_page, stats_flash_page],
        "Données": [archive_page],
        "Pilotage": [activite_page, dashboard_page],
        "Compte": _compte,
    },
    "direction": {
        "Rapports": [reporting_page, stats_flash_page],
        "Données": [archive_page],
        "Pilotage": [dashboard_page],
        "Compte": _compte,
    },
}
pages = _pages_by_role.get(_role, _pages_by_role["agent"])

pg = st.navigation(pages)
pg.run()
